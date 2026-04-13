"""Tests for the multi-agent branch coverage swarm."""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from specter.branch_swarm import (
    BranchContext,
    JudgeFeedback,
    SolutionPattern,
    SpecialistProposal,
    SwarmJournal,
    SwarmRound,
    _build_condition_cracker_prompt,
    _build_history_miner_prompt,
    _build_path_finder_prompt,
    _build_stub_architect_prompt,
    _extract_condition_vars,
    _gather_branch_context,
    _parse_specialist_response,
    _synthesize_test_cases,
    swarm_enabled,
)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

class TestSwarmEnabled(unittest.TestCase):
    def test_default_enabled(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertTrue(swarm_enabled())

    def test_disabled_by_env(self):
        for val in ("0", "false", "no", "off"):
            with patch.dict("os.environ", {"SPECTER_BRANCH_SWARM": val}):
                self.assertFalse(swarm_enabled())


# ---------------------------------------------------------------------------
# Condition var extraction
# ---------------------------------------------------------------------------

class TestExtractConditionVars(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(
            _extract_condition_vars("IF WS-STATUS = '00'"),
            ["WS-STATUS"],
        )

    def test_quoted_stripped(self):
        result = _extract_condition_vars("WHEN 'ERRORES'")
        self.assertNotIn("ERRORES", result)

    def test_keywords_filtered(self):
        result = _extract_condition_vars("IF WS-X NOT EQUAL SPACES")
        self.assertIn("WS-X", result)
        self.assertNotIn("NOT", result)
        self.assertNotIn("SPACES", result)


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

class TestParseSpecialistResponse(unittest.TestCase):
    def test_valid_json(self):
        resp = json.dumps({
            "input_state": {"WS-X": "A"},
            "stub_outcomes": {},
            "reasoning": "test",
            "confidence": 0.8,
        })
        p = _parse_specialist_response(resp, "condition_cracker")
        self.assertEqual(p.specialist, "condition_cracker")
        self.assertEqual(p.input_state, {"WS-X": "A"})
        self.assertAlmostEqual(p.confidence, 0.8)

    def test_markdown_fenced(self):
        resp = "```json\n" + json.dumps({
            "input_state": {"A": 1},
            "reasoning": "fenced",
        }) + "\n```"
        p = _parse_specialist_response(resp, "stub_architect")
        self.assertEqual(p.input_state, {"A": 1})

    def test_empty_response(self):
        p = _parse_specialist_response(None, "path_finder")
        self.assertEqual(p.confidence, 0.0)
        self.assertIn("empty", p.reasoning)

    def test_garbage_response(self):
        p = _parse_specialist_response("no json here at all !!!", "history_miner")
        self.assertEqual(p.input_state, {})
        self.assertIn("could not parse", p.reasoning)

    def test_json_in_prose(self):
        resp = 'Here is my proposal:\n{"input_state": {"X": "1"}, "reasoning": "embedded"}'
        p = _parse_specialist_response(resp, "condition_cracker")
        self.assertEqual(p.input_state, {"X": "1"})


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

class TestPromptBuilders(unittest.TestCase):
    def _bctx(self, **overrides) -> BranchContext:
        defaults = dict(
            bid=42, direction="T", branch_key="42:T",
            paragraph="MAIN-PARA", condition_text="IF WS-STATUS = '00'",
            backward_slice_code="state['WS-STATUS'] = '00'\n",
            var_domain_info={"WS-STATUS": {
                "classification": "status", "data_type": "alpha",
                "max_length": 2, "condition_literals": ["00", "10"],
                "valid_88_values": {}, "stub_op": "READ:FILE",
            }},
            nearest_hit={"input_state": {"WS-X": "A"}, "branches_hit": ["41:T"]},
            call_graph_path=["ENTRY", "INIT-PARA", "MAIN-PARA"],
            gating_conditions=[{"variable": "WS-FLAG", "values": ["Y"], "negated": False}],
            stub_ops_in_slice=["READ:FILE"],
            stub_mapping={"READ:FILE": ["WS-STATUS"]},
            fault_tables={"status_file": ["00", "10", "23"]},
            test_case_count=15,
            solution_patterns=[],
        )
        defaults.update(overrides)
        return BranchContext(**defaults)

    def test_condition_cracker_prompt(self):
        prompt = _build_condition_cracker_prompt(self._bctx())
        self.assertIn("condition analyst", prompt)
        self.assertIn("WS-STATUS", prompt)
        self.assertIn("TRUE", prompt)  # direction=T
        self.assertIn("00", prompt)  # condition literal

    def test_path_finder_prompt(self):
        prompt = _build_path_finder_prompt(self._bctx())
        self.assertIn("reachability", prompt)
        self.assertIn("ENTRY", prompt)
        self.assertIn("WS-FLAG", prompt)

    def test_stub_architect_prompt(self):
        prompt = _build_stub_architect_prompt(self._bctx())
        self.assertIn("stub", prompt.lower())
        self.assertIn("READ:FILE", prompt)
        self.assertIn("status_file", prompt)

    def test_stub_architect_shows_operation_sequence(self):
        """When multiple stubs fire in order, the prompt should list
        the full sequence and instruct the LLM to provide stubs for all."""
        bctx = self._bctx(
            stub_ops_in_slice=["OPEN:ACCT-FILE", "READ:ACCT-REC", "REWRITE:ACCT-REC"],
            stub_op_sequence=["OPEN:ACCT-FILE", "READ:ACCT-REC", "REWRITE:ACCT-REC"],
        )
        prompt = _build_stub_architect_prompt(bctx)
        self.assertIn("fire in this order", prompt)
        self.assertIn("1. OPEN:ACCT-FILE", prompt)
        self.assertIn("2. READ:ACCT-REC", prompt)
        self.assertIn("3. REWRITE:ACCT-REC", prompt)
        self.assertIn("ALL operations", prompt)

    def test_history_miner_prompt(self):
        prompt = _build_history_miner_prompt(self._bctx())
        self.assertIn("mutation", prompt.lower())
        self.assertIn("WS-X", prompt)  # from nearest_hit

    def test_condition_cracker_with_feedback(self):
        fb = [JudgeFeedback(
            reached_paragraph=True, branch_hit=False,
            actual_var_values={"WS-STATUS": "00"},
        )]
        prompt = _build_condition_cracker_prompt(self._bctx(), prior_feedback=fb)
        self.assertIn("Previous round", prompt)
        self.assertIn("fundamentally different", prompt)

    def test_condition_cracker_shows_88_parent(self):
        """When a condition variable is an 88-level child, the prompt
        should tell the LLM to set the parent variable."""
        bctx = self._bctx(
            condition_text="IF APPL-AOK",
            var_domain_info={"APPL-AOK": {
                "classification": "flag", "data_type": "alpha",
            }},
            parent_88_lookup={"APPL-AOK": ("APPL-RESULT", 0)},
        )
        prompt = _build_condition_cracker_prompt(bctx)
        self.assertIn("APPL-RESULT", prompt)
        self.assertIn("88-level flag", prompt)

    def test_condition_cracker_88_not_in_domain_info(self):
        """88-level child may not have its own domain entry — the prompt
        should still surface the parent from parent_88_lookup."""
        bctx = self._bctx(
            condition_text="IF END-OF-FILE",
            var_domain_info={},  # no entry for END-OF-FILE
            parent_88_lookup={"END-OF-FILE": ("FILE-STATUS", "10")},
        )
        prompt = _build_condition_cracker_prompt(bctx)
        self.assertIn("FILE-STATUS", prompt)
        self.assertIn("88-level flag", prompt)

    def test_path_finder_no_path(self):
        prompt = _build_path_finder_prompt(self._bctx(call_graph_path=[]))
        self.assertIn("No call graph path", prompt)

    def test_history_miner_no_nearest_hit(self):
        prompt = _build_history_miner_prompt(self._bctx(nearest_hit=None))
        self.assertIn("No test case has reached", prompt)


# ---------------------------------------------------------------------------
# Test case synthesis
# ---------------------------------------------------------------------------

class TestSynthesizeTestCases(unittest.TestCase):
    def _bctx(self):
        return BranchContext(
            bid=1, direction="T", branch_key="1:T", paragraph="P",
            condition_text="", backward_slice_code="", var_domain_info={},
            nearest_hit=None, call_graph_path=[], gating_conditions=[],
            stub_ops_in_slice=[], stub_mapping={}, fault_tables={},
            test_case_count=0, solution_patterns=[],
        )

    def test_merges_all_proposals(self):
        proposals = [
            SpecialistProposal(specialist="path_finder", input_state={"GATE": "Y"}),
            SpecialistProposal(specialist="condition_cracker", input_state={"WS-X": "10"}),
            SpecialistProposal(specialist="stub_architect", stub_outcomes={"READ:F": [[["S", "00"]]]}),
            SpecialistProposal(specialist="history_miner", input_state={"WS-X": "99"}),
        ]
        cases = _synthesize_test_cases(proposals, self._bctx())
        self.assertGreaterEqual(len(cases), 1)
        merged = cases[0]
        # Path finder values should be in the merge.
        self.assertEqual(merged["input_state"]["GATE"], "Y")
        # Condition cracker overwrites path_finder for shared keys
        # but path_finder's unique keys remain.
        self.assertIn("WS-X", merged["input_state"])
        self.assertIn("READ:F", merged["stub_outcomes"])

    def test_empty_proposals_fallback(self):
        proposals = [
            SpecialistProposal(specialist="condition_cracker"),
            SpecialistProposal(specialist="path_finder"),
        ]
        cases = _synthesize_test_cases(proposals, self._bctx())
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0]["origin"], "empty_fallback")

    def test_distinct_history_mutation_added(self):
        proposals = [
            SpecialistProposal(specialist="condition_cracker", input_state={"A": "1"}),
            SpecialistProposal(specialist="stub_architect", stub_outcomes={"OP": [[["V", "0"]]]}),
            SpecialistProposal(specialist="history_miner", input_state={"B": "99"}),
            SpecialistProposal(specialist="path_finder"),
        ]
        cases = _synthesize_test_cases(proposals, self._bctx())
        origins = [c["origin"] for c in cases]
        self.assertIn("history_mutation", origins)

    def test_caps_at_3(self):
        proposals = [
            SpecialistProposal(specialist="condition_cracker", input_state={"A": "1"}),
            SpecialistProposal(specialist="stub_architect", stub_outcomes={"OP": [[["V", "0"]]]}),
            SpecialistProposal(specialist="history_miner", input_state={"B": "2"}),
            SpecialistProposal(specialist="path_finder", input_state={"C": "3"}),
        ]
        cases = _synthesize_test_cases(proposals, self._bctx())
        self.assertLessEqual(len(cases), 3)


# ---------------------------------------------------------------------------
# SwarmJournal backward compatibility
# ---------------------------------------------------------------------------

class TestSwarmJournalCompat(unittest.TestCase):
    def test_iterations_flattened(self):
        journal = SwarmJournal(
            branch_key="1:T",
            rounds=[
                SwarmRound(
                    round_num=0,
                    proposals=[
                        SpecialistProposal(specialist="cc", reasoning="try A"),
                    ],
                    synthesized_cases=[{"input_state": {"X": "1"}, "stub_outcomes": {}}],
                    feedback=[JudgeFeedback(branch_hit=False, reached_paragraph=True)],
                ),
            ],
        )
        iters = journal.iterations
        self.assertEqual(len(iters), 1)
        self.assertEqual(iters[0].proposed_input, {"X": "1"})
        self.assertFalse(iters[0].branch_hit)

    def test_max_iterations_alias(self):
        journal = SwarmJournal(branch_key="1:T", max_rounds=5)
        self.assertEqual(journal.max_iterations, 5)


# ---------------------------------------------------------------------------
# Context gathering (with mocked ctx/cov)
# ---------------------------------------------------------------------------

class TestGatherBranchContext(unittest.TestCase):
    def test_basic_context(self):
        ctx = SimpleNamespace(
            branch_meta={"1": {"paragraph": "MAIN", "condition": "IF X = 'Y'"}},
            module=None,
            domains={},
            stub_mapping={},
            call_graph=None,
            gating_conds={},
            memory_state=None,
        )
        cov = SimpleNamespace(
            test_cases=[],
            branches_hit=set(),
        )
        bctx = _gather_branch_context(1, "T", ctx, cov)
        self.assertEqual(bctx.paragraph, "MAIN")
        self.assertEqual(bctx.condition_text, "IF X = 'Y'")
        self.assertEqual(bctx.branch_key, "1:T")

    def test_missing_meta(self):
        ctx = SimpleNamespace(
            branch_meta={},
            module=None, domains={}, stub_mapping={},
            call_graph=None, gating_conds={}, memory_state=None,
        )
        cov = SimpleNamespace(test_cases=[], branches_hit=set())
        bctx = _gather_branch_context(99, "F", ctx, cov)
        self.assertEqual(bctx.paragraph, "")


if __name__ == "__main__":
    unittest.main()
