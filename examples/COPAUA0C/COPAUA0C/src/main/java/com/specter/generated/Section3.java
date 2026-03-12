package com.specter.generated;

/**
 * Generated section: Section3.
 */
public class Section3 extends SectionBase {

    public Section3(ParagraphRegistry registry, StubExecutor stubs) {
        super(registry, stubs);
        paragraph("3100-READ-REQUEST-MQ", this::do_3100_READ_REQUEST_MQ);
        paragraph("3100-EXIT", this::do_3100_EXIT);
    }

    void do_3100_READ_REQUEST_MQ(ProgramState state) {
        state.put("MQGMO-OPTIONS", CobolRuntime.toNum(state.get("MQGMO-NO-SYNCPOINT")) + CobolRuntime.toNum(state.get("MQGMO-WAIT")));
        state.put("MQGMO-WAITINTERVAL", state.get("WS-WAIT-INTERVAL"));
        state.put("MQMD-MSGID", state.get("MQMI-NONE"));
        state.put("MQMD-CORRELID", state.get("MQCI-NONE"));
        state.put("MQMD-FORMAT", state.get("MQFMT-STRING"));
        state.put("W01-BUFFLEN", String.valueOf(state.get("W01-GET-BUFFER")).length());
        stubs.mqGet(state, "W01-GET-BUFFER", "W01-DATALEN", "MQGMO-WAITINTERVAL");
        if (java.util.Objects.equals(state.get("WS-COMPCODE"), state.get("MQCC-OK"))) {
            state.addBranch(7);
            state.put("WS-SAVE-CORRELID", state.get("MQMD-CORRELID"));
            state.put("WS-REPLY-QNAME", state.get("MQMD-REPLYTOQ"));
        } else {
            state.addBranch(-7);
            if (java.util.Objects.equals(state.get("WS-REASON"), state.get("MQRC-NO-MSG-AVAILABLE"))) {
                state.addBranch(8);
                state.put("NO-MORE-MSG-AVAILABLE", true);
            } else {
                state.addBranch(-8);
                state.put("ERR-LOCATION", "M003");
                state.put("ERR-CRITICAL", true);
                state.put("ERR-CICS", true);
                state.put("WS-CODE-DISPLAY", state.get("WS-COMPCODE"));
                state.put("ERR-CODE-1", state.get("WS-CODE-DISPLAY"));
                state.put("WS-CODE-DISPLAY", state.get("WS-REASON"));
                state.put("ERR-CODE-2", state.get("WS-CODE-DISPLAY"));
                state.put("READ", state.get("FAILED"));
                state.put("REQUEST", state.get("FAILED"));
                state.put("MQ", state.get("FAILED"));
                state.put("ERR-EVENT-KEY", state.get("PA-CARD-NUM"));
                perform(state, "9500-LOG-ERROR");
            }
        }
    }

    void do_3100_EXIT(ProgramState state) {
        // EXIT
    }

}
