"""Compile-once / run-many COBOL executor with batch parallelism.

Encapsulates the full pipeline: instrument → compile → run N test cases
with mock data, collecting paragraph and branch coverage from each run.
"""

from __future__ import annotations

import logging
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
import re

from .cobol_mock import (
    InstrumentResult,
    MockConfig,
    _format_mock_record,
    generate_init_records,
    generate_mock_data_ordered,
    instrument_cobol,
    parse_call_chain,
    parse_trace,
    parse_variable_snapshots,
    run_cobol,
)

log = logging.getLogger(__name__)

# Regex for extracting SPECTER-MOCK operation keys from instrumented source
_SPECTER_MOCK_RE = re.compile(r"DISPLAY\s+'SPECTER-MOCK:([^']+)'")

# Extended regex that also captures a trailing COBOL variable (dynamic CALL)
_SPECTER_MOCK_DYNAMIC_RE = re.compile(
    r"DISPLAY\s+'SPECTER-MOCK:([^']+)'\s+([A-Z0-9][-A-Z0-9]*)",
    re.IGNORECASE,
)


def _extract_mock_operations(source_text: str) -> list[str]:
    """Extract ordered mock-operation keys from instrumented COBOL source.

    Handles both static ops (``DISPLAY 'SPECTER-MOCK:CALL:RGLCONV'``) and
    dynamic ops (``DISPLAY 'SPECTER-MOCK:CALL:' WS-PARAM``).  For dynamic
    targets, appends the COBOL variable name as the op suffix (matching the
    Python pre-run's stub_log convention, e.g. ``CALL:WS-PARAM``).
    """
    lines = source_text.splitlines()

    ops: list[str] = []
    for line_idx, line in enumerate(lines):
        # Quick pre-filter
        if "SPECTER-MOCK:" not in line:
            continue
        upper = line.upper().strip()
        if upper.startswith("*"):
            continue

        # Try dynamic pattern first (has trailing variable)
        m_dyn = _SPECTER_MOCK_DYNAMIC_RE.search(line)
        if m_dyn:
            op_key = m_dyn.group(1)   # e.g. "CALL:"
            var_name = m_dyn.group(2).upper()  # e.g. "WS-PARAM"
            ops.append(op_key + var_name)
            continue

        # Static pattern
        m_static = _SPECTER_MOCK_RE.search(line)
        if m_static:
            ops.append(m_static.group(1))

    return ops

# Sentinel object used as the *entry* value for padded OPEN/CLOSE records.
# ``generate_mock_data_ordered`` recognises this and emits a bare primary
# record with alpha='00' / num=0  — no SET: payload records — so the mock
# record stream stays aligned.
_OPEN_SUCCESS_SENTINEL = object()


# ---------------------------------------------------------------------------
# IBM → GnuCOBOL source-level fixups
# ---------------------------------------------------------------------------

def _gnucobol_source_fixups(source_text: str) -> str:
    """Apply IBM-to-GnuCOBOL syntax fixups on the full instrumented source.

    This runs on the final source text (after COPY resolution and
    instrumentation) to catch patterns from inlined copybooks that
    bypass the pre-clean phase.

    Every rule here replaces an LLM call. If the LLM fix cache shows
    a pattern being fixed repeatedly, add it here as a regex rule.
    """
    # --- DIAGNOSTIC: count VALUES ARE before/after ---
    before_count = len(re.findall(r"VALUES\s+ARE", source_text, re.IGNORECASE))
    if before_count:
        log.info("GnuCOBOL fixups: found %d 'VALUES ARE' instances to fix", before_count)

    # --- BRUTE FORCE pass first (catches everything, even edge cases) ---
    # Simple case-insensitive replacement on the raw text.
    # This runs BEFORE the line-by-line pass as a safety net.
    source_text = re.sub(r"\bVALUES\s+ARE\b", "VALUE", source_text, flags=re.IGNORECASE)
    source_text = re.sub(r"\bVALUES\s+IS\b", "VALUE", source_text, flags=re.IGNORECASE)

    after_count = len(re.findall(r"VALUES\s+ARE", source_text, re.IGNORECASE))
    if before_count:
        log.info("GnuCOBOL fixups: %d 'VALUES ARE' after brute-force pass (%d removed)",
                 after_count, before_count - after_count)

    # --- Line-by-line pass for remaining fixups ---
    fixed_lines: list[str] = []
    fixes = 0
    in_procedure = False
    for line in source_text.splitlines(keepends=True):
        # Track which division we're in
        code_area = line[6:72] if len(line) > 6 else line
        if "PROCEDURE DIVISION" in code_area.upper() and (len(line) <= 6 or line[6] not in ("*", "/")):
            in_procedure = True

        # Only touch code lines, not comments
        if len(line) > 6 and line[6] not in ("*", "/"):
            orig = line

            # --- VALUE clause fixes (belt-and-suspenders after brute force) ---
            line = re.sub(r"\bVALUES\s+ARE\b", "VALUE", line, flags=re.IGNORECASE)
            line = re.sub(r"\bVALUES\s+IS\b", "VALUE", line, flags=re.IGNORECASE)
            if not in_procedure:
                line = re.sub(r"\bVALUES\b(?!\s+(?:ARE|IS)\b)", "VALUE", line, flags=re.IGNORECASE)

            # --- PIC clause fixes ---
            line = re.sub(r"\bP\.I\.C\.", "PIC", line)

            # --- IBM compiler directives (not supported by GnuCOBOL) ---
            stripped = code_area.strip().upper()
            if stripped in ("EJECT", "EJECT.", "SKIP1", "SKIP1.",
                            "SKIP2", "SKIP2.", "SKIP3", "SKIP3."):
                line = line[:6] + "*" + line[7:]
            elif stripped.startswith("SERVICE RELOAD") or stripped.startswith("SERVICE LABEL"):
                line = line[:6] + "*" + line[7:]
            elif stripped.startswith("READY TRACE") or stripped.startswith("RESET TRACE"):
                line = line[:6] + "*" + line[7:]

            # --- Truncate to 72 columns (sequence numbers in 73-80) ---
            raw = line.rstrip("\n\r")
            if len(raw) > 72:
                line = raw[:72] + "\n"

            if line != orig:
                fixes += 1

        fixed_lines.append(line)

    if fixes:
        log.info("GnuCOBOL source fixups: %d lines fixed (line-by-line pass)", fixes)

    # --- Multi-line pattern fixes ---
    # Only safe, non-destructive multi-line rules are kept here.
    # The "period before next level number" and "orphaned VALUE continuation"
    # rules have been removed — they caused more errors than they fixed on
    # enterprise COBOL sources.  The agent_compile LLM loop handles those
    # edge cases instead.
    multi_fixes = 0

    # 1. Commented-out REDEFINES target: line ends with REDEFINES,
    #    next line is a comment with the target name -> uncomment it.
    #    Pattern:
    #      05  DTE-DATE-E-G-8     REDEFINES
    #      *            DTE-7-INPUT-DATE.
    for i in range(len(fixed_lines) - 1):
        ln = fixed_lines[i]
        if len(ln) > 6 and ln[6] not in ("*", "/"):
            content = ln[7:72].rstrip() if len(ln) > 7 else ln.rstrip()
            if content.upper().endswith("REDEFINES"):
                nxt = fixed_lines[i + 1]
                if len(nxt) > 6 and nxt[6] in ("*", "/"):
                    # Uncomment: the target name is on this commented line
                    fixed_lines[i + 1] = nxt[:6] + " " + nxt[7:]
                    multi_fixes += 1

    # 2. Duplicate consecutive lines -> remove the second copy.
    #    Compare code area only (cols 7-72), ignore trailing whitespace
    #    and sequence numbers in cols 73-80.
    deduped: list[str] = []
    for i, ln in enumerate(fixed_lines):
        if i > 0:
            cur = ln[6:72].rstrip() if len(ln) > 6 else ln.rstrip()
            prev = fixed_lines[i - 1][6:72].rstrip() if len(fixed_lines[i - 1]) > 6 else fixed_lines[i - 1].rstrip()
            if cur and cur == prev:
                multi_fixes += 1
                continue
        deduped.append(ln)
    fixed_lines = deduped

    if multi_fixes:
        log.info("GnuCOBOL source fixups: %d multi-line fixes", multi_fixes)

    return "".join(fixed_lines)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class CobolExecutionContext:
    """Compiled COBOL ready for repeated execution."""

    executable_path: Path
    instrumented_source_path: Path
    branch_meta: dict = field(default_factory=dict)  # branch_id -> {paragraph, condition}
    injectable_vars: list[str] = field(default_factory=list)
    total_paragraphs: int = 0
    total_branches: int = 0
    hardened_mode: bool = False
    coverage_mode: bool = False
    mock_operations: list[str] = field(default_factory=list)  # ordered SPECTER-MOCK op keys
    fd_record_fields: dict[str, str] = field(default_factory=dict)  # FD field -> "alpha"|"numeric"
    # Unified branch registry — source of truth for branch identification
    # across Python (code_generator) and COBOL (branch_instrumenter after
    # Phase 3). When present, downstream consumers should prefer this
    # over ``branch_meta`` (which is the legacy shape derived from the
    # same data). Set by ``prepare_context`` when the caller provides
    # the AST program; ``None`` for older call sites.
    branch_registry: object = None
    # Translation table from a Python-side branch id (the one in
    # ``branch_registry.by_bid``) to the matching COBOL probe
    # ``(cobol_bid, direction)``. For IF branches that's the bid plus
    # ``"T"`` (firing direction); for EVALUATE WHEN arms it's the
    # shared EVALUATE bid plus the arm direction (``"W1"``, ``"WO"``,
    # ...). Built by ``prepare_context`` via content-hash lookup. Empty
    # dict when the caller didn't supply the AST program.
    python_to_cobol_bid: dict = field(default_factory=dict)
    # Maps 88-level condition-name (child, uppercase) to its activating
    # value as a string. Used by ``run_test_case`` to coerce Python
    # bool values in input_state (shorthand for "activate this flag")
    # into the actual value the runtime will MOVE to MOCK-ALPHA-STATUS
    # so the mock's SPECTER-READ-INIT-VARS dispatcher actually fires
    # the ``SET <flag> TO TRUE`` branch. Falls back to Y/N when the
    # variable isn't a known 88-level.
    condition_names_88: dict[str, str] = field(default_factory=dict)

    def translate_py_branch(self, py_branch: str) -> str | None:
        """Translate a ``py:<bid>:<direction>`` label to its COBOL equivalent.

        Returns the COBOL branch label (``"<cbid>:<direction>"``) that covers
        the same source construct, or ``None`` when there is no counterpart
        (e.g. PERFORM UNTIL/VARYING, or an EVALUATE WHEN arm's ``:F`` — the
        "arm not taken" case doesn't correspond to a single COBOL probe
        since it's expressed by some other arm firing).
        """
        if not py_branch.startswith("py:") or not self.python_to_cobol_bid:
            return None
        parts = py_branch[3:].split(":", 1)
        if len(parts) != 2:
            return None
        try:
            py_bid = int(parts[0])
        except ValueError:
            return None
        py_dir = parts[1].upper()
        hit = self.python_to_cobol_bid.get(py_bid)
        if hit is None:
            return None
        cobol_bid, cobol_dir = hit
        # EVALUATE arms store the actual W1/WO direction; only Python :T
        # (arm taken) maps to that probe.
        if cobol_dir and cobol_dir.startswith("W"):
            if py_dir != "T":
                return None
            return f"{cobol_bid}:{cobol_dir}"
        # IF branches use pass-through direction (T ↔ T, F ↔ F).
        return f"{cobol_bid}:{py_dir}"


@dataclass
class CobolTestResult:
    """Result of a single COBOL test execution."""

    paragraphs_hit: list[str] = field(default_factory=list)
    branches_hit: set[str] = field(default_factory=set)
    call_chain: list[tuple[str, str]] = field(default_factory=list)
    variable_snapshots: dict[str, dict[str, str]] = field(default_factory=dict)
    display_output: list[str] = field(default_factory=list)
    return_code: int = 0
    execution_time_ms: float = 0.0
    error: str | None = None


# ---------------------------------------------------------------------------
# Branch coverage parsing
# ---------------------------------------------------------------------------

def parse_branch_coverage(stdout: str) -> set[str]:
    """Extract branch coverage probes from COBOL output.

    Looks for lines matching ``@@B:<id>:<direction>`` and returns
    a set of ``"<id>:<direction>"`` strings.
    """
    branches: set[str] = set()
    for line in stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("@@B:"):
            # Format: @@B:<id>:<direction>
            parts = stripped.split(":")
            if len(parts) >= 3:
                branch_key = f"{parts[1]}:{parts[2]}"
                branches.add(branch_key)
    return branches


# ---------------------------------------------------------------------------
# Context preparation
# ---------------------------------------------------------------------------

def prepare_context(
    cobol_source: str | Path,
    copybook_dirs: list[str | Path] | None = None,
    enable_branch_tracing: bool = True,
    work_dir: str | Path | None = None,
    injectable_vars: list[str] | None = None,
    payload_variables: dict[str, str] | None = None,
    coverage_mode: bool = False,
    allow_hardening_fallback: bool = True,
    llm_provider=None,
    llm_model: str | None = None,
    program=None,  # optional specter.models.Program — builds branch registry
) -> CobolExecutionContext:
    """Instrument and compile a COBOL source for repeated execution.

    Args:
        cobol_source: Path to the COBOL source file.
        copybook_dirs: Directories containing copybooks.
        enable_branch_tracing: Add branch-level probes (@@B:).
        work_dir: Directory for build artifacts. Defaults to temp dir.
        injectable_vars: Variable names to register for INIT record injection.
            The COBOL init-dispatch EVALUATE is generated with WHEN clauses for
            these names so that values can be injected at runtime via mock data.

    Returns:
        CobolExecutionContext ready for run_test_case().

    Raises:
        RuntimeError: If compilation fails.
    """
    cobol_source = Path(cobol_source)
    copybook_paths = [Path(d) for d in (copybook_dirs or [])]

    if work_dir is None:
        # Use a stable directory next to the source so compiled binaries persist
        work_dir = cobol_source.parent / f".specter_build_{cobol_source.stem}"
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    # Check if a compiled binary already exists from a prior run.
    # Skip the entire instrument+compile pipeline if so.
    executable_path = work_dir / cobol_source.stem
    instrumented_path = work_dir / (cobol_source.stem + ".mock.cbl")
    if executable_path.exists() and instrumented_path.exists():
        # Verify the binary is newer than the source
        if executable_path.stat().st_mtime >= cobol_source.stat().st_mtime:
            source_text = instrumented_path.read_text()
            if payload_variables and "SPECTER-APPLY-MOCK-PAYLOAD" not in source_text:
                log.info("Cached compiled COBOL is missing payload helpers; rebuilding")
            else:
                # -- Precompiled SQL patch: EXEC SQL already commented out by
                # DB2 precompiler, active EVALUATE SQLCODE remains without
                # mock reads.  Insert mock reads and recompile if needed.
                if "EVALUATE SQLCODE" in source_text and "SPECTER-MOCK:SQL" not in source_text:
                    from .cobol_mock import _mock_precompiled_sql_evaluates
                    src_lines = source_text.splitlines(keepends=True)
                    patched, n_patched = _mock_precompiled_sql_evaluates(src_lines)
                    if n_patched > 0:
                        log.info("Patching %d precompiled SQL EVALUATE blocks; recompiling",
                                 n_patched)
                        instrumented_path.write_text("".join(patched))
                        import subprocess
                        compile_cmd = [
                            "cobc", "-x",
                            "-std=ibm", "-Wno-dialect",
                            "-frelax-syntax-checks", "-frelax-level-hierarchy",
                            "-o", str(executable_path),
                            str(instrumented_path),
                        ]
                        for cpd in (copybook_dirs or []):
                            compile_cmd.extend(["-I", str(cpd)])
                        cp = subprocess.run(compile_cmd, capture_output=True, text=True)
                        if cp.returncode != 0:
                            log.warning("Recompile after SQL patch failed: %s", cp.stderr[:500])
                            # Restore original and proceed with the existing binary
                            instrumented_path.write_text(source_text)
                        else:
                            source_text = instrumented_path.read_text()
                            log.info("Recompile successful after SQL patch")

                log.info("Using cached compiled COBOL: %s", executable_path)
                hardened_mode = "SPECTER-HARDENED-ENTRY" in source_text
                branch_meta: dict = {}
                total_branches = 0
                total_paragraphs = 0
                # When the caller passed the AST program, rebuild the
                # hash-annotated branch_meta by re-running ``_add_branch_tracing``
                # on a probe-stripped copy of the cached source. This is
                # necessary for the Python↔COBOL branch translation map to
                # be populated on cache hits — otherwise the reconstructed
                # branch_meta below has no ``content_hash`` / ``when_hashes``
                # fields and the hash-based lookup later returns empty.
                hash_rich_meta: dict | None = None
                if enable_branch_tracing and program is not None:
                    try:
                        from .cobol_mock import _add_branch_tracing as _abt
                        import re as _re2
                        _probe_re = _re2.compile(
                            r"\bDISPLAY\s+'@@[BV]:", _re2.IGNORECASE
                        )
                        stripped = [
                            ln + "\n" for ln in source_text.splitlines()
                            if not _probe_re.search(ln)
                        ]
                        _, hash_rich_meta, _ = _abt(stripped)
                    except Exception as exc:  # noqa: BLE001
                        log.warning(
                            "cache: could not rebuild hash-rich branch_meta: %s",
                            exc,
                        )
                        hash_rich_meta = None
                if enable_branch_tracing:
                    # Count @@B: probes and extract conditions from the source
                    import re as _re
                    _para_re = _re.compile(r"^\s{7}([A-Z0-9][A-Z0-9_-]*)\s*\.\s*$", _re.IGNORECASE)
                    _if_re = _re.compile(r"^.{6}\s+IF\s+(.+)", _re.IGNORECASE)
                    _eval_re = _re.compile(r"^.{6}\s+EVALUATE\s+(.+)", _re.IGNORECASE)
                    source_lines = source_text.splitlines()
                    current_para = ""
                    # First pass: map each @@B: line number to bid
                    probe_line_map: dict[int, str] = {}
                    for li, line in enumerate(source_lines):
                        m_para = _para_re.match(line)
                        if m_para:
                            current_para = m_para.group(1).upper()
                        m_probe = _re.search(r"@@B:(\d+):(T|F|W\d+)", line)
                        if m_probe and not (len(line) > 6 and line[6] in ("*", "/")):
                            bid = m_probe.group(1)
                            total_branches += 1
                            if bid not in branch_meta:
                                branch_meta[bid] = {"paragraph": current_para}
                                probe_line_map[li] = bid
                    # Second pass: extract IF/EVALUATE conditions for each probe
                    for probe_li, bid in probe_line_map.items():
                        # Scan backward from the probe to find the IF or EVALUATE
                        for scan_i in range(probe_li - 1, max(probe_li - 30, -1), -1):
                            scan_line = source_lines[scan_i]
                            m_if = _if_re.match(scan_line)
                            if m_if:
                                cond_parts = [m_if.group(1).strip().rstrip(".")]
                                # Gather continuation lines
                                for k in range(scan_i + 1, probe_li):
                                    cl = source_lines[k]
                                    if len(cl) > 6 and cl[6] in ("*", "/"):
                                        continue
                                    ct = cl[7:].strip().upper() if len(cl) > 7 else ""
                                    if not ct or ct.startswith("DISPLAY"):
                                        break
                                    cond_parts.append(ct.rstrip("."))
                                branch_meta[bid]["condition"] = " ".join(cond_parts)
                                branch_meta[bid]["type"] = "IF"
                                break
                            m_eval = _eval_re.match(scan_line)
                            if m_eval:
                                branch_meta[bid]["condition"] = m_eval.group(1).strip().rstrip(".")
                                branch_meta[bid]["type"] = "EVALUATE"
                                break
                            # Stop scanning if we hit another paragraph header
                            if _para_re.match(scan_line):
                                break
                total_paragraphs = source_text.count("SPECTER-TRACE:")
                mock_ops = _extract_mock_operations(source_text)
                from .incremental_mock import _extract_fd_record_fields
                fd_fields = _extract_fd_record_fields(
                    source_text.splitlines(keepends=True)
                )
                # Merge content_hash / when_hashes from the rebuild into
                # the probe-scanned branch_meta so downstream hash lookups
                # work on cache hits.
                if hash_rich_meta:
                    for bid_key, enriched in hash_rich_meta.items():
                        row = branch_meta.get(str(bid_key))
                        if row is None:
                            continue
                        if enriched.get("content_hash"):
                            row["content_hash"] = enriched["content_hash"]
                        if enriched.get("when_hashes"):
                            row["when_hashes"] = dict(enriched["when_hashes"])

                # Build the branch registry + translation map for the
                # cached path too (mirrors the non-cached return below).
                cached_reg = None
                cached_translation: dict[int, tuple[str, str]] = {}
                if program is not None:
                    try:
                        from .branch_registry import build_registry as _build_reg
                        from .persistence_utils import atomic_write_json
                        cached_reg = _build_reg(program)
                        atomic_write_json(
                            work_dir / "branch_registry.json",
                            cached_reg.to_dict(),
                        )
                        cobol_by_hash: dict[str, tuple[str, str]] = {}
                        for cobol_bid, meta in (branch_meta or {}).items():
                            if not isinstance(meta, dict):
                                continue
                            if meta.get("type") == "EVALUATE":
                                for direction, h in (meta.get("when_hashes") or {}).items():
                                    cobol_by_hash[h] = (str(cobol_bid), direction)
                            else:
                                h = meta.get("content_hash")
                                if h:
                                    cobol_by_hash[h] = (str(cobol_bid), "T")
                        matched = 0
                        for e in cached_reg.entries:
                            hit = cobol_by_hash.get(e.content_hash)
                            if hit is not None:
                                cached_translation[e.bid] = hit
                                matched += 1
                        log.info(
                            "branch_registry (cached): translated %d/%d Python "
                            "bids to COBOL probes",
                            matched, len(cached_reg.entries),
                        )
                    except Exception as exc:  # noqa: BLE001
                        log.warning(
                            "branch_registry (cached): build failed: %s", exc,
                        )
                        cached_reg = None
                        cached_translation = {}

                return CobolExecutionContext(
                    executable_path=executable_path,
                    instrumented_source_path=instrumented_path,
                    branch_meta=branch_meta,
                    injectable_vars=list(set(injectable_vars or []) | set(fd_fields.keys())),
                    total_paragraphs=total_paragraphs,
                    total_branches=total_branches,
                    hardened_mode=hardened_mode,
                    coverage_mode=coverage_mode,
                    mock_operations=mock_ops,
                    fd_record_fields=fd_fields,
                    branch_registry=cached_reg,
                    python_to_cobol_bid=cached_translation,
                )

    # No pre-clean — the incremental pipeline handles errors via LLM.
    # Pre-clean regex (column truncation, VALUES ARE, P.I.C.) created as
    # many problems as it solved (double periods, orphaned lines, etc.).
    log.info("Instrumenting and compiling COBOL (work_dir=%s) ...", work_dir)

    # Build initial_values dict for instrumentation — placeholder values
    # just to register the variable names for the EVALUATE dispatch.
    # Actual values come from INIT records in the mock data file at runtime.
    # Use a non-numeric placeholder so the generated COBOL uses
    # MOVE MOCK-ALPHA-STATUS TO <var> (reads from the data file).
    #
    # Exclude most EIB fields — those are set via VALUE clauses in the
    # stubs and faking them corrupts CICS semantics. EIBCALEN and EIBAID
    # are the exception: they are primary branch drivers (first-entry
    # vs re-entry, AID key dispatch) and must be injectable when the
    # program branches on them. If the caller included them in
    # injectable_vars (via `_is_safe_to_inject` / `_is_replay_injectable_var`
    # having cleared them), let them through so SPECTER-READ-INIT-VARS
    # dispatches on their INIT:* records.
    _EIB_FIELDS = {"EIBTRNID", "EIBTIME", "EIBDATE",
                   "EIBTASKN", "EIBTRMID", "EIBCPOSN", "EIBFN", "EIBRCODE",
                   "EIBDS", "EIBREQID", "EIBRSRCE", "EIBSYNC", "EIBFREE",
                   "EIBRECV", "EIBSIG", "EIBCONF", "EIBERR", "EIBERRCD",
                   "EIBSYNRB", "EIBNODAT", "EIBRESP", "EIBRESP2"}
    init_values: dict[str, str] = {}
    if injectable_vars:
        for var in injectable_vars:
            if var.upper() not in _EIB_FIELDS:
                init_values[var] = "__DYNAMIC__"

    # Use incremental instrumentation pipeline: apply transformations one
    # phase at a time, compiling and fixing errors after each phase.
    from .incremental_mock import incremental_instrument
    mock_path, branch_meta, total_branches = incremental_instrument(
        cobol_source,
        copybook_paths,
        work_dir,
        llm_provider=llm_provider,
        llm_model=llm_model,
        coverage_mode=coverage_mode,
        allow_hardening_fallback=allow_hardening_fallback,
        initial_values=init_values,
        payload_variables=payload_variables,
        stop_on_exec_return=not coverage_mode,
        stop_on_exec_xctl=not coverage_mode,
        eib_calen=100 if coverage_mode else 0,
        eib_aid="X'7D'" if coverage_mode else "SPACES",
    )

    instrumented_path = mock_path
    executable_path = work_dir / cobol_source.stem
    source_text = instrumented_path.read_text(errors="replace")
    hardened_mode = "SPECTER-HARDENED-ENTRY" in source_text
    total_paragraphs = sum(
        1 for l in source_text.splitlines()
        if "SPECTER-TRACE:" in l and not l.strip().startswith("*")
    )

    mock_ops = _extract_mock_operations(source_text)

    # Discover FD record fields from the instrumented source so the
    # coverage engine can inject values for file-buffer variables.
    from .incremental_mock import _extract_fd_record_fields
    fd_fields = _extract_fd_record_fields(
        source_text.splitlines(keepends=True)
    )
    log.info("Compiled COBOL: %s (%d paragraphs traced, %d branch probes, %d mock ops, %d FD fields)",
             executable_path, total_paragraphs, total_branches, len(mock_ops), len(fd_fields))

    # Re-derive 88-level condition-name → activating-value map from the
    # same copybook set the instrumenter used, so `run_test_case` can
    # coerce Python bool input_state values (specialist shorthand for
    # "activate this flag") into the activating literal the runtime
    # dispatcher actually checks against.
    condition_names_88: dict[str, str] = {}
    try:
        from .copybook_parser import parse_copybook
        for cpy_dir in copybook_paths or []:
            for cpy_file in Path(cpy_dir).glob("*.[cC][pP][yY]"):
                try:
                    rec = parse_copybook(cpy_file.read_text(errors="replace"))
                    for fld in rec.fields:
                        if fld.values_88:
                            for child_name, child_value in fld.values_88.items():
                                condition_names_88.setdefault(
                                    child_name.upper(), str(child_value),
                                )
                except Exception:  # noqa: BLE001
                    continue
    except Exception:  # noqa: BLE001
        pass

    # Build and persist the unified branch registry when the caller
    # supplied the AST. Downstream consumers (cobol_coverage, swarm,
    # the Phase-3 COBOL instrumenter) can look up bid by content hash
    # or by anchor, eliminating the Python/COBOL ID-mismatch bug. The
    # JSON file next to the build artifacts makes the registry
    # available to out-of-process tooling (CLI inspectors etc.).
    branch_registry = None
    python_to_cobol_bid: dict[int, tuple[str, str]] = {}
    if program is not None:
        try:
            from .branch_registry import build_registry as _build_reg
            from .persistence_utils import atomic_write_json
            branch_registry = _build_reg(program)
            atomic_write_json(
                work_dir / "branch_registry.json",
                branch_registry.to_dict(),
            )
            log.debug(
                "branch_registry: wrote %d entries to %s",
                len(branch_registry.entries),
                work_dir / "branch_registry.json",
            )
            # Build the Python-bid → COBOL-(bid, direction) translation
            # map via content-hash. For IF branches the COBOL tracer
            # stores one hash per bid; for EVALUATE it stores one hash
            # per WHEN arm under ``when_hashes[direction]``.
            cobol_by_hash: dict[str, tuple[str, str]] = {}
            for cobol_bid, meta in (branch_meta or {}).items():
                if not isinstance(meta, dict):
                    continue
                if meta.get("type") == "EVALUATE":
                    for direction, h in (meta.get("when_hashes") or {}).items():
                        cobol_by_hash[h] = (str(cobol_bid), direction)
                else:
                    h = meta.get("content_hash")
                    if h:
                        # IF maps to T direction on fire (false to F).
                        cobol_by_hash[h] = (str(cobol_bid), "T")
            matched = 0
            for e in branch_registry.entries:
                hit = cobol_by_hash.get(e.content_hash)
                if hit is not None:
                    python_to_cobol_bid[e.bid] = hit
                    matched += 1
            log.info(
                "branch_registry: translated %d/%d Python bids to COBOL probes "
                "(%d COBOL-only)",
                matched, len(branch_registry.entries),
                len(cobol_by_hash) - matched,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("branch_registry: build/persist failed: %s", exc)
            branch_registry = None
            python_to_cobol_bid = {}

    return CobolExecutionContext(
        executable_path=executable_path,
        instrumented_source_path=instrumented_path,
        branch_meta=branch_meta,
        # Include FD record fields in injectable_vars — these are added
        # to the SPECTER-READ-INIT-VARS WHEN dispatch during
        # incremental_instrument() (enriched from _extract_fd_record_fields)
        # but are NOT in the original injectable_vars list because they
        # don't appear in the AST's variable_extractor domains.  Without
        # them, the run_test_case INIT filter drops critical records
        # like PROCESS-DATE-DD-FD and DIFF-IND-FD, causing the program
        # to crash on date validation at startup.
        injectable_vars=list(set(injectable_vars or []) | set(fd_fields.keys())),
        total_paragraphs=total_paragraphs,
        total_branches=total_branches,
        hardened_mode=hardened_mode,
        coverage_mode=coverage_mode,
        mock_operations=mock_ops,
        fd_record_fields=fd_fields,
        condition_names_88=condition_names_88,
        branch_registry=branch_registry,
        python_to_cobol_bid=python_to_cobol_bid,
    )


# ---------------------------------------------------------------------------
# Single test case execution
# ---------------------------------------------------------------------------

def run_test_case(
    context: CobolExecutionContext,
    input_state: dict[str, object],
    stub_log: list[tuple[str, list]],
    work_dir: str | Path | None = None,
    timeout: int = 30,
    stub_defaults: dict[str, list] | None = None,
) -> CobolTestResult:
    """Run a single test case against the compiled COBOL program.

    Args:
        context: Compiled COBOL context from prepare_context().
        input_state: Variable values to inject via INIT records.
        stub_log: Execution-ordered stub log from Python pre-run.
        work_dir: Directory for temp data files.
        timeout: Execution timeout in seconds.
        stub_defaults: Optional stub defaults — used to insert success
            records for OPEN/CLOSE operations that the Python pre-run
            didn't consume (because the generated run() function often
            doesn't call the OPEN paragraphs).

    Returns:
        CobolTestResult with coverage and output data.
    """
    start = time.monotonic()

    if work_dir is None:
        work_dir = context.executable_path.parent
    work_dir = Path(work_dir)

    # Build mock data: init records + stub records
    #
    # CRITICAL: Only emit INIT records for variables that have matching
    # WHEN clauses in the COBOL binary's SPECTER-READ-INIT-VARS dispatch.
    # The input_state may contain 1500+ variables (all status/flag/input
    # domains), but the COBOL binary only recognises ~1065 of them.
    # Unrecognised INIT records still loop through the full EVALUATE
    # (1065 WHEN comparisons each) adding massive overhead — 1895 records
    # takes >5 seconds just for INIT processing, causing every baseline
    # test case to timeout before reaching application code.
    # Convert input_state values for INIT records. Two specialist
    # shorthands need translation before they can reach the COBOL
    # runtime meaningfully:
    #
    # 1. Python bool → activating value. ``CDEMO-PGM-REENTER: True``
    #    means "activate this 88-level / set the flag on". Look up the
    #    activating literal from ``context.condition_names_88`` if the
    #    variable is a known 88-level; otherwise fall back to 'Y'/'N'
    #    (the common CICS flag convention).
    #
    # 2. AID constant name → byte value. ``EIBAID: 'DFHENTER'`` is a
    #    specialist naming the AID key by its DFH* constant. The mock
    #    stub defines DFHENTER as VALUE X'7D' (one byte), so MOVEing
    #    the 8-char string "DFHENTER" into EIBAID (PIC X) would only
    #    land 'D' and EVALUATE EIBAID WHEN DFHENTER would never match.
    #    Substitute the single-byte value so the comparison fires.
    _AID_NAME_TO_BYTE: dict[str, str] = {
        "DFHENTER": "\x7D",  "DFHCLEAR": "\x6D",
        "DFHPA1":   "\x6C",  "DFHPA2":   "\x6E",  "DFHPA3":   "\x6B",
        "DFHPF1":   "\xF1",  "DFHPF2":   "\xF2",  "DFHPF3":   "\xF3",
        "DFHPF4":   "\xF4",  "DFHPF5":   "\xF5",  "DFHPF6":   "\xF6",
        "DFHPF7":   "\xF7",  "DFHPF8":   "\xF8",  "DFHPF9":   "\xF9",
        "DFHPF10":  "\x7A",  "DFHPF11":  "\x7B",  "DFHPF12":  "\x7C",
        "DFHPF13":  "\xC1",  "DFHPF14":  "\xC2",  "DFHPF15":  "\xC3",
        "DFHPF16":  "\xC4",  "DFHPF17":  "\xC5",  "DFHPF18":  "\xC6",
        "DFHPF19":  "\xC7",  "DFHPF20":  "\xC8",  "DFHPF21":  "\xC9",
        "DFHPF22":  "\x4A",  "DFHPF23":  "\x4B",  "DFHPF24":  "\x4C",
    }

    def _coerce_for_init(name: str, v: object) -> str:
        if isinstance(v, bool):
            act = context.condition_names_88.get(name.upper())
            if act is not None:
                return str(act) if v else ""
            return "Y" if v else "N"
        if isinstance(v, str):
            _k = v.strip().upper()
            aid = (
                _AID_NAME_TO_BYTE.get(_k)
                or _AID_NAME_TO_BYTE.get("DFH" + _k)
            )
            if aid is not None:
                return aid
        return str(v)

    init_values = {k: _coerce_for_init(k, v) for k, v in input_state.items()
                   if not str(k).startswith("_")}
    if context.injectable_vars:
        injectable_set = set(context.injectable_vars)
        init_values = {k: v for k, v in init_values.items()
                       if k in injectable_set}
    init_data = generate_init_records(init_values) if init_values else ""

    # The COBOL binary reads mock records SEQUENTIALLY — each
    # PERFORM SPECTER-NEXT-MOCK-RECORD reads the next record from
    # the file.  The Python pre-run captures operations in EXECUTION
    # order, which is the order the COBOL binary will consume them.
    #
    # IMPORTANT: We keep stub_log in Python pre-run execution order
    # (NOT source-line order from mock_operations).  Source-line order
    # does NOT match execution order due to PERFORM calls — a utility
    # paragraph late in the source may be PERFORMed early during
    # initialization.  Reordering to source-line order caused severe
    # misalignment where SET: payload records from one operation were
    # consumed by a different operation, cascading into bad file-status
    # values and abends.
    #
    # We also FILTER stub_log to only include operations that exist in
    # the COBOL source's mock_operations.  The Python simulator often
    # generates extra operations (e.g. individual OPEN for a grouped
    # OPEN statement, or per-iteration CLOSE entries) that have no
    # no corresponding DISPLAY 'SPECTER-MOCK:...' in the COBOL binary.
    # Those extra records shift the entire mock data alignment.
    #
    # For operations the Python pre-run didn't cover (executed by
    # COBOL but not the simulator), generous padding records at the
    # end ensure the binary never hits EOF.  These padding records
    # have alpha='00' and no SET: payloads, so they safely satisfy
    # any file-status or return-code check.
    if context.mock_operations and stub_log:
        mock_op_set = set(context.mock_operations)
        filtered_log: list[tuple[str, list]] = []
        dropped = 0
        for op_key, entry in stub_log:
            if op_key in mock_op_set:
                filtered_log.append((op_key, entry))
            else:
                dropped += 1
        if dropped:
            log.debug(
                "Mock data: filtered %d Python-only stub entries "
                "(kept %d entries matching %d COBOL ops)",
                dropped, len(filtered_log), len(mock_op_set),
            )
        # Keep stubs in Python execution order (closest to COBOL order).
        # All entries are emitted as single primary records (no SET:
        # payloads).  The COBOL mock infrastructure defaults status
        # variables before SPECTER-APPLY-MOCK-PAYLOAD, so SET: records
        # are redundant for baseline values.  Eliminating multi-record
        # entries prevents APPLY-MOCK-PAYLOAD read-ahead from consuming
        # records meant for subsequent operations when uncovered mock
        # ops shift the alignment by one or more positions.
        stub_log = filtered_log
    elif stub_log:
        pass  # no mock_operations available — keep stub_log as-is

    # Generate mock data — every entry becomes a single primary record
    # (no SET: payload records).  This ensures each mock operation
    # consumes exactly one record from the stream, preventing the
    # cascading misalignment that occurs when uncovered COBOL operations
    # shift the stream position and cause APPLY-MOCK-PAYLOAD to consume
    # SET: records meant for completely different operations.
    #
    # For entries with payloads, the primary alpha is extracted from the
    # last pair value (matching _encode_mock_entry convention).  Status
    # variables are set via INIT records and/or the COBOL code's own
    # MOVE defaults before SPECTER-APPLY-MOCK-PAYLOAD, so omitting SET:
    # records is safe for baseline coverage.
    if stub_log:
        records: list[str] = []
        for op_key, entry in stub_log:
            if entry is _OPEN_SUCCESS_SENTINEL or entry is None:
                records.append(_format_mock_record(op_key, "00", 0))
            elif isinstance(entry, list) and entry:
                # Extract alpha from the first pair (same as _encode_mock_entry
                # — file-status-leading stubs must route the status literal
                # into the primary record's MOCK-ALPHA-STATUS, not a later
                # side-effect value).
                first_pair = entry[0]
                if isinstance(first_pair, (list, tuple)) and len(first_pair) == 2:
                    alpha = str(first_pair[1])
                else:
                    alpha = "00"
                try:
                    num = int(alpha)
                except (ValueError, TypeError):
                    num = 0
                records.append(_format_mock_record(op_key, alpha, num))
            else:
                records.append(_format_mock_record(op_key, "00", 0))

        # SQL cursor termination: after each run of SQL-FETCH records,
        # inject a PAIRED FETCH record with SQLCODE=100 so cursor loops
        # exit cleanly.  Each COBOL mock operation consumes 2 records:
        # 1 primary (NEXT-MOCK-RECORD) + 1 lookahead (APPLY-MOCK-PAYLOAD).
        # SQLCODE is set from the lookahead's MOCK-NUM-STATUS, so we need
        # 2 records with num=100: one consumed as primary, one as lookahead.
        patched: list[str] = []
        for i, rec in enumerate(records):
            patched.append(rec)
            if stub_log[i][0].upper().startswith("SQL-FETCH"):
                # Check if next entry is NOT a FETCH (end of cursor loop)
                next_is_fetch = (
                    i + 1 < len(stub_log)
                    and stub_log[i + 1][0].upper().startswith("SQL-FETCH")
                )
                if not next_is_fetch:
                    # Inject paired EOF FETCH: primary + lookahead both 100
                    eof_rec = _format_mock_record("SQL-FETCH", "00", 100)
                    patched.append(eof_rec)
                    patched.append(eof_rec)
        records = patched

        stub_data = "\n".join(records) + "\n" if records else "\n"
    else:
        stub_data = ""

    # In coverage mode (RETURN/XCTL don't terminate), the COBOL program
    # consumes more mock records than the Python pre-run produces.
    # Pad with extra success records so the COBOL doesn't hit EOF early.
    # Use enough padding to cover operations the Python pre-run missed
    # (e.g. utility paragraphs, report writer I/O, and extra operations
    # reached via coverage-mode fall-through).
    #
    # Padding uses all '00' (success) primary records.  Older '10' (EOF)
    # padding records caused hard GOBACKs on programs with strict
    # file-status checks (e.g. IF FILE-STATUS NOT EQUAL '00' AND '04'
    # AND '05' → U-FILE-EXCEPTION → GOBACK), terminating the entire
    # program instead of just the current READ loop.
    #
    # To break READ loops cleanly, every Nth primary record is followed
    # by SET: payload records for FD fields whose names indicate loop-
    # control (IND, FLAG, END-OF, MORE, CUT-OFF).  APPLY-MOCK-PAYLOAD
    # consumes these SET: records and populates the FD record buffer
    # with values that differ from the loop-continuation defaults,
    # causing the COBOL loop-exit checks to fire naturally.
    pad_data = ""
    if context.coverage_mode:
        n_mock_ops = len(context.mock_operations) if context.mock_operations else 0
        # Generous padding: at least 60 records, or 2x the known mock ops.
        # Keep padding modest so SQL cursor FETCH loops hit mock-EOF
        # quickly (mock-EOF sets SQLCODE=100 for FETCH, terminating
        # cursor loops naturally).  The SET: loop-break records provide
        # control-flag variation for READ loops.
        pad_count = max(60, n_mock_ops * 2)
        ok_record = f"{'CICS':<30}{'00':<20}{'0':>9}{' ' * 21}"[:80]

        # Build SET: records for loop-control FD fields.
        # These are injected after every LOOP_BREAK_INTERVAL-th primary
        # record so READ loops inside the program encounter changed FD
        # buffers and hit their exit conditions.
        _LOOP_BREAK_INTERVAL = 5  # inject SET: after every 5th primary
        loop_break_phase_a: list[str] = []
        loop_break_phase_b: list[str] = []
        if context.fd_record_fields:
            _LOOP_CTL = {"IND", "FLAG", "END-OF", "MORE", "CUT-OFF", "CUTOFF"}
            # Only alpha fields whose names match loop-control keywords
            # are treated as loop flags.  Numeric fields that happen to
            # contain these keywords (e.g. a COMP-3 date field whose name
            # includes "CUTOFF") must NOT be treated as loop flags —
            # setting them to 1 corrupts packed-decimal values.
            loop_ctl_fields: set[str] = set()
            for fname, fkind in sorted(context.fd_record_fields.items()):
                fu = fname.upper()
                if (fkind != "numeric"
                        and any(kw in fu for kw in _LOOP_CTL)):
                    loop_ctl_fields.add(fu)
                    padded_name = f"{fname.upper()[:26]:<26}"
                    # Alpha loop-control: Phase A = continuation ('0'),
                    # Phase B = termination ('1')
                    loop_break_phase_a.append(
                        _format_mock_record(f"SET:{padded_name}", "0", 0))
                    loop_break_phase_b.append(
                        _format_mock_record(f"SET:{padded_name}", "1", 1))
            # Also zero-initialize ALL remaining FD fields so mock READs
            # leave predictable buffer contents.  Without this, numeric
            # COMP-3 / PIC 9 fields contain binary garbage that causes
            # fatal comparison failures at runtime.
            #
            # This adds ~648 SET: records per block (100 blocks → ~65K
            # records) but the COBOL binary handles the volume fine
            # because APPLY-MOCK-PAYLOAD reads them sequentially
            # and SET: dispatches are fast WHEN jumps.
            for fname, fkind in sorted(context.fd_record_fields.items()):
                fu = fname.upper()
                if fu in loop_ctl_fields:
                    continue  # already handled above
                padded_name = f"{fname.upper()[:26]:<26}"
                # File-status fields are PIC X(02) and must be '00' for
                # success — a single '0' becomes '0 ' which fails the
                # typical ``IF FILE-STATUS-xxx EQUAL '00'`` check and
                # sends the program into U-FILE-EXCEPTION → GOBACK.
                if "FILE-STATUS" in fu or fu.startswith("FS-"):
                    zero_rec = _format_mock_record(
                        f"SET:{padded_name}", "00", 0)
                else:
                    zero_rec = _format_mock_record(
                        f"SET:{padded_name}", "0", 0)
                loop_break_phase_a.append(zero_rec)
                loop_break_phase_b.append(zero_rec)

        pad_lines: list[str] = []
        # Phase A occupies the first 40% of padding (loop-entry values),
        # Phase B occupies the remaining 60% (loop-termination values).
        # A moderate Phase A gives the program enough success
        # records to enter processing loops and execute business
        # paragraphs, then Phase B signals loop termination via
        # changed indicators.
        phase_switch = int(pad_count * 0.40)
        for i in range(pad_count):
            pad_lines.append(ok_record)
            if (i + 1) % _LOOP_BREAK_INTERVAL == 0:
                if i < phase_switch and loop_break_phase_a:
                    pad_lines.extend(loop_break_phase_a)
                elif loop_break_phase_b:
                    pad_lines.extend(loop_break_phase_b)
        pad_data = "\n".join(pad_lines) + "\n"

    # Concatenate: init records first, then stub records (now in COBOL
    # execution order with defaults for missing ops), then padding.
    # CRITICAL: Do NOT use "\n".join() — each part may or may not end
    # with a newline.  An extra newline between parts creates a BLANK
    # LINE record in the LINE SEQUENTIAL file.  The INIT loop exits on
    # the first non-INIT record, and a blank line (80 spaces) is not
    # 'INIT:'.  This shifts every subsequent mock operation by one
    # record, causing cascading misalignment and early crashes.
    parts = [p for p in [init_data, stub_data, pad_data] if p]
    # Ensure each part ends with exactly one newline before concatenation
    mock_data = "".join(p if p.endswith("\n") else p + "\n" for p in parts) if parts else "\n"

    # Write temp data file
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".dat", delete=False, dir=str(work_dir),
    ) as f:
        f.write(mock_data)
        dat_path = Path(f.name)

    try:
        rc, stdout, stderr = run_cobol(
            context.executable_path, dat_path, timeout=timeout,
        )
    finally:
        dat_path.unlink(missing_ok=True)

    elapsed_ms = (time.monotonic() - start) * 1000

    if rc == -1 and not (stdout or "").strip():
        return CobolTestResult(
            return_code=rc,
            execution_time_ms=elapsed_ms,
            error=stderr or "Execution failed",
        )

    # Parse outputs
    paragraphs = parse_trace(stdout)
    branches = parse_branch_coverage(stdout)
    call_chain = parse_call_chain(stdout)
    var_snapshots = parse_variable_snapshots(stdout)

    # Collect non-trace display output
    displays = []
    for line in stdout.splitlines():
        stripped = line.strip()
        if (not stripped.startswith("SPECTER-TRACE:")
                and not stripped.startswith("SPECTER-MOCK:")
                and not stripped.startswith("SPECTER-")
                and not stripped.startswith("@@B:")
                and not stripped.startswith("@@V:")):
            if stripped:
                displays.append(stripped)

    return CobolTestResult(
        paragraphs_hit=paragraphs,
        branches_hit=branches,
        call_chain=call_chain,
        variable_snapshots=var_snapshots,
        display_output=displays,
        return_code=rc,
        execution_time_ms=elapsed_ms,
    )


# ---------------------------------------------------------------------------
# Batch execution
# ---------------------------------------------------------------------------

def _run_single(args: tuple) -> CobolTestResult:
    """Worker function for parallel execution."""
    exe_path, input_state, stub_log, work_dir, timeout = args
    # Reconstruct a minimal context for the worker
    ctx = CobolExecutionContext(executable_path=Path(exe_path))
    return run_test_case(ctx, input_state, stub_log, work_dir=work_dir, timeout=timeout)


def run_batch(
    context: CobolExecutionContext,
    test_cases: list[tuple[dict, list[tuple[str, list]]]],
    max_workers: int = 4,
    timeout: int = 30,
) -> list[CobolTestResult]:
    """Run multiple test cases in parallel.

    Args:
        context: Compiled COBOL context.
        test_cases: List of (input_state, stub_log) tuples.
        max_workers: Number of parallel workers.
        timeout: Per-execution timeout in seconds.

    Returns:
        List of CobolTestResult in same order as test_cases.
    """
    if not test_cases:
        return []

    work_dir = context.executable_path.parent

    # For small batches, run sequentially
    if len(test_cases) <= 2 or max_workers <= 1:
        return [
            run_test_case(context, inp, stub, work_dir=work_dir, timeout=timeout)
            for inp, stub in test_cases
        ]

    # Parallel execution
    args_list = [
        (str(context.executable_path), inp, stub, str(work_dir), timeout)
        for inp, stub in test_cases
    ]

    results: list[CobolTestResult | None] = [None] * len(test_cases)
    with ProcessPoolExecutor(max_workers=max_workers) as pool:
        future_to_idx = {
            pool.submit(_run_single, args): idx
            for idx, args in enumerate(args_list)
        }
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                results[idx] = future.result()
            except Exception as e:
                results[idx] = CobolTestResult(
                    return_code=-1,
                    error=str(e),
                )

    return [r if r is not None else CobolTestResult(return_code=-1, error="Unknown")
            for r in results]
