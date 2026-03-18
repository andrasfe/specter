package com.specter.generated;

/**
 * Generated section: Section1.
 */
public class Section1 extends SectionBase {

    public Section1(ParagraphRegistry registry, StubExecutor stubs) {
        super(registry, stubs);
        paragraph("1000-INITIALIZE", this::do_1000_INITIALIZE);
        paragraph("1000-EXIT", this::do_1000_EXIT);
        paragraph("1100-OPEN-REQUEST-QUEUE", this::do_1100_OPEN_REQUEST_QUEUE);
        paragraph("1100-EXIT", this::do_1100_EXIT);
        paragraph("1200-SCHEDULE-PSB", this::do_1200_SCHEDULE_PSB);
        paragraph("1200-EXIT", this::do_1200_EXIT);
    }

    void do_1000_INITIALIZE(ProgramState state) {
        stubs.cicsRetrieve(state, "MQTM");
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

    void do_1000_EXIT(ProgramState state) {
        // EXIT
    }

    void do_1100_OPEN_REQUEST_QUEUE(ProgramState state) {
        state.put("MQOD-OBJECTTYPE", state.get("MQOT-Q"));
        state.put("MQOD-OBJECTNAME", state.get("WS-REQUEST-QNAME"));
        state.put("WS-OPTIONS", CobolRuntime.toNum(state.get("MQOO-INPUT-SHARED")));
        stubs.mqOpen(state, "WS-REQUEST-QNAME");
        if (java.util.Objects.equals(state.get("WS-COMPCODE"), state.get("MQCC-OK"))) {
            state.addBranch(2);
            state.put("WS-REQUEST-MQ-CLSE", false);
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

    void do_1100_EXIT(ProgramState state) {
        // EXIT
    }

    void do_1200_SCHEDULE_PSB(ProgramState state) {
        stubs.dliSchedulePsb(state, "PSB-NAME");
        state.put("IMS-RETURN-CODE", state.get("DIBSTAT"));
        if (CobolRuntime.isTruthy(state.get("PSB-SCHEDULED-MORE-THAN-ONCE"))) {
            state.addBranch(3);
            stubs.dliTerminate(state);
            stubs.dliSchedulePsb(state, "PSB-NAME");
            state.put("IMS-RETURN-CODE", state.get("DIBSTAT"));
        } else {
            state.addBranch(-3);
        }
        if (CobolRuntime.isTruthy(state.get("STATUS-OK"))) {
            state.addBranch(4);
            state.put("IMS-PSB-NOT-SCHD", false);
            state.put("IMS-PSB-SCHD", true);
        } else {
            state.addBranch(-4);
            state.put("ERR-LOCATION", "I001");
            state.put("ERR-CRITICAL", true);
            state.put("ERR-IMS", true);
            state.put("ERR-CODE-1", state.get("IMS-RETURN-CODE"));
            state.put("ERR-MESSAGE", "IMS SCHD FAILED");
            perform(state, "9500-LOG-ERROR");
        }
    }

    void do_1200_EXIT(ProgramState state) {
        // EXIT
    }

}
