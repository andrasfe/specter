package com.specter.generated;

/**
 * Generated paragraph: 5300-READ-CUST-RECORD.
 */
public class Para_5300_READ_CUST_RECORD extends Paragraph {

    public Para_5300_READ_CUST_RECORD(ParagraphRegistry registry, StubExecutor stubs) {
        super("5300-READ-CUST-RECORD", registry, stubs);
    }

    @Override
    protected void doExecute(ProgramState state) {
        state.put("WS-CARD-RID-CUST-ID", state.get("XREF-CUST-ID"));
        stubs.dummyExec(state, "CICS", "EXEC CICS READ DATASET   (WS-CUSTFILENAME) RIDFLD    (WS-CARD-RID-CUST-ID-X) KEYLENGTH (LENGTH OF WS-CARD-RID-CUST-ID-X) INTO      (CUSTOMER-RECORD) LENGTH    (LENGTH OF CUSTOMER-RECORD) RESP      (WS...");
        Object _evalSubject = state.get("WS-RESP-CD");
        if (java.util.Objects.equals(_evalSubject, 0)) {
            state.addBranch(17);
            state.put("FOUND-CUST-IN-MSTR", true);
        }
        else if (java.util.Objects.equals(_evalSubject, 13)) {
            state.addBranch(18);
            state.put("NFOUND-CUST-IN-MSTR", true);
            state.put("ERR-LOCATION", "A003");
            state.put("ERR-WARNING", true);
            state.put("ERR-APP", true);
            state.put("ERR-MESSAGE", "CUST NOT FOUND IN XREF");
            state.put("ERR-EVENT-KEY", state.get("WS-CARD-RID-CUST-ID"));
            perform(state, "9500-LOG-ERROR");
        }
        else {
            state.addBranch(19);
            state.put("ERR-LOCATION", "C003");
            state.put("ERR-CRITICAL", true);
            state.put("ERR-CICS", true);
            state.put("WS-CODE-DISPLAY", state.get("WS-RESP-CD"));
            state.put("ERR-CODE-1", state.get("WS-CODE-DISPLAY"));
            state.put("WS-CODE-DISPLAY", state.get("WS-REAS-CD"));
            state.put("ERR-CODE-2", state.get("WS-CODE-DISPLAY"));
            state.put("READ", state.get("FAILED"));
            state.put("CUST", state.get("FAILED"));
            state.put("FILE", state.get("FAILED"));
            state.put("ERR-EVENT-KEY", state.get("WS-CARD-RID-CUST-ID"));
            perform(state, "9500-LOG-ERROR");
        }
    }
}
