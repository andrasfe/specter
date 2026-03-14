package com.specter.generated;

/**
 * Generated section: Section9.
 */
public class Section9 extends SectionBase {

    public Section9(ParagraphRegistry registry, StubExecutor stubs) {
        super(registry, stubs);
        paragraph("9000-READ-ACCT", this::do_9000_READ_ACCT);
        paragraph("9000-READ-ACCT-EXIT", this::do_9000_READ_ACCT_EXIT);
        paragraph("9200-GETCARDXREF-BYACCT", this::do_9200_GETCARDXREF_BYACCT);
        paragraph("9200-GETCARDXREF-BYACCT-EXIT", this::do_9200_GETCARDXREF_BYACCT_EXIT);
        paragraph("9300-GETACCTDATA-BYACCT", this::do_9300_GETACCTDATA_BYACCT);
        paragraph("9300-GETACCTDATA-BYACCT-EXIT", this::do_9300_GETACCTDATA_BYACCT_EXIT);
        paragraph("9400-GETCUSTDATA-BYCUST", this::do_9400_GETCUSTDATA_BYCUST);
        paragraph("9400-GETCUSTDATA-BYCUST-EXIT", this::do_9400_GETCUSTDATA_BYCUST_EXIT);
        paragraph("9500-STORE-FETCHED-DATA", this::do_9500_STORE_FETCHED_DATA);
        paragraph("9500-STORE-FETCHED-DATA-EXIT", this::do_9500_STORE_FETCHED_DATA_EXIT);
        paragraph("9600-WRITE-PROCESSING", this::do_9600_WRITE_PROCESSING);
        paragraph("9600-WRITE-PROCESSING-EXIT", this::do_9600_WRITE_PROCESSING_EXIT);
        paragraph("9700-CHECK-CHANGE-IN-REC", this::do_9700_CHECK_CHANGE_IN_REC);
        paragraph("9700-CHECK-CHANGE-IN-REC-EXIT", this::do_9700_CHECK_CHANGE_IN_REC_EXIT);
    }

    void do_9000_READ_ACCT(ProgramState state) {
        state.put("ACUP-OLD-DETAILS", state.get("ACUP-OLD-DETAILS") instanceof Number ? 0 : "");
        state.put("WS-NO-INFO-MESSAGE", true);
        state.put("ACUP-OLD-ACCT-ID", state.get("CC-ACCT-ID"));
        performThru(state, "9200-GETCARDXREF-BYACCT", "9200-GETCARDXREF-BYACCT-EXIT");
        if (CobolRuntime.isTruthy(state.get("FLG-ACCTFILTER-NOT-OK"))) {
            state.addBranch(268);
            registry.get("9000-READ-ACCT-EXIT").execute(state);
            return;
        } else {
            state.addBranch(-268);
        }
        performThru(state, "9300-GETACCTDATA-BYACCT", "9300-GETACCTDATA-BYACCT-EXIT");
        if (CobolRuntime.isTruthy(state.get("DID-NOT-FIND-ACCT-IN-ACCTDAT"))) {
            state.addBranch(269);
            registry.get("9000-READ-ACCT-EXIT").execute(state);
            return;
        } else {
            state.addBranch(-269);
        }
        state.put("WS-CARD-RID-CUST-ID", state.get("CDEMO-CUST-ID"));
        performThru(state, "9400-GETCUSTDATA-BYCUST", "9400-GETCUSTDATA-BYCUST-EXIT");
        if (CobolRuntime.isTruthy(state.get("DID-NOT-FIND-CUST-IN-CUSTDAT"))) {
            state.addBranch(270);
            registry.get("9000-READ-ACCT-EXIT").execute(state);
            return;
        } else {
            state.addBranch(-270);
        }
        performThru(state, "9500-STORE-FETCHED-DATA", "9500-STORE-FETCHED-DATA-EXIT");
    }

    void do_9000_READ_ACCT_EXIT(ProgramState state) {
        // EXIT
    }

    void do_9200_GETCARDXREF_BYACCT(ProgramState state) {
        stubs.cicsRead(state, "LIT-CARDXREFNAME-ACCT-PATH", "WS-CARD-RID-ACCT-ID-X", "CARD-XREF-RECORD", "WS-RESP-CD", "WS-REAS-CD");
        Object _evalSubject8 = state.get("WS-RESP-CD");
        if (java.util.Objects.equals(_evalSubject8, 0)) {
            state.addBranch(271);
            state.put("CDEMO-CUST-ID", state.get("XREF-CUST-ID"));
            state.put("CDEMO-CARD-NUM", state.get("XREF-CARD-NUM"));
        }
        else if (java.util.Objects.equals(_evalSubject8, 13)) {
            state.addBranch(272);
            state.put("INPUT-ERROR", true);
            state.put("FLG-ACCTFILTER-NOT-OK", true);
            if (CobolRuntime.isTruthy(state.get("WS-RETURN-MSG-OFF"))) {
                state.addBranch(273);
                state.put("ERROR-RESP", state.get("WS-RESP-CD"));
                state.put("ERROR-RESP2", state.get("WS-REAS-CD"));
                state.put("WS-RETURN-MSG", "Account:" + String.valueOf(state.get("WS-CARD-RID-ACCT-ID-X")) + " not found in" + " Cross ref file.  Resp:" + String.valueOf(state.get("ERROR-RESP")) + " Reas:" + String.valueOf(state.get("ERROR-RESP2")));
            } else {
                state.addBranch(-273);
            }
        }
        else {
            state.addBranch(274);
            state.put("INPUT-ERROR", true);
            state.put("FLG-ACCTFILTER-NOT-OK", true);
            state.put("ERROR-OPNAME", "READ");
            state.put("ERROR-FILE", state.get("LIT-CARDXREFNAME-ACCT-PATH"));
            state.put("ERROR-RESP", state.get("WS-RESP-CD"));
            state.put("ERROR-RESP2", state.get("WS-REAS-CD"));
            state.put("WS-RETURN-MSG", state.get("WS-FILE-ERROR-MESSAGE"));
        }
    }

    void do_9200_GETCARDXREF_BYACCT_EXIT(ProgramState state) {
        // EXIT
    }

    void do_9300_GETACCTDATA_BYACCT(ProgramState state) {
        stubs.cicsRead(state, "LIT-ACCTFILENAME", "WS-CARD-RID-ACCT-ID-X", "ACCOUNT-RECORD", "WS-RESP-CD", "WS-REAS-CD");
        Object _evalSubject9 = state.get("WS-RESP-CD");
        if (java.util.Objects.equals(_evalSubject9, 0)) {
            state.addBranch(275);
            state.put("FOUND-ACCT-IN-MASTER", true);
        }
        else if (java.util.Objects.equals(_evalSubject9, 13)) {
            state.addBranch(276);
            state.put("INPUT-ERROR", true);
            state.put("FLG-ACCTFILTER-NOT-OK", true);
            if (CobolRuntime.isTruthy(state.get("WS-RETURN-MSG-OFF"))) {
                state.addBranch(277);
                state.put("ERROR-RESP", state.get("WS-RESP-CD"));
                state.put("ERROR-RESP2", state.get("WS-REAS-CD"));
                state.put("WS-RETURN-MSG", "Account:" + String.valueOf(state.get("WS-CARD-RID-ACCT-ID-X")) + " not found in" + " Acct Master file.Resp:" + String.valueOf(state.get("ERROR-RESP")) + " Reas:" + String.valueOf(state.get("ERROR-RESP2")));
            } else {
                state.addBranch(-277);
            }
        }
        else {
            state.addBranch(278);
            state.put("INPUT-ERROR", true);
            state.put("FLG-ACCTFILTER-NOT-OK", true);
            state.put("ERROR-OPNAME", "READ");
            state.put("ERROR-FILE", state.get("LIT-ACCTFILENAME"));
            state.put("ERROR-RESP", state.get("WS-RESP-CD"));
            state.put("ERROR-RESP2", state.get("WS-REAS-CD"));
            state.put("WS-RETURN-MSG", state.get("WS-FILE-ERROR-MESSAGE"));
        }
    }

    void do_9300_GETACCTDATA_BYACCT_EXIT(ProgramState state) {
        // EXIT
    }

    void do_9400_GETCUSTDATA_BYCUST(ProgramState state) {
        stubs.cicsRead(state, "LIT-CUSTFILENAME", "WS-CARD-RID-CUST-ID-X", "CUSTOMER-RECORD", "WS-RESP-CD", "WS-REAS-CD");
        Object _evalSubject10 = state.get("WS-RESP-CD");
        if (java.util.Objects.equals(_evalSubject10, 0)) {
            state.addBranch(279);
            state.put("FOUND-CUST-IN-MASTER", true);
        }
        else if (java.util.Objects.equals(_evalSubject10, 13)) {
            state.addBranch(280);
            state.put("INPUT-ERROR", true);
            state.put("FLG-CUSTFILTER-NOT-OK", true);
            state.put("ERROR-RESP", state.get("WS-RESP-CD"));
            state.put("ERROR-RESP2", state.get("WS-REAS-CD"));
            if (CobolRuntime.isTruthy(state.get("WS-RETURN-MSG-OFF"))) {
                state.addBranch(281);
                state.put("WS-RETURN-MSG", "CustId:" + String.valueOf(state.get("WS-CARD-RID-CUST-ID-X")) + " not found" + " in customer master.Resp: " + String.valueOf(state.get("ERROR-RESP")) + " REAS:" + String.valueOf(state.get("ERROR-RESP2")));
            } else {
                state.addBranch(-281);
            }
        }
        else {
            state.addBranch(282);
            state.put("INPUT-ERROR", true);
            state.put("FLG-CUSTFILTER-NOT-OK", true);
            state.put("ERROR-OPNAME", "READ");
            state.put("ERROR-FILE", state.get("LIT-CUSTFILENAME"));
            state.put("ERROR-RESP", state.get("WS-RESP-CD"));
            state.put("ERROR-RESP2", state.get("WS-REAS-CD"));
            state.put("WS-RETURN-MSG", state.get("WS-FILE-ERROR-MESSAGE"));
        }
    }

    void do_9400_GETCUSTDATA_BYCUST_EXIT(ProgramState state) {
        // EXIT
    }

    void do_9500_STORE_FETCHED_DATA(ProgramState state) {
        state.put("CDEMO-ACCT-ID", state.get("ACCT-ID"));
        state.put("CDEMO-CUST-ID", state.get("CUST-ID"));
        state.put("CDEMO-CUST-FNAME", state.get("CUST-FIRST-NAME"));
        state.put("CDEMO-CUST-MNAME", state.get("CUST-MIDDLE-NAME"));
        state.put("CDEMO-CUST-LNAME", state.get("CUST-LAST-NAME"));
        state.put("CDEMO-ACCT-STATUS", state.get("ACCT-ACTIVE-STATUS"));
        state.put("CDEMO-CARD-NUM", state.get("XREF-CARD-NUM"));
        state.put("ACUP-OLD-DETAILS", state.get("ACUP-OLD-DETAILS") instanceof Number ? 0 : "");
        state.put("ACUP-OLD-ACCT-ID", state.get("ACCT-ID"));
        state.put("ACUP-OLD-ACTIVE-STATUS", state.get("ACCT-ACTIVE-STATUS"));
        state.put("ACUP-OLD-CURR-BAL-N", state.get("ACCT-CURR-BAL"));
        state.put("ACUP-OLD-CREDIT-LIMIT-N", state.get("ACCT-CREDIT-LIMIT"));
        state.put("ACUP-OLD-CASH-CREDIT-LIMIT-N", state.get("ACCT-CASH-CREDIT-LIMIT"));
        state.put("ACUP-OLD-CURR-CYC-CREDIT-N", state.get("ACCT-CURR-CYC-CREDIT"));
        state.put("ACUP-OLD-CURR-CYC-DEBIT-N", state.get("ACCT-CURR-CYC-DEBIT"));
        state.put("ACUP-OLD-OPEN-YEAR", (String.valueOf(state.get("ACCT-OPEN-DATE")).length() > 0 ? String.valueOf(state.get("ACCT-OPEN-DATE")).substring(0, Math.min(4, String.valueOf(state.get("ACCT-OPEN-DATE")).length())) : ""));
        state.put("ACUP-OLD-OPEN-MON", (String.valueOf(state.get("ACCT-OPEN-DATE")).length() > 5 ? String.valueOf(state.get("ACCT-OPEN-DATE")).substring(5, Math.min(7, String.valueOf(state.get("ACCT-OPEN-DATE")).length())) : ""));
        state.put("ACUP-OLD-OPEN-DAY", (String.valueOf(state.get("ACCT-OPEN-DATE")).length() > 8 ? String.valueOf(state.get("ACCT-OPEN-DATE")).substring(8, Math.min(10, String.valueOf(state.get("ACCT-OPEN-DATE")).length())) : ""));
        state.put("ACUP-OLD-EXP-YEAR", (String.valueOf(state.get("ACCT-EXPIRAION-DATE")).length() > 0 ? String.valueOf(state.get("ACCT-EXPIRAION-DATE")).substring(0, Math.min(4, String.valueOf(state.get("ACCT-EXPIRAION-DATE")).length())) : ""));
        state.put("ACUP-OLD-EXP-MON", (String.valueOf(state.get("ACCT-EXPIRAION-DATE")).length() > 5 ? String.valueOf(state.get("ACCT-EXPIRAION-DATE")).substring(5, Math.min(7, String.valueOf(state.get("ACCT-EXPIRAION-DATE")).length())) : ""));
        state.put("ACUP-OLD-EXP-DAY", (String.valueOf(state.get("ACCT-EXPIRAION-DATE")).length() > 8 ? String.valueOf(state.get("ACCT-EXPIRAION-DATE")).substring(8, Math.min(10, String.valueOf(state.get("ACCT-EXPIRAION-DATE")).length())) : ""));
        state.put("ACUP-OLD-REISSUE-YEAR", (String.valueOf(state.get("ACCT-REISSUE-DATE")).length() > 0 ? String.valueOf(state.get("ACCT-REISSUE-DATE")).substring(0, Math.min(4, String.valueOf(state.get("ACCT-REISSUE-DATE")).length())) : ""));
        state.put("ACUP-OLD-REISSUE-MON", (String.valueOf(state.get("ACCT-REISSUE-DATE")).length() > 5 ? String.valueOf(state.get("ACCT-REISSUE-DATE")).substring(5, Math.min(7, String.valueOf(state.get("ACCT-REISSUE-DATE")).length())) : ""));
        state.put("ACUP-OLD-REISSUE-DAY", (String.valueOf(state.get("ACCT-REISSUE-DATE")).length() > 8 ? String.valueOf(state.get("ACCT-REISSUE-DATE")).substring(8, Math.min(10, String.valueOf(state.get("ACCT-REISSUE-DATE")).length())) : ""));
        state.put("ACUP-OLD-GROUP-ID", state.get("ACCT-GROUP-ID"));
        state.put("ACUP-OLD-CUST-ID", state.get("CUST-ID"));
        state.put("ACUP-OLD-CUST-SSN", state.get("CUST-SSN"));
        state.put("ACUP-OLD-CUST-DOB-YEAR", (String.valueOf(state.get("CUST-DOB-YYYY-MM-DD")).length() > 0 ? String.valueOf(state.get("CUST-DOB-YYYY-MM-DD")).substring(0, Math.min(4, String.valueOf(state.get("CUST-DOB-YYYY-MM-DD")).length())) : ""));
        state.put("ACUP-OLD-CUST-DOB-MON", (String.valueOf(state.get("CUST-DOB-YYYY-MM-DD")).length() > 5 ? String.valueOf(state.get("CUST-DOB-YYYY-MM-DD")).substring(5, Math.min(7, String.valueOf(state.get("CUST-DOB-YYYY-MM-DD")).length())) : ""));
        state.put("ACUP-OLD-CUST-DOB-DAY", (String.valueOf(state.get("CUST-DOB-YYYY-MM-DD")).length() > 8 ? String.valueOf(state.get("CUST-DOB-YYYY-MM-DD")).substring(8, Math.min(10, String.valueOf(state.get("CUST-DOB-YYYY-MM-DD")).length())) : ""));
        state.put("ACUP-OLD-CUST-FICO-SCORE", state.get("CUST-FICO-CREDIT-SCORE"));
        state.put("ACUP-OLD-CUST-FIRST-NAME", state.get("CUST-FIRST-NAME"));
        state.put("ACUP-OLD-CUST-MIDDLE-NAME", state.get("CUST-MIDDLE-NAME"));
        state.put("ACUP-OLD-CUST-LAST-NAME", state.get("CUST-LAST-NAME"));
        state.put("ACUP-OLD-CUST-ADDR-LINE-1", state.get("CUST-ADDR-LINE-1"));
        state.put("ACUP-OLD-CUST-ADDR-LINE-2", state.get("CUST-ADDR-LINE-2"));
        state.put("ACUP-OLD-CUST-ADDR-LINE-3", state.get("CUST-ADDR-LINE-3"));
        state.put("ACUP-OLD-CUST-ADDR-STATE-CD", state.get("CUST-ADDR-STATE-CD"));
        state.put("ACUP-OLD-CUST-ADDR-COUNTRY-CD", state.get("CUST-ADDR-COUNTRY-CD"));
        state.put("ACUP-OLD-CUST-ADDR-ZIP", state.get("CUST-ADDR-ZIP"));
        state.put("ACUP-OLD-CUST-PHONE-NUM-1", state.get("CUST-PHONE-NUM-1"));
        state.put("ACUP-OLD-CUST-PHONE-NUM-2", state.get("CUST-PHONE-NUM-2"));
        state.put("ACUP-OLD-CUST-GOVT-ISSUED-ID", state.get("CUST-GOVT-ISSUED-ID"));
        state.put("ACUP-OLD-CUST-EFT-ACCOUNT-ID", state.get("CUST-EFT-ACCOUNT-ID"));
        state.put("ACUP-OLD-CUST-PRI-HOLDER-IND", state.get("CUST-PRI-CARD-HOLDER-IND"));
    }

    void do_9500_STORE_FETCHED_DATA_EXIT(ProgramState state) {
        // EXIT
    }

    void do_9600_WRITE_PROCESSING(ProgramState state) {
        state.put("WS-CARD-RID-ACCT-ID", state.get("CC-ACCT-ID"));
        stubs.dummyExec(state, "CICS", "EXEC CICS READ FILE      (LIT-ACCTFILENAME) UPDATE RIDFLD    (WS-CARD-RID-ACCT-ID-X) KEYLENGTH (LENGTH OF WS-CARD-RID-ACCT-ID-X) INTO      (ACCOUNT-RECORD) LENGTH    (LENGTH OF ACCOUNT-RECORD) RESP   ...");
        if (java.util.Objects.equals(state.get("WS-RESP-CD"), 0)) {
            state.addBranch(283);
            // CONTINUE
        } else {
            state.addBranch(-283);
            state.put("INPUT-ERROR", true);
            if (CobolRuntime.isTruthy(state.get("WS-RETURN-MSG-OFF"))) {
                state.addBranch(284);
                state.put("COULD-NOT-LOCK-ACCT-FOR-UPDATE", true);
            } else {
                state.addBranch(-284);
            }
            registry.get("9600-WRITE-PROCESSING-EXIT").execute(state);
            return;
        }
        state.put("WS-CARD-RID-CUST-ID", state.get("CDEMO-CUST-ID"));
        stubs.dummyExec(state, "CICS", "EXEC CICS READ FILE      (LIT-CUSTFILENAME) UPDATE RIDFLD    (WS-CARD-RID-CUST-ID-X) KEYLENGTH (LENGTH OF WS-CARD-RID-CUST-ID-X) INTO      (CUSTOMER-RECORD) LENGTH    (LENGTH OF CUSTOMER-RECORD) RESP ...");
        if (java.util.Objects.equals(state.get("WS-RESP-CD"), 0)) {
            state.addBranch(285);
            // CONTINUE
        } else {
            state.addBranch(-285);
            state.put("INPUT-ERROR", true);
            if (CobolRuntime.isTruthy(state.get("WS-RETURN-MSG-OFF"))) {
                state.addBranch(286);
                state.put("COULD-NOT-LOCK-CUST-FOR-UPDATE", true);
            } else {
                state.addBranch(-286);
            }
            registry.get("9600-WRITE-PROCESSING-EXIT").execute(state);
            return;
        }
        performThru(state, "9700-CHECK-CHANGE-IN-REC", "9700-CHECK-CHANGE-IN-REC-EXIT");
        if (CobolRuntime.isTruthy(state.get("DATA-WAS-CHANGED-BEFORE-UPDATE"))) {
            state.addBranch(287);
            registry.get("9600-WRITE-PROCESSING-EXIT").execute(state);
            return;
        } else {
            state.addBranch(-287);
        }
        state.put("ACCT-UPDATE-RECORD", state.get("ACCT-UPDATE-RECORD") instanceof Number ? 0 : "");
        state.put("ACCT-UPDATE-ID", state.get("ACUP-NEW-ACCT-ID"));
        state.put("ACCT-UPDATE-ACTIVE-STATUS", state.get("ACUP-NEW-ACTIVE-STATUS"));
        state.put("ACCT-UPDATE-CURR-BAL", state.get("ACUP-NEW-CURR-BAL-N"));
        state.put("ACCT-UPDATE-CREDIT-LIMIT", state.get("ACUP-NEW-CREDIT-LIMIT-N"));
        state.put("ACCT-UPDATE-CASH-CREDIT-LIMIT", state.get("ACUP-NEW-CASH-CREDIT-LIMIT-N"));
        state.put("ACCT-UPDATE-CURR-CYC-CREDIT", state.get("ACUP-NEW-CURR-CYC-CREDIT-N"));
        state.put("ACCT-UPDATE-CURR-CYC-DEBIT", state.get("ACUP-NEW-CURR-CYC-DEBIT-N"));
        state.put("ACCT-UPDATE-OPEN-DATE", String.valueOf(state.get("ACUP-NEW-OPEN-YEAR")) + "-" + String.valueOf(state.get("ACUP-NEW-OPEN-MON")) + "-" + String.valueOf(state.get("ACUP-NEW-OPEN-DAY")));
        state.put("ACCT-UPDATE-EXPIRAION-DATE", String.valueOf(state.get("ACUP-NEW-EXP-YEAR")) + "-" + String.valueOf(state.get("ACUP-NEW-EXP-MON")) + "-" + String.valueOf(state.get("ACUP-NEW-EXP-DAY")));
        state.put("ACCT-UPDATE-REISSUE-DATE", state.get("ACCT-REISSUE-DATE"));
        state.put("ACCT-UPDATE-REISSUE-DATE", String.valueOf(state.get("ACUP-NEW-REISSUE-YEAR")) + "-" + String.valueOf(state.get("ACUP-NEW-REISSUE-MON")) + "-" + String.valueOf(state.get("ACUP-NEW-REISSUE-DAY")));
        state.put("ACCT-UPDATE-GROUP-ID", state.get("ACUP-NEW-GROUP-ID"));
        state.put("CUST-UPDATE-RECORD", state.get("CUST-UPDATE-RECORD") instanceof Number ? 0 : "");
        state.put("CUST-UPDATE-ID", state.get("ACUP-NEW-CUST-ID"));
        state.put("CUST-UPDATE-FIRST-NAME", state.get("ACUP-NEW-CUST-FIRST-NAME"));
        state.put("CUST-UPDATE-MIDDLE-NAME", state.get("ACUP-NEW-CUST-MIDDLE-NAME"));
        state.put("CUST-UPDATE-LAST-NAME", state.get("ACUP-NEW-CUST-LAST-NAME"));
        state.put("CUST-UPDATE-ADDR-LINE-1", state.get("ACUP-NEW-CUST-ADDR-LINE-1"));
        state.put("CUST-UPDATE-ADDR-LINE-2", state.get("ACUP-NEW-CUST-ADDR-LINE-2"));
        state.put("CUST-UPDATE-ADDR-LINE-3", state.get("ACUP-NEW-CUST-ADDR-LINE-3"));
        state.put("CUST-UPDATE-ADDR-STATE-CD", state.get("ACUP-NEW-CUST-ADDR-STATE-CD"));
        state.put("CUST-UPDATE-ADDR-COUNTRY-CD", state.get("ACUP-NEW-CUST-ADDR-COUNTRY-CD"));
        state.put("CUST-UPDATE-ADDR-ZIP", state.get("ACUP-NEW-CUST-ADDR-ZIP"));
        state.put("CUST-UPDATE-PHONE-NUM-1", "(" + String.valueOf(state.get("ACUP-NEW-CUST-PHONE-NUM-1A")) + ")" + String.valueOf(state.get("ACUP-NEW-CUST-PHONE-NUM-1B")) + "-" + String.valueOf(state.get("ACUP-NEW-CUST-PHONE-NUM-1C")));
        state.put("CUST-UPDATE-PHONE-NUM-2", "(" + String.valueOf(state.get("ACUP-NEW-CUST-PHONE-NUM-2A")) + ")" + String.valueOf(state.get("ACUP-NEW-CUST-PHONE-NUM-2B")) + "-" + String.valueOf(state.get("ACUP-NEW-CUST-PHONE-NUM-2C")));
        state.put("CUST-UPDATE-SSN", state.get("ACUP-NEW-CUST-SSN"));
        state.put("CUST-UPDATE-GOVT-ISSUED-ID", state.get("ACUP-NEW-CUST-GOVT-ISSUED-ID"));
        state.put("CUST-UPDATE-DOB-YYYY-MM-DD", String.valueOf(state.get("ACUP-NEW-CUST-DOB-YEAR")) + "-" + String.valueOf(state.get("ACUP-NEW-CUST-DOB-MON")) + "-" + String.valueOf(state.get("ACUP-NEW-CUST-DOB-DAY")));
        state.put("CUST-UPDATE-EFT-ACCOUNT-ID", state.get("ACUP-NEW-CUST-EFT-ACCOUNT-ID"));
        state.put("CUST-UPDATE-PRI-CARD-IND", state.get("ACUP-NEW-CUST-PRI-HOLDER-IND"));
        state.put("CUST-UPDATE-FICO-CREDIT-SCORE", state.get("ACUP-NEW-CUST-FICO-SCORE"));
        stubs.dummyExec(state, "CICS", "EXEC CICS REWRITE FILE(LIT-ACCTFILENAME) FROM(ACCT-UPDATE-RECORD) LENGTH(LENGTH OF ACCT-UPDATE-RECORD) RESP      (WS-RESP-CD) RESP2     (WS-REAS-CD) END-EXEC.");
        if (java.util.Objects.equals(state.get("WS-RESP-CD"), 0)) {
            state.addBranch(288);
            // CONTINUE
        } else {
            state.addBranch(-288);
            state.put("LOCKED-BUT-UPDATE-FAILED", true);
            registry.get("9600-WRITE-PROCESSING-EXIT").execute(state);
            return;
        }
        stubs.dummyExec(state, "CICS", "EXEC CICS REWRITE FILE(LIT-CUSTFILENAME) FROM(CUST-UPDATE-RECORD) LENGTH(LENGTH OF CUST-UPDATE-RECORD) RESP      (WS-RESP-CD) RESP2     (WS-REAS-CD) END-EXEC.");
        if (java.util.Objects.equals(state.get("WS-RESP-CD"), 0)) {
            state.addBranch(289);
            // CONTINUE
        } else {
            state.addBranch(-289);
            state.put("LOCKED-BUT-UPDATE-FAILED", true);
            stubs.cicsSyncpoint(state);
            registry.get("9600-WRITE-PROCESSING-EXIT").execute(state);
            return;
        }
    }

    void do_9600_WRITE_PROCESSING_EXIT(ProgramState state) {
        // EXIT
    }

    void do_9700_CHECK_CHANGE_IN_REC(ProgramState state) {
        if ((((((((((((((((java.util.Objects.equals(state.get("ACCT-ACTIVE-STATUS"), state.get("ACUP-OLD-ACTIVE-STATUS"))) && (java.util.Objects.equals(state.get("ACCT-CURR-BAL"), state.get("ACUP-OLD-CURR-BAL-N")))) && (java.util.Objects.equals(state.get("ACCT-CREDIT-LIMIT"), state.get("ACUP-OLD-CREDIT-LIMIT-N")))) && (java.util.Objects.equals(state.get("ACCT-CASH-CREDIT-LIMIT"), state.get("ACUP-OLD-CASH-CREDIT-LIMIT-N")))) && (java.util.Objects.equals(state.get("ACCT-CURR-CYC-CREDIT"), state.get("ACUP-OLD-CURR-CYC-CREDIT-N")))) && (java.util.Objects.equals(state.get("ACCT-CURR-CYC-DEBIT"), state.get("ACUP-OLD-CURR-CYC-DEBIT-N")))) && (java.util.Objects.equals(state.get("ACCT-OPEN-DATE(1:4)"), state.get("ACUP-OLD-OPEN-YEAR")))) && (java.util.Objects.equals(state.get("ACCT-OPEN-DATE(6:2)"), state.get("ACUP-OLD-OPEN-MON")))) && (java.util.Objects.equals(state.get("ACCT-OPEN-DATE(9:2)"), state.get("ACUP-OLD-OPEN-DAY")))) && (java.util.Objects.equals(state.get("ACCT-EXPIRAION-DATE(1:4)"), state.get("ACUP-OLD-EXP-YEAR")))) && (java.util.Objects.equals(state.get("ACCT-EXPIRAION-DATE(6:2)"), state.get("ACUP-OLD-EXP-MON")))) && (java.util.Objects.equals(state.get("ACCT-EXPIRAION-DATE(9:2)"), state.get("ACUP-OLD-EXP-DAY")))) && (java.util.Objects.equals(state.get("ACCT-REISSUE-DATE(1:4)"), state.get("ACUP-OLD-REISSUE-YEAR")))) && (java.util.Objects.equals(state.get("ACCT-REISSUE-DATE(6:2)"), state.get("ACUP-OLD-REISSUE-MON")))) && (java.util.Objects.equals(state.get("ACCT-REISSUE-DATE(9:2)"), state.get("ACUP-OLD-REISSUE-DAY")))) && (CobolRuntime.isTruthy(state.get("FUNCTION")))) {
            state.addBranch(290);
            // CONTINUE
        } else {
            state.addBranch(-290);
            state.put("DATA-WAS-CHANGED-BEFORE-UPDATE", true);
            registry.get("9600-WRITE-PROCESSING-EXIT").execute(state);
            return;
        }
        if (CobolRuntime.isTruthy(state.get("FUNCTION"))) {
            state.addBranch(291);
            // CONTINUE
        } else {
            state.addBranch(-291);
            state.put("DATA-WAS-CHANGED-BEFORE-UPDATE", true);
            registry.get("9600-WRITE-PROCESSING-EXIT").execute(state);
            return;
        }
    }

    void do_9700_CHECK_CHANGE_IN_REC_EXIT(ProgramState state) {
        // EXIT
        // UNKNOWN: COPY 'CSSTRPFY'
    }

}
