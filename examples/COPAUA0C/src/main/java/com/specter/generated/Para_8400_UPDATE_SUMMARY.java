package com.specter.generated;

/**
 * Generated paragraph: 8400-UPDATE-SUMMARY.
 */
public class Para_8400_UPDATE_SUMMARY extends Paragraph {

    public Para_8400_UPDATE_SUMMARY(ParagraphRegistry registry, StubExecutor stubs) {
        super("8400-UPDATE-SUMMARY", registry, stubs);
    }

    @Override
    protected void doExecute(ProgramState state) {
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
            stubs.dummyExec(state, "DLI", "EXEC DLI REPL USING PCB(PAUT-PCB-NUM) SEGMENT (PAUTSUM0) FROM (PENDING-AUTH-SUMMARY) END-EXEC");
        } else {
            state.addBranch(-41);
            stubs.dummyExec(state, "DLI", "EXEC DLI ISRT USING PCB(PAUT-PCB-NUM) SEGMENT (PAUTSUM0) FROM (PENDING-AUTH-SUMMARY) END-EXEC");
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
}
