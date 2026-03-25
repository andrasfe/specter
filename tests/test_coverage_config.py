"""Tests for pluggable coverage strategy configuration."""

import tempfile
from pathlib import Path

import pytest

from specter.coverage_config import (
    CoverageConfig,
    RoundConfig,
    TerminationConfig,
    build_strategies,
    load_config,
)


class TestLoadConfig:
    def test_none_returns_defaults(self):
        cfg = load_config(None)
        assert cfg.selector == "heuristic"
        assert cfg.default_batch_size == 200
        assert cfg.rounds is None
        assert cfg.strategies is None

    def test_nonexistent_file_returns_defaults(self):
        cfg = load_config("/nonexistent/config.yaml")
        assert cfg.selector == "heuristic"

    def test_json_config(self):
        import json
        data = {
            "selector": "llm",
            "default_batch_size": 500,
            "strategies": ["baseline", "direct_paragraph", "monte_carlo"],
            "termination": {
                "max_stale_rounds": 5,
                "plateau_para_pct": 0.95,
            },
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            path = f.name

        cfg = load_config(path)
        Path(path).unlink()

        assert cfg.selector == "llm"
        assert cfg.default_batch_size == 500
        assert cfg.strategies == ["baseline", "direct_paragraph", "monte_carlo"]
        assert cfg.termination.max_stale_rounds == 5
        assert cfg.termination.plateau_para_pct == 0.95
        assert cfg.termination.plateau_branch_pct == 0.8  # default

    def test_yaml_config(self):
        yaml_text = """\
selector: heuristic
default_batch_size: 300
rounds:
  - strategy: baseline
    batch_size: 500
  - strategy: direct_paragraph
    batch_size: 5000
  - strategy: fault_injection
  - strategy: monte_carlo
    batch_size: 2000
loop_from: 1
strategy_params:
  llm_runtime:
    max_calls: 10
termination:
  max_stale_rounds: 15
  extended_stale_limit: 50
"""
        try:
            import yaml
        except ImportError:
            pytest.skip("PyYAML not installed")

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_text)
            path = f.name

        cfg = load_config(path)
        Path(path).unlink()

        assert cfg.default_batch_size == 300
        assert len(cfg.rounds) == 4
        assert cfg.rounds[0].strategy == "baseline"
        assert cfg.rounds[0].batch_size == 500
        assert cfg.rounds[2].strategy == "fault_injection"
        assert cfg.rounds[2].batch_size is None
        assert cfg.loop_from == 1
        assert cfg.strategy_params["llm_runtime"]["max_calls"] == 10
        assert cfg.termination.max_stale_rounds == 15
        assert cfg.termination.extended_stale_limit == 50


class TestBuildStrategies:
    def test_default_no_llm(self):
        cfg = CoverageConfig()
        strategies = build_strategies(cfg)
        names = [s.name for s in strategies]
        assert "baseline" in names
        assert "direct_paragraph" in names
        assert "fault_injection" in names

    def test_explicit_strategies_list(self):
        cfg = CoverageConfig(strategies=["baseline", "fault_injection"])
        strategies = build_strategies(cfg)
        names = [s.name for s in strategies]
        assert names == ["baseline", "fault_injection"]

    def test_from_rounds(self):
        cfg = CoverageConfig(rounds=[
            RoundConfig(strategy="baseline"),
            RoundConfig(strategy="fault_injection"),
            RoundConfig(strategy="baseline"),  # duplicate
        ])
        strategies = build_strategies(cfg)
        names = [s.name for s in strategies]
        # Deduped: baseline, fault_injection
        assert "baseline" in names
        assert "fault_injection" in names
        assert len(names) == 2

    def test_unknown_strategy_skipped(self):
        cfg = CoverageConfig(strategies=["baseline", "nonexistent", "fault_injection"])
        strategies = build_strategies(cfg)
        names = [s.name for s in strategies]
        assert "baseline" in names
        assert "fault_injection" in names
        assert len(names) == 2

    def test_unknown_strategy_all_skipped(self):
        cfg = CoverageConfig(strategies=["nonexistent", "also_missing"])
        strategies = build_strategies(cfg)
        assert len(strategies) == 0


class TestTerminationConfig:
    def test_defaults(self):
        t = TerminationConfig()
        assert t.max_stale_rounds == 10
        assert t.plateau_para_pct == 0.9
        assert t.plateau_branch_pct == 0.8
        assert t.extended_stale_limit == 30

    def test_custom(self):
        t = TerminationConfig(max_stale_rounds=5, plateau_branch_pct=0.95)
        assert t.max_stale_rounds == 5
        assert t.plateau_branch_pct == 0.95


class TestRoundConfig:
    def test_basic(self):
        r = RoundConfig(strategy="baseline", batch_size=500)
        assert r.strategy == "baseline"
        assert r.batch_size == 500
        assert r.params == {}

    def test_with_params(self):
        r = RoundConfig(strategy="llm_runtime", params={"max_calls": 10})
        assert r.params["max_calls"] == 10
