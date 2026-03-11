package com.specter.generated;

/**
 * Generated paragraph: 2100-EXTRACT-REQUEST-MSG.
 */
public class Para_2100_EXTRACT_REQUEST_MSG extends Paragraph {

    public Para_2100_EXTRACT_REQUEST_MSG(ParagraphRegistry registry, StubExecutor stubs) {
        super("2100-EXTRACT-REQUEST-MSG", registry, stubs);
    }

    @Override
    protected void doExecute(ProgramState state) {
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
}
