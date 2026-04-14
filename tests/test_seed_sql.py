"""Tests for the per-test-case seed SQL generator."""

import unittest

from specter.copybook_parser import CopybookField, CopybookRecord
from specter.java_templates.seed_sql import (
    build_seed_sql,
    build_table_index,
    is_seedable_op_key,
)


def _make_record(name: str, fields: list[tuple[str, str, int, int]]) -> CopybookRecord:
    """Helper: build a CopybookRecord from (field_name, pic_type, length, occurs) tuples."""
    flds = []
    for field_name, pic_type, length, occurs in fields:
        flds.append(
            CopybookField(
                level=5,
                name=field_name,
                pic=None,
                pic_type=pic_type,
                length=length,
                precision=0,
                occurs=occurs,
                is_filler=False,
            )
        )
    return CopybookRecord(name=name, fields=flds, copybook_file="test.cpy")


class TestIsSeedableOpKey(unittest.TestCase):
    def test_read_prefix(self):
        self.assertTrue(is_seedable_op_key("READ:ACCOUNT-FILE"))

    def test_cics_read(self):
        self.assertTrue(is_seedable_op_key("CICS-READ"))

    def test_dli_gu(self):
        self.assertTrue(is_seedable_op_key("DLI-GU"))

    def test_non_seedable(self):
        self.assertFalse(is_seedable_op_key("SQL-SELECT"))
        self.assertFalse(is_seedable_op_key("CALL:CUSTAPI"))
        self.assertFalse(is_seedable_op_key("CICS-WRITE"))


class TestBuildTableIndex(unittest.TestCase):
    def test_indexes_by_uppercase_underscored_name(self):
        rec = _make_record("ACCT-REC", [("ACCT-ID", "alpha", 8, 1)])
        idx = build_table_index([rec])
        self.assertIn("ACCT_REC", idx)
        self.assertIs(idx["ACCT_REC"], rec)

    def test_skips_records_without_fields(self):
        rec = CopybookRecord(name="EMPTY", fields=[], copybook_file="x.cpy")
        self.assertEqual(build_table_index([rec]), {})


class TestBuildSeedSql(unittest.TestCase):
    def test_read_file_op_emits_insert_into_named_table(self):
        rec = _make_record(
            "ACCOUNT-FILE",
            [("ACCT-ID", "alpha", 8, 1), ("ACCT-BAL", "numeric", 9, 1)],
        )
        sql = build_seed_sql(
            "tc1",
            input_state={"ACCT-ID": "00000042"},
            stub_outcomes={
                "READ:ACCOUNT-FILE": [
                    [["ACCT-BAL", 100]],
                ]
            },
            table_index=build_table_index([rec]),
        )
        self.assertIn("TRUNCATE TABLE ACCOUNT_FILE CASCADE;", sql)
        self.assertIn("INSERT INTO ACCOUNT_FILE", sql)
        self.assertIn("ACCT_BAL", sql)
        self.assertIn("100", sql)

    def test_cics_read_uses_input_state_ridfld_for_key(self):
        rec = _make_record(
            "ACCT-REC",
            [("ACCT-ID", "alpha", 8, 1), ("ACCT-BAL", "numeric", 9, 1)],
        )
        sql = build_seed_sql(
            "tc1",
            input_state={"ACCT-ID": "42"},
            stub_outcomes={
                "CICS-READ": [
                    [["ACCT-BAL", 100]],
                ]
            },
            table_index=build_table_index([rec]),
        )
        # Key column from input_state, value column from outcome.
        self.assertIn("ACCT_ID", sql)
        self.assertIn("'42'", sql)
        self.assertIn("ACCT_BAL", sql)
        self.assertIn("100", sql)

    def test_multi_outcome_emits_multiple_rows_with_synthetic_keys(self):
        rec = _make_record(
            "ACCT-REC",
            [("ACCT-ID", "alpha", 12, 1), ("ACCT-BAL", "numeric", 9, 1)],
        )
        sql = build_seed_sql(
            "tc1",
            input_state={"ACCT-ID": "K1"},
            stub_outcomes={
                "CICS-READ": [
                    [["ACCT-BAL", 100]],
                    [["ACCT-BAL", 200]],
                    [["ACCT-BAL", 300]],
                ]
            },
            table_index=build_table_index([rec]),
        )
        # First row uses real ridfld value; subsequent ones get synthetic key.
        self.assertIn("'K1'", sql)
        self.assertIn("'K1__1'", sql)
        self.assertIn("'K1__2'", sql)
        self.assertEqual(sql.count("INSERT INTO"), 3)
        # All three balances appear.
        self.assertIn("100", sql)
        self.assertIn("200", sql)
        self.assertIn("300", sql)

    def test_no_table_index_returns_empty(self):
        sql = build_seed_sql(
            "tc1",
            input_state={},
            stub_outcomes={"CICS-READ": [[["X", 1]]]},
            table_index={},
        )
        self.assertEqual(sql, "")

    def test_no_seedable_outcomes_returns_empty(self):
        rec = _make_record("ACCT-REC", [("ACCT-ID", "alpha", 8, 1)])
        sql = build_seed_sql(
            "tc1",
            input_state={"ACCT-ID": "x"},
            stub_outcomes={"SQL-SELECT": [[["SQLCODE", 0]]], "CALL:FOO": [[["X", 1]]]},
            table_index=build_table_index([rec]),
        )
        self.assertEqual(sql, "")

    def test_unmatched_op_emits_todo_comment(self):
        rec = _make_record("ACCT-REC", [("ACCT-ID", "alpha", 8, 1)])
        sql = build_seed_sql(
            "tc1",
            input_state={},
            stub_outcomes={"CICS-READ": [[["UNRELATED-VAR", 1]]]},
            table_index=build_table_index([rec]),
        )
        # No table matches because UNRELATED_VAR isn't in any record.
        self.assertIn("TODO(seed)", sql)

    def test_quoting_handles_apostrophes_and_nulls(self):
        rec = _make_record(
            "ACCT-REC",
            [("ACCT-ID", "alpha", 12, 1), ("NAME", "alpha", 20, 1)],
        )
        sql = build_seed_sql(
            "tc1",
            input_state={"ACCT-ID": "K1"},
            stub_outcomes={
                "CICS-READ": [[["NAME", "O'Brien"]]],
            },
            table_index=build_table_index([rec]),
        )
        # Apostrophe doubled per SQL convention.
        self.assertIn("'O''Brien'", sql)


if __name__ == "__main__":
    unittest.main()
