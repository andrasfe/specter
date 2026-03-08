"""Persistent test case storage (JSONL format).

Each test case is a complete execution spec: input variables + all stub
outcomes (SQL results, file statuses, CALL return codes, etc.).
Append-only JSONL — survives interruption, enables incremental progress.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TestCase:
    """A single test case: input state + full stub orchestration."""

    id: str  # SHA-256 of (input_state, stub_outcomes)
    input_state: dict[str, object]
    stub_outcomes: dict[str, list]  # per-operation mock queues
    stub_defaults: dict[str, list]  # exhaustion defaults per operation
    paragraphs_covered: list[str]
    branches_covered: list[int]
    layer: int  # which synthesis layer produced it (1-5)
    target: str  # what paragraph/branch it was targeting


def _compute_id(input_state: dict, stub_outcomes: dict) -> str:
    """Deterministic SHA-256 from input_state + stub_outcomes."""
    payload = json.dumps(
        {"input_state": input_state, "stub_outcomes": stub_outcomes},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _tc_to_dict(tc: TestCase) -> dict:
    """Serialize a TestCase to a JSON-safe dict."""
    return {
        "id": tc.id,
        "input_state": tc.input_state,
        "stub_outcomes": {
            k: [
                [(pair[0], pair[1]) for pair in entry]
                if isinstance(entry, list) and entry and isinstance(entry[0], (list, tuple))
                else entry
                for entry in v
            ]
            for k, v in tc.stub_outcomes.items()
        },
        "stub_defaults": {
            k: [(pair[0], pair[1]) for pair in v]
            if isinstance(v, list) and v and isinstance(v[0], (list, tuple))
            else v
            for k, v in tc.stub_defaults.items()
        },
        "paragraphs_covered": tc.paragraphs_covered,
        "branches_covered": tc.branches_covered,
        "layer": tc.layer,
        "target": tc.target,
    }


def _dict_to_tc(d: dict) -> TestCase:
    """Deserialize a dict to a TestCase."""
    # Restore stub_outcomes: lists of lists of [var, val] pairs → lists of lists of tuples
    stub_outcomes = {}
    for k, v in d.get("stub_outcomes", {}).items():
        entries = []
        for entry in v:
            if isinstance(entry, list) and entry and isinstance(entry[0], list):
                entries.append([tuple(pair) for pair in entry])
            else:
                entries.append(entry)
        stub_outcomes[k] = entries

    stub_defaults = {}
    for k, v in d.get("stub_defaults", {}).items():
        if isinstance(v, list) and v and isinstance(v[0], list):
            stub_defaults[k] = [tuple(pair) for pair in v]
        else:
            stub_defaults[k] = v

    return TestCase(
        id=d["id"],
        input_state=d.get("input_state", {}),
        stub_outcomes=stub_outcomes,
        stub_defaults=stub_defaults,
        paragraphs_covered=d.get("paragraphs_covered", []),
        branches_covered=d.get("branches_covered", []),
        layer=d.get("layer", 0),
        target=d.get("target", ""),
    )


class TestStore:
    """Persistent test case storage backed by a JSONL file."""

    @staticmethod
    def load(path: str | Path) -> list[TestCase]:
        """Read and deduplicate test cases from a JSONL file."""
        path = Path(path)
        if not path.exists():
            return []

        seen_ids: set[str] = set()
        cases: list[TestCase] = []
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            tc = _dict_to_tc(d)
            if tc.id not in seen_ids:
                seen_ids.add(tc.id)
                cases.append(tc)
        return cases

    @staticmethod
    def append(path: str | Path, tc: TestCase) -> None:
        """Atomic single-line append of a test case."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(_tc_to_dict(tc), default=str)
        with open(path, "a") as f:
            f.write(line + "\n")

    @staticmethod
    def replay(
        module,
        test_cases: list[TestCase],
    ) -> tuple[set[str], set[int], set[tuple]]:
        """Execute all test cases and return baseline coverage.

        Returns (covered_paras, covered_branches, covered_edges).
        """
        covered_paras: set[str] = set()
        covered_branches: set[int] = set()
        covered_edges: set[tuple] = set()

        goback_cls = getattr(module, "_GobackSignal", None)

        for tc in test_cases:
            try:
                state = _build_run_state(module, tc)
                rs = module.run(state)
                trace = rs.get("_trace", [])
                covered_paras.update(trace)
                covered_branches.update(rs.get("_branches", set()))
                for j in range(len(trace) - 1):
                    if trace[j] != trace[j + 1]:
                        covered_edges.add((trace[j], trace[j + 1]))
            except Exception:
                pass

        return covered_paras, covered_branches, covered_edges


def _build_run_state(module, tc: TestCase) -> dict:
    """Build a state dict ready for module.run() from a TestCase."""
    default_state_fn = getattr(module, "_default_state", None)
    state = default_state_fn() if default_state_fn else {}
    state.update(tc.input_state)

    if tc.stub_outcomes:
        state["_stub_outcomes"] = {
            k: [list(entry) for entry in v]
            for k, v in tc.stub_outcomes.items()
        }

    if tc.stub_defaults:
        state["_stub_defaults"] = dict(tc.stub_defaults)

    return state
