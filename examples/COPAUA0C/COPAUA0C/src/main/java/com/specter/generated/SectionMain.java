package com.specter.generated;

/**
 * Generated section: SectionMain.
 */
public class SectionMain extends SectionBase {

    public SectionMain(ParagraphRegistry registry, StubExecutor stubs) {
        super(registry, stubs);
        paragraph("MAIN-PARA", this::do_MAIN_PARA);
        paragraph("MQCLOSE", this::do_MQCLOSE);
        paragraph("MQGET", this::do_MQGET);
        paragraph("MQGMO-OPTIONS", this::do_MQGMO_OPTIONS);
        paragraph("MQOPEN", this::do_MQOPEN);
        paragraph("MQPMO-OPTIONS", this::do_MQPMO_OPTIONS);
        paragraph("MQPUT1", this::do_MQPUT1);
        paragraph("PA-AUTH-DATE-9C", this::do_PA_AUTH_DATE_9C);
        paragraph("PA-AUTH-TIME-9C", this::do_PA_AUTH_TIME_9C);
        paragraph("PA-RQ-TRANSACTION-AMT", this::do_PA_RQ_TRANSACTION_AMT);
        paragraph("WS-AVAILABLE-AMT", this::do_WS_AVAILABLE_AMT);
        paragraph("WS-OPTIONS", this::do_WS_OPTIONS);
        paragraph("WS-TIME-WITH-MS", this::do_WS_TIME_WITH_MS);
    }

    void do_MAIN_PARA(ProgramState state) {
        performThru(state, "1000-INITIALIZE", "1000-EXIT");
        performThru(state, "2000-MAIN-PROCESS", "2000-EXIT");
        performThru(state, "9000-TERMINATE", "9000-EXIT");
        stubs.dummyExec(state, "CICS", "EXEC CICS RETURN END-EXEC.");
    }

    void do_MQCLOSE(ProgramState state) {
        // empty paragraph
    }

    void do_MQGET(ProgramState state) {
        // empty paragraph
    }

    void do_MQGMO_OPTIONS(ProgramState state) {
        // empty paragraph
    }

    void do_MQOPEN(ProgramState state) {
        // empty paragraph
    }

    void do_MQPMO_OPTIONS(ProgramState state) {
        // empty paragraph
    }

    void do_MQPUT1(ProgramState state) {
        // empty paragraph
    }

    void do_PA_AUTH_DATE_9C(ProgramState state) {
        // empty paragraph
    }

    void do_PA_AUTH_TIME_9C(ProgramState state) {
        // empty paragraph
    }

    void do_PA_RQ_TRANSACTION_AMT(ProgramState state) {
        // empty paragraph
    }

    void do_WS_AVAILABLE_AMT(ProgramState state) {
        // empty paragraph
    }

    void do_WS_OPTIONS(ProgramState state) {
        // empty paragraph
    }

    void do_WS_TIME_WITH_MS(ProgramState state) {
        // empty paragraph
    }

}
