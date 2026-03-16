package com.specter.generated;

/**
 * Generated section: SectionMain.
 */
public class SectionMain_COTRN02C extends SectionBase {

    public SectionMain_COTRN02C(ParagraphRegistry registry, StubExecutor stubs) {
        super(registry, stubs);
        paragraph("MAIN-PARA", this::do_MAIN_PARA);
        paragraph("PROCESS-ENTER-KEY", this::do_PROCESS_ENTER_KEY);
        paragraph("VALIDATE-INPUT-KEY-FIELDS", this::do_VALIDATE_INPUT_KEY_FIELDS);
        paragraph("VALIDATE-INPUT-DATA-FIELDS", this::do_VALIDATE_INPUT_DATA_FIELDS);
        paragraph("ADD-TRANSACTION", this::do_ADD_TRANSACTION);
        paragraph("COPY-LAST-TRAN-DATA", this::do_COPY_LAST_TRAN_DATA);
        paragraph("RETURN-TO-PREV-SCREEN", this::do_RETURN_TO_PREV_SCREEN);
        paragraph("SEND-TRNADD-SCREEN", this::do_SEND_TRNADD_SCREEN);
        paragraph("RECEIVE-TRNADD-SCREEN", this::do_RECEIVE_TRNADD_SCREEN);
        paragraph("POPULATE-HEADER-INFO", this::do_POPULATE_HEADER_INFO);
        paragraph("READ-CXACAIX-FILE", this::do_READ_CXACAIX_FILE);
        paragraph("READ-CCXREF-FILE", this::do_READ_CCXREF_FILE);
        paragraph("STARTBR-TRANSACT-FILE", this::do_STARTBR_TRANSACT_FILE);
        paragraph("READPREV-TRANSACT-FILE", this::do_READPREV_TRANSACT_FILE);
        paragraph("ENDBR-TRANSACT-FILE", this::do_ENDBR_TRANSACT_FILE);
        paragraph("WRITE-TRANSACT-FILE", this::do_WRITE_TRANSACT_FILE);
        paragraph("CLEAR-CURRENT-SCREEN", this::do_CLEAR_CURRENT_SCREEN);
        paragraph("INITIALIZE-ALL-FIELDS", this::do_INITIALIZE_ALL_FIELDS);
        paragraph("CSUTLDTC", this::do_CSUTLDTC);
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
                state.put("COTRN2AO", "\u0000");
                state.put("ACTIDINL", -1);
                if (!java.util.List.of(" ", "\u0000").contains(state.get("CDEMO-CT02-TRN-SELECTED"))) {
                    state.addBranch(3);
                    state.put("CARDNINI", state.get("CDEMO-CT02-TRN-SELECTED"));
                    perform(state, "PROCESS-ENTER-KEY");
                } else {
                    state.addBranch(-3);
                }
                perform(state, "SEND-TRNADD-SCREEN");
            } else {
                state.addBranch(-2);
                perform(state, "RECEIVE-TRNADD-SCREEN");
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
                else if ((java.util.Objects.equals(_evalSubject1, "DFHPF5"))) {
                    state.addBranch(8);
                    perform(state, "COPY-LAST-TRAN-DATA");
                }
                else {
                    state.addBranch(9);
                    state.put("WS-ERR-FLG", "Y");
                    state.put("WS-MESSAGE", state.get("CCDA-MSG-INVALID-KEY"));
                    perform(state, "SEND-TRNADD-SCREEN");
                }
            }
        }
        stubs.cicsReturn(state, true);
    }

    void do_PROCESS_ENTER_KEY(ProgramState state) {
        perform(state, "VALIDATE-INPUT-KEY-FIELDS");
        perform(state, "VALIDATE-INPUT-DATA-FIELDS");
        Object _evalSubject2 = state.get("CONFIRMI OF COTRN2AI");
        if ((java.util.Objects.equals(_evalSubject2, "Y"))) {
            state.addBranch(10);
            perform(state, "ADD-TRANSACTION");
        }
        else if ((java.util.Objects.equals(_evalSubject2, "N"))) {
            state.addBranch(11);
            state.put("WS-ERR-FLG", "Y");
            state.put("WS-MESSAGE", "Confirm to add this transaction...");
            state.put("CONFIRML", -1);
            perform(state, "SEND-TRNADD-SCREEN");
        }
        else {
            state.addBranch(12);
            state.put("WS-ERR-FLG", "Y");
            state.put("WS-MESSAGE", "Invalid value. Valid values are (Y/N)...");
            state.put("CONFIRML", -1);
            perform(state, "SEND-TRNADD-SCREEN");
        }
    }

    void do_VALIDATE_INPUT_KEY_FIELDS(ProgramState state) {
        if ((!java.util.List.of(" ", "\u0000").contains(state.get("ACTIDINI")))) {
            state.addBranch(13);
            if (!CobolRuntime.isNumeric(state.get("ACTIDINI"))) {
                state.addBranch(14);
                state.put("WS-ERR-FLG", "Y");
                state.put("WS-MESSAGE", "Account ID must be Numeric...");
                state.put("ACTIDINL", -1);
                perform(state, "SEND-TRNADD-SCREEN");
            } else {
                state.addBranch(-14);
            }
            state.put("WS-ACCT-ID-N", CobolRuntime.toNum(state.get("ACTIDINI")));
            state.put("XREF-ACCT-ID", state.get("WS-ACCT-ID-N"));
            state.put("ACTIDINI", state.get("WS-ACCT-ID-N"));
            perform(state, "READ-CXACAIX-FILE");
            state.put("CARDNINI", state.get("XREF-CARD-NUM"));
        }
        else if ((!java.util.List.of(" ", "\u0000").contains(state.get("CARDNINI")))) {
            state.addBranch(15);
            if (!CobolRuntime.isNumeric(state.get("CARDNINI"))) {
                state.addBranch(16);
                state.put("WS-ERR-FLG", "Y");
                state.put("WS-MESSAGE", "Card Number must be Numeric...");
                state.put("CARDNINL", -1);
                perform(state, "SEND-TRNADD-SCREEN");
            } else {
                state.addBranch(-16);
            }
            state.put("WS-CARD-NUM-N", CobolRuntime.toNum(state.get("CARDNINI")));
            state.put("XREF-CARD-NUM", state.get("WS-CARD-NUM-N"));
            state.put("CARDNINI", state.get("WS-CARD-NUM-N"));
            perform(state, "READ-CCXREF-FILE");
            state.put("ACTIDINI", state.get("XREF-ACCT-ID"));
        }
        else {
            state.addBranch(17);
            state.put("WS-ERR-FLG", "Y");
            state.put("WS-MESSAGE", "Account or Card Number must be entered...");
            state.put("ACTIDINL", -1);
            perform(state, "SEND-TRNADD-SCREEN");
        }
    }

    void do_VALIDATE_INPUT_DATA_FIELDS(ProgramState state) {
        if (CobolRuntime.isTruthy(state.get("ERR-FLG-ON"))) {
            state.addBranch(18);
            state.put("TTYPCDI", " ");
            state.put("TCATCDI", " ");
            state.put("TRNSRCI", " ");
            state.put("TRNAMTI", " ");
            state.put("TDESCI", " ");
            state.put("TORIGDTI", " ");
            state.put("TPROCDTI", " ");
            state.put("MIDI", " ");
            state.put("MNAMEI", " ");
            state.put("MCITYI", " ");
            state.put("MZIPI", " ");
        } else {
            state.addBranch(-18);
        }
        if ((java.util.List.of(" ", "\u0000").contains(state.get("TTYPCDI")))) {
            state.addBranch(19);
            state.put("WS-ERR-FLG", "Y");
            state.put("WS-MESSAGE", "Type CD can NOT be empty...");
            state.put("TTYPCDL", -1);
            perform(state, "SEND-TRNADD-SCREEN");
        }
        else if ((java.util.List.of(" ", "\u0000").contains(state.get("TCATCDI")))) {
            state.addBranch(20);
            state.put("WS-ERR-FLG", "Y");
            state.put("WS-MESSAGE", "Category CD can NOT be empty...");
            state.put("TCATCDL", -1);
            perform(state, "SEND-TRNADD-SCREEN");
        }
        else if ((java.util.List.of(" ", "\u0000").contains(state.get("TRNSRCI")))) {
            state.addBranch(21);
            state.put("WS-ERR-FLG", "Y");
            state.put("WS-MESSAGE", "Source can NOT be empty...");
            state.put("TRNSRCL", -1);
            perform(state, "SEND-TRNADD-SCREEN");
        }
        else if ((java.util.List.of(" ", "\u0000").contains(state.get("TDESCI")))) {
            state.addBranch(22);
            state.put("WS-ERR-FLG", "Y");
            state.put("WS-MESSAGE", "Description can NOT be empty...");
            state.put("TDESCL", -1);
            perform(state, "SEND-TRNADD-SCREEN");
        }
        else if ((java.util.List.of(" ", "\u0000").contains(state.get("TRNAMTI")))) {
            state.addBranch(23);
            state.put("WS-ERR-FLG", "Y");
            state.put("WS-MESSAGE", "Amount can NOT be empty...");
            state.put("TRNAMTL", -1);
            perform(state, "SEND-TRNADD-SCREEN");
        }
        else if ((java.util.List.of(" ", "\u0000").contains(state.get("TORIGDTI")))) {
            state.addBranch(24);
            state.put("WS-ERR-FLG", "Y");
            state.put("WS-MESSAGE", "Orig Date can NOT be empty...");
            state.put("TORIGDTL", -1);
            perform(state, "SEND-TRNADD-SCREEN");
        }
        else if ((java.util.List.of(" ", "\u0000").contains(state.get("TPROCDTI")))) {
            state.addBranch(25);
            state.put("WS-ERR-FLG", "Y");
            state.put("WS-MESSAGE", "Proc Date can NOT be empty...");
            state.put("TPROCDTL", -1);
            perform(state, "SEND-TRNADD-SCREEN");
        }
        else if ((java.util.List.of(" ", "\u0000").contains(state.get("MIDI")))) {
            state.addBranch(26);
            state.put("WS-ERR-FLG", "Y");
            state.put("WS-MESSAGE", "Merchant ID can NOT be empty...");
            state.put("MIDL", -1);
            perform(state, "SEND-TRNADD-SCREEN");
        }
        else if ((java.util.List.of(" ", "\u0000").contains(state.get("MNAMEI")))) {
            state.addBranch(27);
            state.put("WS-ERR-FLG", "Y");
            state.put("WS-MESSAGE", "Merchant Name can NOT be empty...");
            state.put("MNAMEL", -1);
            perform(state, "SEND-TRNADD-SCREEN");
        }
        else if ((java.util.List.of(" ", "\u0000").contains(state.get("MCITYI")))) {
            state.addBranch(28);
            state.put("WS-ERR-FLG", "Y");
            state.put("WS-MESSAGE", "Merchant City can NOT be empty...");
            state.put("MCITYL", -1);
            perform(state, "SEND-TRNADD-SCREEN");
        }
        else if ((java.util.List.of(" ", "\u0000").contains(state.get("MZIPI")))) {
            state.addBranch(29);
            state.put("WS-ERR-FLG", "Y");
            state.put("WS-MESSAGE", "Merchant Zip can NOT be empty...");
            state.put("MZIPL", -1);
            perform(state, "SEND-TRNADD-SCREEN");
        }
        else {
            state.addBranch(30);
            // CONTINUE
        }
        if ((!CobolRuntime.isTruthy(state.get("TTYPCDI")))) {
            state.addBranch(31);
            state.put("WS-ERR-FLG", "Y");
            state.put("WS-MESSAGE", "Type CD must be Numeric...");
            state.put("TTYPCDL", -1);
            perform(state, "SEND-TRNADD-SCREEN");
        }
        else if ((!CobolRuntime.isTruthy(state.get("TCATCDI")))) {
            state.addBranch(32);
            state.put("WS-ERR-FLG", "Y");
            state.put("WS-MESSAGE", "Category CD must be Numeric...");
            state.put("TCATCDL", -1);
            perform(state, "SEND-TRNADD-SCREEN");
        }
        else {
            state.addBranch(33);
            // CONTINUE
        }
        if ((!java.util.List.of("-", "+").contains(state.get("TRNAMTI(1:1)")))) {
            state.addBranch(34);
            state.put("WS-ERR-FLG", "Y");
            state.put("WS-MESSAGE", "Amount should be in format -99999999.99");
            state.put("TRNAMTL", -1);
            perform(state, "SEND-TRNADD-SCREEN");
        }
        else {
            state.addBranch(35);
            // CONTINUE
        }
        if ((!CobolRuntime.isNumeric(state.get("TORIGDTI(1:4)")))) {
            state.addBranch(36);
            state.put("WS-ERR-FLG", "Y");
            state.put("WS-MESSAGE", "Orig Date should be in format YYYY-MM-DD");
            state.put("TORIGDTL", -1);
            perform(state, "SEND-TRNADD-SCREEN");
        }
        else {
            state.addBranch(37);
            // CONTINUE
        }
        if ((!CobolRuntime.isNumeric(state.get("TPROCDTI(1:4)")))) {
            state.addBranch(38);
            state.put("WS-ERR-FLG", "Y");
            state.put("WS-MESSAGE", "Proc Date should be in format YYYY-MM-DD");
            state.put("TPROCDTL", -1);
            perform(state, "SEND-TRNADD-SCREEN");
        }
        else {
            state.addBranch(39);
            // CONTINUE
        }
        state.put("WS-TRAN-AMT-N", CobolRuntime.toNum(state.get("TRNAMTI")));
        state.put("WS-TRAN-AMT-E", state.get("WS-TRAN-AMT-N"));
        state.put("TRNAMTI", state.get("WS-TRAN-AMT-E"));
        state.put("CSUTLDTC-DATE", state.get("TORIGDTI"));
        state.put("CSUTLDTC-DATE-FORMAT", state.get("WS-DATE-FORMAT"));
        state.put("CSUTLDTC-RESULT", " ");
        stubs.dummyCall(state, "CSUTLDTC");
        if (java.util.Objects.equals(state.get("CSUTLDTC-RESULT-SEV-CD"), "0000")) {
            state.addBranch(40);
            // CONTINUE
        } else {
            state.addBranch(-40);
            if (!java.util.Objects.equals(state.get("CSUTLDTC-RESULT-MSG-NUM"), "2513")) {
                state.addBranch(41);
                state.put("WS-MESSAGE", "Orig Date - Not a valid date...");
                state.put("WS-ERR-FLG", "Y");
                state.put("TORIGDTL", -1);
                perform(state, "SEND-TRNADD-SCREEN");
            } else {
                state.addBranch(-41);
            }
        }
        state.put("CSUTLDTC-DATE", state.get("TPROCDTI"));
        state.put("CSUTLDTC-DATE-FORMAT", state.get("WS-DATE-FORMAT"));
        state.put("CSUTLDTC-RESULT", " ");
        stubs.dummyCall(state, "CSUTLDTC");
        if (java.util.Objects.equals(state.get("CSUTLDTC-RESULT-SEV-CD"), "0000")) {
            state.addBranch(42);
            // CONTINUE
        } else {
            state.addBranch(-42);
            if (!java.util.Objects.equals(state.get("CSUTLDTC-RESULT-MSG-NUM"), "2513")) {
                state.addBranch(43);
                state.put("WS-MESSAGE", "Proc Date - Not a valid date...");
                state.put("WS-ERR-FLG", "Y");
                state.put("TPROCDTL", -1);
                perform(state, "SEND-TRNADD-SCREEN");
            } else {
                state.addBranch(-43);
            }
        }
        if (!CobolRuntime.isNumeric(state.get("MIDI"))) {
            state.addBranch(44);
            state.put("WS-ERR-FLG", "Y");
            state.put("WS-MESSAGE", "Merchant ID must be Numeric...");
            state.put("MIDL", -1);
            perform(state, "SEND-TRNADD-SCREEN");
        } else {
            state.addBranch(-44);
        }
    }

    void do_ADD_TRANSACTION(ProgramState state) {
        state.put("TRAN-ID", "\u00FF");
        perform(state, "STARTBR-TRANSACT-FILE");
        perform(state, "READPREV-TRANSACT-FILE");
        perform(state, "ENDBR-TRANSACT-FILE");
        state.put("WS-TRAN-ID-N", state.get("TRAN-ID"));
        state.put("WS-TRAN-ID-N", CobolRuntime.toNum(state.get("WS-TRAN-ID-N")) + 1);
        state.put("TRAN-RECORD", state.get("TRAN-RECORD") instanceof Number ? 0 : "");
        state.put("TRAN-ID", state.get("WS-TRAN-ID-N"));
        state.put("TRAN-TYPE-CD", state.get("TTYPCDI"));
        state.put("TRAN-CAT-CD", state.get("TCATCDI"));
        state.put("TRAN-SOURCE", state.get("TRNSRCI"));
        state.put("TRAN-DESC", state.get("TDESCI"));
        state.put("WS-TRAN-AMT-N", CobolRuntime.toNum(state.get("TRNAMTI")));
        state.put("TRAN-AMT", state.get("WS-TRAN-AMT-N"));
        state.put("TRAN-CARD-NUM", state.get("CARDNINI"));
        state.put("TRAN-MERCHANT-ID", state.get("MIDI"));
        state.put("TRAN-MERCHANT-NAME", state.get("MNAMEI"));
        state.put("TRAN-MERCHANT-CITY", state.get("MCITYI"));
        state.put("TRAN-MERCHANT-ZIP", state.get("MZIPI"));
        state.put("TRAN-ORIG-TS", state.get("TORIGDTI"));
        state.put("TRAN-PROC-TS", state.get("TPROCDTI"));
        perform(state, "WRITE-TRANSACT-FILE");
    }

    void do_COPY_LAST_TRAN_DATA(ProgramState state) {
        perform(state, "VALIDATE-INPUT-KEY-FIELDS");
        state.put("TRAN-ID", "\u00FF");
        perform(state, "STARTBR-TRANSACT-FILE");
        perform(state, "READPREV-TRANSACT-FILE");
        perform(state, "ENDBR-TRANSACT-FILE");
        if (!(CobolRuntime.isTruthy(state.get("ERR-FLG-ON")))) {
            state.addBranch(45);
            state.put("WS-TRAN-AMT-E", state.get("TRAN-AMT"));
            state.put("TTYPCDI", state.get("TRAN-TYPE-CD"));
            state.put("TCATCDI", state.get("TRAN-CAT-CD"));
            state.put("TRNSRCI", state.get("TRAN-SOURCE"));
            state.put("TRNAMTI", state.get("WS-TRAN-AMT-E"));
            state.put("TDESCI", state.get("TRAN-DESC"));
            state.put("TORIGDTI", state.get("TRAN-ORIG-TS"));
            state.put("TPROCDTI", state.get("TRAN-PROC-TS"));
            state.put("MIDI", state.get("TRAN-MERCHANT-ID"));
            state.put("MNAMEI", state.get("TRAN-MERCHANT-NAME"));
            state.put("MCITYI", state.get("TRAN-MERCHANT-CITY"));
            state.put("MZIPI", state.get("TRAN-MERCHANT-ZIP"));
        } else {
            state.addBranch(-45);
        }
        perform(state, "PROCESS-ENTER-KEY");
    }

    void do_RETURN_TO_PREV_SCREEN(ProgramState state) {
        if (java.util.List.of("\u0000", " ").contains(state.get("CDEMO-TO-PROGRAM"))) {
            state.addBranch(46);
            state.put("CDEMO-TO-PROGRAM", "COSGN00C");
        } else {
            state.addBranch(-46);
        }
        state.put("CDEMO-FROM-TRANID", state.get("WS-TRANID"));
        state.put("CDEMO-FROM-PROGRAM", state.get("WS-PGMNAME"));
        state.put("CDEMO-PGM-CONTEXT", 0);
        stubs.dummyExec(state, "CICS", "EXEC CICS XCTL PROGRAM(CDEMO-TO-PROGRAM) COMMAREA(CARDDEMO-COMMAREA) END-EXEC");
    }

    void do_SEND_TRNADD_SCREEN(ProgramState state) {
        perform(state, "POPULATE-HEADER-INFO");
        state.put("ERRMSGO", state.get("WS-MESSAGE"));
        stubs.dummyExec(state, "CICS", "EXEC CICS SEND MAP('COTRN2A') MAPSET('COTRN02') FROM(COTRN2AO) ERASE CURSOR END-EXEC");
        stubs.cicsReturn(state, true);
    }

    void do_RECEIVE_TRNADD_SCREEN(ProgramState state) {
        stubs.dummyExec(state, "CICS", "EXEC CICS RECEIVE MAP('COTRN2A') MAPSET('COTRN02') INTO(COTRN2AI) RESP(WS-RESP-CD) RESP2(WS-REAS-CD) END-EXEC");
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

    void do_READ_CXACAIX_FILE(ProgramState state) {
        stubs.cicsRead(state, "WS-CXACAIX-FILE", "XREF-ACCT-ID", "CARD-XREF-RECORD", "WS-RESP-CD", "WS-REAS-CD");
        Object _evalSubject9 = state.get("WS-RESP-CD");
        if ((java.util.Objects.equals(_evalSubject9, 0))) {
            state.addBranch(47);
            // CONTINUE
        }
        else if ((java.util.Objects.equals(_evalSubject9, 13))) {
            state.addBranch(48);
            state.put("WS-ERR-FLG", "Y");
            state.put("WS-MESSAGE", "Account ID NOT found...");
            state.put("ACTIDINL", -1);
            perform(state, "SEND-TRNADD-SCREEN");
        }
        else {
            state.addBranch(49);
            display(state, "RESP:", String.valueOf(state.get("WS-RESP-CD")), "REAS:", String.valueOf(state.get("WS-REAS-CD")));
            state.put("WS-ERR-FLG", "Y");
            state.put("WS-MESSAGE", "Unable to lookup Acct in XREF AIX file...");
            state.put("ACTIDINL", -1);
            perform(state, "SEND-TRNADD-SCREEN");
        }
    }

    void do_READ_CCXREF_FILE(ProgramState state) {
        stubs.cicsRead(state, "WS-CCXREF-FILE", "XREF-CARD-NUM", "CARD-XREF-RECORD", "WS-RESP-CD", "WS-REAS-CD");
        Object _evalSubject10 = state.get("WS-RESP-CD");
        if ((java.util.Objects.equals(_evalSubject10, 0))) {
            state.addBranch(50);
            // CONTINUE
        }
        else if ((java.util.Objects.equals(_evalSubject10, 13))) {
            state.addBranch(51);
            state.put("WS-ERR-FLG", "Y");
            state.put("WS-MESSAGE", "Card Number NOT found...");
            state.put("CARDNINL", -1);
            perform(state, "SEND-TRNADD-SCREEN");
        }
        else {
            state.addBranch(52);
            display(state, "RESP:", String.valueOf(state.get("WS-RESP-CD")), "REAS:", String.valueOf(state.get("WS-REAS-CD")));
            state.put("WS-ERR-FLG", "Y");
            state.put("WS-MESSAGE", "Unable to lookup Card # in XREF file...");
            state.put("CARDNINL", -1);
            perform(state, "SEND-TRNADD-SCREEN");
        }
    }

    void do_STARTBR_TRANSACT_FILE(ProgramState state) {
        stubs.dummyExec(state, "CICS", "EXEC CICS STARTBR DATASET   (WS-TRANSACT-FILE) RIDFLD    (TRAN-ID) KEYLENGTH (LENGTH OF TRAN-ID) RESP      (WS-RESP-CD) RESP2     (WS-REAS-CD) END-EXEC");
        Object _evalSubject11 = state.get("WS-RESP-CD");
        if ((java.util.Objects.equals(_evalSubject11, 0))) {
            state.addBranch(53);
            // CONTINUE
        }
        else if ((java.util.Objects.equals(_evalSubject11, 13))) {
            state.addBranch(54);
            state.put("WS-ERR-FLG", "Y");
            state.put("WS-MESSAGE", "Transaction ID NOT found...");
            state.put("ACTIDINL", -1);
            perform(state, "SEND-TRNADD-SCREEN");
        }
        else {
            state.addBranch(55);
            display(state, "RESP:", String.valueOf(state.get("WS-RESP-CD")), "REAS:", String.valueOf(state.get("WS-REAS-CD")));
            state.put("WS-ERR-FLG", "Y");
            state.put("WS-MESSAGE", "Unable to lookup Transaction...");
            state.put("ACTIDINL", -1);
            perform(state, "SEND-TRNADD-SCREEN");
        }
    }

    void do_READPREV_TRANSACT_FILE(ProgramState state) {
        stubs.cicsRead(state, "WS-TRANSACT-FILE", "TRAN-ID", "TRAN-RECORD", "WS-RESP-CD", "WS-REAS-CD");
        Object _evalSubject12 = state.get("WS-RESP-CD");
        if ((java.util.Objects.equals(_evalSubject12, 0))) {
            state.addBranch(56);
            // CONTINUE
        }
        else if ((java.util.Objects.equals(_evalSubject12, 20))) {
            state.addBranch(57);
            state.put("TRAN-ID", 0);
        }
        else {
            state.addBranch(58);
            display(state, "RESP:", String.valueOf(state.get("WS-RESP-CD")), "REAS:", String.valueOf(state.get("WS-REAS-CD")));
            state.put("WS-ERR-FLG", "Y");
            state.put("WS-MESSAGE", "Unable to lookup Transaction...");
            state.put("ACTIDINL", -1);
            perform(state, "SEND-TRNADD-SCREEN");
        }
    }

    void do_ENDBR_TRANSACT_FILE(ProgramState state) {
        stubs.dummyExec(state, "CICS", "EXEC CICS ENDBR DATASET   (WS-TRANSACT-FILE) END-EXEC");
    }

    void do_WRITE_TRANSACT_FILE(ProgramState state) {
        stubs.dummyExec(state, "CICS", "EXEC CICS WRITE DATASET   (WS-TRANSACT-FILE) FROM      (TRAN-RECORD) LENGTH    (LENGTH OF TRAN-RECORD) RIDFLD    (TRAN-ID) KEYLENGTH (LENGTH OF TRAN-ID) RESP      (WS-RESP-CD) RESP2     (WS-REAS-CD) E...");
        Object _evalSubject13 = state.get("WS-RESP-CD");
        if ((java.util.Objects.equals(_evalSubject13, 0))) {
            state.addBranch(59);
            perform(state, "INITIALIZE-ALL-FIELDS");
            state.put("WS-MESSAGE", " ");
            state.put("ERRMSGC", state.get("DFHGREEN"));
            state.put("WS-MESSAGE", "Transaction added successfully. " + " Your Tran ID is " + String.valueOf(state.get("TRAN-ID")) + String.valueOf(state.get("DELIMITED")) + String.valueOf(state.get("BY")) + String.valueOf(state.get("SPACE")) + ".");
            perform(state, "SEND-TRNADD-SCREEN");
        }
        else if ((java.util.Objects.equals(_evalSubject13, 15))) {
            state.addBranch(60);
            state.put("WS-ERR-FLG", "Y");
            state.put("WS-MESSAGE", "Tran ID already exist...");
            state.put("ACTIDINL", -1);
            perform(state, "SEND-TRNADD-SCREEN");
        }
        else {
            state.addBranch(61);
            display(state, "RESP:", String.valueOf(state.get("WS-RESP-CD")), "REAS:", String.valueOf(state.get("WS-REAS-CD")));
            state.put("WS-ERR-FLG", "Y");
            state.put("WS-MESSAGE", "Unable to Add Transaction...");
            state.put("ACTIDINL", -1);
            perform(state, "SEND-TRNADD-SCREEN");
        }
    }

    void do_CLEAR_CURRENT_SCREEN(ProgramState state) {
        perform(state, "INITIALIZE-ALL-FIELDS");
        perform(state, "SEND-TRNADD-SCREEN");
    }

    void do_INITIALIZE_ALL_FIELDS(ProgramState state) {
        state.put("ACTIDINL", -1);
        state.put("ACTIDINI", " ");
        state.put("CARDNINI", " ");
        state.put("TTYPCDI", " ");
        state.put("TCATCDI", " ");
        state.put("TRNSRCI", " ");
        state.put("TRNAMTI", " ");
        state.put("TDESCI", " ");
        state.put("TORIGDTI", " ");
        state.put("TPROCDTI", " ");
        state.put("MIDI", " ");
        state.put("MNAMEI", " ");
        state.put("MCITYI", " ");
        state.put("MZIPI", " ");
        state.put("CONFIRMI", " ");
        state.put("WS-MESSAGE", " ");
    }

    void do_CSUTLDTC(ProgramState state) {
        // empty paragraph
    }

}
