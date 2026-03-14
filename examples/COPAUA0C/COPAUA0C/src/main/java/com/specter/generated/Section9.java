package com.specter.generated;

/**
 * Generated section: Section9.
 */
public class Section9 extends SectionBase {

    public Section9(ParagraphRegistry registry, StubExecutor stubs) {
        super(registry, stubs);
        paragraph("9000-TERMINATE", this::do_9000_TERMINATE);
        paragraph("9000-EXIT", this::do_9000_EXIT);
        paragraph("9100-CLOSE-REQUEST-QUEUE", this::do_9100_CLOSE_REQUEST_QUEUE);
        paragraph("9100-EXIT", this::do_9100_EXIT);
        paragraph("9500-LOG-ERROR", this::do_9500_LOG_ERROR);
        paragraph("9500-EXIT", this::do_9500_EXIT);
        paragraph("9990-END-ROUTINE", this::do_9990_END_ROUTINE);
        paragraph("9990-EXIT", this::do_9990_EXIT);
    }

    void do_9000_TERMINATE(ProgramState state) {
        if (CobolRuntime.isTruthy(state.get("IMS-PSB-SCHD"))) {
            state.addBranch(43);
            stubs.dliTerminate(state);
        } else {
            state.addBranch(-43);
        }
        performThru(state, "9100-CLOSE-REQUEST-QUEUE", "9100-EXIT");
    }

    void do_9000_EXIT(ProgramState state) {
        // EXIT
    }

    void do_9100_CLOSE_REQUEST_QUEUE(ProgramState state) {
        if (CobolRuntime.isTruthy(state.get("WS-REQUEST-MQ-OPEN"))) {
            state.addBranch(44);
            stubs.mqClose(state);
            if (java.util.Objects.equals(state.get("WS-COMPCODE"), state.get("MQCC-OK"))) {
                state.addBranch(45);
                state.put("WS-REQUEST-MQ-OPEN", false);
                state.put("WS-REQUEST-MQ-CLSE", true);
            } else {
                state.addBranch(-45);
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
            state.addBranch(-44);
        }
    }

    void do_9100_EXIT(ProgramState state) {
        // EXIT
    }

    void do_9500_LOG_ERROR(ProgramState state) {
        stubs.cicsAsktime(state, "WS-ABS-TIME");
        stubs.cicsFormattime(state, "WS-ABS-TIME", "WS-CUR-DATE-X6", "WS-CUR-TIME-X6", null);
        state.put("ERR-APPLICATION", state.get("WS-CICS-TRANID"));
        state.put("ERR-PROGRAM", state.get("WS-PGM-AUTH"));
        state.put("ERR-DATE", state.get("WS-CUR-DATE-X6"));
        state.put("ERR-TIME", state.get("WS-CUR-TIME-X6"));
        stubs.cicsWriteqTd(state, "CSSL", "ERROR-LOG-RECORD");
        if (CobolRuntime.isTruthy(state.get("ERR-CRITICAL"))) {
            state.addBranch(46);
            perform(state, "9990-END-ROUTINE");
        } else {
            state.addBranch(-46);
        }
    }

    void do_9500_EXIT(ProgramState state) {
        // EXIT
    }

    void do_9990_END_ROUTINE(ProgramState state) {
        perform(state, "9000-TERMINATE");
        stubs.cicsReturn(state, false);
        // UNKNOWN: 
    }

    void do_9990_EXIT(ProgramState state) {
        // EXIT
    }

}
