#!/usr/bin/env python3
"""Run the full COBOL mock validation pipeline.

This script automates the 4-step flow documented in examples/README.md:
1) Instrument COBOL source for mock execution
2) Compile instrumented COBOL with GnuCOBOL (cobc)
3) Generate Python from AST and synthesize test cases
4) Compare Python vs COBOL outputs using the synthesized test store

Example:
    python3 examples/run_pipeline.py \
      --ast examples/COPAUA0C.cbl.ast \
      --cbl ../carddemo/app/.../COPAUA0C.cbl \
      --cpy ../carddemo/app/.../cpy
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path


def _quote_cmd(parts: list[str]) -> str:
    return " ".join(shlex.quote(p) for p in parts)


def _run(cmd: list[str], *, cwd: Path) -> None:
    print(f"\n$ {_quote_cmd(cmd)}")
    subprocess.run(cmd, cwd=str(cwd), check=True)


def _is_specter_flag_supported(specter_cmd: list[str], flag: str, cwd: Path) -> bool:
    try:
        result = subprocess.run(
            specter_cmd + ["--help"],
            cwd=str(cwd),
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return False
    return flag in result.stdout


def _resolve_repo_root() -> Path:
    # Script is in <repo>/examples/run_pipeline.py
    return Path(__file__).resolve().parent.parent


def main() -> int:
    parser = argparse.ArgumentParser(description="Run full Specter COBOL mock pipeline")
    parser.add_argument("--ast", required=True, help="Path to AST file (.ast)")
    parser.add_argument("--cbl", required=True, help="Path to COBOL source file (.cbl/.cob/.cobol)")
    parser.add_argument(
        "--cpy",
        action="append",
        required=True,
        help="Copybook directory (repeat --cpy for multiple dirs)",
    )
    parser.add_argument(
        "--out-dir",
        default="examples",
        help="Output directory for generated files (default: examples)",
    )
    parser.add_argument(
        "--test-store",
        default=None,
        help="Path to synthesized test store JSONL (default: <out-dir>/tests.jsonl)",
    )
    parser.add_argument(
        "--exclude-values",
        default=None,
        help="Optional path to exclude-values file, used only if specter supports --exclude-values",
    )
    parser.add_argument(
        "--synthesis-layers",
        type=int,
        default=None,
        help="Optional synthesis layer limit to pass to specter",
    )
    parser.add_argument(
        "--synthesis-timeout",
        type=int,
        default=None,
        help="Optional synthesis timeout in seconds to pass to specter",
    )
    parser.add_argument("--cobc-bin", default="cobc", help="GnuCOBOL compiler binary (default: cobc)")
    parser.add_argument(
        "--specter-bin",
        default=None,
        help="Specter executable to use (default: python -m specter)",
    )
    parser.add_argument(
        "--python-bin",
        default=sys.executable,
        help="Python executable for run_mock.py (default: current interpreter)",
    )

    args = parser.parse_args()

    repo_root = _resolve_repo_root()
    ast_path = Path(args.ast).expanduser().resolve()
    cbl_path = Path(args.cbl).expanduser().resolve()
    cpy_dirs = [Path(d).expanduser().resolve() for d in args.cpy]
    out_dir = Path(args.out_dir).expanduser().resolve()

    if not ast_path.exists():
        print(f"Error: AST not found: {ast_path}", file=sys.stderr)
        return 1
    if not cbl_path.exists():
        print(f"Error: COBOL source not found: {cbl_path}", file=sys.stderr)
        return 1
    for d in cpy_dirs:
        if not d.exists() or not d.is_dir():
            print(f"Error: copybook dir not found or not a directory: {d}", file=sys.stderr)
            return 1

    out_dir.mkdir(parents=True, exist_ok=True)

    stem = cbl_path.stem
    mock_cbl = out_dir / f"{stem}.mock.cbl"
    mock_exe = out_dir / f"{stem}.mock"
    generated_py = out_dir / f"{stem}.py"
    test_store = Path(args.test_store).expanduser().resolve() if args.test_store else (out_dir / "tests.jsonl")

    if args.specter_bin:
        specter_cmd = [args.specter_bin]
    else:
        specter_cmd = [sys.executable, "-m", "specter"]

    supports_cobol_validate = _is_specter_flag_supported(specter_cmd, "--cobol-validate", repo_root)
    supports_exclude_values = _is_specter_flag_supported(specter_cmd, "--exclude-values", repo_root)

    # 1) Instrument COBOL source for standalone mock execution.
    cmd1 = specter_cmd + [str(cbl_path), "--mock-cobol", "-o", str(mock_cbl)]
    for d in cpy_dirs:
        cmd1 += ["--copybook-dir", str(d)]
    _run(cmd1, cwd=repo_root)

    # 2) Compile instrumented mock with GnuCOBOL.
    cmd2 = [args.cobc_bin, "-x", "-o", str(mock_exe), str(mock_cbl)]
    _run(cmd2, cwd=repo_root)

    # 3) Generate Python + synthesize tests.
    cmd3 = specter_cmd + [
        str(ast_path),
        "-o",
        str(generated_py),
        "--synthesize",
        "--test-store",
        str(test_store),
    ]
    if supports_cobol_validate:
        cmd3 += ["--cobol-validate", str(mock_exe)]
    if args.exclude_values and supports_exclude_values:
        cmd3 += ["--exclude-values", str(Path(args.exclude_values).expanduser().resolve())]
    if args.synthesis_layers is not None:
        cmd3 += ["--synthesis-layers", str(args.synthesis_layers)]
    if args.synthesis_timeout is not None:
        cmd3 += ["--synthesis-timeout", str(args.synthesis_timeout)]
    _run(cmd3, cwd=repo_root)

    # 4) Compare Python vs COBOL outputs using synthesized test store.
    run_mock = repo_root / "examples" / "run_mock.py"
    cmd4 = [args.python_bin, str(run_mock), str(mock_exe), str(generated_py), str(test_store)]
    _run(cmd4, cwd=repo_root)

    print("\nPipeline finished successfully.")
    print(f"  Mock COBOL:  {mock_cbl}")
    print(f"  Mock binary: {mock_exe}")
    print(f"  Python out:  {generated_py}")
    print(f"  Test store:  {test_store}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        print(f"\nCommand failed with exit code {exc.returncode}", file=sys.stderr)
        raise
