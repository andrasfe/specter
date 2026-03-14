package com.specter.generated;

/**
 * Generated section: Section5.
 */
public class Section5 extends SectionBase {

    public Section5(ParagraphRegistry registry, StubExecutor stubs) {
        super(registry, stubs);
        paragraph("5000-PROCESS-AUTH", this::do_5000_PROCESS_AUTH);
        paragraph("5000-EXIT", this::do_5000_EXIT);
        paragraph("5100-READ-XREF-RECORD", this::do_5100_READ_XREF_RECORD);
        paragraph("5100-EXIT", this::do_5100_EXIT);
        paragraph("5200-READ-ACCT-RECORD", this::do_5200_READ_ACCT_RECORD);
        paragraph("5200-EXIT", this::do_5200_EXIT);
        paragraph("5300-READ-CUST-RECORD", this::do_5300_READ_CUST_RECORD);
        paragraph("5300-EXIT", this::do_5300_EXIT);
        paragraph("5500-READ-AUTH-SUMMRY", this::do_5500_READ_AUTH_SUMMRY);
        paragraph("5500-EXIT", this::do_5500_EXIT);
        paragraph("5600-READ-PROFILE-DATA", this::do_5600_READ_PROFILE_DATA);
        paragraph("5600-EXIT", this::do_5600_EXIT);
    }

    void do_5000_PROCESS_AUTH(ProgramState state) {
        state.put("APPROVE-AUTH", true);
        performThru(state, "1200-SCHEDULE-PSB", "1200-EXIT");
        state.put("CARD-FOUND-XREF", true);
        state.put("FOUND-ACCT-IN-MSTR", true);
        performThru(state, "5100-READ-XREF-RECORD", "5100-EXIT");
        if (CobolRuntime.isTruthy(state.get("CARD-FOUND-XREF"))) {
            state.addBranch(9);
            performThru(state, "5200-READ-ACCT-RECORD", "5200-EXIT");
            performThru(state, "5300-READ-CUST-RECORD", "5300-EXIT");
            performThru(state, "5500-READ-AUTH-SUMMRY", "5500-EXIT");
            performThru(state, "5600-READ-PROFILE-DATA", "5600-EXIT");
        } else {
            state.addBranch(-9);
        }
        performThru(state, "6000-MAKE-DECISION", "6000-EXIT");
        performThru(state, "7100-SEND-RESPONSE", "7100-EXIT");
        if (CobolRuntime.isTruthy(state.get("CARD-FOUND-XREF"))) {
            state.addBranch(10);
            performThru(state, "8000-WRITE-AUTH-TO-DB", "8000-EXIT");
        } else {
            state.addBranch(-10);
        }
    }

    void do_5000_EXIT(ProgramState state) {
        // EXIT
    }

    void do_5100_READ_XREF_RECORD(ProgramState state) {
        state.put("XREF-CARD-NUM", state.get("PA-RQ-CARD-NUM"));
        stubs.cicsRead(state, "WS-CCXREF-FILE", "XREF-CARD-NUM", "CARD-XREF-RECORD", "WS-RESP-CD", "WS-REAS-CD");
        Object _evalSubject1 = state.get("WS-RESP-CD");
        if ((java.util.Objects.equals(_evalSubject1, 0))) {
            state.addBranch(11);
            state.put("CARD-FOUND-XREF", true);
        }
        else if ((java.util.Objects.equals(_evalSubject1, 13))) {
            state.addBranch(12);
            state.put("CARD-NFOUND-XREF", true);
            state.put("NFOUND-CUST-IN-MSTR", false);
            state.put("NFOUND-ACCT-IN-MSTR", true);
            state.put("ERR-LOCATION", "A001");
            state.put("ERR-WARNING", true);
            state.put("ERR-APP", true);
            state.put("ERR-MESSAGE", "CARD NOT FOUND IN XREF");
            state.put("ERR-EVENT-KEY", state.get("XREF-CARD-NUM"));
            perform(state, "9500-LOG-ERROR");
        }
        else {
            state.addBranch(13);
            state.put("ERR-LOCATION", "C001");
            state.put("ERR-CRITICAL", true);
            state.put("ERR-CICS", true);
            state.put("WS-CODE-DISPLAY", state.get("WS-RESP-CD"));
            state.put("ERR-CODE-1", state.get("WS-CODE-DISPLAY"));
            state.put("WS-CODE-DISPLAY", state.get("WS-REAS-CD"));
            state.put("ERR-CODE-2", state.get("WS-CODE-DISPLAY"));
            state.put("READ", state.get("FAILED"));
            state.put("XREF", state.get("FAILED"));
            state.put("FILE", state.get("FAILED"));
            state.put("ERR-EVENT-KEY", state.get("XREF-CARD-NUM"));
            perform(state, "9500-LOG-ERROR");
        }
    }

    void do_5100_EXIT(ProgramState state) {
        // EXIT
    }

    void do_5200_READ_ACCT_RECORD(ProgramState state) {
        state.put("WS-CARD-RID-ACCT-ID", state.get("XREF-ACCT-ID"));
        stubs.cicsRead(state, "WS-ACCTFILENAME", "WS-CARD-RID-ACCT-ID-X", "ACCOUNT-RECORD", "WS-RESP-CD", "WS-REAS-CD");
        Object _evalSubject2 = state.get("WS-RESP-CD");
        if ((java.util.Objects.equals(_evalSubject2, 0))) {
            state.addBranch(14);
            state.put("FOUND-ACCT-IN-MSTR", true);
        }
        else if ((java.util.Objects.equals(_evalSubject2, 13))) {
            state.addBranch(15);
            state.put("NFOUND-CUST-IN-MSTR", false);
            state.put("NFOUND-ACCT-IN-MSTR", true);
            state.put("ERR-LOCATION", "A002");
            state.put("ERR-WARNING", true);
            state.put("ERR-APP", true);
            state.put("ERR-MESSAGE", "ACCT NOT FOUND IN XREF");
            state.put("ERR-EVENT-KEY", state.get("WS-CARD-RID-ACCT-ID-X"));
            perform(state, "9500-LOG-ERROR");
        }
        else {
            state.addBranch(16);
            state.put("ERR-LOCATION", "C002");
            state.put("ERR-CRITICAL", true);
            state.put("ERR-CICS", true);
            state.put("WS-CODE-DISPLAY", state.get("WS-RESP-CD"));
            state.put("ERR-CODE-1", state.get("WS-CODE-DISPLAY"));
            state.put("WS-CODE-DISPLAY", state.get("WS-REAS-CD"));
            state.put("ERR-CODE-2", state.get("WS-CODE-DISPLAY"));
            state.put("READ", state.get("FAILED"));
            state.put("ACCT", state.get("FAILED"));
            state.put("FILE", state.get("FAILED"));
            state.put("ERR-EVENT-KEY", state.get("WS-CARD-RID-ACCT-ID-X"));
            perform(state, "9500-LOG-ERROR");
        }
    }

    void do_5200_EXIT(ProgramState state) {
        // EXIT
    }

    void do_5300_READ_CUST_RECORD(ProgramState state) {
        state.put("WS-CARD-RID-CUST-ID", state.get("XREF-CUST-ID"));
        stubs.cicsRead(state, "WS-CUSTFILENAME", "WS-CARD-RID-CUST-ID-X", "CUSTOMER-RECORD", "WS-RESP-CD", "WS-REAS-CD");
        Object _evalSubject3 = state.get("WS-RESP-CD");
        if ((java.util.Objects.equals(_evalSubject3, 0))) {
            state.addBranch(17);
            state.put("FOUND-CUST-IN-MSTR", true);
        }
        else if ((java.util.Objects.equals(_evalSubject3, 13))) {
            state.addBranch(18);
            state.put("NFOUND-ACCT-IN-MSTR", false);
            state.put("NFOUND-CUST-IN-MSTR", true);
            state.put("ERR-LOCATION", "A003");
            state.put("ERR-WARNING", true);
            state.put("ERR-APP", true);
            state.put("ERR-MESSAGE", "CUST NOT FOUND IN XREF");
            state.put("ERR-EVENT-KEY", state.get("WS-CARD-RID-CUST-ID"));
            perform(state, "9500-LOG-ERROR");
        }
        else {
            state.addBranch(19);
            state.put("ERR-LOCATION", "C003");
            state.put("ERR-CRITICAL", true);
            state.put("ERR-CICS", true);
            state.put("WS-CODE-DISPLAY", state.get("WS-RESP-CD"));
            state.put("ERR-CODE-1", state.get("WS-CODE-DISPLAY"));
            state.put("WS-CODE-DISPLAY", state.get("WS-REAS-CD"));
            state.put("ERR-CODE-2", state.get("WS-CODE-DISPLAY"));
            state.put("READ", state.get("FAILED"));
            state.put("CUST", state.get("FAILED"));
            state.put("FILE", state.get("FAILED"));
            state.put("ERR-EVENT-KEY", state.get("WS-CARD-RID-CUST-ID"));
            perform(state, "9500-LOG-ERROR");
        }
    }

    void do_5300_EXIT(ProgramState state) {
        // EXIT
    }

    void do_5500_READ_AUTH_SUMMRY(ProgramState state) {
        state.put("PA-ACCT-ID", state.get("XREF-ACCT-ID"));
        stubs.dliGetUnique(state, "PAUTSUM0", "PENDING-AUTH-SUMMARY", "ACCNTID", "PA-ACCT-ID");
        state.put("IMS-RETURN-CODE", state.get("DIBSTAT"));
        if ((CobolRuntime.isTruthy(state.get("STATUS-OK")))) {
            state.addBranch(20);
            state.put("FOUND-PAUT-SMRY-SEG", true);
        }
        else if ((CobolRuntime.isTruthy(state.get("SEGMENT-NOT-FOUND")))) {
            state.addBranch(21);
            state.put("NFOUND-PAUT-SMRY-SEG", true);
        }
        else {
            state.addBranch(22);
            state.put("ERR-LOCATION", "I002");
            state.put("ERR-CRITICAL", true);
            state.put("ERR-IMS", true);
            state.put("ERR-CODE-1", state.get("IMS-RETURN-CODE"));
            state.put("ERR-MESSAGE", "IMS GET SUMMARY FAILED");
            state.put("ERR-EVENT-KEY", state.get("PA-CARD-NUM"));
            perform(state, "9500-LOG-ERROR");
        }
    }

    void do_5500_EXIT(ProgramState state) {
        // EXIT
    }

    void do_5600_READ_PROFILE_DATA(ProgramState state) {
        // CONTINUE
    }

    void do_5600_EXIT(ProgramState state) {
        // EXIT
    }

}
