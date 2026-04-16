"""Tests for the hierarchical 3-level branch planner."""

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
    _build_gate_solver_prompt,
    _build_history_miner_prompt,
    _build_path_finder_prompt,
    _build_stub_architect_prompt,
    _build_tape,
    _extract_condition_vars,
    _gather_branch_context,
    _merge_proposals,
    _parse_gate_solver_response,
    _format_prior_feedback,
    _parse_specialist_response,
    _plan_route,
    _validate_python,
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
# Level 1: Route Planner
# ---------------------------------------------------------------------------

class TestPlanRoute(unittest.TestCase):
    def test_returns_route_with_gates(self):
        call_graph = SimpleNamespace(
            path_to=lambda t: ["ENTRY", "INIT", "MAIN"] if t == "MAIN" else None,
        )
        gc_init = SimpleNamespace(variable="WS-MODE", values=["A"], negated=False)
        gating_conds = {"INIT": [gc_init], "MAIN": []}
        ctx = SimpleNamespace(call_graph=call_graph, gating_conds=gating_conds)
        bctx = BranchContext(
            bid=1, direction="T", branch_key="1:T", paragraph="MAIN",
            condition_text="", backward_slice_code="", var_domain_info={},
            nearest_hit=None, call_graph_path=[], gating_conditions=[],
            stub_ops_in_slice=[], stub_mapping={}, fault_tables={},
            test_case_count=0, solution_patterns=[],
        )

        route = _plan_route(bctx, ctx)
        self.assertEqual(len(route), 3)
        self.assertEqual(route[0][0], "ENTRY")
        self.assertEqual(route[1][0], "INIT")
        self.assertEqual(route[1][1][0]["variable"], "WS-MODE")
        self.assertEqual(route[2][0], "MAIN")

    def test_returns_empty_when_unreachable(self):
        call_graph = SimpleNamespace(path_to=lambda t: None)
        ctx = SimpleNamespace(call_graph=call_graph, gating_conds={})
        bctx = BranchContext(
            bid=1, direction="T", branch_key="1:T", paragraph="UNREACHABLE",
            condition_text="", backward_slice_code="", var_domain_info={},
            nearest_hit=None, call_graph_path=[], gating_conditions=[],
            stub_ops_in_slice=[], stub_mapping={}, fault_tables={},
            test_case_count=0, solution_patterns=[],
        )
        self.assertEqual(_plan_route(bctx, ctx), [])

    def test_returns_empty_when_no_call_graph(self):
        ctx = SimpleNamespace(call_graph=None, gating_conds={})
        bctx = BranchContext(
            bid=1, direction="T", branch_key="1:T", paragraph="P",
            condition_text="", backward_slice_code="", var_domain_info={},
            nearest_hit=None, call_graph_path=[], gating_conditions=[],
            stub_ops_in_slice=[], stub_mapping={}, fault_tables={},
            test_case_count=0, solution_patterns=[],
        )
        self.assertEqual(_plan_route(bctx, ctx), [])


# ---------------------------------------------------------------------------
# Specialist prompts
# ---------------------------------------------------------------------------

class TestSpecialistPrompts(unittest.TestCase):
    def _bctx(self, **overrides):
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
            call_graph_path=["ENTRY", "INIT", "MAIN-PARA"],
            gating_conditions=[{"variable": "WS-FLAG", "values": ["Y"], "negated": False}],
            stub_ops_in_slice=["READ:FILE"],
            stub_op_sequence=["OPEN:FILE", "READ:FILE"],
            stub_mapping={"READ:FILE": ["WS-STATUS"]},
            fault_tables={"status_file": ["00", "10"]},
            test_case_count=15, solution_patterns=[],
            parent_88_lookup={},
        )
        defaults.update(overrides)
        return BranchContext(**defaults)

    def test_condition_cracker(self):
        prompt = _build_condition_cracker_prompt(self._bctx())
        self.assertIn("WS-STATUS", prompt)
        self.assertIn("TRUE", prompt)

    def test_condition_cracker_88_level(self):
        bctx = self._bctx(
            condition_text="IF APPL-AOK",
            parent_88_lookup={"APPL-AOK": ("APPL-RESULT", 0)},
        )
        prompt = _build_condition_cracker_prompt(bctx)
        self.assertIn("APPL-RESULT", prompt)

    def test_path_finder(self):
        prompt = _build_path_finder_prompt(self._bctx())
        self.assertIn("reachability", prompt.lower())
        self.assertIn("ENTRY", prompt)

    def test_stub_architect(self):
        prompt = _build_stub_architect_prompt(self._bctx())
        self.assertIn("READ:FILE", prompt)
        self.assertIn("OPEN:FILE", prompt)

    def test_stub_architect_sequence(self):
        prompt = _build_stub_architect_prompt(self._bctx())
        self.assertIn("fire in this order", prompt)

    def test_history_miner(self):
        prompt = _build_history_miner_prompt(self._bctx())
        self.assertIn("mutation", prompt.lower())
        self.assertIn("WS-X", prompt)


class TestParseSpecialistResponse(unittest.TestCase):
    def test_valid_json(self):
        p = _parse_specialist_response(json.dumps({"input_state": {"X": "1"}, "reasoning": "ok"}), "cc")
        self.assertEqual(p.input_state, {"X": "1"})

    def test_empty(self):
        p = _parse_specialist_response(None, "cc")
        self.assertEqual(p.confidence, 0.0)

    def test_garbage(self):
        p = _parse_specialist_response("no json!!!", "cc")
        self.assertIn("could not parse", p.reasoning)


class TestMergeProposals(unittest.TestCase):
    def test_merges_all(self):
        proposals = [
            SpecialistProposal(specialist="path_finder", input_state={"GATE": "Y"}),
            SpecialistProposal(specialist="condition_cracker", input_state={"WS-X": "10"}),
            SpecialistProposal(specialist="stub_architect", stub_outcomes={"READ:F": [[["S", "00"]]]}),
        ]
        inp, stubs = _merge_proposals(proposals)
        self.assertEqual(inp["GATE"], "Y")
        self.assertIn("WS-X", inp)
        self.assertIn("READ:F", stubs)

    def test_empty_proposals(self):
        inp, stubs = _merge_proposals([SpecialistProposal(specialist="cc")])
        self.assertEqual(inp, {})
        self.assertEqual(stubs, {})


# ---------------------------------------------------------------------------
# Level 2: Gate Solver prompt + parsing
# ---------------------------------------------------------------------------

class TestFormatPriorFeedback(unittest.TestCase):
    def _bctx(self, **overrides):
        defaults = dict(
            bid=42, direction="T", branch_key="42:T",
            paragraph="TARGET-PARA", condition_text="IF X = '00'",
            backward_slice_code="", var_domain_info={},
            nearest_hit=None, call_graph_path=[], gating_conditions=[],
            stub_ops_in_slice=[], stub_op_sequence=[],
            stub_mapping={}, fault_tables={},
            test_case_count=0, solution_patterns=[],
            parent_88_lookup={},
        )
        defaults.update(overrides)
        return BranchContext(**defaults)

    def test_empty_feedback(self):
        result = _format_prior_feedback(None, self._bctx())
        self.assertEqual(result, "")

    def test_includes_cobol_trace(self):
        fb = JudgeFeedback(
            reached_paragraph=False,
            cobol_trace=["OPEN-FILES", "READ-RECORD", "ABEND-PROGRAM"],
        )
        result = _format_prior_feedback([fb], self._bctx())
        self.assertIn("OPEN-FILES", result)
        self.assertIn("ABEND-PROGRAM", result)
        self.assertIn("NEVER REACHED", result)

    def test_target_found_in_trace(self):
        fb = JudgeFeedback(
            reached_paragraph=True,
            cobol_trace=["OPEN-FILES", "READ-RECORD", "TARGET-PARA", "CLOSE-FILES"],
        )
        result = _format_prior_feedback([fb], self._bctx())
        self.assertIn("[TARGET-PARA]", result)
        self.assertNotIn("NEVER REACHED", result)

    def test_includes_error_display_output(self):
        fb = JudgeFeedback(
            display_output=["ERROR: Cannot open CUSTOMER-INPUT, Status: 35",
                            "SOME NORMAL MESSAGE"],
        )
        result = _format_prior_feedback([fb], self._bctx())
        self.assertIn("ERROR: Cannot open", result)
        self.assertNotIn("SOME NORMAL MESSAGE", result)

    def test_includes_actual_var_values(self):
        fb = JudgeFeedback(
            actual_var_values={"WS-STATUS": "10"},
        )
        result = _format_prior_feedback([fb], self._bctx())
        self.assertIn("WS-STATUS", result)
        self.assertIn("10", result)


class TestGateSolverPrompt(unittest.TestCase):
    def _bctx(self, **overrides):
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
            call_graph_path=[], gating_conditions=[],
            stub_ops_in_slice=["READ:FILE"],
            stub_op_sequence=["OPEN:FILE", "READ:FILE"],
            stub_mapping={"READ:FILE": ["WS-STATUS"]},
            fault_tables={"status_file": ["00", "10"]},
            test_case_count=15, solution_patterns=[],
            parent_88_lookup={},
        )
        defaults.update(overrides)
        return BranchContext(**defaults)

    def test_prompt_includes_backward_chaining(self):
        prompt = _build_gate_solver_prompt(self._bctx(), [])
        self.assertIn("backward", prompt.lower())
        self.assertIn("WS-STATUS", prompt)
        self.assertIn("TRUE", prompt)

    def test_prompt_includes_route(self):
        route = [
            ("ENTRY", []),
            ("INIT", [{"variable": "WS-MODE", "values": ["A"], "negated": False}]),
            ("MAIN-PARA", []),
        ]
        prompt = _build_gate_solver_prompt(self._bctx(), route)
        self.assertIn("EXECUTION ROUTE", prompt)
        self.assertIn("WS-MODE", prompt)
        self.assertIn("Step 1", prompt)

    def test_prompt_includes_stub_sequence(self):
        prompt = _build_gate_solver_prompt(self._bctx(), [])
        self.assertIn("STUB OPERATION SEQUENCE", prompt)
        self.assertIn("1. OPEN:FILE", prompt)
        self.assertIn("2. READ:FILE", prompt)
        self.assertIn("success", prompt.lower())

    def test_prompt_includes_88_level(self):
        bctx = self._bctx(
            condition_text="IF APPL-AOK",
            parent_88_lookup={"APPL-AOK": ("APPL-RESULT", 0)},
            var_domain_info={},
        )
        prompt = _build_gate_solver_prompt(bctx, [])
        self.assertIn("APPL-RESULT", prompt)
        self.assertIn("88-level", prompt)

    def test_prompt_includes_diagnosis_on_retry(self):
        diag = "  WS-STATUS = '' (set by stub READ:FILE)\n  nearby branches: [-42]"
        prompt = _build_gate_solver_prompt(self._bctx(), [], diagnosis=diag)
        self.assertIn("PREVIOUS ATTEMPT FAILED", prompt)
        self.assertIn("WS-STATUS = ''", prompt)

    def test_prompt_includes_nearest_hit(self):
        prompt = _build_gate_solver_prompt(self._bctx(), [])
        self.assertIn("NEAREST-HIT", prompt)
        self.assertIn("WS-X", prompt)


class TestParseGateSolverResponse(unittest.TestCase):
    def test_valid_json(self):
        resp = json.dumps({
            "input_state": {"WS-X": "A"},
            "stub_outcomes": {"READ:F": [[["S", "00"]]]},
            "reasoning": "test",
        })
        inp, stubs, reason = _parse_gate_solver_response(resp)
        self.assertEqual(inp, {"WS-X": "A"})
        self.assertEqual(stubs, {"READ:F": [[["S", "00"]]]})

    def test_empty_response(self):
        inp, stubs, reason = _parse_gate_solver_response(None)
        self.assertEqual(inp, {})
        self.assertIn("empty", reason)

    def test_garbage_response(self):
        inp, stubs, reason = _parse_gate_solver_response("no json at all!!!")
        self.assertEqual(inp, {})
        self.assertIn("could not parse", reason)

    def test_markdown_fenced(self):
        resp = "```json\n" + json.dumps({
            "input_state": {"A": 1},
            "reasoning": "fenced",
        }) + "\n```"
        inp, stubs, reason = _parse_gate_solver_response(resp)
        self.assertEqual(inp, {"A": 1})


# ---------------------------------------------------------------------------
# Level 2.5: Python forward validation
# ---------------------------------------------------------------------------

class TestValidatePython(unittest.TestCase):
    def test_returns_false_when_no_module(self):
        bctx = BranchContext(
            bid=1, direction="T", branch_key="1:T", paragraph="P",
            condition_text="", backward_slice_code="", var_domain_info={},
            nearest_hit=None, call_graph_path=[], gating_conditions=[],
            stub_ops_in_slice=[], stub_mapping={}, fault_tables={},
            test_case_count=0, solution_patterns=[],
        )
        ok, diag = _validate_python(None, bctx, {}, {})
        self.assertFalse(ok)
        self.assertIn("no module", diag)


# ---------------------------------------------------------------------------
# Level 3: Tape Builder
# ---------------------------------------------------------------------------

class TestBuildTape(unittest.TestCase):
    def test_returns_empty_when_no_module(self):
        bctx = BranchContext(
            bid=1, direction="T", branch_key="1:T", paragraph="P",
            condition_text="", backward_slice_code="", var_domain_info={},
            nearest_hit=None, call_graph_path=[], gating_conditions=[],
            stub_ops_in_slice=[], stub_mapping={}, fault_tables={},
            test_case_count=0, solution_patterns=[],
        )
        ctx = SimpleNamespace(module=None)
        inp, log = _build_tape(bctx, ctx, {"X": "1"}, {})
        self.assertEqual(inp, {"X": "1"})
        self.assertEqual(log, [])

    def test_filters_tape_to_relevant_stub_ops(self):
        bctx = BranchContext(
            bid=1, direction="T", branch_key="1:T", paragraph="P",
            condition_text="", backward_slice_code="", var_domain_info={},
            nearest_hit=None, call_graph_path=[], gating_conditions=[],
            stub_ops_in_slice=[], stub_mapping={}, fault_tables={},
            test_case_count=0, solution_patterns=[],
            stub_op_sequence=["START:RVLTABLE"],
        )
        ctx = SimpleNamespace(module=object(), domains={})

        with patch("specter.cobol_coverage._python_pre_run", return_value=[
            ("OPEN:FILE", []),
            ("START:RVLTABLE", [("FILE-STATUS-RVLTABLE-WS", "35")]),
            ("READ:FILE", []),
        ]):
            inp, log = _build_tape(
                bctx,
                ctx,
                {"X": "1"},
                {"START:RVLTABLE": [[("FILE-STATUS-RVLTABLE-WS", "35")]]},
            )

        self.assertEqual(inp, {"X": "1"})
        self.assertEqual(log, [("START:RVLTABLE", [("FILE-STATUS-RVLTABLE-WS", "35")])])


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
                        SpecialistProposal(specialist="gate_solver", reasoning="try A"),
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
# Context gathering
# ---------------------------------------------------------------------------

class TestIterativeDeepening(unittest.TestCase):
    """Test that investigate_branch_swarm splits into Phase 1 (Reach) and Phase 2 (Flip)."""

    def test_phase1_skipped_when_paragraph_already_reached(self):
        """When the target paragraph is already in cov.paragraphs_hit,
        Phase 1 is skipped and all rounds go to Phase 2."""
        from specter.branch_swarm import investigate_branch_swarm

        ctx = SimpleNamespace(
            branch_meta={"1": {"paragraph": "MAIN", "condition": "IF X = 'Y'"}},
            module=None, domains={}, stub_mapping={}, call_graph=None,
            gating_conds={}, memory_state=None, memory_store=None,
            var_report=None, context=None, store_path=None,
        )
        cov = SimpleNamespace(
            test_cases=[], branches_hit=set(),
            paragraphs_hit={"MAIN"},  # already reached
            all_paragraphs={"MAIN"},
            runtime_only_paragraphs=set(),
            total_branches=2,
        )
        report = SimpleNamespace(
            branches_total=2, branches_hit=0,
            total_test_cases=0, elapsed_seconds=0,
            layer_stats={},
        )

        # No LLM → returns immediately, but we can check the journal
        journal, _ = investigate_branch_swarm(
            bid=1, direction="T", ctx=ctx, cov=cov, report=report,
            tc_count=0, max_rounds=3, llm_provider=None,
        )
        self.assertEqual(journal.final_reasoning, "no LLM provider configured")

    def test_phase1_allocated_when_paragraph_not_reached(self):
        """When the paragraph hasn't been reached, Phase 1 gets rounds."""
        # This is a structural test — verify the flow doesn't crash
        from specter.branch_swarm import investigate_branch_swarm

        ctx = SimpleNamespace(
            branch_meta={"1": {"paragraph": "UNREACHED", "condition": "IF X = 'Y'"}},
            module=None, domains={}, stub_mapping={}, call_graph=None,
            gating_conds={}, memory_state=None, memory_store=None,
            var_report=None, context=None, store_path=None,
        )
        cov = SimpleNamespace(
            test_cases=[], branches_hit=set(),
            paragraphs_hit=set(),  # NOT reached
            all_paragraphs={"UNREACHED"},
            runtime_only_paragraphs=set(),
            total_branches=2,
        )
        report = SimpleNamespace(
            branches_total=2, branches_hit=0,
            total_test_cases=0, elapsed_seconds=0,
            layer_stats={},
        )

        journal, _ = investigate_branch_swarm(
            bid=1, direction="T", ctx=ctx, cov=cov, report=report,
            tc_count=0, max_rounds=3, llm_provider=None,
        )
        self.assertIn("no LLM", journal.final_reasoning)


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
            var_report=None,
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
            var_report=None,
        )
        cov = SimpleNamespace(test_cases=[], branches_hit=set())
        bctx = _gather_branch_context(99, "F", ctx, cov)
        self.assertEqual(bctx.paragraph, "")


if __name__ == "__main__":
    unittest.main()
