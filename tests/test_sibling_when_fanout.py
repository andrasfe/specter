"""Tests for SiblingWhenFanoutStrategy — multi-arm EVALUATE coverage."""

from __future__ import annotations

import pytest

from specter.coverage_strategies import (
    SiblingWhenFanoutStrategy,
    _extract_leaf_name,
    _non_blank_value_for,
    _parse_arm_requirement,
)


# --------------------------------------------------- _parse_arm_requirement


@pytest.mark.parametrize(
    "condition, expected_var, expected_values",
    [
        ("SDTMMI OF CORPT0AI = SPACES OR LOW-VALUES", "SDTMMI", ["  ", ""]),
        ("WHEN SDTDDI OF CORPT0AI = SPACES OR", "SDTDDI", ["  ", ""]),
        ("EDTYYYYI OF CORPT0AI = LOW-VALUES", "EDTYYYYI", [""]),
        ("WS-FLAG = 'Y'", "WS-FLAG", ["Y"]),
        ("WS-COUNT = 7", "WS-COUNT", ["7"]),
        ("SDTMMI IS NOT NUMERIC", "SDTMMI", ["X"]),
        ("WHEN OTHER", "", []),
        ("", "", []),
    ],
)
def test_parse_arm_requirement(condition, expected_var, expected_values) -> None:
    var, values = _parse_arm_requirement(condition)
    assert var == expected_var
    assert values == expected_values


def test_extract_leaf_name() -> None:
    assert _extract_leaf_name("SDTMMI OF CORPT0AI") == "SDTMMI"
    assert _extract_leaf_name("sdtmmi") == "SDTMMI"
    assert _extract_leaf_name("X-Y-Z") == "X-Y-Z"


# --------------------------------------------------- non-blank picker


class _Dom:
    def __init__(self, lits):
        self.condition_literals = lits


class _Ctx:
    def __init__(self, domains):
        self.domains = domains


def test_non_blank_value_picks_from_condition_literals() -> None:
    ctx = _Ctx(domains={"SDTMMI": _Dom(["  ", "", "12", "01"])})
    # First non-blank literal wins.
    assert _non_blank_value_for("SDTMMI", ctx) == "12"


def test_non_blank_value_falls_back_to_X() -> None:
    ctx = _Ctx(domains={"SDTMMI": _Dom(["", "  "])})
    # All literals blank → "X" sentinel.
    assert _non_blank_value_for("SDTMMI", ctx) == "X"


def test_non_blank_value_missing_domain_returns_X() -> None:
    ctx = _Ctx(domains={})
    assert _non_blank_value_for("UNKNOWN", ctx) == "X"


# --------------------------------------------------- fanout generator


class _FakeRegistry:
    """Minimal registry stub exposing ``by_hash``."""

    def __init__(self, entries):
        # entries: list of (hash, condition_text)
        class _Entry:
            def __init__(self, condition):
                self.condition = condition
        self.by_hash = {h: _Entry(c) for h, c in entries}


class _FakeContext:
    def __init__(self, registry):
        self.branch_registry = registry


class _FakeStrategyCtx:
    """Minimal StrategyContext double."""

    def __init__(self, branch_meta, registry, test_cases, domains):
        self.branch_meta = branch_meta
        self.context = _FakeContext(registry)
        self.domains = domains
        self.success_stubs = {"CICS-RECEIVE": [[("EIBAID", "\x7D")]]}
        self.success_defaults = {"CICS-RECEIVE": [("EIBAID", "\x7D")]}

    current_target_key = None


class _FakeCov:
    def __init__(self, test_cases, branches_hit):
        self.test_cases = test_cases
        self.branches_hit = set(branches_hit)


def test_fanout_generates_case_per_uncovered_arm() -> None:
    # One EVALUATE at cobol_bid=7 with 3 arms: W1 covered, W2 and W3 uncovered.
    registry = _FakeRegistry([
        ("h1", "SDTMMI OF CORPT0AI = SPACES OR LOW-VALUES"),
        ("h2", "SDTDDI OF CORPT0AI = SPACES OR LOW-VALUES"),
        ("h3", "SDTYYYYI OF CORPT0AI = SPACES OR LOW-VALUES"),
    ])
    branch_meta = {
        "7": {
            "type": "EVALUATE",
            "paragraph": "PROCESS-ENTER-KEY",
            "when_hashes": {"W1": "h1", "W2": "h2", "W3": "h3"},
        },
    }
    seed_tc = {
        "input_state": {
            "EIBCALEN": 1, "EIBAID": "DFHENTER", "CUSTOMI": "X",
            "SDTMMI": "  ", "SDTDDI": "01", "SDTYYYYI": "2025",
        },
        "stub_outcomes": {"CICS-RECEIVE": [[("EIBAID", "\x7D")]]},
        "stub_defaults": {"CICS-RECEIVE": [("EIBAID", "\x7D")]},
        "branches_hit": ["7:W1"],
    }
    domains = {"SDTMMI": _Dom(["12"]), "SDTDDI": _Dom(["01"]), "SDTYYYYI": _Dom(["2025"])}
    ctx = _FakeStrategyCtx(branch_meta, registry, [seed_tc], domains)
    cov = _FakeCov([seed_tc], branches_hit=["7:W1"])

    strat = SiblingWhenFanoutStrategy()
    cases = list(strat.generate_cases(ctx, cov, batch_size=10))

    # Two uncovered arms (W2, W3) → two fanout cases
    assert len(cases) == 2
    # For the W2 (SDTDDI=SPACES) case, SDTDDI must be blank and SDTMMI
    # must have a non-blank value so only this arm fires.
    w2_case = next(
        c for c in cases
        if c[3] == "branch:7:W2"
    )
    input_state = w2_case[0]
    assert input_state["SDTDDI"].strip() == ""
    assert input_state["SDTMMI"].strip() != ""  # prior arm's variable disqualified


def test_fanout_skips_when_no_arm_is_covered_yet() -> None:
    """Without a seed (no covered sibling), nothing to fan out from."""
    registry = _FakeRegistry([
        ("h1", "SDTMMI OF CORPT0AI = SPACES OR LOW-VALUES"),
        ("h2", "SDTDDI OF CORPT0AI = SPACES OR LOW-VALUES"),
    ])
    branch_meta = {
        "7": {
            "type": "EVALUATE",
            "paragraph": "X",
            "when_hashes": {"W1": "h1", "W2": "h2"},
        },
    }
    ctx = _FakeStrategyCtx(branch_meta, registry, [], domains={})
    cov = _FakeCov([], branches_hit=[])

    strat = SiblingWhenFanoutStrategy()
    assert list(strat.generate_cases(ctx, cov, batch_size=10)) == []


def test_fanout_skips_when_all_arms_covered() -> None:
    """Nothing to do when every arm is already hit."""
    registry = _FakeRegistry([
        ("h1", "SDTMMI OF CORPT0AI = SPACES"),
        ("h2", "SDTDDI OF CORPT0AI = SPACES"),
    ])
    branch_meta = {
        "7": {
            "type": "EVALUATE",
            "paragraph": "X",
            "when_hashes": {"W1": "h1", "W2": "h2"},
        },
    }
    seed = {"input_state": {}, "branches_hit": ["7:W1", "7:W2"]}
    ctx = _FakeStrategyCtx(branch_meta, registry, [seed], domains={})
    cov = _FakeCov([seed], branches_hit=["7:W1", "7:W2"])

    strat = SiblingWhenFanoutStrategy()
    assert list(strat.generate_cases(ctx, cov, batch_size=10)) == []
