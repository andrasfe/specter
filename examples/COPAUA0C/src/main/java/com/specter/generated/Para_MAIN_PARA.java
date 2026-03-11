package com.specter.generated;

/**
 * Generated paragraph: MAIN-PARA.
 */
public class Para_MAIN_PARA extends Paragraph {

    public Para_MAIN_PARA(ParagraphRegistry registry, StubExecutor stubs) {
        super("MAIN-PARA", registry, stubs);
    }

    @Override
    protected void doExecute(ProgramState state) {
        performThru(state, "1000-INITIALIZE", "1000-EXIT");
        performThru(state, "2000-MAIN-PROCESS", "2000-EXIT");
        performThru(state, "9000-TERMINATE", "9000-EXIT");
        stubs.dummyExec(state, "CICS", "EXEC CICS RETURN END-EXEC.");
    }
}
