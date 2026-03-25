"""Validate a Python-generated test store against compiled COBOL.

Pass 1 (--synthesize) generates test cases fast via Python execution.
Pass 2 (--cobol-validate-store) compiles the COBOL, runs each test case
through the binary, and keeps only those that produce matching coverage.

Usage:
    specter program.ast --cobol-validate-store tests.jsonl \
        --cobol-source program.cbl --copybook-dir ./cpy
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

log = logging.getLogger(__name__)


def validate_store(
    ast_file: str | Path,
    cobol_source: str | Path,
    copybook_dirs: list[str | Path] | None = None,
    store_path: str | Path = "",
    output_path: str | Path = "",
    timeout_per_case: int = 30,
) -> str:
    """Validate test cases from a JSONL store against compiled COBOL.

    Args:
        ast_file: Path to JSON AST file.
        cobol_source: Path to COBOL source (.cbl).
        copybook_dirs: Copybook directories.
        store_path: Input JSONL test store (from --synthesize).
        output_path: Output validated JSONL.
        timeout_per_case: Per-test execution timeout in seconds.

    Returns:
        Summary report string.
    """
    from .ast_parser import parse_ast
    from .code_generator import generate_code
    from .cobol_coverage import _python_pre_run, load_existing_coverage
    from .cobol_executor import prepare_context, run_test_case
    from .cobol_mock import generate_mock_data_ordered
    from .monte_carlo import _load_module
    from .variable_extractor import extract_variables

    start_time = time.time()
    copybook_dirs = list(copybook_dirs or [])

    # --- Parse and generate Python module for pre-runs ---
    log.info("Parsing AST: %s", ast_file)
    program = parse_ast(ast_file)
    var_report = extract_variables(program)

    import tempfile
    code = generate_code(program, var_report, instrument=True,
                         cobol_source=str(cobol_source))
    tmpdir = Path(tempfile.mkdtemp(prefix="specter_validate_"))
    py_path = tmpdir / f"{program.program_id}.py"
    py_path.write_text(code)
    module = _load_module(py_path)

    # --- Compile COBOL ---
    log.info("Instrumenting and compiling COBOL: %s", cobol_source)
    context = prepare_context(
        cobol_source, copybook_dirs,
        enable_branch_tracing=True,
        coverage_mode=True,
        allow_hardening_fallback=True,
    )
    log.info("COBOL compiled: %d paragraphs, %d branches",
             context.total_paragraphs, context.total_branches)

    # --- Load test cases ---
    store_path = Path(store_path)
    test_cases, _, _ = load_existing_coverage(store_path)
    log.info("Loaded %d test cases from %s", len(test_cases), store_path)

    # --- Validate each test case ---
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    validated = 0
    failed = 0
    errors = 0
    all_cobol_paras: set[str] = set()
    all_cobol_branches: set[str] = set()
    all_python_branches: set[str] = set()

    with open(output_path, "w") as out_f:
        for i, tc in enumerate(test_cases):
            input_state = tc.get("input_state", {})
            python_branches = set(tc.get("branches_hit", []))
            python_paras = set(tc.get("paragraphs_hit", []))

            # Reconstruct stub_outcomes from stored stub_log
            stub_log = []
            for entry in tc.get("stub_outcomes", []):
                if isinstance(entry, list) and len(entry) == 2:
                    op_key, outcomes = entry
                    stub_log.append((op_key, outcomes))

            # If no stub_log stored, do a Python pre-run to get ordering
            if not stub_log:
                stub_log = _python_pre_run(module, input_state)

            # Run through COBOL
            result = run_test_case(
                context, input_state, stub_log,
                timeout=timeout_per_case,
            )

            if result.error:
                errors += 1
                log.warning("  TC %d/%d [%s]: error: %s",
                            i + 1, len(test_cases), tc.get("id", "?"), result.error)
                continue

            cobol_paras = set(result.paragraphs_hit)
            cobol_branches = result.branches_hit

            # Check if COBOL execution confirms Python coverage
            # A test case is valid if COBOL hits at least the paragraphs
            # and branches that Python predicted
            cobol_confirms = bool(cobol_paras or cobol_branches)

            if cobol_confirms:
                validated += 1
                all_cobol_paras.update(cobol_paras)
                all_cobol_branches.update(cobol_branches)
                all_python_branches.update(python_branches)

                # Write validated record with both Python and COBOL coverage
                record = dict(tc)
                record["cobol_paragraphs_hit"] = sorted(cobol_paras)
                record["cobol_branches_hit"] = sorted(cobol_branches)
                record["validated"] = True
                out_f.write(json.dumps(record, default=str) + "\n")

                if (validated % 10) == 1 or validated <= 5:
                    log.info("  TC %d/%d [%s]: validated — COBOL: %d paras, %d branches",
                             i + 1, len(test_cases), tc.get("id", "?"),
                             len(cobol_paras), len(cobol_branches))
            else:
                failed += 1

            # Progress
            if (i + 1) % 50 == 0:
                log.info("  Progress: %d/%d validated, %d failed, %d errors "
                         "— COBOL branches: %d",
                         validated, i + 1, failed, errors,
                         len(all_cobol_branches))

    elapsed = time.time() - start_time

    # Build summary
    lines = [
        "=== COBOL Validation Report ===",
        f"  Test cases:     {len(test_cases)}",
        f"  Validated:      {validated}",
        f"  Failed:         {failed}",
        f"  Errors:         {errors}",
        f"  COBOL paragraphs: {len(all_cobol_paras)}/{context.total_paragraphs}",
        f"  COBOL branches:   {len(all_cobol_branches)}/{context.total_branches}",
        f"  Python branches:  {len(all_python_branches)} (pre-validation)",
        f"  Time:           {elapsed:.1f}s",
    ]
    return "\n".join(lines)
