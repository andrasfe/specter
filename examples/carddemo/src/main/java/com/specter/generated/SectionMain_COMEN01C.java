package com.specter.generated;

/**
 * Generated section: SectionMain.
 */
public class SectionMain_COMEN01C extends SectionBase {

    public SectionMain_COMEN01C(ParagraphRegistry registry, StubExecutor stubs) {
        super(registry, stubs);
        paragraph("MAIN-PARA", this::do_MAIN_PARA);
        paragraph("PROCESS-ENTER-KEY", this::do_PROCESS_ENTER_KEY);
        paragraph("RETURN-TO-SIGNON-SCREEN", this::do_RETURN_TO_SIGNON_SCREEN);
        paragraph("SEND-MENU-SCREEN", this::do_SEND_MENU_SCREEN);
        paragraph("RECEIVE-MENU-SCREEN", this::do_RECEIVE_MENU_SCREEN);
        paragraph("POPULATE-HEADER-INFO", this::do_POPULATE_HEADER_INFO);
        paragraph("BUILD-MENU-OPTIONS", this::do_BUILD_MENU_OPTIONS);
    }

    void do_MAIN_PARA(ProgramState state) {
        state.put("ERR-FLG-ON", false);
        state.put("ERR-FLG-OFF", true);
        state.put("WS-MESSAGE", " ");
        state.put("ERRMSGO", " ");
        if (java.util.Objects.equals(state.get("EIBCALEN"), 0)) {
            state.addBranch(1);
            state.put("CDEMO-FROM-PROGRAM", "COSGN00C");
            perform(state, "RETURN-TO-SIGNON-SCREEN");
        } else {
            state.addBranch(-1);
            state.put("CARDDEMO-COMMAREA", state.get("DFHCOMMAREA(1:EIBCALEN)"));
            if (!(CobolRuntime.isTruthy(state.get("CDEMO-PGM-REENTER")))) {
                state.addBranch(2);
                state.put("CDEMO-PGM-REENTER", true);
                state.put("COMEN1AO", "\u0000");
                perform(state, "SEND-MENU-SCREEN");
            } else {
                state.addBranch(-2);
                perform(state, "RECEIVE-MENU-SCREEN");
                Object _evalSubject1 = state.get("EIBAID");
                if ((java.util.Objects.equals(_evalSubject1, "DFHENTER"))) {
                    state.addBranch(3);
                    perform(state, "PROCESS-ENTER-KEY");
                }
                else if ((java.util.Objects.equals(_evalSubject1, "DFHPF3"))) {
                    state.addBranch(4);
                    state.put("CDEMO-TO-PROGRAM", "COSGN00C");
                    perform(state, "RETURN-TO-SIGNON-SCREEN");
                }
                else {
                    state.addBranch(5);
                    state.put("WS-ERR-FLG", "Y");
                    state.put("WS-MESSAGE", state.get("CCDA-MSG-INVALID-KEY"));
                    perform(state, "SEND-MENU-SCREEN");
                }
            }
        }
        stubs.cicsReturn(state, true);
    }

    void do_PROCESS_ENTER_KEY(ProgramState state) {
        int _lc1 = 0;
        while (true) /* VARYING: VARYING WS-IDX FROM LENGTH OF OPTIONI OF COMEN1AI  */ {
            // empty loop body
            _lc1++;
            if (_lc1 >= 100) {
                break;
            }
        }
        state.put("WS-OPTION-X", state.get("OPTIONI(1:WS-IDX)"));
        // INSPECT REPLACING: INSPECT WS-OPTION-X REPLACING ALL ' ' BY '0'
        state.put("WS-OPTION", state.get("WS-OPTION-X"));
        state.put("OPTIONO", state.get("WS-OPTION"));
        if (((!CobolRuntime.isNumeric(state.get("WS-OPTION"))) || (CobolRuntime.toNum(state.get("WS-OPTION")) > CobolRuntime.toNum(state.get("CDEMO-MENU-OPT-COUNT")))) || (java.util.Objects.equals(state.get("WS-OPTION"), 0))) {
            state.addBranch(6);
            state.put("WS-ERR-FLG", "Y");
            state.put("WS-MESSAGE", "Please enter a valid option number...");
            perform(state, "SEND-MENU-SCREEN");
        } else {
            state.addBranch(-6);
        }
        if ((CobolRuntime.isTruthy(state.get("CDEMO-USRTYP-USER"))) && (java.util.Objects.equals(state.get("CDEMO-MENU-OPT-USRTYPE(WS-OPTION)"), "A"))) {
            state.addBranch(7);
            state.put("ERR-FLG-OFF", false);
            state.put("ERR-FLG-ON", true);
            state.put("WS-MESSAGE", " ");
            state.put("WS-MESSAGE", "No access - Admin Only option... ");
            perform(state, "SEND-MENU-SCREEN");
        } else {
            state.addBranch(-7);
        }
        if (!(CobolRuntime.isTruthy(state.get("ERR-FLG-ON")))) {
            state.addBranch(8);
            if ((java.util.Objects.equals(state.get("CDEMO-MENU-OPT-PGMNAME(WS-OPTION)"), "COPAUS0C"))) {
                state.addBranch(9);
                stubs.dummyExec(state, "CICS", "EXEC CICS INQUIRE PROGRAM(CDEMO-MENU-OPT-PGMNAME(WS-OPTION)) NOHANDLE END-EXEC");
                if (java.util.Objects.equals(state.get("EIBRESP"), 0)) {
                    state.addBranch(10);
                    state.put("CDEMO-FROM-TRANID", state.get("WS-TRANID"));
                    state.put("CDEMO-FROM-PROGRAM", state.get("WS-PGMNAME"));
                    state.put("CDEMO-PGM-CONTEXT", 0);
                    stubs.dummyExec(state, "CICS", "EXEC CICS XCTL PROGRAM(CDEMO-MENU-OPT-PGMNAME(WS-OPTION)) COMMAREA(CARDDEMO-COMMAREA) END-EXEC");
                } else {
                    state.addBranch(-10);
                    state.put("WS-MESSAGE", " ");
                    state.put("ERRMSGC", state.get("DFHRED"));
                    state.put("WS-MESSAGE", "This option " + String.valueOf(state.get("CDEMO-MENU-OPT-NAME")) + String.valueOf(state.get("WS-OPTION")) + String.valueOf(state.get("DELIMITED")) + String.valueOf(state.get("BY")) + " " + " is not installed...");
                }
            }
            else if ((CobolRuntime.isTruthy(state.get("CDEMO-MENU-OPT-PGMNAME(WS-OPTION)")))) {
                state.addBranch(11);
                state.put("CDEMO-FROM-TRANID", state.get("WS-TRANID"));
                state.put("CDEMO-FROM-PROGRAM", state.get("WS-PGMNAME"));
                state.put("CDEMO-PGM-CONTEXT", 0);
                stubs.dummyExec(state, "CICS", "EXEC CICS XCTL PROGRAM(CDEMO-MENU-OPT-PGMNAME(WS-OPTION)) COMMAREA(CARDDEMO-COMMAREA) END-EXEC");
            }
            else {
                state.addBranch(12);
                state.put("WS-MESSAGE", "Option not available");
            }
            perform(state, "SEND-MENU-SCREEN");
        } else {
            state.addBranch(-8);
        }
    }

    void do_RETURN_TO_SIGNON_SCREEN(ProgramState state) {
        if (java.util.List.of("\u0000", " ").contains(state.get("CDEMO-TO-PROGRAM"))) {
            state.addBranch(13);
            state.put("CDEMO-TO-PROGRAM", "COSGN00C");
        } else {
            state.addBranch(-13);
        }
        stubs.dummyExec(state, "CICS", "EXEC CICS XCTL PROGRAM(CDEMO-TO-PROGRAM) END-EXEC");
    }

    void do_SEND_MENU_SCREEN(ProgramState state) {
        perform(state, "POPULATE-HEADER-INFO");
        perform(state, "BUILD-MENU-OPTIONS");
        state.put("ERRMSGO", state.get("WS-MESSAGE"));
        stubs.dummyExec(state, "CICS", "EXEC CICS SEND MAP('COMEN1A') MAPSET('COMEN01') FROM(COMEN1AO) ERASE END-EXEC");
    }

    void do_RECEIVE_MENU_SCREEN(ProgramState state) {
        stubs.dummyExec(state, "CICS", "EXEC CICS RECEIVE MAP('COMEN1A') MAPSET('COMEN01') INTO(COMEN1AI) RESP(WS-RESP-CD) RESP2(WS-REAS-CD) END-EXEC");
    }

    void do_POPULATE_HEADER_INFO(ProgramState state) {
        state.put("WS-CURDATE-DATA", new java.text.SimpleDateFormat("yyyyMMddHHmmssSSS").format(new java.util.Date()));
        state.put("TITLE01O", state.get("CCDA-TITLE01"));
        state.put("TITLE02O", state.get("CCDA-TITLE02"));
        state.put("TRNNAMEO", state.get("WS-TRANID"));
        state.put("PGMNAMEO", state.get("WS-PGMNAME"));
        state.put("WS-CURDATE-MM", state.get("WS-CURDATE-MONTH"));
        state.put("WS-CURDATE-DD", state.get("WS-CURDATE-DAY"));
        state.put("WS-CURDATE-YY", (String.valueOf(state.get("WS-CURDATE-YEAR")).length() > 2 ? String.valueOf(state.get("WS-CURDATE-YEAR")).substring(2, Math.min(4, String.valueOf(state.get("WS-CURDATE-YEAR")).length())) : ""));
        state.put("CURDATEO", state.get("WS-CURDATE-MM-DD-YY"));
        state.put("WS-CURTIME-HH", state.get("WS-CURTIME-HOURS"));
        state.put("WS-CURTIME-MM", state.get("WS-CURTIME-MINUTE"));
        state.put("WS-CURTIME-SS", state.get("WS-CURTIME-SECOND"));
        state.put("CURTIMEO", state.get("WS-CURTIME-HH-MM-SS"));
    }

    void do_BUILD_MENU_OPTIONS(ProgramState state) {
        state.put("WS-IDX", CobolRuntime.toNum(1));
        int _lc2 = 0;
        while (!(CobolRuntime.toNum(state.get("WS-IDX")) > CobolRuntime.toNum(state.get("CDEMO-MENU-OPT-COUNT")))) {
            state.addBranch(14);
            state.put("WS-MENU-OPT-TXT", " ");
            state.put("WS-MENU-OPT-TXT", String.valueOf(state.get("CDEMO-MENU-OPT-NUM")) + String.valueOf(state.get("WS-IDX")) + ". " + String.valueOf(state.get("CDEMO-MENU-OPT-NAME")) + String.valueOf(state.get("WS-IDX")));
            Object _evalSubject3 = state.get("WS-IDX");
            _evalSubject3 = CobolRuntime.toNum(_evalSubject3);
            if ((java.util.Objects.equals(_evalSubject3, CobolRuntime.toNum(1)))) {
                state.addBranch(15);
                state.put("OPTN001O", state.get("WS-MENU-OPT-TXT"));
            }
            else if ((java.util.Objects.equals(_evalSubject3, CobolRuntime.toNum(2)))) {
                state.addBranch(16);
                state.put("OPTN002O", state.get("WS-MENU-OPT-TXT"));
            }
            else if ((java.util.Objects.equals(_evalSubject3, CobolRuntime.toNum(3)))) {
                state.addBranch(17);
                state.put("OPTN003O", state.get("WS-MENU-OPT-TXT"));
            }
            else if ((java.util.Objects.equals(_evalSubject3, CobolRuntime.toNum(4)))) {
                state.addBranch(18);
                state.put("OPTN004O", state.get("WS-MENU-OPT-TXT"));
            }
            else if ((java.util.Objects.equals(_evalSubject3, CobolRuntime.toNum(5)))) {
                state.addBranch(19);
                state.put("OPTN005O", state.get("WS-MENU-OPT-TXT"));
            }
            else if ((java.util.Objects.equals(_evalSubject3, CobolRuntime.toNum(6)))) {
                state.addBranch(20);
                state.put("OPTN006O", state.get("WS-MENU-OPT-TXT"));
            }
            else if ((java.util.Objects.equals(_evalSubject3, CobolRuntime.toNum(7)))) {
                state.addBranch(21);
                state.put("OPTN007O", state.get("WS-MENU-OPT-TXT"));
            }
            else if ((java.util.Objects.equals(_evalSubject3, CobolRuntime.toNum(8)))) {
                state.addBranch(22);
                state.put("OPTN008O", state.get("WS-MENU-OPT-TXT"));
            }
            else if ((java.util.Objects.equals(_evalSubject3, CobolRuntime.toNum(9)))) {
                state.addBranch(23);
                state.put("OPTN009O", state.get("WS-MENU-OPT-TXT"));
            }
            else if ((java.util.Objects.equals(_evalSubject3, CobolRuntime.toNum(10)))) {
                state.addBranch(24);
                state.put("OPTN010O", state.get("WS-MENU-OPT-TXT"));
            }
            else if ((java.util.Objects.equals(_evalSubject3, CobolRuntime.toNum(11)))) {
                state.addBranch(25);
                state.put("OPTN011O", state.get("WS-MENU-OPT-TXT"));
            }
            else if ((java.util.Objects.equals(_evalSubject3, CobolRuntime.toNum(12)))) {
                state.addBranch(26);
                state.put("OPTN012O", state.get("WS-MENU-OPT-TXT"));
            }
            else {
                state.addBranch(27);
                // CONTINUE
            }
            state.put("WS-IDX", CobolRuntime.toNum(state.get("WS-IDX")) + CobolRuntime.toNum(1));
            _lc2++;
            if (_lc2 >= 100) {
                break;
            }
        }
        if (_lc2 == 0) {
            state.addBranch(-14);
        }
    }

}
