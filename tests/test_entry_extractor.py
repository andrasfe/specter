"""Tests for the source-text entry-statement extractor."""

import textwrap
import unittest
from pathlib import Path
from tempfile import NamedTemporaryFile

from specter.entry_extractor import (
    _parse_statements,
    _slice_entry_section,
    _tokenise,
    _TokenStream,
    extract_entry_statements,
)


def _src(body: str) -> str:
    """Build a minimal COBOL source with a PROCEDURE DIVISION + the given
    body + one labeled paragraph. Indented to match COBOL Area B."""
    indented = "\n".join(
        ("           " + line) if line.strip() else line
        for line in textwrap.dedent(body).splitlines()
    )
    return (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. TEST.\n"
        "       PROCEDURE DIVISION.\n"
        f"{indented}\n"
        "       0000-FIRST-PARA.\n"
        "           CONTINUE.\n"
    )


def _parse(body: str):
    src = _src(body)
    sliced = _slice_entry_section(src)
    assert sliced is not None, f"slicer returned None for: {src!r}"
    return _parse_statements(_TokenStream(_tokenise(sliced)))


class TestSliceEntrySection(unittest.TestCase):
    def test_returns_text_between_proc_division_and_first_para(self):
        src = _src("DISPLAY 'hi'.")
        out = _slice_entry_section(src)
        self.assertIsNotNone(out)
        self.assertIn("DISPLAY 'hi'", out)
        self.assertNotIn("0000-FIRST-PARA", out)

    def test_returns_none_when_no_procedure_division(self):
        self.assertIsNone(_slice_entry_section("       IDENTIFICATION DIVISION.\n"))

    def test_skips_END_keywords_when_finding_first_para(self):
        # END-PERFORM. and END-IF. would otherwise look like paragraph
        # headers — but they're block terminators that shouldn't end the
        # entry-section slice.
        body = """
            PERFORM UNTIL EOF
                DISPLAY 'x'
            END-PERFORM.
            DISPLAY 'after-loop'.
            GOBACK.
        """
        sliced = _slice_entry_section(_src(body))
        self.assertIn("DISPLAY 'after-loop'", sliced)
        self.assertIn("GOBACK", sliced)

    def test_paragraph_names_starting_with_digit_terminate_slice(self):
        # CardDemo paragraphs all start with digits — make sure those work.
        out = _slice_entry_section(_src("DISPLAY 'hi'."))
        self.assertIn("DISPLAY 'hi'", out)
        self.assertNotIn("CONTINUE", out)


class TestParseStatements(unittest.TestCase):
    def test_display_simple(self):
        stmts = _parse("DISPLAY 'hello world'.")
        self.assertEqual(len(stmts), 1)
        self.assertEqual(stmts[0].type, "DISPLAY")
        self.assertIn("'hello world'", stmts[0].text)

    def test_perform_simple(self):
        stmts = _parse("PERFORM 0100-OPEN.")
        self.assertEqual(len(stmts), 1)
        self.assertEqual(stmts[0].type, "PERFORM")
        self.assertEqual(stmts[0].attributes["target"], "0100-OPEN")

    def test_perform_thru(self):
        stmts = _parse("PERFORM 0100-A THRU 0100-Z.")
        self.assertEqual(stmts[0].type, "PERFORM")
        self.assertEqual(stmts[0].attributes["target"], "0100-A")
        self.assertEqual(stmts[0].attributes["thru"], "0100-Z")

    def test_perform_until_with_body(self):
        stmts = _parse("""
            PERFORM UNTIL EOF = 'Y'
                PERFORM 1000-READ
            END-PERFORM.
        """)
        self.assertEqual(len(stmts), 1)
        s = stmts[0]
        self.assertEqual(s.type, "PERFORM_INLINE")
        self.assertEqual(s.attributes["condition"], "UNTIL EOF = 'Y'")
        self.assertEqual(len(s.children), 1)
        self.assertEqual(s.children[0].type, "PERFORM")
        self.assertEqual(s.children[0].attributes["target"], "1000-READ")

    def test_if_with_else(self):
        stmts = _parse("""
            IF X = 0
                PERFORM 1000-OK
            ELSE
                PERFORM 1000-FAIL
            END-IF.
        """)
        self.assertEqual(len(stmts), 1)
        s = stmts[0]
        self.assertEqual(s.type, "IF")
        self.assertEqual(s.attributes["condition"], "X = 0")
        # Children: [then-perform, ELSE-node]
        self.assertEqual(s.children[0].type, "PERFORM")
        self.assertEqual(s.children[0].attributes["target"], "1000-OK")
        self.assertEqual(s.children[1].type, "ELSE")
        self.assertEqual(s.children[1].children[0].type, "PERFORM")
        self.assertEqual(s.children[1].children[0].attributes["target"], "1000-FAIL")

    def test_move_extracts_source_and_target(self):
        stmts = _parse("MOVE 0 TO WS-COUNT.")
        self.assertEqual(stmts[0].type, "MOVE")
        self.assertEqual(stmts[0].attributes["source"], "0")
        self.assertEqual(stmts[0].attributes["targets"], "WS-COUNT")

    def test_goback(self):
        stmts = _parse("GOBACK.")
        self.assertEqual(len(stmts), 1)
        self.assertEqual(stmts[0].type, "GOBACK")

    def test_full_carddemo_pattern(self):
        stmts = _parse("""
            DISPLAY 'START'.
            PERFORM 0000-OPEN.
            PERFORM UNTIL EOF = 'Y'
                IF EOF = 'N'
                    PERFORM 1000-PROCESS
                END-IF
            END-PERFORM.
            PERFORM 9000-CLOSE.
            DISPLAY 'END'.
            GOBACK.
        """)
        types = [s.type for s in stmts]
        self.assertEqual(
            types,
            ["DISPLAY", "PERFORM", "PERFORM_INLINE", "PERFORM", "DISPLAY", "GOBACK"],
        )
        # Loop body is preserved as nested children.
        loop = stmts[2]
        self.assertEqual(loop.children[0].type, "IF")


class TestExtractEntryStatementsFile(unittest.TestCase):
    def test_returns_empty_for_missing_file(self):
        self.assertEqual(extract_entry_statements("/nonexistent/x.cbl"), [])

    def test_parses_real_file(self):
        with NamedTemporaryFile("w", suffix=".cbl", delete=False) as fh:
            fh.write(_src("DISPLAY 'hello'.\n           GOBACK."))
            path = Path(fh.name)
        try:
            stmts = extract_entry_statements(path)
            types = [s.type for s in stmts]
            self.assertEqual(types, ["DISPLAY", "GOBACK"])
        finally:
            path.unlink()


if __name__ == "__main__":
    unittest.main()
