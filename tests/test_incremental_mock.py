"""Tests for incremental_mock.py — incremental COBOL instrumentation."""

from __future__ import annotations

import json
import os
import subprocess
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from specter.incremental_mock import (
    Resolution,
    _apply_preventive_fixes,
    _build_fix_prompt,
    _cluster_errors,
    _compile_and_fix,
    _load_resolutions,
    _parse_errors,
    _save_resolutions,
    incremental_instrument,
)


# ---------------------------------------------------------------------------
# Resolution serialization
# ---------------------------------------------------------------------------

class TestResolutionPersistence:
    """Test resolution log save/load round-trip."""

    def test_save_and_load(self, tmp_path):
        log_path = tmp_path / "resolution_log.json"
        resolutions = [
            Resolution(
                phase="exec_replacement",
                batch=1,
                transformation="Replace EXEC CICS READ",
                error="'DFHCOMMAREA' is not defined",
                fix="Added 01 DFHCOMMAREA PIC X(256).",
                fix_lines={"145": "       01 DFHCOMMAREA PIC X(256).\n"},
                verified=True,
                timestamp="2026-04-01T10:00:00Z",
            ),
            Resolution(
                phase="io_replacement",
                batch=0,
                transformation="Replace READ",
                error="'SQLCODE' is not defined",
                fix="Already in common stubs",
                fix_lines={},
                verified=True,
                timestamp="2026-04-01T10:01:00Z",
            ),
        ]
        _save_resolutions(resolutions, log_path)
        loaded = _load_resolutions(log_path)
        assert len(loaded) == 2
        assert loaded[0].phase == "exec_replacement"
        assert loaded[0].fix_lines == {"145": "       01 DFHCOMMAREA PIC X(256).\n"}
        assert loaded[1].verified is True

    def test_load_nonexistent(self, tmp_path):
        log_path = tmp_path / "missing.json"
        assert _load_resolutions(log_path) == []

    def test_load_corrupted(self, tmp_path):
        log_path = tmp_path / "bad.json"
        log_path.write_text("not json at all")
        assert _load_resolutions(log_path) == []

    def test_summary(self):
        r = Resolution(
            phase="exec_replacement", batch=3,
            transformation="Replace EXEC", error="X not defined",
            fix="Added stub", fix_lines={}, verified=True,
        )
        summary = r.summary()
        assert "exec_replacement" in summary
        assert "X not defined" in summary


# ---------------------------------------------------------------------------
# Error parsing
# ---------------------------------------------------------------------------

class TestParseErrors:
    """Test cobc error output parsing."""

    def test_basic_errors(self):
        stderr = textwrap.dedent("""\
            test.cbl:100: error: 'WS-FIELD' is not defined
            test.cbl:200: error: syntax error, unexpected ELSE
            test.cbl:300: warning: something (not an error)
        """)
        errors = _parse_errors(stderr, "test.cbl")
        assert len(errors) == 2
        assert errors[0] == (100, "'WS-FIELD' is not defined")
        assert errors[1] == (200, "syntax error, unexpected ELSE")

    def test_no_errors(self):
        assert _parse_errors("all clean", "test.cbl") == []

    def test_deduplicate_by_line(self):
        stderr = (
            "test.cbl:50: error: first\n"
            "test.cbl:50: error: second\n"
        )
        errors = _parse_errors(stderr, "test.cbl")
        assert len(errors) == 1  # deduplicated by line

    def test_cluster_errors_adjacent(self):
        """Adjacent errors within gap are grouped into one cluster."""
        errors = [
            (100, "error A"),
            (105, "error B"),
            (108, "error C"),
            (200, "error D"),
        ]
        clusters = _cluster_errors(errors, gap=10)
        assert len(clusters) == 2
        assert len(clusters[0]) == 3  # lines 100, 105, 108
        assert len(clusters[1]) == 1  # line 200

    def test_cluster_errors_all_separate(self):
        errors = [(10, "a"), (100, "b"), (200, "c")]
        clusters = _cluster_errors(errors, gap=10)
        assert len(clusters) == 3

    def test_cluster_errors_all_together(self):
        errors = [(10, "a"), (12, "b"), (15, "c"), (18, "d")]
        clusters = _cluster_errors(errors, gap=10)
        assert len(clusters) == 1
        assert len(clusters[0]) == 4

    def test_cluster_errors_empty(self):
        assert _cluster_errors([]) == []


# ---------------------------------------------------------------------------
# LLM prompt building
# ---------------------------------------------------------------------------

class TestBuildFixPrompt:
    """Test LLM fix prompt construction."""

    def test_includes_resolutions(self):
        resolutions = [
            Resolution(
                phase="exec", batch=1, transformation="test",
                error="X not defined", fix="Added stub",
                fix_lines={}, verified=True,
            ),
        ]
        src_lines = [f"       line {i}\n" for i in range(100)]
        errors = [(50, "'FIELD' is not defined")]
        prompt = _build_fix_prompt(errors, src_lines, "test.cbl", "io_replacement", resolutions)
        assert "Prior resolutions" in prompt
        assert "X not defined" in prompt
        assert "'FIELD' is not defined" in prompt
        assert "io_replacement" in prompt

    def test_no_resolutions(self):
        src_lines = [f"       line {i}\n" for i in range(10)]
        errors = [(5, "some error")]
        prompt = _build_fix_prompt(errors, src_lines, "t.cbl", "test", [])
        assert "Prior resolutions" not in prompt
        assert "some error" in prompt


# ---------------------------------------------------------------------------
# Preventive fixes
# ---------------------------------------------------------------------------

class TestPreventiveFixes:
    """Test applying cached fixes proactively."""

    def test_applies_verified_fixes(self):
        lines = ["line 0\n", "line 1\n", "line 2\n"]
        resolutions = [
            Resolution(
                phase="test", batch=0, transformation="t",
                error="err", fix="fixed",
                fix_lines={"2": "FIXED LINE 2\n"},
                verified=True,
            ),
        ]
        result = _apply_preventive_fixes(lines, resolutions)
        assert result[1] == "FIXED LINE 2\n"
        assert result[0] == "line 0\n"  # unchanged

    def test_skips_unverified(self):
        lines = ["line 0\n", "line 1\n"]
        resolutions = [
            Resolution(
                phase="test", batch=0, transformation="t",
                error="err", fix="fixed",
                fix_lines={"1": "CHANGED\n"},
                verified=False,
            ),
        ]
        result = _apply_preventive_fixes(lines, resolutions)
        assert result[0] == "line 0\n"  # unchanged


# ---------------------------------------------------------------------------
# Compile and fix cycle
# ---------------------------------------------------------------------------

class TestCompileAndFix:
    """Test the compile-and-fix cycle."""

    @patch("specter.incremental_mock._cobc_syntax_check")
    def test_compiles_clean(self, mock_check, tmp_path):
        src = tmp_path / "test.cbl"
        src.write_text("       IDENTIFICATION DIVISION.\n")
        mock_check.return_value = (0, "")

        resolutions = _compile_and_fix(src, "test", 0, [])
        assert resolutions == []
        mock_check.assert_called_once()

    @patch("specter.incremental_mock._cobc_syntax_check")
    def test_no_llm_reports_errors(self, mock_check, tmp_path):
        src = tmp_path / "test.cbl"
        src.write_text("       bad code\n")
        mock_check.return_value = (1, "test.cbl:1: error: syntax error")

        resolutions = _compile_and_fix(src, "test", 0, [], llm_provider=None)
        assert resolutions == []  # no LLM, just reports

    @patch("specter.incremental_mock._cobc_syntax_check")
    def test_baseline_errors_filtered(self, mock_check, tmp_path):
        src = tmp_path / "test.cbl"
        src.write_text("       code\n")
        mock_check.return_value = (1, "test.cbl:1: error: pre-existing issue")

        baseline = {"pre-existing issue"}
        resolutions = _compile_and_fix(
            src, "test", 0, [], baseline_errors=baseline,
        )
        assert resolutions == []


# ---------------------------------------------------------------------------
# Integration: incremental_instrument with mocked cobc
# ---------------------------------------------------------------------------

class TestIncrementalInstrument:
    """Integration test with mocked cobc compiler."""

    @pytest.fixture
    def simple_cobol(self, tmp_path):
        """Create a minimal COBOL source file with proper column formatting."""
        src = tmp_path / "TEST.cbl"
        # COBOL fixed format: cols 1-6 = sequence, col 7 = indicator, cols 8-72 = code
        lines = [
            "       IDENTIFICATION DIVISION.\n",
            "       PROGRAM-ID. TEST.\n",
            "       ENVIRONMENT DIVISION.\n",
            "       INPUT-OUTPUT SECTION.\n",
            "       FILE-CONTROL.\n",
            "       DATA DIVISION.\n",
            "       WORKING-STORAGE SECTION.\n",
            "       01 WS-STATUS PIC X(02) VALUE SPACES.\n",
            "       PROCEDURE DIVISION.\n",
            "       MAIN-PARA.\n",
            "           DISPLAY 'HELLO'.\n",
            "           STOP RUN.\n",
        ]
        src.write_text("".join(lines))
        return src

    @patch("specter.incremental_mock._cobc_compile")
    @patch("specter.incremental_mock._cobc_syntax_check")
    def test_happy_path(self, mock_syntax, mock_compile, simple_cobol, tmp_path):
        """All phases compile clean, no LLM needed."""
        mock_syntax.return_value = (0, "")
        mock_compile.return_value = (0, "")

        output_dir = tmp_path / "build"
        # Create a fake executable so the check passes
        output_dir.mkdir(parents=True)
        fake_exe = output_dir / "TEST"
        fake_exe.write_text("fake")

        mock_path, branch_meta, total_branches = incremental_instrument(
            simple_cobol,
            copybook_dirs=[],
            output_dir=output_dir,
        )

        assert mock_path.exists()
        assert mock_path.name == "TEST.mock.cbl"
        # Resolution log should exist
        res_log = output_dir / "resolution_log.json"
        assert res_log.exists()
        data = json.loads(res_log.read_text())
        assert "resolutions" in data

    @patch("specter.incremental_mock._cobc_compile")
    @patch("specter.incremental_mock._cobc_syntax_check")
    def test_preserves_mock_infrastructure(self, mock_syntax, mock_compile,
                                            simple_cobol, tmp_path):
        """Verify that mock infrastructure is added to the source."""
        mock_syntax.return_value = (0, "")
        mock_compile.return_value = (0, "")

        output_dir = tmp_path / "build"
        output_dir.mkdir(parents=True)
        (output_dir / "TEST").write_text("fake")

        mock_path, _, _ = incremental_instrument(
            simple_cobol,
            copybook_dirs=[],
            output_dir=output_dir,
        )

        content = mock_path.read_text()
        assert "MOCK-FILE" in content
        assert "MOCK-RECORD" in content
        assert "SPECTER-TRACE:" in content

    @patch("specter.incremental_mock._cobc_compile")
    @patch("specter.incremental_mock._cobc_syntax_check")
    def test_resolution_log_reused(self, mock_syntax, mock_compile,
                                    simple_cobol, tmp_path):
        """Prior resolutions are loaded on re-run."""
        mock_syntax.return_value = (0, "")
        mock_compile.return_value = (0, "")

        output_dir = tmp_path / "build"
        output_dir.mkdir(parents=True)
        (output_dir / "TEST").write_text("fake")

        # Pre-populate resolution log
        prior_res = [Resolution(
            phase="prior_run", batch=0, transformation="test",
            error="old error", fix="old fix",
            fix_lines={"10": "       fixed\n"}, verified=True,
        )]
        _save_resolutions(prior_res, output_dir / "resolution_log.json")

        mock_path, _, _ = incremental_instrument(
            simple_cobol,
            copybook_dirs=[],
            output_dir=output_dir,
        )

        # The final resolution log should contain the prior resolution
        data = json.loads((output_dir / "resolution_log.json").read_text())
        phases = [r["phase"] for r in data["resolutions"]]
        assert "prior_run" in phases

    @patch("specter.incremental_mock._cobc_compile")
    @patch("specter.incremental_mock._cobc_syntax_check")
    def test_compile_failure_raises(self, mock_syntax, mock_compile,
                                     simple_cobol, tmp_path):
        """Final compilation failure raises RuntimeError."""
        mock_syntax.return_value = (0, "")  # phases pass syntax
        mock_compile.return_value = (1, "TEST.mock.cbl:1: error: fatal")

        output_dir = tmp_path / "build"
        output_dir.mkdir(parents=True)

        with pytest.raises(RuntimeError, match="COBOL compilation failed"):
            incremental_instrument(
                simple_cobol,
                copybook_dirs=[],
                output_dir=output_dir,
            )


# ---------------------------------------------------------------------------
# Phase functions (isolated)
# ---------------------------------------------------------------------------

class TestPhaseFunctions:
    """Test individual phase functions in isolation."""

    def test_phase_copy_resolution(self):
        from specter.incremental_mock import _phase_copy_resolution
        lines = ["       IDENTIFICATION DIVISION.\n"]
        result, desc = _phase_copy_resolution(lines, [])
        assert "Resolved" in desc

    def test_phase_exec_replacement(self):
        from specter.cobol_mock import MockConfig, _replace_exec_blocks
        lines = [
            "       PROCEDURE DIVISION.\n",
            "       MAIN-PARA.\n",
            "           EXEC CICS RETURN END-EXEC.\n",
        ]
        config = MockConfig()
        result, count = _replace_exec_blocks(lines, config)
        assert count >= 1

    def test_exec_replacement_max_count(self):
        """max_count limits how many EXEC blocks are replaced per call."""
        from specter.cobol_mock import MockConfig, _replace_exec_blocks
        lines = [
            "       PROCEDURE DIVISION.\n",
            "       PARA-1.\n",
            "           EXEC CICS RETURN END-EXEC.\n",
            "       PARA-2.\n",
            "           EXEC CICS SEND END-EXEC.\n",
            "       PARA-3.\n",
            "           EXEC SQL SELECT 1 END-EXEC.\n",
        ]
        config = MockConfig()
        # Replace only 1 block
        result, count = _replace_exec_blocks(lines, config, max_count=1)
        assert count == 1
        # The remaining 2 EXEC blocks should still be in the output
        remaining = sum(1 for l in result if "EXEC" in l and not l.strip().startswith("*"))
        assert remaining == 2

        # Replace all (no limit)
        result2, count2 = _replace_exec_blocks(lines, config, max_count=0)
        assert count2 == 3

    def test_io_replacement_max_count(self):
        """max_count limits how many IO verbs are replaced per call."""
        from specter.cobol_mock import _replace_io_verbs
        lines = [
            "       PROCEDURE DIVISION.\n",
            "       PARA-1.\n",
            "           READ MY-FILE.\n",
            "       PARA-2.\n",
            "           WRITE MY-REC.\n",
        ]
        result, count = _replace_io_verbs(lines, max_count=1)
        assert count == 1
        # One IO verb should still be unreplaced
        remaining = sum(
            1 for l in result
            if any(v in l.upper() for v in ("READ MY-FILE", "WRITE MY-REC"))
            and not l.strip().startswith("*")
        )
        assert remaining == 1

    def test_call_replacement_max_count(self):
        """max_count limits how many CALL statements are replaced per call."""
        from specter.cobol_mock import _replace_call_stmts
        lines = [
            "       PROCEDURE DIVISION.\n",
            "       PARA-1.\n",
            "           CALL 'PROG1'.\n",
            "\n",
            "       PARA-2.\n",
            "           CALL 'PROG2'.\n",
        ]
        result, count = _replace_call_stmts(lines, max_count=1)
        assert count == 1
        # One CALL 'PROGn' should still be unreplaced
        remaining = sum(
            1 for l in result
            if "CALL" in l and "'PROG" in l
            and not l.strip().startswith("*")
        )
        assert remaining == 1

    def test_phase_paragraph_tracing(self):
        from specter.incremental_mock import _phase_paragraph_tracing
        lines = [
            "       PROCEDURE DIVISION.\n",
            "       MAIN-PARA.\n",
            "           DISPLAY 'X'.\n",
        ]
        result, desc, count = _phase_paragraph_tracing(lines)
        assert count >= 1
        assert "SPECTER-TRACE:" in "".join(result)
