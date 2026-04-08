from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SuccessState:
    """Captured successful test input that produced coverage progress."""

    target: str
    input_state: dict[str, Any]
    stub_outcomes: list[list[Any]] = field(default_factory=list)
    paragraphs_hit: list[str] = field(default_factory=list)
    branches_hit: list[str] = field(default_factory=list)
    timestamp: float = 0.0


@dataclass
class FailureFragment:
    """Captured no-gain attempt fragment for future reuse/avoidance."""

    target: str
    input_state: dict[str, Any]
    stub_outcomes: list[list[Any]] = field(default_factory=list)
    reason: str = ""
    timestamp: float = 0.0


@dataclass
class TargetStatus:
    """Per-target execution status tracked across runs."""

    attempts: int = 0
    solved: bool = False
    nearest_paragraph_hits: int = 0
    nearest_branch_hits: int = 0
    last_error: str = ""
    last_updated: float = 0.0


@dataclass
class StrategyStats:
    """Persisted yield/cost counters for one strategy."""

    total_cases: int = 0
    total_new_coverage: int = 0
    rounds: int = 0
    last_yield_round: int = 0
    last_updated: float = 0.0


@dataclass
class APIBudgetLedger:
    """Persisted API budget/cost accounting across resumed runs."""

    llm_calls: int = 0
    llm_tokens: int = 0
    jit_requests: int = 0
    jit_cache_hits: int = 0
    jit_cache_misses: int = 0
    last_updated: float = 0.0


@dataclass
class MemoryState:
    """Top-level persisted memory state for a coverage run family."""

    version: int = 1
    successes: list[SuccessState] = field(default_factory=list)
    failures: list[FailureFragment] = field(default_factory=list)
    targets: dict[str, TargetStatus] = field(default_factory=dict)
    strategies: dict[str, StrategyStats] = field(default_factory=dict)
    api_ledger: APIBudgetLedger = field(default_factory=APIBudgetLedger)
    meta: dict[str, Any] = field(default_factory=dict)


def _success_to_dict(item: SuccessState) -> dict[str, Any]:
    return {
        "target": item.target,
        "input_state": item.input_state,
        "stub_outcomes": item.stub_outcomes,
        "paragraphs_hit": item.paragraphs_hit,
        "branches_hit": item.branches_hit,
        "timestamp": item.timestamp,
    }


def _failure_to_dict(item: FailureFragment) -> dict[str, Any]:
    return {
        "target": item.target,
        "input_state": item.input_state,
        "stub_outcomes": item.stub_outcomes,
        "reason": item.reason,
        "timestamp": item.timestamp,
    }


def _target_to_dict(item: TargetStatus) -> dict[str, Any]:
    return {
        "attempts": item.attempts,
        "solved": item.solved,
        "nearest_paragraph_hits": item.nearest_paragraph_hits,
        "nearest_branch_hits": item.nearest_branch_hits,
        "last_error": item.last_error,
        "last_updated": item.last_updated,
    }


def _strategy_to_dict(item: StrategyStats) -> dict[str, Any]:
    return {
        "total_cases": item.total_cases,
        "total_new_coverage": item.total_new_coverage,
        "rounds": item.rounds,
        "last_yield_round": item.last_yield_round,
        "last_updated": item.last_updated,
    }


def _ledger_to_dict(item: APIBudgetLedger) -> dict[str, Any]:
    return {
        "llm_calls": item.llm_calls,
        "llm_tokens": item.llm_tokens,
        "jit_requests": item.jit_requests,
        "jit_cache_hits": item.jit_cache_hits,
        "jit_cache_misses": item.jit_cache_misses,
        "last_updated": item.last_updated,
    }


def memory_state_to_dict(state: MemoryState) -> dict[str, Any]:
    return {
        "version": state.version,
        "successes": [_success_to_dict(s) for s in state.successes],
        "failures": [_failure_to_dict(f) for f in state.failures],
        "targets": {k: _target_to_dict(v) for k, v in state.targets.items()},
        "strategies": {k: _strategy_to_dict(v) for k, v in state.strategies.items()},
        "api_ledger": _ledger_to_dict(state.api_ledger),
        "meta": state.meta,
    }


def memory_state_from_dict(raw: dict[str, Any]) -> MemoryState:
    successes = [
        SuccessState(
            target=str(item.get("target", "")),
            input_state=dict(item.get("input_state", {})),
            stub_outcomes=list(item.get("stub_outcomes", [])),
            paragraphs_hit=list(item.get("paragraphs_hit", [])),
            branches_hit=list(item.get("branches_hit", [])),
            timestamp=float(item.get("timestamp", 0.0) or 0.0),
        )
        for item in list(raw.get("successes", []))
        if isinstance(item, dict)
    ]
    failures = [
        FailureFragment(
            target=str(item.get("target", "")),
            input_state=dict(item.get("input_state", {})),
            stub_outcomes=list(item.get("stub_outcomes", [])),
            reason=str(item.get("reason", "")),
            timestamp=float(item.get("timestamp", 0.0) or 0.0),
        )
        for item in list(raw.get("failures", []))
        if isinstance(item, dict)
    ]

    targets: dict[str, TargetStatus] = {}
    for key, item in dict(raw.get("targets", {})).items():
        if not isinstance(item, dict):
            continue
        targets[str(key)] = TargetStatus(
            attempts=int(item.get("attempts", 0) or 0),
            solved=bool(item.get("solved", False)),
            nearest_paragraph_hits=int(item.get("nearest_paragraph_hits", 0) or 0),
            nearest_branch_hits=int(item.get("nearest_branch_hits", 0) or 0),
            last_error=str(item.get("last_error", "")),
            last_updated=float(item.get("last_updated", 0.0) or 0.0),
        )

    strategies: dict[str, StrategyStats] = {}
    for key, item in dict(raw.get("strategies", {})).items():
        if not isinstance(item, dict):
            continue
        strategies[str(key)] = StrategyStats(
            total_cases=int(item.get("total_cases", 0) or 0),
            total_new_coverage=int(item.get("total_new_coverage", 0) or 0),
            rounds=int(item.get("rounds", 0) or 0),
            last_yield_round=int(item.get("last_yield_round", 0) or 0),
            last_updated=float(item.get("last_updated", 0.0) or 0.0),
        )

    ledger_raw = raw.get("api_ledger", {})
    if not isinstance(ledger_raw, dict):
        ledger_raw = {}
    ledger = APIBudgetLedger(
        llm_calls=int(ledger_raw.get("llm_calls", 0) or 0),
        llm_tokens=int(ledger_raw.get("llm_tokens", 0) or 0),
        jit_requests=int(ledger_raw.get("jit_requests", 0) or 0),
        jit_cache_hits=int(ledger_raw.get("jit_cache_hits", 0) or 0),
        jit_cache_misses=int(ledger_raw.get("jit_cache_misses", 0) or 0),
        last_updated=float(ledger_raw.get("last_updated", 0.0) or 0.0),
    )

    meta = raw.get("meta", {})
    if not isinstance(meta, dict):
        meta = {}

    return MemoryState(
        version=int(raw.get("version", 1) or 1),
        successes=successes,
        failures=failures,
        targets=targets,
        strategies=strategies,
        api_ledger=ledger,
        meta=meta,
    )
