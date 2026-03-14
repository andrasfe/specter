package com.specter.generated;

/**
 * Generated section: Section0.
 */
public class Section0 extends SectionBase {

    public Section0(ParagraphRegistry registry, StubExecutor stubs) {
        super(registry, stubs);
        paragraph("0000-MAIN", this::do_0000_MAIN);
        paragraph("0000-MAIN-EXIT", this::do_0000_MAIN_EXIT);
    }

    void do_0000_MAIN(ProgramState state) {
        stubs.dummyExec(state, "CICS", "EXEC CICS HANDLE ABEND LABEL(ABEND-ROUTINE) END-EXEC");
        state.put("CC-WORK-AREA", state.get("CC-WORK-AREA") instanceof Number ? 0 : "");
        state.put("WS-TRANID", state.get("LIT-THISTRANID"));
        state.put("WS-RETURN-MSG-OFF", true);
        if ((java.util.Objects.equals(state.get("EIBCALEN"), 0)) || ((java.util.Objects.equals(state.get("CDEMO-FROM-PROGRAM"), state.get("LIT-MENUPGM"))) && (!(CobolRuntime.isTruthy(state.get("CDEMO-PGM-REENTER")))))) {
            state.addBranch(1);
            state.put("CARDDEMO-COMMAREA", state.get("CARDDEMO-COMMAREA") instanceof Number ? 0 : "");
            state.put("CDEMO-PGM-ENTER", true);
            state.put("ACUP-DETAILS-NOT-FETCHED", true);
        } else {
            state.addBranch(-1);
            state.put("CARDDEMO-COMMAREA", state.get("DFHCOMMAREA (1:LENGTH)"));
            // UNKNOWN: MOVE DFHCOMMAREA(LENGTH OF CARDDEMO-COMMAREA + 1: LENGTH OF 
        }
        perform(state, "YYYY-STORE-PFKEY");
        state.put("PFK-INVALID", true);
        if ((((CobolRuntime.isTruthy(state.get("CCARD-AID-ENTER"))) || (CobolRuntime.isTruthy(state.get("CCARD-AID-PFK03")))) || ((CobolRuntime.isTruthy(state.get("CCARD-AID-PFK05"))) && (CobolRuntime.isTruthy(state.get("ACUP-CHANGES-OK-NOT-CONFIRMED"))))) || ((CobolRuntime.isTruthy(state.get("CCARD-AID-PFK12"))) && (!(CobolRuntime.isTruthy(state.get("ACUP-DETAILS-NOT-FETCHED")))))) {
            state.addBranch(2);
            state.put("PFK-VALID", true);
        } else {
            state.addBranch(-2);
        }
        if (CobolRuntime.isTruthy(state.get("PFK-INVALID"))) {
            state.addBranch(3);
            state.put("CCARD-AID-ENTER", true);
        } else {
            state.addBranch(-3);
        }
        if (CobolRuntime.isTruthy(state.get("CCARD-AID-PFK03"))) {
            state.addBranch(4);
            state.put("CCARD-AID-PFK03", true);
            if ((java.util.Objects.equals(state.get("CDEMO-FROM-TRANID"), "\u0000")) || (java.util.Objects.equals(state.get("CDEMO-FROM-TRANID"), " "))) {
                state.addBranch(5);
                state.put("CDEMO-TO-TRANID", state.get("LIT-MENUTRANID"));
            } else {
                state.addBranch(-5);
                state.put("CDEMO-TO-TRANID", state.get("CDEMO-FROM-TRANID"));
            }
            if ((java.util.Objects.equals(state.get("CDEMO-FROM-PROGRAM"), "\u0000")) || (java.util.Objects.equals(state.get("CDEMO-FROM-PROGRAM"), " "))) {
                state.addBranch(6);
                state.put("CDEMO-TO-PROGRAM", state.get("LIT-MENUPGM"));
            } else {
                state.addBranch(-6);
                state.put("CDEMO-TO-PROGRAM", state.get("CDEMO-FROM-PROGRAM"));
            }
            state.put("CDEMO-FROM-TRANID", state.get("LIT-THISTRANID"));
            state.put("CDEMO-FROM-PROGRAM", state.get("LIT-THISPGM"));
            state.put("CDEMO-USRTYP-USER", true);
            state.put("CDEMO-PGM-ENTER", true);
            state.put("CDEMO-LAST-MAPSET", state.get("LIT-THISMAPSET"));
            state.put("CDEMO-LAST-MAP", state.get("LIT-THISMAP"));
            stubs.cicsSyncpoint(state);
            stubs.dummyExec(state, "CICS", "EXEC CICS XCTL PROGRAM (CDEMO-TO-PROGRAM) COMMAREA(CARDDEMO-COMMAREA) END-EXEC");
        }
        else if (CobolRuntime.isTruthy(state.get("ACUP-DETAILS-NOT-FETCHED"))) {
            state.addBranch(7);
            // First entry: show the account lookup screen
            performThru(state, "3000-SEND-MAP", "3000-SEND-MAP-EXIT");
            state.put("CDEMO-PGM-REENTER", true);
            registry.get("COMMON-RETURN").execute(state);
            return;
        }
        else if (java.util.Objects.equals(state.get("CDEMO-FROM-PROGRAM"), state.get("LIT-MENUPGM"))) {
            state.addBranch(8);
            state.put("WS-THIS-PROGCOMMAREA", state.get("WS-THIS-PROGCOMMAREA") instanceof Number ? 0 : "");
            performThru(state, "3000-SEND-MAP", "3000-SEND-MAP-EXIT");
            state.put("CDEMO-PGM-REENTER", true);
            state.put("ACUP-DETAILS-NOT-FETCHED", true);
            registry.get("COMMON-RETURN").execute(state);
            return;
        }
        else if (CobolRuntime.isTruthy(state.get("ACUP-CHANGES-OKAYED-AND-DONE"))) {
            state.addBranch(9);
            // empty WHEN
        }
        else if (CobolRuntime.isTruthy(state.get("ACUP-CHANGES-FAILED"))) {
            state.addBranch(10);
            state.put("WS-THIS-PROGCOMMAREA", state.get("WS-THIS-PROGCOMMAREA") instanceof Number ? 0 : "");
            state.put("CDEMO-PGM-ENTER", true);
            performThru(state, "3000-SEND-MAP", "3000-SEND-MAP-EXIT");
            state.put("CDEMO-PGM-REENTER", true);
            state.put("ACUP-DETAILS-NOT-FETCHED", true);
            registry.get("COMMON-RETURN").execute(state);
            return;
        }
        else {
            state.addBranch(11);
            performThru(state, "1000-PROCESS-INPUTS", "1000-PROCESS-INPUTS-EXIT");
            performThru(state, "2000-DECIDE-ACTION", "2000-DECIDE-ACTION-EXIT");
            performThru(state, "3000-SEND-MAP", "3000-SEND-MAP-EXIT");
            registry.get("COMMON-RETURN").execute(state);
            return;
        }
    }

    void do_0000_MAIN_EXIT(ProgramState state) {
        // EXIT
    }

}
