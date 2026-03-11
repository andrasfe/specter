package com.specter.generated;

/**
 * Generated paragraph: 2000-MAIN-PROCESS.
 */
public class Para_2000_MAIN_PROCESS extends Paragraph {

    public Para_2000_MAIN_PROCESS(ParagraphRegistry registry, StubExecutor stubs) {
        super("2000-MAIN-PROCESS", registry, stubs);
    }

    @Override
    protected void doExecute(ProgramState state) {
        int _lc1 = 0;
        while (!((CobolRuntime.isTruthy(state.get("NO-MORE-MSG-AVAILABLE"))) || (CobolRuntime.isTruthy(state.get("WS-LOOP-END"))))) {
            state.addBranch(5);
            performThru(state, "2100-EXTRACT-REQUEST-MSG", "2100-EXIT");
            performThru(state, "5000-PROCESS-AUTH", "5000-EXIT");
            state.put("WS-MSG-PROCESSED", CobolRuntime.toNum(state.get("WS-MSG-PROCESSED")) + 1);
            stubs.dummyExec(state, "CICS", "EXEC CICS SYNCPOINT END-EXEC");
            state.put("IMS-PSB-NOT-SCHD", true);
            if (CobolRuntime.toNum(state.get("WS-MSG-PROCESSED")) > CobolRuntime.toNum(state.get("WS-REQSTS-PROCESS-LIMIT"))) {
                state.addBranch(6);
                state.put("WS-LOOP-END", true);
            } else {
                state.addBranch(-6);
                performThru(state, "3100-READ-REQUEST-MQ", "3100-EXIT");
            }
            _lc1++;
            if (_lc1 >= 100) {
                break;
            }
        }
        if (_lc1 == 0) {
            state.addBranch(-5);
        }
    }
}
