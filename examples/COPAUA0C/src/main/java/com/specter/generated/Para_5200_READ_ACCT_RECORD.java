package com.specter.generated;

/**
 * Generated paragraph: 5200-READ-ACCT-RECORD.
 */
public class Para_5200_READ_ACCT_RECORD extends Paragraph {

    public Para_5200_READ_ACCT_RECORD(ParagraphRegistry registry, StubExecutor stubs) {
        super("5200-READ-ACCT-RECORD", registry, stubs);
    }

    @Override
    protected void doExecute(ProgramState state) {
        state.put("WS-CARD-RID-ACCT-ID", state.get("XREF-ACCT-ID"));
        stubs.dummyExec(state, "CICS", "EXEC CICS READ DATASET   (WS-ACCTFILENAME) RIDFLD    (WS-CARD-RID-ACCT-ID-X) KEYLENGTH (LENGTH OF WS-CARD-RID-ACCT-ID-X) INTO      (ACCOUNT-RECORD) LENGTH    (LENGTH OF ACCOUNT-RECORD) RESP      (WS-R...");
        Object _evalSubject = state.get("WS-RESP-CD");
        if (java.util.Objects.equals(_evalSubject, 0)) {
            state.addBranch(14);
            state.put("FOUND-ACCT-IN-MSTR", true);
        }
        else if (java.util.Objects.equals(_evalSubject, 13)) {
            state.addBranch(15);
            state.put("NFOUND-ACCT-IN-MSTR", true);
            state.put("ERR-LOCATION", "A002");
            state.put("ERR-WARNING", true);
            state.put("ERR-APP", true);
            state.put("ERR-MESSAGE", "ACCT NOT FOUND IN XREF");
            state.put("ERR-EVENT-KEY", state.get("WS-CARD-RID-ACCT-ID-X"));
            perform(state, "9500-LOG-ERROR");
        }
        else {
            state.addBranch(16);
            state.put("ERR-LOCATION", "C002");
            state.put("ERR-CRITICAL", true);
            state.put("ERR-CICS", true);
            state.put("WS-CODE-DISPLAY", state.get("WS-RESP-CD"));
            state.put("ERR-CODE-1", state.get("WS-CODE-DISPLAY"));
            state.put("WS-CODE-DISPLAY", state.get("WS-REAS-CD"));
            state.put("ERR-CODE-2", state.get("WS-CODE-DISPLAY"));
            state.put("READ", state.get("FAILED"));
            state.put("ACCT", state.get("FAILED"));
            state.put("FILE", state.get("FAILED"));
            state.put("ERR-EVENT-KEY", state.get("WS-CARD-RID-ACCT-ID-X"));
            perform(state, "9500-LOG-ERROR");
        }
    }
}
