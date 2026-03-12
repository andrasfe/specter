package com.specter.generated;

/**
 * Generated section: Section7.
 */
public class Section7 extends SectionBase {

    public Section7(ParagraphRegistry registry, StubExecutor stubs) {
        super(registry, stubs);
        paragraph("7100-SEND-RESPONSE", this::do_7100_SEND_RESPONSE);
        paragraph("7100-EXIT", this::do_7100_EXIT);
    }

    void do_7100_SEND_RESPONSE(ProgramState state) {
        state.put("MQOD-OBJECTTYPE", state.get("MQOT-Q"));
        state.put("OF", state.get("MQOT-Q"));
        state.put("MQM-OD-REPLY", state.get("MQOT-Q"));
        state.put("MQOD-OBJECTNAME", state.get("WS-REPLY-QNAME"));
        state.put("OF", state.get("WS-REPLY-QNAME"));
        state.put("MQM-OD-REPLY", state.get("WS-REPLY-QNAME"));
        state.put("MQMD-MSGTYPE", state.get("MQMT-REPLY"));
        state.put("OF", state.get("MQMT-REPLY"));
        state.put("MQM-MD-REPLY", state.get("MQMT-REPLY"));
        state.put("MQMD-CORRELID", state.get("WS-SAVE-CORRELID"));
        state.put("OF", state.get("WS-SAVE-CORRELID"));
        state.put("MQM-MD-REPLY", state.get("WS-SAVE-CORRELID"));
        state.put("MQMD-MSGID", state.get("MQMI-NONE"));
        state.put("OF", state.get("MQMI-NONE"));
        state.put("MQM-MD-REPLY", state.get("MQMI-NONE"));
        state.put("MQMD-REPLYTOQ", " ");
        state.put("OF", " ");
        state.put("MQM-MD-REPLY", " ");
        state.put("MQMD-REPLYTOQMGR", " ");
        state.put("OF", " ");
        state.put("MQM-MD-REPLY", " ");
        state.put("MQMD-PERSISTENCE", state.get("MQPER-NOT-PERSISTENT"));
        state.put("OF", state.get("MQPER-NOT-PERSISTENT"));
        state.put("MQM-MD-REPLY", state.get("MQPER-NOT-PERSISTENT"));
        state.put("MQMD-EXPIRY", 50);
        state.put("OF", 50);
        state.put("MQM-MD-REPLY", 50);
        state.put("MQMD-FORMAT", state.get("MQFMT-STRING"));
        state.put("OF", state.get("MQFMT-STRING"));
        state.put("MQM-MD-REPLY", state.get("MQFMT-STRING"));
        state.put("MQPMO-OPTIONS", CobolRuntime.toNum(state.get("MQPMO-NO-SYNCPOINT")));
        state.put("W02-BUFFLEN", state.get("WS-RESP-LENGTH"));
        stubs.mqPut1(state, "WS-REPLY-QNAME", "W02-PUT-BUFFER", "W02-BUFLEN");
        if (!java.util.Objects.equals(state.get("WS-COMPCODE"), state.get("MQCC-OK"))) {
            state.addBranch(38);
            state.put("ERR-LOCATION", "M004");
            state.put("ERR-CRITICAL", true);
            state.put("ERR-MQ", true);
            state.put("WS-CODE-DISPLAY", state.get("WS-COMPCODE"));
            state.put("ERR-CODE-1", state.get("WS-CODE-DISPLAY"));
            state.put("WS-CODE-DISPLAY", state.get("WS-REASON"));
            state.put("ERR-CODE-2", state.get("WS-CODE-DISPLAY"));
            state.put("PUT", state.get("FAILED"));
            state.put("ON", state.get("FAILED"));
            state.put("REPLY", state.get("FAILED"));
            state.put("MQ", state.get("FAILED"));
            state.put("ERR-EVENT-KEY", state.get("PA-CARD-NUM"));
            perform(state, "9500-LOG-ERROR");
        } else {
            state.addBranch(-38);
        }
    }

    void do_7100_EXIT(ProgramState state) {
        // EXIT
    }

}
