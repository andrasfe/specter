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
    compile_cobol,
    generate_init_records,
    generate_mock_data_ordered,
    instrument_cobol,
    parse_trace,
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

            # --- VALUE clause fixes ---
            # VALUES ARE → VALUE  (IBM plural syntax)
            line = re.sub(r"\bVALUES\s+ARE\b", "VALUE", line, flags=re.IGNORECASE)
            # VALUES IS → VALUE
            line = re.sub(r"\bVALUES\s+IS\b", "VALUE", line, flags=re.IGNORECASE)
            # Bare VALUES → VALUE (but not in PROCEDURE DIVISION where
            # it could be part of HIGH-VALUES/LOW-VALUES/SPACES usage)
            if not in_procedure:
                line = re.sub(r"\bVALUES\b(?!\s+(?:ARE|IS)\b)", "VALUE", line, flags=re.IGNORECASE)

            # --- PIC clause fixes ---
            # P.I.C. → PIC
            line = re.sub(r"\bP\.I\.C\.", "PIC", line)

            # --- IBM compiler directives (not supported by GnuCOBOL) ---
            stripped = code_area.strip().upper()
            # EJECT / SKIP1 / SKIP2 / SKIP3 — IBM page formatting
            if stripped in ("EJECT", "EJECT.", "SKIP1", "SKIP1.",
                            "SKIP2", "SKIP2.", "SKIP3", "SKIP3."):
                line = line[:6] + "*" + line[7:]
            # SERVICE RELOAD — IBM only
            elif stripped.startswith("SERVICE RELOAD") or stripped.startswith("SERVICE LABEL"):
                line = line[:6] + "*" + line[7:]
            # READY TRACE / RESET TRACE — IBM debug
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
        log.info("GnuCOBOL source fixups: %d lines fixed", fixes)
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
        work_dir = Path(tempfile.mkdtemp(prefix="specter_cobol_"))
    else:
        work_dir = Path(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)

    # Pre-clean copybooks AND source for GnuCOBOL compatibility.
    # Pass work_dir so cached LLM fixes from prior runs can be applied.
    if copybook_paths:
        from .cobol_mock import clean_copybooks, clean_cobol_source
        copybook_paths = clean_copybooks(copybook_paths)
        cobol_source = clean_cobol_source(cobol_source, fix_cache_dir=work_dir)

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

    # Instrument — in coverage mode, don't terminate on CICS RETURN/XCTL
    # so that coverage engine can explore post-transaction logic.
    # Also set EIBCALEN > 0 so CICS programs get past first-time init.
    config = MockConfig(
        copybook_dirs=copybook_paths,
        trace_paragraphs=True,
        initial_values=init_values,
        stop_on_exec_return=not coverage_mode,
        stop_on_exec_xctl=not coverage_mode,
        eib_calen=100 if coverage_mode else 0,
        eib_aid="X'7D'" if coverage_mode else "SPACES",  # X'7D' = DFHENTER
    )
    result = instrument_cobol(
        cobol_source,
        config,
        allow_hardening_fallback=allow_hardening_fallback,
    )

    # Apply branch tracing if requested
    source_text = result.source
    branch_meta: dict = {}
    total_branches = 0
    hardened_mode = "SPECTER-HARDENED-ENTRY" in source_text
    if enable_branch_tracing:
        from .cobol_mock import _add_branch_tracing, _ensure_sentence_break_before_paragraphs
        lines = source_text.splitlines(keepends=True)
        lines, branch_meta, total_branches = _add_branch_tracing(lines)
        lines = _ensure_sentence_break_before_paragraphs(lines)
        source_text = "".join(lines)
        if hardened_mode and total_branches == 0:
            log.warning(
                "Branch tracing disabled by hardening fallback: instrumented source "
                "contains SPECTER-HARDENED-ENTRY and no active IF/EVALUATE "
                "constructs remain. Paragraph coverage is still valid, but branch "
                "coverage will report 0/0 until compilation succeeds without full "
                "procedure hardening."
            )

    # Apply IBM→GnuCOBOL source-level fixes on the final instrumented text.
    # This catches patterns from inlined copybooks that bypass pre-clean.
    source_text = _gnucobol_source_fixups(source_text)

    # Write instrumented source
    instrumented_path = work_dir / (cobol_source.stem + ".mock.cbl")
    instrumented_path.write_text(source_text)

    # Compile
    executable_path = work_dir / cobol_source.stem
    success, message = compile_cobol(
        instrumented_path, executable_path, copybook_paths,
        llm_provider=llm_provider, llm_model=llm_model,
    )
    if not success and "unknown (signal)" in (message or "").lower():
        # cobc internal abort: attempt targeted local mitigation while preserving
        # strict mode semantics (no full hardening fallback).
        from .cobol_mock import _mitigate_cobc_internal_abort

        mitigated_lines = _mitigate_cobc_internal_abort(
            source_text.splitlines(keepends=True),
            message,
            allow_hardening_fallback=False,
        )
        mitigated_source = "".join(mitigated_lines)
        if mitigated_source != source_text:
            source_text = mitigated_source
            instrumented_path.write_text(source_text)
            success, message = compile_cobol(
                instrumented_path, executable_path, copybook_paths,
                llm_provider=llm_provider, llm_model=llm_model,
            )
            if not success:
                missing = {
                    sym.strip().upper()
                    for sym in re.findall(r"'([^']+)'\s+is\s+not\s+defined", message or "", re.IGNORECASE)
                    if re.match(r"^[A-Z0-9-]+$", sym.strip().upper())
                }
                if missing:
                    from .cobol_mock import _inject_fallback_paragraphs

                    # Filter out symbols already defined as paragraphs
                    existing = set()
                    for ln in source_text.splitlines():
                        stripped = ln[7:72].strip() if len(ln) > 7 else ln.strip()
                        m = re.match(r"^([A-Z0-9][A-Z0-9-]*)\s*\.", stripped, re.IGNORECASE)
                        if m:
                            existing.add(m.group(1).upper())
                    missing = missing - existing

                    lines = source_text.splitlines(keepends=True)
                    lines = _inject_fallback_paragraphs(lines, sorted(missing))
                    source_text = "".join(lines)
                    instrumented_path.write_text(source_text)
                    success, message = compile_cobol(
                        instrumented_path, executable_path, copybook_paths,
                        llm_provider=llm_provider, llm_model=llm_model,
                    )
    if not success:
        raise RuntimeError(f"COBOL compilation failed: {message}")

    log.info("Compiled COBOL: %s (%d paragraphs traced, %d branch probes)",
             executable_path, result.paragraphs_traced, total_branches)

    return CobolExecutionContext(
        executable_path=executable_path,
        instrumented_source_path=instrumented_path,
        branch_meta=branch_meta,
        injectable_vars=[],  # populated by caller from domain model
        total_paragraphs=result.paragraphs_traced,
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
) -> CobolTestResult:
    """Run a single test case against the compiled COBOL program.

    Args:
        context: Compiled COBOL context from prepare_context().
        input_state: Variable values to inject via INIT records.
        stub_log: Execution-ordered stub log from Python pre-run.
        work_dir: Directory for temp data files.
        timeout: Execution timeout in seconds.

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
    stub_data = generate_mock_data_ordered(stub_log) if stub_log else ""

    # In coverage mode (RETURN/XCTL don't terminate), the COBOL program
    # consumes more mock records than the Python pre-run produces.
    # Pad with extra success records so the COBOL doesn't hit EOF early.
    pad_data = ""
    if context.coverage_mode:
        pad_record = f"{'CICS':<30}{'00':<20}{'0':>9}{' ' * 21}"[:80]
        pad_data = "\n".join([pad_record] * 50) + "\n"

    # Concatenate: init records first, then stub records, then optional padding
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

    # Collect non-trace display output
    displays = []
    for line in stdout.splitlines():
        stripped = line.strip()
        if (not stripped.startswith("SPECTER-TRACE:")
                and not stripped.startswith("SPECTER-MOCK:")
                and not stripped.startswith("SPECTER-")
                and not stripped.startswith("@@B:")):
            if stripped:
                displays.append(stripped)

    return CobolTestResult(
        paragraphs_hit=paragraphs,
        branches_hit=branches,
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
