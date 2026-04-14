"""Tests for the PIC info extractor + truncation helper."""

import textwrap
import unittest
from pathlib import Path
from tempfile import NamedTemporaryFile

from specter.copybook_parser import CopybookField, CopybookRecord
from specter.pic_extractor import (
    build_pic_info,
    pic_info_from_copybooks,
    pic_info_from_source,
    truncate_for_pic,
)


def _src(data: str) -> str:
    """Build a minimal COBOL program with a DATA DIVISION body."""
    indented = "\n".join("       " + line for line in textwrap.dedent(data).splitlines())
    return (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. T.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        f"{indented}\n"
        "       PROCEDURE DIVISION.\n"
        "           GOBACK.\n"
    )


class TestFromCopybooks(unittest.TestCase):
    def test_extracts_alpha_field_length(self):
        rec = CopybookRecord(
            name="ACCT-REC",
            fields=[CopybookField(
                level=5, name="ACCT-ID", pic="X(8)", pic_type="alpha",
                length=8, precision=0, occurs=1, is_filler=False,
            )],
            copybook_file="x.cpy",
        )
        out = pic_info_from_copybooks([rec])
        self.assertIn("ACCT-ID", out)
        self.assertEqual(out["ACCT-ID"]["length"], 8)
        self.assertEqual(out["ACCT-ID"]["kind"], "alpha")

    def test_skips_filler_and_groups(self):
        rec = CopybookRecord(
            name="REC",
            fields=[
                CopybookField(level=5, name="FILLER", pic="X(4)",
                              pic_type="alpha", length=4, precision=0,
                              occurs=1, is_filler=True),
                CopybookField(level=5, name="GRP", pic=None, pic_type="group",
                              length=0, precision=0, occurs=1, is_filler=False),
            ],
            copybook_file="x.cpy",
        )
        self.assertEqual(pic_info_from_copybooks([rec]), {})


class TestFromSource(unittest.TestCase):
    def test_inline_alpha_field(self):
        with NamedTemporaryFile("w", suffix=".cbl", delete=False) as fh:
            fh.write(_src("01 END-OF-FILE PIC X(1) VALUE 'N'."))
            path = Path(fh.name)
        try:
            out = pic_info_from_source(path)
            self.assertIn("END-OF-FILE", out)
            self.assertEqual(out["END-OF-FILE"]["length"], 1)
            self.assertEqual(out["END-OF-FILE"]["kind"], "alpha")
        finally:
            path.unlink()

    def test_inline_numeric_field(self):
        with NamedTemporaryFile("w", suffix=".cbl", delete=False) as fh:
            fh.write(_src("01 WS-COUNT PIC 9(4) VALUE ZERO."))
            path = Path(fh.name)
        try:
            out = pic_info_from_source(path)
            self.assertIn("WS-COUNT", out)
            self.assertEqual(out["WS-COUNT"]["length"], 4)
            self.assertEqual(out["WS-COUNT"]["kind"], "numeric")
        finally:
            path.unlink()

    def test_skips_88_levels(self):
        with NamedTemporaryFile("w", suffix=".cbl", delete=False) as fh:
            fh.write(_src(
                "01 EOF-FLAG PIC X(1).\n"
                "  88 END-REACHED VALUE 'Y'.\n"
            ))
            path = Path(fh.name)
        try:
            out = pic_info_from_source(path)
            self.assertIn("EOF-FLAG", out)
            self.assertNotIn("END-REACHED", out)
        finally:
            path.unlink()

    def test_skips_procedure_division_paragraphs(self):
        # Paragraph names in PROCEDURE DIVISION must not be picked up as
        # data items.
        src_body = "01 WS-X PIC X(2).\n"
        with NamedTemporaryFile("w", suffix=".cbl", delete=False) as fh:
            fh.write(_src(src_body))
            path = Path(fh.name)
        try:
            out = pic_info_from_source(path)
            self.assertEqual(set(out.keys()), {"WS-X"})
        finally:
            path.unlink()


class TestBuildPicInfo(unittest.TestCase):
    def test_copybook_takes_precedence_over_inline(self):
        rec = CopybookRecord(
            name="REC",
            fields=[CopybookField(
                level=5, name="WS-X", pic="X(8)", pic_type="alpha",
                length=8, precision=0, occurs=1, is_filler=False,
            )],
            copybook_file="x.cpy",
        )
        with NamedTemporaryFile("w", suffix=".cbl", delete=False) as fh:
            fh.write(_src("01 WS-X PIC X(99)."))
            path = Path(fh.name)
        try:
            out = build_pic_info([rec], path)
            # Copybook wins: length stays at 8, not 99.
            self.assertEqual(out["WS-X"]["length"], 8)
        finally:
            path.unlink()

    def test_no_inputs_returns_empty(self):
        self.assertEqual(build_pic_info([], None), {})


class TestTruncateForPic(unittest.TestCase):
    def test_truncates_long_alpha_to_pic_length(self):
        out = truncate_for_pic("NVGFYGWWQC", {"length": 1, "kind": "alpha"})
        self.assertEqual(out, "N")

    def test_short_alpha_unchanged(self):
        out = truncate_for_pic("Y", {"length": 1, "kind": "alpha"})
        self.assertEqual(out, "Y")

    def test_empty_value_unchanged(self):
        self.assertEqual(truncate_for_pic("", {"length": 1, "kind": "alpha"}), "")
        self.assertIsNone(truncate_for_pic(None, {"length": 1, "kind": "alpha"}))

    def test_no_entry_passthrough(self):
        self.assertEqual(truncate_for_pic("anything", None), "anything")

    def test_numeric_kind_not_truncated_as_string(self):
        # Numeric values are precision-typed; we don't string-truncate them.
        out = truncate_for_pic("00042", {"length": 5, "kind": "numeric"})
        self.assertEqual(out, "00042")


if __name__ == "__main__":
    unittest.main()
