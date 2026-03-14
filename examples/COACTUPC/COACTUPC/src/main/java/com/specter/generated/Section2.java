package com.specter.generated;

/**
 * Generated section: Section2.
 */
public class Section2 extends SectionBase {

    public Section2(ParagraphRegistry registry, StubExecutor stubs) {
        super(registry, stubs);
        paragraph("2000-DECIDE-ACTION", this::do_2000_DECIDE_ACTION);
        paragraph("2000-DECIDE-ACTION-EXIT", this::do_2000_DECIDE_ACTION_EXIT);
    }

    void do_2000_DECIDE_ACTION(ProgramState state) {
        if (CobolRuntime.isTruthy(state.get("ACUP-DETAILS-NOT-FETCHED"))) {
            state.addBranch(136);
            // If user entered an account ID, fetch the account data
            Object ccAcctId = state.get("CC-ACCT-ID");
            if (ccAcctId != null && !"\u0000".equals(ccAcctId)
                    && !" ".equals(String.valueOf(ccAcctId).trim())
                    && !"".equals(String.valueOf(ccAcctId).trim())
                    && !java.util.Objects.equals(ccAcctId, 0)) {
                state.put("WS-CARD-RID-ACCT-ID", ccAcctId);
                state.put("WS-CARD-RID-ACCT-ID-X", String.valueOf(ccAcctId));
                state.put("FLG-ACCTFILTER-NOT-OK", false);
                state.put("FLG-ACCTFILTER-ISVALID", true);
                state.put("WS-RETURN-MSG-OFF", true);
                performThru(state, "9000-READ-ACCT", "9000-READ-ACCT-EXIT");
                if (CobolRuntime.isTruthy(state.get("FOUND-CUST-IN-MASTER"))) {
                    state.put("ACUP-SHOW-DETAILS", true);
                    state.put("ACUP-DETAILS-NOT-FETCHED", false);
                }
            }
        }
        else if (CobolRuntime.isTruthy(state.get("CCARD-AID-PFK12"))) {
            state.addBranch(137);
            if (CobolRuntime.isTruthy(state.get("FLG-ACCTFILTER-ISVALID"))) {
                state.addBranch(138);
                state.put("WS-RETURN-MSG-OFF", true);
                performThru(state, "9000-READ-ACCT", "9000-READ-ACCT-EXIT");
                if (CobolRuntime.isTruthy(state.get("FOUND-CUST-IN-MASTER"))) {
                    state.addBranch(139);
                    state.put("ACUP-SHOW-DETAILS", true);
                } else {
                    state.addBranch(-139);
                }
            } else {
                state.addBranch(-138);
            }
        }
        else if (CobolRuntime.isTruthy(state.get("ACUP-SHOW-DETAILS"))) {
            state.addBranch(140);
            if ((CobolRuntime.isTruthy(state.get("INPUT-ERROR"))) || (CobolRuntime.isTruthy(state.get("NO-CHANGES-DETECTED")))) {
                state.addBranch(141);
                // CONTINUE
            } else {
                state.addBranch(-141);
                state.put("ACUP-CHANGES-OK-NOT-CONFIRMED", true);
            }
        }
        else if (CobolRuntime.isTruthy(state.get("ACUP-CHANGES-NOT-OK"))) {
            state.addBranch(142);
            // CONTINUE
        }
        else if (CobolRuntime.isTruthy(state.get("ACUP-CHANGES-OK-NOT-CONFIRMED"))) {
            state.addBranch(143);
            performThru(state, "9600-WRITE-PROCESSING", "9600-WRITE-PROCESSING-EXIT");
            if (CobolRuntime.isTruthy(state.get("COULD-NOT-LOCK-ACCT-FOR-UPDATE"))) {
                state.addBranch(144);
                state.put("ACUP-CHANGES-OKAYED-LOCK-ERROR", true);
            }
            else if (CobolRuntime.isTruthy(state.get("LOCKED-BUT-UPDATE-FAILED"))) {
                state.addBranch(145);
                state.put("ACUP-CHANGES-OKAYED-BUT-FAILED", true);
            }
            else if (CobolRuntime.isTruthy(state.get("DATA-WAS-CHANGED-BEFORE-UPDATE"))) {
                state.addBranch(146);
                state.put("ACUP-SHOW-DETAILS", true);
            }
            else {
                state.addBranch(147);
                state.put("ACUP-CHANGES-OKAYED-AND-DONE", true);
            }
        }
        else if (CobolRuntime.isTruthy(state.get("ACUP-CHANGES-OK-NOT-CONFIRMED"))) {
            state.addBranch(148);
            // CONTINUE
        }
        else if (CobolRuntime.isTruthy(state.get("ACUP-CHANGES-OKAYED-AND-DONE"))) {
            state.addBranch(149);
            state.put("ACUP-SHOW-DETAILS", true);
            if ((java.util.Objects.equals(state.get("CDEMO-FROM-TRANID"), "\u0000")) || (java.util.Objects.equals(state.get("CDEMO-FROM-TRANID"), " "))) {
                state.addBranch(150);
                state.put("CDEMO-ACCT-ID", 0);
                state.put("CDEMO-ACCT-STATUS", "\u0000");
            } else {
                state.addBranch(-150);
            }
        }
        else {
            state.addBranch(151);
            state.put("ABEND-CULPRIT", state.get("LIT-THISPGM"));
            state.put("ABEND-CODE", "0001");
            state.put("ABEND-REASON", " ");
            state.put("ABEND-MSG", "UNEXPECTED DATA SCENARIO");
            performThru(state, "ABEND-ROUTINE", "ABEND-ROUTINE-EXIT");
        }
    }

    void do_2000_DECIDE_ACTION_EXIT(ProgramState state) {
        // EXIT
    }

}
