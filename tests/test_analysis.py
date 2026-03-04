"""Tests for instrumented code generation and dynamic analysis."""

import unittest

from specter.analysis import AnalysisReport, build_analysis_report
from specter.ast_parser import parse_ast
from specter.code_generator import generate_code
from specter.variable_extractor import extract_variables


class TestInstrumentedCodeGeneration(unittest.TestCase):

    def _make_program(self, paragraphs):
        return parse_ast({
            "program_id": "TEST",
            "paragraphs": paragraphs,
        })

    def _simple_program(self):
        return self._make_program([
            {
                "name": "MAIN-PARA",
                "line_start": 1, "line_end": 10,
                "statements": [
                    {"type": "MOVE", "text": "MOVE 'A' TO X",
                     "line_start": 1, "line_end": 1,
                     "attributes": {"source": "'A'", "targets": "X"},
                     "children": []},
                    {"type": "PERFORM", "text": "PERFORM SUB-PARA",
                     "line_start": 2, "line_end": 2,
                     "attributes": {"target": "SUB-PARA"},
                     "children": []},
                    {"type": "GOBACK", "text": "GOBACK",
                     "line_start": 3, "line_end": 3,
                     "attributes": {}, "children": []},
                ],
            },
            {
                "name": "SUB-PARA",
                "line_start": 11, "line_end": 15,
                "statements": [
                    {"type": "MOVE", "text": "MOVE 'B' TO Y",
                     "line_start": 12, "line_end": 12,
                     "attributes": {"source": "'B'", "targets": "Y"},
                     "children": []},
                ],
            },
            {
                "name": "DEAD-PARA",
                "line_start": 16, "line_end": 20,
                "statements": [
                    {"type": "DISPLAY", "text": "DISPLAY 'NEVER'",
                     "line_start": 17, "line_end": 17,
                     "attributes": {}, "children": []},
                ],
            },
        ])

    def test_instrument_false_no_trace(self):
        prog = self._simple_program()
        code = generate_code(prog, instrument=False)
        ns = {}
        exec(code, ns)
        result = ns["run"]()
        self.assertNotIn("_trace", result)
        self.assertNotIn("_var_writes", result)

    def test_instrument_true_compiles(self):
        prog = self._simple_program()
        code = generate_code(prog, instrument=True)
        compile(code, "<test>", "exec")

    def test_instrument_true_trace(self):
        prog = self._simple_program()
        code = generate_code(prog, instrument=True)
        ns = {}
        exec(code, ns)
        result = ns["run"]()
        self.assertEqual(result["_trace"], ["MAIN-PARA", "SUB-PARA"])

    def test_instrument_var_writes(self):
        prog = self._simple_program()
        code = generate_code(prog, instrument=True)
        ns = {}
        exec(code, ns)
        result = ns["run"]()
        writes = result["_var_writes"]
        write_vars = [w[0] for w in writes]
        self.assertIn("X", write_vars)
        self.assertIn("Y", write_vars)

    def test_instrument_var_reads(self):
        prog = self._make_program([{
            "name": "MAIN-PARA",
            "line_start": 1, "line_end": 5,
            "statements": [
                {"type": "MOVE", "text": "MOVE X TO Y",
                 "line_start": 1, "line_end": 1,
                 "attributes": {"source": "X", "targets": "Y"},
                 "children": []},
            ],
        }])
        code = generate_code(prog, instrument=True)
        ns = {}
        exec(code, ns)
        result = ns["run"]({"X": "hello"})
        read_vars = [r[0] for r in result["_var_reads"]]
        self.assertIn("X", read_vars)

    def test_instrument_state_diffs(self):
        prog = self._make_program([{
            "name": "MAIN-PARA",
            "line_start": 1, "line_end": 5,
            "statements": [
                {"type": "MOVE", "text": "MOVE 99 TO MY-VAR",
                 "line_start": 1, "line_end": 1,
                 "attributes": {"source": "99", "targets": "MY-VAR"},
                 "children": []},
            ],
        }])
        vr = extract_variables(prog)
        code = generate_code(prog, var_report=vr, instrument=True)
        ns = {}
        exec(code, ns)
        result = ns["run"]()
        diffs = result["_state_diffs"]
        self.assertIn("MY-VAR", diffs)
        self.assertEqual(diffs["MY-VAR"]["to"], 99)

    def test_instrument_existing_behavior_unchanged(self):
        prog = self._simple_program()
        code_normal = generate_code(prog, instrument=False)
        code_instr = generate_code(prog, instrument=True)
        ns1, ns2 = {}, {}
        exec(code_normal, ns1)
        exec(code_instr, ns2)
        r1 = ns1["run"]()
        r2 = ns2["run"]()
        self.assertEqual(r1["X"], r2["X"])
        self.assertEqual(r1["Y"], r2["Y"])

    def test_instrument_if_branch(self):
        prog = self._make_program([{
            "name": "MAIN-PARA",
            "line_start": 1, "line_end": 10,
            "statements": [{
                "type": "IF", "text": "IF X = 'Y'",
                "line_start": 1, "line_end": 5,
                "attributes": {"condition": "X = 'Y'"},
                "children": [
                    {"type": "PERFORM", "text": "PERFORM BRANCH-A",
                     "line_start": 2, "line_end": 2,
                     "attributes": {"target": "BRANCH-A"},
                     "children": []},
                    {"type": "ELSE", "text": "ELSE",
                     "line_start": 3, "line_end": 4,
                     "attributes": {},
                     "children": [
                         {"type": "PERFORM", "text": "PERFORM BRANCH-B",
                          "line_start": 4, "line_end": 4,
                          "attributes": {"target": "BRANCH-B"},
                          "children": []},
                     ]},
                ],
            }],
        }, {
            "name": "BRANCH-A",
            "line_start": 11, "line_end": 15,
            "statements": [
                {"type": "MOVE", "text": "MOVE 'A' TO RESULT",
                 "line_start": 12, "line_end": 12,
                 "attributes": {"source": "'A'", "targets": "RESULT"},
                 "children": []},
            ],
        }, {
            "name": "BRANCH-B",
            "line_start": 16, "line_end": 20,
            "statements": [
                {"type": "MOVE", "text": "MOVE 'B' TO RESULT",
                 "line_start": 17, "line_end": 17,
                 "attributes": {"source": "'B'", "targets": "RESULT"},
                 "children": []},
            ],
        }])
        code = generate_code(prog, instrument=True)
        ns = {}
        exec(code, ns)

        r1 = ns["run"]({"X": "Y"})
        self.assertIn("BRANCH-A", r1["_trace"])
        self.assertNotIn("BRANCH-B", r1["_trace"])

        r2 = ns["run"]({"X": "N"})
        self.assertNotIn("BRANCH-A", r2["_trace"])
        self.assertIn("BRANCH-B", r2["_trace"])


class TestBuildAnalysisReport(unittest.TestCase):

    def test_basic_report(self):
        iterations = [
            {
                "trace": ["MAIN", "SUB"],
                "var_writes": [("X", "MAIN"), ("Y", "SUB")],
                "var_reads": [("X", "SUB")],
                "state_diffs": {"X": {"from": "", "to": "A"}},
            },
            {
                "trace": ["MAIN", "SUB"],
                "var_writes": [("X", "MAIN"), ("Y", "SUB")],
                "var_reads": [("X", "SUB")],
                "state_diffs": {"X": {"from": "", "to": "B"}},
            },
        ]
        report = build_analysis_report(iterations, ["MAIN", "SUB", "DEAD"])
        self.assertEqual(report.paragraph_hit_counts["MAIN"], 2)
        self.assertEqual(report.paragraph_hit_counts["SUB"], 2)
        self.assertEqual(report.dead_paragraphs, ["DEAD"])
        self.assertIn("Y", report.dead_writes)
        self.assertNotIn("X", report.dead_writes)
        self.assertEqual(report.n_iterations, 2)

    def test_call_graph(self):
        iterations = [
            {
                "trace": ["A", "B", "C"],
                "var_writes": [], "var_reads": [],
                "state_diffs": {},
            },
        ]
        report = build_analysis_report(iterations, ["A", "B", "C"])
        self.assertIn("B", report.call_graph.get("A", set()))
        self.assertIn("C", report.call_graph.get("B", set()))

    def test_read_only_vars(self):
        iterations = [
            {
                "trace": ["MAIN"],
                "var_writes": [("Y", "MAIN")],
                "var_reads": [("X", "MAIN"), ("Y", "MAIN")],
                "state_diffs": {},
            },
        ]
        report = build_analysis_report(iterations, ["MAIN"])
        self.assertIn("X", report.read_only_vars)
        self.assertNotIn("Y", report.read_only_vars)

    def test_state_diffs_tracking(self):
        iterations = [
            {"trace": [], "var_writes": [], "var_reads": [],
             "state_diffs": {"A": {"from": 0, "to": 1}}},
            {"trace": [], "var_writes": [], "var_reads": [],
             "state_diffs": {"A": {"from": 0, "to": 1}}},
            {"trace": [], "var_writes": [], "var_reads": [],
             "state_diffs": {}},
        ]
        report = build_analysis_report(iterations, [])
        self.assertEqual(report.state_diffs["A"]["changed_in"], 2)

    def test_empty_iterations(self):
        report = build_analysis_report([], ["MAIN"])
        self.assertEqual(report.dead_paragraphs, ["MAIN"])
        self.assertEqual(report.n_iterations, 0)


class TestAnalysisReportSummary(unittest.TestCase):

    def test_summary_format(self):
        report = AnalysisReport(
            paragraph_hit_counts={"MAIN": 10, "SUB": 5},
            dead_paragraphs=["DEAD-PARA"],
            call_graph={"MAIN": {"SUB"}},
            variable_write_counts={"X": 10, "Y": 5},
            variable_read_counts={"X": 8},
            dead_writes=["Y"],
            read_only_vars=["Z"],
            state_diffs={"X": {"changed_in": 10}},
            n_iterations=10,
        )
        text = report.summary()
        self.assertIn("Dynamic Analysis (10 iterations)", text)
        self.assertIn("2/3", text)  # 2 hit / 3 total
        self.assertIn("DEAD-PARA", text)
        self.assertIn("MAIN -> SUB", text)
        self.assertIn("Read-only: Z", text)
        self.assertIn("Dead writes: Y", text)


if __name__ == "__main__":
    unittest.main()
