"""Unified end-to-end pipeline: COBOL → coverage → Java harness → equivalence.

A single command takes a COBOL AST + source + copybooks and produces a
deployable Java project whose integration tests assert behavioural
equivalence with the original COBOL on every synthesized test case.

Phases (each tagged in the CLI output):

1. ``coverage``   — :func:`specter.cobol_coverage.run_cobol_coverage`
                    produces ``tests.jsonl`` (synthesized inputs + stub
                    outcomes) and an instrumented COBOL binary.
2. ``snapshot``   — :func:`specter.cobol_snapshot.capture_snapshots`
                    replays every test case through the binary to record
                    the COBOL ground truth as JSON.
3. ``java``       — :func:`specter.java_code_generator.generate_java_project`
                    emits the Maven project, ``docker-compose.yml`` with
                    PostgreSQL + RabbitMQ + WireMock sidecars, per-test
                    seed SQL, per-test WireMock mappings, and copies the
                    snapshots into the IT classpath.
4. ``deploy``     — ``docker compose up -d`` for sidecars.
5. ``validate``   — ``mvn verify`` in ``integration-tests/`` runs the
                    JUnit5 + Mockito + ``EquivalenceAssert`` matrix.
6. ``report``     — parse Surefire/Failsafe XML; write
                    ``equivalence-report.md`` summarising pass/fail.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence
from xml.etree import ElementTree as ET

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class PipelineResult:
    """Outcome of a unified pipeline run."""

    output_dir: Path
    test_store_path: Path
    snapshot_dir: Path
    project_dir: Path
    coverage_report: object | None = None  # specter.cobol_coverage.CobolCoverageReport
    snapshots_written: int = 0
    docker_compose_returncode: int | None = None
    mvn_returncode: int | None = None
    tests_run: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    tests_errors: int = 0
    tests_skipped: int = 0
    failures: list[dict] = field(default_factory=list)
    failed_tc_ids: set = field(default_factory=set)
    category_counts: dict = field(default_factory=dict)
    first_divergence_patterns: dict = field(default_factory=dict)
    unique_tcs_total: int = 0
    unique_tcs_passed: int = 0
    unique_tcs_failed: int = 0
    cobol_abend_count: int = 0
    cobol_clean_count: int = 0
    report_path: Path | None = None
    elapsed_seconds: float = 0.0

    @property
    def all_tests_passed(self) -> bool:
        return (
            self.mvn_returncode == 0
            and self.tests_run > 0
            and self.tests_failed == 0
            and self.tests_errors == 0
        )

    @property
    def unique_pass_rate(self) -> float:
        if self.unique_tcs_total == 0:
            return 0.0
        return 100.0 * self.unique_tcs_passed / self.unique_tcs_total


# ---------------------------------------------------------------------------
# Phase: subprocess helpers
# ---------------------------------------------------------------------------

def _run(cmd: Sequence[str], cwd: Path | None = None, *, label: str) -> int:
    """Run a subprocess, streaming output. Returns exit code; never raises."""
    log.info("[%s] $ %s", label, " ".join(str(c) for c in cmd))
    try:
        result = subprocess.run(
            list(cmd),
            cwd=str(cwd) if cwd else None,
            check=False,
        )
    except FileNotFoundError as exc:
        log.error("[%s] command not found: %s", label, exc)
        return 127
    log.info("[%s] exit=%d", label, result.returncode)
    return result.returncode


# ---------------------------------------------------------------------------
# Phase: parse JUnit Surefire/Failsafe XML
# ---------------------------------------------------------------------------

def _parse_test_reports(reports_dir: Path) -> dict:
    """Aggregate JUnit XML test reports into per-suite + per-failure stats.

    Adds rich categorisation: per-failure divergence kind (abend / displays
    / trace / final_state), unique tc_id sets for pass/fail, and the
    most-frequent first-divergence patterns.
    """
    summary = {
        "tests": 0, "failures": 0, "errors": 0, "skipped": 0,
        "by_suite": [], "failures_detail": [],
        "failed_tc_ids": set(),
        "category_counts": {
            "abend_only": 0,
            "displays_only": 0,
            "trace_only": 0,
            "final_state_only": 0,
            "displays+trace": 0,
            "abend+others": 0,
            "other_combo": 0,
        },
        "first_divergence_patterns": {},
    }
    if not reports_dir.is_dir():
        return summary
    for f in sorted(reports_dir.glob("TEST-*.xml")):
        try:
            tree = ET.parse(f)
        except ET.ParseError:
            continue
        root = tree.getroot()
        attrs = root.attrib
        try:
            t = int(attrs.get("tests", "0"))
            fails = int(attrs.get("failures", "0"))
            errs = int(attrs.get("errors", "0"))
            skipped = int(attrs.get("skipped", "0"))
        except ValueError:
            continue
        summary["tests"] += t
        summary["failures"] += fails
        summary["errors"] += errs
        summary["skipped"] += skipped
        summary["by_suite"].append({
            "suite": attrs.get("name", f.stem),
            "tests": t, "failures": fails, "errors": errs, "skipped": skipped,
        })
        for case in root.iterfind("testcase"):
            for kind in ("failure", "error"):
                node = case.find(kind)
                if node is None:
                    continue
                msg = (node.attrib.get("message") or node.text or "").strip()
                tc_match = re.search(r"tc=([0-9a-f]+)", msg)
                tc_id = tc_match.group(1) if tc_match else None
                if tc_id:
                    summary["failed_tc_ids"].add(tc_id)
                # Categorise by which divergence types appear.
                has_abend = "abended:" in msg
                has_displays = "displays differ" in msg
                has_trace = "paragraph trace differs" in msg
                has_state = "final_state[" in msg
                cnt = sum([has_abend, has_displays, has_trace, has_state])
                bucket = "other_combo"
                if has_abend and cnt > 1:
                    bucket = "abend+others"
                elif has_abend and cnt == 1:
                    bucket = "abend_only"
                elif has_displays and has_trace and not has_state:
                    bucket = "displays+trace"
                elif has_displays and cnt == 1:
                    bucket = "displays_only"
                elif has_trace and cnt == 1:
                    bucket = "trace_only"
                elif has_state and cnt == 1:
                    bucket = "final_state_only"
                summary["category_counts"][bucket] += 1
                # Capture the first divergence line for pattern grouping.
                first_div = ""
                for line in msg.split("\n"):
                    line = line.strip()
                    if line.startswith("- "):
                        first_div = line[2:].split(":", 1)[0]
                        break
                if first_div:
                    summary["first_divergence_patterns"][first_div] = (
                        summary["first_divergence_patterns"].get(first_div, 0) + 1
                    )
                summary["failures_detail"].append({
                    "case": case.attrib.get("name", "<unknown>"),
                    "kind": kind,
                    "tc_id": tc_id,
                    "category": bucket,
                    "message": msg.split("\n")[0][:240],
                })
    return summary


# ---------------------------------------------------------------------------
# Phase: equivalence report
# ---------------------------------------------------------------------------

def _write_report(result: PipelineResult) -> Path:
    """Render a markdown summary of the pipeline run.

    Surfaces the unique-tc pass rate prominently (a single test_store entry
    can be parameterised many times by JUnit, so the raw junit run count is
    misleading), categorises failures by divergence type, and lists the
    most common first-divergence patterns.
    """
    report = result.output_dir / "equivalence-report.md"
    lines: list[str] = []
    lines.append("# Specter Pipeline — Equivalence Report")
    lines.append("")
    lines.append(f"- Output directory: `{result.output_dir}`")
    lines.append(f"- Java project: `{result.project_dir}`")
    lines.append(f"- Test store: `{result.test_store_path}`")
    lines.append(f"- Snapshots: `{result.snapshot_dir}` ({result.snapshots_written} files)")
    lines.append(f"- Elapsed: {result.elapsed_seconds:.1f}s")
    lines.append("")

    # ----- Headline result -----
    lines.append("## Headline")
    lines.append("")
    if result.unique_tcs_total > 0:
        rate = result.unique_pass_rate
        bar_len = 30
        filled = int(bar_len * rate / 100.0)
        bar = "█" * filled + "░" * (bar_len - filled)
        lines.append(f"**Unique test cases: {result.unique_tcs_passed}/{result.unique_tcs_total} pass — {rate:.1f}%**")
        lines.append("")
        lines.append(f"```\n[{bar}]  {rate:.1f}%\n```")
        lines.append("")
    else:
        lines.append("_No equivalence tests ran (mvn verify skipped or failed early)._")
        lines.append("")

    # ----- Coverage from the COBOL coverage phase -----
    cov = result.coverage_report
    if cov is not None:
        lines.append("## Test data coverage (from coverage phase)")
        lines.append("")
        paras_hit = getattr(cov, "paragraphs_hit", 0)
        paras_total = getattr(cov, "paragraphs_total", 0)
        para_pct = getattr(cov, "paragraph_coverage", 0.0) * 100.0
        branches_hit = getattr(cov, "branches_hit", 0)
        branches_total = getattr(cov, "branches_total", 0)
        br_pct = getattr(cov, "branch_coverage", 0.0) * 100.0
        cov_tcs = getattr(cov, "total_test_cases", 0)
        cov_elapsed = getattr(cov, "elapsed_seconds", 0.0)
        lines.append(f"- Test cases generated: **{cov_tcs}**")
        lines.append(f"- Paragraph coverage: **{paras_hit}/{paras_total}** ({para_pct:.1f}%)")
        lines.append(f"- Branch coverage:    **{branches_hit}/{branches_total}** ({br_pct:.1f}%)")
        lines.append(f"- Coverage phase elapsed: {cov_elapsed:.1f}s")
        lines.append("")

    # ----- COBOL reference dataset shape -----
    if result.cobol_abend_count or result.cobol_clean_count:
        lines.append("## COBOL reference behaviour (across snapshots)")
        lines.append("")
        total = result.cobol_abend_count + result.cobol_clean_count
        lines.append(f"- Snapshots captured: **{total}**")
        lines.append(f"- COBOL exited cleanly (rc=0, abended=False): **{result.cobol_clean_count}**")
        lines.append(f"- COBOL abended (rc≠0): **{result.cobol_abend_count}**")
        lines.append("")

    # ----- Phase outcomes -----
    lines.append("## Phase outcomes")
    lines.append("")
    lines.append(f"- `docker compose up -d`: exit={result.docker_compose_returncode}")
    lines.append(f"- `mvn verify`: exit={result.mvn_returncode}")
    lines.append("")

    # ----- Raw test counts -----
    lines.append("## Equivalence test counts")
    lines.append("")
    lines.append(f"- Total junit runs: **{result.tests_run}**")
    lines.append(f"- Passed: **{result.tests_passed}**")
    lines.append(f"- Failed: **{result.tests_failed}**")
    lines.append(f"- Errors: **{result.tests_errors}**")
    lines.append(f"- Skipped: **{result.tests_skipped}**")
    lines.append("")

    # ----- Divergence categorisation -----
    if result.category_counts and any(result.category_counts.values()):
        lines.append("## Divergence categories")
        lines.append("")
        lines.append("Each failure is bucketed by which equivalence axes diverged.")
        lines.append("")
        lines.append("| category | failure count | description |")
        lines.append("|---|---:|---|")
        descs = {
            "abend_only": "abended flag mismatch only",
            "displays_only": "DISPLAY output strings differ",
            "trace_only": "paragraph trace order differs",
            "final_state_only": "specific COBOL variable values differ",
            "displays+trace": "displays AND trace both diverge (typically: Java reaches different paragraphs)",
            "abend+others": "abend mismatch combined with display/trace diff",
            "other_combo": "multi-axis divergence",
        }
        for cat, n in sorted(
            result.category_counts.items(), key=lambda kv: kv[1], reverse=True,
        ):
            if n == 0:
                continue
            lines.append(f"| `{cat}` | {n} | {descs.get(cat, '')} |")
        lines.append("")

    # ----- Top first-divergence patterns -----
    if result.first_divergence_patterns:
        lines.append("## Top first-divergence patterns")
        lines.append("")
        lines.append("First divergence shown to the user (one per failure).")
        lines.append("")
        lines.append("| count | first-divergence axis |")
        lines.append("|---:|---|")
        for pattern, n in sorted(
            result.first_divergence_patterns.items(),
            key=lambda kv: kv[1], reverse=True,
        )[:10]:
            lines.append(f"| {n} | `{pattern}` |")
        lines.append("")

    # ----- Passing tc_ids -----
    if result.unique_tcs_passed > 0:
        passing = sorted(_passing_tc_ids(result))
        lines.append(f"## Passing tc_ids ({len(passing)})")
        lines.append("")
        for tc in passing[:50]:
            lines.append(f"- `{tc}`")
        if len(passing) > 50:
            lines.append(f"- _(+{len(passing) - 50} more)_")
        lines.append("")

    # ----- Failing samples -----
    if result.failures:
        lines.append("## Failing test samples (first 50)")
        lines.append("")
        lines.append("| tc_id | category | first divergence |")
        lines.append("|---|---|---|")
        seen = set()
        shown = 0
        for f in result.failures:
            tc = f.get("tc_id") or "?"
            if tc in seen:
                continue
            seen.add(tc)
            lines.append(
                f"| `{tc}` | `{f.get('category', '?')}` | {f['message']} |"
            )
            shown += 1
            if shown >= 50:
                break
        lines.append("")
    else:
        lines.append("All test cases passed equivalence assertions.")
        lines.append("")

    # ----- Honest scope note -----
    lines.append("## What this report measures")
    lines.append("")
    lines.append(
        "Each failure represents a real semantic divergence between the COBOL "
        "binary's execution and the generated Java's execution **of the same "
        "test case input**. Failures are fixable in the Java code generator "
        "(and the Java runtime template) — none require editing generated "
        "Java files. Common remaining root causes:"
    )
    lines.append("")
    lines.append("- `REDEFINES` (multiple field names sharing storage)")
    lines.append("- `USAGE BINARY` / `COMP-3` width-aware semantics")
    lines.append("- COBOL picture-aware DISPLAY formatting (PIC 9 vs alpha emit different output)")
    lines.append("- COBOL string operators (STRING/UNSTRING/INSPECT)")
    lines.append("- CICS/DLI verbs not yet implemented in JdbcStubExecutor")
    lines.append("")

    report.write_text("\n".join(lines), encoding="utf-8")
    return report


def _passing_tc_ids(result: PipelineResult) -> set[str]:
    """Return the set of tc_ids that passed (unique TCs - failed TCs)."""
    all_ids: set[str] = set()
    if result.test_store_path.exists():
        with open(result.test_store_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = __import__("json").loads(line)
                except Exception:
                    continue
                if "id" in obj and not obj.get("_type"):
                    all_ids.add(str(obj["id"]))
    return all_ids - result.failed_tc_ids


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_pipeline(
    ast_path: str | Path,
    cobol_source: str | Path,
    copybook_dirs: Sequence[str | Path],
    output_dir: str | Path,
    *,
    coverage_budget: int = 5000,
    coverage_timeout: int = 1800,
    execution_timeout: int = 900,
    skip_docker: bool = False,
    skip_mvn: bool = False,
    docker_services: Sequence[str] = ("db", "rabbitmq", "wiremock"),
    llm_provider=None,
    llm_model: str | None = None,
) -> PipelineResult:
    """Run the unified pipeline end-to-end.

    Args:
        ast_path: Path to the COBOL AST JSON.
        cobol_source: Path to the COBOL source file.
        copybook_dirs: Directories containing copybooks (.cpy).
        output_dir: Project root for the generated Java + snapshots.
        coverage_budget: Max test cases to synthesize.
        coverage_timeout: Max wall-clock seconds for coverage phase.
        execution_timeout: Per-test-case execution timeout (seconds).
        skip_docker: Don't run `docker compose up`.
        skip_mvn: Don't run `mvn verify`.
        docker_services: Which sidecars to start; defaults to db + rabbitmq + wiremock.

    Returns:
        A :class:`PipelineResult` with status + diagnostics. Always returns
        even on failures; check ``mvn_returncode`` and ``failures``.
    """
    from .ast_parser import parse_ast
    from .code_generator import generate_code
    from .cobol_coverage import run_cobol_coverage
    from .cobol_executor import prepare_context
    from .cobol_snapshot import capture_snapshots
    from .java_code_generator import generate_java_project
    from .monte_carlo import _load_module
    from .variable_extractor import extract_variables

    out_root = Path(output_dir).resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    cobol_source = Path(cobol_source).resolve()
    ast_path = Path(ast_path).resolve()
    copybook_paths = [str(Path(d).resolve()) for d in copybook_dirs]

    test_store_path = out_root / "tests.jsonl"
    snapshot_dir = out_root / "cobol_snapshots"
    project_dir = out_root / "java"

    started = time.monotonic()
    result = PipelineResult(
        output_dir=out_root,
        test_store_path=test_store_path,
        snapshot_dir=snapshot_dir,
        project_dir=project_dir,
    )

    # ----- Phase 1: coverage -------------------------------------------------
    log.info("[1/6] coverage  → %s", test_store_path)
    coverage_report = run_cobol_coverage(
        ast_file=str(ast_path),
        cobol_source=str(cobol_source),
        copybook_dirs=copybook_paths,
        budget=coverage_budget,
        timeout=coverage_timeout,
        execution_timeout=execution_timeout,
        store_path=str(test_store_path),
        llm_provider=llm_provider,
        llm_model=llm_model,
    )
    result.coverage_report = coverage_report
    log.info(
        "[1/6] coverage done: %d test cases, paragraph coverage %.1f%%",
        getattr(coverage_report, "total_test_cases", 0),
        100.0 * getattr(coverage_report, "paragraph_coverage", 0.0),
    )

    # ----- Phase 2: snapshot -------------------------------------------------
    log.info("[2/6] snapshot  → %s", snapshot_dir)
    program = parse_ast(str(ast_path), cobol_source=str(cobol_source))
    var_report = extract_variables(program)
    code = generate_code(
        program, var_report, instrument=True,
        cobol_source=str(cobol_source),
    )
    py_path = out_root / f"{program.program_id}.py"
    py_path.write_text(code, encoding="utf-8")
    py_module = _load_module(py_path)

    cobol_ctx = prepare_context(
        cobol_source=str(cobol_source),
        copybook_dirs=copybook_paths,
        coverage_mode=True,
        llm_provider=llm_provider,
        llm_model=llm_model,
    )
    # Build PIC info so input_state values are truncated to COBOL field
    # widths in BOTH the Python pre-run and the COBOL binary execution.
    # Mirrors what the Java integration test does at @BeforeEach time.
    from .pic_extractor import build_pic_info
    from .copybook_parser import parse_copybook as _parse_cpy
    import os as _os
    _pic_records = []
    for d in copybook_paths:
        if not _os.path.isdir(d):
            continue
        for fname in sorted(_os.listdir(d)):
            if not fname.lower().endswith(".cpy"):
                continue
            with open(_os.path.join(d, fname)) as fh:
                rec = _parse_cpy(fh.read(), copybook_file=fname)
            if rec.fields:
                _pic_records.append(rec)
    pic_info_map = build_pic_info(_pic_records, str(cobol_source))
    from .pic_extractor import injectable_var_names
    inj_vars = injectable_var_names(program, var_report, _pic_records, str(cobol_source))

    written = capture_snapshots(
        test_store_path,
        cobol_ctx,
        snapshot_dir,
        python_module=py_module,
        timeout=execution_timeout,
        pic_info=pic_info_map,
        injectable_vars=inj_vars,
    )
    result.snapshots_written = len(written)
    log.info("[2/6] snapshot done: %d snapshots", len(written))

    # ----- Phase 3: Java generation -----------------------------------------
    log.info("[3/6] java      → %s", project_dir)
    project_dir.mkdir(parents=True, exist_ok=True)
    generate_java_project(
        program, var_report,
        output_dir=str(project_dir),
        test_store_path=str(test_store_path),
        copybook_paths=copybook_paths or None,
        docker=True,
        integration_tests=True,
        snapshot_dir=str(snapshot_dir),
        cobol_source=str(cobol_source),
    )
    log.info("[3/6] java done")

    # ----- Phase 4: docker deploy -------------------------------------------
    if skip_docker:
        log.info("[4/6] deploy    → skipped (--skip-docker)")
    else:
        log.info("[4/6] deploy    → docker compose up -d %s", " ".join(docker_services))
        rc = _run(
            ["docker", "compose", "up", "-d", *docker_services],
            cwd=project_dir,
            label="deploy",
        )
        result.docker_compose_returncode = rc
        if rc != 0:
            log.warning(
                "[4/6] deploy failed (exit=%d). Continuing to validate phase "
                "with whatever's running.", rc,
            )

    # ----- Phase 5: mvn validate --------------------------------------------
    if skip_mvn:
        log.info("[5/6] validate  → skipped (--skip-mvn)")
    else:
        # Install the parent project first so the IT module can resolve it.
        log.info("[5/6] validate  → mvn install (-DskipTests) on parent project")
        rc = _run(
            ["mvn", "-q", "install", "-DskipTests"],
            cwd=project_dir, label="install",
        )
        if rc != 0:
            log.error("[5/6] mvn install failed (exit=%d) — skipping verify", rc)
            result.mvn_returncode = rc
        else:
            log.info("[5/6] validate  → mvn verify in integration-tests/")
            it_dir = project_dir / "integration-tests"
            rc = _run(
                ["mvn", "-q", "verify"],
                cwd=it_dir,
                label="verify",
            )
            result.mvn_returncode = rc

    # ----- Phase 6: report ---------------------------------------------------
    if not skip_mvn:
        # Failsafe writes target/failsafe-reports/; Surefire writes target/surefire-reports/.
        it_dir = project_dir / "integration-tests"
        merged_categories: dict = {}
        merged_patterns: dict = {}
        for sub in ("failsafe-reports", "surefire-reports"):
            stats = _parse_test_reports(it_dir / "target" / sub)
            if stats["tests"] > 0:
                result.tests_run += stats["tests"]
                result.tests_failed += stats["failures"]
                result.tests_errors += stats["errors"]
                result.tests_skipped += stats["skipped"]
                result.failures.extend(stats["failures_detail"])
                result.failed_tc_ids.update(stats["failed_tc_ids"])
                for cat, n in stats["category_counts"].items():
                    merged_categories[cat] = merged_categories.get(cat, 0) + n
                for pattern, n in stats["first_divergence_patterns"].items():
                    merged_patterns[pattern] = merged_patterns.get(pattern, 0) + n
        result.tests_passed = max(
            0, result.tests_run - result.tests_failed - result.tests_errors - result.tests_skipped,
        )
        result.category_counts = merged_categories
        result.first_divergence_patterns = merged_patterns

    # Aggregate unique-tc and snapshot stats for the headline.
    if test_store_path.exists():
        import json as _json2
        unique_ids: set[str] = set()
        with open(test_store_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = _json2.loads(line)
                except _json2.JSONDecodeError:
                    continue
                if "id" in obj and not obj.get("_type"):
                    unique_ids.add(str(obj["id"]))
        result.unique_tcs_total = len(unique_ids)
        result.unique_tcs_failed = len(result.failed_tc_ids & unique_ids)
        result.unique_tcs_passed = result.unique_tcs_total - result.unique_tcs_failed

    if snapshot_dir.is_dir():
        import json as _json3
        for snap in snapshot_dir.glob("*.json"):
            try:
                d = _json3.loads(snap.read_text())
            except Exception:
                continue
            if d.get("abended"):
                result.cobol_abend_count += 1
            else:
                result.cobol_clean_count += 1

    result.elapsed_seconds = time.monotonic() - started
    result.report_path = _write_report(result)
    log.info("[6/6] report    → %s", result.report_path)

    # Console summary
    log.info(
        "Pipeline complete: %d junit runs, %d passed, %d failed, %d errors, %d skipped (%.1fs)",
        result.tests_run, result.tests_passed,
        result.tests_failed, result.tests_errors, result.tests_skipped,
        result.elapsed_seconds,
    )
    if result.unique_tcs_total > 0:
        log.info(
            "Unique tc_ids: %d/%d pass strict equivalence (%.1f%%)",
            result.unique_tcs_passed, result.unique_tcs_total,
            result.unique_pass_rate,
        )
    return result
