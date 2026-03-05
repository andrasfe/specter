"""Tests for stub diversification and stub-status mapping."""

import tempfile
import unittest
from pathlib import Path

from specter.ast_parser import parse_ast
from specter.code_generator import generate_code
from specter.monte_carlo import _generate_stub_outcomes, _STATUS_VALUES
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


class TestApplyStubOutcome(unittest.TestCase):
    """Test that generated code includes _apply_stub_outcome and it works."""

    def test_stub_outcome_sets_variable(self):
        prog = _make_program([{
            "name": "MAIN", "line_start": 1, "line_end": 10,
            "statements": [{
                "type": "EXEC_SQL",
                "text": "EXEC SQL SELECT 1 END-EXEC",
                "line_start": 1, "line_end": 1,
                "attributes": {"raw_text": "SELECT 1"},
                "children": [],
            }],
        }])
        code = generate_code(prog)
        ns = {}
        exec(code, ns)

        # Without stub outcomes - SQLCODE should be default
        result = ns["run"]()
        self.assertIn("_execs", result)

        # With stub outcomes - SQLCODE should be set
        result = ns["run"]({
            "_stub_outcomes": {"SQL": [("SQLCODE", -803)]},
        })
        self.assertEqual(result.get("SQLCODE"), -803)

    def test_stub_outcome_call(self):
        prog = _make_program([{
            "name": "MAIN", "line_start": 1, "line_end": 10,
            "statements": [{
                "type": "CALL",
                "text": "CALL 'MYPROC'",
                "line_start": 1, "line_end": 1,
                "attributes": {"target": "MYPROC"},
                "children": [],
            }],
        }])
        code = generate_code(prog)
        ns = {}
        exec(code, ns)

        result = ns["run"]({
            "_stub_outcomes": {"CALL:MYPROC": [("RETURN-CODE", 8)]},
        })
        self.assertEqual(result.get("RETURN-CODE"), 8)

    def test_stub_outcome_read(self):
        prog = _make_program([{
            "name": "MAIN", "line_start": 1, "line_end": 10,
            "statements": [{
                "type": "READ",
                "text": "READ MY-FILE INTO MY-REC",
                "line_start": 1, "line_end": 1,
                "attributes": {},
                "children": [],
            }],
        }])
        code = generate_code(prog)
        ns = {}
        exec(code, ns)

        result = ns["run"]({
            "_stub_outcomes": {"READ:MY-FILE": [("MY-FILE-STATUS", "10")]},
        })
        self.assertEqual(result.get("MY-FILE-STATUS"), "10")

    def test_stub_outcome_write(self):
        prog = _make_program([{
            "name": "MAIN", "line_start": 1, "line_end": 10,
            "statements": [{
                "type": "WRITE",
                "text": "WRITE MY-REC",
                "line_start": 1, "line_end": 1,
                "attributes": {},
                "children": [],
            }],
        }])
        code = generate_code(prog)
        ns = {}
        exec(code, ns)

        result = ns["run"]({
            "_stub_outcomes": {"WRITE:MY-REC": [("MY-FILE-STATUS", "48")]},
        })
        self.assertEqual(result.get("MY-FILE-STATUS"), "48")

    def test_no_stub_outcomes_backward_compatible(self):
        """Without _stub_outcomes key, nothing changes."""
        prog = _make_program([{
            "name": "MAIN", "line_start": 1, "line_end": 10,
            "statements": [
                {
                    "type": "EXEC_SQL",
                    "text": "EXEC SQL INSERT INTO T END-EXEC",
                    "line_start": 1, "line_end": 1,
                    "attributes": {"raw_text": "INSERT INTO T"},
                    "children": [],
                },
                {
                    "type": "READ",
                    "text": "READ MYFILE",
                    "line_start": 2, "line_end": 2,
                    "attributes": {},
                    "children": [],
                },
            ],
        }])
        code = generate_code(prog)
        ns = {}
        exec(code, ns)
        # Should run without error
        result = ns["run"]()
        self.assertIsInstance(result, dict)

    def test_stub_outcome_open_close(self):
        prog = _make_program([{
            "name": "MAIN", "line_start": 1, "line_end": 10,
            "statements": [
                {
                    "type": "OPEN",
                    "text": "OPEN INPUT MY-FILE",
                    "line_start": 1, "line_end": 1,
                    "attributes": {},
                    "children": [],
                },
                {
                    "type": "CLOSE",
                    "text": "CLOSE MY-FILE",
                    "line_start": 2, "line_end": 2,
                    "attributes": {},
                    "children": [],
                },
            ],
        }])
        code = generate_code(prog)
        ns = {}
        exec(code, ns)

        result = ns["run"]({
            "_stub_outcomes": {
                "OPEN:MY-FILE": [("MY-FILE-STATUS", "35")],
                "CLOSE:MY-FILE": [("MY-FILE-STATUS", "42")],
            },
        })
        # The CLOSE stub outcome should be applied last
        self.assertEqual(result.get("MY-FILE-STATUS"), "42")

    def test_multiple_stub_outcomes_consumed_in_order(self):
        """Multiple EXEC SQL calls consume outcomes in FIFO order."""
        prog = _make_program([{
            "name": "MAIN", "line_start": 1, "line_end": 10,
            "statements": [
                {
                    "type": "EXEC_SQL",
                    "text": "EXEC SQL SELECT 1 END-EXEC",
                    "line_start": 1, "line_end": 1,
                    "attributes": {"raw_text": "SELECT 1"},
                    "children": [],
                },
                {
                    "type": "MOVE", "text": "MOVE SQLCODE TO WS-SAVE1",
                    "line_start": 2, "line_end": 2,
                    "attributes": {"source": "SQLCODE", "targets": "WS-SAVE1"},
                    "children": [],
                },
                {
                    "type": "EXEC_SQL",
                    "text": "EXEC SQL SELECT 2 END-EXEC",
                    "line_start": 3, "line_end": 3,
                    "attributes": {"raw_text": "SELECT 2"},
                    "children": [],
                },
            ],
        }])
        code = generate_code(prog)
        ns = {}
        exec(code, ns)

        result = ns["run"]({
            "_stub_outcomes": {
                "SQL": [("SQLCODE", 0), ("SQLCODE", -803)],
            },
        })
        # First EXEC SQL sets SQLCODE=0, saved to WS-SAVE1
        # Second EXEC SQL sets SQLCODE=-803
        self.assertEqual(result.get("WS-SAVE1"), 0)
        self.assertEqual(result.get("SQLCODE"), -803)


class TestExtractStubStatusMapping(unittest.TestCase):

    def test_sql_to_sqlcode(self):
        prog = _make_program([{
            "name": "MAIN", "line_start": 1, "line_end": 10,
            "statements": [
                {
                    "type": "EXEC_SQL",
                    "text": "EXEC SQL SELECT 1 END-EXEC",
                    "line_start": 1, "line_end": 1,
                    "attributes": {"raw_text": "SELECT 1"},
                    "children": [],
                },
                {
                    "type": "IF",
                    "text": "IF SQLCODE NOT = 0",
                    "line_start": 2, "line_end": 4,
                    "attributes": {"condition": "SQLCODE NOT = 0"},
                    "children": [],
                },
            ],
        }])
        var_report = extract_variables(prog)
        mapping = extract_stub_status_mapping(prog, var_report)
        self.assertIn("SQL", mapping)
        self.assertIn("SQLCODE", mapping["SQL"])

    def test_read_to_file_status(self):
        # Create a variable report with a status var
        var_report = VariableReport()
        var_report.variables["MY-FILE-STATUS"] = VariableInfo(
            name="MY-FILE-STATUS", classification="status",
        )
        prog = _make_program([{
            "name": "MAIN", "line_start": 1, "line_end": 10,
            "statements": [
                {
                    "type": "READ",
                    "text": "READ MY-FILE INTO MY-REC",
                    "line_start": 1, "line_end": 1,
                    "attributes": {},
                    "children": [],
                },
                {
                    "type": "IF",
                    "text": "IF MY-FILE-STATUS NOT = '00'",
                    "line_start": 2, "line_end": 4,
                    "attributes": {"condition": "MY-FILE-STATUS NOT = '00'"},
                    "children": [],
                },
            ],
        }])
        mapping = extract_stub_status_mapping(prog, var_report)
        self.assertIn("READ:MY-FILE", mapping)
        self.assertIn("MY-FILE-STATUS", mapping["READ:MY-FILE"])

    def test_fallback_sql_default(self):
        """When no IF follows EXEC SQL, fallback maps SQL -> SQLCODE."""
        var_report = VariableReport()
        var_report.variables["SQLCODE"] = VariableInfo(
            name="SQLCODE", classification="status",
        )
        prog = _make_program([{
            "name": "MAIN", "line_start": 1, "line_end": 5,
            "statements": [{
                "type": "EXEC_SQL",
                "text": "EXEC SQL INSERT INTO T END-EXEC",
                "line_start": 1, "line_end": 1,
                "attributes": {"raw_text": "INSERT INTO T"},
                "children": [],
            }],
        }])
        mapping = extract_stub_status_mapping(prog, var_report)
        self.assertIn("SQL", mapping)
        self.assertIn("SQLCODE", mapping["SQL"])


class TestGenerateStubOutcomes(unittest.TestCase):

    def test_generates_outcomes_for_mapped_ops(self):
        import random
        stub_mapping = {
            "SQL": ["SQLCODE"],
            "READ:MY-FILE": ["MY-FILE-STATUS"],
        }
        var_report = VariableReport()
        var_report.variables["SQLCODE"] = VariableInfo(
            name="SQLCODE", classification="status",
            condition_literals=[0, -803, 100],
        )
        var_report.variables["MY-FILE-STATUS"] = VariableInfo(
            name="MY-FILE-STATUS", classification="status",
            condition_literals=["00", "10"],
        )
        rng = random.Random(42)
        outcomes = _generate_stub_outcomes(stub_mapping, var_report, rng)

        self.assertIn("SQL", outcomes)
        self.assertIn("READ:MY-FILE", outcomes)
        # Each should have at least one entry (list of (var, val) pairs)
        self.assertTrue(len(outcomes["SQL"]) >= 1)
        # Each entry is a list of (var, val) pairs
        self.assertIsInstance(outcomes["SQL"][0], list)
        self.assertEqual(outcomes["SQL"][0][0][0], "SQLCODE")

    def test_no_mapping_returns_empty(self):
        import random
        rng = random.Random(42)
        outcomes = _generate_stub_outcomes({}, None, rng)
        self.assertEqual(outcomes, {})


if __name__ == "__main__":
    unittest.main()
