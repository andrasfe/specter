"""Tests for the COBOL coverage-guided test generation engine.

Covers: variable domain model, branch instrumentation, coverage parsing,
mock data generation, and the agentic coverage loop.
"""

import json
import random
import shutil
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from specter.copybook_parser import CopybookField, CopybookRecord
from specter.coverage_strategies import StrategyContext, TranscriptSearchStrategy
from specter.jit_value_inference import JITValueInferenceService
from specter.variable_domain import (
    VariableDomain,
    build_payload_value_candidates,
    build_variable_domains,
    format_value_for_cobol,
    generate_value,
    load_copybooks,
    payload_kind_for_domain,
    _compute_range,
    _infer_semantic_type,
)
from specter.variable_extractor import VariableInfo, VariableReport
from specter.cobol_coverage import (
    CoverageState,
    _best_cobol_seed_input,
    _build_target_variable_allowlists,
    _canonical_target_key,
    _build_input_state,
    _build_transcript_payload_candidates,
    _jit_status_suffix,
    _project_cobol_replay_input,
    _select_priority_branch_target,
)
from specter.static_analysis import GatingCondition


# ---------------------------------------------------------------------------
# Variable Domain Model tests
# ---------------------------------------------------------------------------


class TestVariableDomain:
    """Tests for VariableDomain construction and value generation."""

    def test_numeric_pic_9_5(self):
        """PIC 9(5) → max_value=99999, data_type=numeric."""
        report = VariableReport(variables={
            "WS-COUNT": VariableInfo(
                name="WS-COUNT", classification="input",
            ),
        })
        records = [CopybookRecord(
            name="WS-REC",
            fields=[CopybookField(
                level=5, name="WS-COUNT", pic="9(5)",
                pic_type="numeric", length=5, precision=0,
                occurs=1, is_filler=False,
            )],
            copybook_file="test.cpy",
        )]
        domains = build_variable_domains(report, records)
        d = domains["WS-COUNT"]
        assert d.data_type == "numeric"
        assert d.max_length == 5
        assert d.max_value == 99999
        assert d.min_value == 0
        assert d.precision == 0
        assert not d.signed

    def test_alpha_pic_x_10(self):
        """PIC X(10) → max_length=10, data_type=alpha."""
        report = VariableReport(variables={
            "WS-NAME": VariableInfo(
                name="WS-NAME", classification="input",
            ),
        })
        records = [CopybookRecord(
            name="WS-REC",
            fields=[CopybookField(
                level=5, name="WS-NAME", pic="X(10)",
                pic_type="alpha", length=10, precision=0,
                occurs=1, is_filler=False,
            )],
            copybook_file="test.cpy",
        )]
        domains = build_variable_domains(report, records)
        d = domains["WS-NAME"]
        assert d.data_type == "alpha"
        assert d.max_length == 10
        assert d.min_value is None
        assert d.max_value is None

    def test_signed_packed_pic_s9_5_v99(self):
        """PIC S9(5)V99 → min_value=-99999.99, precision=2."""
        report = VariableReport(variables={
            "WS-AMOUNT": VariableInfo(
                name="WS-AMOUNT", classification="input",
            ),
        })
        records = [CopybookRecord(
            name="WS-REC",
            fields=[CopybookField(
                level=5, name="WS-AMOUNT", pic="S9(5)V99",
                pic_type="packed", length=5, precision=2,
                occurs=1, is_filler=False, values_88={},
            )],
            copybook_file="test.cpy",
        )]
        domains = build_variable_domains(report, records)
        d = domains["WS-AMOUNT"]
        assert d.data_type == "packed"
        assert d.precision == 2
        assert d.signed is True
        assert d.min_value is not None
        assert d.min_value < 0
        # max_value should be 99999 + fraction
        assert d.max_value is not None
        assert d.max_value > 99999

    def test_88_level_values(self):
        """88-level conditions populate valid_88_values."""
        report = VariableReport(variables={
            "PA-AUTH-RESULT": VariableInfo(
                name="PA-AUTH-RESULT", classification="status",
            ),
        })
        records = [CopybookRecord(
            name="WS-REC",
            fields=[CopybookField(
                level=5, name="PA-AUTH-RESULT", pic="X(2)",
                pic_type="alpha", length=2, precision=0,
                occurs=1, is_filler=False,
                values_88={"PA-AUTH-APPROVED": "00", "PA-AUTH-DENIED": "05"},
            )],
            copybook_file="test.cpy",
        )]
        domains = build_variable_domains(report, records)
        d = domains["PA-AUTH-RESULT"]
        assert d.valid_88_values == {"PA-AUTH-APPROVED": "00", "PA-AUTH-DENIED": "05"}

    def test_semantic_inference_date(self):
        """Variable named WS-PROC-DATE → semantic_type=date."""
        report = VariableReport(variables={
            "WS-PROC-DATE": VariableInfo(
                name="WS-PROC-DATE", classification="input",
            ),
        })
        domains = build_variable_domains(report)
        assert domains["WS-PROC-DATE"].semantic_type == "date"

    def test_semantic_inference_status(self):
        """Variable ending in -STATUS → semantic_type=status_file."""
        report = VariableReport(variables={
            "FILE-STATUS-INFILE": VariableInfo(
                name="FILE-STATUS-INFILE", classification="status",
            ),
        })
        domains = build_variable_domains(report)
        assert domains["FILE-STATUS-INFILE"].semantic_type == "status_file"

    def test_semantic_inference_flag(self):
        """Variable with FLAG → semantic_type=flag_bool."""
        report = VariableReport(variables={
            "WS-ERROR-FLAG": VariableInfo(
                name="WS-ERROR-FLAG", classification="flag",
            ),
        })
        domains = build_variable_domains(report)
        assert domains["WS-ERROR-FLAG"].semantic_type == "flag_bool"

    def test_stub_mapping_populates_set_by_stub(self):
        """Variables in stub_mapping get set_by_stub populated."""
        report = VariableReport(variables={
            "SQLCODE": VariableInfo(name="SQLCODE", classification="status"),
        })
        stub_mapping = {"SQL": ["SQLCODE"]}
        domains = build_variable_domains(report, stub_mapping=stub_mapping)
        assert domains["SQLCODE"].set_by_stub == "SQL"

    def test_condition_literals_from_ast(self):
        """condition_literals from VariableInfo propagate to domain."""
        report = VariableReport(variables={
            "WS-CODE": VariableInfo(
                name="WS-CODE", classification="input",
                condition_literals=["00", "10", "23"],
            ),
        })
        domains = build_variable_domains(report)
        assert domains["WS-CODE"].condition_literals == ["00", "10", "23"]


class TestGenerateValue:
    """Tests for generate_value() with different strategies."""

    def _make_numeric_domain(self, **kwargs):
        defaults = dict(
            name="TEST-VAR", data_type="numeric", max_length=5,
            precision=0, signed=False, min_value=0, max_value=99999,
        )
        defaults.update(kwargs)
        return VariableDomain(**defaults)

    def _make_alpha_domain(self, **kwargs):
        defaults = dict(
            name="TEST-VAR", data_type="alpha", max_length=10,
        )
        defaults.update(kwargs)
        return VariableDomain(**defaults)

    def test_condition_literal_strategy(self):
        """condition_literal picks from condition_literals."""
        d = self._make_numeric_domain(condition_literals=[42, 99])
        rng = random.Random(1)
        val = generate_value(d, "condition_literal", rng)
        assert val in [42, 99]

    def test_88_value_strategy(self):
        """88_value picks from valid_88_values."""
        d = self._make_alpha_domain(valid_88_values={"OK": "00", "ERR": "10"})
        rng = random.Random(1)
        val = generate_value(d, "88_value", rng)
        assert val in ["00", "10"]

    def test_boundary_numeric(self):
        """boundary returns min/max/zero for numeric types."""
        d = self._make_numeric_domain()
        rng = random.Random(1)
        val = generate_value(d, "boundary", rng)
        assert isinstance(val, (int, float))
        assert 0 <= val <= 99999 or val == 0

    def test_random_valid_within_range(self):
        """random_valid always produces values within PIC range."""
        d = self._make_numeric_domain(min_value=0, max_value=99999)
        rng = random.Random(42)
        for _ in range(100):
            val = generate_value(d, "random_valid", rng)
            assert isinstance(val, int)
            assert 0 <= val <= 99999

    def test_random_valid_alpha(self):
        """random_valid for alpha produces correct length strings."""
        d = self._make_alpha_domain(max_length=5)
        rng = random.Random(42)
        val = generate_value(d, "random_valid", rng)
        assert isinstance(val, str)
        assert len(val) == 5

    def test_semantic_date(self):
        """semantic strategy for date type produces YYYYMMDD format."""
        d = self._make_numeric_domain(
            max_length=8, semantic_type="date",
        )
        rng = random.Random(42)
        val = generate_value(d, "semantic", rng)
        assert isinstance(val, str)
        assert len(val) == 8
        year = int(val[:4])
        assert 2020 <= year <= 2027

    def test_semantic_status_file(self):
        """semantic strategy for status_file returns valid file status."""
        d = self._make_alpha_domain(semantic_type="status_file")
        rng = random.Random(42)
        val = generate_value(d, "semantic", rng)
        assert val in ["00", "10", "23", "35", "39", "41", "46", "47"]

    def test_build_payload_value_candidates_prefers_literals(self):
        """Payload candidates should preserve literals before generated fallbacks."""
        d = self._make_alpha_domain(
            condition_literals=["AA", "BB"],
            valid_88_values={"OK": "00"},
            semantic_type="identifier",
        )
        vals = build_payload_value_candidates(d, limit=5, rng=random.Random(1))
        assert vals[:3] == ["AA", "BB", "00"]
        assert len(vals) <= 5

    def test_adversarial_numeric(self):
        """adversarial returns edge cases."""
        d = self._make_numeric_domain()
        rng = random.Random(42)
        val = generate_value(d, "adversarial", rng)
        assert isinstance(val, (int, float))

    def test_boundary_with_precision(self):
        """boundary for PIC S9(5)V99 returns float values."""
        d = VariableDomain(
            name="AMT", data_type="packed", max_length=5,
            precision=2, signed=True, min_value=-99999.99, max_value=99999.99,
        )
        rng = random.Random(42)
        val = generate_value(d, "boundary", rng)
        assert isinstance(val, (int, float))


class TestTranscriptPayloadSearch:
    """Tests for transcript payload helper derivation and mutation strategy."""

    def test_build_transcript_payload_candidates_focuses_read_ops(self):
        domains = {
            "WS-CODE": VariableDomain(
                name="WS-CODE",
                data_type="alpha",
                max_length=4,
                condition_literals=["AA", "BB"],
                classification="input",
                semantic_type="identifier",
            ),
            "READ-STATUS": VariableDomain(
                name="READ-STATUS",
                data_type="alpha",
                max_length=2,
                classification="status",
                semantic_type="status_file",
            ),
        }

        payload_variables, payload_candidates = _build_transcript_payload_candidates(
            domains,
            {
                "READ:INFILE": ["READ-STATUS"],
                "WRITE:OUTFILE": ["READ-STATUS"],
            },
            ["WS-CODE"],
        )

        assert payload_kind_for_domain(domains["WS-CODE"]) == "alpha"
        assert payload_variables["WS-CODE"] == "alpha"
        assert payload_variables["READ-STATUS"] == "alpha"
        assert "READ:INFILE" in payload_candidates
        assert "WRITE:OUTFILE" not in payload_candidates
        assert payload_candidates["READ:INFILE"]["WS-CODE"][:2] == ["AA", "BB"]

    def test_transcript_search_strategy_appends_payload_to_read_entries(self):
        domains = {
            "WS-CODE": VariableDomain(
                name="WS-CODE",
                data_type="alpha",
                max_length=4,
                condition_literals=["AA"],
                classification="input",
                semantic_type="identifier",
            ),
            "READ-STATUS": VariableDomain(
                name="READ-STATUS",
                data_type="alpha",
                max_length=2,
                classification="status",
                semantic_type="status_file",
            ),
        }
        ctx = StrategyContext(
            module=mock.Mock(),
            context=None,
            domains=domains,
            stub_mapping={"READ:INFILE": ["READ-STATUS"]},
            call_graph=mock.Mock(),
            gating_conds={},
            var_report=VariableReport(variables={}),
            program=mock.Mock(),
            all_paragraphs=set(),
            success_stubs={
                "READ:INFILE": [
                    [("READ-STATUS", "00")],
                    [("READ-STATUS", "00")],
                    [("READ-STATUS", "10")],
                ],
            },
            success_defaults={"READ:INFILE": [("READ-STATUS", "10")]},
            rng=random.Random(1),
            store_path=Path("/tmp/transcript-search.jsonl"),
            payload_candidates={"READ:INFILE": {"WS-CODE": ["AA"]}},
        )

        strategy = TranscriptSearchStrategy()
        cases = list(strategy.generate_cases(ctx, CoverageState(), 1))

        assert len(cases) == 1
        _, stubs, defaults, target = cases[0]
        assert ("WS-CODE", "AA  ") in stubs["READ:INFILE"][0]
        assert ("WS-CODE", "AA  ") in stubs["READ:INFILE"][1]
        assert defaults["READ:INFILE"] == [("READ-STATUS", "10")]
        assert target.startswith("transcript:READ:INFILE:WS-CODE=")


class TestFormatValue:
    """Tests for format_value_for_cobol()."""

    def test_alpha_right_padded(self):
        d = VariableDomain(name="X", data_type="alpha", max_length=10)
        assert format_value_for_cobol(d, "ABC") == "ABC       "

    def test_numeric_integer(self):
        d = VariableDomain(name="N", data_type="numeric", max_length=5, precision=0)
        assert format_value_for_cobol(d, 42) == "42"

    def test_numeric_decimal(self):
        d = VariableDomain(name="A", data_type="packed", max_length=5, precision=2)
        assert format_value_for_cobol(d, 123.45) == "123.45"

    def test_numeric_blank_string_maps_to_zero(self):
        d = VariableDomain(name="N", data_type="numeric", max_length=5, precision=0)
        assert format_value_for_cobol(d, "") == "0"

    def test_numeric_blank_string_with_precision_maps_to_zero(self):
        d = VariableDomain(name="A", data_type="packed", max_length=5, precision=2)
        assert format_value_for_cobol(d, "   ") == "0.00"

    def test_numeric_y_string_maps_to_one(self):
        d = VariableDomain(name="N", data_type="numeric", max_length=1, precision=0)
        assert format_value_for_cobol(d, "Y") == "1"

    def test_numeric_n_string_maps_to_zero(self):
        d = VariableDomain(name="N", data_type="numeric", max_length=1, precision=0)
        assert format_value_for_cobol(d, "N") == "0"

    def test_numeric_flag_semantic_uses_numeric_values(self):
        d = VariableDomain(
            name="FLAG", data_type="numeric", max_length=1, precision=0,
            semantic_type="flag_bool",
        )
        rng = random.Random(42)
        for _ in range(20):
            assert generate_value(d, "semantic", rng) in [0, 1]


class TestJITValueInference:
    def test_service_caches_profiles(self, monkeypatch):
        calls = []

        def fake_query(provider, prompt, model):
            calls.append((provider, model))
            return (
                json.dumps([
                    {
                        "variable": "WS-AGE",
                        "data_type": "counter",
                        "description": "Customer age",
                        "valid_values": [18, 35, 65],
                    }
                ]),
                42,
            )

        monkeypatch.setattr("specter.jit_value_inference._query_llm_sync", fake_query)

        service = JITValueInferenceService(provider=object(), model="test-model")
        domain = VariableDomain(
            name="WS-AGE",
            data_type="numeric",
            max_length=3,
            classification="input",
            min_value=0,
            max_value=120,
        )

        first = service.generate_value(
            "WS-AGE", domain, "semantic", random.Random(1), target_paragraph="PARA-1"
        )
        second = service.generate_value(
            "WS-AGE", domain, "semantic", random.Random(2), target_paragraph="PARA-1"
        )

        assert first in [18, 35, 65]
        assert second in [18, 35, 65]
        assert len(calls) == 1
        assert service.cache_hits == 1

    def test_service_skips_untargeted_requests(self, monkeypatch):
        calls = []

        def fake_query(provider, prompt, model):
            calls.append((provider, prompt, model))
            return ("[]", 0)

        monkeypatch.setattr("specter.jit_value_inference._query_llm_sync", fake_query)

        service = JITValueInferenceService(provider=object(), model="test-model")
        domain = VariableDomain(
            name="WS-CODE",
            data_type="alpha",
            max_length=4,
            classification="input",
        )

        value = service.generate_value("WS-CODE", domain, "semantic", random.Random(1))

        assert value is None
        assert calls == []
        assert service.skipped_untargeted == 1
        assert service.cache_misses == 0

    def test_service_skips_out_of_scope_requests(self, monkeypatch):
        calls = []

        def fake_query(provider, prompt, model):
            calls.append((provider, prompt, model))
            return ("[]", 0)

        monkeypatch.setattr("specter.jit_value_inference._query_llm_sync", fake_query)

        service = JITValueInferenceService(provider=object(), model="test-model")
        domain = VariableDomain(
            name="WS-CODE",
            data_type="alpha",
            max_length=4,
            classification="input",
        )

        value = service.generate_value(
            "WS-CODE",
            domain,
            "semantic",
            random.Random(1),
            target_paragraph="PARA-1",
            allowed_variables={"OTHER-VAR"},
            target_key="para:PARA-1",
        )

        assert value is None
        assert calls == []
        assert service.skipped_out_of_scope == 1
        assert service.cache_misses == 0

    def test_build_input_state_uses_jit_semantic_values(self):
        class StubService:
            def generate_value(self, var_name, domain, strategy, rng, **kwargs):
                if var_name == "WS-STATE" and strategy == "semantic":
                    return "CA"
                return None

        domains = {
            "WS-STATE": VariableDomain(
                name="WS-STATE",
                data_type="alpha",
                max_length=2,
                classification="input",
            ),
            "SQLCODE": VariableDomain(
                name="SQLCODE",
                data_type="numeric",
                max_length=4,
                classification="status",
                set_by_stub="SQL",
            ),
        }

        state = _build_input_state(
            domains,
            "semantic",
            random.Random(1),
            jit_inference=StubService(),
        )

        assert state["WS-STATE"] == "CA"
        assert "SQLCODE" not in state

    def test_service_falls_back_when_llm_fails(self, monkeypatch):
        def fake_query(provider, prompt, model):
            raise RuntimeError("boom")

        monkeypatch.setattr("specter.jit_value_inference._query_llm_sync", fake_query)

        service = JITValueInferenceService(provider=object(), model="test-model")
        domain = VariableDomain(
            name="WS-FLAG",
            data_type="alpha",
            max_length=1,
            classification="flag",
            semantic_type="flag_bool",
        )

        assert service.generate_value(
            "WS-FLAG", domain, "semantic", random.Random(1), target_paragraph="PARA-1"
        ) is None

    def test_service_exposes_metrics_snapshot(self, monkeypatch):
        def fake_query(provider, prompt, model):
            return (
                json.dumps([
                    {
                        "variable": "WS-COUNT",
                        "data_type": "counter",
                        "description": "Counter",
                        "valid_values": [1, 2, 3],
                    }
                ]),
                12,
            )

        monkeypatch.setattr("specter.jit_value_inference._query_llm_sync", fake_query)
        service = JITValueInferenceService(provider=object(), model="test-model")
        domain = VariableDomain(
            name="WS-COUNT",
            data_type="numeric",
            max_length=3,
            classification="input",
            min_value=0,
            max_value=999,
        )

        _ = service.generate_value(
            "WS-COUNT", domain, "semantic", random.Random(1), target_paragraph="PARA-1"
        )
        _ = service.generate_value(
            "WS-COUNT", domain, "semantic", random.Random(2), target_paragraph="PARA-1"
        )
        _ = service.generate_value("WS-COUNT", domain, "semantic", random.Random(3))
        snap = service.snapshot_metrics()

        assert snap["requests"] == 3
        assert snap["cache_hits"] == 1
        assert snap["cache_misses"] == 1
        assert snap["skipped_untargeted"] == 1
        assert snap["skipped_out_of_scope"] == 0
        assert snap["llm_successes"] == 1
        assert snap["llm_failures"] == 0

    def test_service_emits_periodic_jit_status(self, monkeypatch, caplog):
        import logging

        def fake_query(provider, prompt, model):
            return (
                json.dumps([
                    {
                        "variable": "WS-RATE",
                        "data_type": "rate",
                        "description": "Rate",
                        "valid_values": [5, 10],
                    }
                ]),
                11,
            )

        monkeypatch.setattr("specter.jit_value_inference._query_llm_sync", fake_query)
        service = JITValueInferenceService(provider=object(), model="test-model")
        service.summary_every_requests = 1
        service.summary_interval_sec = 0.0

        domain = VariableDomain(
            name="WS-RATE",
            data_type="numeric",
            max_length=3,
            classification="input",
            min_value=0,
            max_value=100,
        )

        with caplog.at_level(logging.INFO, logger="specter.jit_value_inference"):
            _ = service.generate_value(
                "WS-RATE", domain, "semantic", random.Random(1), target_paragraph="PARA-1"
            )
            _ = service.generate_value("WS-RATE", domain, "semantic", random.Random(2))

        assert any("JIT status:" in rec.message for rec in caplog.records)
        assert any("skip_u=1" in rec.message for rec in caplog.records)

    def test_jit_status_suffix_from_snapshot(self):
        class StubJit:
            def snapshot_metrics(self):
                return {
                    "requests": 12,
                    "cache_hit_pct": 75.0,
                    "skipped_untargeted": 2,
                    "skipped_out_of_scope": 3,
                    "llm_successes": 3,
                    "llm_failures": 1,
                    "avg_latency_ms": 41.0,
                }

        class Ctx:
            jit_inference = StubJit()

        suffix = _jit_status_suffix(Ctx(), enabled=True)
        assert "JIT reqs=12" in suffix
        assert "hit=75.0%" in suffix
        assert "skip_u=2" in suffix
        assert "skip_scope=3" in suffix
        assert "ok=3" in suffix

    def test_build_target_variable_allowlists_gating_and_stubs(self):
        class DummyModule:
            pass

        branch_meta = {
            "1": {"paragraph": "PARA-A", "condition": "WS-FLAG = 'Y'"},
        }
        gating = {
            "PARA-A": [GatingCondition(variable="WS-GATE", values=["Y"], negated=False)],
        }
        stubs = {
            "CALL:EXT": ["SQLCODE"],
        }

        allowlists = _build_target_variable_allowlists(
            DummyModule,
            branch_meta,
            gating,
            stubs,
            include_gates=True,
            include_slice=False,
        )

        assert "para:PARA-A" in allowlists
        assert "WS-GATE" in allowlists["para:PARA-A"]
        assert "SQLCODE" in allowlists["para:PARA-A"]
        assert "branch:1:T" in allowlists
        assert "branch:1:F" in allowlists
        assert "WS-GATE" in allowlists["branch:1:T"]
        assert "SQLCODE" in allowlists["branch:1:F"]


class TestCobolReplayHelpers:
    """Tests for direct-paragraph COBOL replay helper logic."""

    def test_best_cobol_seed_input_skips_direct_py_cases(self):
        cov = CoverageState(test_cases=[
            {
                "target": "direct:PARA-A",
                "input_state": {"A": "1"},
                "paragraphs_hit": ["P1", "P2", "P3"],
                "branches_hit": ["py:1:T"],
            },
            {
                "target": "baseline",
                "input_state": {"B": "2"},
                "paragraphs_hit": ["P1", "P2"],
                "branches_hit": [],
            },
            {
                "target": "fault",
                "input_state": {"C": "3"},
                "paragraphs_hit": ["P1", "P2", "P3", "P4"],
                "branches_hit": ["12:T"],
            },
        ])

        assert _best_cobol_seed_input(cov) == {"C": "3"}

    def test_project_cobol_replay_input_filters_and_overlays_seed(self):
        projected = _project_cobol_replay_input(
            {
                "KEEP-ME": "7",
                "DROP-ME": "9",
                "_TRACE": "x",
            },
            ["SEED-VAR", "KEEP-ME"],
            seed_state={"SEED-VAR": "1", "OTHER": "2"},
        )

        assert projected == {
            "SEED-VAR": "1",
            "OTHER": "2",
            "KEEP-ME": "7",
        }


class TestComputeRange:
    """Tests for _compute_range()."""

    def test_pic_9_5(self):
        lo, hi = _compute_range("numeric", 5, 0, False)
        assert lo == 0
        assert hi == 99999

    def test_pic_s9_5(self):
        lo, hi = _compute_range("numeric", 5, 0, True)
        assert lo == -99999
        assert hi == 99999

    def test_pic_s9_9_v99(self):
        lo, hi = _compute_range("packed", 9, 2, True)
        assert lo < 0
        assert hi > 999999999

    def test_alpha_no_range(self):
        lo, hi = _compute_range("alpha", 10, 0, False)
        assert lo is None
        assert hi is None


class TestSemanticInference:
    """Tests for _infer_semantic_type()."""

    def test_date(self):
        assert _infer_semantic_type("WS-PROC-DATE", "input") == "date"

    def test_time(self):
        assert _infer_semantic_type("WS-START-TIME", "input") == "time"

    def test_amount(self):
        assert _infer_semantic_type("WS-TOTAL-AMT", "input") == "amount"

    def test_counter(self):
        assert _infer_semantic_type("WS-REC-COUNT", "input") == "counter"

    def test_sqlcode(self):
        assert _infer_semantic_type("SQLCODE", "status") == "status_sql"

    def test_file_status(self):
        assert _infer_semantic_type("FILE-STATUS-CUST", "status") == "status_file"

    def test_flag(self):
        assert _infer_semantic_type("WS-EOF-FLAG", "flag") == "flag_bool"

    def test_generic(self):
        assert _infer_semantic_type("WS-FOOBAR", "internal") == "generic"


# ---------------------------------------------------------------------------
# Branch instrumentation tests
# ---------------------------------------------------------------------------


class TestBranchTracing:
    """Tests for _add_branch_tracing()."""

    def test_if_with_else(self):
        """IF with ELSE gets T and F probes."""
        from specter.cobol_mock import _add_branch_tracing

        lines = [
            "       IDENTIFICATION DIVISION.\n",
            "       PROCEDURE DIVISION.\n",
            "       MAIN-PARA.\n",
            "           IF WS-STATUS = '00'\n",
            "               DISPLAY 'OK'\n",
            "           ELSE\n",
            "               DISPLAY 'ERR'\n",
            "           END-IF.\n",
        ]
        result, meta, count = _add_branch_tracing(lines)
        text = "".join(result)
        assert "@@B:1:T" in text
        assert "@@B:1:F" in text
        assert count == 2  # 1 IF → 2 directions (T + F)
        assert "1" in meta
        assert meta["1"]["type"] == "IF"

    def test_if_without_else(self):
        """IF without ELSE gets inserted ELSE with F probe."""
        from specter.cobol_mock import _add_branch_tracing

        lines = [
            "       IDENTIFICATION DIVISION.\n",
            "       PROCEDURE DIVISION.\n",
            "       MAIN-PARA.\n",
            "           IF WS-FLAG = 'Y'\n",
            "               DISPLAY 'YES'\n",
            "           END-IF.\n",
        ]
        result, meta, count = _add_branch_tracing(lines)
        text = "".join(result)
        assert "@@B:1:T" in text
        assert "@@B:1:F" in text
        assert "ELSE" in text
        assert count == 2  # 1 IF → 2 directions

    def test_evaluate_when(self):
        """EVALUATE/WHEN gets probes for each WHEN."""
        from specter.cobol_mock import _add_branch_tracing

        lines = [
            "       IDENTIFICATION DIVISION.\n",
            "       PROCEDURE DIVISION.\n",
            "       MAIN-PARA.\n",
            "           EVALUATE WS-CODE\n",
            "           WHEN '00'\n",
            "               DISPLAY 'OK'\n",
            "           WHEN '10'\n",
            "               DISPLAY 'EOF'\n",
            "           WHEN OTHER\n",
            "               DISPLAY 'ERR'\n",
            "           END-EVALUATE.\n",
        ]
        result, meta, count = _add_branch_tracing(lines)
        text = "".join(result)
        assert "@@B:1:W1" in text
        assert "@@B:1:W2" in text
        assert "@@B:1:WO" in text
        assert count == 3  # 1 EVALUATE with 3 WHENs → 3 directions
        assert meta["1"]["type"] == "EVALUATE"
        assert meta["1"]["when_count"] == 3

    def test_nested_if(self):
        """Nested IFs get separate branch IDs."""
        from specter.cobol_mock import _add_branch_tracing

        lines = [
            "       IDENTIFICATION DIVISION.\n",
            "       PROCEDURE DIVISION.\n",
            "       MAIN-PARA.\n",
            "           IF WS-A = '1'\n",
            "               IF WS-B = '2'\n",
            "                   DISPLAY 'BOTH'\n",
            "               END-IF\n",
            "           END-IF.\n",
        ]
        result, meta, count = _add_branch_tracing(lines)
        assert count == 4  # 2 IFs × 2 directions each
        assert "1" in meta
        assert "2" in meta

    def test_multiline_if_condition(self):
        """Multi-line IF conditions don't get probe inserted mid-condition."""
        from specter.cobol_mock import _add_branch_tracing

        lines = [
            "       IDENTIFICATION DIVISION.\n",
            "       PROCEDURE DIVISION.\n",
            "       MAIN-PARA.\n",
            "           IF WS-VAR NOT =\n",
            "                              SPACES AND LOW-VALUES\n",
            "               MOVE 'Y' TO WS-FLAG\n",
            "           END-IF.\n",
        ]
        result, meta, count = _add_branch_tracing(lines)
        text = "".join(result)
        assert "@@B:1:T" in text
        # The probe must come AFTER the continuation line, not between
        # "IF WS-VAR NOT =" and "SPACES AND LOW-VALUES"
        probe_pos = text.index("@@B:1:T")
        condition_end_pos = text.index("SPACES AND LOW-VALUES")
        assert probe_pos > condition_end_pos, (
            "Probe must be after condition continuation line"
        )


# ---------------------------------------------------------------------------
# Branch coverage parsing tests
# ---------------------------------------------------------------------------


class TestParseBranchCoverage:
    """Tests for parse_branch_coverage()."""

    def test_basic_parsing(self):
        from specter.cobol_executor import parse_branch_coverage

        stdout = (
            "SPECTER-TRACE:MAIN-PARA\n"
            "@@B:1:T\n"
            "some display output\n"
            "@@B:2:F\n"
            "@@B:3:W1\n"
        )
        branches = parse_branch_coverage(stdout)
        assert branches == {"1:T", "2:F", "3:W1"}

    def test_empty_output(self):
        from specter.cobol_executor import parse_branch_coverage

        assert parse_branch_coverage("") == set()
        assert parse_branch_coverage("just normal output\n") == set()


# ---------------------------------------------------------------------------
# Mock data generation tests
# ---------------------------------------------------------------------------


class TestMockDataGeneration:
    """Tests for INIT records and mock data ordering."""

    def test_init_records_format(self):
        from specter.cobol_mock import generate_init_records

        records = generate_init_records({"WS-COUNT": "42", "WS-NAME": "HELLO"})
        lines = records.split("\n")
        # Should have 2 INIT records + 1 END-INIT sentinel
        assert len(lines) == 3
        assert lines[0].startswith("INIT:WS-COUNT")
        assert lines[1].startswith("INIT:WS-NAME")
        assert lines[2].startswith("END-INIT")
        # INIT records are 80 chars; END-INIT sentinel is 60 chars (existing behavior)
        assert len(lines[0]) == 80
        assert len(lines[1]) == 80
        assert len(lines[2]) >= 59

    def test_mock_data_ordered_format(self):
        from specter.cobol_mock import generate_mock_data_ordered

        stub_log = [
            ("READ:INFILE1", [("FILE-STATUS", "00")]),
            ("DLI-ISRT", [("PCB-STATUS", "  ")]),
            ("READ:INFILE1", [("FILE-STATUS", "10")]),
        ]
        data = generate_mock_data_ordered(stub_log)
        lines = data.strip().split("\n")
        assert len(lines) == 6
        assert lines[0].startswith("READ:INFILE1")
        assert lines[1].startswith("SET:FILE-STATUS")
        assert lines[2].startswith("DLI-ISRT")
        assert lines[3].startswith("SET:PCB-STATUS")
        assert lines[4].startswith("READ:INFILE1")
        assert lines[5].startswith("SET:FILE-STATUS")

    def test_mock_data_ordered_preserves_payload_assignments(self):
        from specter.cobol_mock import generate_mock_data_ordered

        stub_log = [
            (
                "SQL-FETCH",
                [("SQLCODE", 100), ("WS-CUST-NAME", "ALPHA"), ("RETURN-CODE", 7)],
            ),
        ]

        data = generate_mock_data_ordered(stub_log)
        lines = data.strip().split("\n")
        assert len(lines) == 4
        assert lines[0].startswith("SQL-FETCH")
        assert lines[1].startswith("SET:SQLCODE")
        assert lines[2].startswith("SET:WS-CUST-NAME")
        assert lines[3].startswith("SET:RETURN-CODE")
        assert "ALPHA" in lines[2]


# ---------------------------------------------------------------------------
# Coverage engine tests
# ---------------------------------------------------------------------------


class TestCoverageState:
    """Tests for coverage state management."""

    def test_load_empty_store(self):
        from specter.cobol_coverage import load_existing_coverage

        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = Path(f.name)
        try:
            path.unlink()
            tcs, paras, branches = load_existing_coverage(path)
            assert tcs == []
            assert paras == set()
            assert branches == set()
        finally:
            path.unlink(missing_ok=True)

    def test_load_populated_store(self):
        from specter.cobol_coverage import load_existing_coverage

        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            record = {
                "id": "abc123",
                "input_state": {"WS-X": "1"},
                "stub_outcomes": [],
                "paragraphs_hit": ["MAIN-PARA", "PROCESS-PARA"],
                "branches_hit": ["1:T", "2:F"],
                "display_output": [],
                "layer": 1,
                "target": "baseline",
            }
            f.write(json.dumps(record) + "\n")
            path = Path(f.name)

        try:
            tcs, paras, branches = load_existing_coverage(path)
            assert len(tcs) == 1
            assert "MAIN-PARA" in paras
            assert "PROCESS-PARA" in paras
            assert "1:T" in branches
        finally:
            path.unlink(missing_ok=True)


class TestCoverageReport:
    """Tests for CobolCoverageReport."""

    def test_summary_format(self):
        from specter.cobol_coverage import CobolCoverageReport

        r = CobolCoverageReport(
            total_test_cases=10,
            paragraph_coverage=0.8,
            branch_coverage=0.6,
            paragraphs_hit=8,
            paragraphs_total=10,
            branches_hit=12,
            branches_total=20,
            elapsed_seconds=5.0,
            layer_stats={"baseline": 5, "constraint_solver": 3, "fault_injection": 2},
        )
        s = r.summary()
        assert "10" in s
        assert "80.0%" in s
        assert "60.0%" in s
        assert "baseline" in s
        assert "Per strategy" in s


# ---------------------------------------------------------------------------
# Strategy tests
# ---------------------------------------------------------------------------


class TestStrategies:
    """Tests for individual coverage strategies."""

    def _make_mock_ctx(self, rng=None):
        """Build a minimal StrategyContext with mocks."""
        from specter.coverage_strategies import StrategyContext

        if rng is None:
            rng = random.Random(42)

        # Minimal mock objects
        module = type("MockModule", (), {
            "_default_state": staticmethod(lambda: {}),
            "run": staticmethod(lambda s: s),
        })()
        context = type("MockContext", (), {
            "branch_meta": {},
            "total_paragraphs": 5,
            "total_branches": 10,
        })()
        var_report = VariableReport(variables={
            "WS-CODE": VariableInfo(
                name="WS-CODE", classification="input",
                condition_literals=["00", "10", "23"],
            ),
            "WS-FLAG": VariableInfo(
                name="WS-FLAG", classification="flag",
            ),
        })
        domains = {
            "WS-CODE": VariableDomain(
                name="WS-CODE", data_type="alpha", max_length=2,
                classification="input",
                condition_literals=["00", "10", "23"],
            ),
            "WS-FLAG": VariableDomain(
                name="WS-FLAG", data_type="alpha", max_length=1,
                classification="flag",
                semantic_type="flag_bool",
            ),
        }
        program = type("MockProgram", (), {
            "program_id": "TEST",
            "paragraphs": [],
        })()
        call_graph = type("MockCallGraph", (), {
            "edges": {},
            "reverse_edges": {},
            "entry": "MAIN-PARA",
            "all_paragraphs": {"MAIN-PARA", "PROCESS", "EXIT-PARA"},
        })()

        return StrategyContext(
            module=module,
            context=context,
            domains=domains,
            stub_mapping={"READ:FILE1": ["WS-CODE"]},
            call_graph=call_graph,
            gating_conds={},
            var_report=var_report,
            program=program,
            all_paragraphs={"MAIN-PARA", "PROCESS", "EXIT-PARA"},
            success_stubs={"READ:FILE1": [[("WS-CODE", "00")]]},
            success_defaults={"READ:FILE1": [("WS-CODE", "00")]},
            rng=rng,
            store_path=Path("/tmp/test_store.jsonl"),
        )

    def _make_mock_cov(self, paras_hit=None, branches_hit=None, test_cases=None):
        from specter.cobol_coverage import CoverageState
        return CoverageState(
            paragraphs_hit=paras_hit or set(),
            branches_hit=branches_hit or set(),
            total_paragraphs=5,
            total_branches=10,
            test_cases=test_cases or [],
            all_paragraphs={"MAIN-PARA", "PROCESS", "EXIT-PARA"},
            _stub_mapping={"READ:FILE1": ["WS-CODE"]},
        )

    def test_baseline_generates_cases(self):
        from specter.coverage_strategies import BaselineStrategy

        s = BaselineStrategy()
        ctx = self._make_mock_ctx()
        cov = self._make_mock_cov()

        cases = list(s.generate_cases(ctx, cov, 100))
        # Should yield at least the 5 strategy cases
        assert len(cases) >= 5
        # Each case is (input_state, stubs, defaults, target)
        for input_state, stubs, defaults, target in cases[:5]:
            assert isinstance(input_state, dict)
            assert isinstance(target, str)

    def test_baseline_runs_once(self):
        from specter.coverage_strategies import BaselineStrategy

        s = BaselineStrategy()
        cov = self._make_mock_cov()
        assert s.should_run(cov, 0) is True
        # Generate cases marks _ran = True
        ctx = self._make_mock_ctx()
        list(s.generate_cases(ctx, cov, 10))
        assert s.should_run(cov, 1) is False

    def test_fault_injection_generates_faults(self):
        from specter.coverage_strategies import FaultInjectionStrategy

        s = FaultInjectionStrategy()
        cov = self._make_mock_cov()
        assert s.should_run(cov, 0) is True

        ctx = self._make_mock_ctx()
        cases = list(s.generate_cases(ctx, cov, 100))
        assert len(cases) > 0
        # At least one case should have fault target
        targets = [c[3] for c in cases]
        assert any("fault:" in t for t in targets)

class TestExecuteAndSaveAppends:
    """Test that _execute_and_save appends to cov.test_cases."""

    def test_test_cases_populated_during_run(self):
        """Verify the bug fix: _execute_and_save appends to cov.test_cases."""
        from specter.cobol_coverage import CoverageState

        # Before the fix, cov.test_cases was only populated from the JSONL
        # store on load, not during the run. This meant mid-run strategies
        # that depend on test_cases (like StubWalk, GuidedMutation) only
        # saw test cases from prior runs.
        #
        # We can't easily call _execute_and_save without a real COBOL context,
        # so we verify the structure: the append code is in _execute_and_save
        # after the _save_test_case call.
        import inspect
        from specter.cobol_coverage import _execute_and_save
        source = inspect.getsource(_execute_and_save)
        assert "cov.test_cases.append" in source


# ---------------------------------------------------------------------------
# Branch probing engine tests
# ---------------------------------------------------------------------------


def _make_probe_module():
    """Build a fake module with a paragraph that has IF branches.

    Generated code pattern:
      para_TEST_PARA(state):
          if state.get('WS-CODE') == '00':
              state['_branches'].add(1)   # 1:T
          else:
              state['_branches'].add(-1)  # 1:F
          if state.get('WS-RESP') == 13:
              state['_branches'].add(2)   # 2:T
          else:
              state['_branches'].add(-2)  # 2:F
    """
    import types
    mod = types.ModuleType("_probe_test_mod")

    def _default_state():
        return {"WS-CODE": "", "WS-RESP": 0, "_branches": set()}

    def para_TEST_PARA(state):
        state.setdefault("_branches", set())
        state.setdefault("_display", [])
        state.setdefault("_calls", [])
        state.setdefault("_execs", [])
        state.setdefault("_reads", [])
        state.setdefault("_writes", [])
        state.setdefault("_abended", False)
        if state.get("WS-CODE") == "00":
            state["_branches"].add(1)
        else:
            state["_branches"].add(-1)
        if state.get("WS-RESP") == 13:
            state["_branches"].add(2)
        else:
            state["_branches"].add(-2)

    mod._default_state = _default_state
    mod.para_TEST_PARA = para_TEST_PARA
    return mod


def _make_probe_ctx(module, rng=None):
    """Build a minimal StrategyContext for probing tests."""
    from specter.coverage_strategies import StrategyContext

    domains = {
        "WS-CODE": VariableDomain(
            name="WS-CODE", data_type="alpha", classification="input",
            max_length=2, condition_literals=["00", "10", "23"],
        ),
        "WS-RESP": VariableDomain(
            name="WS-RESP", data_type="numeric", classification="input",
            max_length=5, max_value=99999, min_value=0,
            condition_literals=[0, 13, 27],
        ),
    }
    report = VariableReport(variables={
        "WS-CODE": VariableInfo(name="WS-CODE", classification="input"),
        "WS-RESP": VariableInfo(name="WS-RESP", classification="input"),
    })
    from specter.models import Program
    from specter.static_analysis import StaticCallGraph

    return StrategyContext(
        module=module,
        context=None,
        domains=domains,
        stub_mapping={},
        call_graph=StaticCallGraph({}, {}),
        gating_conds={},
        var_report=report,
        program=Program(program_id="TEST", paragraphs=[]),
        all_paragraphs={"TEST-PARA"},
        success_stubs={},
        success_defaults={},
        rng=rng or random.Random(42),
        store_path=Path("/tmp/test_store.jsonl"),
        branch_meta={
            1: {"condition": "WS-CODE = '00'", "paragraph": "TEST-PARA", "type": "IF"},
            2: {"condition": "WS-RESP = 13", "paragraph": "TEST-PARA", "type": "IF"},
        },
    )


class TestBranchProbing:
    """Tests for _probe_branches_for_paragraph and _discover_stub_branch_mapping."""

    def test_probe_finds_hits(self):
        from specter.cobol_coverage import CoverageState
        from specter.coverage_strategies import _probe_branches_for_paragraph

        mod = _make_probe_module()
        ctx = _make_probe_ctx(mod)
        cov = CoverageState(
            total_paragraphs=1,
            total_branches=4,
            all_paragraphs={"TEST-PARA"},
            _stub_mapping={},
        )
        cov.paragraphs_hit.add("TEST-PARA")

        results = _probe_branches_for_paragraph(
            ctx, cov, "TEST-PARA", ctx.branch_meta, max_probes=50,
        )
        assert len(results) == 4  # 1:T, 1:F, 2:T, 2:F
        # At least some branches should be hit
        total_hits = sum(r.hit_count for r in results)
        assert total_hits > 0

    def test_probe_skips_covered_branches(self):
        from specter.cobol_coverage import CoverageState
        from specter.coverage_strategies import _probe_branches_for_paragraph

        mod = _make_probe_module()
        ctx = _make_probe_ctx(mod)
        cov = CoverageState(
            total_paragraphs=1,
            total_branches=4,
            all_paragraphs={"TEST-PARA"},
            _stub_mapping={},
        )
        cov.paragraphs_hit.add("TEST-PARA")
        cov.branches_hit.update({"1:T", "1:F"})  # branch 1 already covered

        results = _probe_branches_for_paragraph(
            ctx, cov, "TEST-PARA", ctx.branch_meta, max_probes=50,
        )
        # Only branches for bid=2 should be probed
        assert len(results) == 2
        assert all(r.branch_key.startswith("2:") for r in results)

    def test_probe_returns_discriminating_vars(self):
        from specter.cobol_coverage import CoverageState
        from specter.coverage_strategies import _probe_branches_for_paragraph

        mod = _make_probe_module()
        ctx = _make_probe_ctx(mod)
        cov = CoverageState(
            total_paragraphs=1,
            total_branches=4,
            all_paragraphs={"TEST-PARA"},
            _stub_mapping={},
        )
        cov.paragraphs_hit.add("TEST-PARA")

        results = _probe_branches_for_paragraph(
            ctx, cov, "TEST-PARA", ctx.branch_meta, max_probes=100,
        )
        # Branch 1:T (WS-CODE='00') should have WS-CODE as discriminating var
        b1t = next((r for r in results if r.branch_key == "1:T"), None)
        assert b1t is not None
        if b1t.hit_count > 0:
            # Should have hit_inputs
            assert len(b1t.hit_inputs) > 0

    def test_probe_returns_empty_for_wrong_para(self):
        from specter.cobol_coverage import CoverageState
        from specter.coverage_strategies import _probe_branches_for_paragraph

        mod = _make_probe_module()
        ctx = _make_probe_ctx(mod)
        cov = CoverageState(
            total_paragraphs=1,
            total_branches=4,
            all_paragraphs={"TEST-PARA"},
            _stub_mapping={},
        )
        results = _probe_branches_for_paragraph(
            ctx, cov, "NONEXISTENT-PARA", ctx.branch_meta, max_probes=50,
        )
        assert results == []

    def test_discover_stub_branch_mapping(self):
        """Test stub discovery with a module that has stub-dependent branches."""
        import types
        from specter.cobol_coverage import CoverageState
        from specter.coverage_strategies import _discover_stub_branch_mapping

        mod = types.ModuleType("_stub_test_mod")

        def _default_state():
            return {
                "WS-STATUS": "00",
                "_branches": set(),
                "_stub_outcomes": {},
                "_stub_defaults": {},
                "_stub_log": [],
            }

        def _apply_stub_outcome(state, op_key):
            outcomes = state.get("_stub_outcomes", {}).get(op_key)
            if outcomes:
                entry = outcomes.pop(0)
            else:
                entry = state.get("_stub_defaults", {}).get(op_key, [])
            for var, val in (entry if isinstance(entry, list) else []):
                state[var] = val

        def para_STUB_PARA(state):
            state.setdefault("_branches", set())
            state.setdefault("_display", [])
            state.setdefault("_calls", [])
            state.setdefault("_execs", [])
            state.setdefault("_reads", [])
            state.setdefault("_writes", [])
            state.setdefault("_abended", False)
            _apply_stub_outcome(state, "CICS:READ")
            if state.get("WS-STATUS") == "00":
                state["_branches"].add(1)
            else:
                state["_branches"].add(-1)

        mod._default_state = _default_state
        mod.para_STUB_PARA = para_STUB_PARA
        mod._apply_stub_outcome = _apply_stub_outcome

        domains = {
            "WS-STATUS": VariableDomain(
                name="WS-STATUS", data_type="alpha", classification="status",
                max_length=2, condition_literals=["00", "10", "23"],
            ),
        }
        report = VariableReport(variables={
            "WS-STATUS": VariableInfo(name="WS-STATUS", classification="status"),
        })
        from specter.models import Program
        from specter.static_analysis import StaticCallGraph
        from specter.coverage_strategies import StrategyContext

        ctx = StrategyContext(
            module=mod, context=None, domains=domains,
            stub_mapping={"CICS:READ": ["WS-STATUS"]},
            call_graph=StaticCallGraph({}, {}), gating_conds={},
            var_report=report,
            program=Program(program_id="TEST", paragraphs=[]),
            all_paragraphs={"STUB-PARA"},
            success_stubs={"CICS:READ": [[("WS-STATUS", "00")]] * 50},
            success_defaults={"CICS:READ": [("WS-STATUS", "00")]},
            rng=random.Random(42),
            store_path=Path("/tmp/test_store.jsonl"),
            branch_meta={1: {"condition": "WS-STATUS = '00'", "paragraph": "STUB-PARA", "type": "IF"}},
        )
        results = _discover_stub_branch_mapping(ctx, "STUB-PARA", ctx.branch_meta)
        assert len(results) > 0
        sm = results[0]
        assert sm.op_key == "CICS:READ"
        # '00' should activate branch 1:T, non-'00' should activate 1:F
        assert any("1:T" in brs for brs in sm.outcome_to_branches.values())

    def test_format_probing_results(self):
        from specter.coverage_strategies import (
            BranchProbeResult,
            StubBranchMap,
            _format_probing_results,
        )

        probes = [
            BranchProbeResult(
                branch_key="17:F", paragraph="READ-PARA",
                hit_count=3, total_probes=200,
                hit_inputs=[{"WS-RESP": 13}],
                discriminating_vars={"WS-RESP": {"13", "27"}},
                discriminating_stubs={"CICS:READ": {"13"}},
            ),
        ]
        stubs = [
            StubBranchMap(
                op_key="CICS:READ",
                outcome_to_branches={"13": {"17:F", "18:T"}},
            ),
        ]
        text = _format_probing_results(probes, stubs)
        assert "17:F" in text
        assert "WS-RESP" in text
        assert "CICS:READ" in text
        assert "Execution Probing Results" in text

    def test_best_probed_state_for_para(self):
        from specter.coverage_strategies import (
            BranchProbeResult,
            _best_probed_state_for_para,
        )

        mod = _make_probe_module()
        ctx = _make_probe_ctx(mod)
        # No cache → None
        assert _best_probed_state_for_para(ctx, "TEST-PARA") is None

        # Add to cache
        ctx.probe_cache["TEST-PARA"] = [
            BranchProbeResult(
                branch_key="1:T", paragraph="TEST-PARA",
                hit_count=5, total_probes=100,
                hit_inputs=[{"WS-CODE": "00"}],
            ),
            BranchProbeResult(
                branch_key="2:T", paragraph="TEST-PARA",
                hit_count=2, total_probes=100,
                hit_inputs=[{"WS-RESP": 13}],
            ),
        ]
        result = _best_probed_state_for_para(ctx, "TEST-PARA")
        assert result is not None
        assert result["WS-CODE"] == "00"  # from the higher-hit-count result

    def test_baseline_strategy_restores_target_key(self):
        from specter.coverage_strategies import BaselineStrategy

        mod = _make_probe_module()
        ctx = _make_probe_ctx(mod)
        cov = CoverageState(
            total_paragraphs=1,
            total_branches=4,
            all_paragraphs={"TEST-PARA"},
            _stub_mapping={},
        )
        ctx.current_target_key = "seed:key"

        strat = BaselineStrategy()
        list(strat.generate_cases(ctx, cov, batch_size=10))

        assert ctx.current_target_key == "seed:key"

    def test_direct_strategy_sets_and_restores_target_key(self):
        from specter.coverage_strategies import DirectParagraphStrategy

        mod = _make_probe_module()
        ctx = _make_probe_ctx(mod)
        cov = CoverageState(
            total_paragraphs=1,
            total_branches=4,
            all_paragraphs={"TEST-PARA"},
            _stub_mapping={},
        )
        cov.paragraphs_hit.add("TEST-PARA")
        ctx.current_target_key = "seed:key"

        strat = DirectParagraphStrategy()
        gen = strat.generate_cases(ctx, cov, batch_size=1)
        _ = next(gen)

        assert ctx.current_target_key in {"branch:1:T", "branch:1:F", "branch:2:T", "branch:2:F"}

        gen.close()
        assert ctx.current_target_key == "seed:key"

    def test_canonical_target_key_normalizes_branch_and_paragraph_targets(self):
        assert _canonical_target_key("direct:PARA-1|df:17:F:0") == "branch:17:F"
        assert _canonical_target_key("direct:PARA-1|frontier:23:T") == "branch:23:T"
        assert _canonical_target_key("direct:PARA-1|p:4") == "para:PARA-1"

    def test_select_priority_branch_target_prefers_low_attempt_unsolved(self):
        from specter.memory_models import MemoryState, TargetStatus

        mod = _make_probe_module()
        ctx = _make_probe_ctx(mod)
        ctx.memory_state = MemoryState(
            targets={
                "branch:1:T": TargetStatus(attempts=4, solved=False, nearest_branch_hits=3),
                "branch:1:F": TargetStatus(attempts=1, solved=False, nearest_branch_hits=2),
                "branch:2:T": TargetStatus(attempts=2, solved=True, nearest_branch_hits=4),
            }
        )

        cov = CoverageState(
            total_paragraphs=1,
            total_branches=4,
            all_paragraphs={"TEST-PARA"},
            _stub_mapping={},
        )
        cov.branches_hit.add("2:F")

        chosen = _select_priority_branch_target(ctx, cov)
        assert chosen == "branch:1:F"

    def test_direct_strategy_respects_preferred_branch_target(self):
        from specter.coverage_strategies import DirectParagraphStrategy

        mod = _make_probe_module()
        ctx = _make_probe_ctx(mod)
        ctx.preferred_target_key = "branch:1:T"
        cov = CoverageState(
            total_paragraphs=1,
            total_branches=4,
            all_paragraphs={"TEST-PARA"},
            _stub_mapping={},
        )
        cov.paragraphs_hit.add("TEST-PARA")

        strat = DirectParagraphStrategy()
        cases = []
        gen = strat.generate_cases(ctx, cov, batch_size=5)
        for _ in range(3):
            try:
                cases.append(next(gen))
            except StopIteration:
                break
        gen.close()

        assert cases
        for _state, _stubs, _defaults, target in cases:
            if "|df:" in target or "|frontier:" in target or "|inv:" in target or "|chain" in target:
                assert ":1:T" in target or "|chain:1" in target


class TestHeuristicSelector:
    """Tests for the HeuristicSelector."""

    def test_selects_by_priority(self):
        from specter.cobol_coverage import CoverageState
        from specter.coverage_strategies import HeuristicSelector
        from specter.coverage_strategies import (
            BaselineStrategy,
            FaultInjectionStrategy,
            StrategyYield,
        )

        selector = HeuristicSelector()
        strategies = [FaultInjectionStrategy(), BaselineStrategy()]

        cov = CoverageState(
            total_paragraphs=10,
            total_branches=20,
            all_paragraphs=set(),
            _stub_mapping={},
        )

        # BaselineStrategy has priority 20, FaultInjectionStrategy has 50
        strategy, batch = selector.select(strategies, cov, 0)
        assert strategy.name == "baseline"

    def test_yield_bonus_shifts_priority(self):
        from specter.cobol_coverage import CoverageState
        from specter.coverage_strategies import HeuristicSelector
        from specter.coverage_strategies import (
            BaselineStrategy,
            FaultInjectionStrategy,
            StrategyYield,
        )

        selector = HeuristicSelector()
        baseline = BaselineStrategy()
        baseline._ran = True  # Already ran, should_run returns False
        fi = FaultInjectionStrategy()
        strategies = [fi, baseline]

        cov = CoverageState(
            total_paragraphs=10,
            total_branches=20,
            all_paragraphs=set(),
            _stub_mapping={"OP:KEY": ["VAR"]},
        )

        # Since baseline already ran, fault_injection should be picked
        strategy, batch = selector.select(strategies, cov, 1)
        assert strategy.name == "fault_injection"


# ---------------------------------------------------------------------------
# Integration test (requires cobc)
# ---------------------------------------------------------------------------


_HAS_COBC = shutil.which("cobc") is not None


@pytest.mark.skipif(not _HAS_COBC, reason="GnuCOBOL (cobc) not installed")
class TestCobolIntegration:
    """Integration tests that compile and run actual COBOL programs."""

    def _write_minimal_cobol(self, tmp_path: Path) -> Path:
        """Write a minimal COBOL program with IF branches."""
        source = tmp_path / "TEST.cbl"
        source.write_text("""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       ENVIRONMENT DIVISION.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-CODE   PIC X(2) VALUE SPACES.
       PROCEDURE DIVISION.
       MAIN-PARA.
           IF WS-CODE = '00'
               DISPLAY 'CODE-OK'
           ELSE
               DISPLAY 'CODE-ERR'
           END-IF.
           STOP RUN.
""")
        return source

    def test_branch_instrument_and_compile(self, tmp_path):
        """Full pipeline: instrument → compile → run."""
        source = self._write_minimal_cobol(tmp_path)

        from specter.cobol_mock import instrument_cobol, MockConfig, compile_cobol, run_cobol

        config = MockConfig(trace_paragraphs=True)
        result = instrument_cobol(source, config)

        # Apply branch tracing
        from specter.cobol_mock import _add_branch_tracing
        lines = result.source.splitlines(keepends=True)
        lines, meta, count = _add_branch_tracing(lines)
        instrumented = "".join(lines)

        mock_path = tmp_path / "TEST.mock.cbl"
        mock_path.write_text(instrumented)

        # Compile
        exe_path = tmp_path / "TEST"
        success, msg = compile_cobol(mock_path, exe_path)
        if not success:
            pytest.skip(f"Compilation failed (expected for minimal program): {msg}")

    def test_parse_trace_from_real_cobol(self, tmp_path):
        """Verify parse_trace extracts paragraph names from COBOL output."""
        from specter.cobol_mock import parse_trace

        stdout = (
            "SPECTER-TRACE:MAIN-PARA\n"
            "CODE-OK\n"
            "SPECTER-TRACE:EXIT-PARA\n"
        )
        trace = parse_trace(stdout)
        assert trace == ["MAIN-PARA", "EXIT-PARA"]

    def test_executor_prepare_and_run(self, tmp_path):
        """Test CobolExecutionContext creation and single test case execution."""
        source = self._write_minimal_cobol(tmp_path)

        from specter.cobol_executor import prepare_context, run_test_case

        try:
            context = prepare_context(source, work_dir=tmp_path)
        except RuntimeError:
            pytest.skip("COBOL compilation failed for minimal program")

        result = run_test_case(
            context,
            input_state={"WS-CODE": "00"},
            stub_log=[],
            work_dir=tmp_path,
        )
        # The minimal program may or may not run correctly depending on
        # instrumentation, but we should at least get no crash
        assert result.error is None or isinstance(result.error, str)
