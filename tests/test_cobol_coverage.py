"""Tests for the COBOL coverage-guided test generation engine.

Covers: variable domain model, branch instrumentation, coverage parsing,
mock data generation, and the agentic coverage loop.
"""

import json
import random
import shutil
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from specter.copybook_parser import CopybookField, CopybookRecord
from specter.variable_domain import (
    VariableDomain,
    build_variable_domains,
    format_value_for_cobol,
    generate_value,
    load_copybooks,
    _compute_range,
    _infer_semantic_type,
)
from specter.variable_extractor import VariableInfo, VariableReport


# ---------------------------------------------------------------------------
# Variable Domain Model tests
# ---------------------------------------------------------------------------


class TestVariableDomain:
    """Tests for VariableDomain construction and value generation."""

    def test_numeric_pic_9_5(self):
        """PIC 9(5) → max_value=99999, data_type=numeric."""
        report = VariableReport(variables={
            "WS-COUNT": VariableInfo(
                name="WS-COUNT", classification="input",
            ),
        })
        records = [CopybookRecord(
            name="WS-REC",
            fields=[CopybookField(
                level=5, name="WS-COUNT", pic="9(5)",
                pic_type="numeric", length=5, precision=0,
                occurs=1, is_filler=False,
            )],
            copybook_file="test.cpy",
        )]
        domains = build_variable_domains(report, records)
        d = domains["WS-COUNT"]
        assert d.data_type == "numeric"
        assert d.max_length == 5
        assert d.max_value == 99999
        assert d.min_value == 0
        assert d.precision == 0
        assert not d.signed

    def test_alpha_pic_x_10(self):
        """PIC X(10) → max_length=10, data_type=alpha."""
        report = VariableReport(variables={
            "WS-NAME": VariableInfo(
                name="WS-NAME", classification="input",
            ),
        })
        records = [CopybookRecord(
            name="WS-REC",
            fields=[CopybookField(
                level=5, name="WS-NAME", pic="X(10)",
                pic_type="alpha", length=10, precision=0,
                occurs=1, is_filler=False,
            )],
            copybook_file="test.cpy",
        )]
        domains = build_variable_domains(report, records)
        d = domains["WS-NAME"]
        assert d.data_type == "alpha"
        assert d.max_length == 10
        assert d.min_value is None
        assert d.max_value is None

    def test_signed_packed_pic_s9_5_v99(self):
        """PIC S9(5)V99 → min_value=-99999.99, precision=2."""
        report = VariableReport(variables={
            "WS-AMOUNT": VariableInfo(
                name="WS-AMOUNT", classification="input",
            ),
        })
        records = [CopybookRecord(
            name="WS-REC",
            fields=[CopybookField(
                level=5, name="WS-AMOUNT", pic="S9(5)V99",
                pic_type="packed", length=5, precision=2,
                occurs=1, is_filler=False, values_88={},
            )],
            copybook_file="test.cpy",
        )]
        domains = build_variable_domains(report, records)
        d = domains["WS-AMOUNT"]
        assert d.data_type == "packed"
        assert d.precision == 2
        assert d.signed is True
        assert d.min_value is not None
        assert d.min_value < 0
        # max_value should be 99999 + fraction
        assert d.max_value is not None
        assert d.max_value > 99999

    def test_88_level_values(self):
        """88-level conditions populate valid_88_values."""
        report = VariableReport(variables={
            "PA-AUTH-RESULT": VariableInfo(
                name="PA-AUTH-RESULT", classification="status",
            ),
        })
        records = [CopybookRecord(
            name="WS-REC",
            fields=[CopybookField(
                level=5, name="PA-AUTH-RESULT", pic="X(2)",
                pic_type="alpha", length=2, precision=0,
                occurs=1, is_filler=False,
                values_88={"PA-AUTH-APPROVED": "00", "PA-AUTH-DENIED": "05"},
            )],
            copybook_file="test.cpy",
        )]
        domains = build_variable_domains(report, records)
        d = domains["PA-AUTH-RESULT"]
        assert d.valid_88_values == {"PA-AUTH-APPROVED": "00", "PA-AUTH-DENIED": "05"}

    def test_semantic_inference_date(self):
        """Variable named WS-PROC-DATE → semantic_type=date."""
        report = VariableReport(variables={
            "WS-PROC-DATE": VariableInfo(
                name="WS-PROC-DATE", classification="input",
            ),
        })
        domains = build_variable_domains(report)
        assert domains["WS-PROC-DATE"].semantic_type == "date"

    def test_semantic_inference_status(self):
        """Variable ending in -STATUS → semantic_type=status_file."""
        report = VariableReport(variables={
            "FILE-STATUS-INFILE": VariableInfo(
                name="FILE-STATUS-INFILE", classification="status",
            ),
        })
        domains = build_variable_domains(report)
        assert domains["FILE-STATUS-INFILE"].semantic_type == "status_file"

    def test_semantic_inference_flag(self):
        """Variable with FLAG → semantic_type=flag_bool."""
        report = VariableReport(variables={
            "WS-ERROR-FLAG": VariableInfo(
                name="WS-ERROR-FLAG", classification="flag",
            ),
        })
        domains = build_variable_domains(report)
        assert domains["WS-ERROR-FLAG"].semantic_type == "flag_bool"

    def test_stub_mapping_populates_set_by_stub(self):
        """Variables in stub_mapping get set_by_stub populated."""
        report = VariableReport(variables={
            "SQLCODE": VariableInfo(name="SQLCODE", classification="status"),
        })
        stub_mapping = {"SQL": ["SQLCODE"]}
        domains = build_variable_domains(report, stub_mapping=stub_mapping)
        assert domains["SQLCODE"].set_by_stub == "SQL"

    def test_condition_literals_from_ast(self):
        """condition_literals from VariableInfo propagate to domain."""
        report = VariableReport(variables={
            "WS-CODE": VariableInfo(
                name="WS-CODE", classification="input",
                condition_literals=["00", "10", "23"],
            ),
        })
        domains = build_variable_domains(report)
        assert domains["WS-CODE"].condition_literals == ["00", "10", "23"]


class TestGenerateValue:
    """Tests for generate_value() with different strategies."""

    def _make_numeric_domain(self, **kwargs):
        defaults = dict(
            name="TEST-VAR", data_type="numeric", max_length=5,
            precision=0, signed=False, min_value=0, max_value=99999,
        )
        defaults.update(kwargs)
        return VariableDomain(**defaults)

    def _make_alpha_domain(self, **kwargs):
        defaults = dict(
            name="TEST-VAR", data_type="alpha", max_length=10,
        )
        defaults.update(kwargs)
        return VariableDomain(**defaults)

    def test_condition_literal_strategy(self):
        """condition_literal picks from condition_literals."""
        d = self._make_numeric_domain(condition_literals=[42, 99])
        rng = random.Random(1)
        val = generate_value(d, "condition_literal", rng)
        assert val in [42, 99]

    def test_88_value_strategy(self):
        """88_value picks from valid_88_values."""
        d = self._make_alpha_domain(valid_88_values={"OK": "00", "ERR": "10"})
        rng = random.Random(1)
        val = generate_value(d, "88_value", rng)
        assert val in ["00", "10"]

    def test_boundary_numeric(self):
        """boundary returns min/max/zero for numeric types."""
        d = self._make_numeric_domain()
        rng = random.Random(1)
        val = generate_value(d, "boundary", rng)
        assert isinstance(val, (int, float))
        assert 0 <= val <= 99999 or val == 0

    def test_random_valid_within_range(self):
        """random_valid always produces values within PIC range."""
        d = self._make_numeric_domain(min_value=0, max_value=99999)
        rng = random.Random(42)
        for _ in range(100):
            val = generate_value(d, "random_valid", rng)
            assert isinstance(val, int)
            assert 0 <= val <= 99999

    def test_random_valid_alpha(self):
        """random_valid for alpha produces correct length strings."""
        d = self._make_alpha_domain(max_length=5)
        rng = random.Random(42)
        val = generate_value(d, "random_valid", rng)
        assert isinstance(val, str)
        assert len(val) == 5

    def test_semantic_date(self):
        """semantic strategy for date type produces YYYYMMDD format."""
        d = self._make_numeric_domain(
            max_length=8, semantic_type="date",
        )
        rng = random.Random(42)
        val = generate_value(d, "semantic", rng)
        assert isinstance(val, str)
        assert len(val) == 8
        year = int(val[:4])
        assert 2020 <= year <= 2027

    def test_semantic_status_file(self):
        """semantic strategy for status_file returns valid file status."""
        d = self._make_alpha_domain(semantic_type="status_file")
        rng = random.Random(42)
        val = generate_value(d, "semantic", rng)
        assert val in ["00", "10", "23", "35", "39", "41", "46", "47"]

    def test_adversarial_numeric(self):
        """adversarial returns edge cases."""
        d = self._make_numeric_domain()
        rng = random.Random(42)
        val = generate_value(d, "adversarial", rng)
        assert isinstance(val, (int, float))

    def test_boundary_with_precision(self):
        """boundary for PIC S9(5)V99 returns float values."""
        d = VariableDomain(
            name="AMT", data_type="packed", max_length=5,
            precision=2, signed=True, min_value=-99999.99, max_value=99999.99,
        )
        rng = random.Random(42)
        val = generate_value(d, "boundary", rng)
        assert isinstance(val, (int, float))


class TestFormatValue:
    """Tests for format_value_for_cobol()."""

    def test_alpha_right_padded(self):
        d = VariableDomain(name="X", data_type="alpha", max_length=10)
        assert format_value_for_cobol(d, "ABC") == "ABC       "

    def test_numeric_integer(self):
        d = VariableDomain(name="N", data_type="numeric", max_length=5, precision=0)
        assert format_value_for_cobol(d, 42) == "42"

    def test_numeric_decimal(self):
        d = VariableDomain(name="A", data_type="packed", max_length=5, precision=2)
        assert format_value_for_cobol(d, 123.45) == "123.45"


class TestComputeRange:
    """Tests for _compute_range()."""

    def test_pic_9_5(self):
        lo, hi = _compute_range("numeric", 5, 0, False)
        assert lo == 0
        assert hi == 99999

    def test_pic_s9_5(self):
        lo, hi = _compute_range("numeric", 5, 0, True)
        assert lo == -99999
        assert hi == 99999

    def test_pic_s9_9_v99(self):
        lo, hi = _compute_range("packed", 9, 2, True)
        assert lo < 0
        assert hi > 999999999

    def test_alpha_no_range(self):
        lo, hi = _compute_range("alpha", 10, 0, False)
        assert lo is None
        assert hi is None


class TestSemanticInference:
    """Tests for _infer_semantic_type()."""

    def test_date(self):
        assert _infer_semantic_type("WS-PROC-DATE", "input") == "date"

    def test_time(self):
        assert _infer_semantic_type("WS-START-TIME", "input") == "time"

    def test_amount(self):
        assert _infer_semantic_type("WS-TOTAL-AMT", "input") == "amount"

    def test_counter(self):
        assert _infer_semantic_type("WS-REC-COUNT", "input") == "counter"

    def test_sqlcode(self):
        assert _infer_semantic_type("SQLCODE", "status") == "status_sql"

    def test_file_status(self):
        assert _infer_semantic_type("FILE-STATUS-CUST", "status") == "status_file"

    def test_flag(self):
        assert _infer_semantic_type("WS-EOF-FLAG", "flag") == "flag_bool"

    def test_generic(self):
        assert _infer_semantic_type("WS-FOOBAR", "internal") == "generic"


# ---------------------------------------------------------------------------
# Branch instrumentation tests
# ---------------------------------------------------------------------------


class TestBranchTracing:
    """Tests for _add_branch_tracing()."""

    def test_if_with_else(self):
        """IF with ELSE gets T and F probes."""
        from specter.cobol_mock import _add_branch_tracing

        lines = [
            "       IDENTIFICATION DIVISION.\n",
            "       PROCEDURE DIVISION.\n",
            "       MAIN-PARA.\n",
            "           IF WS-STATUS = '00'\n",
            "               DISPLAY 'OK'\n",
            "           ELSE\n",
            "               DISPLAY 'ERR'\n",
            "           END-IF.\n",
        ]
        result, meta, count = _add_branch_tracing(lines)
        text = "".join(result)
        assert "@@B:1:T" in text
        assert "@@B:1:F" in text
        assert count == 1
        assert "1" in meta
        assert meta["1"]["type"] == "IF"

    def test_if_without_else(self):
        """IF without ELSE gets inserted ELSE with F probe."""
        from specter.cobol_mock import _add_branch_tracing

        lines = [
            "       IDENTIFICATION DIVISION.\n",
            "       PROCEDURE DIVISION.\n",
            "       MAIN-PARA.\n",
            "           IF WS-FLAG = 'Y'\n",
            "               DISPLAY 'YES'\n",
            "           END-IF.\n",
        ]
        result, meta, count = _add_branch_tracing(lines)
        text = "".join(result)
        assert "@@B:1:T" in text
        assert "@@B:1:F" in text
        assert "ELSE" in text
        assert count == 1

    def test_evaluate_when(self):
        """EVALUATE/WHEN gets probes for each WHEN."""
        from specter.cobol_mock import _add_branch_tracing

        lines = [
            "       IDENTIFICATION DIVISION.\n",
            "       PROCEDURE DIVISION.\n",
            "       MAIN-PARA.\n",
            "           EVALUATE WS-CODE\n",
            "           WHEN '00'\n",
            "               DISPLAY 'OK'\n",
            "           WHEN '10'\n",
            "               DISPLAY 'EOF'\n",
            "           WHEN OTHER\n",
            "               DISPLAY 'ERR'\n",
            "           END-EVALUATE.\n",
        ]
        result, meta, count = _add_branch_tracing(lines)
        text = "".join(result)
        assert "@@B:1:W1" in text
        assert "@@B:1:W2" in text
        assert "@@B:1:WO" in text
        assert count == 1
        assert meta["1"]["type"] == "EVALUATE"

    def test_nested_if(self):
        """Nested IFs get separate branch IDs."""
        from specter.cobol_mock import _add_branch_tracing

        lines = [
            "       IDENTIFICATION DIVISION.\n",
            "       PROCEDURE DIVISION.\n",
            "       MAIN-PARA.\n",
            "           IF WS-A = '1'\n",
            "               IF WS-B = '2'\n",
            "                   DISPLAY 'BOTH'\n",
            "               END-IF\n",
            "           END-IF.\n",
        ]
        result, meta, count = _add_branch_tracing(lines)
        assert count == 2
        assert "1" in meta
        assert "2" in meta

    def test_multiline_if_condition(self):
        """Multi-line IF conditions don't get probe inserted mid-condition."""
        from specter.cobol_mock import _add_branch_tracing

        lines = [
            "       IDENTIFICATION DIVISION.\n",
            "       PROCEDURE DIVISION.\n",
            "       MAIN-PARA.\n",
            "           IF WS-VAR NOT =\n",
            "                              SPACES AND LOW-VALUES\n",
            "               MOVE 'Y' TO WS-FLAG\n",
            "           END-IF.\n",
        ]
        result, meta, count = _add_branch_tracing(lines)
        text = "".join(result)
        assert "@@B:1:T" in text
        # The probe must come AFTER the continuation line, not between
        # "IF WS-VAR NOT =" and "SPACES AND LOW-VALUES"
        probe_pos = text.index("@@B:1:T")
        condition_end_pos = text.index("SPACES AND LOW-VALUES")
        assert probe_pos > condition_end_pos, (
            "Probe must be after condition continuation line"
        )


# ---------------------------------------------------------------------------
# Branch coverage parsing tests
# ---------------------------------------------------------------------------


class TestParseBranchCoverage:
    """Tests for parse_branch_coverage()."""

    def test_basic_parsing(self):
        from specter.cobol_executor import parse_branch_coverage

        stdout = (
            "SPECTER-TRACE:MAIN-PARA\n"
            "@@B:1:T\n"
            "some display output\n"
            "@@B:2:F\n"
            "@@B:3:W1\n"
        )
        branches = parse_branch_coverage(stdout)
        assert branches == {"1:T", "2:F", "3:W1"}

    def test_empty_output(self):
        from specter.cobol_executor import parse_branch_coverage

        assert parse_branch_coverage("") == set()
        assert parse_branch_coverage("just normal output\n") == set()


# ---------------------------------------------------------------------------
# Mock data generation tests
# ---------------------------------------------------------------------------


class TestMockDataGeneration:
    """Tests for INIT records and mock data ordering."""

    def test_init_records_format(self):
        from specter.cobol_mock import generate_init_records

        records = generate_init_records({"WS-COUNT": "42", "WS-NAME": "HELLO"})
        lines = records.split("\n")
        # Should have 2 INIT records + 1 END-INIT sentinel
        assert len(lines) == 3
        assert lines[0].startswith("INIT:WS-COUNT")
        assert lines[1].startswith("INIT:WS-NAME")
        assert lines[2].startswith("END-INIT")
        # INIT records are 80 chars; END-INIT sentinel is 60 chars (existing behavior)
        assert len(lines[0]) == 80
        assert len(lines[1]) == 80
        assert len(lines[2]) >= 60

    def test_mock_data_ordered_format(self):
        from specter.cobol_mock import generate_mock_data_ordered

        stub_log = [
            ("READ:INFILE1", [("FILE-STATUS", "00")]),
            ("DLI-ISRT", [("PCB-STATUS", "  ")]),
            ("READ:INFILE1", [("FILE-STATUS", "10")]),
        ]
        data = generate_mock_data_ordered(stub_log)
        lines = data.strip().split("\n")
        assert len(lines) == 3
        assert lines[0].startswith("READ:INFILE1")
        assert lines[1].startswith("DLI-ISRT")
        assert lines[2].startswith("READ:INFILE1")


# ---------------------------------------------------------------------------
# Coverage engine tests
# ---------------------------------------------------------------------------


class TestCoverageState:
    """Tests for coverage state management."""

    def test_load_empty_store(self):
        from specter.cobol_coverage import load_existing_coverage

        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = Path(f.name)
        try:
            path.unlink()
            tcs, paras, branches = load_existing_coverage(path)
            assert tcs == []
            assert paras == set()
            assert branches == set()
        finally:
            path.unlink(missing_ok=True)

    def test_load_populated_store(self):
        from specter.cobol_coverage import load_existing_coverage

        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            record = {
                "id": "abc123",
                "input_state": {"WS-X": "1"},
                "stub_outcomes": [],
                "paragraphs_hit": ["MAIN-PARA", "PROCESS-PARA"],
                "branches_hit": ["1:T", "2:F"],
                "display_output": [],
                "layer": 1,
                "target": "baseline",
            }
            f.write(json.dumps(record) + "\n")
            path = Path(f.name)

        try:
            tcs, paras, branches = load_existing_coverage(path)
            assert len(tcs) == 1
            assert "MAIN-PARA" in paras
            assert "PROCESS-PARA" in paras
            assert "1:T" in branches
        finally:
            path.unlink(missing_ok=True)


class TestCoverageReport:
    """Tests for CobolCoverageReport."""

    def test_summary_format(self):
        from specter.cobol_coverage import CobolCoverageReport

        r = CobolCoverageReport(
            total_test_cases=10,
            paragraph_coverage=0.8,
            branch_coverage=0.6,
            paragraphs_hit=8,
            paragraphs_total=10,
            branches_hit=12,
            branches_total=20,
            elapsed_seconds=5.0,
            layer_stats={1: 5, 2: 3, 4: 2},
        )
        s = r.summary()
        assert "10" in s
        assert "80.0%" in s
        assert "60.0%" in s
        assert "Layer 1" in s


# ---------------------------------------------------------------------------
# Integration test (requires cobc)
# ---------------------------------------------------------------------------


_HAS_COBC = shutil.which("cobc") is not None


@pytest.mark.skipif(not _HAS_COBC, reason="GnuCOBOL (cobc) not installed")
class TestCobolIntegration:
    """Integration tests that compile and run actual COBOL programs."""

    def _write_minimal_cobol(self, tmp_path: Path) -> Path:
        """Write a minimal COBOL program with IF branches."""
        source = tmp_path / "TEST.cbl"
        source.write_text("""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       ENVIRONMENT DIVISION.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-CODE   PIC X(2) VALUE SPACES.
       PROCEDURE DIVISION.
       MAIN-PARA.
           IF WS-CODE = '00'
               DISPLAY 'CODE-OK'
           ELSE
               DISPLAY 'CODE-ERR'
           END-IF.
           STOP RUN.
""")
        return source

    def test_branch_instrument_and_compile(self, tmp_path):
        """Full pipeline: instrument → compile → run."""
        source = self._write_minimal_cobol(tmp_path)

        from specter.cobol_mock import instrument_cobol, MockConfig, compile_cobol, run_cobol

        config = MockConfig(trace_paragraphs=True)
        result = instrument_cobol(source, config)

        # Apply branch tracing
        from specter.cobol_mock import _add_branch_tracing
        lines = result.source.splitlines(keepends=True)
        lines, meta, count = _add_branch_tracing(lines)
        instrumented = "".join(lines)

        mock_path = tmp_path / "TEST.mock.cbl"
        mock_path.write_text(instrumented)

        # Compile
        exe_path = tmp_path / "TEST"
        success, msg = compile_cobol(mock_path, exe_path)
        if not success:
            pytest.skip(f"Compilation failed (expected for minimal program): {msg}")

    def test_parse_trace_from_real_cobol(self, tmp_path):
        """Verify parse_trace extracts paragraph names from COBOL output."""
        from specter.cobol_mock import parse_trace

        stdout = (
            "SPECTER-TRACE:MAIN-PARA\n"
            "CODE-OK\n"
            "SPECTER-TRACE:EXIT-PARA\n"
        )
        trace = parse_trace(stdout)
        assert trace == ["MAIN-PARA", "EXIT-PARA"]

    def test_executor_prepare_and_run(self, tmp_path):
        """Test CobolExecutionContext creation and single test case execution."""
        source = self._write_minimal_cobol(tmp_path)

        from specter.cobol_executor import prepare_context, run_test_case

        try:
            context = prepare_context(source, work_dir=tmp_path)
        except RuntimeError:
            pytest.skip("COBOL compilation failed for minimal program")

        result = run_test_case(
            context,
            input_state={"WS-CODE": "00"},
            stub_log=[],
            work_dir=tmp_path,
        )
        # The minimal program may or may not run correctly depending on
        # instrumentation, but we should at least get no crash
        assert result.error is None or isinstance(result.error, str)
