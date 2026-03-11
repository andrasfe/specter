package com.specter.generated;

/**
 * Generated paragraph: 8500-INSERT-AUTH.
 */
public class Para_8500_INSERT_AUTH extends Paragraph {

    public Para_8500_INSERT_AUTH(ParagraphRegistry registry, StubExecutor stubs) {
        super("8500-INSERT-AUTH", registry, stubs);
    }

    @Override
    protected void doExecute(ProgramState state) {
        stubs.dummyExec(state, "CICS", "EXEC CICS ASKTIME NOHANDLE ABSTIME(WS-ABS-TIME) END-EXEC");
        stubs.dummyExec(state, "CICS", "EXEC CICS FORMATTIME ABSTIME(WS-ABS-TIME) YYDDD(WS-CUR-DATE-X6) TIME(WS-CUR-TIME-X6) MILLISECONDS(WS-CUR-TIME-MS) END-EXEC");
        state.put("WS-YYDDD", String.valueOf(state.get("WS-CUR-DATE-X6")).substring(0, Math.min(5, String.valueOf(state.get("WS-CUR-DATE-X6")).length())));
        state.put("WS-CUR-TIME-N6", state.get("WS-CUR-TIME-X6"));
        state.put("WS-TIME-WITH-MS", (CobolRuntime.toNum(state.get("WS-CUR-TIME-N6")) * 1000) +);
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
        stubs.dummyExec(state, "DLI", "EXEC DLI ISRT USING PCB(PAUT-PCB-NUM) SEGMENT (PAUTSUM0) WHERE (ACCNTID = PA-ACCT-ID) SEGMENT (PAUTDTL1) FROM (PENDING-AUTH-DETAILS) SEGLENGTH (LENGTH OF PENDING-AUTH-DETAILS) END-EXEC");
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
}
