"""End-to-end tests using real AST files."""

import json
import os
import unittest
from pathlib import Path

from specter.ast_parser import parse_ast
from specter.code_generator import generate_code
from specter.variable_extractor import extract_variables

# Path to example AST files
_EXAMPLES_DIR = Path(
    "/Users/andraslferenczi/war_rig/examples/app-authorization-ims-db2-mq/cbl"
)


def _ast_available(name: str) -> bool:
    return (_EXAMPLES_DIR / name).exists()


class TestEndToEndPAUDBLOD(unittest.TestCase):
    """Test with PAUDBLOD.CBL.ast — simple IMS batch loader."""

    AST_FILE = "PAUDBLOD.CBL.ast"

    @unittest.skipUnless(
        _ast_available("PAUDBLOD.CBL.ast"),
        "PAUDBLOD.CBL.ast not found",
    )
    def test_generates_and_compiles(self):
        program = parse_ast(_EXAMPLES_DIR / self.AST_FILE)
        var_report = extract_variables(program)
        code = generate_code(program, var_report)
        # Must compile
        compile(code, "<paudblod>", "exec")

    @unittest.skipUnless(
        _ast_available("PAUDBLOD.CBL.ast"),
        "PAUDBLOD.CBL.ast not found",
    )
    def test_runs_with_immediate_eof(self):
        program = parse_ast(_EXAMPLES_DIR / self.AST_FILE)
        var_report = extract_variables(program)
        code = generate_code(program, var_report)
        ns = {}
        exec(code, ns)
        result = ns["run"]({
            "WS-INFIL1-STATUS": " ",
            "WS-INFIL2-STATUS": " ",
            "PAUT-PCB-STATUS": " ",
            "END-ROOT-SEG-FILE": "Y",
            "END-CHILD-SEG-FILE": "Y",
        })
        # Should complete without error
        self.assertIsInstance(result, dict)
        # Should have display output
        self.assertGreater(len(result["_display"]), 0)

    @unittest.skipUnless(
        _ast_available("PAUDBLOD.CBL.ast"),
        "PAUDBLOD.CBL.ast not found",
    )
    def test_runs_with_read_loop(self):
        """Simulate a few file reads before EOF."""
        program = parse_ast(_EXAMPLES_DIR / self.AST_FILE)
        var_report = extract_variables(program)
        code = generate_code(program, var_report)
        ns = {}
        exec(code, ns)
        result = ns["run"]({
            "WS-INFIL1-STATUS": " ",
            "WS-INFIL2-STATUS": " ",
            "PAUT-PCB-STATUS": " ",
            "END-ROOT-SEG-FILE": False,
            "END-CHILD-SEG-FILE": "Y",
        })
        self.assertIsInstance(result, dict)


class TestEndToEndCBPAUP0C(unittest.TestCase):
    """Test with CBPAUP0C.cbl.ast — nested PERFORMs."""

    @unittest.skipUnless(
        _ast_available("CBPAUP0C.cbl.ast"),
        "CBPAUP0C.cbl.ast not found",
    )
    def test_generates_and_compiles(self):
        program = parse_ast(_EXAMPLES_DIR / "CBPAUP0C.cbl.ast")
        var_report = extract_variables(program)
        code = generate_code(program, var_report)
        compile(code, "<cbpaup0c>", "exec")

    @unittest.skipUnless(
        _ast_available("CBPAUP0C.cbl.ast"),
        "CBPAUP0C.cbl.ast not found",
    )
    def test_runs_basic(self):
        program = parse_ast(_EXAMPLES_DIR / "CBPAUP0C.cbl.ast")
        var_report = extract_variables(program)
        code = generate_code(program, var_report)
        ns = {}
        exec(code, ns)
        result = ns["run"]({
            "ERR-FLG-ON": True,
            "END-OF-AUTHDB": True,
            "NO-MORE-AUTHS": True,
            "P-EXPIRY-DAYS": "5",
        })
        self.assertIsInstance(result, dict)


class TestEndToEndCOPAUS2C(unittest.TestCase):
    """Test with COPAUS2C.cbl.ast — EXEC SQL/CICS."""

    @unittest.skipUnless(
        _ast_available("COPAUS2C.cbl.ast"),
        "COPAUS2C.cbl.ast not found",
    )
    def test_generates_and_compiles(self):
        program = parse_ast(_EXAMPLES_DIR / "COPAUS2C.cbl.ast")
        var_report = extract_variables(program)
        code = generate_code(program, var_report)
        compile(code, "<copaus2c>", "exec")

    @unittest.skipUnless(
        _ast_available("COPAUS2C.cbl.ast"),
        "COPAUS2C.cbl.ast not found",
    )
    def test_runs_with_sql_success(self):
        program = parse_ast(_EXAMPLES_DIR / "COPAUS2C.cbl.ast")
        var_report = extract_variables(program)
        code = generate_code(program, var_report)
        ns = {}
        exec(code, ns)
        result = ns["run"]({
            "SQLCODE": 0,
        })
        self.assertIsInstance(result, dict)
        # Should have recorded SQL exec
        self.assertGreater(len(result["_execs"]), 0)


class TestEndToEndAllFiles(unittest.TestCase):
    """Test that all AST files generate compilable code."""

    @unittest.skipUnless(
        _EXAMPLES_DIR.exists(),
        "Examples directory not found",
    )
    def test_all_ast_files_compile(self):
        for ast_file in sorted(_EXAMPLES_DIR.glob("*.ast")):
            with self.subTest(file=ast_file.name):
                program = parse_ast(ast_file)
                var_report = extract_variables(program)
                code = generate_code(program, var_report)
                try:
                    compile(code, f"<{ast_file.name}>", "exec")
                except SyntaxError as e:
                    self.fail(f"{ast_file.name} failed to compile: {e}")


if __name__ == "__main__":
    unittest.main()
