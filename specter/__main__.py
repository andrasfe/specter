"""CLI entry point: python -m specter <ast_file> [options]."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .ast_parser import parse_ast
from .code_generator import generate_code
from .monte_carlo import run_monte_carlo
from .variable_extractor import extract_variables


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

    args = parser.parse_args(argv)

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
    code = generate_code(program, var_report)
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

    # Monte Carlo
    if args.monte_carlo:
        print(f"Running Monte Carlo ({args.monte_carlo} iterations, seed={args.seed}) ...")
        report = run_monte_carlo(
            output_path,
            n_iterations=args.monte_carlo,
            seed=args.seed,
            var_report=var_report,
        )
        print()
        print(report.summary())

    return 0


if __name__ == "__main__":
    sys.exit(main())
