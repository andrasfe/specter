package com.specter.generated;

/**
 * Generated paragraph: 5100-READ-XREF-RECORD.
 */
public class Para_5100_READ_XREF_RECORD extends Paragraph {

    public Para_5100_READ_XREF_RECORD(ParagraphRegistry registry, StubExecutor stubs) {
        super("5100-READ-XREF-RECORD", registry, stubs);
    }

    @Override
    protected void doExecute(ProgramState state) {
        state.put("XREF-CARD-NUM", state.get("PA-RQ-CARD-NUM"));
        stubs.dummyExec(state, "CICS", "EXEC CICS READ DATASET   (WS-CCXREF-FILE) INTO      (CARD-XREF-RECORD) LENGTH    (LENGTH OF CARD-XREF-RECORD) RIDFLD    (XREF-CARD-NUM) KEYLENGTH (LENGTH OF XREF-CARD-NUM) RESP      (WS-RESP-CD) RESP2...");
        Object _evalSubject = state.get("WS-RESP-CD");
        if (java.util.Objects.equals(_evalSubject, 0)) {
            state.addBranch(11);
            state.put("CARD-FOUND-XREF", true);
        }
        else if (java.util.Objects.equals(_evalSubject, 13)) {
            state.addBranch(12);
            state.put("CARD-NFOUND-XREF", true);
            state.put("NFOUND-ACCT-IN-MSTR", true);
            state.put("ERR-LOCATION", "A001");
            state.put("ERR-WARNING", true);
            state.put("ERR-APP", true);
            state.put("ERR-MESSAGE", "CARD NOT FOUND IN XREF");
            state.put("ERR-EVENT-KEY", state.get("XREF-CARD-NUM"));
            perform(state, "9500-LOG-ERROR");
        }
        else {
            state.addBranch(13);
            state.put("ERR-LOCATION", "C001");
            state.put("ERR-CRITICAL", true);
            state.put("ERR-CICS", true);
            state.put("WS-CODE-DISPLAY", state.get("WS-RESP-CD"));
            state.put("ERR-CODE-1", state.get("WS-CODE-DISPLAY"));
            state.put("WS-CODE-DISPLAY", state.get("WS-REAS-CD"));
            state.put("ERR-CODE-2", state.get("WS-CODE-DISPLAY"));
            state.put("READ", state.get("FAILED"));
            state.put("XREF", state.get("FAILED"));
            state.put("FILE", state.get("FAILED"));
            state.put("ERR-EVENT-KEY", state.get("XREF-CARD-NUM"));
            perform(state, "9500-LOG-ERROR");
        }
    }
}
