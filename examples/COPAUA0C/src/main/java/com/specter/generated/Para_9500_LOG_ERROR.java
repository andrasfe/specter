package com.specter.generated;

/**
 * Generated paragraph: 9500-LOG-ERROR.
 */
public class Para_9500_LOG_ERROR extends Paragraph {

    public Para_9500_LOG_ERROR(ParagraphRegistry registry, StubExecutor stubs) {
        super("9500-LOG-ERROR", registry, stubs);
    }

    @Override
    protected void doExecute(ProgramState state) {
        stubs.dummyExec(state, "CICS", "EXEC CICS ASKTIME NOHANDLE ABSTIME(WS-ABS-TIME) END-EXEC");
        stubs.dummyExec(state, "CICS", "EXEC CICS FORMATTIME ABSTIME(WS-ABS-TIME) YYMMDD(WS-CUR-DATE-X6) TIME(WS-CUR-TIME-X6) END-EXEC");
        state.put("ERR-APPLICATION", state.get("WS-CICS-TRANID"));
        state.put("ERR-PROGRAM", state.get("WS-PGM-AUTH"));
        state.put("ERR-DATE", state.get("WS-CUR-DATE-X6"));
        state.put("ERR-TIME", state.get("WS-CUR-TIME-X6"));
        stubs.dummyExec(state, "CICS", "EXEC CICS WRITEQ TD QUEUE('CSSL') FROM (ERROR-LOG-RECORD) LENGTH (LENGTH OF ERROR-LOG-RECORD) NOHANDLE END-EXEC");
        if (CobolRuntime.isTruthy(state.get("ERR-CRITICAL"))) {
            state.addBranch(48);
            perform(state, "9990-END-ROUTINE");
        } else {
            state.addBranch(-48);
        }
    }
}
