package com.specter.generated;

/**
 * Generated section: SectionMain.
 */
public class SectionMain_COUSR03C extends SectionBase {

    public SectionMain_COUSR03C(ParagraphRegistry registry, StubExecutor stubs) {
        super(registry, stubs);
        paragraph("MAIN-PARA", this::do_MAIN_PARA);
        paragraph("PROCESS-ENTER-KEY", this::do_PROCESS_ENTER_KEY);
        paragraph("DELETE-USER-INFO", this::do_DELETE_USER_INFO);
        paragraph("RETURN-TO-PREV-SCREEN", this::do_RETURN_TO_PREV_SCREEN);
        paragraph("SEND-USRDEL-SCREEN", this::do_SEND_USRDEL_SCREEN);
        paragraph("RECEIVE-USRDEL-SCREEN", this::do_RECEIVE_USRDEL_SCREEN);
        paragraph("POPULATE-HEADER-INFO", this::do_POPULATE_HEADER_INFO);
        paragraph("READ-USER-SEC-FILE", this::do_READ_USER_SEC_FILE);
        paragraph("DELETE-USER-SEC-FILE", this::do_DELETE_USER_SEC_FILE);
        paragraph("CLEAR-CURRENT-SCREEN", this::do_CLEAR_CURRENT_SCREEN);
        paragraph("INITIALIZE-ALL-FIELDS", this::do_INITIALIZE_ALL_FIELDS);
    }

    void do_MAIN_PARA(ProgramState state) {
        state.put("ERR-FLG-OFF", true);
        state.put("USR-MODIFIED-NO", true);
        state.put("WS-MESSAGE", " ");
        state.put("ERRMSGO", " ");
        if (java.util.Objects.equals(state.get("EIBCALEN"), 0)) {
            state.addBranch(1);
            state.put("CDEMO-TO-PROGRAM", "COSGN00C");
            perform(state, "RETURN-TO-PREV-SCREEN");
        } else {
            state.addBranch(-1);
            state.put("CARDDEMO-COMMAREA", state.get("DFHCOMMAREA(1:EIBCALEN)"));
            if (!(CobolRuntime.isTruthy(state.get("CDEMO-PGM-REENTER")))) {
                state.addBranch(2);
                state.put("CDEMO-PGM-REENTER", true);
                state.put("COUSR3AO", "\u0000");
                state.put("USRIDINL", -1);
                if (!java.util.List.of(" ", "\u0000").contains(state.get("CDEMO-CU03-USR-SELECTED"))) {
                    state.addBranch(3);
                    state.put("USRIDINI", state.get("CDEMO-CU03-USR-SELECTED"));
                    perform(state, "PROCESS-ENTER-KEY");
                } else {
                    state.addBranch(-3);
                }
                perform(state, "SEND-USRDEL-SCREEN");
            } else {
                state.addBranch(-2);
                perform(state, "RECEIVE-USRDEL-SCREEN");
                Object _evalSubject1 = state.get("EIBAID");
                if ((java.util.Objects.equals(_evalSubject1, "DFHENTER"))) {
                    state.addBranch(4);
                    perform(state, "PROCESS-ENTER-KEY");
                }
                else if ((java.util.Objects.equals(_evalSubject1, "DFHPF3"))) {
                    state.addBranch(5);
                    if (java.util.List.of(" ", "\u0000").contains(state.get("CDEMO-FROM-PROGRAM"))) {
                        state.addBranch(6);
                        state.put("CDEMO-TO-PROGRAM", "COADM01C");
                    } else {
                        state.addBranch(-6);
                        state.put("CDEMO-TO-PROGRAM", state.get("CDEMO-FROM-PROGRAM"));
                    }
                    perform(state, "RETURN-TO-PREV-SCREEN");
                }
                else if ((java.util.Objects.equals(_evalSubject1, "DFHPF4"))) {
                    state.addBranch(7);
                    perform(state, "CLEAR-CURRENT-SCREEN");
                }
                else if ((java.util.Objects.equals(_evalSubject1, "DFHPF5"))) {
                    state.addBranch(8);
                    perform(state, "DELETE-USER-INFO");
                }
                else if ((java.util.Objects.equals(_evalSubject1, "DFHPF12"))) {
                    state.addBranch(9);
                    state.put("CDEMO-TO-PROGRAM", "COADM01C");
                    perform(state, "RETURN-TO-PREV-SCREEN");
                }
                else {
                    state.addBranch(10);
                    state.put("WS-ERR-FLG", "Y");
                    state.put("WS-MESSAGE", state.get("CCDA-MSG-INVALID-KEY"));
                    perform(state, "SEND-USRDEL-SCREEN");
                }
            }
        }
        stubs.cicsReturn(state, true);
    }

    void do_PROCESS_ENTER_KEY(ProgramState state) {
        if ((java.util.List.of(" ", "\u0000").contains(state.get("USRIDINI")))) {
            state.addBranch(11);
            state.put("WS-ERR-FLG", "Y");
            state.put("WS-MESSAGE", "User ID can NOT be empty...");
            state.put("USRIDINL", -1);
            perform(state, "SEND-USRDEL-SCREEN");
        }
        else {
            state.addBranch(12);
            state.put("USRIDINL", -1);
            // CONTINUE
        }
        if (!(CobolRuntime.isTruthy(state.get("ERR-FLG-ON")))) {
            state.addBranch(13);
            state.put("FNAMEI", " ");
            state.put("LNAMEI", " ");
            state.put("USRTYPEI", " ");
            state.put("SEC-USR-ID", state.get("USRIDINI"));
            perform(state, "READ-USER-SEC-FILE");
        } else {
            state.addBranch(-13);
        }
        if (!(CobolRuntime.isTruthy(state.get("ERR-FLG-ON")))) {
            state.addBranch(14);
            state.put("FNAMEI", state.get("SEC-USR-FNAME"));
            state.put("LNAMEI", state.get("SEC-USR-LNAME"));
            state.put("USRTYPEI", state.get("SEC-USR-TYPE"));
            perform(state, "SEND-USRDEL-SCREEN");
        } else {
            state.addBranch(-14);
        }
    }

    void do_DELETE_USER_INFO(ProgramState state) {
        if ((java.util.List.of(" ", "\u0000").contains(state.get("USRIDINI")))) {
            state.addBranch(15);
            state.put("WS-ERR-FLG", "Y");
            state.put("WS-MESSAGE", "User ID can NOT be empty...");
            state.put("USRIDINL", -1);
            perform(state, "SEND-USRDEL-SCREEN");
        }
        else {
            state.addBranch(16);
            state.put("USRIDINL", -1);
            // CONTINUE
        }
        if (!(CobolRuntime.isTruthy(state.get("ERR-FLG-ON")))) {
            state.addBranch(17);
            state.put("SEC-USR-ID", state.get("USRIDINI"));
            perform(state, "READ-USER-SEC-FILE");
            perform(state, "DELETE-USER-SEC-FILE");
        } else {
            state.addBranch(-17);
        }
    }

    void do_RETURN_TO_PREV_SCREEN(ProgramState state) {
        if (java.util.List.of("\u0000", " ").contains(state.get("CDEMO-TO-PROGRAM"))) {
            state.addBranch(18);
            state.put("CDEMO-TO-PROGRAM", "COSGN00C");
        } else {
            state.addBranch(-18);
        }
        state.put("CDEMO-FROM-TRANID", state.get("WS-TRANID"));
        state.put("CDEMO-FROM-PROGRAM", state.get("WS-PGMNAME"));
        state.put("CDEMO-PGM-CONTEXT", 0);
        stubs.dummyExec(state, "CICS", "EXEC CICS XCTL PROGRAM(CDEMO-TO-PROGRAM) COMMAREA(CARDDEMO-COMMAREA) END-EXEC");
    }

    void do_SEND_USRDEL_SCREEN(ProgramState state) {
        perform(state, "POPULATE-HEADER-INFO");
        state.put("ERRMSGO", state.get("WS-MESSAGE"));
        stubs.dummyExec(state, "CICS", "EXEC CICS SEND MAP('COUSR3A') MAPSET('COUSR03') FROM(COUSR3AO) ERASE CURSOR END-EXEC");
    }

    void do_RECEIVE_USRDEL_SCREEN(ProgramState state) {
        stubs.dummyExec(state, "CICS", "EXEC CICS RECEIVE MAP('COUSR3A') MAPSET('COUSR03') INTO(COUSR3AI) RESP(WS-RESP-CD) RESP2(WS-REAS-CD) END-EXEC");
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

    void do_READ_USER_SEC_FILE(ProgramState state) {
        stubs.cicsRead(state, "WS-USRSEC-FILE", "SEC-USR-ID", "SEC-USER-DATA", "WS-RESP-CD", "WS-REAS-CD");
        Object _evalSubject4 = state.get("WS-RESP-CD");
        if ((java.util.Objects.equals(_evalSubject4, 0))) {
            state.addBranch(19);
            // CONTINUE
            state.put("WS-MESSAGE", "Press PF5 key to delete this user ...");
            state.put("ERRMSGC", state.get("DFHNEUTR"));
            perform(state, "SEND-USRDEL-SCREEN");
        }
        else if ((java.util.Objects.equals(_evalSubject4, 13))) {
            state.addBranch(20);
            state.put("WS-ERR-FLG", "Y");
            state.put("WS-MESSAGE", "User ID NOT found...");
            state.put("USRIDINL", -1);
            perform(state, "SEND-USRDEL-SCREEN");
        }
        else {
            state.addBranch(21);
            display(state, "RESP:", String.valueOf(state.get("WS-RESP-CD")), "REAS:", String.valueOf(state.get("WS-REAS-CD")));
            state.put("WS-ERR-FLG", "Y");
            state.put("WS-MESSAGE", "Unable to lookup User...");
            state.put("FNAMEL", -1);
            perform(state, "SEND-USRDEL-SCREEN");
        }
    }

    void do_DELETE_USER_SEC_FILE(ProgramState state) {
        stubs.dummyExec(state, "CICS", "EXEC CICS DELETE DATASET   (WS-USRSEC-FILE) RESP      (WS-RESP-CD) RESP2     (WS-REAS-CD) END-EXEC");
        Object _evalSubject5 = state.get("WS-RESP-CD");
        if ((java.util.Objects.equals(_evalSubject5, 0))) {
            state.addBranch(22);
            perform(state, "INITIALIZE-ALL-FIELDS");
            state.put("WS-MESSAGE", " ");
            state.put("ERRMSGC", state.get("DFHGREEN"));
            state.put("WS-MESSAGE", "User " + String.valueOf(state.get("SEC-USR-ID")) + String.valueOf(state.get("DELIMITED")) + String.valueOf(state.get("BY")) + String.valueOf(state.get("SPACE")) + " has been deleted ...");
            perform(state, "SEND-USRDEL-SCREEN");
        }
        else if ((java.util.Objects.equals(_evalSubject5, 13))) {
            state.addBranch(23);
            state.put("WS-ERR-FLG", "Y");
            state.put("WS-MESSAGE", "User ID NOT found...");
            state.put("USRIDINL", -1);
            perform(state, "SEND-USRDEL-SCREEN");
        }
        else {
            state.addBranch(24);
            display(state, "RESP:", String.valueOf(state.get("WS-RESP-CD")), "REAS:", String.valueOf(state.get("WS-REAS-CD")));
            state.put("WS-ERR-FLG", "Y");
            state.put("WS-MESSAGE", "Unable to Update User...");
            state.put("FNAMEL", -1);
            perform(state, "SEND-USRDEL-SCREEN");
        }
    }

    void do_CLEAR_CURRENT_SCREEN(ProgramState state) {
        perform(state, "INITIALIZE-ALL-FIELDS");
        perform(state, "SEND-USRDEL-SCREEN");
    }

    void do_INITIALIZE_ALL_FIELDS(ProgramState state) {
        state.put("USRIDINL", -1);
        state.put("USRIDINI", " ");
        state.put("FNAMEI", " ");
        state.put("LNAMEI", " ");
        state.put("USRTYPEI", " ");
        state.put("WS-MESSAGE", " ");
    }

}
