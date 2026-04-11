"""Tests for the inner branch agent loop."""

import json
import os
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

from specter.branch_agent import (
    AgentIteration,
    BranchAgentJournal,
    _build_agent_prompt,
    _extract_condition_vars,
    _find_nearest_hit,
    _select_priority_branch_targets,
    agent_enabled,
    investigate_branch,
    parse_agent_response,
    run_branch_agent,
)


class TestAgentEnabled(unittest.TestCase):
    def test_default_enabled(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SPECTER_BRANCH_AGENT", None)
            self.assertTrue(agent_enabled())

    def test_disabled(self):
        with patch.dict(os.environ, {"SPECTER_BRANCH_AGENT": "0"}):
            self.assertFalse(agent_enabled())

    def test_disabled_by_false(self):
        with patch.dict(os.environ, {"SPECTER_BRANCH_AGENT": "false"}):
            self.assertFalse(agent_enabled())


class TestParseAgentResponse(unittest.TestCase):
    def test_clean_json(self):
        resp = json.dumps({
            "input_state": {"WS-FOO": "A"},
            "stub_outcomes": {"READ:F": [[["STATUS", "10"]]]},
            "reasoning": "set EOF on read",
        })
        inp, stubs, reason = parse_agent_response(resp)
        self.assertEqual(inp["WS-FOO"], "A")
        self.assertIn("READ:F", stubs)
        self.assertIn("EOF", reason)

    def test_markdown_fenced(self):
        resp = "```json\n" + json.dumps({
            "input_state": {"X": 1},
            "stub_outcomes": {},
            "reasoning": "ok",
        }) + "\n```"
        inp, stubs, reason = parse_agent_response(resp)
        self.assertEqual(inp["X"], 1)

    def test_prose_then_json(self):
        resp = "Sure! Here's my proposal:\n" + json.dumps({
            "input_state": {"A": "B"},
            "stub_outcomes": {},
            "reasoning": "test",
        })
        inp, _, _ = parse_agent_response(resp)
        self.assertEqual(inp["A"], "B")

    def test_empty_response(self):
        inp, stubs, reason = parse_agent_response("")
        self.assertEqual(inp, {})
        self.assertEqual(stubs, {})
        self.assertIn("empty", reason)

    def test_garbage(self):
        inp, stubs, reason = parse_agent_response("not json at all")
        self.assertEqual(inp, {})
        self.assertIn("could not parse", reason)

    def test_missing_fields(self):
        inp, stubs, reason = parse_agent_response('{"other": true}')
        self.assertEqual(inp, {})
        self.assertEqual(stubs, {})


class TestExtractConditionVars(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(
            _extract_condition_vars("IF WS-STATUS = '00'"),
            ["WS-STATUS"],
        )

    def test_filters_keywords(self):
        result = _extract_condition_vars("IF A-VAR NOT EQUAL SPACES")
        self.assertIn("A-VAR", result)
        self.assertNotIn("NOT", result)
        self.assertNotIn("EQUAL", result)
        self.assertNotIn("SPACES", result)

    def test_dedupes(self):
        self.assertEqual(
            _extract_condition_vars("IF X-VAR = X-VAR"),
            ["X-VAR"],
        )


class TestBuildAgentPrompt(unittest.TestCase):
    def test_contains_branch_id(self):
        prompt = _build_agent_prompt(
            bid=42, direction="T", paragraph="MAIN",
            condition_text="IF X = 1",
            backward_slice_code="",
            var_domains={}, nearest_hit=None,
            prior_iterations=[], total_attempts=10,
        )
        self.assertIn("42:T", prompt)
        self.assertIn("MAIN", prompt)

    def test_contains_backward_slice(self):
        prompt = _build_agent_prompt(
            bid=1, direction="F", paragraph="P",
            condition_text="",
            backward_slice_code="if state['X'] == '00':\n    ...",
            var_domains={}, nearest_hit=None,
            prior_iterations=[], total_attempts=0,
        )
        self.assertIn("state['X']", prompt)

    def test_contains_prior_attempts(self):
        prior = [AgentIteration(
            iteration=0,
            proposed_input={"X": "1"},
            proposed_stubs={},
            reasoning="tried X=1",
            execution_result={"rc": 11},
        )]
        prompt = _build_agent_prompt(
            bid=5, direction="T", paragraph="P",
            condition_text="IF X > 0",
            backward_slice_code="",
            var_domains={}, nearest_hit=None,
            prior_iterations=prior, total_attempts=5,
        )
        self.assertIn("tried X=1", prompt)
        self.assertIn("fundamentally different", prompt)

    def test_contains_var_domains(self):
        domains = {
            "WS-CODE": {
                "classification": "status",
                "data_type": "alpha",
                "max_length": 2,
                "condition_literals": ["00", "10"],
                "valid_88_values": {},
                "stub_op": "READ:F",
            }
        }
        prompt = _build_agent_prompt(
            bid=1, direction="T", paragraph="P",
            condition_text="IF WS-CODE = '10'",
            backward_slice_code="",
            var_domains=domains, nearest_hit=None,
            prior_iterations=[], total_attempts=0,
        )
        self.assertIn("WS-CODE", prompt)
        self.assertIn("READ:F", prompt)


class TestFindNearestHit(unittest.TestCase):
    def test_no_test_cases(self):
        self.assertIsNone(_find_nearest_hit([], 42, "P"))

    def test_picks_paragraph_match(self):
        tcs = [
            {"paragraphs_hit": ["P"], "branches_hit": ["42:T"], "input_state": {"X": 1}},
            {"paragraphs_hit": ["OTHER"], "branches_hit": ["42:F"], "input_state": {"X": 2}},
        ]
        result = _find_nearest_hit(tcs, 42, "P")
        self.assertIsNotNone(result)
        self.assertEqual(result["input_state"]["X"], 1)


class TestSelectPriorityBranchTargets(unittest.TestCase):
    def test_returns_uncovered(self):
        ctx = SimpleNamespace(
            branch_meta={"1": {}, "2": {}},
            memory_state=None,
        )
        cov = SimpleNamespace(branches_hit={"1:T", "1:F"})
        targets = _select_priority_branch_targets(ctx, cov, max_targets=5)
        # Branch 1 is fully covered; branch 2 has T and F uncovered.
        self.assertTrue(any("2:T" in t for t in targets))

    def test_respects_max(self):
        ctx = SimpleNamespace(
            branch_meta={str(i): {} for i in range(20)},
            memory_state=None,
        )
        cov = SimpleNamespace(branches_hit=set())
        targets = _select_priority_branch_targets(ctx, cov, max_targets=3)
        self.assertEqual(len(targets), 3)


class TestInvestigateBranch(unittest.TestCase):
    def test_no_provider_returns_empty_journal(self):
        ctx = SimpleNamespace(
            branch_meta={"42": {"paragraph": "P", "condition": "IF X = 1"}},
            domains={}, stub_mapping={}, module=None,
            memory_store=None, memory_state=None,
        )
        cov = SimpleNamespace(branches_hit=set(), test_cases=[])
        report = SimpleNamespace()

        journal, tc = investigate_branch(
            bid=42, direction="T", ctx=ctx, cov=cov,
            report=report, tc_count=0,
            max_iterations=3, llm_provider=None,
        )
        self.assertFalse(journal.success)
        self.assertIn("no LLM provider", journal.final_reasoning)

    def test_successful_investigation(self):
        """Mock the LLM to return a proposal that 'solves' the branch."""
        ctx = SimpleNamespace(
            branch_meta={"42": {"paragraph": "P", "condition": "IF X = 1"}},
            domains={}, stub_mapping={}, module=None,
            memory_store=None, memory_state=None,
        )
        cov = SimpleNamespace(branches_hit=set(), test_cases=[])
        report = SimpleNamespace()

        llm_response = json.dumps({
            "input_state": {"X": 1},
            "stub_outcomes": {},
            "reasoning": "set X to 1 to make IF X = 1 true",
        })

        def fake_execute(ctx, cov, input_state, stubs, defaults,
                         strategy, target, report, tc_count):
            # Simulate the branch being hit.
            cov.branches_hit.add("42:T")
            cov.test_cases.append({
                "input_state": input_state,
                "paragraphs_hit": ["P"],
                "branches_hit": ["42:T"],
            })
            return True, tc_count + 1

        with patch("specter.llm_coverage._query_llm_sync", return_value=(llm_response, {})), \
             patch("specter.cobol_coverage._execute_and_save", side_effect=fake_execute):
            journal, tc = investigate_branch(
                bid=42, direction="T", ctx=ctx, cov=cov,
                report=report, tc_count=0,
                max_iterations=3, llm_provider=MagicMock(),
            )

        self.assertTrue(journal.success)
        self.assertEqual(len(journal.iterations), 1)
        self.assertTrue(journal.iterations[0].branch_hit)
        self.assertIn("Solved", journal.final_reasoning)

    def test_exhausts_iterations(self):
        """After max_iterations failures, journal records exhaustion."""
        ctx = SimpleNamespace(
            branch_meta={"5": {"paragraph": "P", "condition": "IF Y > 0"}},
            domains={}, stub_mapping={}, module=None,
            memory_store=None, memory_state=None,
        )
        cov = SimpleNamespace(branches_hit=set(), test_cases=[])
        report = SimpleNamespace()

        llm_response = json.dumps({
            "input_state": {"Y": 99},
            "stub_outcomes": {},
            "reasoning": "try large Y",
        })

        def fake_execute(ctx, cov, input_state, stubs, defaults,
                         strategy, target, report, tc_count):
            cov.test_cases.append({
                "input_state": input_state,
                "paragraphs_hit": ["P"],
                "branches_hit": ["5:F"],
            })
            return True, tc_count + 1

        with patch("specter.llm_coverage._query_llm_sync", return_value=(llm_response, {})), \
             patch("specter.cobol_coverage._execute_and_save", side_effect=fake_execute):
            journal, tc = investigate_branch(
                bid=5, direction="T", ctx=ctx, cov=cov,
                report=report, tc_count=0,
                max_iterations=2, llm_provider=MagicMock(),
            )

        self.assertFalse(journal.success)
        self.assertEqual(len(journal.iterations), 2)
        self.assertIn("Exhausted", journal.final_reasoning)


class TestRunBranchAgent(unittest.TestCase):
    def test_disabled_returns_empty(self):
        with patch.dict(os.environ, {"SPECTER_BRANCH_AGENT": "0"}):
            journals, n, tc = run_branch_agent(
                ctx=None, cov=None, report=None, tc_count=0,
            )
            self.assertEqual(journals, [])

    def test_no_provider_returns_empty(self):
        journals, n, tc = run_branch_agent(
            ctx=SimpleNamespace(branch_meta={"1": {}}),
            cov=SimpleNamespace(branches_hit=set()),
            report=SimpleNamespace(), tc_count=0,
            llm_provider=None,
        )
        self.assertEqual(journals, [])


class TestJournalSerialization(unittest.TestCase):
    def test_round_trip(self):
        journal = BranchAgentJournal(
            branch_key="42:T",
            paragraph="MAIN",
            condition_text="IF X = 1",
            iterations=[
                AgentIteration(
                    iteration=0,
                    proposed_input={"X": 1},
                    reasoning="try X=1",
                    branch_hit=True,
                ),
            ],
            success=True,
            final_reasoning="Solved",
        )
        d = asdict(journal)
        serialized = json.dumps(d, default=str)
        loaded = json.loads(serialized)
        self.assertEqual(loaded["branch_key"], "42:T")
        self.assertTrue(loaded["success"])
        self.assertEqual(len(loaded["iterations"]), 1)
        self.assertTrue(loaded["iterations"][0]["branch_hit"])


if __name__ == "__main__":
    unittest.main()
