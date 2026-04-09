"""Tests for the post-run uncovered-branch diagnostic report."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from specter.uncovered_report import (
    AttemptSummary,
    NearestHit,
    UncoveredBranchDetail,
    _classify_condition,
    _count_attempts,
    _extract_branch_conditions,
    _extract_condition_vars,
    _generate_hints,
    _render_markdown,
    generate_uncovered_report,
)


# ---------------------------------------------------------------------------
# Condition classification
# ---------------------------------------------------------------------------

class TestClassifyCondition(unittest.TestCase):
    def test_empty_is_unknown(self):
        self.assertEqual(_classify_condition(""), "unknown")

    def test_file_status_numeric(self):
        self.assertEqual(
            _classify_condition("IF ACCTFILE-STATUS = '10'"),
            "file_status_eq",
        )

    def test_bare_88_flag(self):
        self.assertEqual(
            _classify_condition("IF APPL-EOF"),
            "status_flag_88",
        )

    def test_compound_and(self):
        self.assertEqual(
            _classify_condition("IF A = 'X' AND B = 'Y'"),
            "compound_and_or",
        )

    def test_compound_or(self):
        self.assertEqual(
            _classify_condition("IF A = 'X' OR B = 'Y'"),
            "compound_and_or",
        )

    def test_numeric_greater(self):
        self.assertEqual(
            _classify_condition("IF WS-COUNT > 100"),
            "numeric_cmp",
        )

    def test_numeric_greater_than_word(self):
        self.assertEqual(
            _classify_condition("IF WS-COUNT GREATER THAN 100"),
            "numeric_cmp",
        )

    def test_not_numeric(self):
        self.assertEqual(
            _classify_condition("IF IO-STATUS NOT NUMERIC"),
            "not_numeric",
        )

    def test_string_eq(self):
        self.assertEqual(
            _classify_condition("IF WS-FLAG = 'Y'"),
            "string_eq",
        )

    def test_evaluate_when(self):
        self.assertEqual(
            _classify_condition("WHEN 'TRNXFILE'"),
            "evaluate_when",
        )

    def test_evaluate_head(self):
        self.assertEqual(
            _classify_condition("EVALUATE WS-FL-DD"),
            "evaluate_head",
        )

    def test_perform_until(self):
        self.assertEqual(
            _classify_condition("PERFORM UNTIL END-OF-FILE = 'Y'"),
            "loop_until",
        )


# ---------------------------------------------------------------------------
# Variable extraction
# ---------------------------------------------------------------------------

class TestExtractConditionVars(unittest.TestCase):
    def test_single_var(self):
        self.assertEqual(
            _extract_condition_vars("IF WS-STATUS = '00'"),
            ["WS-STATUS"],
        )

    def test_compound_condition(self):
        result = _extract_condition_vars("IF A-VAR = 'X' AND B-VAR > 10")
        self.assertIn("A-VAR", result)
        self.assertIn("B-VAR", result)

    def test_keywords_filtered(self):
        result = _extract_condition_vars("IF WS-FOO NOT EQUAL SPACES")
        self.assertIn("WS-FOO", result)
        self.assertNotIn("NOT", result)
        self.assertNotIn("EQUAL", result)
        self.assertNotIn("SPACES", result)

    def test_single_char_names_filtered(self):
        result = _extract_condition_vars("IF X = 0")
        self.assertNotIn("X", result)

    def test_duplicates_deduped(self):
        result = _extract_condition_vars("IF A-VAR = A-VAR")
        self.assertEqual(result, ["A-VAR"])


# ---------------------------------------------------------------------------
# Branch-condition extraction from mock source
# ---------------------------------------------------------------------------

class TestExtractBranchConditions(unittest.TestCase):
    def test_basic_probe_walk(self):
        cobol = (
            "       PROCEDURE DIVISION.\n"
            "       MAIN-PARA.\n"
            "           IF WS-FOO = 'A'\n"
            "           DISPLAY '@@B:1:T'\n"
            "               MOVE 1 TO WS-BAR\n"
            "           ELSE\n"
            "           DISPLAY '@@B:1:F'\n"
            "               MOVE 0 TO WS-BAR\n"
            "           END-IF.\n"
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".cbl", delete=False) as f:
            f.write(cobol)
            path = Path(f.name)
        try:
            result = _extract_branch_conditions(path)
        finally:
            path.unlink()

        self.assertIn("1", result)
        entry = result["1"]
        self.assertEqual(entry["paragraph"], "MAIN-PARA")
        self.assertIn("WS-FOO", entry["condition_text"])
        self.assertEqual(entry["condition_type"], "IF")

    def test_comment_lines_ignored(self):
        cobol = (
            "       PROCEDURE DIVISION.\n"
            "       MAIN-PARA.\n"
            "      *    IF SHOULD-NOT-MATCH = 'X'\n"
            "           IF REAL-VAR > 5\n"
            "           DISPLAY '@@B:42:T'\n"
            "               CONTINUE.\n"
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".cbl", delete=False) as f:
            f.write(cobol)
            path = Path(f.name)
        try:
            result = _extract_branch_conditions(path)
        finally:
            path.unlink()

        self.assertIn("REAL-VAR", result["42"]["condition_text"])
        self.assertNotIn("SHOULD-NOT-MATCH", result["42"]["condition_text"])

    def test_nonexistent_file(self):
        self.assertEqual(_extract_branch_conditions(Path("/nonexistent.cbl")), {})


# ---------------------------------------------------------------------------
# Attempt counting
# ---------------------------------------------------------------------------

class TestCountAttempts(unittest.TestCase):
    def _tc(self, layer, target, paragraphs, branches=None, input_state=None):
        return {
            "id": f"tc-{hash((layer, target)) & 0xffff}",
            "layer": layer,
            "target": target,
            "paragraphs_hit": paragraphs,
            "branches_hit": branches or [],
            "input_state": input_state or {},
        }

    def test_no_test_cases(self):
        total, strategies, nearest = _count_attempts([], 42, "T", "MAIN")
        self.assertEqual(total, 0)
        self.assertEqual(strategies, [])
        self.assertIsNone(nearest)

    def test_direct_bid_match(self):
        tcs = [self._tc(
            "direct_paragraph",
            "direct:MAIN-PARA|chain-if:42:T",
            ["MAIN-PARA"],
        )]
        total, strategies, _ = _count_attempts(tcs, 42, "T", "MAIN-PARA")
        self.assertEqual(total, 1)
        self.assertEqual(strategies[0].strategy, "direct_paragraph")
        self.assertEqual(strategies[0].direct_bid_match, 1)

    def test_paragraph_match_only(self):
        tcs = [self._tc(
            "baseline", "baseline", ["MAIN-PARA", "OTHER-PARA"],
        )]
        total, strategies, _ = _count_attempts(tcs, 42, "T", "MAIN-PARA")
        self.assertEqual(total, 1)
        self.assertEqual(strategies[0].paragraph_match, 1)
        self.assertEqual(strategies[0].direct_bid_match, 0)

    def test_multiple_strategies_aggregated(self):
        tcs = [
            self._tc("baseline", "baseline", ["P"]),
            self._tc("baseline", "lit:X", ["P"]),
            self._tc("fault_injection", "fault:READ:F=10", ["P"]),
        ]
        total, strategies, _ = _count_attempts(tcs, 5, "T", "P")
        self.assertEqual(total, 3)
        self.assertEqual(len(strategies), 2)
        baseline = next(s for s in strategies if s.strategy == "baseline")
        self.assertEqual(baseline.count, 2)

    def test_nearest_hit_picked(self):
        tcs = [
            self._tc(
                "baseline", "baseline", ["P"],
                branches=["5:F"],
                input_state={"WS-FOO": "A"},
            ),
            self._tc(
                "direct_paragraph", "direct:P|p:1", ["P"],
                branches=["5:F", "6:T"],
                input_state={"WS-FOO": "B"},
            ),
        ]
        _, _, nearest = _count_attempts(tcs, 5, "T", "P")
        self.assertIsNotNone(nearest)
        # The second test case covered more same-paragraph branches.
        self.assertEqual(nearest.strategy, "direct_paragraph")
        self.assertEqual(nearest.input_state.get("WS-FOO"), "B")


# ---------------------------------------------------------------------------
# Hint generation
# ---------------------------------------------------------------------------

class TestGenerateHints(unittest.TestCase):
    def _detail(self, **kwargs) -> UncoveredBranchDetail:
        defaults = {
            "branch_id": 1,
            "direction": "T",
            "branch_key": "1:T",
            "paragraph": "P",
            "source_file": "",
            "source_line": 0,
            "condition_text": "",
            "condition_category": "unknown",
        }
        defaults.update(kwargs)
        return UncoveredBranchDetail(**defaults)

    def test_file_status_hint(self):
        d = self._detail(
            condition_text="IF WS-STATUS = '22'",
            condition_category="file_status_eq",
        )
        hints = _generate_hints(d)
        joined = " ".join(hints)
        self.assertIn("'22'", joined)
        self.assertIn("WS-STATUS", joined)

    def test_88_level_hint_with_values(self):
        d = self._detail(
            condition_text="IF APPL-EOF",
            condition_category="status_flag_88",
            condition_vars=["APPL-EOF"],
            var_88_values={"APPL-EOF": {"APPL-EOF": 16}},
        )
        hints = _generate_hints(d)
        self.assertTrue(any("activating" in h or "88-level" in h for h in hints))

    def test_compound_hint_mentions_concolic(self):
        d = self._detail(
            condition_text="IF A = 'X' OR B = 'Y'",
            condition_category="compound_and_or",
        )
        hints = _generate_hints(d)
        self.assertTrue(any("concolic" in h.lower() for h in hints))

    def test_no_attempts_hint(self):
        d = self._detail(total_attempts=0)
        hints = _generate_hints(d)
        self.assertTrue(any("reachable" in h or "PERFORM" in h for h in hints))

    def test_stub_return_var_hint(self):
        d = self._detail(
            condition_text="IF CARDFILE-STATUS = '10'",
            condition_category="file_status_eq",
            condition_vars=["CARDFILE-STATUS"],
            stub_return_vars={"CARDFILE-STATUS": "READ:CARDFILE"},
        )
        hints = _generate_hints(d)
        self.assertTrue(any("READ:CARDFILE" in h for h in hints))


# ---------------------------------------------------------------------------
# End-to-end report generation
# ---------------------------------------------------------------------------

class TestGenerateUncoveredReport(unittest.TestCase):
    def _setup_ctx_cov(self, tmp_path):
        # Minimal stand-in objects that mirror the shape the real
        # StrategyContext / CoverageState expose at finalize time.
        ctx = SimpleNamespace(
            branch_meta={"1": {"paragraph": "MAIN-PARA"}, "2": {"paragraph": "MAIN-PARA"}},
            domains={},
            stub_mapping={},
            gating_conds={},
            var_report=None,
        )
        cov = SimpleNamespace(
            branches_hit={"1:T", "1:F", "2:T"},  # 2:F is uncovered
            paragraphs_hit={"MAIN-PARA"},
            test_cases=[
                {
                    "id": "tc-1",
                    "layer": "baseline",
                    "target": "baseline",
                    "paragraphs_hit": ["MAIN-PARA"],
                    "branches_hit": ["1:T", "2:T"],
                    "input_state": {"WS-FOO": "A"},
                    "stub_outcomes": {},
                },
            ],
            total_branches=4,
        )
        report = SimpleNamespace(
            branches_total=4,
            branches_hit=3,
            total_test_cases=1,
            elapsed_seconds=12.3,
        )
        return ctx, cov, report

    def test_writes_json_and_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            store_stem = tmp_path / "tests.jsonl"
            store_stem.write_text("")

            ctx, cov, report = self._setup_ctx_cov(tmp_path)

            result = generate_uncovered_report(
                ctx=ctx,
                cov=cov,
                report=report,
                program_id="TEST",
                mock_source_path=None,
                out_path_stem=store_stem,
                format="both",
            )

            json_path = tmp_path / "tests.uncovered.json"
            md_path = tmp_path / "tests.uncovered.md"
            self.assertTrue(json_path.exists(), f"JSON not written: {list(tmp_path.iterdir())}")
            self.assertTrue(md_path.exists())

            data = json.loads(json_path.read_text())
            self.assertEqual(data["program_id"], "TEST")
            # Exactly one uncovered branch: 2:F
            self.assertEqual(data["uncovered_branches"], 1)
            self.assertEqual(len(data["branches"]), 1)
            self.assertEqual(data["branches"][0]["branch_key"], "2:F")

            md = md_path.read_text()
            self.assertIn("TEST", md)
            self.assertIn("2:F", md)

    def test_json_format_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            store_stem = tmp_path / "tests.jsonl"

            ctx, cov, report = self._setup_ctx_cov(tmp_path)

            generate_uncovered_report(
                ctx=ctx, cov=cov, report=report,
                program_id="TEST",
                mock_source_path=None,
                out_path_stem=store_stem,
                format="json",
            )
            self.assertTrue((tmp_path / "tests.uncovered.json").exists())
            self.assertFalse((tmp_path / "tests.uncovered.md").exists())

    def test_end_to_end_with_mock_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            store_stem = tmp_path / "tests.jsonl"

            cobol = (
                "       PROCEDURE DIVISION.\n"
                "       MAIN-PARA.\n"
                "           IF WS-STATUS = '10'\n"
                "           DISPLAY '@@B:1:T'\n"
                "               CONTINUE\n"
                "           ELSE\n"
                "           DISPLAY '@@B:1:F'\n"
                "               CONTINUE\n"
                "           END-IF.\n"
            )
            mock_path = tmp_path / "TEST.mock.cbl"
            mock_path.write_text(cobol)

            ctx, cov, report = self._setup_ctx_cov(tmp_path)
            ctx.branch_meta = {"1": {"paragraph": "MAIN-PARA"}}
            cov.branches_hit = {"1:T"}  # 1:F uncovered
            cov.total_branches = 2
            report.branches_total = 2
            report.branches_hit = 1

            result = generate_uncovered_report(
                ctx=ctx, cov=cov, report=report,
                program_id="TEST",
                mock_source_path=mock_path,
                out_path_stem=store_stem,
                format="json",
            )

            data = json.loads((tmp_path / "tests.uncovered.json").read_text())
            self.assertEqual(len(data["branches"]), 1)
            entry = data["branches"][0]
            self.assertEqual(entry["branch_key"], "1:F")
            self.assertIn("WS-STATUS", entry["condition_text"])
            self.assertEqual(entry["condition_category"], "file_status_eq")
            self.assertIn("WS-STATUS", entry["condition_vars"])

    def test_markdown_handles_list_form_stub_outcomes(self):
        """Regression: reloaded test stores expose stub_outcomes as a
        list of [op_key, outcome] pairs, not as a dict. The markdown
        renderer must accept both shapes without crashing."""
        from specter.uncovered_report import _render_markdown, _stub_op_preview

        # dict form
        self.assertEqual(
            _stub_op_preview({"READ:F": [("X", "00")], "OPEN:F": []}),
            ["READ:F", "OPEN:F"],
        )
        # list form (reloaded test store)
        self.assertEqual(
            _stub_op_preview([["READ:F", [("X", "00")]], ["OPEN:F", []]]),
            ["READ:F", "OPEN:F"],
        )
        # truncated
        self.assertEqual(
            _stub_op_preview([["A", []], ["B", []], ["C", []]], limit=2),
            ["A", "B"],
        )
        # garbage shapes return empty
        self.assertEqual(_stub_op_preview(None), [])
        self.assertEqual(_stub_op_preview("invalid"), [])
        self.assertEqual(_stub_op_preview([]), [])

        # Full render path: build a NearestHit with list-form stub_outcomes
        # and confirm the markdown renderer doesn't crash.
        from specter.uncovered_report import (
            NearestHit, UncoveredBranchDetail, UncoveredReport,
        )
        detail = UncoveredBranchDetail(
            branch_id=1, direction="T", branch_key="1:T", paragraph="MAIN",
            source_file="", source_line=0, condition_text="IF X = '00'",
            condition_category="file_status_eq",
            nearest_hit=NearestHit(
                test_case_id="tc-1", strategy="baseline", target="baseline",
                input_state={"X": "AA"},
                stub_outcomes=[["READ:F", [["X", "00"]]]],
            ),
        )
        report = UncoveredReport(
            program_id="TEST", total_branches=2, covered_branches=1,
            uncovered_branches=1, total_test_cases=1, elapsed_seconds=1.0,
            generated_at="2026-04-09T00:00:00+00:00", branches=[detail],
        )
        md = _render_markdown(report)
        self.assertIn("Stub ops", md)
        self.assertIn("READ:F", md)

    def test_exception_path_emits_report_before_reraising(self):
        """When _run_agentic_loop raises, the caller's try/except
        must invoke _emit_uncovered_report so the last on-disk
        snapshot reflects the state at the moment of failure. The
        original exception must still propagate afterwards."""
        from unittest.mock import patch
        import os

        # Simulate the run_cobol_coverage caller. The wrapper pattern
        # lives at the call site so we reproduce it inline here.
        from specter.cobol_coverage import _emit_uncovered_report

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            store_stem = tmp_path / "tests.jsonl"
            store_stem.write_text("")

            ctx, cov, report = self._setup_ctx_cov(tmp_path)
            ctx.store_path = store_stem

            captured_err: list[BaseException] = []
            emit_calls: list[str] = []

            def fake_loop(*a, **kw):
                raise RuntimeError("simulated z3 crash")

            def emit_spy(ctx_, cov_, report_, *, reason):
                emit_calls.append(reason)
                # Make sure we can reach the real writer without
                # going through the module-level helper's resolver,
                # which depends on env vars.
                ctx_.uncovered_report_path = store_stem
                from specter.uncovered_report import generate_uncovered_report
                generate_uncovered_report(
                    ctx=ctx_, cov=cov_, report=report_,
                    program_id="TEST",
                    mock_source_path=None,
                    out_path_stem=store_stem,
                    format="both",
                )

            try:
                try:
                    fake_loop()
                except BaseException:
                    emit_spy(ctx, cov, report, reason="exception")
                    raise
            except RuntimeError as exc:
                captured_err.append(exc)

            self.assertEqual(len(captured_err), 1)
            self.assertEqual(str(captured_err[0]), "simulated z3 crash")
            self.assertEqual(emit_calls, ["exception"])
            # And the files should now be on disk.
            self.assertTrue((tmp_path / "tests.uncovered.json").exists())

    def test_never_raises_on_garbage_input(self):
        """If anything in the report pipeline crashes, the caller gets
        an empty report and a warning log. The main coverage loop
        must never be blocked on a reporter failure."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            store_stem = tmp_path / "tests.jsonl"

            # Break something: branch_meta is None on the context.
            ctx = SimpleNamespace(
                branch_meta=None, domains={}, stub_mapping={},
                gating_conds={}, var_report=None,
            )
            cov = SimpleNamespace(
                branches_hit=set(), paragraphs_hit=set(),
                test_cases=[], total_branches=0,
            )
            report = SimpleNamespace(
                branches_total=0, branches_hit=0,
                total_test_cases=0, elapsed_seconds=0.0,
            )

            # Must not raise.
            result = generate_uncovered_report(
                ctx=ctx, cov=cov, report=report,
                program_id="TEST",
                mock_source_path=None,
                out_path_stem=store_stem,
                format="both",
            )
            self.assertIsNotNone(result)


if __name__ == "__main__":
    unittest.main()
