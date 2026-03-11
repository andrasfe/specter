package com.specter.generated;

/**
 * Generated paragraph: 5500-READ-AUTH-SUMMRY.
 */
public class Para_5500_READ_AUTH_SUMMRY extends Paragraph {

    public Para_5500_READ_AUTH_SUMMRY(ParagraphRegistry registry, StubExecutor stubs) {
        super("5500-READ-AUTH-SUMMRY", registry, stubs);
    }

    @Override
    protected void doExecute(ProgramState state) {
        state.put("PA-ACCT-ID", state.get("XREF-ACCT-ID"));
        stubs.dummyExec(state, "DLI", "EXEC DLI GU USING PCB(PAUT-PCB-NUM) SEGMENT (PAUTSUM0) INTO (PENDING-AUTH-SUMMARY) WHERE (ACCNTID = PA-ACCT-ID) END-EXEC");
        state.put("IMS-RETURN-CODE", state.get("DIBSTAT"));
        if (CobolRuntime.isTruthy(state.get("STATUS-OK"))) {
            state.addBranch(20);
            state.put("FOUND-PAUT-SMRY-SEG", true);
        }
        else if (CobolRuntime.isTruthy(state.get("SEGMENT-NOT-FOUND"))) {
            state.addBranch(21);
            state.put("NFOUND-PAUT-SMRY-SEG", true);
        }
        else {
            state.addBranch(22);
            state.put("ERR-LOCATION", "I002");
            state.put("ERR-CRITICAL", true);
            state.put("ERR-IMS", true);
            state.put("ERR-CODE-1", state.get("IMS-RETURN-CODE"));
            state.put("ERR-MESSAGE", "IMS GET SUMMARY FAILED");
            state.put("ERR-EVENT-KEY", state.get("PA-CARD-NUM"));
            perform(state, "9500-LOG-ERROR");
        }
    }
}
