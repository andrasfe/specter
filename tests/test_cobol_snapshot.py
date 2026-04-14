"""Tests for cobol_snapshot: normalization + Snapshot dataclass + iter."""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from specter.cobol_executor import CobolTestResult
from specter.cobol_snapshot import (
    CobolSnapshot,
    iter_test_cases,
    normalize_stub_outcomes,
    normalize_value,
    values_equivalent,
)


class TestNormalizeStubOutcomes(unittest.TestCase):
    def test_dict_passthrough(self):
        raw = {"OPEN:F": [[("A", "1")]], "READ:F": [[("B", "2")]]}
        out = normalize_stub_outcomes(raw)
        self.assertEqual(out, {"OPEN:F": [[("A", "1")]], "READ:F": [[("B", "2")]]})

    def test_list_of_pairs_groups_by_op_key_in_order(self):
        # Format produced by cobol_coverage._save_test_case.
        raw = [
            ["OPEN:DALY", [["DALY-STATUS", "00"]]],
            ["OPEN:TRAN", [["TRAN-STATUS", "00"]]],
            ["READ:DALY", [["DALY-STATUS", "00"]]],
            ["READ:DALY", [["DALY-STATUS", "10"]]],
        ]
        out = normalize_stub_outcomes(raw)
        self.assertEqual(set(out.keys()), {"OPEN:DALY", "OPEN:TRAN", "READ:DALY"})
        self.assertEqual(len(out["READ:DALY"]), 2)
        self.assertEqual(out["READ:DALY"][0], [["DALY-STATUS", "00"]])
        self.assertEqual(out["READ:DALY"][1], [["DALY-STATUS", "10"]])

    def test_none_and_empty_return_empty_dict(self):
        self.assertEqual(normalize_stub_outcomes(None), {})
        self.assertEqual(normalize_stub_outcomes([]), {})
        self.assertEqual(normalize_stub_outcomes({}), {})

    def test_dict_with_none_queue_becomes_empty_list(self):
        out = normalize_stub_outcomes({"OPEN:F": None})
        self.assertEqual(out, {"OPEN:F": []})


class TestNormalizeValue(unittest.TestCase):
    def test_strings_rstripped_only(self):
        # COBOL pads PIC X on the right; preserve any deliberate left padding.
        self.assertEqual(normalize_value("hello   "), "hello")
        self.assertEqual(normalize_value("  hello   "), "  hello")

    def test_empty_and_blank_to_empty_string(self):
        self.assertEqual(normalize_value(""), "")
        self.assertEqual(normalize_value(" "), "")
        self.assertEqual(normalize_value(None), "")

    def test_numeric_strings_canonicalised(self):
        self.assertEqual(normalize_value("00042"), "42")
        self.assertEqual(normalize_value("-007"), "-7")
        self.assertEqual(normalize_value("+12"), "12")
        self.assertEqual(normalize_value("0"), "0")
        self.assertEqual(normalize_value("0.50"), "0.5")
        self.assertEqual(normalize_value("0.00"), "0")
        self.assertEqual(normalize_value("100.10"), "100.1")

    def test_python_numbers_canonicalised(self):
        self.assertEqual(normalize_value(42), "42")
        self.assertEqual(normalize_value(0), "0")
        self.assertEqual(normalize_value(0.5), "0.5")
        self.assertEqual(normalize_value(True), "true")
        self.assertEqual(normalize_value(False), "false")

    def test_non_numeric_strings_passthrough(self):
        self.assertEqual(normalize_value("abc"), "abc")
        self.assertEqual(normalize_value("X12Y"), "X12Y")


class TestValuesEquivalent(unittest.TestCase):
    def test_pic_x_padding_equivalent(self):
        self.assertTrue(values_equivalent("ABC   ", "ABC"))

    def test_leading_zero_numeric_equivalent(self):
        self.assertTrue(values_equivalent("00042", 42))
        self.assertTrue(values_equivalent("0042", "42"))

    def test_distinct_values_not_equivalent(self):
        self.assertFalse(values_equivalent("ABC", "ABD"))
        self.assertFalse(values_equivalent(42, 43))


class TestSnapshotFromResult(unittest.TestCase):
    def test_roundtrip_basic_fields(self):
        result = CobolTestResult(
            paragraphs_hit=["MAIN", "PROC-A"],
            branches_hit={"5:T", "12:F"},
            display_output=["hello"],
            variable_snapshots={
                "MAIN": {"WS-X": "00042", "WS-NAME": "ABC   "},
            },
            return_code=0,
            execution_time_ms=1.0,
        )
        snap = CobolSnapshot.from_result("tc1", result)
        self.assertEqual(snap.id, "tc1")
        self.assertFalse(snap.abended)
        self.assertEqual(snap.displays, ["hello"])
        self.assertEqual(snap.paragraphs_covered, ["MAIN", "PROC-A"])
        # Branches sorted (deterministic).
        self.assertEqual(snap.branches, ["12:F", "5:T"])
        # Final state values normalised.
        self.assertEqual(snap.final_state["WS-X"], "42")
        self.assertEqual(snap.final_state["WS-NAME"], "ABC")

    def test_abended_when_nonzero_return_code(self):
        result = CobolTestResult(return_code=1, error="bad")
        snap = CobolSnapshot.from_result("tc1", result)
        self.assertTrue(snap.abended)

    def test_track_vars_filters_final_state(self):
        result = CobolTestResult(
            variable_snapshots={"MAIN": {"WS-X": 1, "WS-Y": 2, "WS-Z": 3}},
            return_code=0,
        )
        snap = CobolSnapshot.from_result("tc1", result, track_vars=["WS-X", "WS-Z"])
        self.assertEqual(set(snap.final_state.keys()), {"WS-X", "WS-Z"})

    def test_to_dict_round_trip_via_json(self):
        result = CobolTestResult(
            paragraphs_hit=["MAIN"],
            display_output=["hi"],
            variable_snapshots={"MAIN": {"WS-X": 42}},
            return_code=0,
        )
        snap = CobolSnapshot.from_result("tc1", result)
        d = snap.to_dict()
        self.assertNotIn("error", d)  # None error stripped
        # Round-trips cleanly through JSON.
        roundtrip = json.loads(json.dumps(d))
        self.assertEqual(roundtrip["id"], "tc1")
        self.assertEqual(roundtrip["paragraphs_covered"], ["MAIN"])


class TestIterTestCases(unittest.TestCase):
    def test_skips_progress_records(self):
        with TemporaryDirectory() as td:
            path = Path(td) / "tests.jsonl"
            with path.open("w", encoding="utf-8") as fh:
                fh.write(json.dumps({"_type": "progress", "layer": 1}) + "\n")
                fh.write(json.dumps({"id": "abc", "input_state": {}, "stub_outcomes": {}}) + "\n")
                fh.write("\n")  # empty line
                fh.write("not-json\n")
                fh.write(json.dumps({"id": "def", "input_state": {}}) + "\n")
            ids = [tc["id"] for tc in iter_test_cases(path)]
            self.assertEqual(ids, ["abc", "def"])


if __name__ == "__main__":
    unittest.main()
