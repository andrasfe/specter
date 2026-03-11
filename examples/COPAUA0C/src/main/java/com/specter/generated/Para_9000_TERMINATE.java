package com.specter.generated;

/**
 * Generated paragraph: 9000-TERMINATE.
 */
public class Para_9000_TERMINATE extends Paragraph {

    public Para_9000_TERMINATE(ParagraphRegistry registry, StubExecutor stubs) {
        super("9000-TERMINATE", registry, stubs);
    }

    @Override
    protected void doExecute(ProgramState state) {
        if (CobolRuntime.isTruthy(state.get("IMS-PSB-SCHD"))) {
            state.addBranch(45);
            stubs.dummyExec(state, "DLI", "EXEC DLI TERM END-EXEC");
        } else {
            state.addBranch(-45);
        }
        performThru(state, "9100-CLOSE-REQUEST-QUEUE", "9100-EXIT");
    }
}
