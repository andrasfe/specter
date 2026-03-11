package com.specter.generated;

/**
 * Generated paragraph: 8000-WRITE-AUTH-TO-DB.
 */
public class Para_8000_WRITE_AUTH_TO_DB extends Paragraph {

    public Para_8000_WRITE_AUTH_TO_DB(ParagraphRegistry registry, StubExecutor stubs) {
        super("8000-WRITE-AUTH-TO-DB", registry, stubs);
    }

    @Override
    protected void doExecute(ProgramState state) {
        performThru(state, "8400-UPDATE-SUMMARY", "8400-EXIT");
        performThru(state, "8500-INSERT-AUTH", "8500-EXIT");
    }
}
