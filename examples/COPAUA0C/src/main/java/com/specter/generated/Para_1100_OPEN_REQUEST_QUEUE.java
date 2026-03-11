package com.specter.generated;

/**
 * Generated paragraph: 1100-OPEN-REQUEST-QUEUE.
 */
public class Para_1100_OPEN_REQUEST_QUEUE extends Paragraph {

    public Para_1100_OPEN_REQUEST_QUEUE(ParagraphRegistry registry, StubExecutor stubs) {
        super("1100-OPEN-REQUEST-QUEUE", registry, stubs);
    }

    @Override
    protected void doExecute(ProgramState state) {
        state.put("MQOD-OBJECTTYPE", state.get("MQOT-Q"));
        state.put("OF", state.get("MQOT-Q"));
        state.put("MQM-OD-REQUEST", state.get("MQOT-Q"));
        state.put("MQOD-OBJECTNAME", state.get("WS-REQUEST-QNAME"));
        state.put("OF", state.get("WS-REQUEST-QNAME"));
        state.put("MQM-OD-REQUEST", state.get("WS-REQUEST-QNAME"));
        state.put("WS-OPTIONS", CobolRuntime.toNum(state.get("MQOO-INPUT-SHARED")));
        stubs.dummyCall(state, "MQOPEN");
        if (java.util.Objects.equals(state.get("WS-COMPCODE"), state.get("MQCC-OK"))) {
            state.addBranch(2);
            state.put("WS-REQUEST-MQ-OPEN", true);
        } else {
            state.addBranch(-2);
            state.put("ERR-LOCATION", "M001");
            state.put("ERR-CRITICAL", true);
            state.put("ERR-MQ", true);
            state.put("WS-CODE-DISPLAY", state.get("WS-COMPCODE"));
            state.put("ERR-CODE-1", state.get("WS-CODE-DISPLAY"));
            state.put("WS-CODE-DISPLAY", state.get("WS-REASON"));
            state.put("ERR-CODE-2", state.get("WS-CODE-DISPLAY"));
            state.put("ERR-MESSAGE", "REQ MQ OPEN ERROR");
            perform(state, "9500-LOG-ERROR");
        }
    }
}
