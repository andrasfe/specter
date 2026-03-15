"""Tests for multi-program CICS XCTL routing generation.

Verifies that ``generate_multi_program_project`` produces a valid Maven
project with CicsProgram implementations, XctlSignal, and a
MultiProgramRunner that wires them together.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# Skip the entire module if the example AST files are not present.
_EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
_AST_FILES = [
    _EXAMPLES / "COSGN00C.cbl.ast",
    _EXAMPLES / "COACTUPC.cbl.ast",
    _EXAMPLES / "COTRN00C.cbl.ast",
]
_SINGLE_AST = _EXAMPLES / "COSGN00C.cbl.ast"

pytestmark = pytest.mark.skipif(
    not all(f.exists() for f in _AST_FILES),
    reason="Example AST files not available",
)


def _read_generated(tmpdir: str, filename: str) -> str:
    """Read a generated Java file from the standard package path."""
    path = (
        Path(tmpdir)
        / "src"
        / "main"
        / "java"
        / "com"
        / "specter"
        / "generated"
        / filename
    )
    assert path.exists(), f"Expected generated file not found: {path}"
    return path.read_text()


class TestMultiProgramProject:
    """Tests for ``generate_multi_program_project``."""

    def test_generates_all_programs(self, tmp_path):
        from specter.java_code_generator import generate_multi_program_project

        result = generate_multi_program_project(
            ast_paths=[str(f) for f in _AST_FILES],
            output_dir=str(tmp_path / "out"),
        )
        out = Path(result)

        # Each program class should exist
        assert (out / "src/main/java/com/specter/generated/Cosgn00cProgram.java").exists()
        assert (out / "src/main/java/com/specter/generated/CoactupcProgram.java").exists()
        assert (out / "src/main/java/com/specter/generated/Cotrn00cProgram.java").exists()

    def test_generates_multi_program_runner(self, tmp_path):
        from specter.java_code_generator import generate_multi_program_project

        result = generate_multi_program_project(
            ast_paths=[str(f) for f in _AST_FILES],
            output_dir=str(tmp_path / "out"),
        )
        src = _read_generated(str(tmp_path / "out"), "MultiProgramRunner.java")

        assert "class MultiProgramRunner" in src
        assert 'registry.put("COSGN00C"' in src
        assert 'registry.put("COACTUPC"' in src
        assert 'registry.put("COTRN00C"' in src
        assert 'firstProgram = "COSGN00C"' in src
        assert "Function<StubExecutor, CicsProgram>" in src

    def test_generates_xctl_signal(self, tmp_path):
        from specter.java_code_generator import generate_multi_program_project

        generate_multi_program_project(
            ast_paths=[str(f) for f in _AST_FILES],
            output_dir=str(tmp_path / "out"),
        )
        src = _read_generated(str(tmp_path / "out"), "XctlSignal.java")

        assert "class XctlSignal extends RuntimeException" in src
        assert "public final String targetProgram" in src

    def test_generates_cics_program_interface(self, tmp_path):
        from specter.java_code_generator import generate_multi_program_project

        generate_multi_program_project(
            ast_paths=[str(f) for f in _AST_FILES],
            output_dir=str(tmp_path / "out"),
        )
        src = _read_generated(str(tmp_path / "out"), "CicsProgram.java")

        assert "interface CicsProgram" in src
        assert "ProgramState run(ProgramState state)" in src
        assert "String programId()" in src
        assert "List<CicsScreen.Field> screenLayout()" in src

    def test_programs_implement_cics_program(self, tmp_path):
        from specter.java_code_generator import generate_multi_program_project

        generate_multi_program_project(
            ast_paths=[str(f) for f in _AST_FILES],
            output_dir=str(tmp_path / "out"),
        )

        for prog_file in ["Cosgn00cProgram.java", "CoactupcProgram.java",
                          "Cotrn00cProgram.java"]:
            src = _read_generated(str(tmp_path / "out"), prog_file)
            assert "implements CicsProgram" in src, (
                f"{prog_file} should implement CicsProgram"
            )
            assert "@Override" in src
            assert "public String programId()" in src
            assert "public List<CicsScreen.Field> screenLayout()" in src

    def test_unique_screen_layouts(self, tmp_path):
        from specter.java_code_generator import generate_multi_program_project

        generate_multi_program_project(
            ast_paths=[str(f) for f in _AST_FILES],
            output_dir=str(tmp_path / "out"),
        )

        for prog_id in ["COSGN00C", "COACTUPC", "COTRN00C"]:
            layout_file = f"ScreenLayout_{prog_id}.java"
            src = _read_generated(str(tmp_path / "out"), layout_file)
            assert f"class ScreenLayout_{prog_id}" in src

    def test_unique_section_classes(self, tmp_path):
        from specter.java_code_generator import generate_multi_program_project

        generate_multi_program_project(
            ast_paths=[str(f) for f in _AST_FILES],
            output_dir=str(tmp_path / "out"),
        )

        # Each program should have its own section classes
        base = Path(tmp_path / "out" / "src/main/java/com/specter/generated")
        cosgn_sections = list(base.glob("Section*_COSGN00C.java"))
        coactupc_sections = list(base.glob("Section*_COACTUPC.java"))
        cotrn_sections = list(base.glob("Section*_COTRN00C.java"))

        assert len(cosgn_sections) >= 1
        assert len(coactupc_sections) >= 1
        assert len(cotrn_sections) >= 1

    def test_terminal_stub_executor_throws_xctl_signal(self, tmp_path):
        from specter.java_code_generator import generate_multi_program_project

        generate_multi_program_project(
            ast_paths=[str(f) for f in _AST_FILES],
            output_dir=str(tmp_path / "out"),
        )
        src = _read_generated(str(tmp_path / "out"), "TerminalStubExecutor.java")

        assert "throw new XctlSignal(program)" in src
        # Should NOT throw GobackSignal for XCTL
        assert "GobackSignal" not in src or "throw new GobackSignal" not in src.split("XCTL")[1]

    def test_pom_xml_generated(self, tmp_path):
        from specter.java_code_generator import generate_multi_program_project

        generate_multi_program_project(
            ast_paths=[str(f) for f in _AST_FILES],
            output_dir=str(tmp_path / "out"),
        )
        pom = (tmp_path / "out" / "pom.xml").read_text()
        assert "carddemo-multi" in pom

    def test_per_program_terminal_mains(self, tmp_path):
        from specter.java_code_generator import generate_multi_program_project

        generate_multi_program_project(
            ast_paths=[str(f) for f in _AST_FILES],
            output_dir=str(tmp_path / "out"),
        )

        for prog_id in ["COSGN00C", "COACTUPC", "COTRN00C"]:
            main_file = f"TerminalMain_{prog_id}.java"
            src = _read_generated(str(tmp_path / "out"), main_file)
            assert f"class TerminalMain_{prog_id}" in src
            assert f"ScreenLayout_{prog_id}.FIELDS" in src


class TestSingleProgramBackwardsCompatibility:
    """Verify single-program generation is not broken."""

    @pytest.mark.skipif(
        not _SINGLE_AST.exists(),
        reason="COSGN00C.cbl.ast not available",
    )
    def test_single_program_terminal(self, tmp_path):
        from specter.ast_parser import parse_ast
        from specter.java_code_generator import generate_java_project
        from specter.variable_extractor import extract_variables

        program = parse_ast(str(_SINGLE_AST))
        var_report = extract_variables(program)

        result = generate_java_project(
            program, var_report, str(tmp_path / "out"),
        )
        out = Path(result)

        # Program class
        prog_src = _read_generated(str(tmp_path / "out"), "Cosgn00cProgram.java")
        assert "implements CicsProgram" in prog_src
        assert "ScreenLayout.FIELDS" in prog_src  # NOT ScreenLayout_COSGN00C

        # ScreenLayout (not prefixed in single mode)
        assert (out / "src/main/java/com/specter/generated/ScreenLayout.java").exists()

        # XctlSignal and CicsProgram generated for terminal programs
        assert (out / "src/main/java/com/specter/generated/XctlSignal.java").exists()
        assert (out / "src/main/java/com/specter/generated/CicsProgram.java").exists()

        # TerminalMain (not prefixed)
        assert (out / "src/main/java/com/specter/generated/TerminalMain.java").exists()
