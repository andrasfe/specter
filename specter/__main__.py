"""CLI entry point: python -m specter <ast_file> [options]."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

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

    args = parser.parse_args(argv)

    # --diagram implies --analyze
    if args.diagram:
        args.analyze = True

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
