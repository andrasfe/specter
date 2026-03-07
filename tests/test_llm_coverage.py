"""Tests for LLM-guided coverage maximization."""

import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from specter.llm_coverage import (
    CoverageGap,
    LLMCoverageState,
    LLMSuggestion,
    _build_coverage_prompt,
    _parse_llm_response,
    apply_suggestion,
    build_coverage_gaps,
    generate_llm_suggestions,
)
from specter.static_analysis import GatingCondition, PathConstraints
from specter.variable_extractor import VariableInfo, VariableReport


def _make_var_report(variables: dict[str, VariableInfo]) -> VariableReport:
    return VariableReport(variables=variables)


class TestParseResponse(unittest.TestCase):
    """Tests for _parse_llm_response."""

    def test_parse_valid_json_array(self):
        response = json.dumps([
            {
                "target": "PROCESS-RECORD",
                "variables": {"WS-STATUS": "00", "WS-FLAG": True},
                "reasoning": "Set status to success",
            }
        ])
        suggestions = _parse_llm_response(response)
        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0].target, "PROCESS-RECORD")
        self.assertEqual(suggestions[0].variable_assignments["WS-STATUS"], "00")
        self.assertTrue(suggestions[0].variable_assignments["WS-FLAG"])

    def test_parse_code_fenced_json(self):
        response = '```json\n[{"target": "INIT", "variables": {"X": 1}, "reasoning": ""}]\n```'
        suggestions = _parse_llm_response(response)
        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0].target, "INIT")

    def test_parse_embedded_json(self):
        response = 'Here is my suggestion:\n[{"target": "A", "variables": {}, "reasoning": ""}]\nDone.'
        suggestions = _parse_llm_response(response)
        self.assertEqual(len(suggestions), 1)

    def test_parse_single_object(self):
        response = json.dumps({
            "target": "SINGLE",
            "variables": {"V": 42},
            "reasoning": "",
        })
        suggestions = _parse_llm_response(response)
        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0].target, "SINGLE")

    def test_parse_invalid_json(self):
        suggestions = _parse_llm_response("This is not JSON at all")
        self.assertEqual(suggestions, [])

    def test_parse_empty_array(self):
        suggestions = _parse_llm_response("[]")
        self.assertEqual(suggestions, [])

    def test_parse_multiple_targets(self):
        response = json.dumps([
            {"target": "A", "variables": {"X": 1}, "reasoning": ""},
            {"target": "B", "variables": {"Y": "test"}, "reasoning": ""},
        ])
        suggestions = _parse_llm_response(response)
        self.assertEqual(len(suggestions), 2)

    def test_parse_skips_invalid_items(self):
        response = json.dumps([
            {"target": "A", "variables": {"X": 1}, "reasoning": ""},
            "not a dict",
            {"no_target": True},
        ])
        suggestions = _parse_llm_response(response)
        self.assertEqual(len(suggestions), 1)


class TestBuildPrompt(unittest.TestCase):
    """Tests for _build_coverage_prompt."""

    def test_prompt_contains_target(self):
        gaps = [CoverageGap(
            target="ERROR-HANDLER",
            path=["MAIN", "PROCESS", "ERROR-HANDLER"],
            gating_conditions=[
                {"variable": "WS-STATUS", "values": ["10"], "negated": False}
            ],
        )]
        var_report = _make_var_report({
            "WS-STATUS": VariableInfo(
                name="WS-STATUS",
                classification="status",
                condition_literals=["00", "10", "21"],
            ),
        })
        prompt = _build_coverage_prompt(gaps, {"MAIN", "PROCESS"}, var_report)
        self.assertIn("ERROR-HANDLER", prompt)
        self.assertIn("WS-STATUS", prompt)
        self.assertIn("10", prompt)

    def test_prompt_empty_when_no_gaps(self):
        prompt = _build_coverage_prompt([], {"MAIN"}, _make_var_report({}))
        self.assertEqual(prompt, "")

    def test_prompt_limits_targets(self):
        gaps = [
            CoverageGap(target=f"PARA-{i}", path=[f"PARA-{i}"],
                        gating_conditions=[])
            for i in range(20)
        ]
        var_report = _make_var_report({})
        prompt = _build_coverage_prompt(gaps, set(), var_report, max_targets=3)
        # Should only include 3 targets
        target_count = prompt.count("Target: PARA-")
        self.assertEqual(target_count, 3)

    def test_prompt_ranks_by_attempts_then_path_length(self):
        gaps = [
            CoverageGap(target="FAR", path=["A", "B", "C", "FAR"],
                        gating_conditions=[], attempt_count=0),
            CoverageGap(target="NEAR", path=["A", "NEAR"],
                        gating_conditions=[], attempt_count=0),
            CoverageGap(target="TRIED", path=["A", "TRIED"],
                        gating_conditions=[], attempt_count=5),
        ]
        var_report = _make_var_report({})
        prompt = _build_coverage_prompt(gaps, set(), var_report, max_targets=2)
        # NEAR should come first (shortest path, 0 attempts)
        self.assertIn("NEAR", prompt)
        # TRIED should be excluded (highest attempts)
        self.assertNotIn("TRIED", prompt)


class TestBuildCoverageGaps(unittest.TestCase):
    """Tests for build_coverage_gaps."""

    def test_builds_gaps_from_uncovered(self):
        pc = PathConstraints(
            target="ERROR",
            path=["MAIN", "PROCESS", "ERROR"],
            constraints=[
                GatingCondition(variable="STATUS", values=["10"], negated=False),
            ],
        )
        gaps = build_coverage_gaps(
            uncovered={"ERROR"},
            path_constraints_map={"ERROR": pc},
            gating_conditions=None,
        )
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].target, "ERROR")
        self.assertEqual(gaps[0].path, ["MAIN", "PROCESS", "ERROR"])
        self.assertEqual(len(gaps[0].gating_conditions), 1)

    def test_handles_missing_path_constraints(self):
        gaps = build_coverage_gaps(
            uncovered={"ORPHAN"},
            path_constraints_map={},
            gating_conditions=None,
        )
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].path, ["ORPHAN"])


class TestApplySuggestion(unittest.TestCase):
    """Tests for apply_suggestion."""

    def test_applies_known_variables(self):
        var_report = _make_var_report({
            "WS-STATUS": VariableInfo(name="WS-STATUS", classification="status"),
            "WS-FLAG": VariableInfo(name="WS-FLAG", classification="flag"),
        })
        suggestion = LLMSuggestion(
            target="TEST",
            variable_assignments={"WS-STATUS": "10", "WS-FLAG": True},
        )
        state = apply_suggestion(suggestion, {}, var_report)
        self.assertEqual(state["WS-STATUS"], "10")
        self.assertTrue(state["WS-FLAG"])

    def test_preserves_base_state(self):
        var_report = _make_var_report({
            "WS-A": VariableInfo(name="WS-A", classification="input"),
        })
        suggestion = LLMSuggestion(
            target="TEST",
            variable_assignments={"WS-A": "new"},
        )
        base = {"WS-A": "old", "WS-B": "keep"}
        state = apply_suggestion(suggestion, base, var_report)
        self.assertEqual(state["WS-A"], "new")
        self.assertEqual(state["WS-B"], "keep")
        # Original base should be unmodified
        self.assertEqual(base["WS-A"], "old")

    def test_uppercases_variable_names(self):
        var_report = _make_var_report({
            "WS-LOWER": VariableInfo(name="WS-LOWER", classification="input"),
        })
        suggestion = LLMSuggestion(
            target="TEST",
            variable_assignments={"ws-lower": "value"},
        )
        state = apply_suggestion(suggestion, {}, var_report)
        self.assertEqual(state["WS-LOWER"], "value")

    def test_accepts_cobol_style_unknown_vars(self):
        var_report = _make_var_report({})
        suggestion = LLMSuggestion(
            target="TEST",
            variable_assignments={"WS-UNKNOWN-VAR": "val"},
        )
        state = apply_suggestion(suggestion, {}, var_report)
        self.assertEqual(state["WS-UNKNOWN-VAR"], "val")


class TestLLMCoverageState(unittest.TestCase):
    """Tests for LLMCoverageState tracking."""

    def test_initial_state(self):
        state = LLMCoverageState()
        self.assertEqual(state.suggestions_tried, 0)
        self.assertEqual(state.suggestions_hit, 0)
        self.assertEqual(state.llm_calls, 0)
        self.assertEqual(state.tokens_used, 0)
        self.assertEqual(state.gaps, [])


class TestGenerateSuggestions(unittest.TestCase):
    """Tests for generate_llm_suggestions with mocked LLM."""

    def test_queries_llm_and_returns_suggestions(self):
        mock_provider = MagicMock()
        mock_response = MagicMock()
        mock_response.content = json.dumps([
            {"target": "ERROR-PARA", "variables": {"STATUS": "10"}, "reasoning": "err"},
        ])
        mock_response.tokens_used = 100

        # Make complete an async method that returns mock_response
        mock_provider.complete = AsyncMock(return_value=mock_response)

        var_report = _make_var_report({
            "STATUS": VariableInfo(
                name="STATUS", classification="status",
                condition_literals=["00", "10"],
            ),
        })

        pc = PathConstraints(
            target="ERROR-PARA",
            path=["MAIN", "ERROR-PARA"],
            constraints=[GatingCondition(variable="STATUS", values=["10"], negated=False)],
        )

        llm_state = LLMCoverageState()
        suggestions = generate_llm_suggestions(
            provider=mock_provider,
            covered_paragraphs={"MAIN"},
            uncovered_paragraphs={"ERROR-PARA"},
            path_constraints_map={"ERROR-PARA": pc},
            gating_conditions=None,
            var_report=var_report,
            llm_state=llm_state,
        )

        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0].target, "ERROR-PARA")
        self.assertEqual(llm_state.llm_calls, 1)
        self.assertEqual(llm_state.tokens_used, 100)

    def test_handles_llm_error_gracefully(self):
        mock_provider = MagicMock()
        mock_provider.complete = AsyncMock(side_effect=Exception("API error"))

        var_report = _make_var_report({})
        pc = PathConstraints(target="T", path=["T"], constraints=[])
        llm_state = LLMCoverageState()

        suggestions = generate_llm_suggestions(
            provider=mock_provider,
            covered_paragraphs=set(),
            uncovered_paragraphs={"T"},
            path_constraints_map={"T": pc},
            gating_conditions=None,
            var_report=var_report,
            llm_state=llm_state,
        )

        self.assertEqual(suggestions, [])

    def test_skips_resolved_gaps(self):
        mock_provider = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "[]"
        mock_response.tokens_used = 10
        mock_provider.complete = AsyncMock(return_value=mock_response)

        var_report = _make_var_report({})
        llm_state = LLMCoverageState()
        llm_state.gaps = [
            CoverageGap(target="DONE", path=["DONE"],
                        gating_conditions=[], resolved=True),
        ]

        suggestions = generate_llm_suggestions(
            provider=mock_provider,
            covered_paragraphs={"DONE"},
            uncovered_paragraphs=set(),
            path_constraints_map={},
            gating_conditions=None,
            var_report=var_report,
            llm_state=llm_state,
        )

        self.assertEqual(suggestions, [])


if __name__ == "__main__":
    unittest.main()
