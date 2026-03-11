package com.specter.generated;

/**
 * Generated paragraph: 1200-SCHEDULE-PSB.
 */
public class Para_1200_SCHEDULE_PSB extends Paragraph {

    public Para_1200_SCHEDULE_PSB(ParagraphRegistry registry, StubExecutor stubs) {
        super("1200-SCHEDULE-PSB", registry, stubs);
    }

    @Override
    protected void doExecute(ProgramState state) {
        stubs.dummyExec(state, "DLI", "EXEC DLI SCHD PSB((PSB-NAME)) NODHABEND END-EXEC");
        state.put("IMS-RETURN-CODE", state.get("DIBSTAT"));
        if (CobolRuntime.isTruthy(state.get("PSB-SCHEDULED-MORE-THAN-ONCE"))) {
            state.addBranch(3);
            stubs.dummyExec(state, "DLI", "EXEC DLI TERM END-EXEC");
            stubs.dummyExec(state, "DLI", "EXEC DLI SCHD PSB((PSB-NAME)) NODHABEND END-EXEC");
            state.put("IMS-RETURN-CODE", state.get("DIBSTAT"));
        } else {
            state.addBranch(-3);
        }
        if (CobolRuntime.isTruthy(state.get("STATUS-OK"))) {
            state.addBranch(4);
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
}
