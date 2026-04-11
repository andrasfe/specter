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
                log.info("Using cached compiled COBOL: %s", executable_path)
                hardened_mode = "SPECTER-HARDENED-ENTRY" in source_text
                branch_meta: dict = {}
                total_branches = 0
                total_paragraphs = 0
                if enable_branch_tracing:
                    # Count @@B: probes already in the source (from LLM or rule-based insertion)
                    import re as _re
                    _para_re = _re.compile(r"^\s{7}([A-Z0-9][A-Z0-9_-]*)\s*\.\s*$", _re.IGNORECASE)
                    current_para = ""
                    for line in source_text.splitlines():
                        m_para = _para_re.match(line)
                        if m_para:
                            current_para = m_para.group(1).upper()
                        m_probe = _re.search(r"@@B:(\d+):(T|F|W\d+)", line)
                        if m_probe and not (len(line) > 6 and line[6] in ("*", "/")):
                            bid = m_probe.group(1)
                            total_branches += 1
                            if bid not in branch_meta:
                                branch_meta[bid] = {"paragraph": current_para}
                total_paragraphs = source_text.count("SPECTER-TRACE:")
                return CobolExecutionContext(
                    executable_path=executable_path,
                    instrumented_source_path=instrumented_path,
                    branch_meta=branch_meta,
                    injectable_vars=list(injectable_vars or []),
                    total_paragraphs=total_paragraphs,
                    total_branches=total_branches,
                    hardened_mode=hardened_mode,
                    coverage_mode=coverage_mode,
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
    # Exclude EIB fields — those are set via VALUE clauses in the stubs.
    _EIB_FIELDS = {"EIBCALEN", "EIBAID", "EIBTRNID", "EIBTIME", "EIBDATE",
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

    log.info("Compiled COBOL: %s (%d paragraphs traced, %d branch probes)",
             executable_path, total_paragraphs, total_branches)

    return CobolExecutionContext(
        executable_path=executable_path,
        instrumented_source_path=instrumented_path,
        branch_meta=branch_meta,
        injectable_vars=list(injectable_vars or []),
        total_paragraphs=total_paragraphs,
        total_branches=total_branches,
        hardened_mode=hardened_mode,
        coverage_mode=coverage_mode,
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
    init_values = {k: str(v) for k, v in input_state.items()
                   if not str(k).startswith("_")}
    init_data = generate_init_records(init_values) if init_values else ""

    # The Python pre-run's run() function calls paragraphs in SOURCE
    # DECLARATION order (1000-GET-NEXT before 0000-ACCTFILE-OPEN),
    # but the COBOL binary runs them in EXECUTION order (OPEN before
    # GET-NEXT, per the main program's PERFORM sequence). This means
    # the stub_log has READ/WRITE/CALL records first and OPEN records
    # later, while the COBOL binary expects OPEN records first.
    #
    # If we write the mock data in stub_log order, the COBOL OPEN
    # paragraph reads a READ record (wrong status — SPACES instead
    # of '00'), and the success path is never exercised. This is the
    # root cause of the APPL-AOK/STATUS='00' plateau on every batch
    # program.
    #
    # Fix: reorder the stub_log so OPEN entries appear at the front
    # (matching COBOL execution order), followed by everything else
    # in their original order.
    open_close_pad = ""
    if stub_log:
        open_entries = [(k, e) for k, e in stub_log if k.startswith("OPEN:")]
        close_entries = [(k, e) for k, e in stub_log if k.startswith("CLOSE:")]
        other_entries = [(k, e) for k, e in stub_log
                         if not k.startswith("OPEN:") and not k.startswith("CLOSE:")]
        # COBOL order: OPEN first, then main logic (READ/WRITE/CALL), then CLOSE
        stub_log = open_entries + other_entries + close_entries
        if open_entries:
            log.debug(
                "Reordered stub_log: %d OPEN + %d other + %d CLOSE (moved %d OPEN entries to front)",
                len(open_entries), len(other_entries), len(close_entries), len(open_entries),
            )

    stub_data = generate_mock_data_ordered(stub_log) if stub_log else ""

    # In coverage mode (RETURN/XCTL don't terminate), the COBOL program
    # consumes more mock records than the Python pre-run produces.
    # Pad with extra success records so the COBOL doesn't hit EOF early.
    pad_data = ""
    if context.coverage_mode:
        pad_record = f"{'CICS':<30}{'00':<20}{'0':>9}{' ' * 21}"[:80]
        pad_data = "\n".join([pad_record] * 50) + "\n"

    # Concatenate: init records first, then stub records (now reordered
    # with OPEN at front), then optional coverage padding.
    parts = [p for p in [init_data, stub_data, pad_data] if p]
    mock_data = "\n".join(parts) if parts else "\n"

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
