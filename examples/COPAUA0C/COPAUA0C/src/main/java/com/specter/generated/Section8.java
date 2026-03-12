package com.specter.generated;

/**
 * Generated section: Section8.
 */
public class Section8 extends SectionBase {

    public Section8(ParagraphRegistry registry, StubExecutor stubs) {
        super(registry, stubs);
        paragraph("8000-WRITE-AUTH-TO-DB", this::do_8000_WRITE_AUTH_TO_DB);
        paragraph("8000-EXIT", this::do_8000_EXIT);
        paragraph("8400-UPDATE-SUMMARY", this::do_8400_UPDATE_SUMMARY);
        paragraph("8400-EXIT", this::do_8400_EXIT);
        paragraph("8500-INSERT-AUTH", this::do_8500_INSERT_AUTH);
        paragraph("8500-EXIT", this::do_8500_EXIT);
    }

    void do_8000_WRITE_AUTH_TO_DB(ProgramState state) {
        performThru(state, "8400-UPDATE-SUMMARY", "8400-EXIT");
        performThru(state, "8500-INSERT-AUTH", "8500-EXIT");
    }

    void do_8000_EXIT(ProgramState state) {
        // EXIT
    }

    void do_8400_UPDATE_SUMMARY(ProgramState state) {
        if (CobolRuntime.isTruthy(state.get("NFOUND-PAUT-SMRY-SEG"))) {
            state.addBranch(39);
            state.put("PENDING-AUTH-SUMMARY", state.get("PENDING-AUTH-SUMMARY") instanceof Number ? 0 : "");
            state.put("PA-ACCT-ID", state.get("XREF-ACCT-ID"));
            state.put("PA-CUST-ID", state.get("XREF-CUST-ID"));
        } else {
            state.addBranch(-39);
        }
        state.put("PA-CREDIT-LIMIT", state.get("ACCT-CREDIT-LIMIT"));
        state.put("PA-CASH-LIMIT", state.get("ACCT-CASH-CREDIT-LIMIT"));
        if (CobolRuntime.isTruthy(state.get("AUTH-RESP-APPROVED"))) {
            state.addBranch(40);
            state.put("PA-APPROVED-AUTH-CNT", CobolRuntime.toNum(state.get("PA-APPROVED-AUTH-CNT")) + 1);
            state.put("PA-APPROVED-AUTH-AMT", CobolRuntime.toNum(state.get("PA-APPROVED-AUTH-AMT")) + CobolRuntime.toNum(state.get("WS-APPROVED-AMT")));
            state.put("PA-CREDIT-BALANCE", CobolRuntime.toNum(state.get("PA-CREDIT-BALANCE")) + CobolRuntime.toNum(state.get("WS-APPROVED-AMT")));
            state.put("PA-CASH-BALANCE", 0);
        } else {
            state.addBranch(-40);
            state.put("PA-DECLINED-AUTH-CNT", CobolRuntime.toNum(state.get("PA-DECLINED-AUTH-CNT")) + 1);
            state.put("PA-DECLINED-AUTH-AMT", CobolRuntime.toNum(state.get("PA-DECLINED-AUTH-AMT")) + CobolRuntime.toNum(state.get("PA-TRANSACTION-AMT")));
        }
        if (CobolRuntime.isTruthy(state.get("FOUND-PAUT-SMRY-SEG"))) {
            state.addBranch(41);
            stubs.dliReplace(state, "PAUTSUM0", "PENDING-AUTH-SUMMARY");
        } else {
            state.addBranch(-41);
            stubs.dliInsert(state, "PAUTSUM0", "PENDING-AUTH-SUMMARY");
        }
        state.put("IMS-RETURN-CODE", state.get("DIBSTAT"));
        if (CobolRuntime.isTruthy(state.get("STATUS-OK"))) {
            state.addBranch(42);
            // CONTINUE
        } else {
            state.addBranch(-42);
            state.put("ERR-LOCATION", "I003");
            state.put("ERR-CRITICAL", true);
            state.put("ERR-IMS", true);
            state.put("ERR-CODE-1", state.get("IMS-RETURN-CODE"));
            state.put("ERR-MESSAGE", "IMS UPDATE SUMRY FAILED");
            state.put("ERR-EVENT-KEY", state.get("PA-CARD-NUM"));
            perform(state, "9500-LOG-ERROR");
        }
    }

    void do_8400_EXIT(ProgramState state) {
        // EXIT
    }

    void do_8500_INSERT_AUTH(ProgramState state) {
        stubs.cicsAsktime(state, "WS-ABS-TIME");
        stubs.cicsFormattime(state, "WS-ABS-TIME", "WS-CUR-DATE-X6", "WS-CUR-TIME-X6", "WS-CUR-TIME-MS");
        state.put("WS-YYDDD", String.valueOf(state.get("WS-CUR-DATE-X6")).substring(0, Math.min(5, String.valueOf(state.get("WS-CUR-DATE-X6")).length())));
        state.put("WS-CUR-TIME-N6", state.get("WS-CUR-TIME-X6"));
        state.put("WS-TIME-WITH-MS", (CobolRuntime.toNum(state.get("WS-CUR-TIME-N6")) * 1000));
        state.put("PA-AUTH-DATE-9C", 99999 - CobolRuntime.toNum(state.get("WS-YYDDD")));
        state.put("PA-AUTH-TIME-9C", 999999999 - CobolRuntime.toNum(state.get("WS-TIME-WITH-MS")));
        state.put("PA-AUTH-ORIG-DATE", state.get("PA-RQ-AUTH-DATE"));
        state.put("PA-AUTH-ORIG-TIME", state.get("PA-RQ-AUTH-TIME"));
        state.put("PA-CARD-NUM", state.get("PA-RQ-CARD-NUM"));
        state.put("PA-AUTH-TYPE", state.get("PA-RQ-AUTH-TYPE"));
        state.put("PA-CARD-EXPIRY-DATE", state.get("PA-RQ-CARD-EXPIRY-DATE"));
        state.put("PA-MESSAGE-TYPE", state.get("PA-RQ-MESSAGE-TYPE"));
        state.put("PA-MESSAGE-SOURCE", state.get("PA-RQ-MESSAGE-SOURCE"));
        state.put("PA-PROCESSING-CODE", state.get("PA-RQ-PROCESSING-CODE"));
        state.put("PA-TRANSACTION-AMT", state.get("PA-RQ-TRANSACTION-AMT"));
        state.put("PA-MERCHANT-CATAGORY-CODE", state.get("PA-RQ-MERCHANT-CATAGORY-CODE"));
        state.put("PA-ACQR-COUNTRY-CODE", state.get("PA-RQ-ACQR-COUNTRY-CODE"));
        state.put("PA-POS-ENTRY-MODE", state.get("PA-RQ-POS-ENTRY-MODE"));
        state.put("PA-MERCHANT-ID", state.get("PA-RQ-MERCHANT-ID"));
        state.put("PA-MERCHANT-NAME", state.get("PA-RQ-MERCHANT-NAME"));
        state.put("PA-MERCHANT-CITY", state.get("PA-RQ-MERCHANT-CITY"));
        state.put("PA-MERCHANT-STATE", state.get("PA-RQ-MERCHANT-STATE"));
        state.put("PA-MERCHANT-ZIP", state.get("PA-RQ-MERCHANT-ZIP"));
        state.put("PA-TRANSACTION-ID", state.get("PA-RQ-TRANSACTION-ID"));
        state.put("PA-AUTH-ID-CODE", state.get("PA-RL-AUTH-ID-CODE"));
        state.put("PA-AUTH-RESP-CODE", state.get("PA-RL-AUTH-RESP-CODE"));
        state.put("PA-AUTH-RESP-REASON", state.get("PA-RL-AUTH-RESP-REASON"));
        state.put("PA-APPROVED-AMT", state.get("PA-RL-APPROVED-AMT"));
        if (CobolRuntime.isTruthy(state.get("AUTH-RESP-APPROVED"))) {
            state.addBranch(43);
            state.put("PA-MATCH-PENDING", true);
        } else {
            state.addBranch(-43);
            state.put("PA-MATCH-AUTH-DECLINED", true);
        }
        state.put("PA-AUTH-FRAUD", " ");
        state.put("PA-ACCT-ID", state.get("XREF-ACCT-ID"));
        stubs.dliInsertChild(state, "PAUTSUM0", "ACCNTID", "PA-ACCT-ID", "PAUTDTL1", "PENDING-AUTH-DETAILS");
        state.put("IMS-RETURN-CODE", state.get("DIBSTAT"));
        if (CobolRuntime.isTruthy(state.get("STATUS-OK"))) {
            state.addBranch(44);
            // CONTINUE
        } else {
            state.addBranch(-44);
            state.put("ERR-LOCATION", "I004");
            state.put("ERR-CRITICAL", true);
            state.put("ERR-IMS", true);
            state.put("ERR-CODE-1", state.get("IMS-RETURN-CODE"));
            state.put("ERR-MESSAGE", "IMS INSERT DETL FAILED");
            state.put("ERR-EVENT-KEY", state.get("PA-CARD-NUM"));
            perform(state, "9500-LOG-ERROR");
        }
    }

    void do_8500_EXIT(ProgramState state) {
        // EXIT
    }

}
