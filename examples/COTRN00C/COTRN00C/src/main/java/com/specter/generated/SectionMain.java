package com.specter.generated;

/**
 * Generated section: SectionMain.
 */
public class SectionMain extends SectionBase {

    public SectionMain(ParagraphRegistry registry, StubExecutor stubs) {
        super(registry, stubs);
        paragraph("MAIN-PARA", this::do_MAIN_PARA);
        paragraph("PROCESS-ENTER-KEY", this::do_PROCESS_ENTER_KEY);
        paragraph("PROCESS-PF7-KEY", this::do_PROCESS_PF7_KEY);
        paragraph("PROCESS-PF8-KEY", this::do_PROCESS_PF8_KEY);
        paragraph("PROCESS-PAGE-FORWARD", this::do_PROCESS_PAGE_FORWARD);
        paragraph("PROCESS-PAGE-BACKWARD", this::do_PROCESS_PAGE_BACKWARD);
        paragraph("POPULATE-TRAN-DATA", this::do_POPULATE_TRAN_DATA);
        paragraph("INITIALIZE-TRAN-DATA", this::do_INITIALIZE_TRAN_DATA);
        paragraph("RETURN-TO-PREV-SCREEN", this::do_RETURN_TO_PREV_SCREEN);
        paragraph("SEND-TRNLST-SCREEN", this::do_SEND_TRNLST_SCREEN);
        paragraph("RECEIVE-TRNLST-SCREEN", this::do_RECEIVE_TRNLST_SCREEN);
        paragraph("POPULATE-HEADER-INFO", this::do_POPULATE_HEADER_INFO);
        paragraph("STARTBR-TRANSACT-FILE", this::do_STARTBR_TRANSACT_FILE);
        paragraph("READNEXT-TRANSACT-FILE", this::do_READNEXT_TRANSACT_FILE);
        paragraph("READPREV-TRANSACT-FILE", this::do_READPREV_TRANSACT_FILE);
        paragraph("ENDBR-TRANSACT-FILE", this::do_ENDBR_TRANSACT_FILE);
        paragraph("CDEMO-CT00-PAGE-NUM", this::do_CDEMO_CT00_PAGE_NUM);
        paragraph("WS-IDX", this::do_WS_IDX);
    }

    void do_MAIN_PARA(ProgramState state) {
        state.put("ERR-FLG-OFF", true);
        state.put("TRANSACT-NOT-EOF", true);
        state.put("NEXT-PAGE-NO", true);
        state.put("SEND-ERASE-YES", true);
        state.put("WS-MESSAGE", " ");
        state.put("TRNIDINL", -1);
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
                state.put("COTRN0AO", "\u0000");
                perform(state, "PROCESS-ENTER-KEY");
                perform(state, "SEND-TRNLST-SCREEN");
            } else {
                state.addBranch(-2);
                perform(state, "RECEIVE-TRNLST-SCREEN");
                Object _evalSubject1 = state.get("EIBAID");
                if (java.util.Objects.equals(_evalSubject1, "DFHENTER")) {
                    state.addBranch(3);
                    perform(state, "PROCESS-ENTER-KEY");
                }
                else if (java.util.Objects.equals(_evalSubject1, "DFHPF3")) {
                    state.addBranch(4);
                    state.put("CDEMO-TO-PROGRAM", "COMEN01C");
                    perform(state, "RETURN-TO-PREV-SCREEN");
                }
                else if (java.util.Objects.equals(_evalSubject1, "DFHPF7")) {
                    state.addBranch(5);
                    perform(state, "PROCESS-PF7-KEY");
                }
                else if (java.util.Objects.equals(_evalSubject1, "DFHPF8")) {
                    state.addBranch(6);
                    perform(state, "PROCESS-PF8-KEY");
                }
                else {
                    state.addBranch(7);
                    state.put("WS-ERR-FLG", "Y");
                    state.put("TRNIDINL", -1);
                    state.put("WS-MESSAGE", state.get("CCDA-MSG-INVALID-KEY"));
                    perform(state, "SEND-TRNLST-SCREEN");
                }
            }
        }
        stubs.cicsReturn(state, true);
    }

    void do_PROCESS_ENTER_KEY(ProgramState state) {
        if (!java.util.List.of(" ", "\u0000").contains(state.get("SEL0001I"))) {
            state.addBranch(8);
            state.put("CDEMO-CT00-TRN-SEL-FLG", state.get("SEL0001I"));
            state.put("CDEMO-CT00-TRN-SELECTED", state.get("TRNID01I"));
        }
        else if (!java.util.List.of(" ", "\u0000").contains(state.get("SEL0002I"))) {
            state.addBranch(9);
            state.put("CDEMO-CT00-TRN-SEL-FLG", state.get("SEL0002I"));
            state.put("CDEMO-CT00-TRN-SELECTED", state.get("TRNID02I"));
        }
        else if (!java.util.List.of(" ", "\u0000").contains(state.get("SEL0003I"))) {
            state.addBranch(10);
            state.put("CDEMO-CT00-TRN-SEL-FLG", state.get("SEL0003I"));
            state.put("CDEMO-CT00-TRN-SELECTED", state.get("TRNID03I"));
        }
        else if (!java.util.List.of(" ", "\u0000").contains(state.get("SEL0004I"))) {
            state.addBranch(11);
            state.put("CDEMO-CT00-TRN-SEL-FLG", state.get("SEL0004I"));
            state.put("CDEMO-CT00-TRN-SELECTED", state.get("TRNID04I"));
        }
        else if (!java.util.List.of(" ", "\u0000").contains(state.get("SEL0005I"))) {
            state.addBranch(12);
            state.put("CDEMO-CT00-TRN-SEL-FLG", state.get("SEL0005I"));
            state.put("CDEMO-CT00-TRN-SELECTED", state.get("TRNID05I"));
        }
        else if (!java.util.List.of(" ", "\u0000").contains(state.get("SEL0006I"))) {
            state.addBranch(13);
            state.put("CDEMO-CT00-TRN-SEL-FLG", state.get("SEL0006I"));
            state.put("CDEMO-CT00-TRN-SELECTED", state.get("TRNID06I"));
        }
        else if (!java.util.List.of(" ", "\u0000").contains(state.get("SEL0007I"))) {
            state.addBranch(14);
            state.put("CDEMO-CT00-TRN-SEL-FLG", state.get("SEL0007I"));
            state.put("CDEMO-CT00-TRN-SELECTED", state.get("TRNID07I"));
        }
        else if (!java.util.List.of(" ", "\u0000").contains(state.get("SEL0008I"))) {
            state.addBranch(15);
            state.put("CDEMO-CT00-TRN-SEL-FLG", state.get("SEL0008I"));
            state.put("CDEMO-CT00-TRN-SELECTED", state.get("TRNID08I"));
        }
        else if (!java.util.List.of(" ", "\u0000").contains(state.get("SEL0009I"))) {
            state.addBranch(16);
            state.put("CDEMO-CT00-TRN-SEL-FLG", state.get("SEL0009I"));
            state.put("CDEMO-CT00-TRN-SELECTED", state.get("TRNID09I"));
        }
        else if (!java.util.List.of(" ", "\u0000").contains(state.get("SEL0010I"))) {
            state.addBranch(17);
            state.put("CDEMO-CT00-TRN-SEL-FLG", state.get("SEL0010I"));
            state.put("CDEMO-CT00-TRN-SELECTED", state.get("TRNID10I"));
        }
        else {
            state.addBranch(18);
            state.put("CDEMO-CT00-TRN-SEL-FLG", " ");
            state.put("CDEMO-CT00-TRN-SELECTED", " ");
        }
        if ((!java.util.List.of(" ", "\u0000").contains(state.get("CDEMO-CT00-TRN-SEL-FLG"))) && (!java.util.List.of(" ", "\u0000").contains(state.get("CDEMO-CT00-TRN-SELECTED")))) {
            state.addBranch(19);
            Object _evalSubject3 = state.get("CDEMO-CT00-TRN-SEL-FLG");
            if (java.util.Objects.equals(_evalSubject3, "S")) {
                state.addBranch(20);
                // empty WHEN
            }
            else if (java.util.Objects.equals(_evalSubject3, "s")) {
                state.addBranch(21);
                state.put("CDEMO-TO-PROGRAM", "COTRN01C");
                state.put("CDEMO-FROM-TRANID", state.get("WS-TRANID"));
                state.put("CDEMO-FROM-PROGRAM", state.get("WS-PGMNAME"));
                state.put("CDEMO-PGM-CONTEXT", 0);
                stubs.dummyExec(state, "CICS", "EXEC CICS XCTL PROGRAM(CDEMO-TO-PROGRAM) COMMAREA(CARDDEMO-COMMAREA) END-EXEC");
            }
            else {
                state.addBranch(22);
                state.put("WS-MESSAGE", "Invalid selection. Valid value is S");
                state.put("TRNIDINL", -1);
            }
        } else {
            state.addBranch(-19);
        }
        if (java.util.List.of(" ", "\u0000").contains(state.get("TRNIDINI"))) {
            state.addBranch(23);
            state.put("TRAN-ID", "\u0000");
        } else {
            state.addBranch(-23);
            if (CobolRuntime.isNumeric(state.get("TRNIDINI"))) {
                state.addBranch(24);
                state.put("TRAN-ID", state.get("TRNIDINI"));
            } else {
                state.addBranch(-24);
                state.put("WS-ERR-FLG", "Y");
                state.put("WS-MESSAGE", "Tran ID must be Numeric ...");
                state.put("TRNIDINL", -1);
                perform(state, "SEND-TRNLST-SCREEN");
            }
        }
        state.put("TRNIDINL", -1);
        state.put("CDEMO-CT00-PAGE-NUM", 0);
        perform(state, "PROCESS-PAGE-FORWARD");
        if (!(CobolRuntime.isTruthy(state.get("ERR-FLG-ON")))) {
            state.addBranch(25);
            state.put("TRNIDINO", " ");
        } else {
            state.addBranch(-25);
        }
    }

    void do_PROCESS_PF7_KEY(ProgramState state) {
        if (java.util.List.of(" ", "\u0000").contains(state.get("CDEMO-CT00-TRNID-FIRST"))) {
            state.addBranch(26);
            state.put("TRAN-ID", "\u0000");
        } else {
            state.addBranch(-26);
            state.put("TRAN-ID", state.get("CDEMO-CT00-TRNID-FIRST"));
        }
        state.put("NEXT-PAGE-YES", true);
        state.put("TRNIDINL", -1);
        if (CobolRuntime.toNum(state.get("CDEMO-CT00-PAGE-NUM")) > 1) {
            state.addBranch(27);
            perform(state, "PROCESS-PAGE-BACKWARD");
        } else {
            state.addBranch(-27);
            state.put("WS-MESSAGE", "You are already at the top of the page...");
            state.put("SEND-ERASE-NO", true);
            perform(state, "SEND-TRNLST-SCREEN");
        }
    }

    void do_PROCESS_PF8_KEY(ProgramState state) {
        if (java.util.List.of(" ", "\u0000").contains(state.get("CDEMO-CT00-TRNID-LAST"))) {
            state.addBranch(28);
            state.put("TRAN-ID", "\u00FF");
        } else {
            state.addBranch(-28);
            state.put("TRAN-ID", state.get("CDEMO-CT00-TRNID-LAST"));
        }
        state.put("TRNIDINL", -1);
        if (CobolRuntime.isTruthy(state.get("NEXT-PAGE-YES"))) {
            state.addBranch(29);
            perform(state, "PROCESS-PAGE-FORWARD");
        } else {
            state.addBranch(-29);
            state.put("WS-MESSAGE", "You are already at the bottom of the page...");
            state.put("SEND-ERASE-NO", true);
            perform(state, "SEND-TRNLST-SCREEN");
        }
    }

    void do_PROCESS_PAGE_FORWARD(ProgramState state) {
        perform(state, "STARTBR-TRANSACT-FILE");
        if (!(CobolRuntime.isTruthy(state.get("ERR-FLG-ON")))) {
            state.addBranch(30);
            if (!java.util.List.of("DFHENTER", "DFHPF7", "DFHPF3").contains(state.get("EIBAID"))) {
                state.addBranch(31);
                perform(state, "READNEXT-TRANSACT-FILE");
            } else {
                state.addBranch(-31);
            }
            if ((CobolRuntime.isTruthy(state.get("TRANSACT-NOT-EOF"))) && (CobolRuntime.isTruthy(state.get("ERR-FLG-OFF")))) {
                state.addBranch(32);
                state.put("WS-IDX", CobolRuntime.toNum(1));
                int _lc1 = 0;
                while (!(CobolRuntime.toNum(state.get("WS-IDX")) > 10)) {
                    state.addBranch(33);
                    perform(state, "INITIALIZE-TRAN-DATA");
                    state.put("WS-IDX", CobolRuntime.toNum(state.get("WS-IDX")) + CobolRuntime.toNum(1));
                    _lc1++;
                    if (_lc1 >= 100) {
                        break;
                    }
                }
                if (_lc1 == 0) {
                    state.addBranch(-33);
                }
            } else {
                state.addBranch(-32);
            }
            state.put("WS-IDX", 1);
            int _lc2 = 0;
            while (!(java.util.List.of(11, state.get("TRANSACT-EOF"), state.get("ERR-FLG-ON")).contains(state.get("WS-IDX")))) {
                state.addBranch(34);
                perform(state, "READNEXT-TRANSACT-FILE");
                if ((CobolRuntime.isTruthy(state.get("TRANSACT-NOT-EOF"))) && (CobolRuntime.isTruthy(state.get("ERR-FLG-OFF")))) {
                    state.addBranch(35);
                    perform(state, "POPULATE-TRAN-DATA");
                    state.put("WS-IDX", CobolRuntime.toNum(state.get("WS-IDX")) + 1);
                } else {
                    state.addBranch(-35);
                }
                _lc2++;
                if (_lc2 >= 100) {
                    break;
                }
            }
            if (_lc2 == 0) {
                state.addBranch(-34);
            }
            if ((CobolRuntime.isTruthy(state.get("TRANSACT-NOT-EOF"))) && (CobolRuntime.isTruthy(state.get("ERR-FLG-OFF")))) {
                state.addBranch(36);
                state.put("CDEMO-CT00-PAGE-NUM", CobolRuntime.toNum(state.get("CDEMO-CT00-PAGE-NUM")) + 1);
                perform(state, "READNEXT-TRANSACT-FILE");
                if ((CobolRuntime.isTruthy(state.get("TRANSACT-NOT-EOF"))) && (CobolRuntime.isTruthy(state.get("ERR-FLG-OFF")))) {
                    state.addBranch(37);
                    state.put("NEXT-PAGE-YES", true);
                } else {
                    state.addBranch(-37);
                    state.put("NEXT-PAGE-NO", true);
                }
            } else {
                state.addBranch(-36);
                state.put("NEXT-PAGE-NO", true);
                if (CobolRuntime.toNum(state.get("WS-IDX")) > 1) {
                    state.addBranch(38);
                    state.put("CDEMO-CT00-PAGE-NUM", CobolRuntime.toNum(state.get("CDEMO-CT00-PAGE-NUM")));
                } else {
                    state.addBranch(-38);
                }
            }
            perform(state, "ENDBR-TRANSACT-FILE");
            state.put("PAGENUMI", state.get("CDEMO-CT00-PAGE-NUM"));
            state.put("TRNIDINO", " ");
            perform(state, "SEND-TRNLST-SCREEN");
        } else {
            state.addBranch(-30);
        }
    }

    void do_PROCESS_PAGE_BACKWARD(ProgramState state) {
        perform(state, "STARTBR-TRANSACT-FILE");
        if (!(CobolRuntime.isTruthy(state.get("ERR-FLG-ON")))) {
            state.addBranch(39);
            if (!java.util.List.of("DFHENTER", "DFHPF8").contains(state.get("EIBAID"))) {
                state.addBranch(40);
                perform(state, "READPREV-TRANSACT-FILE");
            } else {
                state.addBranch(-40);
            }
            if ((CobolRuntime.isTruthy(state.get("TRANSACT-NOT-EOF"))) && (CobolRuntime.isTruthy(state.get("ERR-FLG-OFF")))) {
                state.addBranch(41);
                state.put("WS-IDX", CobolRuntime.toNum(1));
                int _lc3 = 0;
                while (!(CobolRuntime.toNum(state.get("WS-IDX")) > 10)) {
                    state.addBranch(42);
                    perform(state, "INITIALIZE-TRAN-DATA");
                    state.put("WS-IDX", CobolRuntime.toNum(state.get("WS-IDX")) + CobolRuntime.toNum(1));
                    _lc3++;
                    if (_lc3 >= 100) {
                        break;
                    }
                }
                if (_lc3 == 0) {
                    state.addBranch(-42);
                }
            } else {
                state.addBranch(-41);
            }
            state.put("WS-IDX", 10);
            int _lc4 = 0;
            while (!(java.util.List.of(0, state.get("TRANSACT-EOF"), state.get("ERR-FLG-ON")).contains(state.get("WS-IDX")))) {
                state.addBranch(43);
                perform(state, "READPREV-TRANSACT-FILE");
                if ((CobolRuntime.isTruthy(state.get("TRANSACT-NOT-EOF"))) && (CobolRuntime.isTruthy(state.get("ERR-FLG-OFF")))) {
                    state.addBranch(44);
                    perform(state, "POPULATE-TRAN-DATA");
                    state.put("WS-IDX", CobolRuntime.toNum(state.get("WS-IDX")) - 1);
                } else {
                    state.addBranch(-44);
                }
                _lc4++;
                if (_lc4 >= 100) {
                    break;
                }
            }
            if (_lc4 == 0) {
                state.addBranch(-43);
            }
            if ((CobolRuntime.isTruthy(state.get("TRANSACT-NOT-EOF"))) && (CobolRuntime.isTruthy(state.get("ERR-FLG-OFF")))) {
                state.addBranch(45);
                perform(state, "READPREV-TRANSACT-FILE");
                if (CobolRuntime.isTruthy(state.get("NEXT-PAGE-YES"))) {
                    state.addBranch(46);
                    if (((CobolRuntime.isTruthy(state.get("TRANSACT-NOT-EOF"))) && (CobolRuntime.isTruthy(state.get("ERR-FLG-OFF")))) && (CobolRuntime.toNum(state.get("CDEMO-CT00-PAGE-NUM")) > 1)) {
                        state.addBranch(47);
                        state.put("CDEMO-CT00-PAGE-NUM", CobolRuntime.toNum(state.get("CDEMO-CT00-PAGE-NUM")) - 1);
                    } else {
                        state.addBranch(-47);
                        state.put("CDEMO-CT00-PAGE-NUM", 1);
                    }
                } else {
                    state.addBranch(-46);
                }
            } else {
                state.addBranch(-45);
            }
            perform(state, "ENDBR-TRANSACT-FILE");
            state.put("PAGENUMI", state.get("CDEMO-CT00-PAGE-NUM"));
            perform(state, "SEND-TRNLST-SCREEN");
        } else {
            state.addBranch(-39);
        }
    }

    void do_POPULATE_TRAN_DATA(ProgramState state) {
        state.put("WS-TRAN-AMT", state.get("TRAN-AMT"));
        state.put("WS-TIMESTAMP", state.get("TRAN-ORIG-TS"));
        state.put("WS-CURDATE-YY", (String.valueOf(state.get("WS-TIMESTAMP-DT-YYYY")).length() > 2 ? String.valueOf(state.get("WS-TIMESTAMP-DT-YYYY")).substring(2, Math.min(4, String.valueOf(state.get("WS-TIMESTAMP-DT-YYYY")).length())) : ""));
        state.put("WS-CURDATE-MM", state.get("WS-TIMESTAMP-DT-MM"));
        state.put("WS-CURDATE-DD", state.get("WS-TIMESTAMP-DT-DD"));
        state.put("WS-TRAN-DATE", state.get("WS-CURDATE-MM-DD-YY"));
        Object _evalSubject4 = state.get("WS-IDX");
        _evalSubject4 = CobolRuntime.toNum(_evalSubject4);
        if (java.util.Objects.equals(_evalSubject4, CobolRuntime.toNum(1))) {
            state.addBranch(48);
            state.put("TRNID01I", state.get("TRAN-ID"));
            state.put("TDATE01I", state.get("WS-TRAN-DATE"));
            state.put("TDESC01I", state.get("TRAN-DESC"));
            state.put("TAMT001I", state.get("WS-TRAN-AMT"));
        }
        else if (java.util.Objects.equals(_evalSubject4, CobolRuntime.toNum(2))) {
            state.addBranch(49);
            state.put("TRNID02I", state.get("TRAN-ID"));
            state.put("TDATE02I", state.get("WS-TRAN-DATE"));
            state.put("TDESC02I", state.get("TRAN-DESC"));
            state.put("TAMT002I", state.get("WS-TRAN-AMT"));
        }
        else if (java.util.Objects.equals(_evalSubject4, CobolRuntime.toNum(3))) {
            state.addBranch(50);
            state.put("TRNID03I", state.get("TRAN-ID"));
            state.put("TDATE03I", state.get("WS-TRAN-DATE"));
            state.put("TDESC03I", state.get("TRAN-DESC"));
            state.put("TAMT003I", state.get("WS-TRAN-AMT"));
        }
        else if (java.util.Objects.equals(_evalSubject4, CobolRuntime.toNum(4))) {
            state.addBranch(51);
            state.put("TRNID04I", state.get("TRAN-ID"));
            state.put("TDATE04I", state.get("WS-TRAN-DATE"));
            state.put("TDESC04I", state.get("TRAN-DESC"));
            state.put("TAMT004I", state.get("WS-TRAN-AMT"));
        }
        else if (java.util.Objects.equals(_evalSubject4, CobolRuntime.toNum(5))) {
            state.addBranch(52);
            state.put("TRNID05I", state.get("TRAN-ID"));
            state.put("TDATE05I", state.get("WS-TRAN-DATE"));
            state.put("TDESC05I", state.get("TRAN-DESC"));
            state.put("TAMT005I", state.get("WS-TRAN-AMT"));
        }
        else if (java.util.Objects.equals(_evalSubject4, CobolRuntime.toNum(6))) {
            state.addBranch(53);
            state.put("TRNID06I", state.get("TRAN-ID"));
            state.put("TDATE06I", state.get("WS-TRAN-DATE"));
            state.put("TDESC06I", state.get("TRAN-DESC"));
            state.put("TAMT006I", state.get("WS-TRAN-AMT"));
        }
        else if (java.util.Objects.equals(_evalSubject4, CobolRuntime.toNum(7))) {
            state.addBranch(54);
            state.put("TRNID07I", state.get("TRAN-ID"));
            state.put("TDATE07I", state.get("WS-TRAN-DATE"));
            state.put("TDESC07I", state.get("TRAN-DESC"));
            state.put("TAMT007I", state.get("WS-TRAN-AMT"));
        }
        else if (java.util.Objects.equals(_evalSubject4, CobolRuntime.toNum(8))) {
            state.addBranch(55);
            state.put("TRNID08I", state.get("TRAN-ID"));
            state.put("TDATE08I", state.get("WS-TRAN-DATE"));
            state.put("TDESC08I", state.get("TRAN-DESC"));
            state.put("TAMT008I", state.get("WS-TRAN-AMT"));
        }
        else if (java.util.Objects.equals(_evalSubject4, CobolRuntime.toNum(9))) {
            state.addBranch(56);
            state.put("TRNID09I", state.get("TRAN-ID"));
            state.put("TDATE09I", state.get("WS-TRAN-DATE"));
            state.put("TDESC09I", state.get("TRAN-DESC"));
            state.put("TAMT009I", state.get("WS-TRAN-AMT"));
        }
        else if (java.util.Objects.equals(_evalSubject4, CobolRuntime.toNum(10))) {
            state.addBranch(57);
            state.put("TRNID10I", state.get("TRAN-ID"));
            state.put("TDATE10I", state.get("WS-TRAN-DATE"));
            state.put("TDESC10I", state.get("TRAN-DESC"));
            state.put("TAMT010I", state.get("WS-TRAN-AMT"));
        }
        else {
            state.addBranch(58);
            // CONTINUE
        }
    }

    void do_INITIALIZE_TRAN_DATA(ProgramState state) {
        Object _evalSubject5 = state.get("WS-IDX");
        _evalSubject5 = CobolRuntime.toNum(_evalSubject5);
        if (java.util.Objects.equals(_evalSubject5, CobolRuntime.toNum(1))) {
            state.addBranch(59);
            state.put("TRNID01I", " ");
            state.put("TDATE01I", " ");
            state.put("TDESC01I", " ");
            state.put("TAMT001I", " ");
        }
        else if (java.util.Objects.equals(_evalSubject5, CobolRuntime.toNum(2))) {
            state.addBranch(60);
            state.put("TRNID02I", " ");
            state.put("TDATE02I", " ");
            state.put("TDESC02I", " ");
            state.put("TAMT002I", " ");
        }
        else if (java.util.Objects.equals(_evalSubject5, CobolRuntime.toNum(3))) {
            state.addBranch(61);
            state.put("TRNID03I", " ");
            state.put("TDATE03I", " ");
            state.put("TDESC03I", " ");
            state.put("TAMT003I", " ");
        }
        else if (java.util.Objects.equals(_evalSubject5, CobolRuntime.toNum(4))) {
            state.addBranch(62);
            state.put("TRNID04I", " ");
            state.put("TDATE04I", " ");
            state.put("TDESC04I", " ");
            state.put("TAMT004I", " ");
        }
        else if (java.util.Objects.equals(_evalSubject5, CobolRuntime.toNum(5))) {
            state.addBranch(63);
            state.put("TRNID05I", " ");
            state.put("TDATE05I", " ");
            state.put("TDESC05I", " ");
            state.put("TAMT005I", " ");
        }
        else if (java.util.Objects.equals(_evalSubject5, CobolRuntime.toNum(6))) {
            state.addBranch(64);
            state.put("TRNID06I", " ");
            state.put("TDATE06I", " ");
            state.put("TDESC06I", " ");
            state.put("TAMT006I", " ");
        }
        else if (java.util.Objects.equals(_evalSubject5, CobolRuntime.toNum(7))) {
            state.addBranch(65);
            state.put("TRNID07I", " ");
            state.put("TDATE07I", " ");
            state.put("TDESC07I", " ");
            state.put("TAMT007I", " ");
        }
        else if (java.util.Objects.equals(_evalSubject5, CobolRuntime.toNum(8))) {
            state.addBranch(66);
            state.put("TRNID08I", " ");
            state.put("TDATE08I", " ");
            state.put("TDESC08I", " ");
            state.put("TAMT008I", " ");
        }
        else if (java.util.Objects.equals(_evalSubject5, CobolRuntime.toNum(9))) {
            state.addBranch(67);
            state.put("TRNID09I", " ");
            state.put("TDATE09I", " ");
            state.put("TDESC09I", " ");
            state.put("TAMT009I", " ");
        }
        else if (java.util.Objects.equals(_evalSubject5, CobolRuntime.toNum(10))) {
            state.addBranch(68);
            state.put("TRNID10I", " ");
            state.put("TDATE10I", " ");
            state.put("TDESC10I", " ");
            state.put("TAMT010I", " ");
        }
        else {
            state.addBranch(69);
            // CONTINUE
        }
    }

    void do_RETURN_TO_PREV_SCREEN(ProgramState state) {
        if (java.util.List.of("\u0000", " ").contains(state.get("CDEMO-TO-PROGRAM"))) {
            state.addBranch(70);
            state.put("CDEMO-TO-PROGRAM", "COSGN00C");
        } else {
            state.addBranch(-70);
        }
        state.put("CDEMO-FROM-TRANID", state.get("WS-TRANID"));
        state.put("CDEMO-FROM-PROGRAM", state.get("WS-PGMNAME"));
        state.put("CDEMO-PGM-CONTEXT", 0);
        stubs.dummyExec(state, "CICS", "EXEC CICS XCTL PROGRAM(CDEMO-TO-PROGRAM) COMMAREA(CARDDEMO-COMMAREA) END-EXEC.");
    }

    void do_SEND_TRNLST_SCREEN(ProgramState state) {
        perform(state, "POPULATE-HEADER-INFO");
        state.put("ERRMSGO", state.get("WS-MESSAGE"));
        if (CobolRuntime.isTruthy(state.get("SEND-ERASE-YES"))) {
            state.addBranch(71);
            stubs.dummyExec(state, "CICS", "EXEC CICS SEND MAP('COTRN0A') MAPSET('COTRN00') FROM(COTRN0AO) ERASE CURSOR END-EXEC");
        } else {
            state.addBranch(-71);
            stubs.dummyExec(state, "CICS", "EXEC CICS SEND MAP('COTRN0A') MAPSET('COTRN00') FROM(COTRN0AO) CURSOR END-EXEC");
        }
    }

    void do_RECEIVE_TRNLST_SCREEN(ProgramState state) {
        stubs.dummyExec(state, "CICS", "EXEC CICS RECEIVE MAP('COTRN0A') MAPSET('COTRN00') INTO(COTRN0AI) RESP(WS-RESP-CD) RESP2(WS-REAS-CD) END-EXEC.");
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

    void do_STARTBR_TRANSACT_FILE(ProgramState state) {
        stubs.dummyExec(state, "CICS", "EXEC CICS STARTBR DATASET   (WS-TRANSACT-FILE) RIDFLD    (TRAN-ID) KEYLENGTH (LENGTH OF TRAN-ID) RESP      (WS-RESP-CD) RESP2     (WS-REAS-CD) END-EXEC.");
        Object _evalSubject6 = state.get("WS-RESP-CD");
        if (java.util.Objects.equals(_evalSubject6, 0)) {
            state.addBranch(72);
            // CONTINUE
        }
        else if (java.util.Objects.equals(_evalSubject6, 13)) {
            state.addBranch(73);
            // CONTINUE
            state.put("TRANSACT-EOF", true);
            state.put("WS-MESSAGE", "You are at the top of the page...");
            state.put("TRNIDINL", -1);
            perform(state, "SEND-TRNLST-SCREEN");
        }
        else {
            state.addBranch(74);
            display(state, "RESP:", String.valueOf(state.get("WS-RESP-CD")), "REAS:", String.valueOf(state.get("WS-REAS-CD")));
            state.put("WS-ERR-FLG", "Y");
            state.put("LOOKUP", state.get("UNABLE"));
            state.put("TRANSACTION", state.get("UNABLE"));
            state.put("TO", state.get("UNABLE"));
            state.put("TRNIDINL", -1);
            perform(state, "SEND-TRNLST-SCREEN");
        }
    }

    void do_READNEXT_TRANSACT_FILE(ProgramState state) {
        stubs.cicsRead(state, "WS-TRANSACT-FILE", "TRAN-ID", "TRAN-RECORD", "WS-RESP-CD", "WS-REAS-CD");
        Object _evalSubject7 = state.get("WS-RESP-CD");
        if (java.util.Objects.equals(_evalSubject7, 0)) {
            state.addBranch(75);
            // CONTINUE
        }
        else if (java.util.Objects.equals(_evalSubject7, 20)) {
            state.addBranch(76);
            // CONTINUE
            state.put("TRANSACT-EOF", true);
            state.put("WS-MESSAGE", "You have reached the bottom of the page...");
            state.put("TRNIDINL", -1);
            perform(state, "SEND-TRNLST-SCREEN");
        }
        else {
            state.addBranch(77);
            display(state, "RESP:", String.valueOf(state.get("WS-RESP-CD")), "REAS:", String.valueOf(state.get("WS-REAS-CD")));
            state.put("WS-ERR-FLG", "Y");
            state.put("LOOKUP", state.get("UNABLE"));
            state.put("TRANSACTION", state.get("UNABLE"));
            state.put("TO", state.get("UNABLE"));
            state.put("TRNIDINL", -1);
            perform(state, "SEND-TRNLST-SCREEN");
        }
    }

    void do_READPREV_TRANSACT_FILE(ProgramState state) {
        stubs.cicsRead(state, "WS-TRANSACT-FILE", "TRAN-ID", "TRAN-RECORD", "WS-RESP-CD", "WS-REAS-CD");
        Object _evalSubject8 = state.get("WS-RESP-CD");
        if (java.util.Objects.equals(_evalSubject8, 0)) {
            state.addBranch(78);
            // CONTINUE
        }
        else if (java.util.Objects.equals(_evalSubject8, 20)) {
            state.addBranch(79);
            // CONTINUE
            state.put("TRANSACT-EOF", true);
            state.put("WS-MESSAGE", "You have reached the top of the page...");
            state.put("TRNIDINL", -1);
            perform(state, "SEND-TRNLST-SCREEN");
        }
        else {
            state.addBranch(80);
            display(state, "RESP:", String.valueOf(state.get("WS-RESP-CD")), "REAS:", String.valueOf(state.get("WS-REAS-CD")));
            state.put("WS-ERR-FLG", "Y");
            state.put("LOOKUP", state.get("UNABLE"));
            state.put("TRANSACTION", state.get("UNABLE"));
            state.put("TO", state.get("UNABLE"));
            state.put("TRNIDINL", -1);
            perform(state, "SEND-TRNLST-SCREEN");
        }
    }

    void do_ENDBR_TRANSACT_FILE(ProgramState state) {
        stubs.dummyExec(state, "CICS", "EXEC CICS ENDBR DATASET   (WS-TRANSACT-FILE) END-EXEC.");
    }

    void do_CDEMO_CT00_PAGE_NUM(ProgramState state) {
        // empty paragraph
    }

    void do_WS_IDX(ProgramState state) {
        // empty paragraph
    }

}
