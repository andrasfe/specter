package com.specter.generated;

/**
 * Generated paragraph: 9990-END-ROUTINE.
 */
public class Para_9990_END_ROUTINE extends Paragraph {

    public Para_9990_END_ROUTINE(ParagraphRegistry registry, StubExecutor stubs) {
        super("9990-END-ROUTINE", registry, stubs);
    }

    @Override
    protected void doExecute(ProgramState state) {
        perform(state, "9000-TERMINATE");
        stubs.dummyExec(state, "CICS", "EXEC CICS RETURN END-EXEC");
        // UNKNOWN: 
    }
}
