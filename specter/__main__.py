"""CLI entry point: python -m specter <ast_file> [options]."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

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
    parser.add_argument("ast_file", help="Path to JSON AST file (.ast)")
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
        metavar="FILE",
        help="File with values to exclude from synthesis (one per line)",
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
        "--paragraph-catalog",
        metavar="JSONL",
        help="Generate paragraph catalog from a test store JSONL file (requires generated .py)",
    )
    parser.add_argument(
        "--mock-cobol",
        action="store_true",
        help="Instrument COBOL source for standalone mock execution (input is .cbl file)",
    )
    parser.add_argument(
        "--copybook-dir",
        action="append",
        metavar="DIR",
        help="Copybook directory for --mock-cobol (can repeat)",
    )

    args = parser.parse_args(argv)

    # --extract-tests: standalone operation, no AST needed
    if args.extract_tests:
        return _extract_tests(args.extract_tests, args.extract_format)

    # --extract-docs: needs generated .py (ast_file used as .py path) + JSONL
    if args.extract_docs:
        from .doc_generator import generate_docs
        # The ast_file arg doubles as the generated .py path for --extract-docs
        py_path = Path(args.ast_file)
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

    # --paragraph-catalog: needs generated .py + JSONL
    if args.paragraph_catalog:
        from .paragraph_catalog import generate_paragraph_catalog
        py_path = Path(args.ast_file)
        if not py_path.exists():
            py_path = py_path.with_suffix(".py")
        if not py_path.exists():
            print(f"Error: generated module not found: {py_path}", file=sys.stderr)
            return 1
        print(f"Generating paragraph catalog from {args.paragraph_catalog} ...", file=sys.stderr)
        md = generate_paragraph_catalog(py_path, args.paragraph_catalog)
        print(md)
        return 0

    # --mock-cobol: instrument COBOL source for mock execution
    if args.mock_cobol:
        from .cobol_mock import instrument_cobol, MockConfig
        cbl_path = Path(args.ast_file)
        if not cbl_path.exists():
            print(f"Error: COBOL file not found: {cbl_path}", file=sys.stderr)
            return 1
        cfg = MockConfig()
        if args.copybook_dir:
            cfg.copybook_dirs = [Path(d) for d in args.copybook_dir]
        print(f"Instrumenting {cbl_path} ...", file=sys.stderr)
        result = instrument_cobol(cbl_path, cfg)
        out_path = Path(args.output) if args.output else cbl_path.with_suffix(".mock.cbl")
        out_path.write_text(result.source)
        print(f"  EXEC blocks replaced: {result.exec_blocks_replaced}", file=sys.stderr)
        print(f"  I/O verbs replaced: {result.io_verbs_replaced}", file=sys.stderr)
        print(f"  CALL stmts replaced: {result.call_stmts_replaced}", file=sys.stderr)
        print(f"  Paragraphs traced: {result.paragraphs_traced}", file=sys.stderr)
        print(f"  COPYs resolved: {result.copy_resolved}", file=sys.stderr)
        print(f"  COPYs stubbed: {result.copy_stubbed}", file=sys.stderr)
        if result.warnings:
            for w in result.warnings:
                print(f"  Warning: {w}", file=sys.stderr)
        print(f"Output: {out_path}", file=sys.stderr)
        return 0

    # --synthesize implies --analyze
    if args.synthesize:
        args.analyze = True
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)-7s %(message)s",
            datefmt="%H:%M:%S",
            stream=sys.stderr,
            force=True,
        )

    # --diagram implies --analyze
    if args.diagram:
        args.analyze = True

    # --concolic implies --guided
    if args.concolic:
        args.guided = True
        logging.basicConfig(
            level=logging.INFO,
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

    # --llm-guided implies --guided
    if args.llm_guided:
        args.guided = True

    # --guided implies --analyze and a higher default iteration count
    if args.guided:
        args.analyze = True
        if not args.monte_carlo:
            args.monte_carlo = 10000

    # --analyze implies --monte-carlo
    if args.analyze and not args.monte_carlo:
        args.monte_carlo = 100

    ast_path = Path(args.ast_file)
    if not ast_path.exists():
        print(f"Error: AST file not found: {ast_path}", file=sys.stderr)
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

    # Generate code
    print(f"Generating {output_path} ...")
    code = generate_code(program, var_report, instrument=args.analyze)
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
        from .monte_carlo import _load_module
        from .test_synthesis import synthesize_test_set

        module = _load_module(output_path)

        analysis_dir = Path(args.analysis_output) if args.analysis_output else Path("/tmp")
        analysis_dir.mkdir(parents=True, exist_ok=True)

        if args.test_store:
            test_store_path = Path(args.test_store)
        else:
            test_store_path = analysis_dir / f"{ast_path.stem}_testset.jsonl"

        # Load excluded values if provided
        excluded_values = None
        if args.exclude_values:
            ev_path = Path(args.exclude_values)
            if not ev_path.exists():
                print(f"Error: exclude-values file not found: {ev_path}", file=sys.stderr)
                return 1
            excluded_values = set()
            for line in ev_path.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    excluded_values.add(line)
            print(f"  Excluding {len(excluded_values)} values from synthesis")

        print(f"Synthesizing test set → {test_store_path} ...")
        synth_report = synthesize_test_set(
            module=module,
            program=program,
            var_report=var_report,
            call_graph=call_graph,
            gating_conditions=gating_conds,
            stub_mapping=stub_mapping,
            equality_constraints=eq_constraints,
            store_path=test_store_path,
            max_time_seconds=args.synthesis_timeout,
            max_layers=args.synthesis_layers,
            excluded_values=excluded_values,
        )
        print()
        print(synth_report.summary())
        print(f"\nTest store: {test_store_path}")

        # Auto-generate paragraph catalog
        from .paragraph_catalog import generate_paragraph_catalog
        try:
            catalog_md = generate_paragraph_catalog(output_path, test_store_path, program)
            catalog_path = test_store_path.with_suffix(".catalog.md")
            catalog_path.write_text(catalog_md)
            print(f"Paragraph catalog: {catalog_path}")
        except Exception as e:
            print(f"Warning: catalog generation failed: {e}", file=sys.stderr)

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
