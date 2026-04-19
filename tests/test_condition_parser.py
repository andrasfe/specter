"""Tests for condition_parser module."""

import unittest

from specter.condition_parser import (
    cobol_condition_to_python,
    parse_when_value,
    resolve_when_value,
)


class TestConditionParser(unittest.TestCase):

    def test_simple_equality(self):
        result = cobol_condition_to_python("X = 'Y'")
        self.assertIn("state['X']", result)
        self.assertIn("==", result)
        self.assertIn("'Y'", result)

    def test_figurative_spaces(self):
        result = cobol_condition_to_python("WS-STATUS = SPACES")
        self.assertIn("state['WS-STATUS']", result)
        self.assertIn("' '", result)

    def test_figurative_zeros(self):
        result = cobol_condition_to_python("SQLCODE = ZERO")
        self.assertIn("state['SQLCODE']", result)
        self.assertIn("0", result)

    def test_figurative_low_values(self):
        result = cobol_condition_to_python("X = LOW-VALUES")
        self.assertIn("''", result)

    def test_multi_value_or(self):
        result = cobol_condition_to_python("WS-INFIL1-STATUS = SPACES OR '00'")
        self.assertIn("in", result)
        self.assertIn("' '", result)
        self.assertIn("'00'", result)

    def test_not_equal(self):
        result = cobol_condition_to_python("P-DEBUG-FLAG NOT = 'Y'")
        self.assertIn("!=", result)
        self.assertIn("'Y'", result)

    def test_not_equal_to_multi(self):
        result = cobol_condition_to_python("PAUT-PCB-STATUS NOT EQUAL TO SPACES AND 'II'")
        self.assertIn("not in", result)
        self.assertIn("' '", result)
        self.assertIn("'II'", result)

    def test_is_numeric(self):
        result = cobol_condition_to_python("P-EXPIRY-DAYS IS NUMERIC")
        self.assertIn("_is_numeric", result)

    def test_is_not_numeric(self):
        result = cobol_condition_to_python("X IS NOT NUMERIC")
        self.assertIn("not", result)
        self.assertIn("_is_numeric", result)

    def test_bare_flag(self):
        result = cobol_condition_to_python("ERR-FLG-ON")
        self.assertEqual(result, "state['ERR-FLG-ON']")

    def test_logical_or(self):
        result = cobol_condition_to_python("ERR-FLG-ON OR END-OF-AUTHDB")
        self.assertIn("or", result)
        self.assertIn("state['ERR-FLG-ON']", result)
        self.assertIn("state['END-OF-AUTHDB']", result)

    def test_comparison_greater(self):
        result = cobol_condition_to_python("WS-AUTH-SMRY-PROC-CNT > P-CHKP-FREQ")
        self.assertIn(">", result)

    def test_comparison_less_equal(self):
        result = cobol_condition_to_python("PA-APPROVED-AUTH-CNT <= 0")
        self.assertIn("<=", result)
        self.assertIn("0", result)

    def test_until_prefix(self):
        result = cobol_condition_to_python("UNTIL END-ROOT-SEG-FILE = 'Y'")
        self.assertIn("state['END-ROOT-SEG-FILE']", result)
        self.assertIn("==", result)
        self.assertIn("'Y'", result)
        self.assertNotIn("UNTIL", result)

    def test_multi_value_with_figurative(self):
        result = cobol_condition_to_python("P-CHKP-FREQ = SPACES OR 0 OR LOW-VALUES")
        self.assertIn("in", result)

    def test_negative_number(self):
        result = cobol_condition_to_python("SQLCODE = -803")
        self.assertIn("-803", result)

    def test_empty_condition(self):
        result = cobol_condition_to_python("")
        self.assertEqual(result, "True")

    def test_compound_and(self):
        result = cobol_condition_to_python(
            "PA-APPROVED-AUTH-CNT <= 0 AND PA-APPROVED-AUTH-CNT <= 0"
        )
        self.assertIn("and", result)


class TestParseWhenValue(unittest.TestCase):

    def test_when_other(self):
        val, is_other = parse_when_value("WHEN OTHER")
        self.assertTrue(is_other)

    def test_when_double_when(self):
        val, is_other = parse_when_value("WHEN WHEN DFHENTER")
        self.assertFalse(is_other)
        self.assertEqual(val, "DFHENTER")

    def test_when_quoted(self):
        val, is_other = parse_when_value("WHEN WHEN 'S'")
        self.assertFalse(is_other)
        self.assertEqual(val, "'S'")


class TestResolveWhenValue(unittest.TestCase):

    def test_literal_value(self):
        result = resolve_when_value("'S'", is_evaluate_true=False)
        self.assertEqual(result, "'S'")

    def test_variable_value(self):
        # DFH* AID names resolve to their byte value so Python
        # comparisons match COBOL's byte-level EVALUATE WHEN dispatch.
        # DFHENTER → X'7D' → '}' (byte 0x7D in ASCII).
        result = resolve_when_value("DFHENTER", is_evaluate_true=False)
        self.assertEqual(result, "'}'")

    def test_condition_for_true(self):
        result = resolve_when_value(
            "SEL0001I OF COPAU0AI NOT = SPACES AND LOW-VALUES",
            is_evaluate_true=True,
        )
        self.assertIn("state[", result)

    def test_implied_subject_and_not_equal(self):
        """AND NOT = val should use the subject from the first comparison."""
        result = cobol_condition_to_python(
            "FILE-STATUS NOT = '00' AND NOT = '04' AND NOT = '05'"
        )
        # Should produce three != checks against the same subject
        self.assertEqual(result.count("state['FILE-STATUS']"), 3)
        self.assertIn("!= '00'", result)
        self.assertIn("!= '04'", result)
        self.assertIn("!= '05'", result)
        self.assertNotIn("True", result)

    def test_implied_subject_and_equal(self):
        """AND = val should use the subject from the first comparison."""
        result = cobol_condition_to_python(
            "SQLCODE NOT = 0 AND NOT = 100"
        )
        self.assertEqual(result.count("state['SQLCODE']"), 2)
        self.assertIn("!= 0", result)
        self.assertIn("!= 100", result)

    def test_and_with_different_subject(self):
        """AND with a full comparison should NOT use implied subject."""
        result = cobol_condition_to_python(
            "WS-FLAG NOT EQUAL 'Y' AND WS-OTHER = 'X'"
        )
        self.assertIn("state['WS-FLAG']", result)
        self.assertIn("state['WS-OTHER']", result)
        self.assertIn("!= 'Y'", result)
        self.assertIn("== 'X'", result)


if __name__ == "__main__":
    unittest.main()
