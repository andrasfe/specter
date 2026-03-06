#!/usr/bin/env python3
"""Validate specter codegen against GnuCOBOL by comparing DISPLAY output.

For each .cbl file in this directory:
1. Compile and run with GnuCOBOL → capture stdout
2. Parse with ProLeap → JSON AST → specter generate_code → exec → capture _display
3. Compare outputs, report pass/fail
"""

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from specter.ast_parser import parse_ast
from specter.code_generator import generate_code
from specter.variable_extractor import extract_variables

PROLEAP_JAR = Path.home() / "war_rig/citadel/proleap-wrapper/target/proleap-wrapper-fat.jar"
COBOL_DIR = Path(__file__).parent


def extract_initial_values(cbl_path: Path) -> dict:
    """Parse VALUE clauses from COBOL source to build initial state dict."""
    initial = {}
    text = cbl_path.read_text()
    # Match: 01 VAR-NAME PIC ... VALUE <value>.
    for m in re.finditer(
        r"^\s+\d+\s+([A-Z][A-Z0-9-]*)\s+PIC\s+(\S+)\s+VALUE\s+(.+?)\.",
        text, re.MULTILINE | re.IGNORECASE,
    ):
        varname = m.group(1).upper()
        pic = m.group(2).upper()
        val_str = m.group(3).strip()

        if val_str.upper() == "SPACES" or val_str.upper() == "SPACE":
            initial[varname] = " "
        elif val_str.upper() == "ZEROS" or val_str.upper() == "ZEROES" or val_str.upper() == "ZERO":
            initial[varname] = 0
        elif val_str.startswith("'") and val_str.endswith("'"):
            initial[varname] = val_str[1:-1]
        elif re.match(r"^-?\d+\.?\d*$", val_str):
            if "." in val_str:
                initial[varname] = float(val_str)
            else:
                initial[varname] = int(val_str)
        else:
            initial[varname] = val_str

    # Handle 88-level conditions: map condition name to parent var + value
    # e.g. 88 IS-ACTIVE VALUE 'Y'. means SET IS-ACTIVE TO TRUE → parent = 'Y'
    lines = text.splitlines()
    current_parent = None
    for line in lines:
        # Track current 01-level variable
        m01 = re.match(r"\s+01\s+([A-Z][A-Z0-9-]*)\s+", line, re.IGNORECASE)
        if m01:
            current_parent = m01.group(1).upper()
        m88 = re.match(
            r"\s+88\s+([A-Z][A-Z0-9-]*)\s+VALUE\s+(.+?)\.",
            line, re.IGNORECASE,
        )
        if m88 and current_parent:
            cond_name = m88.group(1).upper()
            val_str = m88.group(2).strip()
            if val_str.startswith("'") and val_str.endswith("'"):
                val = val_str[1:-1]
            elif re.match(r"^-?\d+$", val_str):
                val = int(val_str)
            else:
                val = val_str
            # Store mapping: when SET cond_name TO TRUE, set parent = val
            initial[f"_88_{cond_name}"] = (current_parent, val)

    return initial


def run_gnucobol(cbl_path: Path) -> tuple[bool, str]:
    """Compile and run a COBOL program with GnuCOBOL. Returns (ok, stdout)."""
    with tempfile.NamedTemporaryFile(suffix="", delete=False) as tmp:
        exe_path = tmp.name

    try:
        # Compile
        result = subprocess.run(
            ["cobc", "-x", "-free", str(cbl_path), "-o", exe_path],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return False, f"COMPILE ERROR: {result.stderr.strip()}"

        # Run
        result = subprocess.run(
            [exe_path],
            capture_output=True, text=True, timeout=10,
        )
        return True, result.stdout.strip()
    except Exception as e:
        return False, f"EXCEPTION: {e}"
    finally:
        try:
            os.unlink(exe_path)
        except OSError:
            pass


def run_proleap(cbl_path: Path) -> tuple[bool, dict]:
    """Parse COBOL with ProLeap. Returns (ok, ast_dict)."""
    try:
        result = subprocess.run(
            ["java", "-jar", str(PROLEAP_JAR), str(cbl_path)],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return False, {"error": result.stderr.strip()}

        ast_data = json.loads(result.stdout)
        return True, ast_data
    except Exception as e:
        return False, {"error": str(e)}


def run_specter(ast_data: dict, initial_vars: dict | None = None) -> tuple[bool, str]:
    """Generate Python from AST, execute, return DISPLAY output."""
    try:
        program = parse_ast(ast_data)
        var_report = extract_variables(program)
        code = generate_code(program, var_report=var_report)

        ns = {}
        exec(code, ns)
        state = dict(initial_vars or {})
        result = ns["run"](state)
        display_lines = [str(d) for d in result.get("_display", [])]
        return True, "\n".join(display_lines)
    except Exception as e:
        return True, f"SPECTER ERROR: {type(e).__name__}: {e}"


def normalize_output(text: str) -> list[str]:
    """Normalize COBOL output for comparison.

    GnuCOBOL pads PIC fields with leading zeros / trailing spaces.
    Specter stores raw Python values. We normalize both sides by
    stripping leading zeros from numeric-looking segments and
    normalizing sign display.
    """
    lines = []
    for line in text.strip().splitlines():
        line = line.rstrip()
        # Normalize leading zeros in numeric segments: 0042 → 42, 0000 → 0
        def strip_leading_zeros(m):
            num = m.group(0).lstrip("0") or "0"
            return num
        line = re.sub(r"\b0+\d+\b", strip_leading_zeros, line)
        # Normalize signed display: +15 → 15 (COBOL shows + for PIC S9)
        line = re.sub(r"\+(\d)", r"\1", line)
        lines.append(line)
    return lines


def main():
    cbl_files = sorted(COBOL_DIR.glob("test*.cbl"))
    if not cbl_files:
        print("No test*.cbl files found!")
        return 1

    passed = 0
    failed = 0
    errors = 0

    for cbl in cbl_files:
        name = cbl.stem
        print(f"\n{'=' * 60}")
        print(f"TEST: {name}")
        print(f"{'=' * 60}")

        # Step 1: GnuCOBOL
        cobol_ok, cobol_out = run_gnucobol(cbl)
        if not cobol_ok:
            print(f"  GNUCOBOL: {cobol_out}")
            errors += 1
            continue

        # Step 2: ProLeap parse
        proleap_ok, ast_data = run_proleap(cbl)
        if not proleap_ok:
            print(f"  PROLEAP: {ast_data.get('error', 'unknown')}")
            errors += 1
            continue

        # Save AST for debugging
        ast_file = cbl.with_suffix(".ast")
        with open(ast_file, "w") as f:
            json.dump(ast_data, f, indent=2)

        # Extract initial values from COBOL source
        initial_vars = extract_initial_values(cbl)
        # Separate out 88-level mappings
        clean_vars = {k: v for k, v in initial_vars.items()
                      if not k.startswith("_88_")}

        # Step 3: Specter
        specter_ok, specter_out = run_specter(ast_data, clean_vars)
        if not specter_ok:
            print(f"  SPECTER: {specter_out}")
            errors += 1
            continue

        # Step 4: Compare
        cobol_lines = normalize_output(cobol_out)
        specter_lines = normalize_output(specter_out)

        if cobol_lines == specter_lines:
            print(f"  PASS ({len(cobol_lines)} lines match)")
            passed += 1
        else:
            print(f"  FAIL")
            failed += 1
            max_lines = max(len(cobol_lines), len(specter_lines))
            for i in range(max_lines):
                c = cobol_lines[i] if i < len(cobol_lines) else "<missing>"
                s = specter_lines[i] if i < len(specter_lines) else "<missing>"
                marker = "  " if c == s else ">>"
                print(f"    {marker} COBOL:   {c!r}")
                if c != s:
                    print(f"    {marker} SPECTER: {s!r}")

    print(f"\n{'=' * 60}")
    print(f"RESULTS: {passed} passed, {failed} failed, {errors} errors")
    print(f"{'=' * 60}")
    return 0 if failed == 0 and errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
