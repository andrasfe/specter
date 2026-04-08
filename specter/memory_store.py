from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .memory_models import (
    APIBudgetLedger,
    FailureFragment,
    MemoryState,
    StrategyStats,
    SuccessState,
    TargetStatus,
    memory_state_from_dict,
    memory_state_to_dict,
)
from .persistence_utils import atomic_write_json


MEMORY_DIR_SUFFIX = "_memory"
MEMORY_FILE = "memory_state.json"


def derive_memory_dir(store_path: str | Path) -> Path:
    """Return run-local memory directory derived from test-store stem."""
    store = Path(store_path)
    return store.with_name(f"{store.stem}{MEMORY_DIR_SUFFIX}")


class MemoryStore:
    """Crash-safe memory state persistence for coverage runs."""

    def __init__(
        self,
        memory_dir: str | Path,
        *,
        max_successes: int = 2000,
        max_failures: int = 2000,
    ):
        self.memory_dir = Path(memory_dir)
        self.max_successes = max_successes
        self.max_failures = max_failures

    @property
    def state_path(self) -> Path:
        return self.memory_dir / MEMORY_FILE

    def load_state(self) -> MemoryState:
        if not self.state_path.exists():
            return MemoryState()
        try:
            raw = json.loads(self.state_path.read_text())
            if not isinstance(raw, dict):
                return MemoryState()
            return memory_state_from_dict(raw)
        except Exception:
            return MemoryState()

    def save_state(self, state: MemoryState) -> None:
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.state_path, memory_state_to_dict(state), indent=2)

    def append_success(self, state: MemoryState, success: SuccessState) -> None:
        state.successes.append(success)
        self.prune_state(state)

    def append_failure(self, state: MemoryState, failure: FailureFragment) -> None:
        state.failures.append(failure)
        self.prune_state(state)

    def upsert_target_status(
        self,
        state: MemoryState,
        target: str,
        *,
        attempts_delta: int = 0,
        solved: bool | None = None,
        nearest_paragraph_hits: int | None = None,
        nearest_branch_hits: int | None = None,
        last_error: str | None = None,
    ) -> None:
        now = time.time()
        current = state.targets.get(target, TargetStatus())
        current.attempts = max(0, current.attempts + attempts_delta)
        if solved is not None:
            current.solved = solved
        if nearest_paragraph_hits is not None:
            current.nearest_paragraph_hits = max(
                current.nearest_paragraph_hits,
                nearest_paragraph_hits,
            )
        if nearest_branch_hits is not None:
            current.nearest_branch_hits = max(
                current.nearest_branch_hits,
                nearest_branch_hits,
            )
        if last_error is not None:
            current.last_error = last_error
        current.last_updated = now
        state.targets[target] = current

    def upsert_strategy_stats(
        self,
        state: MemoryState,
        strategy_name: str,
        stats: StrategyStats,
    ) -> None:
        merged = state.strategies.get(strategy_name, StrategyStats())
        merged.total_cases = max(merged.total_cases, stats.total_cases)
        merged.total_new_coverage = max(merged.total_new_coverage, stats.total_new_coverage)
        merged.rounds = max(merged.rounds, stats.rounds)
        merged.last_yield_round = max(merged.last_yield_round, stats.last_yield_round)
        merged.last_updated = time.time()
        state.strategies[strategy_name] = merged

    def update_api_ledger(self, state: MemoryState, ledger: APIBudgetLedger) -> None:
        state.api_ledger = APIBudgetLedger(
            llm_calls=max(state.api_ledger.llm_calls, ledger.llm_calls),
            llm_tokens=max(state.api_ledger.llm_tokens, ledger.llm_tokens),
            jit_requests=max(state.api_ledger.jit_requests, ledger.jit_requests),
            jit_cache_hits=max(state.api_ledger.jit_cache_hits, ledger.jit_cache_hits),
            jit_cache_misses=max(state.api_ledger.jit_cache_misses, ledger.jit_cache_misses),
            last_updated=time.time(),
        )

    def checkpoint(
        self,
        state: MemoryState,
        *,
        round_num: int,
        tc_count: int,
        extra_meta: dict[str, Any] | None = None,
    ) -> None:
        state.meta["last_round"] = round_num
        state.meta["last_tc_count"] = tc_count
        state.meta["last_checkpoint"] = time.time()
        if extra_meta:
            state.meta.update(extra_meta)
        self.save_state(state)

    def prune_state(self, state: MemoryState) -> None:
        if len(state.successes) > self.max_successes:
            state.successes = state.successes[-self.max_successes :]
        if len(state.failures) > self.max_failures:
            state.failures = state.failures[-self.max_failures :]
