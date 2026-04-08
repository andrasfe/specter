"""Tests for the scribe / challenger validation module."""

import os
import unittest
from unittest.mock import patch

from specter.llm_review import (
    ReviewVerdict,
    parse_review_response,
    review_enabled,
    review_fix,
)


class TestParseReviewResponse(unittest.TestCase):
    """Tests for parse_review_response — must tolerate noisy LLM output."""

    def test_clean_accept(self):
        v = parse_review_response('{"verdict": "accept", "reason": "looks fine", "severity": "high"}')
        self.assertEqual(v.verdict, "accept")
        self.assertTrue(v.accepted)
        self.assertEqual(v.reason, "looks fine")
        self.assertEqual(v.severity, "high")

    def test_clean_reject(self):
        v = parse_review_response(
            '{"verdict": "reject", "reason": "comments out a referenced line", "severity": "high"}'
        )
        self.assertEqual(v.verdict, "reject")
        self.assertFalse(v.accepted)
        self.assertEqual(v.reason, "comments out a referenced line")

    def test_markdown_fenced_response(self):
        # Some models wrap JSON in ```json ... ``` even when told not to.
        v = parse_review_response(
            '```json\n{"verdict": "accept", "reason": "ok", "severity": "low"}\n```'
        )
        self.assertEqual(v.verdict, "accept")
        self.assertEqual(v.severity, "low")

    def test_response_with_leading_whitespace(self):
        v = parse_review_response('   {"verdict": "reject", "reason": "x"}   ')
        self.assertEqual(v.verdict, "reject")

    def test_severity_defaults_to_high_when_missing(self):
        v = parse_review_response('{"verdict": "reject", "reason": "x"}')
        self.assertEqual(v.severity, "high")

    def test_invalid_severity_normalised(self):
        v = parse_review_response('{"verdict": "reject", "reason": "x", "severity": "critical"}')
        self.assertEqual(v.severity, "high")

    def test_invalid_verdict_returns_unknown(self):
        v = parse_review_response('{"verdict": "maybe", "reason": "x"}')
        self.assertEqual(v.verdict, "unknown")

    def test_empty_response_returns_unknown(self):
        v = parse_review_response("")
        self.assertEqual(v.verdict, "unknown")
        self.assertEqual(v.severity, "low")

    def test_malformed_json_falls_back_to_regex(self):
        # Stray text + missing closing brace, but verdict is still extractable.
        noisy = 'Sure! Here is the verdict: {"verdict": "reject", "reason": "renames undefined symbol"'
        v = parse_review_response(noisy)
        self.assertEqual(v.verdict, "reject")
        self.assertIn("renames", v.reason)

    def test_garbage_returns_unknown(self):
        v = parse_review_response("not even close to JSON")
        self.assertEqual(v.verdict, "unknown")


class TestReviewEnabled(unittest.TestCase):
    """Tests for the SPECTER_LLM_REVIEW kill switch."""

    def test_default_enabled(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SPECTER_LLM_REVIEW", None)
            self.assertTrue(review_enabled())

    def test_disabled_by_zero(self):
        with patch.dict(os.environ, {"SPECTER_LLM_REVIEW": "0"}):
            self.assertFalse(review_enabled())

    def test_disabled_by_false(self):
        with patch.dict(os.environ, {"SPECTER_LLM_REVIEW": "false"}):
            self.assertFalse(review_enabled())

    def test_disabled_by_off(self):
        with patch.dict(os.environ, {"SPECTER_LLM_REVIEW": "off"}):
            self.assertFalse(review_enabled())

    def test_enabled_by_one(self):
        with patch.dict(os.environ, {"SPECTER_LLM_REVIEW": "1"}):
            self.assertTrue(review_enabled())

    def test_enabled_by_anything_else(self):
        with patch.dict(os.environ, {"SPECTER_LLM_REVIEW": "yes"}):
            self.assertTrue(review_enabled())


class TestReviewFix(unittest.TestCase):
    """Tests for review_fix — the public entry point.

    review_fix MUST never raise — on any failure path it returns a
    ReviewVerdict('unknown', ...) so the caller can pass through.
    """

    def _src(self) -> list[str]:
        return [
            "       IDENTIFICATION DIVISION.\n",
            "       PROGRAM-ID. TEST.\n",
            "       DATA DIVISION.\n",
            "       WORKING-STORAGE SECTION.\n",
            "       01 WS-FOO PIC X(10).\n",
            "       PROCEDURE DIVISION.\n",
            "       MAIN-PARA.\n",
            "           DISPLAY 'HI'.\n",
            "           STOP RUN.\n",
        ]

    def test_kill_switch_returns_unknown(self):
        with patch.dict(os.environ, {"SPECTER_LLM_REVIEW": "0"}):
            v = review_fix(
                llm_provider=object(),  # would crash if it tried to call
                llm_model="x",
                error_summary="some error",
                src_lines=self._src(),
                fixes={5: "       01 WS-BAR PIC X(2).\n"},
            )
        self.assertEqual(v.verdict, "unknown")
        self.assertIn("disabled", v.reason)

    def test_no_provider_returns_unknown(self):
        v = review_fix(
            llm_provider=None,
            llm_model="x",
            error_summary="some error",
            src_lines=self._src(),
            fixes={5: "       01 WS-BAR PIC X(2).\n"},
        )
        self.assertEqual(v.verdict, "unknown")

    def test_empty_fixes_returns_unknown(self):
        v = review_fix(
            llm_provider=object(),
            llm_model="x",
            error_summary="some error",
            src_lines=self._src(),
            fixes={},
        )
        self.assertEqual(v.verdict, "unknown")

    def test_provider_exception_returns_unknown(self):
        # The reviewer must NEVER let an LLM exception propagate.
        def _boom(*a, **kw):
            raise RuntimeError("simulated 500")

        with patch("specter.llm_coverage._query_llm_sync", side_effect=_boom):
            v = review_fix(
                llm_provider=object(),
                llm_model="x",
                error_summary="some error",
                src_lines=self._src(),
                fixes={5: "       01 WS-BAR PIC X(2).\n"},
            )
        self.assertEqual(v.verdict, "unknown")
        self.assertIn("simulated", v.reason)

    def test_accept_path(self):
        # The challenger says accept and the parser turns the JSON into
        # an accepted verdict.
        accept_response = (
            '{"verdict": "accept", "reason": "adds a missing data definition", "severity": "high"}'
        )
        with patch(
            "specter.llm_coverage._query_llm_sync",
            return_value=(accept_response, {}),
        ):
            v = review_fix(
                llm_provider=object(),
                llm_model="x",
                error_summary="WS-BAR is not defined",
                src_lines=self._src(),
                fixes={5: "       01 WS-BAR PIC X(2).\n"},
            )
        self.assertTrue(v.accepted)

    def test_reject_path_propagates_reason(self):
        reject_response = (
            '{"verdict": "reject", "reason": '
            '"comments out an active business statement", "severity": "high"}'
        )
        with patch(
            "specter.llm_coverage._query_llm_sync",
            return_value=(reject_response, {}),
        ):
            v = review_fix(
                llm_provider=object(),
                llm_model="x",
                error_summary="syntax error",
                src_lines=self._src(),
                fixes={8: "      *           DISPLAY 'HI'.\n"},
            )
        self.assertFalse(v.accepted)
        self.assertEqual(v.severity, "high")
        self.assertIn("comments out", v.reason)


if __name__ == "__main__":
    unittest.main()
