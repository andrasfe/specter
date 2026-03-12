"""Tests for copybook_parser module."""

import os
import tempfile

import pytest

from specter.copybook_parser import (
    CopybookField,
    CopybookRecord,
    generate_dao_java,
    generate_ddl,
    generate_all_ddl,
    parse_copybook,
)


# ---------------------------------------------------------------------------
# Copybook texts used across tests
# ---------------------------------------------------------------------------

CARD_XREF = """\
01 CARD-XREF-RECORD.
    05  XREF-CARD-NUM                     PIC X(16).
    05  XREF-CUST-ID                      PIC 9(09).
    05  XREF-ACCT-ID                      PIC 9(11).
    05  FILLER                            PIC X(14).
"""

ACCOUNT_RECORD = """\
01  ACCOUNT-RECORD.
    05  ACCT-ID                           PIC 9(11).
    05  ACCT-ACTIVE-STATUS                PIC X(01).
    05  ACCT-CURR-BAL                     PIC S9(10)V99.
    05  ACCT-CREDIT-LIMIT                 PIC S9(10)V99.
    05  ACCT-CASH-CREDIT-LIMIT            PIC S9(10)V99.
    05  ACCT-OPEN-DATE                    PIC X(10).
    05  ACCT-EXPIRAION-DATE               PIC X(10).
    05  ACCT-REISSUE-DATE                 PIC X(10).
    05  ACCT-CURR-CYC-CREDIT              PIC S9(10)V99.
    05  ACCT-CURR-CYC-DEBIT               PIC S9(10)V99.
    05  ACCT-ADDR-ZIP                     PIC X(10).
    05  ACCT-GROUP-ID                     PIC X(10).
    05  FILLER                            PIC X(178).
"""

CUSTOMER_RECORD = """\
01  CUSTOMER-RECORD.
    05  CUST-ID                                 PIC 9(09).
    05  CUST-FIRST-NAME                         PIC X(25).
    05  CUST-MIDDLE-NAME                        PIC X(25).
    05  CUST-LAST-NAME                          PIC X(25).
    05  CUST-ADDR-LINE-1                        PIC X(50).
    05  CUST-ADDR-LINE-2                        PIC X(50).
    05  CUST-ADDR-LINE-3                        PIC X(50).
    05  CUST-ADDR-STATE-CD                      PIC X(02).
    05  CUST-ADDR-COUNTRY-CD                    PIC X(03).
    05  CUST-ADDR-ZIP                           PIC X(10).
    05  CUST-PHONE-NUM-1                        PIC X(15).
    05  CUST-PHONE-NUM-2                        PIC X(15).
    05  CUST-SSN                                PIC 9(09).
    05  CUST-GOVT-ISSUED-ID                     PIC X(20).
    05  CUST-DOB-YYYY-MM-DD                     PIC X(10).
    05  CUST-EFT-ACCOUNT-ID                     PIC X(10).
    05  CUST-PRI-CARD-HOLDER-IND                PIC X(01).
    05  CUST-FICO-CREDIT-SCORE                  PIC 9(03).
    05  FILLER                                  PIC X(168).
"""

PENDING_AUTH_SUMMARY = """\
01 PENDING-AUTH-SUMMARY.
    05  PA-ACCT-ID                   PIC S9(11) COMP-3.
    05  PA-CUST-ID                   PIC  9(09).
    05  PA-AUTH-STATUS               PIC  X(01).
    05  PA-ACCOUNT-STATUS            PIC  X(02) OCCURS 5 TIMES.
    05  PA-CREDIT-LIMIT              PIC S9(09)V99 COMP-3.
    05  PA-CASH-LIMIT                PIC S9(09)V99 COMP-3.
    05  PA-CREDIT-BALANCE            PIC S9(09)V99 COMP-3.
    05  PA-CASH-BALANCE              PIC S9(09)V99 COMP-3.
    05  PA-APPROVED-AUTH-CNT         PIC S9(04) COMP.
    05  PA-DECLINED-AUTH-CNT         PIC S9(04) COMP.
    05  PA-APPROVED-AUTH-AMT         PIC S9(09)V99 COMP-3.
    05  PA-DECLINED-AUTH-AMT         PIC S9(09)V99 COMP-3.
    05  FILLER                       PIC X(34).
"""

PENDING_AUTH_DETAILS = """\
01 PENDING-AUTH-DETAILS.
    05  PA-AUTHORIZATION-KEY.
        10 PA-AUTH-DATE-9C           PIC S9(05) COMP-3.
        10 PA-AUTH-TIME-9C           PIC S9(09) COMP-3.
    05  PA-AUTH-ORIG-DATE            PIC  X(06).
    05  PA-AUTH-ORIG-TIME            PIC  X(06).
    05  PA-CARD-NUM                  PIC  X(16).
    05  PA-AUTH-TYPE                 PIC  X(04).
    05  PA-CARD-EXPIRY-DATE          PIC  X(04).
    05  PA-MESSAGE-TYPE              PIC  X(06).
    05  PA-MESSAGE-SOURCE            PIC  X(06).
    05  PA-AUTH-ID-CODE              PIC  X(06).
    05  PA-AUTH-RESP-CODE            PIC  X(02).
        88 PA-AUTH-APPROVED          VALUE '00'.
    05  PA-AUTH-RESP-REASON          PIC  X(04).
    05  PA-PROCESSING-CODE           PIC  9(06).
    05  PA-TRANSACTION-AMT           PIC S9(10)V99 COMP-3.
    05  PA-APPROVED-AMT              PIC S9(10)V99 COMP-3.
    05  PA-MERCHANT-CATAGORY-CODE    PIC  X(04).
    05  PA-ACQR-COUNTRY-CODE         PIC  X(03).
    05  PA-POS-ENTRY-MODE            PIC  9(02).
    05  PA-MERCHANT-ID               PIC  X(15).
    05  PA-MERCHANT-NAME             PIC  X(22).
    05  PA-MERCHANT-CITY             PIC  X(13).
    05  PA-MERCHANT-STATE            PIC  X(02).
    05  PA-MERCHANT-ZIP              PIC  X(09).
    05  PA-TRANSACTION-ID            PIC  X(15).
    05  PA-MATCH-STATUS              PIC  X(01).
        88 PA-MATCH-PENDING          VALUE 'P'.
        88 PA-MATCH-AUTH-DECLINED    VALUE 'D'.
        88 PA-MATCH-PENDING-EXPIRED  VALUE 'E'.
        88 PA-MATCHED-WITH-TRAN      VALUE 'M'.
    05  PA-AUTH-FRAUD                PIC  X(01).
        88 PA-FRAUD-CONFIRMED        VALUE 'F'.
        88 PA-FRAUD-REMOVED          VALUE 'R'.
    05  PA-FRAUD-RPT-DATE            PIC  X(08).
    05  FILLER                       PIC  X(17).
"""

ERROR_LOG_RECORD = """\
01 ERROR-LOG-RECORD.
    05 ERR-DATE                     PIC  X(06).
    05 ERR-TIME                     PIC  X(06).
    05 ERR-APPLICATION              PIC  X(08).
    05 ERR-PROGRAM                  PIC  X(08).
    05 ERR-LOCATION                 PIC  X(04).
    05 ERR-LEVEL                    PIC  X(01).
       88 ERR-LOG                   VALUE 'L'.
       88 ERR-INFO                  VALUE 'I'.
       88 ERR-WARNING               VALUE 'W'.
       88 ERR-CRITICAL              VALUE 'C'.
    05 ERR-SUBSYSTEM                PIC  X(01).
       88 ERR-APP                   VALUE 'A'.
       88 ERR-CICS                  VALUE 'C'.
       88 ERR-IMS                   VALUE 'I'.
       88 ERR-DB2                   VALUE 'D'.
       88 ERR-MQ                    VALUE 'M'.
       88 ERR-FILE                  VALUE 'F'.
    05 ERR-CODE-1                   PIC  X(09).
    05 ERR-CODE-2                   PIC  X(09).
    05 ERR-MESSAGE                  PIC  X(50).
    05 ERR-EVENT-KEY                PIC  X(20).
"""


# ===================================================================
# 1. Parsing PIC types
# ===================================================================

class TestParsePicTypes:
    def test_pic_x(self):
        rec = parse_copybook("01 REC.\n    05 FLD PIC X(16).")
        f = rec.fields[0]
        assert f.pic_type == 'alpha'
        assert f.length == 16
        assert f.precision == 0

    def test_pic_9(self):
        rec = parse_copybook("01 REC.\n    05 FLD PIC 9(09).")
        f = rec.fields[0]
        assert f.pic_type == 'numeric'
        assert f.length == 9
        assert f.precision == 0

    def test_pic_s9v99(self):
        rec = parse_copybook("01 REC.\n    05 FLD PIC S9(10)V99.")
        f = rec.fields[0]
        assert f.pic_type == 'numeric'
        assert f.length == 10
        assert f.precision == 2

    def test_pic_comp3(self):
        rec = parse_copybook("01 REC.\n    05 FLD PIC S9(11) COMP-3.")
        f = rec.fields[0]
        assert f.pic_type == 'packed'
        assert f.length == 11
        assert f.precision == 0

    def test_pic_comp(self):
        rec = parse_copybook("01 REC.\n    05 FLD PIC S9(04) COMP.")
        f = rec.fields[0]
        assert f.pic_type == 'comp'
        assert f.length == 4
        assert f.precision == 0

    def test_pic_comp3_with_decimal(self):
        rec = parse_copybook("01 REC.\n    05 FLD PIC S9(09)V99 COMP-3.")
        f = rec.fields[0]
        assert f.pic_type == 'packed'
        assert f.length == 9
        assert f.precision == 2

    def test_pic_x_small(self):
        rec = parse_copybook("01 REC.\n    05 FLD PIC X(01).")
        f = rec.fields[0]
        assert f.pic_type == 'alpha'
        assert f.length == 1


# ===================================================================
# 2. FILLER parsing
# ===================================================================

class TestFiller:
    def test_filler_detected(self):
        rec = parse_copybook(CARD_XREF)
        fillers = [f for f in rec.fields if f.is_filler]
        assert len(fillers) == 1
        assert fillers[0].length == 14

    def test_filler_skipped_in_ddl(self):
        rec = parse_copybook(CARD_XREF)
        ddl = generate_ddl(rec)
        assert 'FILLER' not in ddl


# ===================================================================
# 3. 88-level conditions
# ===================================================================

class TestLevel88:
    def test_88_captured(self):
        rec = parse_copybook(ERROR_LOG_RECORD)
        err_level = [f for f in rec.fields if f.name == 'ERR-LEVEL'][0]
        assert 'ERR-LOG' in err_level.values_88
        assert err_level.values_88['ERR-LOG'] == 'L'
        assert 'ERR-CRITICAL' in err_level.values_88
        assert err_level.values_88['ERR-CRITICAL'] == 'C'

    def test_88_not_in_fields(self):
        """88-level conditions should not appear as separate fields."""
        rec = parse_copybook(ERROR_LOG_RECORD)
        levels = [f.level for f in rec.fields]
        assert 88 not in levels

    def test_88_subsystem(self):
        rec = parse_copybook(ERROR_LOG_RECORD)
        err_sub = [f for f in rec.fields if f.name == 'ERR-SUBSYSTEM'][0]
        assert len(err_sub.values_88) == 6
        assert err_sub.values_88['ERR-DB2'] == 'D'

    def test_88_not_in_ddl(self):
        rec = parse_copybook(ERROR_LOG_RECORD)
        ddl = generate_ddl(rec)
        assert 'ERR_LOG' not in ddl or 'ERR_LOG ' not in ddl
        # The column ERR_LEVEL should exist but not ERR_LOG as a column
        assert 'ERR_LEVEL' in ddl

    def test_88_match_status(self):
        rec = parse_copybook(PENDING_AUTH_DETAILS)
        match_field = [f for f in rec.fields if f.name == 'PA-MATCH-STATUS'][0]
        assert len(match_field.values_88) == 4
        assert match_field.values_88['PA-MATCH-PENDING'] == 'P'


# ===================================================================
# 4. OCCURS
# ===================================================================

class TestOccurs:
    def test_occurs_parsed(self):
        rec = parse_copybook(PENDING_AUTH_SUMMARY)
        pa_status = [f for f in rec.fields if f.name == 'PA-ACCOUNT-STATUS'][0]
        assert pa_status.occurs == 5

    def test_occurs_expanded_in_ddl(self):
        rec = parse_copybook(PENDING_AUTH_SUMMARY)
        ddl = generate_ddl(rec)
        for i in range(1, 6):
            assert f'PA_ACCOUNT_STATUS_{i}' in ddl

    def test_non_occurs_default_1(self):
        rec = parse_copybook(CARD_XREF)
        for f in rec.fields:
            assert f.occurs == 1


# ===================================================================
# 5. Group items (hierarchical)
# ===================================================================

class TestGroupItems:
    def test_group_item_parsed(self):
        rec = parse_copybook(PENDING_AUTH_DETAILS)
        auth_key = [f for f in rec.fields if f.name == 'PA-AUTHORIZATION-KEY'][0]
        assert auth_key.pic_type == 'group'
        assert auth_key.pic is None

    def test_group_children(self):
        rec = parse_copybook(PENDING_AUTH_DETAILS)
        # After PA-AUTHORIZATION-KEY (level 05), the next fields are level 10
        idx = next(i for i, f in enumerate(rec.fields) if f.name == 'PA-AUTHORIZATION-KEY')
        child1 = rec.fields[idx + 1]
        child2 = rec.fields[idx + 2]
        assert child1.name == 'PA-AUTH-DATE-9C'
        assert child1.level == 10
        assert child2.name == 'PA-AUTH-TIME-9C'
        assert child2.level == 10

    def test_group_skipped_in_ddl(self):
        rec = parse_copybook(PENDING_AUTH_DETAILS)
        ddl = generate_ddl(rec)
        assert 'PA_AUTHORIZATION_KEY ' not in ddl
        # But children should be present
        assert 'PA_AUTH_DATE_9C' in ddl
        assert 'PA_AUTH_TIME_9C' in ddl


# ===================================================================
# 6. DDL generation for each copybook
# ===================================================================

class TestDDLGeneration:
    def test_card_xref_ddl(self):
        rec = parse_copybook(CARD_XREF)
        ddl = generate_ddl(rec)
        assert 'CREATE TABLE CARD_XREF_RECORD' in ddl
        assert 'XREF_CARD_NUM' in ddl
        assert 'VARCHAR(16)' in ddl
        assert 'XREF_CUST_ID' in ddl
        assert 'NUMERIC(9)' in ddl
        assert 'XREF_ACCT_ID' in ddl
        assert 'NUMERIC(11)' in ddl
        assert 'FILLER' not in ddl

    def test_account_record_ddl(self):
        rec = parse_copybook(ACCOUNT_RECORD)
        ddl = generate_ddl(rec)
        assert 'CREATE TABLE ACCOUNT_RECORD' in ddl
        assert 'ACCT_CURR_BAL' in ddl
        assert 'DECIMAL(12, 2)' in ddl
        assert 'ACCT_OPEN_DATE' in ddl
        assert 'VARCHAR(10)' in ddl

    def test_customer_record_ddl(self):
        rec = parse_copybook(CUSTOMER_RECORD)
        ddl = generate_ddl(rec)
        assert 'CREATE TABLE CUSTOMER_RECORD' in ddl
        assert 'CUST_FIRST_NAME' in ddl
        assert 'VARCHAR(25)' in ddl
        assert 'CUST_SSN' in ddl
        assert 'NUMERIC(9)' in ddl
        assert 'CUST_FICO_CREDIT_SCORE' in ddl
        assert 'NUMERIC(3)' in ddl

    def test_pending_auth_summary_ddl(self):
        rec = parse_copybook(PENDING_AUTH_SUMMARY)
        ddl = generate_ddl(rec)
        assert 'CREATE TABLE PENDING_AUTH_SUMMARY' in ddl
        assert 'PA_ACCT_ID' in ddl
        assert 'DECIMAL(11, 0)' in ddl
        assert 'PA_AUTH_STATUS' in ddl
        assert 'CHAR(1)' in ddl
        assert 'PA_ACCOUNT_STATUS_1' in ddl
        assert 'CHAR(2)' in ddl
        assert 'PA_CREDIT_LIMIT' in ddl
        assert 'DECIMAL(11, 2)' in ddl
        assert 'PA_APPROVED_AUTH_CNT' in ddl
        assert 'INTEGER' in ddl

    def test_pending_auth_details_ddl(self):
        rec = parse_copybook(PENDING_AUTH_DETAILS)
        ddl = generate_ddl(rec)
        assert 'CREATE TABLE PENDING_AUTH_DETAILS' in ddl
        assert 'PA_AUTH_DATE_9C' in ddl
        assert 'PA_TRANSACTION_AMT' in ddl
        assert 'DECIMAL(12, 2)' in ddl

    def test_error_log_ddl(self):
        rec = parse_copybook(ERROR_LOG_RECORD)
        ddl = generate_ddl(rec)
        assert 'CREATE TABLE ERROR_LOG_RECORD' in ddl
        assert 'ERR_DATE' in ddl
        assert 'ERR_MESSAGE' in ddl
        assert 'VARCHAR(50)' in ddl
        # 88-level condition names should NOT appear as columns
        assert 'ERR_LOG ' not in ddl.replace('ERROR_LOG_RECORD', '')

    def test_custom_table_name(self):
        rec = parse_copybook(CARD_XREF)
        ddl = generate_ddl(rec, table_name='MY_TABLE')
        assert 'CREATE TABLE MY_TABLE' in ddl


# ===================================================================
# 7. generate_all_ddl
# ===================================================================

class TestGenerateAllDDL:
    def test_scans_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, 'test1.cpy'), 'w') as f:
                f.write(CARD_XREF)
            with open(os.path.join(tmpdir, 'test2.cpy'), 'w') as f:
                f.write(ACCOUNT_RECORD)
            ddl = generate_all_ddl(tmpdir)
            assert 'CARD_XREF_RECORD' in ddl
            assert 'ACCOUNT_RECORD' in ddl

    def test_ignores_non_cpy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, 'test1.cpy'), 'w') as f:
                f.write(CARD_XREF)
            with open(os.path.join(tmpdir, 'test2.txt'), 'w') as f:
                f.write(ACCOUNT_RECORD)
            ddl = generate_all_ddl(tmpdir)
            assert 'CARD_XREF_RECORD' in ddl
            assert 'ACCOUNT_RECORD' not in ddl


# ===================================================================
# 8. Java DAO generation
# ===================================================================

class TestDAOGeneration:
    def test_card_xref_dao(self):
        rec = parse_copybook(CARD_XREF)
        java = generate_dao_java(rec, 'com.example.dao')
        assert 'package com.example.dao;' in java
        assert 'class CardXrefRecordDao' in java
        assert 'populateFromResultSet' in java
        assert 'bindToStatement' in java
        assert 'state.put("XREF-CARD-NUM"' in java
        assert 'rs.getString("XREF_CARD_NUM")' in java
        assert 'rs.getLong("XREF_CUST_ID")' in java
        assert 'FILLER' not in java

    def test_dao_bind_indices(self):
        rec = parse_copybook(CARD_XREF)
        java = generate_dao_java(rec, 'com.example')
        assert 'ps.setString(1,' in java
        assert 'ps.setLong(2,' in java
        assert 'ps.setLong(3,' in java

    def test_dao_decimal_fields(self):
        rec = parse_copybook(ACCOUNT_RECORD)
        java = generate_dao_java(rec, 'com.example')
        assert 'getBigDecimal' in java
        assert 'setBigDecimal' in java

    def test_dao_occurs_expanded(self):
        rec = parse_copybook(PENDING_AUTH_SUMMARY)
        java = generate_dao_java(rec, 'com.example')
        assert 'PA-ACCOUNT-STATUS(1)' in java
        assert 'PA-ACCOUNT-STATUS(5)' in java
        assert 'PA_ACCOUNT_STATUS_1' in java

    def test_dao_skips_group_items(self):
        rec = parse_copybook(PENDING_AUTH_DETAILS)
        java = generate_dao_java(rec, 'com.example')
        assert 'PA-AUTHORIZATION-KEY' not in java
        assert 'PA-AUTH-DATE-9C' in java

    def test_dao_comp_integer(self):
        rec = parse_copybook(PENDING_AUTH_SUMMARY)
        java = generate_dao_java(rec, 'com.example')
        assert 'CobolRuntime.toNum' in java


# ===================================================================
# 9. Record-level parsing
# ===================================================================

class TestRecordParsing:
    def test_record_name(self):
        rec = parse_copybook(CARD_XREF, copybook_file='CVACT03Y.cpy')
        assert rec.name == 'CARD-XREF-RECORD'
        assert rec.copybook_file == 'CVACT03Y.cpy'

    def test_field_count_card_xref(self):
        rec = parse_copybook(CARD_XREF)
        # 3 real fields + 1 FILLER = 4
        assert len(rec.fields) == 4

    def test_field_count_error_log(self):
        rec = parse_copybook(ERROR_LOG_RECORD)
        # 10 fields (no 88s in field list)
        field_names = [f.name for f in rec.fields]
        assert 'ERR-DATE' in field_names
        assert 'ERR-EVENT-KEY' in field_names
        # 88-level names should NOT be in the field list
        assert 'ERR-LOG' not in field_names
