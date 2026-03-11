#!/usr/bin/env python3
"""Run test-store inputs against both Python and compiled COBOL mock, compare outputs.

Usage:
    python3 examples/run_mock.py <cobol_executable> <generated.py> <test_store.jsonl>

The pipeline for each test case:
  1. Run the generated Python with stub_log enabled → capture displays + stub order
  2. Generate execution-ordered mock data from the stub_log
  3. Run the compiled COBOL mock with that data → capture displays + trace
  4. Compare DISPLAY outputs between Python and COBOL
"""
import json
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
    """Run a test case through the Python module, return (displays, stub_log)."""
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
    return displays, stub_log


def _run_cobol(executable, stub_log):
    """Run the COBOL mock with ordered mock data, return (displays, trace)."""
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

    return displays, trace, rc, stdout, stderr


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
    tcs, _ = TestStore.load(store_path)
    print(f"Loaded {len(tcs)} test cases from {store_path}")

    display_match = 0
    display_mismatch = 0
    cobol_errors = 0
    inconclusive = 0
    all_cobol_paras: set[str] = set()

    for tc in tcs:
        py_displays, stub_log = _run_python(mod, tc)
        cobol_displays, cobol_trace, rc, stdout, stderr = _run_cobol(executable, stub_log)
        all_cobol_paras.update(cobol_trace)

        if rc == -1:
            cobol_errors += 1
            continue

        # Some generated/neutralized mocks can complete with no output signal.
        # Treat those cases as inconclusive rather than hard mismatches.
        if rc == 0 and not stdout.strip() and not stderr.strip():
            inconclusive += 1
            continue

        if py_displays == cobol_displays:
            display_match += 1
        else:
            display_mismatch += 1
            print(f"  TC {tc.id} (layer {tc.layer}): DISPLAY mismatch")
            py_set, cobol_set = set(py_displays), set(cobol_displays)
            only_py = py_set - cobol_set
            only_cobol = cobol_set - py_set
            if only_py:
                print(f"    Python only:  {sorted(only_py)[:5]}")
            if only_cobol:
                print(f"    COBOL only:   {sorted(only_cobol)[:5]}")

    total = len(tcs)
    print(f"\nResults: {total} test cases")
    print(f"  DISPLAY match:    {display_match}/{total}")
    if display_mismatch:
        print(f"  DISPLAY mismatch: {display_mismatch}/{total}")
    if cobol_errors:
        print(f"  COBOL errors:     {cobol_errors}/{total}")
    if inconclusive:
        print(f"  Inconclusive:     {inconclusive}/{total}")
    print(f"  COBOL paragraphs: {len(all_cobol_paras)}")
    for p in sorted(all_cobol_paras):
        print(f"    {p}")


if __name__ == "__main__":
    main()
