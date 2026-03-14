package com.specter.generated;

/**
 * Generated section: SectionMain.
 */
public class SectionMain extends SectionBase {

    public SectionMain(ParagraphRegistry registry, StubExecutor stubs) {
        super(registry, stubs);
        paragraph("COMMON-RETURN", this::do_COMMON_RETURN);
        paragraph("EDIT-AREA-CODE", this::do_EDIT_AREA_CODE);
        paragraph("EDIT-US-PHONE-PREFIX", this::do_EDIT_US_PHONE_PREFIX);
        paragraph("EDIT-US-PHONE-LINENUM", this::do_EDIT_US_PHONE_LINENUM);
        paragraph("EDIT-US-PHONE-EXIT", this::do_EDIT_US_PHONE_EXIT);
        paragraph("ABEND-ROUTINE", this::do_ABEND_ROUTINE);
        paragraph("ABEND-ROUTINE-EXIT", this::do_ABEND_ROUTINE_EXIT);
        paragraph("ACUP-NEW-CASH-CREDIT-LIMIT-N", this::do_ACUP_NEW_CASH_CREDIT_LIMIT_N);
        paragraph("ACUP-NEW-CREDIT-LIMIT-N", this::do_ACUP_NEW_CREDIT_LIMIT_N);
        paragraph("ACUP-NEW-CURR-BAL-N", this::do_ACUP_NEW_CURR_BAL_N);
        paragraph("ACUP-NEW-CURR-CYC-CREDIT-N", this::do_ACUP_NEW_CURR_CYC_CREDIT_N);
        paragraph("ACUP-NEW-CURR-CYC-DEBIT-N", this::do_ACUP_NEW_CURR_CYC_DEBIT_N);
        paragraph("EDIT-DATE-CCYYMMDD", this::do_EDIT_DATE_CCYYMMDD);
        paragraph("EDIT-DATE-OF-BIRTH", this::do_EDIT_DATE_OF_BIRTH);
        paragraph("YYYY-STORE-PFKEY", this::do_YYYY_STORE_PFKEY);
    }

    void do_COMMON_RETURN(ProgramState state) {
        state.put("CCARD-ERROR-MSG", state.get("WS-RETURN-MSG"));
        state.put("WS-COMMAREA", state.get("CARDDEMO-COMMAREA"));
        state.put("WS-COMMAREA", state.get("WS-THIS-PROGCOMMAREA"));
        state.put("LENGTH", state.get("WS-THIS-PROGCOMMAREA"));
        state.put("1", state.get("WS-THIS-PROGCOMMAREA"));
        stubs.cicsReturn(state, true);
        // UNKNOWN: 
    }

    void do_EDIT_AREA_CODE(ProgramState state) {
        if ((java.util.Objects.equals(state.get("WS-EDIT-US-PHONE-NUMA"), " ")) || (java.util.Objects.equals(state.get("WS-EDIT-US-PHONE-NUMA"), "\u0000"))) {
            state.addBranch(12);
            state.put("INPUT-ERROR", true);
            state.put("FLG-EDIT-US-PHONEA-BLANK", true);
            if (CobolRuntime.isTruthy(state.get("WS-RETURN-MSG-OFF"))) {
                state.addBranch(13);
                state.put("WS-RETURN-MSG", String.valueOf(state.get("FUNCTION")) + String.valueOf(state.get("TRIM")) + String.valueOf(state.get("WS-EDIT-VARIABLE-NAME")) + ": Area code must be supplied.");
            } else {
                state.addBranch(-13);
            }
            registry.get("EDIT-US-PHONE-PREFIX").execute(state);
            return;
        } else {
            state.addBranch(-12);
            // CONTINUE
        }
        if (CobolRuntime.isNumeric(state.get("WS-EDIT-US-PHONE-NUMA"))) {
            state.addBranch(14);
            // CONTINUE
        } else {
            state.addBranch(-14);
            state.put("INPUT-ERROR", true);
            state.put("FLG-EDIT-US-PHONEA-NOT-OK", true);
            if (CobolRuntime.isTruthy(state.get("WS-RETURN-MSG-OFF"))) {
                state.addBranch(15);
                state.put("WS-RETURN-MSG", String.valueOf(state.get("FUNCTION")) + String.valueOf(state.get("TRIM")) + String.valueOf(state.get("WS-EDIT-VARIABLE-NAME")) + ": Area code must be A 3 digit number.");
            } else {
                state.addBranch(-15);
            }
            registry.get("EDIT-US-PHONE-PREFIX").execute(state);
            return;
        }
        if (java.util.Objects.equals(state.get("WS-EDIT-US-PHONE-NUMA-N"), 0)) {
            state.addBranch(16);
            state.put("INPUT-ERROR", true);
            state.put("FLG-EDIT-US-PHONEA-NOT-OK", true);
            if (CobolRuntime.isTruthy(state.get("WS-RETURN-MSG-OFF"))) {
                state.addBranch(17);
                state.put("WS-RETURN-MSG", String.valueOf(state.get("FUNCTION")) + String.valueOf(state.get("TRIM")) + String.valueOf(state.get("WS-EDIT-VARIABLE-NAME")) + ": Area code cannot be zero");
            } else {
                state.addBranch(-17);
            }
            registry.get("EDIT-US-PHONE-PREFIX").execute(state);
            return;
        } else {
            state.addBranch(-16);
            // CONTINUE
        }
        state.put("WS-US-PHONE-AREA-CODE-TO-EDIT", state.get("FUNCTION TRIM (WS-EDIT-US-PHONE-NUMA)"));
        if (CobolRuntime.isTruthy(state.get("VALID-GENERAL-PURP-CODE"))) {
            state.addBranch(18);
            // CONTINUE
        } else {
            state.addBranch(-18);
            state.put("INPUT-ERROR", true);
            state.put("FLG-EDIT-US-PHONEA-NOT-OK", true);
            if (CobolRuntime.isTruthy(state.get("WS-RETURN-MSG-OFF"))) {
                state.addBranch(19);
                state.put("WS-RETURN-MSG", String.valueOf(state.get("FUNCTION")) + String.valueOf(state.get("TRIM")) + String.valueOf(state.get("WS-EDIT-VARIABLE-NAME")) + ": Not valid North America general purpose area code");
            } else {
                state.addBranch(-19);
            }
            registry.get("EDIT-US-PHONE-PREFIX").execute(state);
            return;
        }
        state.put("FLG-EDIT-US-PHONEA-ISVALID", true);
    }

    void do_EDIT_US_PHONE_PREFIX(ProgramState state) {
        if ((java.util.Objects.equals(state.get("WS-EDIT-US-PHONE-NUMB"), " ")) || (java.util.Objects.equals(state.get("WS-EDIT-US-PHONE-NUMB"), "\u0000"))) {
            state.addBranch(20);
            state.put("INPUT-ERROR", true);
            state.put("FLG-EDIT-US-PHONEB-BLANK", true);
            if (CobolRuntime.isTruthy(state.get("WS-RETURN-MSG-OFF"))) {
                state.addBranch(21);
                state.put("WS-RETURN-MSG", String.valueOf(state.get("FUNCTION")) + String.valueOf(state.get("TRIM")) + String.valueOf(state.get("WS-EDIT-VARIABLE-NAME")) + ": Prefix code must be supplied.");
            } else {
                state.addBranch(-21);
            }
            registry.get("EDIT-US-PHONE-LINENUM").execute(state);
            return;
        } else {
            state.addBranch(-20);
            // CONTINUE
        }
        if (CobolRuntime.isNumeric(state.get("WS-EDIT-US-PHONE-NUMB"))) {
            state.addBranch(22);
            // CONTINUE
        } else {
            state.addBranch(-22);
            state.put("INPUT-ERROR", true);
            state.put("FLG-EDIT-US-PHONEB-NOT-OK", true);
            if (CobolRuntime.isTruthy(state.get("WS-RETURN-MSG-OFF"))) {
                state.addBranch(23);
                state.put("WS-RETURN-MSG", String.valueOf(state.get("FUNCTION")) + String.valueOf(state.get("TRIM")) + String.valueOf(state.get("WS-EDIT-VARIABLE-NAME")) + ": Prefix code must be A 3 digit number.");
            } else {
                state.addBranch(-23);
            }
            registry.get("EDIT-US-PHONE-LINENUM").execute(state);
            return;
        }
        if (java.util.Objects.equals(state.get("WS-EDIT-US-PHONE-NUMB-N"), 0)) {
            state.addBranch(24);
            state.put("INPUT-ERROR", true);
            state.put("FLG-EDIT-US-PHONEB-NOT-OK", true);
            if (CobolRuntime.isTruthy(state.get("WS-RETURN-MSG-OFF"))) {
                state.addBranch(25);
                state.put("WS-RETURN-MSG", String.valueOf(state.get("FUNCTION")) + String.valueOf(state.get("TRIM")) + String.valueOf(state.get("WS-EDIT-VARIABLE-NAME")) + ": Prefix code cannot be zero");
            } else {
                state.addBranch(-25);
            }
            registry.get("EDIT-US-PHONE-LINENUM").execute(state);
            return;
        } else {
            state.addBranch(-24);
            // CONTINUE
        }
        state.put("FLG-EDIT-US-PHONEB-ISVALID", true);
    }

    void do_EDIT_US_PHONE_LINENUM(ProgramState state) {
        if ((java.util.Objects.equals(state.get("WS-EDIT-US-PHONE-NUMC"), " ")) || (java.util.Objects.equals(state.get("WS-EDIT-US-PHONE-NUMC"), "\u0000"))) {
            state.addBranch(26);
            state.put("INPUT-ERROR", true);
            state.put("FLG-EDIT-US-PHONEC-BLANK", true);
            if (CobolRuntime.isTruthy(state.get("WS-RETURN-MSG-OFF"))) {
                state.addBranch(27);
                state.put("WS-RETURN-MSG", String.valueOf(state.get("FUNCTION")) + String.valueOf(state.get("TRIM")) + String.valueOf(state.get("WS-EDIT-VARIABLE-NAME")) + ": Line number code must be supplied.");
            } else {
                state.addBranch(-27);
            }
            registry.get("EDIT-US-PHONE-EXIT").execute(state);
            return;
        } else {
            state.addBranch(-26);
            // CONTINUE
        }
        if (CobolRuntime.isNumeric(state.get("WS-EDIT-US-PHONE-NUMC"))) {
            state.addBranch(28);
            // CONTINUE
        } else {
            state.addBranch(-28);
            state.put("INPUT-ERROR", true);
            state.put("FLG-EDIT-US-PHONEC-NOT-OK", true);
            if (CobolRuntime.isTruthy(state.get("WS-RETURN-MSG-OFF"))) {
                state.addBranch(29);
                state.put("WS-RETURN-MSG", String.valueOf(state.get("FUNCTION")) + String.valueOf(state.get("TRIM")) + String.valueOf(state.get("WS-EDIT-VARIABLE-NAME")) + ": Line number code must be A 4 digit number.");
            } else {
                state.addBranch(-29);
            }
            registry.get("EDIT-US-PHONE-EXIT").execute(state);
            return;
        }
        if (java.util.Objects.equals(state.get("WS-EDIT-US-PHONE-NUMC-N"), 0)) {
            state.addBranch(30);
            state.put("INPUT-ERROR", true);
            state.put("FLG-EDIT-US-PHONEC-NOT-OK", true);
            if (CobolRuntime.isTruthy(state.get("WS-RETURN-MSG-OFF"))) {
                state.addBranch(31);
                state.put("WS-RETURN-MSG", String.valueOf(state.get("FUNCTION")) + String.valueOf(state.get("TRIM")) + String.valueOf(state.get("WS-EDIT-VARIABLE-NAME")) + ": Line number code cannot be zero");
            } else {
                state.addBranch(-31);
            }
            registry.get("EDIT-US-PHONE-EXIT").execute(state);
            return;
        } else {
            state.addBranch(-30);
            // CONTINUE
        }
        state.put("FLG-EDIT-US-PHONEC-ISVALID", true);
    }

    void do_EDIT_US_PHONE_EXIT(ProgramState state) {
        // EXIT
    }

    void do_ABEND_ROUTINE(ProgramState state) {
        if (java.util.Objects.equals(state.get("ABEND-MSG"), "\u0000")) {
            state.addBranch(32);
            state.put("ABEND-MSG", "UNEXPECTED ABEND OCCURRED.");
        } else {
            state.addBranch(-32);
        }
        state.put("ABEND-CULPRIT", state.get("LIT-THISPGM"));
        stubs.dummyExec(state, "CICS", "EXEC CICS SEND FROM (ABEND-DATA) LENGTH(LENGTH OF ABEND-DATA) NOHANDLE ERASE END-EXEC");
        stubs.dummyExec(state, "CICS", "EXEC CICS HANDLE ABEND CANCEL END-EXEC");
        stubs.dummyExec(state, "CICS", "EXEC CICS ABEND ABCODE('9999') END-EXEC");
        // UNKNOWN: 
    }

    void do_ABEND_ROUTINE_EXIT(ProgramState state) {
        // EXIT
        // UNKNOWN: COPY CSUTLDPY
    }

    void do_ACUP_NEW_CASH_CREDIT_LIMIT_N(ProgramState state) {
        // empty paragraph
    }

    void do_ACUP_NEW_CREDIT_LIMIT_N(ProgramState state) {
        // empty paragraph
    }

    void do_ACUP_NEW_CURR_BAL_N(ProgramState state) {
        // empty paragraph
    }

    void do_ACUP_NEW_CURR_CYC_CREDIT_N(ProgramState state) {
        // empty paragraph
    }

    void do_ACUP_NEW_CURR_CYC_DEBIT_N(ProgramState state) {
        // empty paragraph
    }

    void do_EDIT_DATE_CCYYMMDD(ProgramState state) {
        // empty paragraph
    }

    void do_EDIT_DATE_OF_BIRTH(ProgramState state) {
        // empty paragraph
    }

    void do_YYYY_STORE_PFKEY(ProgramState state) {
        // empty paragraph
    }

}
