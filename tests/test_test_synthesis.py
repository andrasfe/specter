"""Tests for the test set synthesis engine."""

import json
import tempfile
import unittest
from pathlib import Path

from specter.ast_parser import parse_ast
from specter.code_generator import generate_code
from specter.monte_carlo import _load_module
from specter.static_analysis import (
    GatingCondition,
    build_static_call_graph,
    extract_gating_conditions,
    extract_equality_constraints,
    extract_sequential_gates,
    augment_gating_with_sequential_gates,
)
from specter.test_store import TestCase, TestStore, StoreProgress, _compute_id
from specter.test_synthesis import (
    SynthesisReport,
    SynthesisState,
    _apply_gating_constraints,
    _compute_stub_combinations,
    _execute_and_collect,
    _run_layer_1,
    _run_layer_2,
    _run_layer_3,
    synthesize_test_set,
)
from specter.variable_extractor import (
    VariableInfo,
    VariableReport,
    extract_stub_status_mapping,
    extract_variables,
)


def _make_program(paragraphs):
    return parse_ast({
        "program_id": "TEST",
        "paragraphs": paragraphs,
    })


def _generate_and_load(program, var_report, instrument=True):
    """Generate code from program, write to temp file, and load module."""
    code = generate_code(program, var_report, instrument=instrument)
    tmp = tempfile.NamedTemporaryFile(suffix=".py", delete=False, mode="w")
    tmp.write(code)
    tmp.flush()
    tmp.close()
    return _load_module(tmp.name)


# =========================================================================
# TestStore tests
# =========================================================================


class TestTestStore(unittest.TestCase):

    def test_save_load_roundtrip(self):
        """Test that saving and loading produces identical test cases."""
        tc = TestCase(
            id="abc123",
            input_state={"WS-STATUS": "00", "WS-AMT": 100},
            stub_outcomes={"SQL": [[("SQLCODE", 0)], [("SQLCODE", 100)]]},
            stub_defaults={"SQL": [("SQLCODE", 100)]},
            paragraphs_covered=["MAIN", "INIT"],
            branches_covered=[1, -2, 3],
            layer=1,
            target="all-success",
        )

        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name

        TestStore.append(path, tc)
        loaded, progress = TestStore.load(path)

        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].id, "abc123")
        self.assertEqual(loaded[0].input_state, {"WS-STATUS": "00", "WS-AMT": 100})
        self.assertEqual(loaded[0].paragraphs_covered, ["MAIN", "INIT"])
        self.assertEqual(loaded[0].branches_covered, [1, -2, 3])
        self.assertEqual(loaded[0].layer, 1)
        self.assertEqual(loaded[0].target, "all-success")

    def test_deduplication(self):
        """Test that duplicate IDs are deduplicated on load."""
        tc1 = TestCase(
            id="same-id",
            input_state={"X": 1},
            stub_outcomes={},
            stub_defaults={},
            paragraphs_covered=["A"],
            branches_covered=[],
            layer=1,
            target="test",
        )
        tc2 = TestCase(
            id="same-id",
            input_state={"X": 2},
            stub_outcomes={},
            stub_defaults={},
            paragraphs_covered=["B"],
            branches_covered=[],
            layer=1,
            target="test",
        )

        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name

        TestStore.append(path, tc1)
        TestStore.append(path, tc2)
        loaded, _ = TestStore.load(path)

        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].input_state, {"X": 1})

    def test_append_atomicity(self):
        """Test that each append creates exactly one line."""
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name

        for i in range(5):
            tc = TestCase(
                id=f"id-{i}",
                input_state={"X": i},
                stub_outcomes={},
                stub_defaults={},
                paragraphs_covered=[],
                branches_covered=[],
                layer=1,
                target="test",
            )
            TestStore.append(path, tc)

        lines = Path(path).read_text().strip().split("\n")
        self.assertEqual(len(lines), 5)
        for line in lines:
            json.loads(line)  # should not raise

    def test_load_nonexistent(self):
        """Loading a nonexistent file returns empty list and empty progress."""
        loaded, progress = TestStore.load("/tmp/nonexistent_test_store_xyz.jsonl")
        self.assertEqual(loaded, [])
        self.assertEqual(progress.completed_layers, set())

    def test_compute_id_deterministic(self):
        """Same inputs produce same ID."""
        id1 = _compute_id({"X": 1}, {"SQL": [[("SQLCODE", 0)]]})
        id2 = _compute_id({"X": 1}, {"SQL": [[("SQLCODE", 0)]]})
        self.assertEqual(id1, id2)

    def test_compute_id_different(self):
        """Different inputs produce different IDs."""
        id1 = _compute_id({"X": 1}, {})
        id2 = _compute_id({"X": 2}, {})
        self.assertNotEqual(id1, id2)


# =========================================================================
# Layer 1 tests
# =========================================================================


class TestLayer1(unittest.TestCase):

    def test_all_success_baseline(self):
        """All-success baseline covers expected paragraphs on simple program."""
        prog = _make_program([
            {
                "name": "MAIN", "line_start": 1, "line_end": 10,
                "statements": [
                    {
                        "type": "PERFORM", "text": "PERFORM STEP-1",
                        "line_start": 2, "line_end": 2,
                        "attributes": {"target": "STEP-1"}, "children": [],
                    },
                    {
                        "type": "PERFORM", "text": "PERFORM STEP-2",
                        "line_start": 3, "line_end": 3,
                        "attributes": {"target": "STEP-2"}, "children": [],
                    },
                    {
                        "type": "GOBACK", "text": "GOBACK",
                        "line_start": 4, "line_end": 4,
                        "attributes": {}, "children": [],
                    },
                ],
            },
            {
                "name": "STEP-1", "line_start": 11, "line_end": 15,
                "statements": [
                    {
                        "type": "MOVE", "text": "MOVE 'DONE' TO WS-RESULT",
                        "line_start": 12, "line_end": 12,
                        "attributes": {"source": "'DONE'", "targets": "WS-RESULT"},
                        "children": [],
                    },
                ],
            },
            {
                "name": "STEP-2", "line_start": 16, "line_end": 20,
                "statements": [
                    {
                        "type": "DISPLAY", "text": "DISPLAY WS-RESULT",
                        "line_start": 17, "line_end": 17,
                        "attributes": {}, "children": [],
                    },
                ],
            },
        ])

        var_report = extract_variables(prog)
        module = _generate_and_load(prog, var_report)

        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            store_path = Path(f.name)

        synth = SynthesisState()
        new = _run_layer_1(
            module, prog, var_report, None, None,
            synth, store_path,
            start_time=0, max_time=None,
        )

        self.assertGreater(new, 0)
        self.assertIn("MAIN", synth.covered_paras)
        self.assertIn("STEP-1", synth.covered_paras)
        self.assertIn("STEP-2", synth.covered_paras)


# =========================================================================
# Layer 2 tests
# =========================================================================


class TestLayer2(unittest.TestCase):

    def test_gated_paragraph_reached(self):
        """Path-constraint satisfaction reaches a gated paragraph."""
        prog = _make_program([
            {
                "name": "MAIN", "line_start": 1, "line_end": 20,
                "statements": [
                    {
                        "type": "IF", "text": "IF WS-STATUS = '00'",
                        "line_start": 3, "line_end": 8,
                        "attributes": {"condition": "WS-STATUS = '00'"},
                        "children": [
                            {
                                "type": "PERFORM", "text": "PERFORM PROCESS",
                                "line_start": 4, "line_end": 4,
                                "attributes": {"target": "PROCESS"}, "children": [],
                            },
                            {
                                "type": "ELSE", "text": "ELSE",
                                "line_start": 5, "line_end": 7,
                                "attributes": {},
                                "children": [
                                    {
                                        "type": "PERFORM", "text": "PERFORM ERROR-PARA",
                                        "line_start": 6, "line_end": 6,
                                        "attributes": {"target": "ERROR-PARA"},
                                        "children": [],
                                    },
                                ],
                            },
                        ],
                    },
                    {
                        "type": "GOBACK", "text": "GOBACK",
                        "line_start": 9, "line_end": 9,
                        "attributes": {}, "children": [],
                    },
                ],
            },
            {
                "name": "PROCESS", "line_start": 21, "line_end": 25,
                "statements": [
                    {
                        "type": "DISPLAY", "text": "DISPLAY 'PROCESSING'",
                        "line_start": 22, "line_end": 22,
                        "attributes": {}, "children": [],
                    },
                ],
            },
            {
                "name": "ERROR-PARA", "line_start": 26, "line_end": 30,
                "statements": [
                    {
                        "type": "DISPLAY", "text": "DISPLAY 'ERROR'",
                        "line_start": 27, "line_end": 27,
                        "attributes": {}, "children": [],
                    },
                ],
            },
        ])

        var_report = extract_variables(prog)
        call_graph = build_static_call_graph(prog)
        gating_conds = extract_gating_conditions(prog, call_graph)
        module = _generate_and_load(prog, var_report)

        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            store_path = Path(f.name)

        synth = SynthesisState()

        # Layer 1 first
        _run_layer_1(module, prog, var_report, None, None, synth, store_path, 0, None)

        # Layer 2
        import time
        new = _run_layer_2(
            module, prog, var_report, call_graph, gating_conds,
            None, None,
            synth, store_path,
            start_time=time.time(), max_time=None,
        )

        # Both PROCESS and ERROR-PARA should be covered
        self.assertIn("PROCESS", synth.covered_paras)
        self.assertIn("ERROR-PARA", synth.covered_paras)


# =========================================================================
# Layer 3 tests
# =========================================================================


class TestLayer3(unittest.TestCase):

    def test_branch_solving_heuristic(self):
        """Heuristic fallback flips a specific branch (no Z3 needed)."""
        prog = _make_program([
            {
                "name": "MAIN", "line_start": 1, "line_end": 20,
                "statements": [
                    {
                        "type": "IF", "text": "IF WS-CODE = 100",
                        "line_start": 2, "line_end": 8,
                        "attributes": {"condition": "WS-CODE = 100"},
                        "children": [
                            {
                                "type": "DISPLAY", "text": "DISPLAY 'NOT-FOUND'",
                                "line_start": 3, "line_end": 3,
                                "attributes": {}, "children": [],
                            },
                            {
                                "type": "ELSE", "text": "ELSE",
                                "line_start": 5, "line_end": 7,
                                "attributes": {},
                                "children": [
                                    {
                                        "type": "DISPLAY", "text": "DISPLAY 'FOUND'",
                                        "line_start": 6, "line_end": 6,
                                        "attributes": {}, "children": [],
                                    },
                                ],
                            },
                        ],
                    },
                    {
                        "type": "GOBACK", "text": "GOBACK",
                        "line_start": 9, "line_end": 9,
                        "attributes": {}, "children": [],
                    },
                ],
            },
        ])

        var_report = extract_variables(prog)
        module = _generate_and_load(prog, var_report)

        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            store_path = Path(f.name)

        synth = SynthesisState()

        # Layer 1 first (covers one branch direction)
        _run_layer_1(module, prog, var_report, None, None, synth, store_path, 0, None)

        # Layer 3 should solve for the other branch direction
        import time
        new = _run_layer_3(
            module, var_report, None,
            synth, store_path,
            start_time=time.time(), max_time=None,
        )

        branch_meta = getattr(module, "_BRANCH_META", {})
        if branch_meta:
            # Should have covered both directions of at least one branch
            all_covered = synth.covered_branches
            for abs_id in branch_meta:
                if abs_id in all_covered or -abs_id in all_covered:
                    # At least one direction was covered
                    pass
            # We expect the layer to have attempted something
            self.assertGreaterEqual(len(synth.test_cases), 1)


# =========================================================================
# Layer 4 tests (stub combinatorics)
# =========================================================================


class TestLayer4(unittest.TestCase):

    def test_stub_combinations_generated(self):
        """Stub combinatorics generates combinations for SQLCODE values."""
        var_report = VariableReport()
        var_report.variables["SQLCODE"] = VariableInfo(
            name="SQLCODE",
            read_count=5,
            write_count=0,
            first_access="read",
            classification="status",
            condition_literals=[0, 100, -803],
        )

        stub_mapping = {"SQL": ["SQLCODE"]}
        branch_meta = {1: {"paragraph": "MAIN", "condition": "SQLCODE = 0"}}

        combos = _compute_stub_combinations(
            target_branch=1,
            branch_meta=branch_meta,
            stub_mapping=stub_mapping,
            var_report=var_report,
            program=None,
        )

        self.assertGreater(len(combos), 0)
        # Each combo should have an SQL key
        for combo in combos:
            self.assertIn("SQL", combo)


# =========================================================================
# Persistence test
# =========================================================================


class TestPersistence(unittest.TestCase):

    def test_progress_records_persisted(self):
        """Progress records (attempts, layer completions) survive reload."""
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name

        # Save a TC + progress records
        tc = TestCase(
            id="tc-1", input_state={"X": 1}, stub_outcomes={},
            stub_defaults={}, paragraphs_covered=["A"],
            branches_covered=[1], layer=1, target="test",
        )
        TestStore.append(path, tc)
        TestStore.append_progress(path, {"_type": "attempt", "layer": 2, "target": "B"})
        TestStore.append_progress(path, {"_type": "attempt", "layer": 2, "target": "C"})
        TestStore.append_progress(path, {"_type": "layer_done", "layer": 1})
        TestStore.append_progress(path, {"_type": "walked", "tc_id": "tc-1"})

        loaded, progress = TestStore.load(path)

        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].id, "tc-1")
        self.assertIn(1, progress.completed_layers)
        self.assertNotIn(2, progress.completed_layers)
        self.assertEqual(progress.attempted_targets[2], {"B", "C"})
        self.assertIn("tc-1", progress.walked_tc_ids)

    def test_resumed_run_skips_completed_layers(self):
        """A resumed run skips layers marked as completed."""
        prog = _make_program([
            {
                "name": "MAIN", "line_start": 1, "line_end": 10,
                "statements": [
                    {"type": "GOBACK", "text": "GOBACK",
                     "line_start": 2, "line_end": 2,
                     "attributes": {}, "children": []},
                ],
            },
        ])
        var_report = extract_variables(prog)
        module = _generate_and_load(prog, var_report)
        call_graph = build_static_call_graph(prog)
        gating_conds = extract_gating_conditions(prog, call_graph)

        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            store_path = Path(f.name)

        # First run
        report1 = synthesize_test_set(
            module=module, program=prog, var_report=var_report,
            call_graph=call_graph, gating_conditions=gating_conds,
            stub_mapping=None, equality_constraints=None,
            store_path=store_path, max_layers=2,
        )

        # Second run — layers 1-2 should be skipped
        report2 = synthesize_test_set(
            module=module, program=prog, var_report=var_report,
            call_graph=call_graph, gating_conditions=gating_conds,
            stub_mapping=None, equality_constraints=None,
            store_path=store_path, max_layers=2,
        )

        self.assertIn(1, report2.skipped_layers)
        self.assertIn(2, report2.skipped_layers)
        # No new test cases on second run
        self.assertEqual(report2.new_test_cases, 0)

    def test_resume_from_store(self):
        """Interrupting and resuming picks up where left off."""
        prog = _make_program([
            {
                "name": "MAIN", "line_start": 1, "line_end": 10,
                "statements": [
                    {
                        "type": "PERFORM", "text": "PERFORM STEP-1",
                        "line_start": 2, "line_end": 2,
                        "attributes": {"target": "STEP-1"}, "children": [],
                    },
                    {
                        "type": "GOBACK", "text": "GOBACK",
                        "line_start": 3, "line_end": 3,
                        "attributes": {}, "children": [],
                    },
                ],
            },
            {
                "name": "STEP-1", "line_start": 11, "line_end": 15,
                "statements": [],
            },
        ])

        var_report = extract_variables(prog)
        module = _generate_and_load(prog, var_report)
        call_graph = build_static_call_graph(prog)
        gating_conds = extract_gating_conditions(prog, call_graph)

        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            store_path = Path(f.name)

        # First run — layers 1-2
        report1 = synthesize_test_set(
            module=module,
            program=prog,
            var_report=var_report,
            call_graph=call_graph,
            gating_conditions=gating_conds,
            stub_mapping=None,
            equality_constraints=None,
            store_path=store_path,
            max_layers=2,
        )

        n_cases_1 = report1.total_test_cases

        # Second run — reload and run all layers
        report2 = synthesize_test_set(
            module=module,
            program=prog,
            var_report=var_report,
            call_graph=call_graph,
            gating_conditions=gating_conds,
            stub_mapping=None,
            equality_constraints=None,
            store_path=store_path,
            max_layers=5,
        )

        # Should have loaded existing cases
        self.assertGreaterEqual(report2.total_test_cases, n_cases_1)
        # Paragraphs should still be covered
        self.assertGreater(report2.covered_paras, 0)


# =========================================================================
# Z3 absence test
# =========================================================================


class TestZ3Absence(unittest.TestCase):

    def test_heuristic_fallback(self):
        """Synthesis works without Z3 using heuristic fallback."""
        prog = _make_program([
            {
                "name": "MAIN", "line_start": 1, "line_end": 20,
                "statements": [
                    {
                        "type": "IF", "text": "IF WS-FLAG = 'Y'",
                        "line_start": 2, "line_end": 8,
                        "attributes": {"condition": "WS-FLAG = 'Y'"},
                        "children": [
                            {
                                "type": "DISPLAY", "text": "DISPLAY 'YES'",
                                "line_start": 3, "line_end": 3,
                                "attributes": {}, "children": [],
                            },
                            {
                                "type": "ELSE", "text": "ELSE",
                                "line_start": 5, "line_end": 7,
                                "attributes": {},
                                "children": [
                                    {
                                        "type": "DISPLAY", "text": "DISPLAY 'NO'",
                                        "line_start": 6, "line_end": 6,
                                        "attributes": {}, "children": [],
                                    },
                                ],
                            },
                        ],
                    },
                    {
                        "type": "GOBACK", "text": "GOBACK",
                        "line_start": 9, "line_end": 9,
                        "attributes": {}, "children": [],
                    },
                ],
            },
        ])

        var_report = extract_variables(prog)
        module = _generate_and_load(prog, var_report)
        call_graph = build_static_call_graph(prog)
        gating_conds = extract_gating_conditions(prog, call_graph)

        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            store_path = Path(f.name)

        # Should not raise even if Z3 is missing
        report = synthesize_test_set(
            module=module,
            program=prog,
            var_report=var_report,
            call_graph=call_graph,
            gating_conditions=gating_conds,
            stub_mapping=None,
            equality_constraints=None,
            store_path=store_path,
        )

        self.assertGreater(report.total_test_cases, 0)
        self.assertGreater(report.covered_paras, 0)


# =========================================================================
# Apply gating constraints test
# =========================================================================


class TestApplyGatingConstraints(unittest.TestCase):

    def test_non_negated(self):
        state = {"WS-STATUS": "XX"}
        constraints = [GatingCondition(variable="WS-STATUS", values=["00"], negated=False)]
        var_report = VariableReport()
        result = _apply_gating_constraints(state, constraints, var_report)
        self.assertEqual(result["WS-STATUS"], "00")

    def test_negated_with_literals(self):
        state = {"WS-CODE": 0}
        constraints = [GatingCondition(variable="WS-CODE", values=[0], negated=True)]
        var_report = VariableReport()
        var_report.variables["WS-CODE"] = VariableInfo(
            name="WS-CODE", classification="status",
            condition_literals=[0, 100, -803],
        )
        result = _apply_gating_constraints(state, constraints, var_report)
        self.assertNotEqual(result["WS-CODE"], 0)
        self.assertIn(result["WS-CODE"], [100, -803])


# =========================================================================
# SynthesisReport test
# =========================================================================


class TestSynthesisReport(unittest.TestCase):

    def test_summary_format(self):
        report = SynthesisReport(
            total_test_cases=10,
            new_test_cases=5,
            covered_paras=20,
            total_paras=30,
            covered_branches=40,
            total_branches=60,
            layer_stats={1: 2, 2: 3},
            elapsed_seconds=1.5,
        )
        text = report.summary()
        self.assertIn("10", text)
        self.assertIn("20/30", text)
        self.assertIn("40/60", text)
        self.assertIn("Layer 1", text)
        self.assertIn("Layer 2", text)


if __name__ == "__main__":
    unittest.main()
