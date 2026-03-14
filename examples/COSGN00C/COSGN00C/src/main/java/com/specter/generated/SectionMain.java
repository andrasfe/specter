package com.specter.generated;

/**
 * Generated section: SectionMain.
 */
public class SectionMain extends SectionBase {

    public SectionMain(ParagraphRegistry registry, StubExecutor stubs) {
        super(registry, stubs);
        paragraph("MAIN-PARA", this::do_MAIN_PARA);
        paragraph("PROCESS-ENTER-KEY", this::do_PROCESS_ENTER_KEY);
        paragraph("SEND-SIGNON-SCREEN", this::do_SEND_SIGNON_SCREEN);
        paragraph("SEND-PLAIN-TEXT", this::do_SEND_PLAIN_TEXT);
        paragraph("POPULATE-HEADER-INFO", this::do_POPULATE_HEADER_INFO);
        paragraph("READ-USER-SEC-FILE", this::do_READ_USER_SEC_FILE);
    }

    void do_MAIN_PARA(ProgramState state) {
        state.put("ERR-FLG-OFF", true);
        state.put("WS-MESSAGE", " ");
        if (java.util.Objects.equals(state.get("EIBCALEN"), 0)) {
            state.addBranch(1);
            state.put("COSGN0AO", "\u0000");
            state.put("USERIDL", -1);
            perform(state, "SEND-SIGNON-SCREEN");
        } else {
            state.addBranch(-1);
            Object _evalSubject1 = state.get("EIBAID");
            if (java.util.Objects.equals(_evalSubject1, "DFHENTER")) {
                state.addBranch(2);
                perform(state, "PROCESS-ENTER-KEY");
            }
            else if (java.util.Objects.equals(_evalSubject1, "DFHPF3")) {
                state.addBranch(3);
                state.put("WS-MESSAGE", state.get("CCDA-MSG-THANK-YOU"));
                perform(state, "SEND-PLAIN-TEXT");
            }
            else {
                state.addBranch(4);
                state.put("WS-ERR-FLG", "Y");
                state.put("WS-MESSAGE", state.get("CCDA-MSG-INVALID-KEY"));
                perform(state, "SEND-SIGNON-SCREEN");
            }
        }
        stubs.cicsReturn(state, true);
    }

    void do_PROCESS_ENTER_KEY(ProgramState state) {
        stubs.dummyExec(state, "CICS", "EXEC CICS RECEIVE MAP('COSGN0A') MAPSET('COSGN00') RESP(WS-RESP-CD) RESP2(WS-REAS-CD) END-EXEC.");
        if (java.util.List.of(" ", "\u0000").contains(state.get("USERIDI"))) {
            state.addBranch(5);
            state.put("WS-ERR-FLG", "Y");
            state.put("WS-MESSAGE", "Please enter User ID ...");
            state.put("USERIDL", -1);
            perform(state, "SEND-SIGNON-SCREEN");
        }
        else if (java.util.List.of(" ", "\u0000").contains(state.get("PASSWDI"))) {
            state.addBranch(6);
            state.put("WS-ERR-FLG", "Y");
            state.put("WS-MESSAGE", "Please enter Password ...");
            state.put("PASSWDL", -1);
            perform(state, "SEND-SIGNON-SCREEN");
        }
        else {
            state.addBranch(7);
            // CONTINUE
        }
        state.put("WS-USER-ID", String.valueOf(state.get("USERIDI")).toUpperCase());
        state.put("WS-USER-PWD", String.valueOf(state.get("PASSWDI")).toUpperCase());
        if (!(CobolRuntime.isTruthy(state.get("ERR-FLG-ON")))) {
            state.addBranch(8);
            perform(state, "READ-USER-SEC-FILE");
        } else {
            state.addBranch(-8);
        }
    }

    void do_SEND_SIGNON_SCREEN(ProgramState state) {
        perform(state, "POPULATE-HEADER-INFO");
        state.put("ERRMSGO", state.get("WS-MESSAGE"));
        stubs.dummyExec(state, "CICS", "EXEC CICS SEND MAP('COSGN0A') MAPSET('COSGN00') FROM(COSGN0AO) ERASE CURSOR END-EXEC.");
    }

    void do_SEND_PLAIN_TEXT(ProgramState state) {
        stubs.dummyExec(state, "CICS", "EXEC CICS SEND TEXT FROM(WS-MESSAGE) LENGTH(LENGTH OF WS-MESSAGE) ERASE FREEKB END-EXEC.");
        stubs.cicsReturn(state, false);
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
        stubs.dummyExec(state, "CICS", "EXEC CICS ASSIGN APPLID(APPLIDO OF COSGN0AO) END-EXEC");
        stubs.dummyExec(state, "CICS", "EXEC CICS ASSIGN SYSID(SYSIDO OF COSGN0AO) END-EXEC.");
    }

    void do_READ_USER_SEC_FILE(ProgramState state) {
        stubs.cicsRead(state, "WS-USRSEC-FILE", "WS-USER-ID", "SEC-USER-DATA", "WS-RESP-CD", "WS-REAS-CD");
        Object _evalSubject3 = state.get("WS-RESP-CD");
        _evalSubject3 = CobolRuntime.toNum(_evalSubject3);
        if (java.util.Objects.equals(_evalSubject3, CobolRuntime.toNum(0))) {
            state.addBranch(9);
            if (java.util.Objects.equals(state.get("SEC-USR-PWD"), state.get("WS-USER-PWD"))) {
                state.addBranch(10);
                state.put("CDEMO-FROM-TRANID", state.get("WS-TRANID"));
                state.put("CDEMO-FROM-PROGRAM", state.get("WS-PGMNAME"));
                state.put("CDEMO-USER-ID", state.get("WS-USER-ID"));
                state.put("CDEMO-USER-TYPE", state.get("SEC-USR-TYPE"));
                state.put("CDEMO-PGM-CONTEXT", 0);
                if (CobolRuntime.isTruthy(state.get("CDEMO-USRTYP-ADMIN"))) {
                    state.addBranch(11);
                    stubs.dummyExec(state, "CICS", "EXEC CICS XCTL PROGRAM ('COADM01C') COMMAREA(CARDDEMO-COMMAREA) END-EXEC");
                } else {
                    state.addBranch(-11);
                    stubs.dummyExec(state, "CICS", "EXEC CICS XCTL PROGRAM ('COMEN01C') COMMAREA(CARDDEMO-COMMAREA) END-EXEC");
                }
            } else {
                state.addBranch(-10);
                state.put("WS-MESSAGE", "Wrong Password. Try again ...");
                state.put("PASSWDL", -1);
                perform(state, "SEND-SIGNON-SCREEN");
            }
        }
        else if (java.util.Objects.equals(_evalSubject3, CobolRuntime.toNum(13))) {
            state.addBranch(12);
            state.put("WS-ERR-FLG", "Y");
            state.put("WS-MESSAGE", "User not found. Try again ...");
            state.put("USERIDL", -1);
            perform(state, "SEND-SIGNON-SCREEN");
        }
        else {
            state.addBranch(13);
            state.put("WS-ERR-FLG", "Y");
            state.put("VERIFY", state.get("UNABLE"));
            state.put("THE", state.get("UNABLE"));
            state.put("USER", state.get("UNABLE"));
            state.put("TO", state.get("UNABLE"));
            state.put("WS-MESSAGE", state.get("UNABLE"));
            state.put("USERIDL", -1);
            perform(state, "SEND-SIGNON-SCREEN");
        }
    }

}
