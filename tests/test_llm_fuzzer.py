"""Tests for LLM-guided fuzzer (adaptive strategy selection)."""

import json
import unittest
from unittest.mock import AsyncMock, MagicMock

from specter.llm_fuzzer import (
    STRATEGY_NAMES,
    SemanticProfile,
    SessionMemory,
    StrategyDecision,
    StrategyResult,
    _build_strategy_prompt,
    _build_variable_inference_prompt,
    _parse_semantic_profiles,
    _parse_strategy_decision,
    apply_strategy_to_state,
    generate_value_from_profile,
    record_coverage_checkpoint,
    record_error,
    record_strategy_result,
    should_consult_llm,
)
from specter.variable_domain import VariableDomain
from specter.variable_extractor import VariableInfo, VariableReport


def _make_var_report(variables: dict[str, VariableInfo]) -> VariableReport:
    return VariableReport(variables=variables)


class TestParseSemanticProfiles(unittest.TestCase):
    """Tests for _parse_semantic_profiles."""

    def test_parse_valid_response(self):
        response = json.dumps([
            {
                "variable": "WS-CUSTOMER-ID",
                "data_type": "identifier",
                "description": "Customer account identifier",
                "valid_values": ["10001", "20002", "30003"],
                "format_pattern": None,
                "related_variables": [],
            },
            {
                "variable": "ACCT-BALANCE",
                "data_type": "amount",
                "description": "Account balance in cents",
                "valid_values": [0, 1000, 50000],
                "format_pattern": None,
                "related_variables": ["WS-CUSTOMER-ID"],
            },
        ])
        profiles = _parse_semantic_profiles(response)
        self.assertEqual(len(profiles), 2)
        self.assertIn("WS-CUSTOMER-ID", profiles)
        self.assertEqual(profiles["WS-CUSTOMER-ID"].data_type, "identifier")
        self.assertEqual(profiles["ACCT-BALANCE"].related_variables, ["WS-CUSTOMER-ID"])

    def test_parse_code_fenced_response(self):
        response = '```json\n[{"variable": "X", "data_type": "text", "description": "test"}]\n```'
        profiles = _parse_semantic_profiles(response)
        self.assertEqual(len(profiles), 1)
        self.assertIn("X", profiles)

    def test_parse_invalid_json(self):
        profiles = _parse_semantic_profiles("not json at all")
        self.assertEqual(profiles, {})

    def test_parse_uppercases_names(self):
        response = json.dumps([
            {"variable": "ws-flag", "data_type": "flag", "description": "a flag"}
        ])
        profiles = _parse_semantic_profiles(response)
        self.assertIn("WS-FLAG", profiles)

    def test_parse_embedded_json(self):
        response = 'Here are profiles:\n[{"variable": "A", "data_type": "text", "description": ""}]\nDone.'
        profiles = _parse_semantic_profiles(response)
        self.assertEqual(len(profiles), 1)


class TestParseStrategyDecision(unittest.TestCase):
    """Tests for _parse_strategy_decision."""

    def test_parse_valid_decision(self):
        response = json.dumps({
            "strategy": "directed_walk",
            "target_paragraph": "ERROR-HANDLER",
            "focus_variables": ["WS-STATUS"],
            "focus_values": {"WS-STATUS": ["10", "21"]},
            "iterations": 75,
            "reasoning": "Status var mutation exhausted",
        })
        decision = _parse_strategy_decision(response)
        self.assertIsNotNone(decision)
        self.assertEqual(decision.strategy, "directed_walk")
        self.assertEqual(decision.target_paragraph, "ERROR-HANDLER")
        self.assertEqual(decision.iterations, 75)

    def test_parse_unknown_strategy_fallback(self):
        response = json.dumps({
            "strategy": "unknown_strategy",
            "iterations": 50,
        })
        decision = _parse_strategy_decision(response)
        self.assertIsNotNone(decision)
        self.assertEqual(decision.strategy, "random_exploration")

    def test_parse_invalid_json(self):
        decision = _parse_strategy_decision("not json")
        self.assertIsNone(decision)

    def test_clamps_iterations(self):
        response = json.dumps({
            "strategy": "random_exploration",
            "iterations": 1000,
        })
        decision = _parse_strategy_decision(response)
        self.assertEqual(decision.iterations, 200)

        response = json.dumps({
            "strategy": "random_exploration",
            "iterations": 1,
        })
        decision = _parse_strategy_decision(response)
        self.assertEqual(decision.iterations, 10)

    def test_parse_code_fenced_decision(self):
        response = '```json\n{"strategy": "crossover", "iterations": 50}\n```'
        decision = _parse_strategy_decision(response)
        self.assertIsNotNone(decision)
        self.assertEqual(decision.strategy, "crossover")


class TestBuildVariableInferencePrompt(unittest.TestCase):
    """Tests for _build_variable_inference_prompt."""

    def test_includes_variable_names(self):
        var_report = _make_var_report({
            "WS-DATE": VariableInfo(name="WS-DATE", classification="input"),
            "SQLCODE": VariableInfo(
                name="SQLCODE", classification="status",
                condition_literals=[0, 100],
            ),
        })
        prompt = _build_variable_inference_prompt(var_report)
        self.assertIn("WS-DATE", prompt)
        self.assertIn("SQLCODE", prompt)
        self.assertIn("condition_values=", prompt)

    def test_empty_var_report(self):
        var_report = _make_var_report({})
        prompt = _build_variable_inference_prompt(var_report)
        self.assertIn("(none)", prompt)


class TestBuildStrategyPrompt(unittest.TestCase):
    """Tests for _build_strategy_prompt."""

    def test_includes_coverage_stats(self):
        memory = SessionMemory()
        memory.strategy_history.append(StrategyResult(
            strategy="random_exploration", iterations=50,
            new_paragraphs=3, new_branches=5, new_edges=2, errors=0,
        ))
        var_report = _make_var_report({
            "WS-STATUS": VariableInfo(name="WS-STATUS", classification="status"),
        })
        prompt = _build_strategy_prompt(
            memory, {"MAIN", "INIT"}, {"MAIN", "INIT", "PROCESS"},
            {"INIT"}, 10, 5, var_report,
        )
        self.assertIn("2/3", prompt)  # covered/total
        self.assertIn("PROCESS", prompt)  # uncovered
        self.assertIn("random_exploration", prompt)  # strategy history


class TestGenerateValueFromProfile(unittest.TestCase):
    """Tests for generate_value_from_profile."""

    def test_uses_valid_values(self):
        import random
        profile = SemanticProfile(
            variable="WS-STATUS",
            data_type="status_code",
            description="File status",
            valid_values=["00", "10", "35"],
        )
        rng = random.Random(42)
        value = generate_value_from_profile(profile, rng)
        self.assertIn(value, ["00", "10", "35"])

    def test_fallback_by_data_type(self):
        import random
        profile = SemanticProfile(
            variable="WS-COUNT",
            data_type="counter",
            description="Record counter",
        )
        rng = random.Random(42)
        value = generate_value_from_profile(profile, rng)
        self.assertIsInstance(value, int)
        self.assertGreaterEqual(value, 0)
        self.assertLessEqual(value, 100)

    def test_date_type_fallback(self):
        import random
        profile = SemanticProfile(
            variable="WS-DATE",
            data_type="date",
            description="Process date",
        )
        rng = random.Random(42)
        value = generate_value_from_profile(profile, rng)
        self.assertEqual(len(value), 8)  # YYYYMMDD


class TestApplyStrategyToState(unittest.TestCase):
    """Tests for apply_strategy_to_state."""

    def test_random_exploration_uses_profiles(self):
        import random
        memory = SessionMemory()
        memory.semantic_profiles = {
            "WS-STATUS": SemanticProfile(
                variable="WS-STATUS", data_type="status_code",
                description="File status", valid_values=["00", "10"],
            ),
        }
        var_report = _make_var_report({
            "WS-STATUS": VariableInfo(name="WS-STATUS", classification="status"),
        })
        decision = StrategyDecision(strategy="random_exploration")
        rng = random.Random(42)
        state = apply_strategy_to_state(decision, {}, var_report, memory, rng)
        self.assertIn(state.get("WS-STATUS"), ["00", "10"])

    def test_single_var_mutation_with_focus(self):
        import random
        memory = SessionMemory()
        memory.semantic_profiles = {
            "WS-FLAG": SemanticProfile(
                variable="WS-FLAG", data_type="flag",
                description="End flag", valid_values=["Y", "N"],
            ),
        }
        var_report = _make_var_report({
            "WS-FLAG": VariableInfo(name="WS-FLAG", classification="flag"),
        })
        decision = StrategyDecision(
            strategy="single_var_mutation",
            focus_variables=["WS-FLAG"],
        )
        rng = random.Random(42)
        state = apply_strategy_to_state(
            decision, {"WS-FLAG": "N"}, var_report, memory, rng,
        )
        self.assertIn(state["WS-FLAG"], ["Y", "N"])

    def test_literal_guided_with_focus_values(self):
        import random
        memory = SessionMemory()
        var_report = _make_var_report({
            "WS-CODE": VariableInfo(
                name="WS-CODE", classification="input",
                condition_literals=["A", "B", "C"],
            ),
        })
        decision = StrategyDecision(
            strategy="literal_guided",
            focus_values={"WS-CODE": ["X", "Y"]},
        )
        rng = random.Random(42)
        state = apply_strategy_to_state(decision, {}, var_report, memory, rng)
        # Should use LLM-suggested values or condition literals
        self.assertIn(state.get("WS-CODE"), ["X", "Y"])

    def test_random_exploration_uses_jit_inference_when_available(self):
        import random

        class StubJITInference:
            def __init__(self):
                self.calls = 0

            def generate_value(self, var_name, domain, strategy, rng, **kwargs):
                self.calls += 1
                return "CA"

            def infer_profile(self, var_name, domain, **kwargs):
                return SemanticProfile(
                    variable=var_name,
                    data_type="text",
                    description="State code",
                    valid_values=["CA", "NY"],
                )

        memory = SessionMemory()
        var_report = _make_var_report({
            "WS-STATE": VariableInfo(name="WS-STATE", classification="input"),
        })
        decision = StrategyDecision(strategy="random_exploration")
        rng = random.Random(42)
        jit = StubJITInference()
        domains = {
            "WS-STATE": VariableDomain(
                name="WS-STATE",
                classification="input",
                data_type="alpha",
                max_length=2,
            ),
        }

        state = apply_strategy_to_state(
            decision,
            {},
            var_report,
            memory,
            rng,
            jit_inference=jit,
            domains=domains,
        )

        self.assertEqual(state["WS-STATE"], "CA")
        self.assertIn("WS-STATE", memory.semantic_profiles)
        self.assertGreaterEqual(jit.calls, 1)


class TestSessionMemory(unittest.TestCase):
    """Tests for session memory recording."""

    def test_record_strategy_result(self):
        memory = SessionMemory()
        record_strategy_result(memory, "random_exploration", 50, 3, 5, 2, 0)
        self.assertEqual(len(memory.strategy_history), 1)
        self.assertEqual(memory.strategy_history[0].strategy, "random_exploration")
        self.assertEqual(memory.strategy_history[0].new_paragraphs, 3)

    def test_record_error(self):
        memory = SessionMemory()
        record_error(memory, "RecursionError", {"WS-X": "1"}, ["WS-X"])
        self.assertEqual(len(memory.error_patterns), 1)
        self.assertEqual(memory.error_patterns[0]["error"], "RecursionError")

    def test_error_pattern_limit(self):
        memory = SessionMemory()
        for i in range(60):
            record_error(memory, f"Error {i}", {})
        self.assertEqual(len(memory.error_patterns), 50)

    def test_record_coverage_checkpoint(self):
        memory = SessionMemory()
        record_coverage_checkpoint(memory, 100, 15, 8)
        self.assertEqual(len(memory.coverage_timeline), 1)
        self.assertEqual(memory.coverage_timeline[0], (100, 15, 8))


class TestShouldConsultLLM(unittest.TestCase):
    """Tests for should_consult_llm decision cadence."""

    def test_regular_interval(self):
        memory = SessionMemory()
        reason = should_consult_llm(500, memory, 0, 1000, 500, 10, 12)
        self.assertEqual(reason, "regular_interval")

    def test_plateau(self):
        memory = SessionMemory()
        reason = should_consult_llm(501, memory, 1000, 1000, 500, 10, 10)
        self.assertEqual(reason, "plateau")

    def test_coverage_milestone(self):
        memory = SessionMemory()
        # 10+ jump: 10 -> 12 is 20%
        reason = should_consult_llm(123, memory, 0, 1000, 500, 10, 12)
        self.assertEqual(reason, "coverage_milestone")

    def test_no_consultation_needed(self):
        memory = SessionMemory()
        reason = should_consult_llm(50, memory, 10, 1000, 500, 10, 10)
        self.assertIsNone(reason)

    def test_iteration_zero_no_consult(self):
        memory = SessionMemory()
        reason = should_consult_llm(0, memory, 0, 1000, 500, 0, 0)
        self.assertIsNone(reason)


class TestInferVariableSemantics(unittest.TestCase):
    """Tests for infer_variable_semantics with mocked LLM."""

    def test_successful_inference(self):
        from specter.llm_fuzzer import infer_variable_semantics

        mock_provider = MagicMock()
        mock_response = MagicMock()
        mock_response.content = json.dumps([
            {
                "variable": "WS-DATE",
                "data_type": "date",
                "description": "Processing date",
                "valid_values": ["20250101", "20251231"],
                "format_pattern": "YYYYMMDD",
                "related_variables": [],
            },
        ])
        mock_response.tokens_used = 200
        mock_provider.complete = AsyncMock(return_value=mock_response)

        var_report = _make_var_report({
            "WS-DATE": VariableInfo(name="WS-DATE", classification="input"),
        })

        profiles = infer_variable_semantics(mock_provider, var_report)
        self.assertEqual(len(profiles), 1)
        self.assertEqual(profiles["WS-DATE"].data_type, "date")
        self.assertEqual(profiles["WS-DATE"].format_pattern, "YYYYMMDD")

    def test_handles_llm_failure(self):
        from specter.llm_fuzzer import infer_variable_semantics

        mock_provider = MagicMock()
        mock_provider.complete = AsyncMock(side_effect=Exception("API error"))

        var_report = _make_var_report({
            "WS-X": VariableInfo(name="WS-X", classification="input"),
        })

        profiles = infer_variable_semantics(mock_provider, var_report)
        self.assertEqual(profiles, {})


class TestGetStrategyDecision(unittest.TestCase):
    """Tests for get_strategy_decision with mocked LLM."""

    def test_successful_decision(self):
        from specter.llm_fuzzer import get_strategy_decision

        mock_provider = MagicMock()
        mock_response = MagicMock()
        mock_response.content = json.dumps({
            "strategy": "stub_outcome_variation",
            "focus_variables": ["SQLCODE"],
            "iterations": 75,
            "reasoning": "SQL paths unexplored",
        })
        mock_response.tokens_used = 150
        mock_provider.complete = AsyncMock(return_value=mock_response)

        memory = SessionMemory()
        var_report = _make_var_report({
            "SQLCODE": VariableInfo(name="SQLCODE", classification="status"),
        })

        decision = get_strategy_decision(
            mock_provider, memory, {"MAIN"}, {"MAIN", "SQL-ERR"},
            set(), 10, 5, var_report,
        )
        self.assertIsNotNone(decision)
        self.assertEqual(decision.strategy, "stub_outcome_variation")
        self.assertEqual(memory.llm_calls, 1)

    def test_handles_llm_failure(self):
        from specter.llm_fuzzer import get_strategy_decision

        mock_provider = MagicMock()
        mock_provider.complete = AsyncMock(side_effect=Exception("timeout"))

        memory = SessionMemory()
        var_report = _make_var_report({})

        decision = get_strategy_decision(
            mock_provider, memory, set(), set(), set(), 0, 0, var_report,
        )
        self.assertIsNone(decision)


if __name__ == "__main__":
    unittest.main()
