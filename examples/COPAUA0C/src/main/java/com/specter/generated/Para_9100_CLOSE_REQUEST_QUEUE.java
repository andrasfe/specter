package com.specter.generated;

/**
 * Generated paragraph: 9100-CLOSE-REQUEST-QUEUE.
 */
public class Para_9100_CLOSE_REQUEST_QUEUE extends Paragraph {

    public Para_9100_CLOSE_REQUEST_QUEUE(ParagraphRegistry registry, StubExecutor stubs) {
        super("9100-CLOSE-REQUEST-QUEUE", registry, stubs);
    }

    @Override
    protected void doExecute(ProgramState state) {
        if (CobolRuntime.isTruthy(state.get("WS-REQUEST-MQ-OPEN"))) {
            state.addBranch(46);
            stubs.dummyCall(state, "MQCLOSE");
            if (java.util.Objects.equals(state.get("WS-COMPCODE"), state.get("MQCC-OK"))) {
                state.addBranch(47);
                state.put("WS-REQUEST-MQ-CLSE", true);
            } else {
                state.addBranch(-47);
                state.put("ERR-LOCATION", "M005");
                state.put("ERR-WARNING", true);
                state.put("ERR-MQ", true);
                state.put("WS-CODE-DISPLAY", state.get("WS-COMPCODE"));
                state.put("ERR-CODE-1", state.get("WS-CODE-DISPLAY"));
                state.put("WS-CODE-DISPLAY", state.get("WS-REASON"));
                state.put("ERR-CODE-2", state.get("WS-CODE-DISPLAY"));
                state.put("CLOSE", state.get("FAILED"));
                state.put("REQUEST", state.get("FAILED"));
                state.put("MQ", state.get("FAILED"));
                perform(state, "9500-LOG-ERROR");
            }
        } else {
            state.addBranch(-46);
        }
    }
}
