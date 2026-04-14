"""Tests for the unified pipeline orchestrator."""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch


def _write_jsonl(path: Path, cases: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for c in cases:
            fh.write(json.dumps(c) + "\n")


def _write_failsafe_xml(reports_dir: Path, suite: str, *, tests: int, failures: int = 0,
                        errors: int = 0, skipped: int = 0,
                        failure_messages: list[tuple[str, str, str]] | None = None) -> None:
    """Write a minimal Failsafe TEST-*.xml file."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    cases_xml = []
    for i in range(tests):
        cases_xml.append(f'  <testcase classname="{suite}" name="test{i}"/>')
    for case_name, kind, msg in (failure_messages or []):
        cases_xml.append(
            f'  <testcase classname="{suite}" name="{case_name}">'
            f'<{kind} message="{msg}">{msg}</{kind}>'
            f'</testcase>'
        )
    body = (
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<testsuite name="{suite}" tests="{tests + len(failure_messages or [])}" '
        f'failures="{failures}" errors="{errors}" skipped="{skipped}">\n'
        + "\n".join(cases_xml) +
        '\n</testsuite>\n'
    )
    (reports_dir / f"TEST-{suite}.xml").write_text(body, encoding="utf-8")


class TestParseTestReports(unittest.TestCase):
    def test_aggregates_counts_and_failures(self):
        from specter.pipeline import _parse_test_reports
        with TemporaryDirectory() as td:
            reports = Path(td) / "failsafe-reports"
            _write_failsafe_xml(
                reports, "DEMO01ProgramIT",
                tests=3, failures=1, errors=0,
                failure_messages=[
                    ("testWithMockitoSpy[1]", "failure",
                     "COBOL/Java equivalence FAILED for tc=abc12345"),
                ],
            )
            stats = _parse_test_reports(reports)
            self.assertEqual(stats["tests"], 4)
            self.assertEqual(stats["failures"], 1)
            self.assertEqual(len(stats["failures_detail"]), 1)
            d = stats["failures_detail"][0]
            self.assertEqual(d["tc_id"], "abc12345")
            self.assertIn("equivalence", d["message"].lower())

    def test_missing_dir_returns_empty(self):
        from specter.pipeline import _parse_test_reports
        with TemporaryDirectory() as td:
            stats = _parse_test_reports(Path(td) / "does-not-exist")
            self.assertEqual(stats["tests"], 0)


class TestRunPipelineEndToEnd(unittest.TestCase):
    """Drive run_pipeline with all heavy phases mocked.

    Asserts: all six phases run in order; report file is written; result
    counts match parsed Failsafe XML; exit code reflects failure presence.
    """

    def _run_with_mocks(
        self,
        td: Path,
        *,
        snapshots: list[str],
        failsafe_failure: bool = False,
        skip_docker: bool = True,
        skip_mvn: bool = False,
    ):
        from specter import pipeline as pipeline_mod

        # Inputs.
        ast_path = td / "demo.ast"
        ast_path.write_text("{}", encoding="utf-8")
        cbl_path = td / "demo.cbl"
        cbl_path.write_text("       IDENTIFICATION DIVISION.\n", encoding="utf-8")
        cpy_dir = td / "cpy"
        cpy_dir.mkdir()

        out_dir = td / "out"

        # Mocked pieces.
        called: list[str] = []

        def fake_run_cobol_coverage(**kwargs):
            called.append("coverage")
            store_path = Path(kwargs["store_path"])
            _write_jsonl(store_path, [
                {"id": tc_id, "input_state": {}, "stub_outcomes": {}}
                for tc_id in snapshots
            ])
            return SimpleNamespace(
                total_test_cases=len(snapshots),
                paragraph_coverage=0.5,
                branch_coverage=0.5,
            )

        def fake_parse_ast(path, cobol_source=None):
            called.append("parse_ast")
            return SimpleNamespace(
                program_id="DEMO01",
                paragraphs=[],
                paragraph_index={},
                entry_statements=None,
            )

        def fake_extract_variables(program):
            called.append("extract_variables")
            return SimpleNamespace(variables={}, input_vars=[], internal_vars=[],
                                   status_vars=[], flag_vars=[])

        def fake_generate_code(program, var_report, **kwargs):
            called.append("generate_code")
            return "# stub generated code\n"

        def fake_load_module(path):
            called.append("load_module")
            return object()

        def fake_prepare_context(**kwargs):
            called.append("prepare_context")
            return SimpleNamespace(executable_path=Path(td) / "demo")

        def fake_capture_snapshots(*args, **kwargs):
            called.append("capture_snapshots")
            output = Path(args[2])
            output.mkdir(parents=True, exist_ok=True)
            written = []
            for tc_id in snapshots:
                p = output / f"{tc_id}.json"
                p.write_text(json.dumps({
                    "id": tc_id, "abended": False, "displays": [],
                    "paragraphs_covered": [], "branches": [],
                    "stub_log_keys": [], "final_state": {}, "return_code": 0,
                }))
                written.append(p)
            return written

        def fake_generate_java_project(*args, **kwargs):
            called.append("generate_java_project")
            project = Path(kwargs["output_dir"])
            project.mkdir(parents=True, exist_ok=True)
            # Fake an integration-tests directory with Failsafe reports.
            it = project / "integration-tests"
            it.mkdir(parents=True, exist_ok=True)
            return str(project.resolve())

        def fake_run(cmd, cwd=None, *, label):
            called.append(f"subprocess:{label}")
            # When mvn verify runs, drop a Failsafe XML so the report parser
            # has something to read.
            if label == "verify":
                reports = Path(cwd) / "target" / "failsafe-reports"
                _write_failsafe_xml(
                    reports, "DEMO01ProgramIT",
                    tests=len(snapshots),
                    failures=1 if failsafe_failure else 0,
                    failure_messages=(
                        [(f"testWithMockitoSpy[1]", "failure",
                          f"COBOL/Java equivalence FAILED for tc={snapshots[0]}")]
                        if failsafe_failure else None
                    ),
                )
            return 0

        with (
            patch.object(pipeline_mod, "_run", side_effect=fake_run),
        ):
            # Patch the lazy-imported names inside run_pipeline.
            with (
                patch("specter.cobol_coverage.run_cobol_coverage",
                      side_effect=fake_run_cobol_coverage),
                patch("specter.ast_parser.parse_ast", side_effect=fake_parse_ast),
                patch("specter.variable_extractor.extract_variables",
                      side_effect=fake_extract_variables),
                patch("specter.code_generator.generate_code",
                      side_effect=fake_generate_code),
                patch("specter.monte_carlo._load_module",
                      side_effect=fake_load_module),
                patch("specter.cobol_executor.prepare_context",
                      side_effect=fake_prepare_context),
                patch("specter.cobol_snapshot.capture_snapshots",
                      side_effect=fake_capture_snapshots),
                patch("specter.java_code_generator.generate_java_project",
                      side_effect=fake_generate_java_project),
            ):
                result = pipeline_mod.run_pipeline(
                    ast_path=ast_path,
                    cobol_source=cbl_path,
                    copybook_dirs=[cpy_dir],
                    output_dir=out_dir,
                    coverage_budget=10,
                    coverage_timeout=60,
                    execution_timeout=10,
                    skip_docker=skip_docker,
                    skip_mvn=skip_mvn,
                )

        return result, called

    def test_full_pipeline_all_pass(self):
        with TemporaryDirectory() as td:
            result, called = self._run_with_mocks(
                Path(td),
                snapshots=["abc1", "abc2", "abc3"],
                failsafe_failure=False,
                skip_docker=True,
                skip_mvn=False,
            )
            self.assertEqual(called[0], "coverage")
            self.assertIn("capture_snapshots", called)
            self.assertIn("generate_java_project", called)
            self.assertEqual(called[-2], "subprocess:install")
            self.assertEqual(called[-1], "subprocess:verify")
            self.assertEqual(result.snapshots_written, 3)
            self.assertEqual(result.tests_run, 3)
            self.assertEqual(result.tests_passed, 3)
            self.assertEqual(result.tests_failed, 0)
            self.assertTrue(result.all_tests_passed)
            self.assertTrue(result.report_path.exists())
            body = result.report_path.read_text()
            self.assertIn("Equivalence Report", body)
            self.assertIn("3", body)

    def test_failure_recorded_in_report(self):
        with TemporaryDirectory() as td:
            result, called = self._run_with_mocks(
                Path(td),
                snapshots=["xyz9"],
                failsafe_failure=True,
                skip_docker=True,
                skip_mvn=False,
            )
            self.assertEqual(result.tests_failed, 1)
            self.assertFalse(result.all_tests_passed)
            body = result.report_path.read_text()
            self.assertIn("xyz9", body)
            self.assertIn("Failing test samples", body)
            self.assertIn("Divergence categories", body)

    def test_skip_flags_prevent_subprocess(self):
        with TemporaryDirectory() as td:
            result, called = self._run_with_mocks(
                Path(td),
                snapshots=["a"],
                skip_docker=True,
                skip_mvn=True,
            )
            self.assertNotIn("subprocess:deploy", called)
            self.assertNotIn("subprocess:verify", called)
            self.assertEqual(result.tests_run, 0)


if __name__ == "__main__":
    unittest.main()
