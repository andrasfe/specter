"""Tests for static reachability analysis."""

import unittest

from specter.ast_parser import parse_ast
from specter.static_analysis import (
    GatingCondition,
    SequentialGate,
    StaticCallGraph,
    augment_gating_with_sequential_gates,
    build_static_call_graph,
    compute_path_constraints,
    extract_gating_conditions,
    extract_sequential_gates,
)


def _make_program(paragraphs):
    return parse_ast({
        "program_id": "TEST",
        "paragraphs": paragraphs,
    })


class TestBuildStaticCallGraph(unittest.TestCase):

    def test_simple_perform_edge(self):
        prog = _make_program([
            {
                "name": "MAIN", "line_start": 1, "line_end": 5,
                "statements": [{
                    "type": "PERFORM", "text": "PERFORM STEP-1",
                    "line_start": 1, "line_end": 1,
                    "attributes": {"target": "STEP-1"}, "children": [],
                }],
            },
            {
                "name": "STEP-1", "line_start": 6, "line_end": 10,
                "statements": [],
            },
        ])
        cg = build_static_call_graph(prog)
        self.assertEqual(cg.entry, "MAIN")
        self.assertIn("STEP-1", cg.edges.get("MAIN", set()))
        self.assertIn("MAIN", cg.reverse_edges.get("STEP-1", set()))

    def test_reachable_and_unreachable(self):
        prog = _make_program([
            {
                "name": "MAIN", "line_start": 1, "line_end": 5,
                "statements": [{
                    "type": "PERFORM", "text": "PERFORM A",
                    "line_start": 1, "line_end": 1,
                    "attributes": {"target": "A"}, "children": [],
                }],
            },
            {
                "name": "A", "line_start": 6, "line_end": 10,
                "statements": [{
                    "type": "PERFORM", "text": "PERFORM B",
                    "line_start": 6, "line_end": 6,
                    "attributes": {"target": "B"}, "children": [],
                }],
            },
            {
                "name": "B", "line_start": 11, "line_end": 15,
                "statements": [],
            },
            {
                "name": "ORPHAN", "line_start": 16, "line_end": 20,
                "statements": [],
            },
        ])
        cg = build_static_call_graph(prog)
        self.assertIn("MAIN", cg.reachable)
        self.assertIn("A", cg.reachable)
        self.assertIn("B", cg.reachable)
        self.assertIn("ORPHAN", cg.unreachable)
        self.assertNotIn("ORPHAN", cg.reachable)

    def test_path_to(self):
        prog = _make_program([
            {
                "name": "MAIN", "line_start": 1, "line_end": 5,
                "statements": [{
                    "type": "PERFORM", "text": "PERFORM A",
                    "line_start": 1, "line_end": 1,
                    "attributes": {"target": "A"}, "children": [],
                }],
            },
            {
                "name": "A", "line_start": 6, "line_end": 10,
                "statements": [{
                    "type": "PERFORM", "text": "PERFORM B",
                    "line_start": 6, "line_end": 6,
                    "attributes": {"target": "B"}, "children": [],
                }],
            },
            {
                "name": "B", "line_start": 11, "line_end": 15,
                "statements": [],
            },
        ])
        cg = build_static_call_graph(prog)
        path = cg.path_to("B")
        self.assertEqual(path, ["MAIN", "A", "B"])

    def test_path_to_unreachable_returns_none(self):
        prog = _make_program([
            {
                "name": "MAIN", "line_start": 1, "line_end": 5,
                "statements": [],
            },
            {
                "name": "ORPHAN", "line_start": 6, "line_end": 10,
                "statements": [],
            },
        ])
        cg = build_static_call_graph(prog)
        self.assertIsNone(cg.path_to("ORPHAN"))

    def test_path_to_self(self):
        prog = _make_program([{
            "name": "MAIN", "line_start": 1, "line_end": 5,
            "statements": [],
        }])
        cg = build_static_call_graph(prog)
        self.assertEqual(cg.path_to("MAIN"), ["MAIN"])

    def test_frontier(self):
        prog = _make_program([
            {
                "name": "MAIN", "line_start": 1, "line_end": 5,
                "statements": [{
                    "type": "PERFORM", "text": "PERFORM A",
                    "line_start": 1, "line_end": 1,
                    "attributes": {"target": "A"}, "children": [],
                }],
            },
            {
                "name": "A", "line_start": 6, "line_end": 10,
                "statements": [],
            },
        ])
        cg = build_static_call_graph(prog)
        frontier = cg.frontier({"MAIN"})
        self.assertEqual(frontier, {"A"})

    def test_goto_edge(self):
        prog = _make_program([
            {
                "name": "MAIN", "line_start": 1, "line_end": 5,
                "statements": [{
                    "type": "GO_TO", "text": "GO TO EXIT-PARA",
                    "line_start": 1, "line_end": 1,
                    "attributes": {"target": "EXIT-PARA"}, "children": [],
                }],
            },
            {
                "name": "EXIT-PARA", "line_start": 6, "line_end": 10,
                "statements": [],
            },
        ])
        cg = build_static_call_graph(prog)
        self.assertIn("EXIT-PARA", cg.edges.get("MAIN", set()))

    def test_perform_thru_edge(self):
        prog = _make_program([
            {
                "name": "MAIN", "line_start": 1, "line_end": 5,
                "statements": [{
                    "type": "PERFORM_THRU", "text": "PERFORM A THRU A-EXIT",
                    "line_start": 1, "line_end": 1,
                    "attributes": {"target": "A"}, "children": [],
                }],
            },
            {
                "name": "A", "line_start": 6, "line_end": 10,
                "statements": [],
            },
        ])
        cg = build_static_call_graph(prog)
        self.assertIn("A", cg.edges.get("MAIN", set()))

    def test_nested_if_perform(self):
        """PERFORM inside IF should still create an edge."""
        prog = _make_program([
            {
                "name": "MAIN", "line_start": 1, "line_end": 10,
                "statements": [{
                    "type": "IF", "text": "IF X = 'Y'",
                    "line_start": 1, "line_end": 5,
                    "attributes": {"condition": "X = 'Y'"},
                    "children": [{
                        "type": "PERFORM", "text": "PERFORM NESTED",
                        "line_start": 2, "line_end": 2,
                        "attributes": {"target": "NESTED"}, "children": [],
                    }],
                }],
            },
            {
                "name": "NESTED", "line_start": 11, "line_end": 15,
                "statements": [],
            },
        ])
        cg = build_static_call_graph(prog)
        self.assertIn("NESTED", cg.edges.get("MAIN", set()))


class TestExtractGatingConditions(unittest.TestCase):

    def test_simple_if_gating(self):
        prog = _make_program([{
            "name": "MAIN", "line_start": 1, "line_end": 10,
            "statements": [{
                "type": "IF", "text": "IF WS-CODE = '00'",
                "line_start": 1, "line_end": 5,
                "attributes": {"condition": "WS-CODE = '00'"},
                "children": [{
                    "type": "PERFORM", "text": "PERFORM SUCCESS-PARA",
                    "line_start": 2, "line_end": 2,
                    "attributes": {"target": "SUCCESS-PARA"}, "children": [],
                }],
            }],
        }, {
            "name": "SUCCESS-PARA", "line_start": 11, "line_end": 15,
            "statements": [],
        }])
        cg = build_static_call_graph(prog)
        gating = extract_gating_conditions(prog, cg)
        self.assertIn("SUCCESS-PARA", gating)
        conditions = gating["SUCCESS-PARA"]
        self.assertTrue(any(gc.variable == "WS-CODE" for gc in conditions))
        matching = [gc for gc in conditions if gc.variable == "WS-CODE"]
        self.assertIn("00", matching[0].values)

    def test_else_branch_negated(self):
        prog = _make_program([{
            "name": "MAIN", "line_start": 1, "line_end": 10,
            "statements": [{
                "type": "IF", "text": "IF SQLCODE = 0",
                "line_start": 1, "line_end": 5,
                "attributes": {"condition": "SQLCODE = 0"},
                "children": [
                    {
                        "type": "PERFORM", "text": "PERFORM OK-PARA",
                        "line_start": 2, "line_end": 2,
                        "attributes": {"target": "OK-PARA"}, "children": [],
                    },
                    {
                        "type": "ELSE", "text": "ELSE",
                        "line_start": 3, "line_end": 4,
                        "attributes": {},
                        "children": [{
                            "type": "PERFORM", "text": "PERFORM ERROR-PARA",
                            "line_start": 4, "line_end": 4,
                            "attributes": {"target": "ERROR-PARA"},
                            "children": [],
                        }],
                    },
                ],
            }],
        }, {
            "name": "OK-PARA", "line_start": 11, "line_end": 15,
            "statements": [],
        }, {
            "name": "ERROR-PARA", "line_start": 16, "line_end": 20,
            "statements": [],
        }])
        cg = build_static_call_graph(prog)
        gating = extract_gating_conditions(prog, cg)

        # OK-PARA should have non-negated condition
        ok_conds = gating.get("OK-PARA", [])
        self.assertTrue(any(not gc.negated for gc in ok_conds))

        # ERROR-PARA should have negated condition
        err_conds = gating.get("ERROR-PARA", [])
        self.assertTrue(any(gc.negated for gc in err_conds))

    def test_no_condition_no_gating(self):
        prog = _make_program([{
            "name": "MAIN", "line_start": 1, "line_end": 5,
            "statements": [{
                "type": "PERFORM", "text": "PERFORM TARGET",
                "line_start": 1, "line_end": 1,
                "attributes": {"target": "TARGET"}, "children": [],
            }],
        }, {
            "name": "TARGET", "line_start": 6, "line_end": 10,
            "statements": [],
        }])
        cg = build_static_call_graph(prog)
        gating = extract_gating_conditions(prog, cg)
        self.assertNotIn("TARGET", gating)


class TestComputePathConstraints(unittest.TestCase):

    def test_collects_constraints_along_path(self):
        prog = _make_program([
            {
                "name": "MAIN", "line_start": 1, "line_end": 10,
                "statements": [{
                    "type": "IF", "text": "IF WS-CODE = 'A'",
                    "line_start": 1, "line_end": 5,
                    "attributes": {"condition": "WS-CODE = 'A'"},
                    "children": [{
                        "type": "PERFORM", "text": "PERFORM STEP-1",
                        "line_start": 2, "line_end": 2,
                        "attributes": {"target": "STEP-1"}, "children": [],
                    }],
                }],
            },
            {
                "name": "STEP-1", "line_start": 11, "line_end": 20,
                "statements": [{
                    "type": "IF", "text": "IF WS-TYPE = 'B'",
                    "line_start": 11, "line_end": 15,
                    "attributes": {"condition": "WS-TYPE = 'B'"},
                    "children": [{
                        "type": "PERFORM", "text": "PERFORM DEEP",
                        "line_start": 12, "line_end": 12,
                        "attributes": {"target": "DEEP"}, "children": [],
                    }],
                }],
            },
            {
                "name": "DEEP", "line_start": 21, "line_end": 25,
                "statements": [],
            },
        ])
        cg = build_static_call_graph(prog)
        gating = extract_gating_conditions(prog, cg)
        pc = compute_path_constraints("DEEP", cg, gating)
        self.assertIsNotNone(pc)
        self.assertEqual(pc.path, ["MAIN", "STEP-1", "DEEP"])
        vars_in_constraints = {gc.variable for gc in pc.constraints}
        self.assertIn("WS-TYPE", vars_in_constraints)

    def test_unreachable_returns_none(self):
        prog = _make_program([
            {"name": "MAIN", "line_start": 1, "line_end": 5, "statements": []},
            {"name": "ORPHAN", "line_start": 6, "line_end": 10, "statements": []},
        ])
        cg = build_static_call_graph(prog)
        gating = extract_gating_conditions(prog, cg)
        self.assertIsNone(compute_path_constraints("ORPHAN", cg, gating))


class TestSequentialGates(unittest.TestCase):

    def test_detect_gate_gauntlet(self):
        """Paragraph with 3+ OPEN→IF patterns should be detected as a gate."""
        prog = _make_program([{
            "name": "1000-INIT", "line_start": 1, "line_end": 30,
            "statements": [
                {"type": "OPEN", "text": "OPEN INPUT FILE-1",
                 "line_start": 1, "line_end": 1,
                 "attributes": {}, "children": []},
                {"type": "IF", "text": "IF FS-FILE1 NOT = '00'",
                 "line_start": 2, "line_end": 4,
                 "attributes": {"condition": "FS-FILE1 NOT = '00'"},
                 "children": [
                     {"type": "GO_TO", "text": "GO TO 9999-EXIT",
                      "line_start": 3, "line_end": 3,
                      "attributes": {"target": "9999-EXIT"}, "children": []},
                 ]},
                {"type": "OPEN", "text": "OPEN INPUT FILE-2",
                 "line_start": 5, "line_end": 5,
                 "attributes": {}, "children": []},
                {"type": "IF", "text": "IF FS-FILE2 NOT = '00'",
                 "line_start": 6, "line_end": 8,
                 "attributes": {"condition": "FS-FILE2 NOT = '00'"},
                 "children": [
                     {"type": "GO_TO", "text": "GO TO 9999-EXIT",
                      "line_start": 7, "line_end": 7,
                      "attributes": {"target": "9999-EXIT"}, "children": []},
                 ]},
                {"type": "OPEN", "text": "OPEN OUTPUT FILE-3",
                 "line_start": 9, "line_end": 9,
                 "attributes": {}, "children": []},
                {"type": "IF", "text": "IF FS-FILE3 NOT = '00'",
                 "line_start": 10, "line_end": 12,
                 "attributes": {"condition": "FS-FILE3 NOT = '00'"},
                 "children": [
                     {"type": "GO_TO", "text": "GO TO 9999-EXIT",
                      "line_start": 11, "line_end": 11,
                      "attributes": {"target": "9999-EXIT"}, "children": []},
                 ]},
                {"type": "PERFORM", "text": "PERFORM 2000-PROCESS",
                 "line_start": 13, "line_end": 13,
                 "attributes": {"target": "2000-PROCESS"}, "children": []},
            ],
        }, {
            "name": "2000-PROCESS", "line_start": 31, "line_end": 35,
            "statements": [],
        }, {
            "name": "9999-EXIT", "line_start": 36, "line_end": 40,
            "statements": [],
        }])

        gates = extract_sequential_gates(prog)
        self.assertEqual(len(gates), 1)
        self.assertEqual(gates[0].paragraph, "1000-INIT")
        self.assertEqual(gates[0].gate_count, 3)
        self.assertEqual(len(gates[0].status_variables), 3)

    def test_no_gate_below_threshold(self):
        """Paragraph with only 2 OPEN→IF patterns should not be detected."""
        prog = _make_program([{
            "name": "INIT", "line_start": 1, "line_end": 10,
            "statements": [
                {"type": "OPEN", "text": "OPEN INPUT FILE-1",
                 "line_start": 1, "line_end": 1,
                 "attributes": {}, "children": []},
                {"type": "IF", "text": "IF FS-FILE1 NOT = '00'",
                 "line_start": 2, "line_end": 3,
                 "attributes": {"condition": "FS-FILE1 NOT = '00'"},
                 "children": []},
                {"type": "OPEN", "text": "OPEN INPUT FILE-2",
                 "line_start": 4, "line_end": 4,
                 "attributes": {}, "children": []},
                {"type": "IF", "text": "IF FS-FILE2 NOT = '00'",
                 "line_start": 5, "line_end": 6,
                 "attributes": {"condition": "FS-FILE2 NOT = '00'"},
                 "children": []},
            ],
        }])
        gates = extract_sequential_gates(prog)
        self.assertEqual(len(gates), 0)

    def test_augment_propagates_to_callees(self):
        """Gate constraints should propagate to paragraphs called from gate paragraph."""
        prog = _make_program([{
            "name": "1000-INIT", "line_start": 1, "line_end": 30,
            "statements": [
                {"type": "OPEN", "text": "OPEN INPUT FILE-1",
                 "line_start": 1, "line_end": 1, "attributes": {}, "children": []},
                {"type": "IF", "text": "IF FS-FILE1 = '00'",
                 "line_start": 2, "line_end": 3,
                 "attributes": {"condition": "FS-FILE1 = '00'"},
                 "children": []},
                {"type": "OPEN", "text": "OPEN INPUT FILE-2",
                 "line_start": 4, "line_end": 4, "attributes": {}, "children": []},
                {"type": "IF", "text": "IF FS-FILE2 = '00'",
                 "line_start": 5, "line_end": 6,
                 "attributes": {"condition": "FS-FILE2 = '00'"},
                 "children": []},
                {"type": "OPEN", "text": "OPEN INPUT FILE-3",
                 "line_start": 7, "line_end": 7, "attributes": {}, "children": []},
                {"type": "IF", "text": "IF FS-FILE3 = '00'",
                 "line_start": 8, "line_end": 9,
                 "attributes": {"condition": "FS-FILE3 = '00'"},
                 "children": []},
                {"type": "PERFORM", "text": "PERFORM 2000-PROCESS",
                 "line_start": 10, "line_end": 10,
                 "attributes": {"target": "2000-PROCESS"}, "children": []},
            ],
        }, {
            "name": "2000-PROCESS", "line_start": 31, "line_end": 35,
            "statements": [],
        }])
        cg = build_static_call_graph(prog)
        gating = extract_gating_conditions(prog, cg)
        gates = extract_sequential_gates(prog)
        augment_gating_with_sequential_gates(gating, gates, cg)

        # 2000-PROCESS should now have gating conditions from the gate
        self.assertIn("2000-PROCESS", gating)
        vars_gated = {gc.variable for gc in gating["2000-PROCESS"]}
        self.assertTrue(vars_gated)


class TestEmptyProgram(unittest.TestCase):

    def test_empty_paragraphs(self):
        prog = _make_program([])
        cg = build_static_call_graph(prog)
        self.assertEqual(cg.entry, "")
        self.assertEqual(cg.reachable, frozenset())
        self.assertEqual(cg.unreachable, frozenset())


if __name__ == "__main__":
    unittest.main()
