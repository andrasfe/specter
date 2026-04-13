"""Tests for the compile-fix swarm."""

import json
import unittest
from unittest.mock import patch

from specter.compile_swarm import (
    CompileFixProposal,
    _judge_proposals,
    _parse_fix_response,
    _score_proposal,
    _semantic_prompt,
    _structure_prompt,
    _syntax_prompt,
    propose_compile_fix_swarm,
    swarm_enabled,
)


class TestSwarmEnabled(unittest.TestCase):
    def test_default_enabled(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertTrue(swarm_enabled())

    def test_disabled_by_env(self):
        for val in ("0", "false", "no", "off"):
            with patch.dict("os.environ", {"SPECTER_COMPILE_SWARM": val}):
                self.assertFalse(swarm_enabled())


class TestSpecialistPrompts(unittest.TestCase):
    def test_syntax_prompt_includes_columns(self):
        p = _syntax_prompt(42, "syntax error", "code\nhere")
        self.assertIn("columns", p.lower())
        self.assertIn("syntax", p.lower())
        self.assertIn("42", p)

    def test_semantic_prompt_warns_against_commenting(self):
        p = _semantic_prompt(42, "error", "code")
        self.assertIn("NEVER comment out", p)
        self.assertIn("business logic", p.lower())

    def test_structure_prompt_mentions_88_level(self):
        p = _structure_prompt(42, "condition-name not allowed here", "code")
        self.assertIn("88-level", p)
        self.assertIn("SET", p)
        # Should give specific guidance for the 88-level error
        self.assertIn("condition-name not allowed here", p)


class TestParseFixResponse(unittest.TestCase):
    def test_valid_json(self):
        resp = '{"42": "           SET FLAG TO TRUE\\n", "reasoning": "88-level"}'
        p = _parse_fix_response(resp, "structure")
        self.assertEqual(p.specialist, "structure")
        self.assertEqual(p.fixes[42], "           SET FLAG TO TRUE\n")
        self.assertEqual(p.reasoning, "88-level")

    def test_markdown_fenced(self):
        resp = '```json\n{"1": "fixed\\n", "reasoning": "test"}\n```'
        p = _parse_fix_response(resp, "syntax")
        self.assertEqual(p.fixes[1], "fixed\n")

    def test_empty_response(self):
        p = _parse_fix_response(None, "syntax")
        self.assertEqual(p.fixes, {})
        self.assertIn("empty", p.reasoning)

    def test_garbage_response(self):
        p = _parse_fix_response("not json at all", "syntax")
        self.assertEqual(p.fixes, {})
        self.assertIn("could not parse", p.reasoning)

    def test_adds_trailing_newline(self):
        resp = '{"1": "no newline", "reasoning": "x"}'
        p = _parse_fix_response(resp, "s")
        self.assertEqual(p.fixes[1], "no newline\n")


class TestScoreProposal(unittest.TestCase):
    def _src(self, *lines):
        return [line + "\n" for line in lines]

    def test_empty_proposal_scores_low(self):
        p = CompileFixProposal(specialist="s", fixes={}, reasoning="")
        self.assertLess(_score_proposal(p, []), 0)

    def test_structural_fix_scores_high(self):
        p = CompileFixProposal(
            specialist="structure",
            fixes={1: "           SET FLAG TO TRUE\n"},
            reasoning="88-level",
        )
        src = self._src("           MOVE X TO FLAG")
        score = _score_proposal(p, src)
        self.assertGreater(score, 0)

    def test_commented_out_fix_hard_rejected(self):
        """ANY comment-out of an active line is hard-rejected."""
        p = CompileFixProposal(
            specialist="s",
            fixes={1: "      *COMMENTED\n"},
            reasoning="",
        )
        src = self._src("           DISPLAY 'X'")  # original was active
        score = _score_proposal(p, src)
        self.assertLessEqual(score, -100)

    def test_continue_replacement_hard_rejected(self):
        """Replacing an active statement with CONTINUE is hard-rejected."""
        p = CompileFixProposal(
            specialist="s",
            fixes={1: "           CONTINUE\n"},
            reasoning="",
        )
        src = self._src("           MOVE X TO Y")
        score = _score_proposal(p, src)
        self.assertLessEqual(score, -100)

    def test_exit_replacement_hard_rejected(self):
        """Replacing with EXIT is hard-rejected."""
        p = CompileFixProposal(
            specialist="s",
            fixes={1: "           EXIT.\n"},
            reasoning="",
        )
        src = self._src("           MOVE X TO Y")
        score = _score_proposal(p, src)
        self.assertLessEqual(score, -100)

    def test_deletion_hard_rejected(self):
        """Replacing with whitespace-only is hard-rejected."""
        p = CompileFixProposal(
            specialist="s",
            fixes={1: "\n"},
            reasoning="",
        )
        src = self._src("           MOVE X TO Y")
        score = _score_proposal(p, src)
        self.assertLessEqual(score, -100)

    def test_continue_to_continue_allowed(self):
        """Changing an already-CONTINUE line to CONTINUE is fine."""
        p = CompileFixProposal(
            specialist="s",
            fixes={1: "           CONTINUE\n"},
            reasoning="",
        )
        src = self._src("           CONTINUE")
        score = _score_proposal(p, src)
        self.assertGreater(score, -100)

    def test_unwanted_goback_penalty(self):
        p = CompileFixProposal(
            specialist="s",
            fixes={1: "           GOBACK.\n"},
            reasoning="",
        )
        src = self._src("           DISPLAY 'X'")  # original wasn't GOBACK
        score = _score_proposal(p, src)
        self.assertLess(score, 0)

    def test_preserves_existing_goback(self):
        # If the line was already GOBACK, no penalty for keeping it
        p = CompileFixProposal(
            specialist="s",
            fixes={1: "           GOBACK.\n"},
            reasoning="",
        )
        src = self._src("           GOBACK.")
        score = _score_proposal(p, src)
        self.assertGreaterEqual(score, 0)


class TestJudgeProposals(unittest.TestCase):
    def _src(self, *lines):
        return [line + "\n" for line in lines]

    def test_picks_highest_scoring(self):
        good = CompileFixProposal(
            specialist="structure",
            fixes={1: "           SET FLAG TO TRUE\n"},
            reasoning="88-level",
        )
        bad = CompileFixProposal(
            specialist="semantic",
            fixes={1: "      *COMMENTED OUT\n"},
            reasoning="",
        )
        src = self._src("           MOVE X TO FLAG")
        winner = _judge_proposals([good, bad], src)
        self.assertEqual(winner.specialist, "structure")

    def test_rejects_all_bad_proposals(self):
        bad1 = CompileFixProposal(
            specialist="s1",
            fixes={1: "      *X\n", 2: "      *Y\n", 3: "      *Z\n"},
            reasoning="",
        )
        bad2 = CompileFixProposal(specialist="s2", fixes={}, reasoning="")
        src = self._src("A", "B", "C")
        winner = _judge_proposals([bad1, bad2], src)
        self.assertEqual(winner.fixes, {})
        self.assertIn("rejected", winner.reasoning)


class TestProposeCompileFixSwarm(unittest.TestCase):
    def test_no_llm_provider(self):
        fixes, reasoning = propose_compile_fix_swarm(
            error_line=1, error_msg="err", context="code", src_lines=[],
            llm_provider=None,
        )
        self.assertEqual(fixes, {})
        self.assertIn("no LLM", reasoning)


if __name__ == "__main__":
    unittest.main()
