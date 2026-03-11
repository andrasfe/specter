#!/usr/bin/env python3
"""COBOL-first comparison: run COBOL mock as ground truth, validate Python matches.

Usage:
    python3 examples/run_mock.py <cobol_executable> <generated.py> <test_store.jsonl>

The pipeline for each test case:
  1. Run the generated Python to capture stub consumption order + branches
  2. Generate execution-ordered mock data from the stub_log
  3. Run the compiled COBOL mock with that data → COBOL output is the REFERENCE
  4. Compare: Python DISPLAY output must match COBOL DISPLAY output
  5. When outputs match, Python's branch data is authoritative for both
     (same DISPLAY output ⇒ same execution path ⇒ same branches taken)
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from specter.cobol_mock import generate_mock_data_ordered, run_cobol, parse_trace
from specter.monte_carlo import _load_module
from specter.test_store import TestStore


def _normalize_stub_outcomes(stub_outcomes: dict) -> dict:
    """Clone stub outcomes into a shape accepted by generated modules."""
    normalized = {}
    for k, v in (stub_outcomes or {}).items():
        if isinstance(v, list):
            normalized[k] = [list(e) if isinstance(e, list) else e for e in v]
        else:
            normalized[k] = v
    return normalized


def _normalize_stub_defaults(stub_defaults: dict) -> dict:
    """Clone stub defaults while tolerating scalar sentinel values."""
    normalized = {}
    for k, v in (stub_defaults or {}).items():
        normalized[k] = list(v) if isinstance(v, list) else v
    return normalized


def _run_python(mod, tc):
    """Run Python to capture stub order, displays, branches, and trace."""
    state = dict(tc.input_state)
    state["_stub_outcomes"] = _normalize_stub_outcomes(tc.stub_outcomes)
    state["_stub_defaults"] = _normalize_stub_defaults(tc.stub_defaults)
    state["_stub_log"] = []
    try:
        result = mod.run(state)
    except Exception:
        result = state
    displays = result.get("_display", [])
    stub_log = result.get("_stub_log", state.get("_stub_log", []))
    branches = result.get("_branches", set())
    trace = result.get("_trace", [])
    return displays, stub_log, branches, trace


def _run_cobol(executable, stub_log):
    """Run the COBOL mock with ordered mock data, return (displays, trace, rc)."""
    mock_data = generate_mock_data_ordered(stub_log)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".dat", delete=False) as f:
        f.write(mock_data)
        dat_path = f.name

    rc, stdout, stderr = run_cobol(executable, dat_path)
    Path(dat_path).unlink(missing_ok=True)

    displays = []
    trace = []
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("SPECTER-TRACE:"):
            trace.append(line.split(":", 1)[1])
        elif line.startswith("SPECTER-"):
            pass  # internal mock/status lines
        else:
            displays.append(line)

    return displays, trace, rc


def main():
    if len(sys.argv) < 4:
        print(
            f"Usage: {sys.argv[0]} <cobol_executable> <generated.py> <test_store.jsonl>",
            file=sys.stderr,
        )
        sys.exit(1)

    executable = Path(sys.argv[1])
    py_module = Path(sys.argv[2])
    store_path = Path(sys.argv[3])

    for p, label in [(executable, "COBOL executable"), (py_module, "Python module"), (store_path, "test store")]:
        if not p.exists():
            print(f"Error: {label} not found: {p}", file=sys.stderr)
            sys.exit(1)

    mod = _load_module(str(py_module))
    branch_meta = getattr(mod, "_BRANCH_META", {})
    total_branches = len(branch_meta)

    tcs, _ = TestStore.load(store_path)
    print(f"Loaded {len(tcs)} test cases from {store_path}")

    display_match = 0
    display_mismatch = 0
    cobol_errors = 0
    all_cobol_paras: set[str] = set()
    all_branches: set[int] = set()

    for tc in tcs:
        # Step 1: Run Python to get stub order + branches
        py_displays, stub_log, branches, py_trace = _run_python(mod, tc)
        all_branches.update(branches)

        if not stub_log:
            display_match += 1
            continue

        # Step 2-3: Generate mock data and run COBOL (ground truth)
        cobol_displays, cobol_trace, rc = _run_cobol(executable, stub_log)
        all_cobol_paras.update(cobol_trace)

        if rc == -1:
            cobol_errors += 1
            continue

        # Step 4: Python must match COBOL (COBOL is the reference)
        if py_displays == cobol_displays:
            display_match += 1
        else:
            display_mismatch += 1
            print(f"  TC {tc.id[:12]} (layer {tc.layer}): Python diverges from COBOL")
            py_set, cobol_set = set(py_displays), set(cobol_displays)
            only_py = py_set - cobol_set
            only_cobol = cobol_set - py_set
            if only_cobol:
                print(f"    COBOL (reference): {sorted(only_cobol)[:5]}")
            if only_py:
                print(f"    Python (wrong):    {sorted(only_py)[:5]}")

    total = len(tcs)
    print(f"\nResults: {total} test cases")
    print(f"  Match:            {display_match}/{total}")
    if display_mismatch:
        print(f"  Python diverges:  {display_mismatch}/{total}")
    if cobol_errors:
        print(f"  COBOL errors:     {cobol_errors}/{total}")

    # Branch coverage (from Python — authoritative when DISPLAY outputs match)
    covered_true = {b for b in all_branches if b > 0}
    covered_false = {abs(b) for b in all_branches if b < 0}
    covered_ids = covered_true | covered_false
    print(f"\n  Branches:         {len(covered_ids)}/{total_branches} branch points covered")
    print(f"    True taken:     {len(covered_true)}")
    print(f"    False taken:    {len(covered_false)}")
    both = covered_true & covered_false
    true_only = covered_true - covered_false
    false_only = covered_false - covered_true
    print(f"    Both ways:      {len(both)}")
    if true_only:
        print(f"    True-only:      {len(true_only)}")
    if false_only:
        print(f"    False-only:     {len(false_only)}")
    uncovered = set(branch_meta.keys()) - covered_ids
    if uncovered:
        print(f"    Uncovered:      {len(uncovered)}")
        for bid in sorted(uncovered)[:10]:
            meta = branch_meta[bid]
            cond = meta.get("condition", "")[:50]
            print(f"      [{bid}] {meta['paragraph']}: {cond}")
        if len(uncovered) > 10:
            print(f"      ... and {len(uncovered) - 10} more")

    print(f"\n  COBOL paragraphs: {len(all_cobol_paras)}")
    for p in sorted(all_cobol_paras):
        print(f"    {p}")


if __name__ == "__main__":
    main()
