"""Tests for the REDEFINES + USAGE BINARY extractor."""

import textwrap
import unittest
from pathlib import Path
from tempfile import NamedTemporaryFile

from specter.redefines_extractor import (
    _calc_storage,
    extract_redefines_groups,
)


def _src(data: str) -> str:
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


def _write_and_extract(body: str) -> dict:
    with NamedTemporaryFile("w", suffix=".cbl", delete=False) as fh:
        fh.write(_src(body))
        path = Path(fh.name)
    try:
        return extract_redefines_groups(path)
    finally:
        path.unlink()


class TestCalcStorage(unittest.TestCase):
    def test_alpha_pic_x(self):
        self.assertEqual(_calc_storage("X(4)", ""), (0, 4))
        self.assertEqual(_calc_storage("X", ""), (0, 1))

    def test_numeric_display(self):
        self.assertEqual(_calc_storage("9(5)", ""), (5, 5))
        self.assertEqual(_calc_storage("9(3)", "DISPLAY"), (3, 3))

    def test_numeric_binary_widths(self):
        self.assertEqual(_calc_storage("9(4)", "BINARY"), (4, 2))
        self.assertEqual(_calc_storage("9(7)", "BINARY"), (7, 4))
        self.assertEqual(_calc_storage("9(12)", "BINARY"), (12, 8))
        self.assertEqual(_calc_storage("9(4)", "COMP"), (4, 2))

    def test_packed_decimal(self):
        # ceil((digits+1)/2) — 5 digits → 3 bytes, 7 digits → 4 bytes
        self.assertEqual(_calc_storage("9(5)", "COMP-3"), (5, 3))
        self.assertEqual(_calc_storage("9(7)", "PACKED-DECIMAL"), (7, 4))


class TestRedefinesGroup(unittest.TestCase):
    def test_two_byte_binary_aliased_by_alpha(self):
        groups = _write_and_extract("""
            01 TWO-BYTES-BINARY     PIC 9(4) BINARY.
            01 TWO-BYTES-ALPHA REDEFINES TWO-BYTES-BINARY.
               05 TWO-BYTES-LEFT  PIC X.
               05 TWO-BYTES-RIGHT PIC X.
        """)
        self.assertIn("TWO-BYTES-BINARY", groups)
        g = groups["TWO-BYTES-BINARY"]
        self.assertEqual(g["width"], 2)
        members = g["members"]
        self.assertEqual(members["TWO-BYTES-BINARY"]["kind"], "binary")
        self.assertEqual(members["TWO-BYTES-BINARY"]["length"], 2)
        self.assertEqual(members["TWO-BYTES-LEFT"]["offset"], 0)
        self.assertEqual(members["TWO-BYTES-LEFT"]["length"], 1)
        self.assertEqual(members["TWO-BYTES-RIGHT"]["offset"], 1)
        self.assertEqual(members["TWO-BYTES-RIGHT"]["length"], 1)

    def test_filler_redefines_with_subfields(self):
        # 01 FILLER REDEFINES X  is a common idiom for sub-byte access.
        groups = _write_and_extract("""
            01 DB2-FORMAT-TS                PIC X(26).
            01 FILLER REDEFINES DB2-FORMAT-TS.
                06 DB2-YYYY                 PIC X(4).
                06 DB2-MM                   PIC X(2).
        """)
        self.assertIn("DB2-FORMAT-TS", groups)
        g = groups["DB2-FORMAT-TS"]
        self.assertEqual(g["width"], 26)
        m = g["members"]
        self.assertEqual(m["DB2-YYYY"]["offset"], 0)
        self.assertEqual(m["DB2-YYYY"]["length"], 4)
        self.assertEqual(m["DB2-MM"]["offset"], 4)
        self.assertEqual(m["DB2-MM"]["length"], 2)
        # FILLER itself is NOT a member (not addressable by name).
        self.assertNotIn("FILLER", m)

    def test_no_redefines_no_groups(self):
        groups = _write_and_extract("""
            01 SIMPLE-FIELD       PIC X(8).
            01 ANOTHER            PIC 9(4) COMP.
        """)
        self.assertEqual(groups, {})

    def test_signed_binary(self):
        groups = _write_and_extract("""
            01 SIGNED-BIN PIC S9(4) BINARY.
            01 SIGNED-ALPHA REDEFINES SIGNED-BIN.
               05 BYTE-A PIC X.
               05 BYTE-B PIC X.
        """)
        m = groups["SIGNED-BIN"]["members"]
        self.assertTrue(m["SIGNED-BIN"]["signed"])
        self.assertEqual(m["SIGNED-BIN"]["length"], 2)


class TestExtractorMissingFile(unittest.TestCase):
    def test_returns_empty_for_missing(self):
        self.assertEqual(extract_redefines_groups("/nonexistent.cbl"), {})


if __name__ == "__main__":
    unittest.main()
