"""CLI entry point: python -m specter <ast_file> [options]."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - optional dependency
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv()

from .ast_parser import parse_ast
from .code_generator import generate_code
from .diagram import write_diagrams
from .monte_carlo import run_monte_carlo
from .static_analysis import (
    build_static_call_graph,
    extract_equality_constraints,
    extract_gating_conditions,
    extract_sequential_gates,
    augment_gating_with_sequential_gates,
)
from .variable_extractor import extract_stub_status_mapping, extract_variables


def _extract_tests(store_path: str, fmt: str) -> int:
    """Extract test cases from a JSONL test store."""
    import csv
    import io
    import json

    from .test_store import TestStore

    test_cases, _progress = TestStore.load(store_path)
    if not test_cases:
        print(f"No test cases found in {store_path}", file=sys.stderr)
        return 1

    print(f"Loaded {len(test_cases)} test cases from {store_path}", file=sys.stderr)

    if fmt == "json":
        # Full JSON array — each TC has input_state, stub_outcomes, metadata
        records = []
        for tc in test_cases:
            records.append({
                "id": tc.id,
                "input_state": tc.input_state,
                "stub_outcomes": {
                    k: [
                        [(pair[0], pair[1]) for pair in entry]
                        if isinstance(entry, list) and entry and isinstance(entry[0], (list, tuple))
                        else entry
                        for entry in v
                    ]
                    for k, v in tc.stub_outcomes.items()
                },
                "stub_defaults": {
                    k: [(pair[0], pair[1]) for pair in v]
                    if isinstance(v, list) and v and isinstance(v[0], (list, tuple))
                    else v
                    for k, v in tc.stub_defaults.items()
                },
                "paragraphs_covered": tc.paragraphs_covered,
                "branches_covered": tc.branches_covered,
                "layer": tc.layer,
                "target": tc.target,
            })
        json.dump(records, sys.stdout, indent=2, default=str)
        print()  # trailing newline

    elif fmt == "jsonl":
        # One JSON object per line — input_state only (compact)
        for tc in test_cases:
            line = json.dumps({
                "id": tc.id,
                "layer": tc.layer,
                "target": tc.target,
                "input_state": tc.input_state,
            }, default=str)
            print(line)

    elif fmt == "csv":
        # Flatten input_state to columns — one row per test case
        # Collect all variable names across all TCs
        all_vars: set[str] = set()
        for tc in test_cases:
            all_vars.update(tc.input_state.keys())
        sorted_vars = sorted(all_vars)

        writer = csv.writer(sys.stdout)
        writer.writerow(["id", "layer", "target"] + sorted_vars)
        for tc in test_cases:
            row = [tc.id, tc.layer, tc.target]
            for var in sorted_vars:
                row.append(tc.input_state.get(var, ""))
            writer.writerow(row)

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="specter",
        description="COBOL AST to executable Python code generator",
    )
    parser.add_argument(
        "ast_file", nargs="*",
        help="Path to JSON AST file(s) (.ast). Multiple files with --multi. Not needed with --run-bundle.",
    )
    parser.add_argument(
        "--output", "-o",
        help="Output Python file (default: <ast_file>.py)",
    )
    parser.add_argument(
        "--monte-carlo", "-m",
        type=int, default=0, metavar="N",
        help="Run Monte Carlo analysis with N iterations",
    )
    parser.add_argument(
        "--seed", "-s",
        type=int, default=42,
        help="Random seed for Monte Carlo (default: 42)",
    )
    parser.add_argument(
        "--verify", "-v",
        action="store_true",
        help="Verify generated code compiles",
    )
    parser.add_argument(
        "--analyze",
        action="store_true",
        help="Run dynamic analysis (implies --monte-carlo 100 if not set)",
    )
    parser.add_argument(
        "--analysis-output",
        metavar="DIR",
        help="Directory for analysis deliverables (default: /tmp)",
    )
    parser.add_argument(
        "--guided",
        action="store_true",
        help="Use coverage-guided fuzzing (implies --analyze, default 10000 iterations)",
    )
    parser.add_argument(
        "--diagram",
        action="store_true",
        help="Generate Mermaid sequence and flow diagrams (implies --analyze)",
    )
    parser.add_argument(
        "--llm-guided",
        action="store_true",
        help="Use LLM-guided coverage maximization (requires LLM provider config via env vars, implies --guided)",
    )
    parser.add_argument(
        "--llm-provider",
        metavar="NAME",
        help="LLM provider name: anthropic, openai, openrouter (default: from LLM_PROVIDER env var)",
    )
    parser.add_argument(
        "--llm-model",
        metavar="MODEL",
        help="LLM model override (default: provider default)",
    )
    parser.add_argument(
        "--llm-interval",
        type=int, default=500, metavar="N",
        help="Query LLM every N iterations for coverage suggestions (default: 500)",
    )
    parser.add_argument(
        "--llm-walk-rounds",
        type=int, default=100, metavar="N",
        help="Random walk rounds per LLM suggestion to maximize coverage (default: 100)",
    )
    parser.add_argument(
        "--concolic",
        action="store_true",
        help="Use Z3 concolic engine to solve for uncovered branches (requires z3-solver, implies --guided)",
    )
    parser.add_argument(
        "--synthesize",
        action="store_true",
        help="Synthesize a minimal test set for maximum coverage",
    )
    parser.add_argument(
        "--test-store",
        metavar="PATH",
        help="Path to test store JSONL file (default: <analysis-output>/<program>_testset.jsonl)",
    )
    parser.add_argument(
        "--synthesis-layers",
        type=int, default=5, metavar="N",
        help="Run only first N synthesis layers (default: 5)",
    )
    parser.add_argument(
        "--synthesis-timeout",
        type=int, default=None, metavar="N",
        help="Max seconds for synthesis (default: unlimited)",
    )
    parser.add_argument(
        "--exclude-values",
        metavar="PATH",
        help="Path to newline-separated values to exclude from synthesized tests",
    )
    parser.add_argument(
        "--cobol-validate",
        metavar="EXECUTABLE",
        help="Validate synthesized tests against compiled COBOL mock executable",
    )
    parser.add_argument(
        "--extract-tests",
        metavar="PATH",
        help="Extract test cases from a test store JSONL file to JSON/CSV",
    )
    parser.add_argument(
        "--extract-format",
        choices=["json", "csv", "jsonl"],
        default="json",
        help="Output format for --extract-tests (default: json)",
    )
    parser.add_argument(
        "--extract-docs",
        metavar="JSONL",
        help="Generate Markdown documentation from a test store JSONL file (requires generated .py)",
    )
    parser.add_argument(
        "--java",
        action="store_true",
        help="Generate a Maven Java project instead of Python",
    )
    parser.add_argument(
        "--java-package",
        default="com.specter.generated",
        metavar="PKG",
        help="Java package name (default: com.specter.generated)",
    )
    parser.add_argument(
        "--docker",
        action="store_true",
        help="Generate Dockerfile + docker-compose.yml (with --java)",
    )
    parser.add_argument(
        "--integration-tests",
        action="store_true",
        help="Generate Mockito integration tests (with --java)",
    )
    parser.add_argument(
        "--multi",
        action="store_true",
        help="Multi-program XCTL routing: generate all AST files into one project (with --java)",
    )
    parser.add_argument(
        "--mock-cobol",
        action="store_true",
        help="Instrument COBOL source for standalone mock execution (input is .cbl/.cob/.cobol)",
    )
    parser.add_argument(
        "--copybook-dir",
        action="append",
        default=[],
        metavar="DIR",
        help="Copybook directory for --mock-cobol (can repeat)",
    )
    parser.add_argument(
        "--init-var",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="Set initial variable value for --mock-cobol (can repeat)",
    )
    parser.add_argument(
        "--cobol-coverage",
        action="store_true",
        help="Run coverage-guided test generation against real COBOL (GnuCOBOL)",
    )
    parser.add_argument(
        "--cobol-source",
        metavar="PATH",
        help="Path to COBOL source file (.cbl) for --cobol-coverage",
    )
    parser.add_argument(
        "--coverage-budget",
        type=int, default=5000, metavar="N",
        help="Max test cases to generate for --cobol-coverage (default: 5000)",
    )
    parser.add_argument(
        "--coverage-timeout",
        type=int, default=1800, metavar="N",
        help="Max seconds for --cobol-coverage (default: 1800)",
    )
    parser.add_argument(
        "--coverage-execution-timeout",
        type=int, default=900, metavar="N",
        help="Per-test COBOL execution timeout in seconds (default: 900)",
    )
    parser.add_argument(
        "--coverage-rounds",
        type=int, default=0, metavar="N",
        help="Max strategy rounds for coverage loop (default: 0 = unlimited)",
    )
    parser.add_argument(
        "--coverage-batch-size",
        type=int, default=200, metavar="N",
        help="Cases per strategy round (default: 200)",
    )
    parser.add_argument(
        "--strict-branch-coverage",
        action="store_true",
        help="Fail fast for --cobol-coverage when no branch probes are generated",
    )
    parser.add_argument(
        "--cobol-validate-store",
        metavar="JSONL",
        help="Validate a test store against compiled COBOL (requires --cobol-source, --copybook-dir)",
    )
    parser.add_argument(
        "--coverage-config",
        metavar="PATH",
        help="YAML config file for strategy pipeline (strategy order, batch sizes, termination)",
    )
    parser.add_argument(
        "--export-bundle",
        metavar="DIR",
        help="Export portable coverage bundle (binary + spec) to directory",
    )
    parser.add_argument(
        "--run-bundle",
        metavar="DIR",
        help="Run coverage from an exported bundle (no AST/source/copybooks needed)",
    )
    parser.add_argument(
        "--obfuscate",
        action="store_true",
        help="Obfuscate all names in exported bundle for IP protection (with --export-bundle)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug-level logging (shows paragraph/field targeting details)",
    )

    args = parser.parse_args(argv)

    # --extract-tests: standalone operation, no AST needed
    if args.extract_tests:
        return _extract_tests(args.extract_tests, args.extract_format)

    # --run-bundle: standalone operation, no AST needed
    if args.run_bundle:
        logging.basicConfig(
            level=logging.DEBUG if args.debug else logging.INFO,
            format="%(asctime)s %(levelname)-7s %(message)s",
            datefmt="%H:%M:%S",
            stream=sys.stderr,
            force=True,
        )

        cov_config = None
        if args.coverage_config:
            from .coverage_config import load_config
            cov_config = load_config(args.coverage_config)

        llm_prov = None
        if args.llm_provider:
            from .llm_coverage import get_llm_provider
            try:
                llm_prov = get_llm_provider(
                    provider_name=args.llm_provider, model=args.llm_model,
                )
            except Exception:
                pass

        from .coverage_bundle import run_bundle
        store = Path(args.test_store) if args.test_store else None
        print(f"Running coverage from bundle: {args.run_bundle}/")
        try:
            cov_report = run_bundle(
                bundle_dir=args.run_bundle,
                store_path=store,
                budget=args.coverage_budget,
                timeout=args.coverage_timeout,
                seed=args.seed,
                coverage_config=cov_config,
                llm_provider=llm_prov,
                llm_model=args.llm_model,
            )
        except RuntimeError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 2
        print()
        print(cov_report.summary())
        return 0

    # --extract-docs: needs generated .py (ast_file used as .py path) + JSONL
    if args.extract_docs:
        from .doc_generator import generate_docs
        # The ast_file arg doubles as the generated .py path for --extract-docs
        py_path = Path(args.ast_file[0])
        if not py_path.exists():
            # Try .py extension
            py_path = py_path.with_suffix(".py")
        if not py_path.exists():
            print(f"Error: generated module not found: {py_path}", file=sys.stderr)
            return 1
        print(f"Generating documentation from {args.extract_docs} ...", file=sys.stderr)
        md = generate_docs(py_path, args.extract_docs)
        print(md)
        return 0

    # --multi --java: multi-program XCTL routing project
    if args.multi:
        if not args.java:
            print("Error: --multi requires --java", file=sys.stderr)
            return 1
        if not args.output:
            print("Error: --multi requires -o <output_dir>", file=sys.stderr)
            return 1
        # Validate all AST files exist
        for ast_file in args.ast_file:
            if not Path(ast_file).exists():
                print(f"Error: AST file not found: {ast_file}", file=sys.stderr)
                return 1

        from .java_code_generator import generate_multi_program_project

        per_program_stores: dict[str, str] | None = None
        output_dir = Path(args.output)

        if args.synthesize:
            import tempfile

            logging.basicConfig(
                level=logging.DEBUG if args.debug else logging.INFO,
                format="%(asctime)s %(levelname)-7s %(message)s",
                datefmt="%H:%M:%S",
                stream=sys.stderr,
                force=True,
            )

            analysis_dir = (
                Path(args.analysis_output) if args.analysis_output
                else output_dir / "test-data"
            )
            analysis_dir.mkdir(parents=True, exist_ok=True)
            per_program_stores = {}

            excluded_values: set[str] | None = None
            if args.exclude_values:
                exclude_path = Path(args.exclude_values)
                if not exclude_path.exists():
                    print(f"Error: exclude-values file not found: {exclude_path}", file=sys.stderr)
                    return 1
                excluded_values = {
                    line.strip()
                    for line in exclude_path.read_text().splitlines()
                    if line.strip() and not line.strip().startswith("#")
                }

            llm_provider_for_synth = None
            if args.llm_guided or args.llm_provider:
                from .llm_coverage import get_llm_provider
                try:
                    llm_provider_for_synth = get_llm_provider(
                        provider_name=args.llm_provider, model=args.llm_model,
                    )
                    print(f"  LLM provider: {type(llm_provider_for_synth).__name__}")
                except Exception as e:
                    print(f"  Warning: LLM init failed: {e}", file=sys.stderr)

            from .cobol_coverage import run_coverage

            with tempfile.TemporaryDirectory(prefix="specter_synth_") as tmpdir:
                tmpdir_path = Path(tmpdir)

                cov_timeout = args.synthesis_timeout or args.coverage_timeout

                # Phase 1: run strategy-based coverage per program
                for ast_file in args.ast_file:
                    ast_path = Path(ast_file)
                    program = parse_ast(ast_path)
                    program_id = program.program_id

                    print(f"\n--- Synthesizing {program_id} ---")
                    print(f"  Paragraphs: {len(program.paragraphs)}")

                    store_path = analysis_dir / f"{program_id}_testset.jsonl"

                    # Load coverage config if provided
                    multi_cov_config = None
                    if args.coverage_config:
                        from .coverage_config import load_config as _load_cov_config
                        multi_cov_config = _load_cov_config(args.coverage_config)

                    try:
                        cov_report = run_coverage(
                            ast_file=ast_path,
                            budget=args.coverage_budget,
                            timeout=cov_timeout,
                            store_path=store_path,
                            seed=args.seed,
                            llm_provider=llm_provider_for_synth,
                            llm_model=args.llm_model,
                            max_rounds=args.coverage_rounds,
                            batch_size=args.coverage_batch_size,
                            coverage_config=multi_cov_config,
                        )
                    except RuntimeError as e:
                        print(f"Error: {e}", file=sys.stderr)
                        return 2
                    print(cov_report.summary())
                    per_program_stores[program_id] = str(store_path)

                # Phase 2: generate catalog
                from .code_generator import generate_code as _gen_code

                catalog_sections: list[str] = []
                for ast_file in args.ast_file:
                    ast_path = Path(ast_file)
                    program = parse_ast(ast_path)
                    var_report = extract_variables(program)
                    program_id = program.program_id
                    if program_id in per_program_stores:
                        # Generate .py for catalog (lightweight, no execution)
                        code = _gen_code(program, var_report, instrument=True)
                        py_path = tmpdir_path / f"{program_id}.py"
                        py_path.write_text(code)
                        store_path = per_program_stores[program_id]
                        from .paragraph_catalog import generate_paragraph_catalog
                        try:
                            catalog_md = generate_paragraph_catalog(
                                py_path, store_path, program,
                            )
                            catalog_sections.append(
                                f"# {program_id}\n\n{catalog_md}"
                            )
                        except Exception as e:
                            print(f"  Warning: catalog generation failed "
                                  f"for {program_id}: {e}", file=sys.stderr)

                if catalog_sections:
                    combined = "\n\n---\n\n".join(catalog_sections)
                    catalog_path = analysis_dir / "tests.catalog.md"
                    catalog_path.write_text(combined)
                    print(f"\nCatalog: {catalog_path}")

        print(f"\nGenerating multi-program Java project → {output_dir}/ ...")
        print(f"  Programs: {len(args.ast_file)}")
        project_path = generate_multi_program_project(
            ast_paths=args.ast_file,
            output_dir=str(output_dir),
            per_program_stores=per_program_stores,
        )
        print(f"  Project: {project_path}")
        return 0

    if not args.ast_file:
        if not args.run_bundle:
            print("Error: AST file required (unless using --run-bundle)", file=sys.stderr)
            return 1
        # --run-bundle doesn't need AST — handled above, but check ordering
        pass
    source_path = Path(args.ast_file[0]) if args.ast_file else Path(".")
    cobol_suffixes = {".cbl", ".cob", ".cobol"}

    # Convenience auto-detect: treat .cbl/.cob input as mock mode when related
    # flags are present (or output is a COBOL file), so older invocation patterns
    # still work.
    cbl_path = Path(args.ast_file[0])
    if not args.mock_cobol and cbl_path.suffix.lower() in cobol_suffixes:
        output_looks_cobol = bool(args.output and Path(args.output).suffix.lower() in cobol_suffixes)
        if args.copybook_dir or args.init_var or output_looks_cobol:
            args.mock_cobol = True
            print(
                "Info: COBOL source detected; enabling --mock-cobol automatically.",
                file=sys.stderr,
            )

    # --mock-cobol: instrument COBOL source for mock execution
    if args.mock_cobol:
        from .cobol_mock import instrument_cobol, MockConfig

        if cbl_path.suffix.lower() not in cobol_suffixes:
            print(
                f"Error: --mock-cobol expects a COBOL source (.cbl/.cob/.cobol), got: {source_path}",
                file=sys.stderr,
            )
            return 1
        if not source_path.exists():
            print(f"Error: COBOL source not found: {source_path}", file=sys.stderr)
            return 1

        init_values: dict[str, str] = {}
        for item in args.init_var:
            if "=" not in item:
                print(f"Error: --init-var requires NAME=VALUE, got: {item}", file=sys.stderr)
                return 1
            name, value = item.split("=", 1)
            name = name.strip().upper()
            if not name:
                print(f"Error: --init-var has empty variable name: {item}", file=sys.stderr)
                return 1
            init_values[name] = value

        copybook_dirs = [Path(d) for d in args.copybook_dir]
        cfg = MockConfig(copybook_dirs=copybook_dirs, initial_values=init_values)

        output_path = Path(args.output) if args.output else source_path.with_suffix(".mock.cbl")

        print(f"Instrumenting COBOL {source_path} ...")
        result = instrument_cobol(source_path, cfg)
        output_path.write_text(result.source)

        print(f"  Written {output_path}")
        print(f"  EXEC blocks replaced: {result.exec_blocks_replaced}")
        print(f"  I/O verbs replaced: {result.io_verbs_replaced}")
        print(f"  CALL statements replaced: {result.call_stmts_replaced}")
        print(f"  Paragraphs traced: {result.paragraphs_traced}")
        print(f"  COPY resolved: {result.copy_resolved} (stubbed: {result.copy_stubbed})")
        if result.warnings:
            print("  Warnings:")
            for w in result.warnings[:20]:
                print(f"    - {w}")
            if len(result.warnings) > 20:
                print(f"    - ... and {len(result.warnings) - 20} more")
        return 0

    # --export-bundle: export portable coverage bundle
    if args.export_bundle:
        if not args.cobol_source:
            print("Error: --export-bundle requires --cobol-source PATH", file=sys.stderr)
            return 1

        logging.basicConfig(
            level=logging.DEBUG if args.debug else logging.INFO,
            format="%(asctime)s %(levelname)-7s %(message)s",
            datefmt="%H:%M:%S",
            stream=sys.stderr,
            force=True,
        )

        llm_prov = None
        if args.llm_provider:
            from .llm_coverage import get_llm_provider
            try:
                llm_prov = get_llm_provider(
                    provider_name=args.llm_provider, model=args.llm_model,
                )
                print(f"  LLM provider: {type(llm_prov).__name__}")
            except Exception as e:
                print(f"  Warning: LLM init failed: {e}", file=sys.stderr)

        from .coverage_bundle import export_bundle
        print(f"Exporting coverage bundle → {args.export_bundle}/")
        try:
            analysis_dir = Path(args.analysis_output) if args.analysis_output else Path(".")
            bundle_dir = export_bundle(
                ast_file=source_path,
                cobol_source=Path(args.cobol_source),
                copybook_dirs=[Path(d) for d in args.copybook_dir],
                output_dir=args.export_bundle,
                llm_provider=llm_prov,
                llm_model=args.llm_model,
                obfuscate=args.obfuscate,
                mapping_output_dir=analysis_dir,
            )
            print(f"Bundle exported: {bundle_dir}")
        except RuntimeError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 2
        return 0

    # --cobol-validate-store: validate a Python-generated test store against COBOL
    if args.cobol_validate_store:
        if not args.cobol_source:
            print("Error: --cobol-validate-store requires --cobol-source PATH", file=sys.stderr)
            return 1
        cobol_path = Path(args.cobol_source)
        if not cobol_path.exists():
            print(f"Error: COBOL source not found: {cobol_path}", file=sys.stderr)
            return 1
        store_path = Path(args.cobol_validate_store)
        if not store_path.exists():
            print(f"Error: test store not found: {store_path}", file=sys.stderr)
            return 1

        logging.basicConfig(
            level=logging.DEBUG if args.debug else logging.INFO,
            format="%(asctime)s %(levelname)-7s %(message)s",
            datefmt="%H:%M:%S",
            stream=sys.stderr,
            force=True,
        )

        from .cobol_validate import validate_store
        validated_path = store_path.with_suffix(".validated.jsonl")
        report = validate_store(
            ast_file=source_path,
            cobol_source=cobol_path,
            copybook_dirs=[Path(d) for d in args.copybook_dir],
            store_path=store_path,
            output_path=validated_path,
        )
        print()
        print(report)
        print(f"\nValidated store: {validated_path}")
        return 0

    # --cobol-coverage: coverage-guided test generation against real COBOL
    if args.cobol_coverage:
        if not args.cobol_source:
            print("Error: --cobol-coverage requires --cobol-source PATH", file=sys.stderr)
            return 1
        cobol_path = Path(args.cobol_source)
        if not cobol_path.exists():
            print(f"Error: COBOL source not found: {cobol_path}", file=sys.stderr)
            return 1

        logging.basicConfig(
            level=logging.DEBUG if args.debug else logging.INFO,
            format="%(asctime)s %(levelname)-7s %(message)s",
            datefmt="%H:%M:%S",
            stream=sys.stderr,
            force=True,
        )

        from .cobol_coverage import run_cobol_coverage

        analysis_dir = Path(args.analysis_output) if args.analysis_output else Path("/tmp")
        analysis_dir.mkdir(parents=True, exist_ok=True)

        if args.test_store:
            cov_store = Path(args.test_store)
        else:
            cov_store = analysis_dir / f"{source_path.stem}_cobol_testset.jsonl"

        # LLM provider is mandatory for --cobol-coverage (used for compilation
        # fixes, seed generation, and runtime strategies). Reads from .env.
        from .llm_coverage import get_llm_provider
        try:
            llm_provider_for_cov = get_llm_provider(
                provider_name=args.llm_provider, model=args.llm_model,
            )
            print(f"  LLM provider: {type(llm_provider_for_cov).__name__}")
        except Exception as e:
            print(f"Error: LLM provider required for --cobol-coverage: {e}", file=sys.stderr)
            print("  Configure LLM_PROVIDER in .env or pass --llm-provider", file=sys.stderr)
            return 1

        # Load coverage config if provided
        cov_config = None
        if args.coverage_config:
            from .coverage_config import load_config
            cov_config = load_config(args.coverage_config)
            print(f"  Config:  {args.coverage_config}")

        print(f"Running COBOL coverage-guided test generation ...")
        print(f"  AST:    {source_path}")
        print(f"  COBOL:  {cobol_path}")
        print(f"  Budget: {args.coverage_budget} TCs, timeout {args.coverage_timeout}s")
        print(f"  Per-test COBOL timeout: {args.coverage_execution_timeout}s")
        print(f"  Store:  {cov_store}")

        try:
            cov_report = run_cobol_coverage(
                ast_file=source_path,
                cobol_source=cobol_path,
                copybook_dirs=[Path(d) for d in args.copybook_dir],
                budget=args.coverage_budget,
                timeout=args.coverage_timeout,
                execution_timeout=args.coverage_execution_timeout,
                store_path=cov_store,
                seed=args.seed,
                llm_provider=llm_provider_for_cov,
                llm_model=args.llm_model,
                max_rounds=args.coverage_rounds,
                batch_size=args.coverage_batch_size,
                strict_branch_coverage=args.strict_branch_coverage,
                coverage_config=cov_config,
            )
        except RuntimeError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 2
        print()
        print(cov_report.summary())
        print(f"\nTest store: {cov_store}")
        return 0

    if args.init_var and not args.mock_cobol:
        print(
            "Error: --init-var requires --mock-cobol (or a .cbl input with mock mode).",
            file=sys.stderr,
        )
        return 1
    if args.copybook_dir and not args.mock_cobol and not args.java and not args.cobol_coverage and not args.synthesize:
        print(
            "Error: --copybook-dir requires --mock-cobol, --java, --cobol-coverage, or --synthesize.",
            file=sys.stderr,
        )
        return 1

    # --synthesize implies --analyze; validate required inputs early
    if args.synthesize:
        if not args.cobol_source:
            print("Error: --synthesize requires --cobol-source PATH", file=sys.stderr)
            return 1
        if not Path(args.cobol_source).exists():
            print(f"Error: COBOL source not found: {args.cobol_source}", file=sys.stderr)
            return 1

        logging.basicConfig(
            level=logging.DEBUG if args.debug else logging.INFO,
            format="%(asctime)s %(levelname)-7s %(message)s",
            datefmt="%H:%M:%S",
            stream=sys.stderr,
            force=True,
        )

        # Verify LLM connection before doing any work
        import concurrent.futures

        from .llm_coverage import _query_llm_sync, get_llm_provider
        try:
            _synth_llm = get_llm_provider(
                provider_name=args.llm_provider, model=args.llm_model,
            )
            print(f"  LLM provider: {type(_synth_llm).__name__}")
            # Ping with 15s timeout to catch hanging connections
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                fut = pool.submit(_query_llm_sync, _synth_llm, "ping", args.llm_model)
                fut.result(timeout=15)
            print("  LLM connection: OK")
        except concurrent.futures.TimeoutError:
            print("Error: LLM connection timed out (15s)", file=sys.stderr)
            return 1
        except Exception as e:
            print(f"Error: LLM connection required for --synthesize: {e}", file=sys.stderr)
            return 1

        args.analyze = True

    # --diagram implies --analyze
    if args.diagram:
        args.analyze = True

    # --concolic implies --guided
    if args.concolic:
        args.guided = True
        logging.basicConfig(
            level=logging.DEBUG if args.debug else logging.INFO,
            format="%(asctime)s %(levelname)-7s %(message)s",
            datefmt="%H:%M:%S",
            stream=sys.stderr,
            force=True,
        )
        try:
            import z3  # noqa: F401
        except ImportError:
            print("Error: --concolic requires z3-solver (pip install z3-solver)", file=sys.stderr)
            return 1

    # --llm-guided implies --guided (unless --synthesize handles it separately)
    if args.llm_guided and not args.synthesize:
        args.guided = True

    # --guided implies --analyze and a higher default iteration count
    if args.guided:
        args.analyze = True
        if not args.monte_carlo:
            args.monte_carlo = 10000

    # --analyze implies --monte-carlo
    if args.analyze and not args.monte_carlo:
        args.monte_carlo = 100

    ast_path = source_path
    if not ast_path.exists():
        print(f"Error: AST file not found: {ast_path}", file=sys.stderr)
        return 1

    if ".py" in ast_path.suffixes:
        print(
            "Error: expected a JSON AST (.ast). You provided a generated Python module. "
            "Use the .ast file from your parser, or use --extract-docs for .py inputs.",
            file=sys.stderr,
        )
        return 1

    # Determine output path
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = ast_path.with_suffix(".py")

    # Parse AST
    print(f"Parsing {ast_path} ...")
    program = parse_ast(ast_path)
    print(f"  Program: {program.program_id}")
    print(f"  Paragraphs: {len(program.paragraphs)}")

    # Extract variables
    var_report = extract_variables(program)
    print(f"  Variables: {len(var_report.variables)}")
    print(f"    Input: {len(var_report.input_vars)}")
    print(f"    Internal: {len(var_report.internal_vars)}")
    print(f"    Status: {len(var_report.status_vars)}")
    print(f"    Flags: {len(var_report.flag_vars)}")

    # Java project generation
    if args.java:
        from .java_code_generator import generate_java_project
        java_dir = output_path.with_suffix("")  # e.g. examples/COPAUA0C
        test_store = Path(args.test_store) if args.test_store else None
        copybook_paths = [str(Path(d)) for d in args.copybook_dir] or None
        print(f"Generating Java project → {java_dir}/ ...")
        project_path = generate_java_project(
            program, var_report, str(java_dir),
            instrument=args.analyze,
            test_store_path=str(test_store) if test_store else None,
            copybook_paths=copybook_paths,
            docker=args.docker,
            integration_tests=args.integration_tests,
        )
        n_paras = len(program.paragraphs)
        print(f"  {n_paras} paragraph classes generated")
        print(f"  Project: {project_path}")
        if args.docker:
            print("  Docker: Dockerfile + docker-compose.yml generated")
        if args.integration_tests:
            print("  Integration tests: integration-tests/ generated")
        if copybook_paths:
            print("  SQL: sql/init.sql generated from copybooks")
        return 0

    # Generate code
    copybook_records = None
    if args.copybook_dir:
        from .variable_domain import load_copybooks
        copybook_records = load_copybooks([Path(d) for d in args.copybook_dir])
    print(f"Generating {output_path} ...")
    cobol_src = getattr(args, 'cobol_source', None)
    code = generate_code(program, var_report, instrument=args.analyze,
                         copybook_records=copybook_records,
                         cobol_source=cobol_src)
    output_path.write_text(code)
    print(f"  Written {len(code)} bytes")

    # Verify compilation
    if args.verify or args.monte_carlo:
        print("Verifying compilation ...")
        try:
            compile(code, str(output_path), "exec")
            print("  Compilation OK")
        except SyntaxError as e:
            print(f"  Compilation FAILED: {e}", file=sys.stderr)
            return 1

    # Static analysis + stub mapping (when guided or analyze)
    call_graph = None
    gating_conds = None
    stub_mapping = None
    eq_constraints = None
    if args.guided or args.analyze:
        call_graph = build_static_call_graph(program)
        gating_conds = extract_gating_conditions(program, call_graph)
        stub_mapping = extract_stub_status_mapping(program, var_report)
        print(f"  Reachable: {len(call_graph.reachable)}/{len(call_graph.all_paragraphs)}")
        if stub_mapping:
            print(f"  Stub mappings: {len(stub_mapping)} operations")

        # Sequential gate detection
        seq_gates = extract_sequential_gates(program)
        if seq_gates:
            print(f"  Sequential gates detected: {len(seq_gates)}")
            for sg in seq_gates:
                print(f"    {sg.paragraph}: {sg.gate_count} gates")
            gating_conds = augment_gating_with_sequential_gates(
                gating_conds, seq_gates, call_graph,
            )

        # Equality constraint detection
        eq_constraints = extract_equality_constraints(program)
        if eq_constraints:
            print(f"  Equality constraints: {len(eq_constraints)}")

    # Synthesis mode
    if args.synthesize:
        from .cobol_coverage import run_coverage

        cobol_src = Path(args.cobol_source)

        analysis_dir = Path(args.analysis_output) if args.analysis_output else Path("/tmp")
        analysis_dir.mkdir(parents=True, exist_ok=True)

        if args.test_store:
            test_store_path = Path(args.test_store)
        else:
            test_store_path = analysis_dir / f"{ast_path.stem}_testset.jsonl"

        llm_provider_for_synth = _synth_llm  # validated at startup

        budget = args.coverage_budget
        cov_timeout = args.synthesis_timeout or args.coverage_timeout

        print(f"Synthesizing test set → {test_store_path} ...")
        print(f"  Budget: {budget} TCs, timeout {cov_timeout}s")
        # Load coverage config if provided
        synth_cov_config = None
        if args.coverage_config:
            from .coverage_config import load_config
            synth_cov_config = load_config(args.coverage_config)

        try:
            cov_report = run_coverage(
                ast_file=ast_path,
                copybook_dirs=[Path(d) for d in args.copybook_dir],
                cobol_source=cobol_src,
                budget=budget,
                timeout=cov_timeout,
                store_path=test_store_path,
                seed=args.seed,
                llm_provider=llm_provider_for_synth,
                llm_model=args.llm_model,
                max_rounds=args.coverage_rounds,
                batch_size=args.coverage_batch_size,
                coverage_config=synth_cov_config,
            )
        except RuntimeError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 2
        print()
        print(cov_report.summary())
        print(f"\nTest store: {test_store_path}")
        return 0

    # Monte Carlo
    llm_provider_instance = None
    if args.monte_carlo:
        # Set up LLM provider if --llm-guided
        if args.llm_guided:
            from .llm_coverage import get_llm_provider
            try:
                llm_provider_instance = get_llm_provider(
                    provider_name=args.llm_provider,
                    model=args.llm_model,
                )
                print(f"  LLM provider: {type(llm_provider_instance).__name__}")
            except Exception as e:
                print(f"  Warning: LLM provider init failed: {e}", file=sys.stderr)
                print("  Continuing with standard guided mode", file=sys.stderr)

        print(f"Running Monte Carlo ({args.monte_carlo} iterations, seed={args.seed}) ...")
        all_para_names = [p.name for p in program.paragraphs]
        report = run_monte_carlo(
            output_path,
            n_iterations=args.monte_carlo,
            seed=args.seed,
            var_report=var_report,
            instrument=args.analyze,
            all_paragraphs=all_para_names,
            guided=args.guided,
            call_graph=call_graph,
            gating_conditions=gating_conds,
            stub_mapping=stub_mapping,
            equality_constraints=eq_constraints,
            program=program,
            llm_provider=llm_provider_instance,
            llm_model=args.llm_model,
            llm_interval=args.llm_interval,
            llm_walk_rounds=args.llm_walk_rounds,
            concolic=args.concolic,
        )
        print()
        print(report.summary())

        if args.analyze and report.analysis_report is not None:
            analysis_text = report.analysis_report.summary()
            print()
            print(analysis_text)

            # Write analysis report to file
            analysis_dir = Path(args.analysis_output) if args.analysis_output else Path("/tmp")
            analysis_dir.mkdir(parents=True, exist_ok=True)
            report_file = analysis_dir / f"{ast_path.stem}_analysis.txt"
            report_file.write_text(analysis_text + "\n")
            print(f"\nAnalysis report written to {report_file}")

        # Generate diagrams
        if args.diagram and args.analyze:
            analysis_dir = Path(args.analysis_output) if args.analysis_output else Path("/tmp")

            # Collect call events from iterations
            all_call_events = report.sample_call_events or []
            if not all_call_events:
                # Fall back to non-guided iteration data
                for it in report.iterations:
                    if it.call_events:
                        all_call_events.append(it.call_events)

            if all_call_events:
                # Use first sample for single-iteration diagrams
                first_events = all_call_events[0]
                created = write_diagrams(
                    first_events,
                    analysis_dir,
                    ast_path.stem,
                    all_iterations_events=all_call_events,
                )
                print(f"\nDiagrams generated:")
                for path in created:
                    print(f"  {path}")
            else:
                print("\nNo call events captured for diagrams (run with --analyze)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
