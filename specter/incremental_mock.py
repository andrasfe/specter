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
# Phase checkpoint for resume
# ---------------------------------------------------------------------------

def _load_checkpoint(output_dir: Path) -> dict:
    """Load phase checkpoint. Returns {} if none exists."""
    path = output_dir / "phase_checkpoint.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
        mock_path = output_dir / data.get("mock_cbl_name", "")
        if mock_path.exists():
            import hashlib
            actual_hash = hashlib.sha256(mock_path.read_bytes()).hexdigest()
            if actual_hash != data.get("mock_cbl_hash", ""):
                log.warning("Checkpoint hash mismatch — starting fresh")
                return {}
        log.info("Resuming from phase %d (%s)",
                 data.get("last_completed_phase_number", -1),
                 data.get("last_completed_phase", "unknown"))
        return data
    except (json.JSONDecodeError, TypeError, KeyError) as exc:
        log.warning("Failed to load checkpoint: %s", exc)
        return {}


def _save_checkpoint(output_dir: Path, phase_name: str, phase_number: int,
                     mock_path: Path) -> None:
    """Save phase checkpoint after successful completion."""
    import hashlib
    path = output_dir / "phase_checkpoint.json"
    data = {
        "last_completed_phase": phase_name,
        "last_completed_phase_number": phase_number,
        "mock_cbl_name": mock_path.name,
        "mock_cbl_hash": hashlib.sha256(mock_path.read_bytes()).hexdigest(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(data, indent=2))


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


_MAX_CONTEXT_LINES = 1000  # max lines sent to LLM per error (was 500)


def _cluster_errors(
    errors: list[tuple[int, str]],
    gap: int = 10,
) -> list[list[tuple[int, str]]]:
    """Group errors within `gap` lines of each other into clusters.

    When 20 errors are all in lines 14620-14630, they're one root cause.
    Treating them as one cluster prevents the LLM from trying each line
    separately with the same doomed fix.
    """
    if not errors:
        return []
    sorted_errs = sorted(errors, key=lambda e: e[0])
    clusters: list[list[tuple[int, str]]] = [[sorted_errs[0]]]
    for err in sorted_errs[1:]:
        if err[0] - clusters[-1][-1][0] <= gap:
            clusters[-1].append(err)
        else:
            clusters.append([err])
    return clusters


def _group_errors_by_type(
    errors: list[tuple[int, str]],
) -> dict[str, list[tuple[int, str]]]:
    """Group errors by their type signature for batch fixing.

    E.g., all "'X' is not defined" errors go into one group so the LLM
    can add all stub definitions at once rather than one at a time.
    """
    groups: dict[str, list[tuple[int, str]]] = {}
    for ln, msg in errors:
        # Normalize: "'FNPLN' is not defined" → "is not defined"
        # Keep the general pattern, drop the specific variable name
        if "is not defined" in msg:
            key = "is not defined"
        elif "syntax error" in msg:
            key = "syntax error"
        elif "PICTURE clause" in msg.upper():
            key = "PICTURE clause"
        elif "duplicate" in msg.lower():
            key = "duplicate"
        else:
            key = msg.split(",")[0].strip()[:40]
        groups.setdefault(key, []).append((ln, msg))
    return groups


def _find_working_storage_range(src_lines: list[str]) -> tuple[int, int] | None:
    """Find the WORKING-STORAGE SECTION line range.

    Returns (start_idx, end_idx) or None if not found.  Used to give the LLM
    a second context chunk so it can add stub definitions in the right place.
    """
    ws_start = None
    ws_end = None
    for i, line in enumerate(src_lines):
        upper = line.upper().strip()
        if upper.startswith("*"):
            continue
        if "WORKING-STORAGE SECTION" in upper:
            ws_start = i
        elif ws_start is not None and any(
            kw in upper for kw in (
                "PROCEDURE DIVISION",
                "LINKAGE SECTION",
                "LOCAL-STORAGE SECTION",
                "REPORT SECTION",
                "SCREEN SECTION",
                "FILE SECTION",
            )
        ):
            ws_end = i
            break
    if ws_start is not None:
        if ws_end is None:
            ws_end = min(ws_start + 500, len(src_lines))
        return ws_start, ws_end
    return None


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
    """Compile, fix errors using LLM — smart batching + memory.

    Key capabilities:
    1. **Batch similar errors**: When 50+ "not defined" errors exist, the
       LLM sees ALL of them and can add all stubs at once.
    2. **Two-chunk context**: For "not defined" errors, the LLM also sees
       WORKING-STORAGE so it knows where to add definitions.
    3. **Failed attempt memory**: The LLM sees what was tried and failed
       with the reason, so it tries fundamentally different approaches.
    4. **Error clustering**: Adjacent errors are one root cause.
    5. **Relaxed verification**: Accept if total error count drops, even
       if the specific targeted line still has an error (line numbers
       shift when stubs are added).

    Returns new resolutions added during this cycle.
    """
    from .llm_coverage import _query_llm_sync, Message
    from .cobol_fix_cache import _parse_llm_fix_response

    new_resolutions: list[Resolution] = []
    source_name = source_path.name
    failed_error_lines: set[int] = set()

    # Memory of failed attempts: (line, error_msg, fix_summary, reason)
    failed_attempts: list[tuple[int, str, str, str]] = []
    # Memory of successful fixes for context
    successful_fixes: list[str] = []

    for attempt in range(max_fix_attempts):
        rc, stderr = _cobc_syntax_check(source_path, copybook_dirs)
        if rc == 0:
            log.info("  Phase %s batch %d: compiles clean", phase, batch)
            return new_resolutions

        errors = _parse_errors(stderr, source_name)
        if not errors:
            log.warning("  Phase %s batch %d: compilation failed (unparseable)", phase, batch)
            return new_resolutions

        # Filter out baseline errors
        if baseline_errors:
            new_errors = [(ln, msg) for ln, msg in errors if msg not in baseline_errors]
            if not new_errors:
                log.info("  Phase %s batch %d: %d errors (all baseline)", phase, batch, len(errors))
                return new_resolutions
        else:
            new_errors = errors

        # Skip errors we already tried and failed
        actionable = [(ln, msg) for ln, msg in new_errors if ln not in failed_error_lines]
        if not actionable:
            log.info("  Phase %s batch %d: %d errors remaining (all attempted)", phase, batch, len(new_errors))
            return new_resolutions

        n_errors = len(new_errors)
        log.info("  Phase %s batch %d attempt %d: %d errors (%d actionable)",
                 phase, batch, attempt + 1, n_errors, len(actionable))

        if not llm_provider:
            for ln, msg in actionable[:5]:
                log.info("    Line %d: %s", ln, msg)
            return new_resolutions

        src_lines = source_path.read_text(errors="replace").splitlines(keepends=True)
        total_lines = len(src_lines)

        # ----- Decide: batch mode or single-error mode -----
        error_groups = _group_errors_by_type(actionable)
        largest_group_type = max(error_groups, key=lambda k: len(error_groups[k]))
        largest_group = error_groups[largest_group_type]
        use_batch_mode = len(largest_group) >= 5

        # Build resolution + failure memory text (shared by both modes)
        current_error_types = {msg.split(",")[0].strip() for _, msg in actionable[:15]}
        relevant_res = [r for r in resolutions + new_resolutions
                        if r.verified and any(et in r.error for et in current_error_types)]
        recent_res = (resolutions + new_resolutions)[-10:]
        seen_keys: set[str] = set()
        res_summaries: list[str] = []
        for r in relevant_res + recent_res:
            key = f"{r.error}:{r.fix}"
            if key not in seen_keys:
                seen_keys.add(key)
                res_summaries.append(r.summary())
            if len(res_summaries) >= 20:
                break

        history_text = ""
        if res_summaries or successful_fixes:
            all_success = [f"- {s}" for s in res_summaries] + [f"- {s}" for s in successful_fixes[-5:]]
            history_text += "WHAT WORKED (apply these patterns):\n" + "\n".join(all_success[:20]) + "\n\n"

        if failed_attempts:
            recent_failed = failed_attempts[-10:]
            failed_lines = []
            for fl, fe, fs, fr in recent_failed:
                failed_lines.append(f"  - Line {fl}: {fe[:60]} | Tried: {fs[:80]} | Result: {fr}")
            history_text += (
                "WHAT FAILED (do NOT repeat — try a different approach):\n"
                + "\n".join(failed_lines) + "\n\n"
            )

        if use_batch_mode:
            # ===== BATCH MODE: Fix all similar errors at once =====
            batch_errors = largest_group[:30]  # Cap at 30 to fit context
            error_list = "\n".join(f"  - Line {ln}: {msg}" for ln, msg in batch_errors)

            log.info("  [%d/%d] BATCH: fixing %d '%s' errors at once",
                     attempt + 1, max_fix_attempts, len(batch_errors), largest_group_type[:40])

            # Build context: error area + optionally WORKING-STORAGE
            # For "not defined" errors, show WS so LLM knows where to add stubs
            context_chunks = []

            # Primary chunk: around the error lines
            err_lines_sorted = sorted(ln for ln, _ in batch_errors)
            first_err = err_lines_sorted[0]
            last_err = err_lines_sorted[-1]
            ctx_start = max(0, first_err - 20)
            ctx_end = min(total_lines, last_err + 20)
            if ctx_end - ctx_start > _MAX_CONTEXT_LINES:
                ctx_end = ctx_start + _MAX_CONTEXT_LINES

            numbered = "\n".join(
                f"{ctx_start + i + 1:5d}: {line.rstrip()}"
                for i, line in enumerate(src_lines[ctx_start:ctx_end])
            )
            context_chunks.append(
                f"Error area (lines {ctx_start+1}-{ctx_end}):\n```cobol\n{numbered}\n```"
            )

            # Secondary chunk: WORKING-STORAGE (for "not defined" errors)
            if "not defined" in largest_group_type:
                ws_range = _find_working_storage_range(src_lines)
                if ws_range:
                    ws_start, ws_end = ws_range
                    # Show last 200 lines of WS (where stubs should be added)
                    ws_show_start = max(ws_start, ws_end - 200)
                    ws_numbered = "\n".join(
                        f"{ws_show_start + i + 1:5d}: {line.rstrip()}"
                        for i, line in enumerate(src_lines[ws_show_start:ws_end])
                    )
                    context_chunks.append(
                        f"\nWORKING-STORAGE tail (lines {ws_show_start+1}-{ws_end}, "
                        f"add new definitions BEFORE the last line shown here):\n"
                        f"```cobol\n{ws_numbered}\n```"
                    )

            all_context = "\n\n".join(context_chunks)

            fix_prompt = (
                f"Fix ALL of these GnuCOBOL compilation errors at once in {source_name} "
                f"({total_lines} lines, phase: {phase}).\n\n"
                f"{history_text}"
                f"Errors to fix ({len(batch_errors)} errors, type: {largest_group_type}):\n"
                f"{error_list}\n\n"
                f"{all_context}\n\n"
                f"IMPORTANT: Fix ALL {len(batch_errors)} errors in a single response.\n"
                f"For 'not defined' errors: add ALL stub definitions together in "
                f"WORKING-STORAGE (before PROCEDURE DIVISION). Use appropriate PIC "
                f"clauses based on how the variables are used in the code.\n"
                f"For syntax errors: look for the root cause BEFORE the error lines.\n\n"
                f"Return ALL fixed/added lines as flat JSON: "
                f"{{\"<line_number>\": \"<content>\"}}\n"
                f"Do NOT wrap in outer keys. Include ALL lines that need changing."
            )

            targeted_lines = set(err_lines_sorted)

        else:
            # ===== SINGLE ERROR MODE: Choose + fix one error =====
            top_errors = actionable[:15]
            error_list = "\n".join(f"  {i+1}. Line {ln}: {msg}" for i, (ln, msg) in enumerate(top_errors))

            choose_prompt = (
                f"You are fixing GnuCOBOL compilation errors in {source_name} "
                f"({total_lines} lines, phase: {phase}).\n\n"
                f"{history_text}"
                f"Current compilation errors ({n_errors} total, showing top 15):\n"
                f"{error_list}\n\n"
                f"Choose ONE error to fix. Respond with JSON:\n"
                f'{{"choose_error": {{"line": <line_number>, "context_start": <start>, "context_end": <end>}}}}\n\n'
                f"Where context_start/context_end define the code range you need to see "
                f"(max {_MAX_CONTEXT_LINES} lines). If many errors cluster, the ROOT CAUSE "
                f"is likely BEFORE the cluster — request context starting well before."
            )

            try:
                response, _ = _query_llm_sync(llm_provider, choose_prompt, llm_model)
            except Exception as exc:
                log.warning("  LLM choose query failed: %s", exc)
                return new_resolutions

            # Parse LLM's choice
            chosen_line = None
            ctx_start = None
            ctx_end = None
            try:
                cleaned = re.sub(r"```\w*\n?", "", response).strip()
                parsed = json.loads(cleaned)
                if "choose_error" in parsed:
                    choice = parsed["choose_error"]
                    chosen_line = int(choice.get("line", 0))
                    ctx_start = max(0, int(choice.get("context_start", chosen_line - 50)) - 1)
                    ctx_end = min(total_lines, int(choice.get("context_end", chosen_line + 50)))
            except (json.JSONDecodeError, TypeError, ValueError, KeyError):
                pass

            if not chosen_line:
                chosen_line = actionable[0][0]
                ctx_start = max(0, chosen_line - 100)
                ctx_end = min(total_lines, chosen_line + 20)

            if ctx_end - ctx_start > _MAX_CONTEXT_LINES:
                ctx_end = ctx_start + _MAX_CONTEXT_LINES

            chosen_msg = next((msg for ln, msg in actionable if ln == chosen_line), "unknown")
            log.info("  [%d/%d] Fixing line %d: %s (context: %d-%d)",
                     attempt + 1, max_fix_attempts, chosen_line, chosen_msg[:60],
                     ctx_start + 1, ctx_end)

            numbered_context = "\n".join(
                f"{ctx_start + i + 1:5d}: {line.rstrip()}"
                for i, line in enumerate(src_lines[ctx_start:ctx_end])
            )

            # Include nearby failed attempts
            nearby_failed = [
                (fl, fe, fs, fr) for fl, fe, fs, fr in failed_attempts
                if abs(fl - chosen_line) < 50
            ]
            nearby_text = ""
            if nearby_failed:
                nf_lines = [f"  - Line {fl}: tried {fs[:100]} → {fr}"
                            for fl, fe, fs, fr in nearby_failed[-5:]]
                nearby_text = (
                    "\nPrevious failed fixes near this area (DO NOT repeat):\n"
                    + "\n".join(nf_lines) + "\n"
                    "Consider: the root cause may be EARLIER in the file.\n\n"
                )

            fix_prompt = (
                f"Fix this GnuCOBOL compilation error:\n"
                f"  Line {chosen_line}: {chosen_msg}\n\n"
                f"{history_text}"
                f"{nearby_text}"
                f"Source context (lines {ctx_start+1}-{ctx_end}):\n"
                f"```cobol\n{numbered_context}\n```\n\n"
                f"Common fixes:\n"
                f"- 'X is not defined': add 01 X PIC X(256). to WORKING-STORAGE\n"
                f"- 'duplicate definition': comment the duplicate\n"
                f"- 'PICTURE clause required': add appropriate PIC clause\n"
                f"- 'unexpected Identifier, expecting SECTION or .': a previous "
                f"line is missing a terminal period or a copybook inlined without "
                f"proper section boundaries — look BEFORE the error\n"
                f"- Don't comment out data definitions other code references\n\n"
                f"Return ONLY fixed lines as flat JSON: "
                f"{{\"<line_number>\": \"<fixed_content>\"}}\n"
                f"Do NOT wrap in outer keys. Only include lines that changed."
            )

            targeted_lines = {chosen_line}

        # ===== Send fix prompt (shared by both modes) =====
        try:
            response2, _ = _query_llm_sync(llm_provider, fix_prompt, llm_model)
        except Exception as exc:
            log.warning("  LLM fix query failed: %s", exc)
            for tl in targeted_lines:
                failed_error_lines.add(tl)
            continue

        # Parse response — allow broader line range for batch mode (stubs
        # may be added in WORKING-STORAGE, far from the error)
        parse_min = 0 if use_batch_mode else (ctx_start if not use_batch_mode else 0)
        parse_max = total_lines + 100  # Allow appending lines
        fixes = _parse_llm_fix_response(response2, parse_min, parse_max)

        if not fixes:
            snippet = response2[:200].replace("\n", "\\n") if response2 else "(empty)"
            log.info("  LLM response not parsed: %s", snippet)
            fix_desc = "batch" if use_batch_mode else f"line {next(iter(targeted_lines))}"
            failed_attempts.append((
                next(iter(targeted_lines)),
                largest_group_type if use_batch_mode else chosen_msg,
                "unparseable response",
                "response not parsed as JSON",
            ))
            for tl in targeted_lines:
                failed_error_lines.add(tl)
            continue

        fix_summary = f"changed {len(fixes)} lines ({sorted(fixes.keys())[:5]}...)" if len(fixes) > 5 else f"changed lines {sorted(fixes.keys())}"

        # ===== Apply, recompile, verify =====
        snapshot = list(src_lines)

        for fix_ln, fix_content in fixes.items():
            idx = fix_ln - 1
            if 0 <= idx < len(src_lines):
                src_lines[idx] = fix_content
            elif fix_ln == len(src_lines) + 1:
                # Appending a new line (e.g., adding stub at end of section)
                src_lines.append(fix_content)

        source_path.write_text("".join(src_lines))

        rc2, stderr2 = _cobc_syntax_check(source_path, copybook_dirs)
        new_error_list = _parse_errors(stderr2, source_name) if rc2 != 0 else []
        new_error_lines_set = {ln for ln, _ in new_error_list}
        new_error_count = len(new_error_list)

        if rc2 == 0:
            fix_lines_dict = {str(k): v for k, v in fixes.items()}
            desc = f"batch {len(targeted_lines)} errors" if use_batch_mode else f"line {next(iter(targeted_lines))}"
            new_resolutions.append(Resolution(
                phase=phase, batch=batch,
                transformation=f"Fix {desc} in phase {phase}",
                error=largest_group_type if use_batch_mode else chosen_msg,
                fix=f"LLM fix ({len(fixes)} lines) — all errors resolved",
                fix_lines=fix_lines_dict,
                verified=True,
                timestamp=datetime.now(timezone.utc).isoformat(),
            ))
            successful_fixes.append(f"Fixed {desc}: {len(fixes)} lines changed → 0 errors")
            log.info("  [%d/%d] ✓ All errors fixed!", attempt + 1, max_fix_attempts)
            return new_resolutions

        # Relaxed verification: accept if error count DECREASED, even if
        # the specific targeted line still has an error (line numbers shift
        # when stubs are added)
        if new_error_count < n_errors:
            fix_lines_dict = {str(k): v for k, v in fixes.items()}
            reduced = n_errors - new_error_count
            desc = f"batch {len(targeted_lines)} errors" if use_batch_mode else f"line {next(iter(targeted_lines))}"
            new_resolutions.append(Resolution(
                phase=phase, batch=batch,
                transformation=f"Fix {desc} in phase {phase}",
                error=largest_group_type if use_batch_mode else chosen_msg,
                fix=f"LLM fix ({len(fixes)} lines) — reduced by {reduced} ({new_error_count} remaining)",
                fix_lines=fix_lines_dict,
                verified=True,
                timestamp=datetime.now(timezone.utc).isoformat(),
            ))
            successful_fixes.append(f"Fixed {desc}: {n_errors}→{new_error_count} errors (-{reduced})")
            log.info("  [%d/%d] ✓ Progress: %d → %d errors (-%d)",
                     attempt + 1, max_fix_attempts, n_errors, new_error_count, reduced)
            # Don't return — keep going to fix remaining errors
            continue

        # Error count same or worse — revert
        source_path.write_text("".join(snapshot))
        src_lines = snapshot  # Reset for next iteration

        revert_reason = f"no improvement ({n_errors}→{new_error_count})"
        failed_attempts.append((
            next(iter(targeted_lines)),
            largest_group_type if use_batch_mode else chosen_msg,
            fix_summary,
            revert_reason,
        ))

        # Mark error cluster as failed
        if use_batch_mode:
            for ln, _ in batch_errors:
                failed_error_lines.add(ln)
            log.info("  [%d/%d] ✗ Reverted batch (%d → %d errors)",
                     attempt + 1, max_fix_attempts, n_errors, new_error_count)
        else:
            clusters = _cluster_errors(actionable)
            for cluster in clusters:
                cluster_lines = {ln for ln, _ in cluster}
                if next(iter(targeted_lines)) in cluster_lines:
                    failed_error_lines.update(cluster_lines)
                    break
            else:
                failed_error_lines.update(targeted_lines)
            log.info("  [%d/%d] ✗ Reverted (%d → %d errors)",
                     attempt + 1, max_fix_attempts, n_errors, new_error_count)

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

    # Load prior resolutions and checkpoint for resume
    resolutions = _load_resolutions(resolution_log_path)
    phase_results: list[PhaseResult] = []
    checkpoint = _load_checkpoint(output_dir)
    start_phase = checkpoint.get("last_completed_phase_number", -1) + 1

    # Working copy of the source — only copy if starting fresh
    mock_path = output_dir / (source_path.stem + ".mock.cbl")
    if start_phase <= 0:
        shutil.copy2(source_path, mock_path)
    elif not mock_path.exists():
        log.warning("Checkpoint exists but mock.cbl missing — starting fresh")
        start_phase = 0
        shutil.copy2(source_path, mock_path)

    total_paragraphs = 0
    branch_meta: dict = {}
    total_branches = 0

    # -----------------------------------------------------------------------
    # Phase 0: Baseline -- compile original and record pre-existing errors
    # -----------------------------------------------------------------------
    baseline_errors: set[str] = set()
    if start_phase <= 0:
        log.info("Phase 0: Baseline compilation check")
        rc, stderr = _cobc_syntax_check(mock_path, copybook_dirs)
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
        _save_checkpoint(output_dir, "baseline", 0, mock_path)
    else:
        log.info("Phase 0: Baseline (skipped — resuming)")

    # -----------------------------------------------------------------------
    # Phase 1: COPY resolution
    # -----------------------------------------------------------------------
    if start_phase <= 1:
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
        _save_checkpoint(output_dir, "copy_resolution", 1, mock_path)
    else:
        log.info("Phase 1: COPY resolution (skipped — resuming)")

    # -----------------------------------------------------------------------
    # Phase 2: Mock infrastructure
    # -----------------------------------------------------------------------
    if start_phase <= 2:
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
        _save_checkpoint(output_dir, "mock_infrastructure", 2, mock_path)
    else:
        log.info("Phase 2: Mock infrastructure (skipped — resuming)")

    # -----------------------------------------------------------------------
    # Phase 3: EXEC replacement (incremental, batch_size blocks at a time)
    # -----------------------------------------------------------------------
    if start_phase <= 3:
        log.info("Phase 3: EXEC replacement (incremental, batch_size=%d)", batch_size)
        from .cobol_mock import _replace_exec_blocks
        batch_num = 0
        while True:
            lines = mock_path.read_text(errors="replace").splitlines(keepends=True)
            new_lines, replaced = _replace_exec_blocks(lines, config, max_count=batch_size)
            if replaced == 0:
                break
            batch_num += 1
            log.info("  Batch %d: replaced %d EXEC blocks", batch_num, replaced)
            snapshot = "".join(lines)  # pre-batch state for revert
            mock_path.write_text("".join(new_lines))

            new_res = _compile_and_fix(
                mock_path, "exec_replacement", batch_num, resolutions,
                copybook_dirs=copybook_dirs,
                llm_provider=llm_provider, llm_model=llm_model,
                baseline_errors=baseline_errors,
            )
            resolutions.extend(new_res)
            _save_resolutions(resolutions, resolution_log_path)

            # Check if batch made things unfixable — revert and retry one-by-one
            rc, stderr = _cobc_syntax_check(mock_path, copybook_dirs)
            if rc != 0:
                errs = _parse_errors(stderr, mock_path.name)
                if len(errs) > 10:
                    log.warning("  Batch %d: %d errors remain, reverting to one-by-one",
                                batch_num, len(errs))
                    mock_path.write_text(snapshot)
                    for _ in range(batch_size):
                        lines = mock_path.read_text(errors="replace").splitlines(keepends=True)
                        one_lines, one_replaced = _replace_exec_blocks(lines, config, max_count=1)
                        if one_replaced == 0:
                            break
                        mock_path.write_text("".join(one_lines))
                        one_res = _compile_and_fix(
                            mock_path, "exec_replacement", batch_num, resolutions,
                            copybook_dirs=copybook_dirs,
                            llm_provider=llm_provider, llm_model=llm_model,
                            baseline_errors=baseline_errors,
                        )
                        resolutions.extend(one_res)
                        _save_resolutions(resolutions, resolution_log_path)

        log.info("  Phase 3 complete (%d batches)", batch_num)
        _save_checkpoint(output_dir, "exec_replacement", 3, mock_path)
    else:
        log.info("Phase 3: EXEC replacement (skipped — resuming)")

    # -----------------------------------------------------------------------
    # Phase 4: I/O replacement (incremental, batch_size blocks at a time)
    # -----------------------------------------------------------------------
    if start_phase <= 4:
        log.info("Phase 4: I/O replacement (incremental, batch_size=%d)", batch_size)
        from .cobol_mock import _replace_io_verbs
        batch_num = 0
        while True:
            lines = mock_path.read_text(errors="replace").splitlines(keepends=True)
            new_lines, replaced = _replace_io_verbs(lines, max_count=batch_size)
            if replaced == 0:
                break
            batch_num += 1
            log.info("  Batch %d: replaced %d I/O verbs", batch_num, replaced)
            snapshot = "".join(lines)
            mock_path.write_text("".join(new_lines))

            new_res = _compile_and_fix(
                mock_path, "io_replacement", batch_num, resolutions,
                copybook_dirs=copybook_dirs,
                llm_provider=llm_provider, llm_model=llm_model,
                baseline_errors=baseline_errors,
            )
            resolutions.extend(new_res)
            _save_resolutions(resolutions, resolution_log_path)

            # Revert + one-by-one if batch causes too many errors
            rc, stderr = _cobc_syntax_check(mock_path, copybook_dirs)
            if rc != 0:
                errs = _parse_errors(stderr, mock_path.name)
                if len(errs) > 10:
                    log.warning("  Batch %d: %d errors remain, reverting to one-by-one",
                                batch_num, len(errs))
                    mock_path.write_text(snapshot)
                    for _ in range(batch_size):
                        lines = mock_path.read_text(errors="replace").splitlines(keepends=True)
                        one_lines, one_replaced = _replace_io_verbs(lines, max_count=1)
                        if one_replaced == 0:
                            break
                        mock_path.write_text("".join(one_lines))
                        one_res = _compile_and_fix(
                            mock_path, "io_replacement", batch_num, resolutions,
                            copybook_dirs=copybook_dirs,
                            llm_provider=llm_provider, llm_model=llm_model,
                            baseline_errors=baseline_errors,
                        )
                        resolutions.extend(one_res)
                        _save_resolutions(resolutions, resolution_log_path)

        log.info("  Phase 4 complete (%d batches)", batch_num)
        _save_checkpoint(output_dir, "io_replacement", 4, mock_path)
    else:
        log.info("Phase 4: I/O replacement (skipped — resuming)")

    # -----------------------------------------------------------------------
    # Phase 5: CALL replacement (incremental, batch_size blocks at a time)
    # -----------------------------------------------------------------------
    if start_phase <= 5:
        log.info("Phase 5: CALL replacement (incremental, batch_size=%d)", batch_size)
        from .cobol_mock import _replace_call_stmts, _replace_accept_stmts
        batch_num = 0
        while True:
            lines = mock_path.read_text(errors="replace").splitlines(keepends=True)
            new_lines, replaced = _replace_call_stmts(lines, max_count=batch_size)
            if replaced == 0:
                break
            batch_num += 1
            log.info("  Batch %d: replaced %d CALL statements", batch_num, replaced)
            snapshot = "".join(lines)
            mock_path.write_text("".join(new_lines))

            new_res = _compile_and_fix(
                mock_path, "call_replacement", batch_num, resolutions,
                copybook_dirs=copybook_dirs,
                llm_provider=llm_provider, llm_model=llm_model,
                baseline_errors=baseline_errors,
            )
            resolutions.extend(new_res)
            _save_resolutions(resolutions, resolution_log_path)

            # Revert + one-by-one if batch causes too many errors
            rc, stderr = _cobc_syntax_check(mock_path, copybook_dirs)
            if rc != 0:
                errs = _parse_errors(stderr, mock_path.name)
                if len(errs) > 10:
                    log.warning("  Batch %d: %d errors remain, reverting to one-by-one",
                                batch_num, len(errs))
                    mock_path.write_text(snapshot)
                    for _ in range(batch_size):
                        lines = mock_path.read_text(errors="replace").splitlines(keepends=True)
                        one_lines, one_replaced = _replace_call_stmts(lines, max_count=1)
                        if one_replaced == 0:
                            break
                        mock_path.write_text("".join(one_lines))
                        one_res = _compile_and_fix(
                            mock_path, "call_replacement", batch_num, resolutions,
                            copybook_dirs=copybook_dirs,
                            llm_provider=llm_provider, llm_model=llm_model,
                            baseline_errors=baseline_errors,
                        )
                        resolutions.extend(one_res)
                        _save_resolutions(resolutions, resolution_log_path)

        # Replace ACCEPT statements (safe, one-shot — just substitutes CONTINUE)
        lines = mock_path.read_text(errors="replace").splitlines(keepends=True)
        lines = _replace_accept_stmts(lines)
        mock_path.write_text("".join(lines))

        log.info("  Phase 5 complete (%d batches)", batch_num)
        _save_checkpoint(output_dir, "call_replacement", 5, mock_path)
    else:
        log.info("Phase 5: CALL replacement (skipped — resuming)")

    # -----------------------------------------------------------------------
    # Phase 6: Paragraph tracing
    # -----------------------------------------------------------------------
    if start_phase <= 6:
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
        _save_checkpoint(output_dir, "paragraph_tracing", 6, mock_path)
    else:
        log.info("Phase 6: Paragraph tracing (skipped — resuming)")

    # -----------------------------------------------------------------------
    # Phase 7: Normalization
    # -----------------------------------------------------------------------
    if start_phase <= 7:
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
        _save_checkpoint(output_dir, "normalization", 7, mock_path)
    else:
        log.info("Phase 7: Normalization (skipped — resuming)")

    # -----------------------------------------------------------------------
    # Phase 8: Auto-stub undefined symbols
    # -----------------------------------------------------------------------
    if start_phase <= 8:
        # Phase 8: Skip auto-stub — the compile-and-fix loop handles
        # undefined symbols via LLM, one at a time with verification.
        # Auto-stub was running cobc up to 48 times and its destructive
        # cleanup phases (_comment_data_blocks, _cleanup_unbalanced_procedure)
        # caused more errors than they fixed.
        log.info("Phase 8: Compile-and-fix (LLM handles undefined symbols)")

        # Recount paragraphs
        lines = mock_path.read_text(errors="replace").splitlines(keepends=True)
        total_paragraphs = sum(
            1 for l in lines
            if "SPECTER-TRACE:" in l and not l.strip().startswith("*")
        )

        new_res = _compile_and_fix(
            mock_path, "compile_fix", 0, resolutions,
            copybook_dirs=copybook_dirs,
            llm_provider=llm_provider, llm_model=llm_model,
            baseline_errors=baseline_errors,
        )
        resolutions.extend(new_res)
        _save_resolutions(resolutions, resolution_log_path)
        _save_checkpoint(output_dir, "compile_fix", 8, mock_path)
    else:
        log.info("Phase 8: Auto-stub (skipped — resuming)")
        # Recount paragraphs from existing mock
        lines = mock_path.read_text(errors="replace").splitlines(keepends=True)
        total_paragraphs = sum(
            1 for l in lines
            if "SPECTER-TRACE:" in l and not l.strip().startswith("*")
        )

    # -----------------------------------------------------------------------
    # Apply GnuCOBOL source fixups on the complete instrumented source
    # -----------------------------------------------------------------------
    if start_phase <= 9:
        # GnuCOBOL fixups disabled — the brute-force VALUES ARE replacement
        # is the only safe one, and it's now handled by the LLM when it sees
        # the compilation error. The multi-line rules (period before level,
        # orphaned VALUE, duplicate removal) caused more problems than they solved.
        log.info("Phase 9: Final compile-and-fix")

        new_res = _compile_and_fix(
            mock_path, "final_fix", 0, resolutions,
            copybook_dirs=copybook_dirs,
            llm_provider=llm_provider, llm_model=llm_model,
        )
        resolutions.extend(new_res)
        _save_resolutions(resolutions, resolution_log_path)
        _save_checkpoint(output_dir, "gnucobol_fixups", 9, mock_path)
    else:
        log.info("GnuCOBOL fixups (skipped — resuming)")

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
