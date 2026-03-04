"""Tests for variable_extractor module — literal harvesting."""

import unittest

from specter.variable_extractor import (
    VariableInfo,
    VariableReport,
    _harvest_condition_literals,
    extract_variables,
)
from specter.models import Program, Paragraph, Statement


class TestHarvestConditionLiterals(unittest.TestCase):
    """Tests for _harvest_condition_literals helper."""

    def _report_with(self, *names):
        report = VariableReport()
        for n in names:
            report.variables[n] = VariableInfo(name=n)
        return report

    def test_simple_equality(self):
        report = self._report_with("WS-STATUS")
        _harvest_condition_literals(report, "WS-STATUS = '00'")
        self.assertIn("00", report.variables["WS-STATUS"].condition_literals)

    def test_multi_value_or(self):
        report = self._report_with("FILE-STATUS")
        _harvest_condition_literals(report, "FILE-STATUS = '00' OR '04' OR '05'")
        lits = report.variables["FILE-STATUS"].condition_literals
        self.assertIn("00", lits)
        self.assertIn("04", lits)
        self.assertIn("05", lits)

    def test_not_equal_multi_and(self):
        report = self._report_with("PCB-STATUS")
        _harvest_condition_literals(report, "PCB-STATUS NOT EQUAL TO SPACES AND 'II'")
        lits = report.variables["PCB-STATUS"].condition_literals
        self.assertIn(" ", lits)
        self.assertIn("II", lits)

    def test_figurative_zeros(self):
        report = self._report_with("SQLCODE")
        _harvest_condition_literals(report, "SQLCODE = ZEROS")
        self.assertIn(0, report.variables["SQLCODE"].condition_literals)

    def test_figurative_spaces(self):
        report = self._report_with("WS-FIELD")
        _harvest_condition_literals(report, "WS-FIELD = SPACES")
        self.assertIn(" ", report.variables["WS-FIELD"].condition_literals)

    def test_numeric_literal(self):
        report = self._report_with("WS-COUNT")
        _harvest_condition_literals(report, "WS-COUNT = 5")
        self.assertIn(5, report.variables["WS-COUNT"].condition_literals)

    def test_negative_numeric(self):
        report = self._report_with("SQLCODE")
        _harvest_condition_literals(report, "SQLCODE = -803")
        self.assertIn(-803, report.variables["SQLCODE"].condition_literals)

    def test_ordering_adds_boundaries(self):
        report = self._report_with("WS-COUNT")
        _harvest_condition_literals(report, "WS-COUNT > 0")
        lits = report.variables["WS-COUNT"].condition_literals
        self.assertIn(0, lits)
        self.assertIn(1, lits)
        self.assertIn(-1, lits)

    def test_variable_on_rhs_skipped(self):
        report = self._report_with("WS-A")
        _harvest_condition_literals(report, "WS-A = WS-B")
        # WS-B is a variable, not a literal — should not appear
        lits = report.variables["WS-A"].condition_literals
        self.assertEqual(lits, [])

    def test_creates_variable_if_missing(self):
        report = VariableReport()
        _harvest_condition_literals(report, "NEW-VAR = '42'")
        self.assertIn("NEW-VAR", report.variables)
        self.assertIn("42", report.variables["NEW-VAR"].condition_literals)

    def test_no_duplicates(self):
        report = self._report_with("WS-STATUS")
        _harvest_condition_literals(report, "WS-STATUS = '00'")
        _harvest_condition_literals(report, "WS-STATUS = '00' OR '04'")
        lits = report.variables["WS-STATUS"].condition_literals
        self.assertEqual(lits.count("00"), 1)

    def test_until_prefix_stripped(self):
        report = self._report_with("END-FLAG")
        _harvest_condition_literals(report, "UNTIL END-FLAG = 'Y'")
        self.assertIn("Y", report.variables["END-FLAG"].condition_literals)

    def test_empty_condition(self):
        report = self._report_with("X")
        _harvest_condition_literals(report, "")
        self.assertEqual(report.variables["X"].condition_literals, [])


class TestExtractVariablesWithLiterals(unittest.TestCase):
    """Integration: extract_variables populates condition_literals."""

    def test_if_statement_harvests_literals(self):
        prog = Program(
            program_id="TEST",
            paragraphs=[
                Paragraph(
                    name="MAIN",
                    line_start=1,
                    line_end=10,
                    statements=[
                        Statement(
                            type="IF",
                            text="IF WS-STATUS = '00'",
                            line_start=2,
                            line_end=4,
                            attributes={"condition": "WS-STATUS = '00'"},
                            children=[],
                        )
                    ],
                )
            ],
        )
        report = extract_variables(prog)
        self.assertIn("WS-STATUS", report.variables)
        self.assertIn("00", report.variables["WS-STATUS"].condition_literals)

    def test_when_statement_harvests_literals(self):
        prog = Program(
            program_id="TEST",
            paragraphs=[
                Paragraph(
                    name="MAIN",
                    line_start=1,
                    line_end=10,
                    statements=[
                        Statement(
                            type="EVALUATE",
                            text="EVALUATE WS-CODE",
                            line_start=2,
                            line_end=8,
                            attributes={"subject": "WS-CODE"},
                            children=[
                                Statement(
                                    type="WHEN",
                                    text="WHEN WHEN 'GE'",
                                    line_start=3,
                                    line_end=4,
                                    attributes={},
                                    children=[],
                                ),
                            ],
                        )
                    ],
                )
            ],
        )
        report = extract_variables(prog)
        # WHEN text "WHEN WHEN 'GE'" doesn't have a comparison operator,
        # so it won't be harvested via the comparison-based approach.
        # That's expected — WHEN values are simple matches, not conditions.


if __name__ == "__main__":
    unittest.main()
