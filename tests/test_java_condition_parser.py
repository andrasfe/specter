"""Tests for java_condition_parser module."""

import unittest

from specter.java_condition_parser import (
    _rewrite_88_level_conditions_java,
    cobol_condition_to_java,
    resolve_when_value_java,
)
from specter.condition_parser import parse_when_value


class TestRewrite88LevelConditionsJava(unittest.TestCase):
    """The 88-level rewrite mirrors specter.code_generator's Python version."""

    def test_no_map_returns_input_unchanged(self):
        out = cobol_condition_to_java("APPL-AOK")
        self.assertIn('CobolRuntime.isTruthy(state.get("APPL-AOK"))', out)

    def test_numeric_88_level_rewritten_to_to_num_comparison(self):
        m = {"APPL-AOK": ("APPL-RESULT", 0)}
        out = cobol_condition_to_java("APPL-AOK", m)
        self.assertEqual(out, 'CobolRuntime.toNum(state.get("APPL-RESULT")) == 0')

    def test_string_88_level_rewritten_to_objects_equals(self):
        m = {"END-OF-FILE": ("WS-EOF-FLAG", "Y")}
        out = cobol_condition_to_java("END-OF-FILE", m)
        self.assertEqual(out, 'java.util.Objects.equals(state.get("WS-EOF-FLAG"), "Y")')

    def test_negation_of_88_level(self):
        m = {"APPL-AOK": ("APPL-RESULT", 0)}
        out = cobol_condition_to_java("NOT APPL-AOK", m)
        # NOT wraps via the Java parser; the rewrite still fires inside.
        self.assertIn('CobolRuntime.toNum(state.get("APPL-RESULT")) == 0', out)
        self.assertIn("!", out)

    def test_compound_condition_with_88_level(self):
        m = {"APPL-AOK": ("APPL-RESULT", 0)}
        out = cobol_condition_to_java("APPL-AOK AND WS-X = 1", m)
        self.assertIn('CobolRuntime.toNum(state.get("APPL-RESULT")) == 0', out)
        # AND collapses to Java &&; the comparator side is left alone.
        self.assertIn("&&", out)
        self.assertIn('state.get("WS-X")', out)

    def test_explicit_comparison_on_88_var_not_rewritten(self):
        # A user writing ``IF APPL-AOK = SOMETHING`` has already disambiguated.
        m = {"APPL-AOK": ("APPL-RESULT", 0)}
        out = cobol_condition_to_java('APPL-AOK = "Y"', m)
        # The literal compare on APPL-AOK should not be rewritten to APPL-RESULT.
        self.assertIn('"APPL-AOK"', out)
        self.assertNotIn("APPL-RESULT", out)

    def test_unknown_identifier_left_alone(self):
        m = {"APPL-AOK": ("APPL-RESULT", 0)}
        out = cobol_condition_to_java("OTHER-FLAG", m)
        self.assertIn('CobolRuntime.isTruthy(state.get("OTHER-FLAG"))', out)
        self.assertNotIn("APPL-RESULT", out)

    def test_direct_helper_call_applied_to_raw_isTruthy(self):
        # Sanity: the helper itself works on a hand-built input.
        out = _rewrite_88_level_conditions_java(
            'CobolRuntime.isTruthy(state.get("APPL-AOK"))',
            {"APPL-AOK": ("APPL-RESULT", 0)},
        )
        self.assertEqual(out, 'CobolRuntime.toNum(state.get("APPL-RESULT")) == 0')

    def test_resolve_when_value_threads_map_for_evaluate_true(self):
        m = {"APPL-AOK": ("APPL-RESULT", 0)}
        out = resolve_when_value_java("APPL-AOK", is_evaluate_true=True, level_88_map=m)
        self.assertEqual(out, 'CobolRuntime.toNum(state.get("APPL-RESULT")) == 0')


class TestNumericLiteralComparisonCoercion(unittest.TestCase):
    """A numeric literal on either side of = / NOT = forces toNum() coercion
    on the variable side. Otherwise Objects.equals("0", 0) returns false."""

    def test_var_eq_zero_coerces_via_toNum(self):
        out = cobol_condition_to_java("WS-X = 0")
        self.assertEqual(out, 'CobolRuntime.toNum(state.get("WS-X")) == 0')

    def test_var_eq_nonzero_int(self):
        out = cobol_condition_to_java("WS-X = 16")
        self.assertEqual(out, 'CobolRuntime.toNum(state.get("WS-X")) == 16')

    def test_zero_eq_var_other_side_too(self):
        out = cobol_condition_to_java("0 = WS-X")
        self.assertEqual(out, '0 == CobolRuntime.toNum(state.get("WS-X"))')

    def test_var_neq_numeric_literal(self):
        out = cobol_condition_to_java("WS-X NOT = 0")
        self.assertEqual(out, 'CobolRuntime.toNum(state.get("WS-X")) != 0')

    def test_string_literal_still_uses_objects_equals(self):
        out = cobol_condition_to_java("WS-STATUS = '00'")
        self.assertIn("Objects.equals", out)
        self.assertNotIn("toNum", out)

    def test_two_literal_numerics_unchanged(self):
        out = cobol_condition_to_java("0 = 0")
        self.assertEqual(out, "0 == 0")


class TestJavaConditionParser(unittest.TestCase):
    """Tests that parallel test_condition_parser.py but verify Java output."""

    # -- Simple equality ---------------------------------------------------

    def test_simple_equality(self):
        result = cobol_condition_to_java("X = 'Y'")
        self.assertIn('state.get("X")', result)
        self.assertIn('"Y"', result)
        self.assertIn("java.util.Objects.equals", result)
        self.assertNotIn("!=", result)

    def test_simple_equality_numeric(self):
        # State variables compared to a numeric literal must coerce via
        # CobolRuntime.toNum so "0"/"00"/0 all match. Objects.equals would
        # return false for the string-vs-int case.
        result = cobol_condition_to_java("X = 5")
        self.assertEqual(result, 'CobolRuntime.toNum(state.get("X")) == 5')

    # -- Figurative constants ---------------------------------------------

    def test_figurative_spaces(self):
        result = cobol_condition_to_java("WS-STATUS = SPACES")
        self.assertIn('state.get("WS-STATUS")', result)
        self.assertIn('" "', result)
        self.assertIn("java.util.Objects.equals", result)

    def test_figurative_zeros(self):
        result = cobol_condition_to_java("SQLCODE = ZERO")
        self.assertIn('state.get("SQLCODE")', result)
        self.assertIn("0", result)

    def test_figurative_low_values(self):
        result = cobol_condition_to_java("X = LOW-VALUES")
        self.assertIn('"\\u0000"', result)

    def test_figurative_high_values(self):
        result = cobol_condition_to_java("X = HIGH-VALUES")
        self.assertIn('"\\u00FF"', result)

    # -- Multi-value OR ---------------------------------------------------

    def test_multi_value_or(self):
        result = cobol_condition_to_java("WS-INFIL1-STATUS = SPACES OR '00'")
        self.assertIn("java.util.List.of", result)
        self.assertIn(".contains(", result)
        self.assertIn('" "', result)
        self.assertIn('"00"', result)

    def test_multi_value_three(self):
        result = cobol_condition_to_java(
            "P-CHKP-FREQ = SPACES OR 0 OR LOW-VALUES"
        )
        self.assertIn("java.util.List.of", result)
        self.assertIn(".contains(", result)

    # -- NOT EQUAL --------------------------------------------------------

    def test_not_equal(self):
        result = cobol_condition_to_java("P-DEBUG-FLAG NOT = 'Y'")
        self.assertIn("!", result)
        self.assertIn("java.util.Objects.equals", result)
        self.assertIn('"Y"', result)

    def test_not_equal_to_multi(self):
        result = cobol_condition_to_java(
            "PAUT-PCB-STATUS NOT EQUAL TO SPACES AND 'II'"
        )
        self.assertIn("!java.util.List.of", result)
        self.assertIn('" "', result)
        self.assertIn('"II"', result)
        self.assertIn(".contains(", result)

    # -- IS NUMERIC / IS NOT NUMERIC --------------------------------------

    def test_is_numeric(self):
        result = cobol_condition_to_java("P-EXPIRY-DAYS IS NUMERIC")
        self.assertIn("CobolRuntime.isNumeric", result)
        self.assertNotIn("!", result)

    def test_is_not_numeric(self):
        result = cobol_condition_to_java("X IS NOT NUMERIC")
        self.assertIn("!", result)
        self.assertIn("CobolRuntime.isNumeric", result)

    # -- Bare flag (truthiness) -------------------------------------------

    def test_bare_flag(self):
        result = cobol_condition_to_java("ERR-FLG-ON")
        self.assertEqual(result, 'CobolRuntime.isTruthy(state.get("ERR-FLG-ON"))')

    def test_not_bare_flag(self):
        """NOT FLAG should negate the truthiness check."""
        result = cobol_condition_to_java("NOT ERR-FLG-ON")
        self.assertIn("!", result)
        self.assertIn("CobolRuntime.isTruthy", result)

    # -- Logical OR -------------------------------------------------------

    def test_logical_or(self):
        result = cobol_condition_to_java("ERR-FLG-ON OR END-OF-AUTHDB")
        self.assertIn("||", result)
        self.assertIn('state.get("ERR-FLG-ON")', result)
        self.assertIn('state.get("END-OF-AUTHDB")', result)

    # -- Comparison operators ---------------------------------------------

    def test_comparison_greater(self):
        result = cobol_condition_to_java(
            "WS-AUTH-SMRY-PROC-CNT > P-CHKP-FREQ"
        )
        self.assertIn(">", result)
        self.assertIn("CobolRuntime.toNum", result)

    def test_comparison_less_equal(self):
        result = cobol_condition_to_java("PA-APPROVED-AUTH-CNT <= 0")
        self.assertIn("<=", result)
        self.assertIn("0", result)
        self.assertIn("CobolRuntime.toNum", result)

    def test_comparison_greater_than_word(self):
        result = cobol_condition_to_java("X GREATER THAN Y")
        self.assertIn(">", result)
        self.assertIn("CobolRuntime.toNum", result)

    def test_comparison_less_than_word(self):
        result = cobol_condition_to_java("X LESS THAN Y")
        self.assertIn("<", result)
        self.assertIn("CobolRuntime.toNum", result)

    def test_comparison_greater_than_or_equal(self):
        result = cobol_condition_to_java("X GREATER THAN OR EQUAL TO Y")
        self.assertIn(">=", result)
        self.assertIn("CobolRuntime.toNum", result)

    def test_comparison_less_than_or_equal(self):
        result = cobol_condition_to_java("X LESS THAN OR EQUAL TO Y")
        self.assertIn("<=", result)
        self.assertIn("CobolRuntime.toNum", result)

    # -- UNTIL prefix -----------------------------------------------------

    def test_until_prefix(self):
        result = cobol_condition_to_java("UNTIL END-ROOT-SEG-FILE = 'Y'")
        self.assertIn('state.get("END-ROOT-SEG-FILE")', result)
        self.assertIn('"Y"', result)
        self.assertNotIn("UNTIL", result)

    # -- Negative number --------------------------------------------------

    def test_negative_number(self):
        result = cobol_condition_to_java("SQLCODE = -803")
        self.assertIn("-803", result)

    # -- Empty condition --------------------------------------------------

    def test_empty_condition(self):
        result = cobol_condition_to_java("")
        self.assertEqual(result, "true")

    # -- Compound AND -----------------------------------------------------

    def test_compound_and(self):
        result = cobol_condition_to_java(
            "PA-APPROVED-AUTH-CNT <= 0 AND PA-APPROVED-AUTH-CNT <= 0"
        )
        self.assertIn("&&", result)

    # -- DFHRESP ----------------------------------------------------------

    def test_dfhresp_normal(self):
        result = cobol_condition_to_java("EIBRESP = DFHRESP(NORMAL)")
        self.assertIn("0", result)

    def test_dfhresp_notfnd(self):
        result = cobol_condition_to_java("EIBRESP = DFHRESP(NOTFND)")
        self.assertIn("13", result)

    # -- CICS AID keys ----------------------------------------------------

    def test_cics_aid_key(self):
        result = cobol_condition_to_java("EIBAID = DFHENTER")
        self.assertIn('"DFHENTER"', result)

    # -- Implied subject AND NOT = val ------------------------------------

    def test_implied_subject_and_not_equal(self):
        result = cobol_condition_to_java(
            "FILE-STATUS NOT = '00' AND NOT = '04' AND NOT = '05'"
        )
        self.assertEqual(result.count('state.get("FILE-STATUS")'), 3)
        self.assertEqual(result.count("java.util.Objects.equals"), 3)
        self.assertEqual(result.count("!java.util.Objects.equals"), 3)
        self.assertNotIn("true", result)

    def test_implied_subject_and_equal(self):
        result = cobol_condition_to_java("SQLCODE NOT = 0 AND NOT = 100")
        self.assertEqual(result.count('state.get("SQLCODE")'), 2)

    # -- Implied subject OR = val -----------------------------------------

    def test_implied_subject_or_equal(self):
        result = cobol_condition_to_java(
            "FILE-STATUS = '00' OR = '04'"
        )
        self.assertEqual(result.count('state.get("FILE-STATUS")'), 2)
        self.assertIn("||", result)

    # -- AND with different subject (should NOT use implied subject) -------

    def test_and_with_different_subject(self):
        result = cobol_condition_to_java(
            "WS-FLAG NOT EQUAL 'Y' AND WS-OTHER = 'X'"
        )
        self.assertIn('state.get("WS-FLAG")', result)
        self.assertIn('state.get("WS-OTHER")', result)
        self.assertIn('"Y"', result)
        self.assertIn('"X"', result)

    # -- String quoting ---------------------------------------------------

    def test_double_quotes_in_output(self):
        """Java output should use double quotes, not single quotes."""
        result = cobol_condition_to_java("X = 'HELLO'")
        self.assertNotIn("'HELLO'", result)
        self.assertIn('"HELLO"', result)

    # -- Variable-to-variable equality ------------------------------------

    def test_var_to_var_equality(self):
        result = cobol_condition_to_java("A = B")
        self.assertIn("java.util.Objects.equals", result)
        self.assertIn('state.get("A")', result)
        self.assertIn('state.get("B")', result)

    def test_var_to_var_inequality(self):
        result = cobol_condition_to_java("A NOT = B")
        self.assertIn("!java.util.Objects.equals", result)
        self.assertIn('state.get("A")', result)
        self.assertIn('state.get("B")', result)

    def test_var_to_var_numeric_comparison(self):
        result = cobol_condition_to_java("A > B")
        self.assertIn("CobolRuntime.toNum", result)
        self.assertEqual(result.count("CobolRuntime.toNum"), 2)

    # -- IS NOT EQUAL / IS NOT GREATER ------------------------------------

    def test_is_not_equal(self):
        result = cobol_condition_to_java("X IS NOT EQUAL TO 'Y'")
        self.assertIn("!java.util.Objects.equals", result)
        self.assertIn('"Y"', result)

    def test_is_not_greater(self):
        result = cobol_condition_to_java("X IS NOT GREATER THAN 5")
        self.assertIn("<=", result)
        self.assertIn("CobolRuntime.toNum", result)

    # -- Java boolean literals --------------------------------------------

    def test_true_false_literals(self):
        """Java output should use lowercase true/false, not Python True/False."""
        empty = cobol_condition_to_java("")
        self.assertEqual(empty, "true")
        self.assertNotEqual(empty, "True")

    # -- Complex combinations ---------------------------------------------

    def test_complex_and_or(self):
        result = cobol_condition_to_java("A = '1' AND B = '2' OR C = '3'")
        self.assertIn("&&", result)
        self.assertIn("||", result)

    def test_not_with_comparison(self):
        result = cobol_condition_to_java("NOT A = 'X'")
        # NOT before a comparison should still work
        self.assertIn('state.get("A")', result)

    # -- Numeric literal equality -----------------------------------------

    def test_numeric_literal_equality(self):
        """A var compared to a numeric literal coerces both sides via
        CobolRuntime.toNum (was incorrectly Objects.equals before)."""
        result = cobol_condition_to_java("SQLCODE = 0")
        self.assertEqual(result, 'CobolRuntime.toNum(state.get("SQLCODE")) == 0')


class TestParseWhenValueJava(unittest.TestCase):
    """Test parse_when_value (reused from condition_parser) with Java resolver."""

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


class TestResolveWhenValueJava(unittest.TestCase):

    def test_literal_value(self):
        result = resolve_when_value_java("'S'", is_evaluate_true=False)
        self.assertEqual(result, '"S"')

    def test_variable_value(self):
        """DFHENTER is a CICS AID key, resolved as a string constant."""
        result = resolve_when_value_java("DFHENTER", is_evaluate_true=False)
        self.assertEqual(result, '"DFHENTER"')

    def test_condition_for_true(self):
        result = resolve_when_value_java(
            "SEL0001I OF COPAU0AI NOT = SPACES AND LOW-VALUES",
            is_evaluate_true=True,
        )
        self.assertIn("state.get(", result)

    def test_numeric_literal_when(self):
        result = resolve_when_value_java("42", is_evaluate_true=False)
        self.assertEqual(result, "42")

    def test_figurative_when(self):
        result = resolve_when_value_java("SPACES", is_evaluate_true=False)
        self.assertEqual(result, '" "')

    def test_condition_when_true_equality(self):
        result = resolve_when_value_java("X = 'Y'", is_evaluate_true=True)
        self.assertIn("java.util.Objects.equals", result)
        self.assertIn('"Y"', result)


class TestJavaOutputFormat(unittest.TestCase):
    """Verify general properties of the Java output format."""

    def test_no_python_and_or_not(self):
        """Output should never contain Python's 'and', 'or', 'not' keywords."""
        cases = [
            "A = '1' AND B = '2'",
            "A = '1' OR B = '2'",
            "NOT A = '1'",
            "A NOT = '1'",
        ]
        for cond in cases:
            result = cobol_condition_to_java(cond)
            # Check word boundaries to avoid false matches in identifiers
            # e.g. "standard" contains "and" but that's fine
            tokens = result.split()
            self.assertNotIn("and", tokens,
                             f"Python 'and' in Java output for: {cond}")
            self.assertNotIn("or", tokens,
                             f"Python 'or' in Java output for: {cond}")
            # 'not' as a standalone token shouldn't appear
            self.assertNotIn("not", tokens,
                             f"Python 'not' in Java output for: {cond}")

    def test_no_single_quotes_for_strings(self):
        """Java string literals should use double quotes."""
        cases = [
            "X = 'HELLO'",
            "X = SPACES",
            "X = DFHENTER",
            "WS-STATUS = '00'",
        ]
        for cond in cases:
            result = cobol_condition_to_java(cond)
            # The result should not contain single-quoted strings
            # (but may contain single quotes inside java identifiers)
            import re
            single_quoted = re.findall(r"'[^']*'", result)
            self.assertEqual(single_quoted, [],
                             f"Single-quoted string in Java output for: {cond} -> {result}")

    def test_state_access_uses_double_quotes(self):
        """state.get() calls should use double-quoted keys."""
        result = cobol_condition_to_java("MY-VAR = '1'")
        self.assertIn('state.get("MY-VAR")', result)
        self.assertNotIn("state['", result)
        self.assertNotIn("state.get('", result)

    def test_no_python_in_keyword(self):
        """Multi-value should not use Python 'in' syntax."""
        result = cobol_condition_to_java("X = 'A' OR 'B'")
        self.assertNotIn(" in (", result)
        self.assertIn("java.util.List.of", result)

    def test_no_python_not_in_keyword(self):
        """Negated multi-value should not use Python 'not in' syntax."""
        result = cobol_condition_to_java("X NOT = 'A' OR 'B'")
        self.assertNotIn("not in", result)
        self.assertIn("!java.util.List.of", result)


if __name__ == "__main__":
    unittest.main()
