package com.specter.generated;

/**
 * Generated section: SectionMain.
 */
public class SectionMain_COUSR00C extends SectionBase {

    public SectionMain_COUSR00C(ParagraphRegistry registry, StubExecutor stubs) {
        super(registry, stubs);
        paragraph("MAIN-PARA", this::do_MAIN_PARA);
        paragraph("PROCESS-ENTER-KEY", this::do_PROCESS_ENTER_KEY);
        paragraph("PROCESS-PF7-KEY", this::do_PROCESS_PF7_KEY);
        paragraph("PROCESS-PF8-KEY", this::do_PROCESS_PF8_KEY);
        paragraph("PROCESS-PAGE-FORWARD", this::do_PROCESS_PAGE_FORWARD);
        paragraph("PROCESS-PAGE-BACKWARD", this::do_PROCESS_PAGE_BACKWARD);
        paragraph("POPULATE-USER-DATA", this::do_POPULATE_USER_DATA);
        paragraph("INITIALIZE-USER-DATA", this::do_INITIALIZE_USER_DATA);
        paragraph("RETURN-TO-PREV-SCREEN", this::do_RETURN_TO_PREV_SCREEN);
        paragraph("SEND-USRLST-SCREEN", this::do_SEND_USRLST_SCREEN);
        paragraph("RECEIVE-USRLST-SCREEN", this::do_RECEIVE_USRLST_SCREEN);
        paragraph("POPULATE-HEADER-INFO", this::do_POPULATE_HEADER_INFO);
        paragraph("STARTBR-USER-SEC-FILE", this::do_STARTBR_USER_SEC_FILE);
        paragraph("READNEXT-USER-SEC-FILE", this::do_READNEXT_USER_SEC_FILE);
        paragraph("READPREV-USER-SEC-FILE", this::do_READPREV_USER_SEC_FILE);
        paragraph("ENDBR-USER-SEC-FILE", this::do_ENDBR_USER_SEC_FILE);
    }

    void do_MAIN_PARA(ProgramState state) {
        state.put("ERR-FLG-OFF", true);
        state.put("USER-SEC-EOF", false);
        state.put("USER-SEC-NOT-EOF", true);
        state.put("NEXT-PAGE-YES", false);
        state.put("NEXT-PAGE-NO", true);
        state.put("SEND-ERASE-NO", false);
        state.put("SEND-ERASE-YES", true);
        state.put("WS-MESSAGE", " ");
        state.put("ERRMSGO", " ");
        state.put("USRIDINL", -1);
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
                state.put("COUSR0AO", "\u0000");
                perform(state, "PROCESS-ENTER-KEY");
                perform(state, "SEND-USRLST-SCREEN");
            } else {
                state.addBranch(-2);
                perform(state, "RECEIVE-USRLST-SCREEN");
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
                else if ((java.util.Objects.equals(_evalSubject1, "DFHPF7"))) {
                    state.addBranch(5);
                    perform(state, "PROCESS-PF7-KEY");
                }
                else if ((java.util.Objects.equals(_evalSubject1, "DFHPF8"))) {
                    state.addBranch(6);
                    perform(state, "PROCESS-PF8-KEY");
                }
                else {
                    state.addBranch(7);
                    state.put("WS-ERR-FLG", "Y");
                    state.put("USRIDINL", -1);
                    state.put("WS-MESSAGE", state.get("CCDA-MSG-INVALID-KEY"));
                    perform(state, "SEND-USRLST-SCREEN");
                }
            }
        }
        stubs.cicsReturn(state, true);
    }

    void do_PROCESS_ENTER_KEY(ProgramState state) {
        if ((!java.util.List.of(" ", "\u0000").contains(state.get("SEL0001I")))) {
            state.addBranch(8);
            state.put("CDEMO-CU00-USR-SEL-FLG", state.get("SEL0001I"));
            state.put("CDEMO-CU00-USR-SELECTED", state.get("USRID01I"));
        }
        else if ((!java.util.List.of(" ", "\u0000").contains(state.get("SEL0002I")))) {
            state.addBranch(9);
            state.put("CDEMO-CU00-USR-SEL-FLG", state.get("SEL0002I"));
            state.put("CDEMO-CU00-USR-SELECTED", state.get("USRID02I"));
        }
        else if ((!java.util.List.of(" ", "\u0000").contains(state.get("SEL0003I")))) {
            state.addBranch(10);
            state.put("CDEMO-CU00-USR-SEL-FLG", state.get("SEL0003I"));
            state.put("CDEMO-CU00-USR-SELECTED", state.get("USRID03I"));
        }
        else if ((!java.util.List.of(" ", "\u0000").contains(state.get("SEL0004I")))) {
            state.addBranch(11);
            state.put("CDEMO-CU00-USR-SEL-FLG", state.get("SEL0004I"));
            state.put("CDEMO-CU00-USR-SELECTED", state.get("USRID04I"));
        }
        else if ((!java.util.List.of(" ", "\u0000").contains(state.get("SEL0005I")))) {
            state.addBranch(12);
            state.put("CDEMO-CU00-USR-SEL-FLG", state.get("SEL0005I"));
            state.put("CDEMO-CU00-USR-SELECTED", state.get("USRID05I"));
        }
        else if ((!java.util.List.of(" ", "\u0000").contains(state.get("SEL0006I")))) {
            state.addBranch(13);
            state.put("CDEMO-CU00-USR-SEL-FLG", state.get("SEL0006I"));
            state.put("CDEMO-CU00-USR-SELECTED", state.get("USRID06I"));
        }
        else if ((!java.util.List.of(" ", "\u0000").contains(state.get("SEL0007I")))) {
            state.addBranch(14);
            state.put("CDEMO-CU00-USR-SEL-FLG", state.get("SEL0007I"));
            state.put("CDEMO-CU00-USR-SELECTED", state.get("USRID07I"));
        }
        else if ((!java.util.List.of(" ", "\u0000").contains(state.get("SEL0008I")))) {
            state.addBranch(15);
            state.put("CDEMO-CU00-USR-SEL-FLG", state.get("SEL0008I"));
            state.put("CDEMO-CU00-USR-SELECTED", state.get("USRID08I"));
        }
        else if ((!java.util.List.of(" ", "\u0000").contains(state.get("SEL0009I")))) {
            state.addBranch(16);
            state.put("CDEMO-CU00-USR-SEL-FLG", state.get("SEL0009I"));
            state.put("CDEMO-CU00-USR-SELECTED", state.get("USRID09I"));
        }
        else if ((!java.util.List.of(" ", "\u0000").contains(state.get("SEL0010I")))) {
            state.addBranch(17);
            state.put("CDEMO-CU00-USR-SEL-FLG", state.get("SEL0010I"));
            state.put("CDEMO-CU00-USR-SELECTED", state.get("USRID10I"));
        }
        else {
            state.addBranch(18);
            state.put("CDEMO-CU00-USR-SEL-FLG", " ");
            state.put("CDEMO-CU00-USR-SELECTED", " ");
        }
        if ((!java.util.List.of(" ", "\u0000").contains(state.get("CDEMO-CU00-USR-SEL-FLG"))) && (!java.util.List.of(" ", "\u0000").contains(state.get("CDEMO-CU00-USR-SELECTED")))) {
            state.addBranch(19);
            Object _evalSubject3 = state.get("CDEMO-CU00-USR-SEL-FLG");
            if ((java.util.Objects.equals(_evalSubject3, "U"))) {
                state.addBranch(20);
                state.put("CDEMO-TO-PROGRAM", "COUSR02C");
                state.put("CDEMO-FROM-TRANID", state.get("WS-TRANID"));
                state.put("CDEMO-FROM-PROGRAM", state.get("WS-PGMNAME"));
                state.put("CDEMO-PGM-CONTEXT", 0);
                stubs.dummyExec(state, "CICS", "EXEC CICS XCTL PROGRAM(CDEMO-TO-PROGRAM) COMMAREA(CARDDEMO-COMMAREA) END-EXEC");
            }
            else if ((java.util.Objects.equals(_evalSubject3, "D"))) {
                state.addBranch(21);
                state.put("CDEMO-TO-PROGRAM", "COUSR03C");
                state.put("CDEMO-FROM-TRANID", state.get("WS-TRANID"));
                state.put("CDEMO-FROM-PROGRAM", state.get("WS-PGMNAME"));
                state.put("CDEMO-PGM-CONTEXT", 0);
                stubs.dummyExec(state, "CICS", "EXEC CICS XCTL PROGRAM(CDEMO-TO-PROGRAM) COMMAREA(CARDDEMO-COMMAREA) END-EXEC");
            }
            else {
                state.addBranch(22);
                state.put("WS-MESSAGE", "Invalid selection. Valid values are U and D");
                state.put("USRIDINL", -1);
            }
        } else {
            state.addBranch(-19);
        }
        if (java.util.List.of(" ", "\u0000").contains(state.get("USRIDINI"))) {
            state.addBranch(23);
            state.put("SEC-USR-ID", "\u0000");
        } else {
            state.addBranch(-23);
            state.put("SEC-USR-ID", state.get("USRIDINI"));
        }
        state.put("USRIDINL", -1);
        state.put("CDEMO-CU00-PAGE-NUM", 0);
        perform(state, "PROCESS-PAGE-FORWARD");
        if (!(CobolRuntime.isTruthy(state.get("ERR-FLG-ON")))) {
            state.addBranch(24);
            state.put("USRIDINO", " ");
        } else {
            state.addBranch(-24);
        }
    }

    void do_PROCESS_PF7_KEY(ProgramState state) {
        if (java.util.List.of(" ", "\u0000").contains(state.get("CDEMO-CU00-USRID-FIRST"))) {
            state.addBranch(25);
            state.put("SEC-USR-ID", "\u0000");
        } else {
            state.addBranch(-25);
            state.put("SEC-USR-ID", state.get("CDEMO-CU00-USRID-FIRST"));
        }
        state.put("NEXT-PAGE-NO", false);
        state.put("NEXT-PAGE-YES", true);
        state.put("USRIDINL", -1);
        if (CobolRuntime.toNum(state.get("CDEMO-CU00-PAGE-NUM")) > 1) {
            state.addBranch(26);
            perform(state, "PROCESS-PAGE-BACKWARD");
        } else {
            state.addBranch(-26);
            state.put("WS-MESSAGE", "You are already at the top of the page...");
            state.put("SEND-ERASE-YES", false);
            state.put("SEND-ERASE-NO", true);
            perform(state, "SEND-USRLST-SCREEN");
        }
    }

    void do_PROCESS_PF8_KEY(ProgramState state) {
        if (java.util.List.of(" ", "\u0000").contains(state.get("CDEMO-CU00-USRID-LAST"))) {
            state.addBranch(27);
            state.put("SEC-USR-ID", "\u00FF");
        } else {
            state.addBranch(-27);
            state.put("SEC-USR-ID", state.get("CDEMO-CU00-USRID-LAST"));
        }
        state.put("USRIDINL", -1);
        if (CobolRuntime.isTruthy(state.get("NEXT-PAGE-YES"))) {
            state.addBranch(28);
            perform(state, "PROCESS-PAGE-FORWARD");
        } else {
            state.addBranch(-28);
            state.put("WS-MESSAGE", "You are already at the bottom of the page...");
            state.put("SEND-ERASE-YES", false);
            state.put("SEND-ERASE-NO", true);
            perform(state, "SEND-USRLST-SCREEN");
        }
    }

    void do_PROCESS_PAGE_FORWARD(ProgramState state) {
        perform(state, "STARTBR-USER-SEC-FILE");
        if (!(CobolRuntime.isTruthy(state.get("ERR-FLG-ON")))) {
            state.addBranch(29);
            if (!java.util.List.of("DFHENTER", "DFHPF7", "DFHPF3").contains(state.get("EIBAID"))) {
                state.addBranch(30);
                perform(state, "READNEXT-USER-SEC-FILE");
            } else {
                state.addBranch(-30);
            }
            if ((CobolRuntime.isTruthy(state.get("USER-SEC-NOT-EOF"))) && (CobolRuntime.isTruthy(state.get("ERR-FLG-OFF")))) {
                state.addBranch(31);
                state.put("WS-IDX", CobolRuntime.toNum(1));
                int _lc1 = 0;
                while (!(CobolRuntime.toNum(state.get("WS-IDX")) > 10)) {
                    state.addBranch(32);
                    perform(state, "INITIALIZE-USER-DATA");
                    state.put("WS-IDX", CobolRuntime.toNum(state.get("WS-IDX")) + CobolRuntime.toNum(1));
                    _lc1++;
                    if (_lc1 >= 100) {
                        break;
                    }
                }
                if (_lc1 == 0) {
                    state.addBranch(-32);
                }
            } else {
                state.addBranch(-31);
            }
            state.put("WS-IDX", 1);
            int _lc2 = 0;
            while (!(java.util.List.of(11, state.get("USER-SEC-EOF"), state.get("ERR-FLG-ON")).contains(state.get("WS-IDX")))) {
                state.addBranch(33);
                perform(state, "READNEXT-USER-SEC-FILE");
                if ((CobolRuntime.isTruthy(state.get("USER-SEC-NOT-EOF"))) && (CobolRuntime.isTruthy(state.get("ERR-FLG-OFF")))) {
                    state.addBranch(34);
                    perform(state, "POPULATE-USER-DATA");
                    state.put("WS-IDX", CobolRuntime.toNum(state.get("WS-IDX")) + 1);
                } else {
                    state.addBranch(-34);
                }
                _lc2++;
                if (_lc2 >= 100) {
                    break;
                }
            }
            if (_lc2 == 0) {
                state.addBranch(-33);
            }
            if ((CobolRuntime.isTruthy(state.get("USER-SEC-NOT-EOF"))) && (CobolRuntime.isTruthy(state.get("ERR-FLG-OFF")))) {
                state.addBranch(35);
                state.put("CDEMO-CU00-PAGE-NUM", CobolRuntime.toNum(state.get("CDEMO-CU00-PAGE-NUM")) + 1);
                perform(state, "READNEXT-USER-SEC-FILE");
                if ((CobolRuntime.isTruthy(state.get("USER-SEC-NOT-EOF"))) && (CobolRuntime.isTruthy(state.get("ERR-FLG-OFF")))) {
                    state.addBranch(36);
                    state.put("NEXT-PAGE-NO", false);
                    state.put("NEXT-PAGE-YES", true);
                } else {
                    state.addBranch(-36);
                    state.put("NEXT-PAGE-YES", false);
                    state.put("NEXT-PAGE-NO", true);
                }
            } else {
                state.addBranch(-35);
                state.put("NEXT-PAGE-YES", false);
                state.put("NEXT-PAGE-NO", true);
                if (CobolRuntime.toNum(state.get("WS-IDX")) > 1) {
                    state.addBranch(37);
                    state.put("CDEMO-CU00-PAGE-NUM", CobolRuntime.toNum(state.get("CDEMO-CU00-PAGE-NUM")) + 1);
                } else {
                    state.addBranch(-37);
                }
            }
            perform(state, "ENDBR-USER-SEC-FILE");
            state.put("PAGENUMI", state.get("CDEMO-CU00-PAGE-NUM"));
            state.put("USRIDINO", " ");
            perform(state, "SEND-USRLST-SCREEN");
        } else {
            state.addBranch(-29);
        }
    }

    void do_PROCESS_PAGE_BACKWARD(ProgramState state) {
        perform(state, "STARTBR-USER-SEC-FILE");
        if (!(CobolRuntime.isTruthy(state.get("ERR-FLG-ON")))) {
            state.addBranch(38);
            if (!java.util.List.of("DFHENTER", "DFHPF8").contains(state.get("EIBAID"))) {
                state.addBranch(39);
                perform(state, "READPREV-USER-SEC-FILE");
            } else {
                state.addBranch(-39);
            }
            if ((CobolRuntime.isTruthy(state.get("USER-SEC-NOT-EOF"))) && (CobolRuntime.isTruthy(state.get("ERR-FLG-OFF")))) {
                state.addBranch(40);
                state.put("WS-IDX", CobolRuntime.toNum(1));
                int _lc3 = 0;
                while (!(CobolRuntime.toNum(state.get("WS-IDX")) > 10)) {
                    state.addBranch(41);
                    perform(state, "INITIALIZE-USER-DATA");
                    state.put("WS-IDX", CobolRuntime.toNum(state.get("WS-IDX")) + CobolRuntime.toNum(1));
                    _lc3++;
                    if (_lc3 >= 100) {
                        break;
                    }
                }
                if (_lc3 == 0) {
                    state.addBranch(-41);
                }
            } else {
                state.addBranch(-40);
            }
            state.put("WS-IDX", 10);
            int _lc4 = 0;
            while (!(java.util.List.of(0, state.get("USER-SEC-EOF"), state.get("ERR-FLG-ON")).contains(state.get("WS-IDX")))) {
                state.addBranch(42);
                perform(state, "READPREV-USER-SEC-FILE");
                if ((CobolRuntime.isTruthy(state.get("USER-SEC-NOT-EOF"))) && (CobolRuntime.isTruthy(state.get("ERR-FLG-OFF")))) {
                    state.addBranch(43);
                    perform(state, "POPULATE-USER-DATA");
                    state.put("WS-IDX", CobolRuntime.toNum(state.get("WS-IDX")) - 1);
                } else {
                    state.addBranch(-43);
                }
                _lc4++;
                if (_lc4 >= 100) {
                    break;
                }
            }
            if (_lc4 == 0) {
                state.addBranch(-42);
            }
            if ((CobolRuntime.isTruthy(state.get("USER-SEC-NOT-EOF"))) && (CobolRuntime.isTruthy(state.get("ERR-FLG-OFF")))) {
                state.addBranch(44);
                perform(state, "READPREV-USER-SEC-FILE");
                if (CobolRuntime.isTruthy(state.get("NEXT-PAGE-YES"))) {
                    state.addBranch(45);
                    if (((CobolRuntime.isTruthy(state.get("USER-SEC-NOT-EOF"))) && (CobolRuntime.isTruthy(state.get("ERR-FLG-OFF")))) && (CobolRuntime.toNum(state.get("CDEMO-CU00-PAGE-NUM")) > 1)) {
                        state.addBranch(46);
                        state.put("CDEMO-CU00-PAGE-NUM", CobolRuntime.toNum(state.get("CDEMO-CU00-PAGE-NUM")) - 1);
                    } else {
                        state.addBranch(-46);
                        state.put("CDEMO-CU00-PAGE-NUM", 1);
                    }
                } else {
                    state.addBranch(-45);
                }
            } else {
                state.addBranch(-44);
            }
            perform(state, "ENDBR-USER-SEC-FILE");
            state.put("PAGENUMI", state.get("CDEMO-CU00-PAGE-NUM"));
            perform(state, "SEND-USRLST-SCREEN");
        } else {
            state.addBranch(-38);
        }
    }

    void do_POPULATE_USER_DATA(ProgramState state) {
        Object _evalSubject4 = state.get("WS-IDX");
        _evalSubject4 = CobolRuntime.toNum(_evalSubject4);
        if ((java.util.Objects.equals(_evalSubject4, CobolRuntime.toNum(1)))) {
            state.addBranch(47);
            state.put("USRID01I", state.get("SEC-USR-ID"));
            state.put("CDEMO-CU00-USRID-FIRST", state.get("SEC-USR-ID"));
            state.put("FNAME01I", state.get("SEC-USR-FNAME"));
            state.put("LNAME01I", state.get("SEC-USR-LNAME"));
            state.put("UTYPE01I", state.get("SEC-USR-TYPE"));
        }
        else if ((java.util.Objects.equals(_evalSubject4, CobolRuntime.toNum(2)))) {
            state.addBranch(48);
            state.put("USRID02I", state.get("SEC-USR-ID"));
            state.put("FNAME02I", state.get("SEC-USR-FNAME"));
            state.put("LNAME02I", state.get("SEC-USR-LNAME"));
            state.put("UTYPE02I", state.get("SEC-USR-TYPE"));
        }
        else if ((java.util.Objects.equals(_evalSubject4, CobolRuntime.toNum(3)))) {
            state.addBranch(49);
            state.put("USRID03I", state.get("SEC-USR-ID"));
            state.put("FNAME03I", state.get("SEC-USR-FNAME"));
            state.put("LNAME03I", state.get("SEC-USR-LNAME"));
            state.put("UTYPE03I", state.get("SEC-USR-TYPE"));
        }
        else if ((java.util.Objects.equals(_evalSubject4, CobolRuntime.toNum(4)))) {
            state.addBranch(50);
            state.put("USRID04I", state.get("SEC-USR-ID"));
            state.put("FNAME04I", state.get("SEC-USR-FNAME"));
            state.put("LNAME04I", state.get("SEC-USR-LNAME"));
            state.put("UTYPE04I", state.get("SEC-USR-TYPE"));
        }
        else if ((java.util.Objects.equals(_evalSubject4, CobolRuntime.toNum(5)))) {
            state.addBranch(51);
            state.put("USRID05I", state.get("SEC-USR-ID"));
            state.put("FNAME05I", state.get("SEC-USR-FNAME"));
            state.put("LNAME05I", state.get("SEC-USR-LNAME"));
            state.put("UTYPE05I", state.get("SEC-USR-TYPE"));
        }
        else if ((java.util.Objects.equals(_evalSubject4, CobolRuntime.toNum(6)))) {
            state.addBranch(52);
            state.put("USRID06I", state.get("SEC-USR-ID"));
            state.put("FNAME06I", state.get("SEC-USR-FNAME"));
            state.put("LNAME06I", state.get("SEC-USR-LNAME"));
            state.put("UTYPE06I", state.get("SEC-USR-TYPE"));
        }
        else if ((java.util.Objects.equals(_evalSubject4, CobolRuntime.toNum(7)))) {
            state.addBranch(53);
            state.put("USRID07I", state.get("SEC-USR-ID"));
            state.put("FNAME07I", state.get("SEC-USR-FNAME"));
            state.put("LNAME07I", state.get("SEC-USR-LNAME"));
            state.put("UTYPE07I", state.get("SEC-USR-TYPE"));
        }
        else if ((java.util.Objects.equals(_evalSubject4, CobolRuntime.toNum(8)))) {
            state.addBranch(54);
            state.put("USRID08I", state.get("SEC-USR-ID"));
            state.put("FNAME08I", state.get("SEC-USR-FNAME"));
            state.put("LNAME08I", state.get("SEC-USR-LNAME"));
            state.put("UTYPE08I", state.get("SEC-USR-TYPE"));
        }
        else if ((java.util.Objects.equals(_evalSubject4, CobolRuntime.toNum(9)))) {
            state.addBranch(55);
            state.put("USRID09I", state.get("SEC-USR-ID"));
            state.put("FNAME09I", state.get("SEC-USR-FNAME"));
            state.put("LNAME09I", state.get("SEC-USR-LNAME"));
            state.put("UTYPE09I", state.get("SEC-USR-TYPE"));
        }
        else if ((java.util.Objects.equals(_evalSubject4, CobolRuntime.toNum(10)))) {
            state.addBranch(56);
            state.put("USRID10I", state.get("SEC-USR-ID"));
            state.put("CDEMO-CU00-USRID-LAST", state.get("SEC-USR-ID"));
            state.put("FNAME10I", state.get("SEC-USR-FNAME"));
            state.put("LNAME10I", state.get("SEC-USR-LNAME"));
            state.put("UTYPE10I", state.get("SEC-USR-TYPE"));
        }
        else {
            state.addBranch(57);
            // CONTINUE
        }
    }

    void do_INITIALIZE_USER_DATA(ProgramState state) {
        Object _evalSubject5 = state.get("WS-IDX");
        _evalSubject5 = CobolRuntime.toNum(_evalSubject5);
        if ((java.util.Objects.equals(_evalSubject5, CobolRuntime.toNum(1)))) {
            state.addBranch(58);
            state.put("USRID01I", " ");
            state.put("FNAME01I", " ");
            state.put("LNAME01I", " ");
            state.put("UTYPE01I", " ");
        }
        else if ((java.util.Objects.equals(_evalSubject5, CobolRuntime.toNum(2)))) {
            state.addBranch(59);
            state.put("USRID02I", " ");
            state.put("FNAME02I", " ");
            state.put("LNAME02I", " ");
            state.put("UTYPE02I", " ");
        }
        else if ((java.util.Objects.equals(_evalSubject5, CobolRuntime.toNum(3)))) {
            state.addBranch(60);
            state.put("USRID03I", " ");
            state.put("FNAME03I", " ");
            state.put("LNAME03I", " ");
            state.put("UTYPE03I", " ");
        }
        else if ((java.util.Objects.equals(_evalSubject5, CobolRuntime.toNum(4)))) {
            state.addBranch(61);
            state.put("USRID04I", " ");
            state.put("FNAME04I", " ");
            state.put("LNAME04I", " ");
            state.put("UTYPE04I", " ");
        }
        else if ((java.util.Objects.equals(_evalSubject5, CobolRuntime.toNum(5)))) {
            state.addBranch(62);
            state.put("USRID05I", " ");
            state.put("FNAME05I", " ");
            state.put("LNAME05I", " ");
            state.put("UTYPE05I", " ");
        }
        else if ((java.util.Objects.equals(_evalSubject5, CobolRuntime.toNum(6)))) {
            state.addBranch(63);
            state.put("USRID06I", " ");
            state.put("FNAME06I", " ");
            state.put("LNAME06I", " ");
            state.put("UTYPE06I", " ");
        }
        else if ((java.util.Objects.equals(_evalSubject5, CobolRuntime.toNum(7)))) {
            state.addBranch(64);
            state.put("USRID07I", " ");
            state.put("FNAME07I", " ");
            state.put("LNAME07I", " ");
            state.put("UTYPE07I", " ");
        }
        else if ((java.util.Objects.equals(_evalSubject5, CobolRuntime.toNum(8)))) {
            state.addBranch(65);
            state.put("USRID08I", " ");
            state.put("FNAME08I", " ");
            state.put("LNAME08I", " ");
            state.put("UTYPE08I", " ");
        }
        else if ((java.util.Objects.equals(_evalSubject5, CobolRuntime.toNum(9)))) {
            state.addBranch(66);
            state.put("USRID09I", " ");
            state.put("FNAME09I", " ");
            state.put("LNAME09I", " ");
            state.put("UTYPE09I", " ");
        }
        else if ((java.util.Objects.equals(_evalSubject5, CobolRuntime.toNum(10)))) {
            state.addBranch(67);
            state.put("USRID10I", " ");
            state.put("FNAME10I", " ");
            state.put("LNAME10I", " ");
            state.put("UTYPE10I", " ");
        }
        else {
            state.addBranch(68);
            // CONTINUE
        }
    }

    void do_RETURN_TO_PREV_SCREEN(ProgramState state) {
        if (java.util.List.of("\u0000", " ").contains(state.get("CDEMO-TO-PROGRAM"))) {
            state.addBranch(69);
            state.put("CDEMO-TO-PROGRAM", "COSGN00C");
        } else {
            state.addBranch(-69);
        }
        state.put("CDEMO-FROM-TRANID", state.get("WS-TRANID"));
        state.put("CDEMO-FROM-PROGRAM", state.get("WS-PGMNAME"));
        state.put("CDEMO-PGM-CONTEXT", 0);
        stubs.dummyExec(state, "CICS", "EXEC CICS XCTL PROGRAM(CDEMO-TO-PROGRAM) COMMAREA(CARDDEMO-COMMAREA) END-EXEC");
    }

    void do_SEND_USRLST_SCREEN(ProgramState state) {
        perform(state, "POPULATE-HEADER-INFO");
        state.put("ERRMSGO", state.get("WS-MESSAGE"));
        if (CobolRuntime.isTruthy(state.get("SEND-ERASE-YES"))) {
            state.addBranch(70);
            stubs.dummyExec(state, "CICS", "EXEC CICS SEND MAP('COUSR0A') MAPSET('COUSR00') FROM(COUSR0AO) ERASE CURSOR END-EXEC");
        } else {
            state.addBranch(-70);
            stubs.dummyExec(state, "CICS", "EXEC CICS SEND MAP('COUSR0A') MAPSET('COUSR00') FROM(COUSR0AO) *>                   ERASE CURSOR END-EXEC");
        }
    }

    void do_RECEIVE_USRLST_SCREEN(ProgramState state) {
        stubs.dummyExec(state, "CICS", "EXEC CICS RECEIVE MAP('COUSR0A') MAPSET('COUSR00') INTO(COUSR0AI) RESP(WS-RESP-CD) RESP2(WS-REAS-CD) END-EXEC");
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

    void do_STARTBR_USER_SEC_FILE(ProgramState state) {
        stubs.dummyExec(state, "CICS", "EXEC CICS STARTBR DATASET   (WS-USRSEC-FILE) RIDFLD    (SEC-USR-ID) KEYLENGTH (LENGTH OF SEC-USR-ID) *>          GTEQ RESP      (WS-RESP-CD) RESP2     (WS-REAS-CD) END-EXEC");
        Object _evalSubject6 = state.get("WS-RESP-CD");
        if ((java.util.Objects.equals(_evalSubject6, 0))) {
            state.addBranch(71);
            // CONTINUE
        }
        else if ((java.util.Objects.equals(_evalSubject6, 13))) {
            state.addBranch(72);
            // CONTINUE
            state.put("USER-SEC-NOT-EOF", false);
            state.put("USER-SEC-EOF", true);
            state.put("WS-MESSAGE", "You are at the top of the page...");
            state.put("USRIDINL", -1);
            perform(state, "SEND-USRLST-SCREEN");
        }
        else {
            state.addBranch(73);
            display(state, "RESP:", String.valueOf(state.get("WS-RESP-CD")), "REAS:", String.valueOf(state.get("WS-REAS-CD")));
            state.put("WS-ERR-FLG", "Y");
            state.put("WS-MESSAGE", "Unable to lookup User...");
            state.put("USRIDINL", -1);
            perform(state, "SEND-USRLST-SCREEN");
        }
    }

    void do_READNEXT_USER_SEC_FILE(ProgramState state) {
        stubs.cicsRead(state, "WS-USRSEC-FILE", "SEC-USR-ID", "SEC-USER-DATA", "WS-RESP-CD", "WS-REAS-CD");
        Object _evalSubject7 = state.get("WS-RESP-CD");
        if ((java.util.Objects.equals(_evalSubject7, 0))) {
            state.addBranch(74);
            // CONTINUE
        }
        else if ((java.util.Objects.equals(_evalSubject7, 20))) {
            state.addBranch(75);
            // CONTINUE
            state.put("USER-SEC-NOT-EOF", false);
            state.put("USER-SEC-EOF", true);
            state.put("WS-MESSAGE", "You have reached the bottom of the page...");
            state.put("USRIDINL", -1);
            perform(state, "SEND-USRLST-SCREEN");
        }
        else {
            state.addBranch(76);
            display(state, "RESP:", String.valueOf(state.get("WS-RESP-CD")), "REAS:", String.valueOf(state.get("WS-REAS-CD")));
            state.put("WS-ERR-FLG", "Y");
            state.put("WS-MESSAGE", "Unable to lookup User...");
            state.put("USRIDINL", -1);
            perform(state, "SEND-USRLST-SCREEN");
        }
    }

    void do_READPREV_USER_SEC_FILE(ProgramState state) {
        stubs.cicsRead(state, "WS-USRSEC-FILE", "SEC-USR-ID", "SEC-USER-DATA", "WS-RESP-CD", "WS-REAS-CD");
        Object _evalSubject8 = state.get("WS-RESP-CD");
        if ((java.util.Objects.equals(_evalSubject8, 0))) {
            state.addBranch(77);
            // CONTINUE
        }
        else if ((java.util.Objects.equals(_evalSubject8, 20))) {
            state.addBranch(78);
            // CONTINUE
            state.put("USER-SEC-NOT-EOF", false);
            state.put("USER-SEC-EOF", true);
            state.put("WS-MESSAGE", "You have reached the top of the page...");
            state.put("USRIDINL", -1);
            perform(state, "SEND-USRLST-SCREEN");
        }
        else {
            state.addBranch(79);
            display(state, "RESP:", String.valueOf(state.get("WS-RESP-CD")), "REAS:", String.valueOf(state.get("WS-REAS-CD")));
            state.put("WS-ERR-FLG", "Y");
            state.put("WS-MESSAGE", "Unable to lookup User...");
            state.put("USRIDINL", -1);
            perform(state, "SEND-USRLST-SCREEN");
        }
    }

    void do_ENDBR_USER_SEC_FILE(ProgramState state) {
        stubs.dummyExec(state, "CICS", "EXEC CICS ENDBR DATASET   (WS-USRSEC-FILE) END-EXEC");
    }

}
