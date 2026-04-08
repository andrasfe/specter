"""Pluggable coverage strategy configuration.

Supports two modes:
1. **Explicit rounds**: A YAML config defines a sequence of (strategy, batch_size)
   pairs. When the list is exhausted, it loops from a configurable index.
2. **Selector-driven**: A list of strategy names is provided, and the selector
   (heuristic or LLM) picks which to run each round.  This is the default
   behavior when no config file is given.

Config format (YAML):

    selector: heuristic
    default_batch_size: 200
    termination:
      max_stale_rounds: 10
      plateau_para_pct: 0.9
      plateau_branch_pct: 0.8
      extended_stale_limit: 30
    rounds:
      - strategy: baseline
        batch_size: 500
      - strategy: direct_paragraph
        batch_size: 5000
      - strategy: fault_injection
      - strategy: llm_runtime
        params:
          max_calls: 5
    loop_from: 1
    strategy_params:
      llm_runtime:
        max_calls: 5
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config dataclasses
# ---------------------------------------------------------------------------

@dataclass
class RoundConfig:
    """Configuration for a single explicit round."""

    strategy: str
    batch_size: int | None = None
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class TerminationConfig:
    """Termination thresholds for the agentic loop."""

    max_stale_rounds: int = 10
    plateau_para_pct: float = 0.9
    plateau_branch_pct: float = 0.8
    extended_stale_limit: int = 30


@dataclass
class SeedConfig:
    """Configuration for LLM seed generation."""

    paragraphs_per_batch: int = 10
    seeds_per_batch: int = 8
    cache: bool = True


@dataclass
class ValidationConfig:
    """Configuration for COBOL validation pass."""

    enabled: bool = False
    timeout_per_case: int = 30


@dataclass
class JITLoggingConfig:
    """Configuration for JIT observability in coverage logs."""

    enabled: bool = True
    periodic_interval_ms: int = 10000
    summary_every_requests: int = 50
    debug_min_interval_ms: int = 100
    require_target_paragraph_context: bool = True
    jit_scope_policy: str = "target_gates_plus_slice"


@dataclass
class CoverageConfig:
    """Top-level coverage configuration."""

    selector: str = "heuristic"
    default_batch_size: int = 200
    termination: TerminationConfig = field(default_factory=TerminationConfig)
    seed_generation: SeedConfig = field(default_factory=SeedConfig)
    validation: ValidationConfig = field(default_factory=ValidationConfig)
    jit_logging: JITLoggingConfig = field(default_factory=JITLoggingConfig)
    strategies: list[str] | None = None
    rounds: list[RoundConfig] | None = None
    loop_from: int = 0
    strategy_params: dict[str, dict[str, Any]] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# YAML loader
# ---------------------------------------------------------------------------

def load_config(path: str | Path | None) -> CoverageConfig:
    """Load config from a YAML file, or return defaults.

    Uses only stdlib — falls back to a minimal YAML subset parser if
    PyYAML is not installed.
    """
    if path is None:
        return CoverageConfig()

    path = Path(path)
    if not path.exists():
        log.warning("Coverage config not found: %s — using defaults", path)
        return CoverageConfig()

    text = path.read_text()
    data = _parse_yaml(text)
    if not isinstance(data, dict):
        log.warning("Coverage config is not a dict — using defaults")
        return CoverageConfig()

    return _build_config(data)


def _parse_yaml(text: str) -> Any:
    """Parse YAML, preferring PyYAML if available, else json fallback."""
    try:
        import yaml
        return yaml.safe_load(text)
    except ImportError:
        pass
    # Minimal fallback: try JSON (YAML is a superset of JSON)
    import json
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        log.warning("Could not parse config (install PyYAML for full YAML support)")
        return {}


def _build_config(data: dict) -> CoverageConfig:
    """Build a CoverageConfig from parsed YAML dict."""
    term_data = data.get("termination", {})
    termination = TerminationConfig(
        max_stale_rounds=int(term_data.get("max_stale_rounds", 10)),
        plateau_para_pct=float(term_data.get("plateau_para_pct", 0.9)),
        plateau_branch_pct=float(term_data.get("plateau_branch_pct", 0.8)),
        extended_stale_limit=int(term_data.get("extended_stale_limit", 30)),
    )

    seed_data = data.get("seed_generation", {})
    seed_generation = SeedConfig(
        paragraphs_per_batch=int(seed_data.get("paragraphs_per_batch", 10)),
        seeds_per_batch=int(seed_data.get("seeds_per_batch", 8)),
        cache=bool(seed_data.get("cache", True)),
    )

    val_data = data.get("validation", {})
    validation = ValidationConfig(
        enabled=bool(val_data.get("enabled", False)),
        timeout_per_case=int(val_data.get("timeout_per_case", 30)),
    )

    jit_data = data.get("jit_logging", {})
    jit_logging = JITLoggingConfig(
        enabled=bool(jit_data.get("enabled", True)),
        periodic_interval_ms=int(jit_data.get("periodic_interval_ms", 10000)),
        summary_every_requests=int(jit_data.get("summary_every_requests", 50)),
        debug_min_interval_ms=int(jit_data.get("debug_min_interval_ms", 100)),
        require_target_paragraph_context=bool(
            jit_data.get("require_target_paragraph_context", True)
        ),
        jit_scope_policy=str(
            jit_data.get("jit_scope_policy", "target_gates_plus_slice")
        ),
    )

    rounds = None
    raw_rounds = data.get("rounds")
    if isinstance(raw_rounds, list):
        rounds = []
        for r in raw_rounds:
            if isinstance(r, dict) and "strategy" in r:
                rounds.append(RoundConfig(
                    strategy=str(r["strategy"]),
                    batch_size=int(r["batch_size"]) if r.get("batch_size") else None,
                    params=dict(r.get("params", {})),
                ))

    strategies = None
    raw_strategies = data.get("strategies")
    if isinstance(raw_strategies, list):
        strategies = [str(s) for s in raw_strategies]

    return CoverageConfig(
        selector=str(data.get("selector", "heuristic")),
        default_batch_size=int(data.get("default_batch_size", 200)),
        termination=termination,
        seed_generation=seed_generation,
        validation=validation,
        jit_logging=jit_logging,
        strategies=strategies,
        rounds=rounds,
        loop_from=int(data.get("loop_from", 0)),
        strategy_params=dict(data.get("strategy_params", {})),
    )


# ---------------------------------------------------------------------------
# Strategy registry and builder
# ---------------------------------------------------------------------------

def _get_strategy_registry() -> dict[str, Any]:
    """Build the strategy name → factory mapping.

    Imported lazily to avoid circular imports.
    """
    from .coverage_strategies import (
        BaselineStrategy,
        CorpusFuzzStrategy,
        DirectParagraphStrategy,
        FaultInjectionStrategy,
        TranscriptSearchStrategy,
    )

    return {
        "baseline": lambda **kw: BaselineStrategy(),
        "direct_paragraph": lambda **kw: DirectParagraphStrategy(),
        "transcript_search": lambda **kw: TranscriptSearchStrategy(),
        "corpus_fuzz": lambda **kw: CorpusFuzzStrategy(),
        "fault_injection": lambda **kw: FaultInjectionStrategy(),
    }


def build_strategies(
    config: CoverageConfig,
    llm_provider=None,
    llm_model: str | None = None,
) -> list:
    """Instantiate Strategy objects from config.

    If config.strategies is set, only those strategies are instantiated.
    If config.rounds is set, strategies are instantiated from the unique
    strategy names in the round sequence.
    If neither is set, returns the default set.
    """
    registry = _get_strategy_registry()

    # Determine which strategy names to instantiate
    if config.rounds:
        names = list(dict.fromkeys(r.strategy for r in config.rounds))
    elif config.strategies:
        names = list(config.strategies)
    else:
        # Default set
        names = [
            "baseline", "direct_paragraph", "transcript_search", "corpus_fuzz", "fault_injection",
        ]

    strategies = []
    for name in names:
        factory = registry.get(name)
        if factory is None:
            log.warning("Unknown strategy '%s' in config — skipping", name)
            continue

        # Merge global strategy_params with per-round params
        params = dict(config.strategy_params.get(name, {}))
        # Add LLM context
        params["llm_provider"] = llm_provider
        params["llm_model"] = llm_model

        try:
            strategy = factory(**params)
            strategies.append(strategy)
        except Exception as e:
            log.warning("Failed to instantiate strategy '%s': %s", name, e)

    return strategies


def build_selector(
    config: CoverageConfig,
    llm_provider=None,
    llm_model: str | None = None,
    var_report=None,
):
    """Instantiate the appropriate StrategySelector from config."""
    from .coverage_strategies import HeuristicSelector

    return HeuristicSelector(default_batch_size=config.default_batch_size)
