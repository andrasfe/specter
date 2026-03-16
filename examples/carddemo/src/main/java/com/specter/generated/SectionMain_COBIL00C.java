package com.specter.generated;

/**
 * Generated section: SectionMain.
 */
public class SectionMain_COBIL00C extends SectionBase {

    public SectionMain_COBIL00C(ParagraphRegistry registry, StubExecutor stubs) {
        super(registry, stubs);
        paragraph("MAIN-PARA", this::do_MAIN_PARA);
        paragraph("PROCESS-ENTER-KEY", this::do_PROCESS_ENTER_KEY);
        paragraph("GET-CURRENT-TIMESTAMP", this::do_GET_CURRENT_TIMESTAMP);
        paragraph("RETURN-TO-PREV-SCREEN", this::do_RETURN_TO_PREV_SCREEN);
        paragraph("SEND-BILLPAY-SCREEN", this::do_SEND_BILLPAY_SCREEN);
        paragraph("RECEIVE-BILLPAY-SCREEN", this::do_RECEIVE_BILLPAY_SCREEN);
        paragraph("POPULATE-HEADER-INFO", this::do_POPULATE_HEADER_INFO);
        paragraph("READ-ACCTDAT-FILE", this::do_READ_ACCTDAT_FILE);
        paragraph("UPDATE-ACCTDAT-FILE", this::do_UPDATE_ACCTDAT_FILE);
        paragraph("READ-CXACAIX-FILE", this::do_READ_CXACAIX_FILE);
        paragraph("STARTBR-TRANSACT-FILE", this::do_STARTBR_TRANSACT_FILE);
        paragraph("READPREV-TRANSACT-FILE", this::do_READPREV_TRANSACT_FILE);
        paragraph("ENDBR-TRANSACT-FILE", this::do_ENDBR_TRANSACT_FILE);
        paragraph("WRITE-TRANSACT-FILE", this::do_WRITE_TRANSACT_FILE);
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
                state.put("COBIL0AO", "\u0000");
                state.put("ACTIDINL", -1);
                if (!java.util.List.of(" ", "\u0000").contains(state.get("CDEMO-CB00-TRN-SELECTED"))) {
                    state.addBranch(3);
                    state.put("ACTIDINI", state.get("CDEMO-CB00-TRN-SELECTED"));
                    perform(state, "PROCESS-ENTER-KEY");
                } else {
                    state.addBranch(-3);
                }
                perform(state, "SEND-BILLPAY-SCREEN");
            } else {
                state.addBranch(-2);
                perform(state, "RECEIVE-BILLPAY-SCREEN");
                Object _evalSubject1 = state.get("EIBAID");
                if ((java.util.Objects.equals(_evalSubject1, "DFHENTER"))) {
                    state.addBranch(4);
                    perform(state, "PROCESS-ENTER-KEY");
                }
                else if ((java.util.Objects.equals(_evalSubject1, "DFHPF3"))) {
                    state.addBranch(5);
                    if (java.util.List.of(" ", "\u0000").contains(state.get("CDEMO-FROM-PROGRAM"))) {
                        state.addBranch(6);
                        state.put("CDEMO-TO-PROGRAM", "COMEN01C");
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
                else {
                    state.addBranch(8);
                    state.put("WS-ERR-FLG", "Y");
                    state.put("WS-MESSAGE", state.get("CCDA-MSG-INVALID-KEY"));
                    perform(state, "SEND-BILLPAY-SCREEN");
                }
            }
        }
        stubs.cicsReturn(state, true);
    }

    void do_PROCESS_ENTER_KEY(ProgramState state) {
        state.put("CONF-PAY-YES", false);
        state.put("CONF-PAY-NO", true);
        if ((java.util.List.of(" ", "\u0000").contains(state.get("ACTIDINI")))) {
            state.addBranch(9);
            state.put("WS-ERR-FLG", "Y");
            state.put("WS-MESSAGE", "Acct ID can NOT be empty...");
            state.put("ACTIDINL", -1);
            perform(state, "SEND-BILLPAY-SCREEN");
        }
        else {
            state.addBranch(10);
            // CONTINUE
        }
        if (!(CobolRuntime.isTruthy(state.get("ERR-FLG-ON")))) {
            state.addBranch(11);
            state.put("ACCT-ID", state.get("ACTIDINI"));
            state.put("XREF-ACCT-ID", state.get("ACTIDINI"));
            Object _evalSubject3 = state.get("CONFIRMI OF COBIL0AI");
            if ((java.util.Objects.equals(_evalSubject3, "Y"))) {
                state.addBranch(12);
                state.put("CONF-PAY-NO", false);
                state.put("CONF-PAY-YES", true);
                perform(state, "READ-ACCTDAT-FILE");
            }
            else if ((java.util.Objects.equals(_evalSubject3, "N"))) {
                state.addBranch(13);
                perform(state, "CLEAR-CURRENT-SCREEN");
                state.put("WS-ERR-FLG", "Y");
            }
            else if ((java.util.Objects.equals(_evalSubject3, " "))) {
                state.addBranch(14);
                perform(state, "READ-ACCTDAT-FILE");
            }
            else {
                state.addBranch(15);
                state.put("WS-ERR-FLG", "Y");
                state.put("WS-MESSAGE", "Invalid value. Valid values are (Y/N)...");
                state.put("CONFIRML", -1);
                perform(state, "SEND-BILLPAY-SCREEN");
            }
            state.put("WS-CURR-BAL", state.get("ACCT-CURR-BAL"));
            state.put("CURBALI", state.get("WS-CURR-BAL"));
        } else {
            state.addBranch(-11);
        }
        if (!(CobolRuntime.isTruthy(state.get("ERR-FLG-ON")))) {
            state.addBranch(16);
            if ((CobolRuntime.toNum(state.get("ACCT-CURR-BAL")) <= 0) && (!java.util.List.of(" ", "\u0000").contains(state.get("ACTIDINI")))) {
                state.addBranch(17);
                state.put("WS-ERR-FLG", "Y");
                state.put("WS-MESSAGE", "You have nothing to pay...");
                state.put("ACTIDINL", -1);
                perform(state, "SEND-BILLPAY-SCREEN");
            } else {
                state.addBranch(-17);
            }
        } else {
            state.addBranch(-16);
        }
        if (!(CobolRuntime.isTruthy(state.get("ERR-FLG-ON")))) {
            state.addBranch(18);
            if (CobolRuntime.isTruthy(state.get("CONF-PAY-YES"))) {
                state.addBranch(19);
                perform(state, "READ-CXACAIX-FILE");
                state.put("TRAN-ID", "\u00FF");
                perform(state, "STARTBR-TRANSACT-FILE");
                perform(state, "READPREV-TRANSACT-FILE");
                perform(state, "ENDBR-TRANSACT-FILE");
                state.put("WS-TRAN-ID-NUM", state.get("TRAN-ID"));
                state.put("WS-TRAN-ID-NUM", CobolRuntime.toNum(state.get("WS-TRAN-ID-NUM")) + 1);
                state.put("TRAN-RECORD", state.get("TRAN-RECORD") instanceof Number ? 0 : "");
                state.put("TRAN-ID", state.get("WS-TRAN-ID-NUM"));
                state.put("TRAN-TYPE-CD", "02");
                state.put("TRAN-CAT-CD", 2);
                state.put("TRAN-SOURCE", "POS TERM");
                state.put("TRAN-DESC", "BILL PAYMENT - ONLINE");
                state.put("TRAN-AMT", state.get("ACCT-CURR-BAL"));
                state.put("TRAN-CARD-NUM", state.get("XREF-CARD-NUM"));
                state.put("TRAN-MERCHANT-ID", 999999999);
                state.put("TRAN-MERCHANT-NAME", "BILL PAYMENT");
                state.put("TRAN-MERCHANT-CITY", "N/A");
                state.put("TRAN-MERCHANT-ZIP", "N/A");
                perform(state, "GET-CURRENT-TIMESTAMP");
                state.put("TRAN-ORIG-TS", state.get("WS-TIMESTAMP"));
                state.put("TRAN-PROC-TS", state.get("WS-TIMESTAMP"));
                perform(state, "WRITE-TRANSACT-FILE");
                state.put("ACCT-CURR-BAL", CobolRuntime.toNum(state.get("ACCT-CURR-BAL")) - CobolRuntime.toNum(state.get("TRAN-AMT")));
                perform(state, "UPDATE-ACCTDAT-FILE");
            } else {
                state.addBranch(-19);
                state.put("WS-MESSAGE", "Confirm to make a bill payment...");
                state.put("CONFIRML", -1);
            }
            perform(state, "SEND-BILLPAY-SCREEN");
        } else {
            state.addBranch(-18);
        }
    }

    void do_GET_CURRENT_TIMESTAMP(ProgramState state) {
        stubs.cicsAsktime(state, "WS-ABS-TIME");
        state.put("WS-TIMESTAMP", state.get("WS-TIMESTAMP") instanceof Number ? 0 : "");
        state.put("WS-TIMESTAMP", state.get("WS-CUR-DATE-X10"));
        state.put("WS-TIMESTAMP", state.get("WS-CUR-TIME-X08"));
        state.put("WS-TIMESTAMP-TM-MS6", 0);
    }

    void do_RETURN_TO_PREV_SCREEN(ProgramState state) {
        if (java.util.List.of("\u0000", " ").contains(state.get("CDEMO-TO-PROGRAM"))) {
            state.addBranch(20);
            state.put("CDEMO-TO-PROGRAM", "COSGN00C");
        } else {
            state.addBranch(-20);
        }
        state.put("CDEMO-FROM-TRANID", state.get("WS-TRANID"));
        state.put("CDEMO-FROM-PROGRAM", state.get("WS-PGMNAME"));
        state.put("CDEMO-PGM-CONTEXT", 0);
        stubs.dummyExec(state, "CICS", "EXEC CICS XCTL PROGRAM(CDEMO-TO-PROGRAM) COMMAREA(CARDDEMO-COMMAREA) END-EXEC");
    }

    void do_SEND_BILLPAY_SCREEN(ProgramState state) {
        perform(state, "POPULATE-HEADER-INFO");
        state.put("ERRMSGO", state.get("WS-MESSAGE"));
        stubs.dummyExec(state, "CICS", "EXEC CICS SEND MAP('COBIL0A') MAPSET('COBIL00') FROM(COBIL0AO) ERASE CURSOR END-EXEC");
    }

    void do_RECEIVE_BILLPAY_SCREEN(ProgramState state) {
        stubs.dummyExec(state, "CICS", "EXEC CICS RECEIVE MAP('COBIL0A') MAPSET('COBIL00') INTO(COBIL0AI) RESP(WS-RESP-CD) RESP2(WS-REAS-CD) END-EXEC");
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

    void do_READ_ACCTDAT_FILE(ProgramState state) {
        stubs.cicsRead(state, "WS-ACCTDAT-FILE", "ACCT-ID", "ACCOUNT-RECORD", "WS-RESP-CD", "WS-REAS-CD");
        Object _evalSubject4 = state.get("WS-RESP-CD");
        if ((java.util.Objects.equals(_evalSubject4, 0))) {
            state.addBranch(21);
            // CONTINUE
        }
        else if ((java.util.Objects.equals(_evalSubject4, 13))) {
            state.addBranch(22);
            state.put("WS-ERR-FLG", "Y");
            state.put("WS-MESSAGE", "Account ID NOT found...");
            state.put("ACTIDINL", -1);
            perform(state, "SEND-BILLPAY-SCREEN");
        }
        else {
            state.addBranch(23);
            display(state, "RESP:", String.valueOf(state.get("WS-RESP-CD")), "REAS:", String.valueOf(state.get("WS-REAS-CD")));
            state.put("WS-ERR-FLG", "Y");
            state.put("WS-MESSAGE", "Unable to lookup Account...");
            state.put("ACTIDINL", -1);
            perform(state, "SEND-BILLPAY-SCREEN");
        }
    }

    void do_UPDATE_ACCTDAT_FILE(ProgramState state) {
        stubs.dummyExec(state, "CICS", "EXEC CICS REWRITE DATASET   (WS-ACCTDAT-FILE) FROM      (ACCOUNT-RECORD) LENGTH    (LENGTH OF ACCOUNT-RECORD) RESP      (WS-RESP-CD) RESP2     (WS-REAS-CD) END-EXEC");
        Object _evalSubject5 = state.get("WS-RESP-CD");
        if ((java.util.Objects.equals(_evalSubject5, 0))) {
            state.addBranch(24);
            // CONTINUE
        }
        else if ((java.util.Objects.equals(_evalSubject5, 13))) {
            state.addBranch(25);
            state.put("WS-ERR-FLG", "Y");
            state.put("WS-MESSAGE", "Account ID NOT found...");
            state.put("ACTIDINL", -1);
            perform(state, "SEND-BILLPAY-SCREEN");
        }
        else {
            state.addBranch(26);
            display(state, "RESP:", String.valueOf(state.get("WS-RESP-CD")), "REAS:", String.valueOf(state.get("WS-REAS-CD")));
            state.put("WS-ERR-FLG", "Y");
            state.put("WS-MESSAGE", "Unable to Update Account...");
            state.put("ACTIDINL", -1);
            perform(state, "SEND-BILLPAY-SCREEN");
        }
    }

    void do_READ_CXACAIX_FILE(ProgramState state) {
        stubs.cicsRead(state, "WS-CXACAIX-FILE", "XREF-ACCT-ID", "CARD-XREF-RECORD", "WS-RESP-CD", "WS-REAS-CD");
        Object _evalSubject6 = state.get("WS-RESP-CD");
        if ((java.util.Objects.equals(_evalSubject6, 0))) {
            state.addBranch(27);
            // CONTINUE
        }
        else if ((java.util.Objects.equals(_evalSubject6, 13))) {
            state.addBranch(28);
            state.put("WS-ERR-FLG", "Y");
            state.put("WS-MESSAGE", "Account ID NOT found...");
            state.put("ACTIDINL", -1);
            perform(state, "SEND-BILLPAY-SCREEN");
        }
        else {
            state.addBranch(29);
            display(state, "RESP:", String.valueOf(state.get("WS-RESP-CD")), "REAS:", String.valueOf(state.get("WS-REAS-CD")));
            state.put("WS-ERR-FLG", "Y");
            state.put("WS-MESSAGE", "Unable to lookup XREF AIX file...");
            state.put("ACTIDINL", -1);
            perform(state, "SEND-BILLPAY-SCREEN");
        }
    }

    void do_STARTBR_TRANSACT_FILE(ProgramState state) {
        stubs.dummyExec(state, "CICS", "EXEC CICS STARTBR DATASET   (WS-TRANSACT-FILE) RIDFLD    (TRAN-ID) KEYLENGTH (LENGTH OF TRAN-ID) RESP      (WS-RESP-CD) RESP2     (WS-REAS-CD) END-EXEC");
        Object _evalSubject7 = state.get("WS-RESP-CD");
        if ((java.util.Objects.equals(_evalSubject7, 0))) {
            state.addBranch(30);
            // CONTINUE
        }
        else if ((java.util.Objects.equals(_evalSubject7, 13))) {
            state.addBranch(31);
            state.put("WS-ERR-FLG", "Y");
            state.put("WS-MESSAGE", "Transaction ID NOT found...");
            state.put("ACTIDINL", -1);
            perform(state, "SEND-BILLPAY-SCREEN");
        }
        else {
            state.addBranch(32);
            display(state, "RESP:", String.valueOf(state.get("WS-RESP-CD")), "REAS:", String.valueOf(state.get("WS-REAS-CD")));
            state.put("WS-ERR-FLG", "Y");
            state.put("WS-MESSAGE", "Unable to lookup Transaction...");
            state.put("ACTIDINL", -1);
            perform(state, "SEND-BILLPAY-SCREEN");
        }
    }

    void do_READPREV_TRANSACT_FILE(ProgramState state) {
        stubs.cicsRead(state, "WS-TRANSACT-FILE", "TRAN-ID", "TRAN-RECORD", "WS-RESP-CD", "WS-REAS-CD");
        Object _evalSubject8 = state.get("WS-RESP-CD");
        if ((java.util.Objects.equals(_evalSubject8, 0))) {
            state.addBranch(33);
            // CONTINUE
        }
        else if ((java.util.Objects.equals(_evalSubject8, 20))) {
            state.addBranch(34);
            state.put("TRAN-ID", 0);
        }
        else {
            state.addBranch(35);
            display(state, "RESP:", String.valueOf(state.get("WS-RESP-CD")), "REAS:", String.valueOf(state.get("WS-REAS-CD")));
            state.put("WS-ERR-FLG", "Y");
            state.put("WS-MESSAGE", "Unable to lookup Transaction...");
            state.put("ACTIDINL", -1);
            perform(state, "SEND-BILLPAY-SCREEN");
        }
    }

    void do_ENDBR_TRANSACT_FILE(ProgramState state) {
        stubs.dummyExec(state, "CICS", "EXEC CICS ENDBR DATASET   (WS-TRANSACT-FILE) END-EXEC");
    }

    void do_WRITE_TRANSACT_FILE(ProgramState state) {
        stubs.dummyExec(state, "CICS", "EXEC CICS WRITE DATASET   (WS-TRANSACT-FILE) FROM      (TRAN-RECORD) LENGTH    (LENGTH OF TRAN-RECORD) RIDFLD    (TRAN-ID) KEYLENGTH (LENGTH OF TRAN-ID) RESP      (WS-RESP-CD) RESP2     (WS-REAS-CD) E...");
        Object _evalSubject9 = state.get("WS-RESP-CD");
        if ((java.util.Objects.equals(_evalSubject9, 0))) {
            state.addBranch(36);
            perform(state, "INITIALIZE-ALL-FIELDS");
            state.put("WS-MESSAGE", " ");
            state.put("ERRMSGC", state.get("DFHGREEN"));
            state.put("WS-MESSAGE", "Payment successful. " + " Your Transaction ID is " + String.valueOf(state.get("TRAN-ID")) + String.valueOf(state.get("DELIMITED")) + String.valueOf(state.get("BY")) + String.valueOf(state.get("SPACE")) + ".");
            perform(state, "SEND-BILLPAY-SCREEN");
        }
        else if ((java.util.Objects.equals(_evalSubject9, 15))) {
            state.addBranch(37);
            state.put("WS-ERR-FLG", "Y");
            state.put("WS-MESSAGE", "Tran ID already exist...");
            state.put("ACTIDINL", -1);
            perform(state, "SEND-BILLPAY-SCREEN");
        }
        else {
            state.addBranch(38);
            display(state, "RESP:", String.valueOf(state.get("WS-RESP-CD")), "REAS:", String.valueOf(state.get("WS-REAS-CD")));
            state.put("WS-ERR-FLG", "Y");
            state.put("WS-MESSAGE", "Unable to Add Bill pay Transaction...");
            state.put("ACTIDINL", -1);
            perform(state, "SEND-BILLPAY-SCREEN");
        }
    }

    void do_CLEAR_CURRENT_SCREEN(ProgramState state) {
        perform(state, "INITIALIZE-ALL-FIELDS");
        perform(state, "SEND-BILLPAY-SCREEN");
    }

    void do_INITIALIZE_ALL_FIELDS(ProgramState state) {
        state.put("ACTIDINL", -1);
        state.put("ACTIDINI", " ");
        state.put("CURBALI", " ");
        state.put("CONFIRMI", " ");
        state.put("WS-MESSAGE", " ");
    }

}
