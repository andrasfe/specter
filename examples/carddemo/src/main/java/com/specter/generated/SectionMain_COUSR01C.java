package com.specter.generated;

/**
 * Generated section: SectionMain.
 */
public class SectionMain_COUSR01C extends SectionBase {

    public SectionMain_COUSR01C(ParagraphRegistry registry, StubExecutor stubs) {
        super(registry, stubs);
        paragraph("MAIN-PARA", this::do_MAIN_PARA);
        paragraph("PROCESS-ENTER-KEY", this::do_PROCESS_ENTER_KEY);
        paragraph("RETURN-TO-PREV-SCREEN", this::do_RETURN_TO_PREV_SCREEN);
        paragraph("SEND-USRADD-SCREEN", this::do_SEND_USRADD_SCREEN);
        paragraph("RECEIVE-USRADD-SCREEN", this::do_RECEIVE_USRADD_SCREEN);
        paragraph("POPULATE-HEADER-INFO", this::do_POPULATE_HEADER_INFO);
        paragraph("WRITE-USER-SEC-FILE", this::do_WRITE_USER_SEC_FILE);
        paragraph("CLEAR-CURRENT-SCREEN", this::do_CLEAR_CURRENT_SCREEN);
        paragraph("INITIALIZE-ALL-FIELDS", this::do_INITIALIZE_ALL_FIELDS);
    }

    void do_MAIN_PARA(ProgramState state) {
        state.put("ERR-FLG-OFF", true);
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
                state.put("COUSR1AO", "\u0000");
                state.put("FNAMEL", -1);
                perform(state, "SEND-USRADD-SCREEN");
            } else {
                state.addBranch(-2);
                perform(state, "RECEIVE-USRADD-SCREEN");
                Object _evalSubject1 = state.get("EIBAID");
                if ((java.util.Objects.equals(_evalSubject1, "DFHENTER"))) {
                    state.addBranch(3);
                    perform(state, "PROCESS-ENTER-KEY");
                }
                else if ((java.util.Objects.equals(_evalSubject1, "DFHPF3"))) {
                    state.addBranch(4);
                    state.put("CDEMO-TO-PROGRAM", "COADM01C");
                    perform(state, "RETURN-TO-PREV-SCREEN");
                }
                else if ((java.util.Objects.equals(_evalSubject1, "DFHPF4"))) {
                    state.addBranch(5);
                    perform(state, "CLEAR-CURRENT-SCREEN");
                }
                else {
                    state.addBranch(6);
                    state.put("WS-ERR-FLG", "Y");
                    state.put("FNAMEL", -1);
                    state.put("WS-MESSAGE", state.get("CCDA-MSG-INVALID-KEY"));
                    perform(state, "SEND-USRADD-SCREEN");
                }
            }
        }
        stubs.cicsReturn(state, true);
    }

    void do_PROCESS_ENTER_KEY(ProgramState state) {
        if ((java.util.List.of(" ", "\u0000").contains(state.get("FNAMEI")))) {
            state.addBranch(7);
            state.put("WS-ERR-FLG", "Y");
            state.put("WS-MESSAGE", "First Name can NOT be empty...");
            state.put("FNAMEL", -1);
            perform(state, "SEND-USRADD-SCREEN");
        }
        else if ((java.util.List.of(" ", "\u0000").contains(state.get("LNAMEI")))) {
            state.addBranch(8);
            state.put("WS-ERR-FLG", "Y");
            state.put("WS-MESSAGE", "Last Name can NOT be empty...");
            state.put("LNAMEL", -1);
            perform(state, "SEND-USRADD-SCREEN");
        }
        else if ((java.util.List.of(" ", "\u0000").contains(state.get("USERIDI")))) {
            state.addBranch(9);
            state.put("WS-ERR-FLG", "Y");
            state.put("WS-MESSAGE", "User ID can NOT be empty...");
            state.put("USERIDL", -1);
            perform(state, "SEND-USRADD-SCREEN");
        }
        else if ((java.util.List.of(" ", "\u0000").contains(state.get("PASSWDI")))) {
            state.addBranch(10);
            state.put("WS-ERR-FLG", "Y");
            state.put("WS-MESSAGE", "Password can NOT be empty...");
            state.put("PASSWDL", -1);
            perform(state, "SEND-USRADD-SCREEN");
        }
        else if ((java.util.List.of(" ", "\u0000").contains(state.get("USRTYPEI")))) {
            state.addBranch(11);
            state.put("WS-ERR-FLG", "Y");
            state.put("WS-MESSAGE", "User Type can NOT be empty...");
            state.put("USRTYPEL", -1);
            perform(state, "SEND-USRADD-SCREEN");
        }
        else {
            state.addBranch(12);
            state.put("FNAMEL", -1);
            // CONTINUE
        }
        if (!(CobolRuntime.isTruthy(state.get("ERR-FLG-ON")))) {
            state.addBranch(13);
            state.put("SEC-USR-ID", state.get("USERIDI"));
            state.put("SEC-USR-FNAME", state.get("FNAMEI"));
            state.put("SEC-USR-LNAME", state.get("LNAMEI"));
            state.put("SEC-USR-PWD", state.get("PASSWDI"));
            state.put("SEC-USR-TYPE", state.get("USRTYPEI"));
            perform(state, "WRITE-USER-SEC-FILE");
        } else {
            state.addBranch(-13);
        }
    }

    void do_RETURN_TO_PREV_SCREEN(ProgramState state) {
        if (java.util.List.of("\u0000", " ").contains(state.get("CDEMO-TO-PROGRAM"))) {
            state.addBranch(14);
            state.put("CDEMO-TO-PROGRAM", "COSGN00C");
        } else {
            state.addBranch(-14);
        }
        state.put("CDEMO-FROM-TRANID", state.get("WS-TRANID"));
        state.put("CDEMO-FROM-PROGRAM", state.get("WS-PGMNAME"));
        state.put("CDEMO-PGM-CONTEXT", 0);
        stubs.dummyExec(state, "CICS", "EXEC CICS XCTL PROGRAM(CDEMO-TO-PROGRAM) COMMAREA(CARDDEMO-COMMAREA) END-EXEC");
    }

    void do_SEND_USRADD_SCREEN(ProgramState state) {
        perform(state, "POPULATE-HEADER-INFO");
        state.put("ERRMSGO", state.get("WS-MESSAGE"));
        stubs.dummyExec(state, "CICS", "EXEC CICS SEND MAP('COUSR1A') MAPSET('COUSR01') FROM(COUSR1AO) ERASE CURSOR END-EXEC");
    }

    void do_RECEIVE_USRADD_SCREEN(ProgramState state) {
        stubs.dummyExec(state, "CICS", "EXEC CICS RECEIVE MAP('COUSR1A') MAPSET('COUSR01') INTO(COUSR1AI) RESP(WS-RESP-CD) RESP2(WS-REAS-CD) END-EXEC");
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

    void do_WRITE_USER_SEC_FILE(ProgramState state) {
        stubs.dummyExec(state, "CICS", "EXEC CICS WRITE DATASET   (WS-USRSEC-FILE) FROM      (SEC-USER-DATA) LENGTH    (LENGTH OF SEC-USER-DATA) RIDFLD    (SEC-USR-ID) KEYLENGTH (LENGTH OF SEC-USR-ID) RESP      (WS-RESP-CD) RESP2     (WS-RE...");
        Object _evalSubject3 = state.get("WS-RESP-CD");
        if ((java.util.Objects.equals(_evalSubject3, 0))) {
            state.addBranch(15);
            perform(state, "INITIALIZE-ALL-FIELDS");
            state.put("WS-MESSAGE", " ");
            state.put("ERRMSGC", state.get("DFHGREEN"));
            state.put("WS-MESSAGE", "User " + String.valueOf(state.get("SEC-USR-ID")) + String.valueOf(state.get("DELIMITED")) + String.valueOf(state.get("BY")) + String.valueOf(state.get("SPACE")) + " has been added ...");
            perform(state, "SEND-USRADD-SCREEN");
        }
        else if ((java.util.Objects.equals(_evalSubject3, 15))) {
            state.addBranch(16);
            state.put("WS-ERR-FLG", "Y");
            state.put("WS-MESSAGE", "User ID already exist...");
            state.put("USERIDL", -1);
            perform(state, "SEND-USRADD-SCREEN");
        }
        else {
            state.addBranch(17);
            state.put("WS-ERR-FLG", "Y");
            state.put("WS-MESSAGE", "Unable to Add User...");
            state.put("FNAMEL", -1);
            perform(state, "SEND-USRADD-SCREEN");
        }
    }

    void do_CLEAR_CURRENT_SCREEN(ProgramState state) {
        perform(state, "INITIALIZE-ALL-FIELDS");
        perform(state, "SEND-USRADD-SCREEN");
    }

    void do_INITIALIZE_ALL_FIELDS(ProgramState state) {
        state.put("FNAMEL", -1);
        state.put("USERIDI", " ");
        state.put("FNAMEI", " ");
        state.put("LNAMEI", " ");
        state.put("PASSWDI", " ");
        state.put("USRTYPEI", " ");
        state.put("WS-MESSAGE", " ");
    }

}
