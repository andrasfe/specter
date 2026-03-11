package com.specter.generated;

/**
 * Generated section: Section6.
 */
public class Section6 extends SectionBase {

    public Section6(ParagraphRegistry registry, StubExecutor stubs) {
        super(registry, stubs);
        paragraph("6000-MAKE-DECISION", this::do_6000_MAKE_DECISION);
        paragraph("6000-EXIT", this::do_6000_EXIT);
    }

    void do_6000_MAKE_DECISION(ProgramState state) {
        state.put("PA-RL-CARD-NUM", state.get("PA-RQ-CARD-NUM"));
        state.put("PA-RL-TRANSACTION-ID", state.get("PA-RQ-TRANSACTION-ID"));
        state.put("PA-RL-AUTH-ID-CODE", state.get("PA-RQ-AUTH-TIME"));
        if (CobolRuntime.isTruthy(state.get("FOUND-PAUT-SMRY-SEG"))) {
            state.addBranch(23);
            state.put("WS-AVAILABLE-AMT", CobolRuntime.toNum(state.get("PA-CREDIT-LIMIT")));
            if (CobolRuntime.toNum(state.get("WS-TRANSACTION-AMT")) > CobolRuntime.toNum(state.get("WS-AVAILABLE-AMT"))) {
                state.addBranch(24);
                state.put("DECLINE-AUTH", true);
                state.put("INSUFFICIENT-FUND", true);
            } else {
                state.addBranch(-24);
            }
        } else {
            state.addBranch(-23);
            if (CobolRuntime.isTruthy(state.get("FOUND-ACCT-IN-MSTR"))) {
                state.addBranch(25);
                state.put("WS-AVAILABLE-AMT", CobolRuntime.toNum(state.get("ACCT-CREDIT-LIMIT")));
                if (CobolRuntime.toNum(state.get("WS-TRANSACTION-AMT")) > CobolRuntime.toNum(state.get("WS-AVAILABLE-AMT"))) {
                    state.addBranch(26);
                    state.put("DECLINE-AUTH", true);
                    state.put("INSUFFICIENT-FUND", true);
                } else {
                    state.addBranch(-26);
                }
            } else {
                state.addBranch(-25);
                state.put("DECLINE-AUTH", true);
            }
        }
        if (CobolRuntime.isTruthy(state.get("DECLINE-AUTH"))) {
            state.addBranch(27);
            state.put("AUTH-RESP-DECLINED", true);
            state.put("PA-RL-AUTH-RESP-CODE", "05");
            state.put("PA-RL-APPROVED-AMT", 0);
        } else {
            state.addBranch(-27);
            state.put("AUTH-RESP-APPROVED", true);
            state.put("PA-RL-AUTH-RESP-CODE", "00");
            state.put("PA-RL-APPROVED-AMT", state.get("PA-RQ-TRANSACTION-AMT"));
        }
        state.put("PA-RL-AUTH-RESP-REASON", "0000");
        if (CobolRuntime.isTruthy(state.get("AUTH-RESP-DECLINED"))) {
            state.addBranch(28);
            if (CobolRuntime.isTruthy(state.get("CARD-NFOUND-XREF"))) {
                state.addBranch(29);
                // empty WHEN
            }
            else if (CobolRuntime.isTruthy(state.get("NFOUND-ACCT-IN-MSTR"))) {
                state.addBranch(30);
                // empty WHEN
            }
            else if (CobolRuntime.isTruthy(state.get("NFOUND-CUST-IN-MSTR"))) {
                state.addBranch(31);
                state.put("PA-RL-AUTH-RESP-REASON", "3100");
            }
            else if (CobolRuntime.isTruthy(state.get("INSUFFICIENT-FUND"))) {
                state.addBranch(32);
                state.put("PA-RL-AUTH-RESP-REASON", "4100");
            }
            else if (CobolRuntime.isTruthy(state.get("CARD-NOT-ACTIVE"))) {
                state.addBranch(33);
                state.put("PA-RL-AUTH-RESP-REASON", "4200");
            }
            else if (CobolRuntime.isTruthy(state.get("ACCOUNT-CLOSED"))) {
                state.addBranch(34);
                state.put("PA-RL-AUTH-RESP-REASON", "4300");
            }
            else if (CobolRuntime.isTruthy(state.get("CARD-FRAUD"))) {
                state.addBranch(35);
                state.put("PA-RL-AUTH-RESP-REASON", "5100");
            }
            else if (CobolRuntime.isTruthy(state.get("MERCHANT-FRAUD"))) {
                state.addBranch(36);
                state.put("PA-RL-AUTH-RESP-REASON", "5200");
            }
            else {
                state.addBranch(37);
                state.put("PA-RL-AUTH-RESP-REASON", "9000");
            }
        } else {
            state.addBranch(-28);
        }
        state.put("WS-APPROVED-AMT-DIS", state.get("WS-APPROVED-AMT"));
        state.put("W02-PUT-BUFFER", String.valueOf(state.get("PA-RL-CARD-NUM")) + "," + String.valueOf(state.get("PA-RL-TRANSACTION-ID")) + "," + String.valueOf(state.get("PA-RL-AUTH-ID-CODE")) + "," + String.valueOf(state.get("PA-RL-AUTH-RESP-CODE")) + "," + String.valueOf(state.get("PA-RL-AUTH-RESP-REASON")) + "," + String.valueOf(state.get("WS-APPROVED-AMT-DIS")) + ",");
    }

    void do_6000_EXIT(ProgramState state) {
        // EXIT
    }

}
