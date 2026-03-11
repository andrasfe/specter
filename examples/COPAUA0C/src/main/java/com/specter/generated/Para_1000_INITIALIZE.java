package com.specter.generated;

/**
 * Generated paragraph: 1000-INITIALIZE.
 */
public class Para_1000_INITIALIZE extends Paragraph {

    public Para_1000_INITIALIZE(ParagraphRegistry registry, StubExecutor stubs) {
        super("1000-INITIALIZE", registry, stubs);
    }

    @Override
    protected void doExecute(ProgramState state) {
        stubs.dummyExec(state, "CICS", "EXEC CICS RETRIEVE INTO(MQTM) NOHANDLE END-EXEC");
        if (java.util.Objects.equals(state.get("EIBRESP"), 0)) {
            state.addBranch(1);
            state.put("WS-REQUEST-QNAME", state.get("MQTM-QNAME"));
            state.put("WS-TRIGGER-DATA", state.get("MQTM-TRIGGERDATA"));
        } else {
            state.addBranch(-1);
        }
        state.put("WS-WAIT-INTERVAL", 5000);
        performThru(state, "1100-OPEN-REQUEST-QUEUE", "1100-EXIT");
        performThru(state, "3100-READ-REQUEST-MQ", "3100-EXIT");
    }
}
