package com.specter.generated;

/**
 * Generated paragraph: 5000-PROCESS-AUTH.
 */
public class Para_5000_PROCESS_AUTH extends Paragraph {

    public Para_5000_PROCESS_AUTH(ParagraphRegistry registry, StubExecutor stubs) {
        super("5000-PROCESS-AUTH", registry, stubs);
    }

    @Override
    protected void doExecute(ProgramState state) {
        state.put("APPROVE-AUTH", true);
        performThru(state, "1200-SCHEDULE-PSB", "1200-EXIT");
        state.put("CARD-FOUND-XREF", true);
        state.put("FOUND-ACCT-IN-MSTR", true);
        performThru(state, "5100-READ-XREF-RECORD", "5100-EXIT");
        if (CobolRuntime.isTruthy(state.get("CARD-FOUND-XREF"))) {
            state.addBranch(9);
            performThru(state, "5200-READ-ACCT-RECORD", "5200-EXIT");
            performThru(state, "5300-READ-CUST-RECORD", "5300-EXIT");
            performThru(state, "5500-READ-AUTH-SUMMRY", "5500-EXIT");
            performThru(state, "5600-READ-PROFILE-DATA", "5600-EXIT");
        } else {
            state.addBranch(-9);
        }
        performThru(state, "6000-MAKE-DECISION", "6000-EXIT");
        performThru(state, "7100-SEND-RESPONSE", "7100-EXIT");
        if (CobolRuntime.isTruthy(state.get("CARD-FOUND-XREF"))) {
            state.addBranch(10);
            performThru(state, "8000-WRITE-AUTH-TO-DB", "8000-EXIT");
        } else {
            state.addBranch(-10);
        }
    }
}
