"""Incremental COBOL mock generation with compile-after-each-step.

Replaces the monolithic instrument_cobol() + agent_compile() flow with an
incremental approach: apply transformations in small phases, compile after
each phase, fix errors immediately using LLM + prior resolutions, and
record every resolution for learning.

Key advantages over the old approach:
1. Never more than a handful of errors at a time -- easy for LLM to fix
2. Resolution log accumulates knowledge -- later phases benefit from earlier fixes
3. No cascading failures -- each step is verified before the next
4. Resolution log is reusable -- re-runs apply cached fixes instantly
5. Branch probes are done last, after everything else compiles
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

# Fixed-format COBOL column constants (mirrored from cobol_mock)
_SEQ = "      "        # Cols 1-6: sequence area
_A = "       "         # Cols 1-7: area A start (col 8)
_B = "           "     # Cols 1-11: area B start (col 12)
_CMT = "      *"       # Comment line prefix (col 7 = *)

# Compilation flags shared across all syntax checks and final compilation
_COBC_COMMON_FLAGS = [
    "-std=ibm",
    "-Wno-dialect",
    "-frelax-syntax-checks",
    "-frelax-level-hierarchy",
]

_COBC_SYNTAX_TIMEOUT = 90
_COBC_COMPILE_TIMEOUT = 120


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Resolution:
    """A single error resolution recorded during incremental instrumentation."""

    phase: str
    batch: int
    transformation: str
    error: str
    fix: str
    fix_lines: dict[str, str]  # line_number (str) -> fixed content
    verified: bool
    timestamp: str = ""

    def summary(self) -> str:
        """One-line human-readable summary for LLM context."""
        return (
            f"Phase {self.phase} batch {self.batch}: "
            f"{self.error!r} -> {self.fix}"
        )


@dataclass
class PhaseResult:
    """Outcome of a single instrumentation phase."""

    phase: str
    errors_before: int
    errors_after: int
    resolutions: list[Resolution] = field(default_factory=list)
    skipped: bool = False


# ---------------------------------------------------------------------------
# Compilation helpers
# ---------------------------------------------------------------------------

def _cobc_syntax_check(
    source_path: Path,
    copybook_dirs: list[Path] | None = None,
    timeout: int = _COBC_SYNTAX_TIMEOUT,
) -> tuple[int, str]:
    """Run cobc syntax-only check.

    Returns (return_code, stderr_text).
    """
    cmd = ["cobc", "-fsyntax-only"] + _COBC_COMMON_FLAGS + [str(source_path)]
    if copybook_dirs:
        for d in copybook_dirs:
            cmd.extend(["-I", str(d)])
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
        )
        return result.returncode, (result.stderr or "") + "\n" + (result.stdout or "")
    except subprocess.TimeoutExpired:
        return -1, "Syntax check timed out"
    except FileNotFoundError:
        return -1, "cobc not found on PATH"


def _cobc_compile(
    source_path: Path,
    output_path: Path,
    copybook_dirs: list[Path] | None = None,
    timeout: int = _COBC_COMPILE_TIMEOUT,
) -> tuple[int, str]:
    """Run cobc full compilation.

    Returns (return_code, stderr_text).
    """
    cmd = [
        "cobc", "-x",
    ] + _COBC_COMMON_FLAGS + [
        "-fmax-errors=10000",
        "-o", str(output_path),
        str(source_path),
    ]
    if copybook_dirs:
        for d in copybook_dirs:
            cmd.extend(["-I", str(d)])
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
        )
        return result.returncode, (result.stderr or "") + "\n" + (result.stdout or "")
    except subprocess.TimeoutExpired:
        return -1, "Compilation timed out"
    except FileNotFoundError:
        return -1, "cobc not found on PATH"


def _parse_errors(stderr: str, source_name: str) -> list[tuple[int, str]]:
    """Parse error lines from cobc output.

    Returns list of (lineno, error_message) tuples, deduplicated by line.
    """
    errors: list[tuple[int, str]] = []
    seen: set[int] = set()
    for line in stderr.splitlines():
        if "error:" not in line.lower():
            continue
        m = re.search(rf"{re.escape(source_name)}:(\d+):\s*error:\s*(.*)", line)
        if m:
            lineno = int(m.group(1))
            msg = m.group(2).strip()
            if lineno not in seen:
                errors.append((lineno, msg))
                seen.add(lineno)
    return errors


# ---------------------------------------------------------------------------
# Resolution log persistence
# ---------------------------------------------------------------------------

def _load_resolutions(path: Path) -> list[Resolution]:
    """Load resolution log from JSON file."""
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        resolutions = []
        for entry in data.get("resolutions", []):
            # Ensure fix_lines keys are strings
            fix_lines = {str(k): v for k, v in entry.get("fix_lines", {}).items()}
            resolutions.append(Resolution(
                phase=entry.get("phase", ""),
                batch=entry.get("batch", 0),
                transformation=entry.get("transformation", ""),
                error=entry.get("error", ""),
                fix=entry.get("fix", ""),
                fix_lines=fix_lines,
                verified=entry.get("verified", False),
                timestamp=entry.get("timestamp", ""),
            ))
        log.info("Loaded %d prior resolutions from %s", len(resolutions), path)
        return resolutions
    except (json.JSONDecodeError, TypeError, KeyError) as exc:
        log.warning("Failed to load resolution log: %s", exc)
        return []


def _save_resolutions(resolutions: list[Resolution], path: Path) -> None:
    """Save resolution log to JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "version": 1,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "resolutions": [asdict(r) for r in resolutions],
    }
    path.write_text(json.dumps(data, indent=2, default=str))


# ---------------------------------------------------------------------------
# LLM-driven error fixing
# ---------------------------------------------------------------------------

def _build_fix_prompt(
    errors: list[tuple[int, str]],
    src_lines: list[str],
    source_name: str,
    phase: str,
    resolutions: list[Resolution],
) -> str:
    """Build an LLM prompt for fixing compilation errors.

    Includes all prior resolutions so the LLM learns from previous fixes.
    """
    # Build resolution summary — include RELEVANT resolutions (matching error
    # types) plus most recent ones. Cap at 30 to avoid context overload.
    resolution_text = ""
    if resolutions:
        current_error_types = {msg.split(",")[0].strip() for _, msg in errors}
        # Prioritize: resolutions matching current error types
        relevant = [r for r in resolutions if any(
            et in r.error for et in current_error_types
        )]
        # Add recent resolutions for general context
        recent = resolutions[-15:]
        # Combine, deduplicate, cap at 30
        seen: set[str] = set()
        selected: list[Resolution] = []
        for r in relevant + recent:
            key = f"{r.error}:{r.fix}"
            if key not in seen:
                seen.add(key)
                selected.append(r)
            if len(selected) >= 30:
                break
        summaries = [r.summary() for r in selected]
        resolution_text = (
            "Prior resolutions from this run (apply these proactively):\n"
            + "\n".join(f"- {s}" for s in summaries)
            + "\n\n"
        )

    # Group errors and extract context
    error_lines = sorted(set(e[0] for e in errors))
    first_line = error_lines[0] if error_lines else 1
    last_line = error_lines[-1] if error_lines else len(src_lines)
    ctx_start = max(0, first_line - 101)
    ctx_end = min(len(src_lines), last_line + 20)

    numbered_context = "\n".join(
        f"{ctx_start + i + 1:5d}: {line.rstrip()}"
        for i, line in enumerate(src_lines[ctx_start:ctx_end])
    )

    error_desc = "\n".join(
        f"  Line {ln}: {msg}" for ln, msg in errors
    )

    prompt = (
        "You are fixing GnuCOBOL compilation errors in a COBOL program "
        "being incrementally instrumented for mock execution.\n\n"
        f"Current phase: {phase}\n"
        f"File: {source_name} ({len(src_lines)} lines total)\n"
        f"Total errors: {len(errors)}\n\n"
        f"{resolution_text}"
        f"Current errors to fix:\n{error_desc}\n\n"
        f"Source context (lines {ctx_start + 1}-{ctx_end}):\n"
        f"```cobol\n{numbered_context}\n```\n\n"
        "Common fixes:\n"
        "- 'X is not defined': add '       01 X PIC X(256).' to WORKING-STORAGE\n"
        "- 'duplicate FD/SELECT': comment the duplicate with * in column 7\n"
        "- 'PICTURE clause required': add appropriate PIC clause\n"
        "- 'unexpected ELSE/END-IF': fix IF nesting or add missing IF\n"
        "- VALUES ARE -> VALUE\n"
        "- Missing terminal period on data definition\n"
        "- Don't comment out data definitions that other code references\n\n"
        "Output ONLY the corrected lines as a flat JSON object mapping "
        "line number to fixed content.\n"
        'Example: {"5417": "       10  EXT-K1-WS  PIC 99.", '
        '"5418": "       10  EXT-K2-WS  PIC 99."}\n'
        "Do NOT wrap in outer keys. Do NOT add explanations.\n"
        "Only include lines that changed. Preserve COBOL column formatting "
        "(cols 7-72)."
    )
    return prompt


def _apply_preventive_fixes(
    src_lines: list[str],
    resolutions: list[Resolution],
) -> list[str]:
    """Apply verified fix_lines from prior resolutions to prevent known errors.

    This lets re-runs skip LLM calls for previously resolved issues.
    """
    lines = list(src_lines)
    applied = 0
    for res in resolutions:
        if not res.verified or not res.fix_lines:
            continue
        for ln_str, content in res.fix_lines.items():
            try:
                idx = int(ln_str) - 1
            except (ValueError, TypeError):
                continue
            if 0 <= idx < len(lines):
                lines[idx] = content if content.endswith("\n") else content + "\n"
                applied += 1
    if applied:
        log.debug("Applied %d preventive fix lines from prior resolutions", applied)
    return lines


def _compile_and_fix(
    source_path: Path,
    phase: str,
    batch: int,
    resolutions: list[Resolution],
    copybook_dirs: list[Path] | None = None,
    llm_provider=None,
    llm_model: str | None = None,
    max_fix_attempts: int = 10,
    baseline_errors: set[str] | None = None,
) -> list[Resolution]:
    """Compile, fix any NEW errors using LLM + prior resolutions.

    Returns new resolutions added during this cycle.
    """
    new_resolutions: list[Resolution] = []
    source_name = source_path.name

    for attempt in range(max_fix_attempts):
        rc, stderr = _cobc_syntax_check(source_path, copybook_dirs)
        if rc == 0:
            log.info("  Phase %s batch %d: compiles clean", phase, batch)
            return new_resolutions

        errors = _parse_errors(stderr, source_name)
        if not errors:
            # No parseable errors but compilation failed -- nothing we can do
            log.warning("  Phase %s batch %d: %d errors (unparseable)",
                        phase, batch, rc)
            return new_resolutions

        # Filter out baseline errors (pre-existing issues)
        if baseline_errors:
            new_errors = [
                (ln, msg) for ln, msg in errors
                if msg not in baseline_errors
            ]
            if not new_errors:
                log.info("  Phase %s batch %d: %d errors (all baseline, ignoring)",
                         phase, batch, len(errors))
                return new_resolutions
        else:
            new_errors = errors

        n_errors = len(new_errors)
        log.info("  Phase %s batch %d attempt %d: %d errors",
                 phase, batch, attempt + 1, n_errors)

        if not llm_provider:
            # No LLM -- just report errors and move on
            for ln, msg in new_errors[:5]:
                log.info("    Line %d: %s", ln, msg)
            return new_resolutions

        # Build LLM prompt with all prior resolutions
        src_lines = source_path.read_text(errors="replace").splitlines(keepends=True)
        prompt = _build_fix_prompt(
            new_errors, src_lines, source_name, phase, resolutions + new_resolutions,
        )

        try:
            from .llm_coverage import _query_llm_sync
            response, _ = _query_llm_sync(llm_provider, prompt, llm_model)
        except Exception as exc:
            log.warning("  LLM query failed: %s", exc)
            return new_resolutions

        # Parse response
        from .cobol_fix_cache import _parse_llm_fix_response
        error_lines = sorted(set(e[0] for e in new_errors))
        min_line = max(0, error_lines[0] - 101) if error_lines else 0
        max_line = min(len(src_lines), error_lines[-1] + 20) if error_lines else len(src_lines)
        fixes = _parse_llm_fix_response(response, min_line, max_line)

        if not fixes:
            snippet = response[:200].replace("\n", "\\n") if response else "(empty)"
            log.info("  LLM response not parsed: %s", snippet)
            return new_resolutions

        # Take a snapshot for revert
        snapshot = list(src_lines)

        # Apply fixes
        for fix_ln, fix_content in fixes.items():
            idx = fix_ln - 1
            if 0 <= idx < len(src_lines):
                src_lines[idx] = fix_content

        source_path.write_text("".join(src_lines))

        # Verify fix didn't make things worse
        rc2, stderr2 = _cobc_syntax_check(source_path, copybook_dirs)
        if rc2 == 0:
            # Fixed everything
            fix_lines = {str(k): v for k, v in fixes.items()}
            for ln, msg in new_errors:
                new_resolutions.append(Resolution(
                    phase=phase,
                    batch=batch,
                    transformation=f"Fix {len(new_errors)} errors in phase {phase}",
                    error=msg,
                    fix=f"LLM fix applied ({len(fixes)} lines changed)",
                    fix_lines=fix_lines,
                    verified=True,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                ))
            log.info("  Phase %s batch %d: all errors fixed", phase, batch)
            return new_resolutions

        new_error_count = len(_parse_errors(stderr2, source_name))
        if new_error_count < n_errors:
            # Partial improvement, record and continue
            fix_lines = {str(k): v for k, v in fixes.items()}
            for ln, msg in new_errors:
                new_resolutions.append(Resolution(
                    phase=phase,
                    batch=batch,
                    transformation=f"Partial fix in phase {phase}",
                    error=msg,
                    fix=f"LLM fix ({n_errors} -> {new_error_count} errors)",
                    fix_lines=fix_lines,
                    verified=False,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                ))
            log.info("  Phase %s batch %d: %d -> %d errors (partial fix)",
                     phase, batch, n_errors, new_error_count)
            # Continue loop to try to fix remaining errors
            continue
        else:
            # Fix made things worse or no improvement -- revert
            source_path.write_text("".join(snapshot))
            log.info("  Phase %s batch %d: fix reverted (%d -> %d errors)",
                     phase, batch, n_errors, new_error_count)
            return new_resolutions

    return new_resolutions


# ---------------------------------------------------------------------------
# Phase implementations
# ---------------------------------------------------------------------------

def _phase_copy_resolution(
    lines: list[str],
    copybook_dirs: list[Path],
) -> tuple[list[str], str]:
    """Phase 1: Resolve COPY statements."""
    from .cobol_mock import _resolve_copies
    new_lines, resolved, stubbed, warnings = _resolve_copies(lines, copybook_dirs)
    desc = f"Resolved {resolved} COPY statements ({stubbed} stubbed)"
    if warnings:
        for w in warnings[:5]:
            log.debug("  COPY warning: %s", w)
    return new_lines, desc


def _phase_mock_infrastructure(
    lines: list[str],
    config,
) -> tuple[list[str], str]:
    """Phase 2: Add division identification + mock infrastructure."""
    from .cobol_mock import (
        _find_divisions,
        _add_mock_infrastructure,
        _disable_original_selects,
    )
    divisions = _find_divisions(lines)
    lines = _add_mock_infrastructure(lines, divisions, config)
    lines = _disable_original_selects(lines, config)
    desc = "Added mock infrastructure (FILE-CONTROL, FD, WS entries)"
    return lines, desc


def _phase_exec_replacement(
    lines: list[str],
    config,
) -> tuple[list[str], str]:
    """Phase 3: Replace all EXEC blocks with mock reads."""
    from .cobol_mock import _replace_exec_blocks
    new_lines, count = _replace_exec_blocks(lines, config)
    return new_lines, f"Replaced {count} EXEC blocks"


def _phase_io_replacement(
    lines: list[str],
) -> tuple[list[str], str]:
    """Phase 4: Replace file I/O verbs with mock operations."""
    from .cobol_mock import _replace_io_verbs
    new_lines, count = _replace_io_verbs(lines)
    return new_lines, f"Replaced {count} I/O verbs"


def _phase_call_replacement(
    lines: list[str],
) -> tuple[list[str], str]:
    """Phase 5: Replace CALL statements with mock stubs."""
    from .cobol_mock import _replace_call_stmts, _replace_accept_stmts
    new_lines, count = _replace_call_stmts(lines)
    new_lines = _replace_accept_stmts(new_lines)
    return new_lines, f"Replaced {count} CALL statements"


def _phase_paragraph_tracing(
    lines: list[str],
) -> tuple[list[str], str, int]:
    """Phase 6: Add SPECTER-TRACE and SPECTER-CALL probes."""
    from .cobol_mock import _add_paragraph_tracing
    new_lines, count = _add_paragraph_tracing(lines)
    return new_lines, f"Added {count} paragraph trace probes", count


def _phase_normalization(
    lines: list[str],
    config,
) -> tuple[list[str], str]:
    """Phase 7: Apply safe normalizations for GnuCOBOL compatibility."""
    from .cobol_mock import (
        _convert_linkage,
        _normalize_redefines_targets,
        _fix_procedure_division,
        _add_mock_file_handling,
        _strip_skip_directives,
        _add_common_stubs,
        _normalize_paragraph_ellipsis,
        _sanitize_source_ascii,
        _fix_occurs_depending_on,
        _ensure_sentence_break_before_paragraphs,
    )
    lines = _convert_linkage(lines)
    lines = _normalize_redefines_targets(lines)
    lines = _fix_procedure_division(lines)
    lines = _add_mock_file_handling(lines, config)
    lines = _strip_skip_directives(lines)
    lines = _add_common_stubs(lines, config)
    lines = _normalize_paragraph_ellipsis(lines)
    lines = _sanitize_source_ascii(lines)
    lines = _fix_occurs_depending_on(lines)
    lines = _ensure_sentence_break_before_paragraphs(lines)
    return lines, "Applied normalization transforms"


def _phase_auto_stub(
    lines: list[str],
    allow_hardening_fallback: bool = True,
) -> tuple[list[str], str]:
    """Phase 8: Auto-stub undefined symbols via cobc diagnostics."""
    from .cobol_mock import _auto_stub_undefined_with_cobc
    new_lines = _auto_stub_undefined_with_cobc(
        lines,
        allow_hardening_fallback=allow_hardening_fallback,
    )
    return new_lines, "Auto-stubbed undefined symbols"


def _phase_restore_tracing(
    lines: list[str],
) -> tuple[list[str], str]:
    """Phase 8b: Restore paragraph tracing probes destroyed by auto-stub."""
    from .cobol_mock import _restore_paragraph_tracing
    new_lines = _restore_paragraph_tracing(lines)
    count = sum(
        1 for l in new_lines
        if "SPECTER-TRACE:" in l and not l.strip().startswith("*")
    )
    return new_lines, f"Restored paragraph tracing ({count} probes)"


def _phase_branch_probes(
    source_path: Path,
    llm_provider,
    llm_model: str | None,
    copybook_dirs: list[Path] | None = None,
) -> tuple[dict, int, str]:
    """Phase 9: Insert branch probes one paragraph at a time.

    Returns (branch_meta, total_probes, description).
    """
    if not llm_provider:
        return {}, 0, "Branch probes skipped (no LLM provider)"

    try:
        from .branch_instrumenter import instrument_branches
        probes, paras_done, branch_meta = instrument_branches(
            source_path, llm_provider, llm_model,
        )
        if probes > 0:
            return branch_meta, probes, (
                f"Inserted {probes} branch probes in {paras_done} paragraphs"
            )
        return {}, 0, "No branch probes inserted"
    except Exception as exc:
        log.warning("Branch instrumentation failed: %s", exc)
        return {}, 0, f"Branch probes failed: {exc}"


# ---------------------------------------------------------------------------
# GnuCOBOL source fixups (imported from cobol_executor)
# ---------------------------------------------------------------------------

def _apply_gnucobol_fixups(source_text: str) -> str:
    """Apply IBM-to-GnuCOBOL fixups on the full instrumented source.

    Delegates to the cobol_executor implementation.
    """
    from .cobol_executor import _gnucobol_source_fixups
    return _gnucobol_source_fixups(source_text)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def incremental_instrument(
    source_path: Path,
    copybook_dirs: list[Path],
    output_dir: Path,
    llm_provider=None,
    llm_model: str | None = None,
    batch_size: int = 5,
    resolution_log_path: Path | None = None,
    coverage_mode: bool = False,
    allow_hardening_fallback: bool = True,
    initial_values: dict[str, str] | None = None,
    stop_on_exec_return: bool = True,
    stop_on_exec_xctl: bool = True,
    eib_calen: int = 0,
    eib_aid: str = "SPACES",
) -> tuple[Path, dict, int]:
    """Incrementally instrument COBOL with compile-after-each-step.

    Applies transformations in phases, compiling and fixing errors after
    each phase.  A resolution log accumulates knowledge so later phases
    (and future re-runs) benefit from earlier fixes.

    Args:
        source_path: Path to the COBOL source file.
        copybook_dirs: Directories containing copybooks.
        output_dir: Directory for build artifacts.
        llm_provider: LLM provider instance for error fixing.
        llm_model: Optional model override for the LLM provider.
        batch_size: Number of transformations per batch (for future use).
        resolution_log_path: Path to the resolution log JSON. Defaults to
            ``{output_dir}/resolution_log.json``.
        coverage_mode: If True, configure for deep coverage exploration.
        allow_hardening_fallback: Allow hardening fallback in auto-stub.
        initial_values: Variable name -> value pairs for INIT record injection.
        stop_on_exec_return: If True, EXEC CICS RETURN terminates the program.
        stop_on_exec_xctl: If True, EXEC CICS XCTL terminates the program.
        eib_calen: Initial EIBCALEN value.
        eib_aid: Initial EIBAID value.

    Returns:
        (mock_cbl_path, branch_meta, total_branches) where:
        - mock_cbl_path: Path to the instrumented .mock.cbl file
        - branch_meta: dict mapping branch_id -> {paragraph, type}
        - total_branches: total number of branch probes inserted
    """
    source_path = Path(source_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if resolution_log_path is None:
        resolution_log_path = output_dir / "resolution_log.json"

    # Build MockConfig for phase functions that need it
    from .cobol_mock import MockConfig
    config = MockConfig(
        copybook_dirs=list(copybook_dirs),
        trace_paragraphs=True,
        initial_values=initial_values or {},
        stop_on_exec_return=stop_on_exec_return,
        stop_on_exec_xctl=stop_on_exec_xctl,
        eib_calen=eib_calen,
        eib_aid=eib_aid,
    )

    # Load prior resolutions
    resolutions = _load_resolutions(resolution_log_path)
    phase_results: list[PhaseResult] = []

    # Working copy of the source
    mock_path = output_dir / (source_path.stem + ".mock.cbl")
    shutil.copy2(source_path, mock_path)

    total_paragraphs = 0
    branch_meta: dict = {}
    total_branches = 0

    # -----------------------------------------------------------------------
    # Phase 0: Baseline -- compile original and record pre-existing errors
    # -----------------------------------------------------------------------
    log.info("Phase 0: Baseline compilation check")
    rc, stderr = _cobc_syntax_check(mock_path, copybook_dirs)
    baseline_errors: set[str] = set()
    if rc != 0:
        errors = _parse_errors(stderr, mock_path.name)
        baseline_errors = {msg for _, msg in errors}
        log.info("  Baseline: %d pre-existing errors", len(errors))
    else:
        log.info("  Baseline: compiles clean")
    phase_results.append(PhaseResult(
        phase="baseline", errors_before=len(baseline_errors),
        errors_after=len(baseline_errors),
    ))

    # -----------------------------------------------------------------------
    # Phase 1: COPY resolution
    # -----------------------------------------------------------------------
    log.info("Phase 1: COPY resolution")
    lines = mock_path.read_text(errors="replace").splitlines(keepends=True)
    lines, desc = _phase_copy_resolution(lines, copybook_dirs)
    mock_path.write_text("".join(lines))
    log.info("  %s", desc)

    new_res = _compile_and_fix(
        mock_path, "copy_resolution", 0, resolutions,
        copybook_dirs=copybook_dirs,
        llm_provider=llm_provider, llm_model=llm_model,
        baseline_errors=baseline_errors,
    )
    resolutions.extend(new_res)
    _save_resolutions(resolutions, resolution_log_path)

    # -----------------------------------------------------------------------
    # Phase 2: Mock infrastructure
    # -----------------------------------------------------------------------
    log.info("Phase 2: Mock infrastructure")
    lines = mock_path.read_text(errors="replace").splitlines(keepends=True)
    lines, desc = _phase_mock_infrastructure(lines, config)
    mock_path.write_text("".join(lines))
    log.info("  %s", desc)

    new_res = _compile_and_fix(
        mock_path, "mock_infrastructure", 0, resolutions,
        copybook_dirs=copybook_dirs,
        llm_provider=llm_provider, llm_model=llm_model,
        baseline_errors=baseline_errors,
    )
    resolutions.extend(new_res)
    _save_resolutions(resolutions, resolution_log_path)

    # -----------------------------------------------------------------------
    # Phase 3: EXEC replacement
    # -----------------------------------------------------------------------
    log.info("Phase 3: EXEC replacement")
    lines = mock_path.read_text(errors="replace").splitlines(keepends=True)
    lines, desc = _phase_exec_replacement(lines, config)
    mock_path.write_text("".join(lines))
    log.info("  %s", desc)

    new_res = _compile_and_fix(
        mock_path, "exec_replacement", 0, resolutions,
        copybook_dirs=copybook_dirs,
        llm_provider=llm_provider, llm_model=llm_model,
        baseline_errors=baseline_errors,
    )
    resolutions.extend(new_res)
    _save_resolutions(resolutions, resolution_log_path)

    # -----------------------------------------------------------------------
    # Phase 4: I/O replacement
    # -----------------------------------------------------------------------
    log.info("Phase 4: I/O replacement")
    lines = mock_path.read_text(errors="replace").splitlines(keepends=True)
    lines, desc = _phase_io_replacement(lines)
    mock_path.write_text("".join(lines))
    log.info("  %s", desc)

    new_res = _compile_and_fix(
        mock_path, "io_replacement", 0, resolutions,
        copybook_dirs=copybook_dirs,
        llm_provider=llm_provider, llm_model=llm_model,
        baseline_errors=baseline_errors,
    )
    resolutions.extend(new_res)
    _save_resolutions(resolutions, resolution_log_path)

    # -----------------------------------------------------------------------
    # Phase 5: CALL replacement
    # -----------------------------------------------------------------------
    log.info("Phase 5: CALL replacement")
    lines = mock_path.read_text(errors="replace").splitlines(keepends=True)
    lines, desc = _phase_call_replacement(lines)
    mock_path.write_text("".join(lines))
    log.info("  %s", desc)

    new_res = _compile_and_fix(
        mock_path, "call_replacement", 0, resolutions,
        copybook_dirs=copybook_dirs,
        llm_provider=llm_provider, llm_model=llm_model,
        baseline_errors=baseline_errors,
    )
    resolutions.extend(new_res)
    _save_resolutions(resolutions, resolution_log_path)

    # -----------------------------------------------------------------------
    # Phase 6: Paragraph tracing
    # -----------------------------------------------------------------------
    log.info("Phase 6: Paragraph tracing")
    lines = mock_path.read_text(errors="replace").splitlines(keepends=True)
    lines, desc, total_paragraphs = _phase_paragraph_tracing(lines)
    mock_path.write_text("".join(lines))
    log.info("  %s", desc)

    new_res = _compile_and_fix(
        mock_path, "paragraph_tracing", 0, resolutions,
        copybook_dirs=copybook_dirs,
        llm_provider=llm_provider, llm_model=llm_model,
        baseline_errors=baseline_errors,
    )
    resolutions.extend(new_res)
    _save_resolutions(resolutions, resolution_log_path)

    # -----------------------------------------------------------------------
    # Phase 7: Normalization
    # -----------------------------------------------------------------------
    log.info("Phase 7: Normalization")
    lines = mock_path.read_text(errors="replace").splitlines(keepends=True)
    lines, desc = _phase_normalization(lines, config)
    mock_path.write_text("".join(lines))
    log.info("  %s", desc)

    new_res = _compile_and_fix(
        mock_path, "normalization", 0, resolutions,
        copybook_dirs=copybook_dirs,
        llm_provider=llm_provider, llm_model=llm_model,
        baseline_errors=baseline_errors,
    )
    resolutions.extend(new_res)
    _save_resolutions(resolutions, resolution_log_path)

    # -----------------------------------------------------------------------
    # Phase 8: Auto-stub undefined symbols
    # -----------------------------------------------------------------------
    log.info("Phase 8: Auto-stub undefined symbols")
    lines = mock_path.read_text(errors="replace").splitlines(keepends=True)
    lines, desc = _phase_auto_stub(lines, allow_hardening_fallback)
    mock_path.write_text("".join(lines))
    log.info("  %s", desc)

    # Phase 8b: Restore tracing probes that auto-stub may have destroyed
    lines = mock_path.read_text(errors="replace").splitlines(keepends=True)
    lines, desc_restore = _phase_restore_tracing(lines)
    mock_path.write_text("".join(lines))
    log.info("  %s", desc_restore)

    # Recount paragraphs after restore
    total_paragraphs = sum(
        1 for l in lines
        if "SPECTER-TRACE:" in l and not l.strip().startswith("*")
    )

    new_res = _compile_and_fix(
        mock_path, "auto_stub", 0, resolutions,
        copybook_dirs=copybook_dirs,
        llm_provider=llm_provider, llm_model=llm_model,
        baseline_errors=baseline_errors,
    )
    resolutions.extend(new_res)
    _save_resolutions(resolutions, resolution_log_path)

    # -----------------------------------------------------------------------
    # Apply GnuCOBOL source fixups on the complete instrumented source
    # -----------------------------------------------------------------------
    log.info("Applying GnuCOBOL source fixups")
    source_text = mock_path.read_text(errors="replace")
    source_text = _apply_gnucobol_fixups(source_text)
    mock_path.write_text(source_text)

    # Final fix cycle after GnuCOBOL fixups
    new_res = _compile_and_fix(
        mock_path, "gnucobol_fixups", 0, resolutions,
        copybook_dirs=copybook_dirs,
        llm_provider=llm_provider, llm_model=llm_model,
    )
    resolutions.extend(new_res)
    _save_resolutions(resolutions, resolution_log_path)

    # -----------------------------------------------------------------------
    # Final compilation to executable
    # -----------------------------------------------------------------------
    log.info("Final compilation to executable")
    executable_path = output_dir / source_path.stem
    rc, stderr = _cobc_compile(mock_path, executable_path, copybook_dirs)

    if rc != 0:
        # One more attempt with LLM fixes
        errors = _parse_errors(stderr, mock_path.name)
        log.warning("Final compile failed with %d errors, attempting fixes",
                     len(errors))
        new_res = _compile_and_fix(
            mock_path, "final_compile", 0, resolutions,
            copybook_dirs=copybook_dirs,
            llm_provider=llm_provider, llm_model=llm_model,
            max_fix_attempts=15,
        )
        resolutions.extend(new_res)
        _save_resolutions(resolutions, resolution_log_path)

        # Retry compilation
        rc, stderr = _cobc_compile(mock_path, executable_path, copybook_dirs)

    if rc != 0:
        errors = _parse_errors(stderr, mock_path.name)
        raise RuntimeError(
            f"COBOL compilation failed with {len(errors)} errors after "
            f"incremental instrumentation:\n{stderr[:2000]}"
        )

    log.info("Compiled: %s", executable_path)

    # -----------------------------------------------------------------------
    # Phase 9: Branch probes (post-compilation, LLM-guided)
    # -----------------------------------------------------------------------
    log.info("Phase 9: Branch probes")
    branch_meta, total_branches, desc = _phase_branch_probes(
        mock_path, llm_provider, llm_model, copybook_dirs,
    )
    log.info("  %s", desc)

    if total_branches > 0:
        # Re-compile with branch probes
        rc, stderr = _cobc_compile(mock_path, executable_path, copybook_dirs)
        if rc != 0:
            # Try to fix
            new_res = _compile_and_fix(
                mock_path, "branch_probes", 0, resolutions,
                copybook_dirs=copybook_dirs,
                llm_provider=llm_provider, llm_model=llm_model,
                max_fix_attempts=5,
            )
            resolutions.extend(new_res)
            _save_resolutions(resolutions, resolution_log_path)

            rc, stderr = _cobc_compile(mock_path, executable_path, copybook_dirs)
            if rc != 0:
                # Revert to pre-probe source and re-compile
                log.warning("Branch probe compilation failed, reverting probes")
                source_text = mock_path.read_text(errors="replace")
                # Remove @@B: lines
                clean_lines = []
                for line in source_text.splitlines(keepends=True):
                    if "@@B:" in line and "DISPLAY" in line.upper():
                        clean_lines.append(_CMT + line[7:] if len(line) > 7 else line)
                    else:
                        clean_lines.append(line)
                mock_path.write_text("".join(clean_lines))
                branch_meta = {}
                total_branches = 0
                rc, stderr = _cobc_compile(mock_path, executable_path, copybook_dirs)
                if rc != 0:
                    raise RuntimeError(
                        f"COBOL compilation failed after reverting branch probes:\n"
                        f"{stderr[:2000]}"
                    )

    # Save final resolution log
    _save_resolutions(resolutions, resolution_log_path)

    # Summary
    total_resolutions = len(resolutions)
    log.info(
        "Incremental instrumentation complete: %s "
        "(%d paragraphs, %d branches, %d resolutions)",
        executable_path, total_paragraphs, total_branches, total_resolutions,
    )

    return mock_path, branch_meta, total_branches
