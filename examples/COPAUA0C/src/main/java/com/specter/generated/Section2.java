package com.specter.generated;

/**
 * Generated section: Section2.
 */
public class Section2 extends SectionBase {

    public Section2(ParagraphRegistry registry, StubExecutor stubs) {
        super(registry, stubs);
        paragraph("2000-MAIN-PROCESS", this::do_2000_MAIN_PROCESS);
        paragraph("2000-EXIT", this::do_2000_EXIT);
        paragraph("2100-EXTRACT-REQUEST-MSG", this::do_2100_EXTRACT_REQUEST_MSG);
        paragraph("2100-EXIT", this::do_2100_EXIT);
    }

    void do_2000_MAIN_PROCESS(ProgramState state) {
        int _lc1 = 0;
        while (!((CobolRuntime.isTruthy(state.get("NO-MORE-MSG-AVAILABLE"))) || (CobolRuntime.isTruthy(state.get("WS-LOOP-END"))))) {
            state.addBranch(5);
            performThru(state, "2100-EXTRACT-REQUEST-MSG", "2100-EXIT");
            performThru(state, "5000-PROCESS-AUTH", "5000-EXIT");
            state.put("WS-MSG-PROCESSED", CobolRuntime.toNum(state.get("WS-MSG-PROCESSED")) + 1);
            stubs.cicsSyncpoint(state);
            state.put("IMS-PSB-SCHD", false);
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

    void do_2000_EXIT(ProgramState state) {
        // EXIT
    }

    void do_2100_EXTRACT_REQUEST_MSG(ProgramState state) {
        String[] _usParts = String.valueOf(state.get("W01-GET-BUFFER")).split(",");
        state.put("PA-RQ-AUTH-DATE", 0 < _usParts.length ? _usParts[0].trim() : "");
        state.put("PA-RQ-AUTH-TIME", 1 < _usParts.length ? _usParts[1].trim() : "");
        state.put("PA-RQ-CARD-NUM", 2 < _usParts.length ? _usParts[2].trim() : "");
        state.put("PA-RQ-AUTH-TYPE", 3 < _usParts.length ? _usParts[3].trim() : "");
        state.put("PA-RQ-CARD-EXPIRY-DATE", 4 < _usParts.length ? _usParts[4].trim() : "");
        state.put("PA-RQ-MESSAGE-TYPE", 5 < _usParts.length ? _usParts[5].trim() : "");
        state.put("PA-RQ-MESSAGE-SOURCE", 6 < _usParts.length ? _usParts[6].trim() : "");
        state.put("PA-RQ-PROCESSING-CODE", 7 < _usParts.length ? _usParts[7].trim() : "");
        state.put("WS-TRANSACTION-AMT-AN", 8 < _usParts.length ? _usParts[8].trim() : "");
        state.put("PA-RQ-MERCHANT-CATAGORY-CODE", 9 < _usParts.length ? _usParts[9].trim() : "");
        state.put("PA-RQ-ACQR-COUNTRY-CODE", 10 < _usParts.length ? _usParts[10].trim() : "");
        state.put("PA-RQ-POS-ENTRY-MODE", 11 < _usParts.length ? _usParts[11].trim() : "");
        state.put("PA-RQ-MERCHANT-ID", 12 < _usParts.length ? _usParts[12].trim() : "");
        state.put("PA-RQ-MERCHANT-NAME", 13 < _usParts.length ? _usParts[13].trim() : "");
        state.put("PA-RQ-MERCHANT-CITY", 14 < _usParts.length ? _usParts[14].trim() : "");
        state.put("PA-RQ-MERCHANT-STATE", 15 < _usParts.length ? _usParts[15].trim() : "");
        state.put("PA-RQ-MERCHANT-ZIP", 16 < _usParts.length ? _usParts[16].trim() : "");
        state.put("PA-RQ-TRANSACTION-ID", 17 < _usParts.length ? _usParts[17].trim() : "");
        state.put("PA-RQ-TRANSACTION-AMT", CobolRuntime.toNum(state.get("WS-TRANSACTION-AMT-AN")));
        state.put("WS-TRANSACTION-AMT", state.get("PA-RQ-TRANSACTION-AMT"));
    }

    void do_2100_EXIT(ProgramState state) {
        // EXIT
    }

}
