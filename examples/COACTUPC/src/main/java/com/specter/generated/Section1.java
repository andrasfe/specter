package com.specter.generated;

/**
 * Generated section: Section1.
 */
public class Section1 extends SectionBase {

    public Section1(ParagraphRegistry registry, StubExecutor stubs) {
        super(registry, stubs);
        paragraph("1000-PROCESS-INPUTS", this::do_1000_PROCESS_INPUTS);
        paragraph("1000-PROCESS-INPUTS-EXIT", this::do_1000_PROCESS_INPUTS_EXIT);
        paragraph("1100-RECEIVE-MAP", this::do_1100_RECEIVE_MAP);
        paragraph("1100-RECEIVE-MAP-EXIT", this::do_1100_RECEIVE_MAP_EXIT);
        paragraph("1200-EDIT-MAP-INPUTS", this::do_1200_EDIT_MAP_INPUTS);
        paragraph("1200-EDIT-MAP-INPUTS-EXIT", this::do_1200_EDIT_MAP_INPUTS_EXIT);
        paragraph("1205-COMPARE-OLD-NEW", this::do_1205_COMPARE_OLD_NEW);
        paragraph("1205-COMPARE-OLD-NEW-EXIT", this::do_1205_COMPARE_OLD_NEW_EXIT);
        paragraph("1210-EDIT-ACCOUNT", this::do_1210_EDIT_ACCOUNT);
        paragraph("1210-EDIT-ACCOUNT-EXIT", this::do_1210_EDIT_ACCOUNT_EXIT);
        paragraph("1215-EDIT-MANDATORY", this::do_1215_EDIT_MANDATORY);
        paragraph("1215-EDIT-MANDATORY-EXIT", this::do_1215_EDIT_MANDATORY_EXIT);
        paragraph("1220-EDIT-YESNO", this::do_1220_EDIT_YESNO);
        paragraph("1220-EDIT-YESNO-EXIT", this::do_1220_EDIT_YESNO_EXIT);
        paragraph("1225-EDIT-ALPHA-REQD", this::do_1225_EDIT_ALPHA_REQD);
        paragraph("1225-EDIT-ALPHA-REQD-EXIT", this::do_1225_EDIT_ALPHA_REQD_EXIT);
        paragraph("1230-EDIT-ALPHANUM-REQD", this::do_1230_EDIT_ALPHANUM_REQD);
        paragraph("1230-EDIT-ALPHANUM-REQD-EXIT", this::do_1230_EDIT_ALPHANUM_REQD_EXIT);
        paragraph("1235-EDIT-ALPHA-OPT", this::do_1235_EDIT_ALPHA_OPT);
        paragraph("1235-EDIT-ALPHA-OPT-EXIT", this::do_1235_EDIT_ALPHA_OPT_EXIT);
        paragraph("1240-EDIT-ALPHANUM-OPT", this::do_1240_EDIT_ALPHANUM_OPT);
        paragraph("1240-EDIT-ALPHANUM-OPT-EXIT", this::do_1240_EDIT_ALPHANUM_OPT_EXIT);
        paragraph("1245-EDIT-NUM-REQD", this::do_1245_EDIT_NUM_REQD);
        paragraph("1245-EDIT-NUM-REQD-EXIT", this::do_1245_EDIT_NUM_REQD_EXIT);
        paragraph("1250-EDIT-SIGNED-9V2", this::do_1250_EDIT_SIGNED_9V2);
        paragraph("1250-EDIT-SIGNED-9V2-EXIT", this::do_1250_EDIT_SIGNED_9V2_EXIT);
        paragraph("1260-EDIT-US-PHONE-NUM", this::do_1260_EDIT_US_PHONE_NUM);
        paragraph("1260-EDIT-US-PHONE-NUM-EXIT", this::do_1260_EDIT_US_PHONE_NUM_EXIT);
        paragraph("1265-EDIT-US-SSN", this::do_1265_EDIT_US_SSN);
        paragraph("1265-EDIT-US-SSN-EXIT", this::do_1265_EDIT_US_SSN_EXIT);
        paragraph("1270-EDIT-US-STATE-CD", this::do_1270_EDIT_US_STATE_CD);
        paragraph("1270-EDIT-US-STATE-CD-EXIT", this::do_1270_EDIT_US_STATE_CD_EXIT);
        paragraph("1275-EDIT-FICO-SCORE", this::do_1275_EDIT_FICO_SCORE);
        paragraph("1275-EDIT-FICO-SCORE-EXIT", this::do_1275_EDIT_FICO_SCORE_EXIT);
        paragraph("1280-EDIT-US-STATE-ZIP-CD", this::do_1280_EDIT_US_STATE_ZIP_CD);
        paragraph("1280-EDIT-US-STATE-ZIP-CD-EXIT", this::do_1280_EDIT_US_STATE_ZIP_CD_EXIT);
    }

    void do_1000_PROCESS_INPUTS(ProgramState state) {
        performThru(state, "1100-RECEIVE-MAP", "1100-RECEIVE-MAP-EXIT");
        performThru(state, "1200-EDIT-MAP-INPUTS", "1200-EDIT-MAP-INPUTS-EXIT");
        state.put("CCARD-ERROR-MSG", state.get("WS-RETURN-MSG"));
        state.put("CCARD-NEXT-PROG", state.get("LIT-THISPGM"));
        state.put("CCARD-NEXT-MAPSET", state.get("LIT-THISMAPSET"));
        state.put("CCARD-NEXT-MAP", state.get("LIT-THISMAP"));
    }

    void do_1000_PROCESS_INPUTS_EXIT(ProgramState state) {
        // EXIT
    }

    void do_1100_RECEIVE_MAP(ProgramState state) {
        stubs.dummyExec(state, "CICS", "EXEC CICS RECEIVE MAP(LIT-THISMAP) MAPSET(LIT-THISMAPSET) INTO(CACTUPAI) RESP(WS-RESP-CD) RESP2(WS-REAS-CD) END-EXEC");
        state.put("ACUP-NEW-DETAILS", state.get("ACUP-NEW-DETAILS") instanceof Number ? 0 : "");
        if ((java.util.Objects.equals(state.get("ACCTSIDI"), "*")) || (java.util.Objects.equals(state.get("ACCTSIDI"), " "))) {
            state.addBranch(31);
            state.put("CC-ACCT-ID", "\u0000");
        } else {
            state.addBranch(-31);
            state.put("CC-ACCT-ID", state.get("ACCTSIDI"));
        }
        if (CobolRuntime.isTruthy(state.get("ACUP-DETAILS-NOT-FETCHED"))) {
            state.addBranch(32);
            registry.get("1100-RECEIVE-MAP-EXIT").execute(state);
            return;
        } else {
            state.addBranch(-32);
        }
        if ((java.util.Objects.equals(state.get("ACSTTUSI"), "*")) || (java.util.Objects.equals(state.get("ACSTTUSI"), " "))) {
            state.addBranch(33);
            state.put("ACUP-NEW-ACTIVE-STATUS", "\u0000");
        } else {
            state.addBranch(-33);
            state.put("ACUP-NEW-ACTIVE-STATUS", state.get("ACSTTUSI"));
        }
        if ((java.util.Objects.equals(state.get("ACRDLIMI"), "*")) || (java.util.Objects.equals(state.get("ACRDLIMI"), " "))) {
            state.addBranch(34);
            state.put("ACUP-NEW-CREDIT-LIMIT-X", "\u0000");
        } else {
            state.addBranch(-34);
            state.put("ACUP-NEW-CREDIT-LIMIT-X", state.get("ACRDLIMI"));
            if (CobolRuntime.isTruthy(state.get("FUNCTION"))) {
                state.addBranch(35);
                state.put("ACUP-NEW-CREDIT-LIMIT-N", CobolRuntime.toNum(state.get("ACRDLIMI")));
            } else {
                state.addBranch(-35);
                // CONTINUE
            }
        }
        if ((java.util.Objects.equals(state.get("ACSHLIMI"), "*")) || (java.util.Objects.equals(state.get("ACSHLIMI"), " "))) {
            state.addBranch(36);
            state.put("ACUP-NEW-CASH-CREDIT-LIMIT-X", "\u0000");
        } else {
            state.addBranch(-36);
            state.put("ACUP-NEW-CASH-CREDIT-LIMIT-X", state.get("ACSHLIMI"));
            if (CobolRuntime.isTruthy(state.get("FUNCTION"))) {
                state.addBranch(37);
                state.put("ACUP-NEW-CASH-CREDIT-LIMIT-N", CobolRuntime.toNum(state.get("ACSHLIMI")));
            } else {
                state.addBranch(-37);
                // CONTINUE
            }
        }
        if ((java.util.Objects.equals(state.get("ACURBALI"), "*")) || (java.util.Objects.equals(state.get("ACURBALI"), " "))) {
            state.addBranch(38);
            state.put("ACUP-NEW-CURR-BAL-X", "\u0000");
        } else {
            state.addBranch(-38);
            state.put("ACUP-NEW-CURR-BAL-X", state.get("ACURBALI"));
            if (CobolRuntime.isTruthy(state.get("FUNCTION"))) {
                state.addBranch(39);
                state.put("ACUP-NEW-CURR-BAL-N", CobolRuntime.toNum(state.get("ACUP-NEW-CURR-BAL-X")));
            } else {
                state.addBranch(-39);
                // CONTINUE
            }
        }
        if ((java.util.Objects.equals(state.get("ACRCYCRI"), "*")) || (java.util.Objects.equals(state.get("ACRCYCRI"), " "))) {
            state.addBranch(40);
            state.put("ACUP-NEW-CURR-CYC-CREDIT-X", "\u0000");
        } else {
            state.addBranch(-40);
            state.put("ACUP-NEW-CURR-CYC-CREDIT-X", state.get("ACRCYCRI"));
            if (CobolRuntime.isTruthy(state.get("FUNCTION"))) {
                state.addBranch(41);
                state.put("ACUP-NEW-CURR-CYC-CREDIT-N", CobolRuntime.toNum(state.get("ACRCYCRI")));
            } else {
                state.addBranch(-41);
                // CONTINUE
            }
        }
        if ((java.util.Objects.equals(state.get("ACRCYDBI"), "*")) || (java.util.Objects.equals(state.get("ACRCYDBI"), " "))) {
            state.addBranch(42);
            state.put("ACUP-NEW-CURR-CYC-DEBIT-X", "\u0000");
        } else {
            state.addBranch(-42);
            state.put("ACUP-NEW-CURR-CYC-DEBIT-X", state.get("ACRCYDBI"));
            if (CobolRuntime.isTruthy(state.get("FUNCTION"))) {
                state.addBranch(43);
                state.put("ACUP-NEW-CURR-CYC-DEBIT-N", CobolRuntime.toNum(state.get("ACRCYDBI")));
            } else {
                state.addBranch(-43);
                // CONTINUE
            }
        }
        if ((java.util.Objects.equals(state.get("OPNYEARI"), "*")) || (java.util.Objects.equals(state.get("OPNYEARI"), " "))) {
            state.addBranch(44);
            state.put("ACUP-NEW-OPEN-YEAR", "\u0000");
        } else {
            state.addBranch(-44);
            state.put("ACUP-NEW-OPEN-YEAR", state.get("OPNYEARI"));
        }
        if ((java.util.Objects.equals(state.get("OPNMONI"), "*")) || (java.util.Objects.equals(state.get("OPNMONI"), " "))) {
            state.addBranch(45);
            state.put("ACUP-NEW-OPEN-MON", "\u0000");
        } else {
            state.addBranch(-45);
            state.put("ACUP-NEW-OPEN-MON", state.get("OPNMONI"));
        }
        if ((java.util.Objects.equals(state.get("OPNDAYI"), "*")) || (java.util.Objects.equals(state.get("OPNDAYI"), " "))) {
            state.addBranch(46);
            state.put("ACUP-NEW-OPEN-DAY", "\u0000");
        } else {
            state.addBranch(-46);
            state.put("ACUP-NEW-OPEN-DAY", state.get("OPNDAYI"));
        }
        if ((java.util.Objects.equals(state.get("EXPYEARI"), "*")) || (java.util.Objects.equals(state.get("EXPYEARI"), " "))) {
            state.addBranch(47);
            state.put("ACUP-NEW-EXP-YEAR", "\u0000");
        } else {
            state.addBranch(-47);
            state.put("ACUP-NEW-EXP-YEAR", state.get("EXPYEARI"));
        }
        if ((java.util.Objects.equals(state.get("EXPMONI"), "*")) || (java.util.Objects.equals(state.get("EXPMONI"), " "))) {
            state.addBranch(48);
            state.put("ACUP-NEW-EXP-MON", "\u0000");
        } else {
            state.addBranch(-48);
            state.put("ACUP-NEW-EXP-MON", state.get("EXPMONI"));
        }
        if ((java.util.Objects.equals(state.get("EXPDAYI"), "*")) || (java.util.Objects.equals(state.get("EXPDAYI"), " "))) {
            state.addBranch(49);
            state.put("ACUP-NEW-EXP-DAY", "\u0000");
        } else {
            state.addBranch(-49);
            state.put("ACUP-NEW-EXP-DAY", state.get("EXPDAYI"));
        }
        if ((java.util.Objects.equals(state.get("RISYEARI"), "*")) || (java.util.Objects.equals(state.get("RISYEARI"), " "))) {
            state.addBranch(50);
            state.put("ACUP-NEW-REISSUE-YEAR", "\u0000");
        } else {
            state.addBranch(-50);
            state.put("ACUP-NEW-REISSUE-YEAR", state.get("RISYEARI"));
        }
        if ((java.util.Objects.equals(state.get("RISMONI"), "*")) || (java.util.Objects.equals(state.get("RISMONI"), " "))) {
            state.addBranch(51);
            state.put("ACUP-NEW-REISSUE-MON", "\u0000");
        } else {
            state.addBranch(-51);
            state.put("ACUP-NEW-REISSUE-MON", state.get("RISMONI"));
        }
        if ((java.util.Objects.equals(state.get("RISDAYI"), "*")) || (java.util.Objects.equals(state.get("RISDAYI"), " "))) {
            state.addBranch(52);
            state.put("ACUP-NEW-REISSUE-DAY", "\u0000");
        } else {
            state.addBranch(-52);
            state.put("ACUP-NEW-REISSUE-DAY", state.get("RISDAYI"));
        }
        if ((java.util.Objects.equals(state.get("AADDGRPI"), "*")) || (java.util.Objects.equals(state.get("AADDGRPI"), " "))) {
            state.addBranch(53);
            state.put("ACUP-NEW-GROUP-ID", "\u0000");
        } else {
            state.addBranch(-53);
            state.put("ACUP-NEW-GROUP-ID", state.get("AADDGRPI"));
        }
        if ((java.util.Objects.equals(state.get("ACSTNUMI"), "*")) || (java.util.Objects.equals(state.get("ACSTNUMI"), " "))) {
            state.addBranch(54);
            state.put("ACUP-NEW-CUST-ID-X", "\u0000");
        } else {
            state.addBranch(-54);
            state.put("ACUP-NEW-CUST-ID-X", state.get("ACSTNUMI"));
        }
        if ((java.util.Objects.equals(state.get("ACTSSN1I"), "*")) || (java.util.Objects.equals(state.get("ACTSSN1I"), " "))) {
            state.addBranch(55);
            state.put("ACUP-NEW-CUST-SSN-1", "\u0000");
        } else {
            state.addBranch(-55);
            state.put("ACUP-NEW-CUST-SSN-1", state.get("ACTSSN1I"));
        }
        if ((java.util.Objects.equals(state.get("ACTSSN2I"), "*")) || (java.util.Objects.equals(state.get("ACTSSN2I"), " "))) {
            state.addBranch(56);
            state.put("ACUP-NEW-CUST-SSN-2", "\u0000");
        } else {
            state.addBranch(-56);
            state.put("ACUP-NEW-CUST-SSN-2", state.get("ACTSSN2I"));
        }
        if ((java.util.Objects.equals(state.get("ACTSSN3I"), "*")) || (java.util.Objects.equals(state.get("ACTSSN3I"), " "))) {
            state.addBranch(57);
            state.put("ACUP-NEW-CUST-SSN-3", "\u0000");
        } else {
            state.addBranch(-57);
            state.put("ACUP-NEW-CUST-SSN-3", state.get("ACTSSN3I"));
        }
        if ((java.util.Objects.equals(state.get("DOBYEARI"), "*")) || (java.util.Objects.equals(state.get("DOBYEARI"), " "))) {
            state.addBranch(58);
            state.put("ACUP-NEW-CUST-DOB-YEAR", "\u0000");
        } else {
            state.addBranch(-58);
            state.put("ACUP-NEW-CUST-DOB-YEAR", state.get("DOBYEARI"));
        }
        if ((java.util.Objects.equals(state.get("DOBMONI"), "*")) || (java.util.Objects.equals(state.get("DOBMONI"), " "))) {
            state.addBranch(59);
            state.put("ACUP-NEW-CUST-DOB-MON", "\u0000");
        } else {
            state.addBranch(-59);
            state.put("ACUP-NEW-CUST-DOB-MON", state.get("DOBMONI"));
        }
        if ((java.util.Objects.equals(state.get("DOBDAYI"), "*")) || (java.util.Objects.equals(state.get("DOBDAYI"), " "))) {
            state.addBranch(60);
            state.put("ACUP-NEW-CUST-DOB-DAY", "\u0000");
        } else {
            state.addBranch(-60);
            state.put("ACUP-NEW-CUST-DOB-DAY", state.get("DOBDAYI"));
        }
        if ((java.util.Objects.equals(state.get("ACSTFCOI"), "*")) || (java.util.Objects.equals(state.get("ACSTFCOI"), " "))) {
            state.addBranch(61);
            state.put("ACUP-NEW-CUST-FICO-SCORE-X", "\u0000");
        } else {
            state.addBranch(-61);
            state.put("ACUP-NEW-CUST-FICO-SCORE-X", state.get("ACSTFCOI"));
        }
        if ((java.util.Objects.equals(state.get("ACSFNAMI"), "*")) || (java.util.Objects.equals(state.get("ACSFNAMI"), " "))) {
            state.addBranch(62);
            state.put("ACUP-NEW-CUST-FIRST-NAME", "\u0000");
        } else {
            state.addBranch(-62);
            state.put("ACUP-NEW-CUST-FIRST-NAME", state.get("ACSFNAMI"));
        }
        if ((java.util.Objects.equals(state.get("ACSMNAMI"), "*")) || (java.util.Objects.equals(state.get("ACSMNAMI"), " "))) {
            state.addBranch(63);
            state.put("ACUP-NEW-CUST-MIDDLE-NAME", "\u0000");
        } else {
            state.addBranch(-63);
            state.put("ACUP-NEW-CUST-MIDDLE-NAME", state.get("ACSMNAMI"));
        }
        if ((java.util.Objects.equals(state.get("ACSLNAMI"), "*")) || (java.util.Objects.equals(state.get("ACSLNAMI"), " "))) {
            state.addBranch(64);
            state.put("ACUP-NEW-CUST-LAST-NAME", "\u0000");
        } else {
            state.addBranch(-64);
            state.put("ACUP-NEW-CUST-LAST-NAME", state.get("ACSLNAMI"));
        }
        if ((java.util.Objects.equals(state.get("ACSADL1I"), "*")) || (java.util.Objects.equals(state.get("ACSADL1I"), " "))) {
            state.addBranch(65);
            state.put("ACUP-NEW-CUST-ADDR-LINE-1", "\u0000");
        } else {
            state.addBranch(-65);
            state.put("ACUP-NEW-CUST-ADDR-LINE-1", state.get("ACSADL1I"));
        }
        if ((java.util.Objects.equals(state.get("ACSADL2I"), "*")) || (java.util.Objects.equals(state.get("ACSADL2I"), " "))) {
            state.addBranch(66);
            state.put("ACUP-NEW-CUST-ADDR-LINE-2", "\u0000");
        } else {
            state.addBranch(-66);
            state.put("ACUP-NEW-CUST-ADDR-LINE-2", state.get("ACSADL2I"));
        }
        if ((java.util.Objects.equals(state.get("ACSCITYI"), "*")) || (java.util.Objects.equals(state.get("ACSCITYI"), " "))) {
            state.addBranch(67);
            state.put("ACUP-NEW-CUST-ADDR-LINE-3", "\u0000");
        } else {
            state.addBranch(-67);
            state.put("ACUP-NEW-CUST-ADDR-LINE-3", state.get("ACSCITYI"));
        }
        if ((java.util.Objects.equals(state.get("ACSSTTEI"), "*")) || (java.util.Objects.equals(state.get("ACSSTTEI"), " "))) {
            state.addBranch(68);
            state.put("ACUP-NEW-CUST-ADDR-STATE-CD", "\u0000");
        } else {
            state.addBranch(-68);
            state.put("ACUP-NEW-CUST-ADDR-STATE-CD", state.get("ACSSTTEI"));
        }
        if ((java.util.Objects.equals(state.get("ACSCTRYI"), "*")) || (java.util.Objects.equals(state.get("ACSCTRYI"), " "))) {
            state.addBranch(69);
            state.put("ACUP-NEW-CUST-ADDR-COUNTRY-CD", "\u0000");
        } else {
            state.addBranch(-69);
            state.put("ACUP-NEW-CUST-ADDR-COUNTRY-CD", state.get("ACSCTRYI"));
        }
        if ((java.util.Objects.equals(state.get("ACSZIPCI"), "*")) || (java.util.Objects.equals(state.get("ACSZIPCI"), " "))) {
            state.addBranch(70);
            state.put("ACUP-NEW-CUST-ADDR-ZIP", "\u0000");
        } else {
            state.addBranch(-70);
            state.put("ACUP-NEW-CUST-ADDR-ZIP", state.get("ACSZIPCI"));
        }
        if ((java.util.Objects.equals(state.get("ACSPH1AI"), "*")) || (java.util.Objects.equals(state.get("ACSPH1AI"), " "))) {
            state.addBranch(71);
            state.put("ACUP-NEW-CUST-PHONE-NUM-1A", "\u0000");
        } else {
            state.addBranch(-71);
            state.put("ACUP-NEW-CUST-PHONE-NUM-1A", state.get("ACSPH1AI"));
        }
        if ((java.util.Objects.equals(state.get("ACSPH1BI"), "*")) || (java.util.Objects.equals(state.get("ACSPH1BI"), " "))) {
            state.addBranch(72);
            state.put("ACUP-NEW-CUST-PHONE-NUM-1B", "\u0000");
        } else {
            state.addBranch(-72);
            state.put("ACUP-NEW-CUST-PHONE-NUM-1B", state.get("ACSPH1BI"));
        }
        if ((java.util.Objects.equals(state.get("ACSPH1CI"), "*")) || (java.util.Objects.equals(state.get("ACSPH1CI"), " "))) {
            state.addBranch(73);
            state.put("ACUP-NEW-CUST-PHONE-NUM-1C", "\u0000");
        } else {
            state.addBranch(-73);
            state.put("ACUP-NEW-CUST-PHONE-NUM-1C", state.get("ACSPH1CI"));
        }
        if ((java.util.Objects.equals(state.get("ACSPH2AI"), "*")) || (java.util.Objects.equals(state.get("ACSPH2AI"), " "))) {
            state.addBranch(74);
            state.put("ACUP-NEW-CUST-PHONE-NUM-2A", "\u0000");
        } else {
            state.addBranch(-74);
            state.put("ACUP-NEW-CUST-PHONE-NUM-2A", state.get("ACSPH2AI"));
        }
        if ((java.util.Objects.equals(state.get("ACSPH2BI"), "*")) || (java.util.Objects.equals(state.get("ACSPH2BI"), " "))) {
            state.addBranch(75);
            state.put("ACUP-NEW-CUST-PHONE-NUM-2B", "\u0000");
        } else {
            state.addBranch(-75);
            state.put("ACUP-NEW-CUST-PHONE-NUM-2B", state.get("ACSPH2BI"));
        }
        if ((java.util.Objects.equals(state.get("ACSPH2CI"), "*")) || (java.util.Objects.equals(state.get("ACSPH2CI"), " "))) {
            state.addBranch(76);
            state.put("ACUP-NEW-CUST-PHONE-NUM-2C", "\u0000");
        } else {
            state.addBranch(-76);
            state.put("ACUP-NEW-CUST-PHONE-NUM-2C", state.get("ACSPH2CI"));
        }
        if ((java.util.Objects.equals(state.get("ACSGOVTI"), "*")) || (java.util.Objects.equals(state.get("ACSGOVTI"), " "))) {
            state.addBranch(77);
            state.put("ACUP-NEW-CUST-GOVT-ISSUED-ID", "\u0000");
        } else {
            state.addBranch(-77);
            state.put("ACUP-NEW-CUST-GOVT-ISSUED-ID", state.get("ACSGOVTI"));
        }
        if ((java.util.Objects.equals(state.get("ACSEFTCI"), "*")) || (java.util.Objects.equals(state.get("ACSEFTCI"), " "))) {
            state.addBranch(78);
            state.put("ACUP-NEW-CUST-EFT-ACCOUNT-ID", "\u0000");
        } else {
            state.addBranch(-78);
            state.put("ACUP-NEW-CUST-EFT-ACCOUNT-ID", state.get("ACSEFTCI"));
        }
        if ((java.util.Objects.equals(state.get("ACSPFLGI"), "*")) || (java.util.Objects.equals(state.get("ACSPFLGI"), " "))) {
            state.addBranch(79);
            state.put("ACUP-NEW-CUST-PRI-HOLDER-IND", "\u0000");
        } else {
            state.addBranch(-79);
            state.put("ACUP-NEW-CUST-PRI-HOLDER-IND", state.get("ACSPFLGI"));
        }
    }

    void do_1100_RECEIVE_MAP_EXIT(ProgramState state) {
        // EXIT
    }

    void do_1200_EDIT_MAP_INPUTS(ProgramState state) {
        state.put("INPUT-OK", true);
        if (CobolRuntime.isTruthy(state.get("ACUP-DETAILS-NOT-FETCHED"))) {
            state.addBranch(80);
            performThru(state, "1210-EDIT-ACCOUNT", "1210-EDIT-ACCOUNT-EXIT");
            state.put("ACUP-OLD-ACCT-DATA", "\u0000");
            if (CobolRuntime.isTruthy(state.get("FLG-ACCTFILTER-BLANK"))) {
                state.addBranch(81);
                state.put("NO-SEARCH-CRITERIA-RECEIVED", true);
            } else {
                state.addBranch(-81);
            }
            registry.get("1200-EDIT-MAP-INPUTS-EXIT").execute(state);
            return;
        } else {
            state.addBranch(-80);
            // CONTINUE
        }
        state.put("FOUND-ACCOUNT-DATA", true);
        state.put("FOUND-ACCT-IN-MASTER", true);
        state.put("FLG-ACCTFILTER-BLANK", false);
        state.put("FLG-ACCTFILTER-NOT-OK", false);
        state.put("FLG-ACCTFILTER-ISVALID", true);
        state.put("FOUND-CUST-IN-MASTER", true);
        state.put("FLG-CUSTFILTER-NOT-OK", false);
        state.put("FLG-CUSTFILTER-ISVALID", true);
        performThru(state, "1205-COMPARE-OLD-NEW", "1205-COMPARE-OLD-NEW-EXIT");
        if (((CobolRuntime.isTruthy(state.get("NO-CHANGES-FOUND"))) || (CobolRuntime.isTruthy(state.get("ACUP-CHANGES-OK-NOT-CONFIRMED")))) || (CobolRuntime.isTruthy(state.get("ACUP-CHANGES-OKAYED-AND-DONE")))) {
            state.addBranch(82);
            state.put("WS-NON-KEY-FLAGS", "\u0000");
            registry.get("1200-EDIT-MAP-INPUTS-EXIT").execute(state);
            return;
        } else {
            state.addBranch(-82);
        }
        state.put("ACUP-CHANGES-OK-NOT-CONFIRMED", false);
        state.put("ACUP-CHANGES-OKAYED-AND-DONE", false);
        state.put("ACUP-CHANGES-OKAYED-BUT-FAILED", false);
        state.put("ACUP-CHANGES-OKAYED-LOCK-ERROR", false);
        state.put("ACUP-DETAILS-NOT-FETCHED", false);
        state.put("ACUP-SHOW-DETAILS", false);
        state.put("ACUP-CHANGES-NOT-OK", true);
        state.put("WS-EDIT-VARIABLE-NAME", "Account Status");
        state.put("WS-EDIT-YES-NO", state.get("ACUP-NEW-ACTIVE-STATUS"));
        performThru(state, "1220-EDIT-YESNO", "1220-EDIT-YESNO-EXIT");
        state.put("WS-EDIT-ACCT-STATUS", state.get("WS-EDIT-YES-NO"));
        state.put("WS-EDIT-VARIABLE-NAME", "Open Date");
        state.put("WS-EDIT-DATE-CCYYMMDD", state.get("ACUP-NEW-OPEN-DATE"));
        perform(state, "EDIT-DATE-CCYYMMDD");
        state.put("WS-EDIT-OPEN-DATE-FLGS", state.get("WS-EDIT-DATE-FLGS"));
        state.put("WS-EDIT-VARIABLE-NAME", "Credit Limit");
        state.put("WS-EDIT-SIGNED-NUMBER-9V2-X", state.get("ACUP-NEW-CREDIT-LIMIT-X"));
        performThru(state, "1250-EDIT-SIGNED-9V2", "1250-EDIT-SIGNED-9V2-EXIT");
        state.put("WS-EDIT-CREDIT-LIMIT", state.get("WS-FLG-SIGNED-NUMBER-EDIT"));
        state.put("WS-EDIT-VARIABLE-NAME", "Expiry Date");
        state.put("WS-EDIT-DATE-CCYYMMDD", state.get("ACUP-NEW-EXPIRAION-DATE"));
        perform(state, "EDIT-DATE-CCYYMMDD");
        state.put("WS-EXPIRY-DATE-FLGS", state.get("WS-EDIT-DATE-FLGS"));
        state.put("WS-EDIT-VARIABLE-NAME", "Cash Credit Limit");
        state.put("WS-EDIT-SIGNED-NUMBER-9V2-X", state.get("ACUP-NEW-CASH-CREDIT-LIMIT-X"));
        performThru(state, "1250-EDIT-SIGNED-9V2", "1250-EDIT-SIGNED-9V2-EXIT");
        state.put("WS-EDIT-CASH-CREDIT-LIMIT", state.get("WS-FLG-SIGNED-NUMBER-EDIT"));
        state.put("WS-EDIT-VARIABLE-NAME", "Reissue Date");
        state.put("WS-EDIT-DATE-CCYYMMDD", state.get("ACUP-NEW-REISSUE-DATE"));
        perform(state, "EDIT-DATE-CCYYMMDD");
        state.put("WS-EDIT-REISSUE-DATE-FLGS", state.get("WS-EDIT-DATE-FLGS"));
        state.put("WS-EDIT-VARIABLE-NAME", "Current Balance");
        state.put("WS-EDIT-SIGNED-NUMBER-9V2-X", state.get("ACUP-NEW-CURR-BAL-X"));
        performThru(state, "1250-EDIT-SIGNED-9V2", "1250-EDIT-SIGNED-9V2-EXIT");
        state.put("WS-EDIT-CURR-BAL", state.get("WS-FLG-SIGNED-NUMBER-EDIT"));
        state.put("WS-EDIT-VARIABLE-NAME", "Current Cycle Credit Limit");
        state.put("WS-EDIT-SIGNED-NUMBER-9V2-X", state.get("ACUP-NEW-CURR-CYC-CREDIT-X"));
        performThru(state, "1250-EDIT-SIGNED-9V2", "1250-EDIT-SIGNED-9V2-EXIT");
        state.put("WS-EDIT-CURR-CYC-CREDIT", state.get("WS-FLG-SIGNED-NUMBER-EDIT"));
        state.put("WS-EDIT-VARIABLE-NAME", "Current Cycle Debit Limit");
        state.put("WS-EDIT-SIGNED-NUMBER-9V2-X", state.get("ACUP-NEW-CURR-CYC-DEBIT-X"));
        performThru(state, "1250-EDIT-SIGNED-9V2", "1250-EDIT-SIGNED-9V2-EXIT");
        state.put("WS-EDIT-CURR-CYC-DEBIT", state.get("WS-FLG-SIGNED-NUMBER-EDIT"));
        state.put("WS-EDIT-VARIABLE-NAME", "SSN");
        performThru(state, "1265-EDIT-US-SSN", "1265-EDIT-US-SSN-EXIT");
        state.put("WS-EDIT-VARIABLE-NAME", "Date of Birth");
        state.put("WS-EDIT-DATE-CCYYMMDD", state.get("ACUP-NEW-CUST-DOB-YYYY-MM-DD"));
        perform(state, "EDIT-DATE-CCYYMMDD");
        state.put("WS-EDIT-DT-OF-BIRTH-FLGS", state.get("WS-EDIT-DATE-FLGS"));
        if (CobolRuntime.isTruthy(state.get("WS-EDIT-DT-OF-BIRTH-ISVALID"))) {
            state.addBranch(83);
            perform(state, "EDIT-DATE-OF-BIRTH");
            state.put("WS-EDIT-DT-OF-BIRTH-FLGS", state.get("WS-EDIT-DATE-FLGS"));
        } else {
            state.addBranch(-83);
        }
        state.put("WS-EDIT-VARIABLE-NAME", "FICO Score");
        state.put("WS-EDIT-ALPHANUM-ONLY", state.get("ACUP-NEW-CUST-FICO-SCORE-X"));
        state.put("WS-EDIT-ALPHANUM-LENGTH", 3);
        performThru(state, "1245-EDIT-NUM-REQD", "1245-EDIT-NUM-REQD-EXIT");
        state.put("WS-EDIT-FICO-SCORE-FLGS", state.get("WS-EDIT-ALPHANUM-ONLY-FLAGS"));
        if (CobolRuntime.isTruthy(state.get("FLG-FICO-SCORE-ISVALID"))) {
            state.addBranch(84);
            performThru(state, "1275-EDIT-FICO-SCORE", "1275-EDIT-FICO-SCORE-EXIT");
        } else {
            state.addBranch(-84);
        }
        state.put("WS-EDIT-VARIABLE-NAME", "First Name");
        state.put("WS-EDIT-ALPHANUM-ONLY", state.get("ACUP-NEW-CUST-FIRST-NAME"));
        state.put("WS-EDIT-ALPHANUM-LENGTH", 25);
        performThru(state, "1225-EDIT-ALPHA-REQD", "1225-EDIT-ALPHA-REQD-EXIT");
        state.put("WS-EDIT-FIRST-NAME-FLGS", state.get("WS-EDIT-ALPHA-ONLY-FLAGS"));
        state.put("WS-EDIT-VARIABLE-NAME", "Middle Name");
        state.put("WS-EDIT-ALPHANUM-ONLY", state.get("ACUP-NEW-CUST-MIDDLE-NAME"));
        state.put("WS-EDIT-ALPHANUM-LENGTH", 25);
        performThru(state, "1235-EDIT-ALPHA-OPT", "1235-EDIT-ALPHA-OPT-EXIT");
        state.put("WS-EDIT-MIDDLE-NAME-FLGS", state.get("WS-EDIT-ALPHA-ONLY-FLAGS"));
        state.put("WS-EDIT-VARIABLE-NAME", "Last Name");
        state.put("WS-EDIT-ALPHANUM-ONLY", state.get("ACUP-NEW-CUST-LAST-NAME"));
        state.put("WS-EDIT-ALPHANUM-LENGTH", 25);
        performThru(state, "1225-EDIT-ALPHA-REQD", "1225-EDIT-ALPHA-REQD-EXIT");
        state.put("WS-EDIT-LAST-NAME-FLGS", state.get("WS-EDIT-ALPHA-ONLY-FLAGS"));
        state.put("WS-EDIT-VARIABLE-NAME", "Address Line 1");
        state.put("WS-EDIT-ALPHANUM-ONLY", state.get("ACUP-NEW-CUST-ADDR-LINE-1"));
        state.put("WS-EDIT-ALPHANUM-LENGTH", 50);
        performThru(state, "1215-EDIT-MANDATORY", "1215-EDIT-MANDATORY-EXIT");
        state.put("WS-EDIT-ADDRESS-LINE-1-FLGS", state.get("WS-EDIT-MANDATORY-FLAGS"));
        state.put("WS-EDIT-VARIABLE-NAME", "State");
        state.put("WS-EDIT-ALPHANUM-ONLY", state.get("ACUP-NEW-CUST-ADDR-STATE-CD"));
        state.put("WS-EDIT-ALPHANUM-LENGTH", 2);
        performThru(state, "1225-EDIT-ALPHA-REQD", "1225-EDIT-ALPHA-REQD-EXIT");
        state.put("WS-EDIT-STATE-FLGS", state.get("WS-EDIT-ALPHA-ONLY-FLAGS"));
        if (CobolRuntime.isTruthy(state.get("FLG-ALPHA-ISVALID"))) {
            state.addBranch(85);
            performThru(state, "1270-EDIT-US-STATE-CD", "1270-EDIT-US-STATE-CD-EXIT");
        } else {
            state.addBranch(-85);
        }
        state.put("WS-EDIT-VARIABLE-NAME", "Zip");
        state.put("WS-EDIT-ALPHANUM-ONLY", state.get("ACUP-NEW-CUST-ADDR-ZIP"));
        state.put("WS-EDIT-ALPHANUM-LENGTH", 5);
        performThru(state, "1245-EDIT-NUM-REQD", "1245-EDIT-NUM-REQD-EXIT");
        state.put("WS-EDIT-ZIPCODE-FLGS", state.get("WS-EDIT-ALPHANUM-ONLY-FLAGS"));
        state.put("WS-EDIT-VARIABLE-NAME", "City");
        state.put("WS-EDIT-ALPHANUM-ONLY", state.get("ACUP-NEW-CUST-ADDR-LINE-3"));
        state.put("WS-EDIT-ALPHANUM-LENGTH", 50);
        performThru(state, "1225-EDIT-ALPHA-REQD", "1225-EDIT-ALPHA-REQD-EXIT");
        state.put("WS-EDIT-CITY-FLGS", state.get("WS-EDIT-ALPHA-ONLY-FLAGS"));
        state.put("WS-EDIT-VARIABLE-NAME", "Country");
        state.put("WS-EDIT-ALPHANUM-ONLY", state.get("ACUP-NEW-CUST-ADDR-COUNTRY-CD"));
        state.put("WS-EDIT-ALPHANUM-LENGTH", 3);
        performThru(state, "1225-EDIT-ALPHA-REQD", "1225-EDIT-ALPHA-REQD-EXIT");
        state.put("WS-EDIT-COUNTRY-FLGS", state.get("WS-EDIT-ALPHA-ONLY-FLAGS"));
        state.put("WS-EDIT-VARIABLE-NAME", "Phone Number 1");
        state.put("WS-EDIT-US-PHONE-NUM", state.get("ACUP-NEW-CUST-PHONE-NUM-1"));
        performThru(state, "1260-EDIT-US-PHONE-NUM", "1260-EDIT-US-PHONE-NUM-EXIT");
        state.put("WS-EDIT-PHONE-NUM-1-FLGS", state.get("WS-EDIT-US-PHONE-NUM-FLGS"));
        state.put("WS-EDIT-VARIABLE-NAME", "Phone Number 2");
        state.put("WS-EDIT-US-PHONE-NUM", state.get("ACUP-NEW-CUST-PHONE-NUM-2"));
        performThru(state, "1260-EDIT-US-PHONE-NUM", "1260-EDIT-US-PHONE-NUM-EXIT");
        state.put("WS-EDIT-PHONE-NUM-2-FLGS", state.get("WS-EDIT-US-PHONE-NUM-FLGS"));
        state.put("WS-EDIT-VARIABLE-NAME", "EFT Account Id");
        state.put("WS-EDIT-ALPHANUM-ONLY", state.get("ACUP-NEW-CUST-EFT-ACCOUNT-ID"));
        state.put("WS-EDIT-ALPHANUM-LENGTH", 10);
        performThru(state, "1245-EDIT-NUM-REQD", "1245-EDIT-NUM-REQD-EXIT");
        state.put("WS-EFT-ACCOUNT-ID-FLGS", state.get("WS-EDIT-ALPHANUM-ONLY-FLAGS"));
        state.put("WS-EDIT-VARIABLE-NAME", "Primary Card Holder");
        state.put("WS-EDIT-YES-NO", state.get("ACUP-NEW-CUST-PRI-HOLDER-IND"));
        performThru(state, "1220-EDIT-YESNO", "1220-EDIT-YESNO-EXIT");
        state.put("WS-EDIT-PRI-CARDHOLDER", state.get("WS-EDIT-YES-NO"));
        if ((CobolRuntime.isTruthy(state.get("FLG-STATE-ISVALID"))) && (CobolRuntime.isTruthy(state.get("FLG-ZIPCODE-ISVALID")))) {
            state.addBranch(86);
            performThru(state, "1280-EDIT-US-STATE-ZIP-CD", "1280-EDIT-US-STATE-ZIP-CD-EXIT");
        } else {
            state.addBranch(-86);
        }
        if (CobolRuntime.isTruthy(state.get("INPUT-ERROR"))) {
            state.addBranch(87);
            // CONTINUE
        } else {
            state.addBranch(-87);
            state.put("ACUP-CHANGES-NOT-OK", false);
            state.put("ACUP-CHANGES-OKAYED-AND-DONE", false);
            state.put("ACUP-CHANGES-OKAYED-BUT-FAILED", false);
            state.put("ACUP-CHANGES-OKAYED-LOCK-ERROR", false);
            state.put("ACUP-DETAILS-NOT-FETCHED", false);
            state.put("ACUP-SHOW-DETAILS", false);
            state.put("ACUP-CHANGES-OK-NOT-CONFIRMED", true);
        }
    }

    void do_1200_EDIT_MAP_INPUTS_EXIT(ProgramState state) {
        // EXIT
    }

    void do_1205_COMPARE_OLD_NEW(ProgramState state) {
        state.put("NO-CHANGES-DETECTED", false);
        state.put("NO-CHANGES-FOUND", true);
        if ((java.util.Objects.equals(state.get("ACUP-NEW-ACCT-ID-X"), state.get("ACUP-OLD-ACCT-ID-X"))) && (CobolRuntime.isTruthy(state.get("FUNCTION")))) {
            state.addBranch(88);
            // CONTINUE
        } else {
            state.addBranch(-88);
            state.put("CHANGE-HAS-OCCURRED", true);
            registry.get("1205-COMPARE-OLD-NEW-EXIT").execute(state);
            return;
        }
        if (CobolRuntime.isTruthy(state.get("FUNCTION"))) {
            state.addBranch(89);
            state.put("NO-CHANGES-FOUND", false);
            state.put("NO-CHANGES-DETECTED", true);
        } else {
            state.addBranch(-89);
            state.put("CHANGE-HAS-OCCURRED", true);
            registry.get("1205-COMPARE-OLD-NEW-EXIT").execute(state);
            return;
        }
    }

    void do_1205_COMPARE_OLD_NEW_EXIT(ProgramState state) {
        // EXIT
    }

    void do_1210_EDIT_ACCOUNT(ProgramState state) {
        state.put("FLG-ACCTFILTER-BLANK", false);
        state.put("FLG-EDIT-US-SSN-PART1-NOT-OK", false);
        state.put("FLG-FICO-SCORE-NOT-OK", false);
        state.put("FLG-STATE-NOT-OK", false);
        state.put("FLG-ZIPCODE-NOT-OK", false);
        state.put("FLG-ACCTFILTER-NOT-OK", true);
        if ((java.util.Objects.equals(state.get("CC-ACCT-ID"), "\u0000")) || (java.util.Objects.equals(state.get("CC-ACCT-ID"), " "))) {
            state.addBranch(90);
            state.put("INPUT-ERROR", true);
            state.put("FLG-ACCTFILTER-NOT-OK", false);
            state.put("FLG-EDIT-US-SSN-PART1-NOT-OK", false);
            state.put("FLG-FICO-SCORE-NOT-OK", false);
            state.put("FLG-STATE-NOT-OK", false);
            state.put("FLG-ZIPCODE-NOT-OK", false);
            state.put("FLG-ACCTFILTER-BLANK", true);
            if (CobolRuntime.isTruthy(state.get("WS-RETURN-MSG-OFF"))) {
                state.addBranch(91);
                state.put("WS-PROMPT-FOR-ACCT", true);
            } else {
                state.addBranch(-91);
            }
            state.put("CDEMO-ACCT-ID", 0);
            registry.get("1210-EDIT-ACCOUNT-EXIT").execute(state);
            return;
        } else {
            state.addBranch(-90);
        }
        state.put("ACUP-NEW-ACCT-ID", state.get("CC-ACCT-ID"));
        if ((!CobolRuntime.isNumeric(state.get("CC-ACCT-ID"))) || (java.util.Objects.equals(state.get("CC-ACCT-ID-N"), 0))) {
            state.addBranch(92);
            state.put("INPUT-ERROR", true);
            if (CobolRuntime.isTruthy(state.get("WS-RETURN-MSG-OFF"))) {
                state.addBranch(93);
                state.put("WS-RETURN-MSG", "Account Number if supplied must be a 11 digit" + " Non-Zero Number");
            } else {
                state.addBranch(-93);
            }
            state.put("CDEMO-ACCT-ID", 0);
            registry.get("1210-EDIT-ACCOUNT-EXIT").execute(state);
            return;
        } else {
            state.addBranch(-92);
            state.put("CDEMO-ACCT-ID", state.get("CC-ACCT-ID"));
            state.put("FLG-ACCTFILTER-BLANK", false);
            state.put("FLG-ACCTFILTER-NOT-OK", false);
            state.put("FLG-ACCTFILTER-ISVALID", true);
        }
    }

    void do_1210_EDIT_ACCOUNT_EXIT(ProgramState state) {
        // EXIT
    }

    void do_1215_EDIT_MANDATORY(ProgramState state) {
        state.put("FLG-MANDATORY-BLANK", false);
        state.put("FLG-MANDATORY-ISVALID", false);
        state.put("FLG-MANDATORY-NOT-OK", true);
        if ((java.util.Objects.equals(state.get("WS-EDIT-ALPHANUM-ONLY(1:WS-EDIT-ALPHANUM-LENGTH)"), "\u0000")) || (java.util.List.of(" ", state.get("FUNCTION")).contains(state.get("WS-EDIT-ALPHANUM-ONLY(1:WS-EDIT-ALPHANUM-LENGTH)")))) {
            state.addBranch(94);
            state.put("INPUT-ERROR", true);
            state.put("FLG-MANDATORY-ISVALID", false);
            state.put("FLG-MANDATORY-NOT-OK", false);
            state.put("FLG-MANDATORY-BLANK", true);
            if (CobolRuntime.isTruthy(state.get("WS-RETURN-MSG-OFF"))) {
                state.addBranch(95);
                state.put("WS-RETURN-MSG", String.valueOf(state.get("FUNCTION")) + String.valueOf(state.get("TRIM")) + String.valueOf(state.get("WS-EDIT-VARIABLE-NAME")) + " must be supplied.");
            } else {
                state.addBranch(-95);
            }
            registry.get("1215-EDIT-MANDATORY-EXIT").execute(state);
            return;
        } else {
            state.addBranch(-94);
        }
        state.put("FLG-MANDATORY-BLANK", false);
        state.put("FLG-MANDATORY-NOT-OK", false);
        state.put("FLG-MANDATORY-ISVALID", true);
    }

    void do_1215_EDIT_MANDATORY_EXIT(ProgramState state) {
        // EXIT
    }

    void do_1220_EDIT_YESNO(ProgramState state) {
        if (((java.util.Objects.equals(state.get("WS-EDIT-YES-NO"), "\u0000")) || (java.util.Objects.equals(state.get("WS-EDIT-YES-NO"), " "))) || (java.util.Objects.equals(state.get("WS-EDIT-YES-NO"), 0))) {
            state.addBranch(96);
            state.put("INPUT-ERROR", true);
            state.put("FLG-YES-NO-NOT-OK", false);
            state.put("FLG-YES-NO-BLANK", true);
            if (CobolRuntime.isTruthy(state.get("WS-RETURN-MSG-OFF"))) {
                state.addBranch(97);
                state.put("WS-RETURN-MSG", String.valueOf(state.get("FUNCTION")) + String.valueOf(state.get("TRIM")) + String.valueOf(state.get("WS-EDIT-VARIABLE-NAME")) + " must be supplied.");
            } else {
                state.addBranch(-97);
            }
            registry.get("1220-EDIT-YESNO-EXIT").execute(state);
            return;
        } else {
            state.addBranch(-96);
        }
        if (CobolRuntime.isTruthy(state.get("FLG-YES-NO-ISVALID"))) {
            state.addBranch(98);
            // CONTINUE
        } else {
            state.addBranch(-98);
            state.put("INPUT-ERROR", true);
            state.put("FLG-YES-NO-BLANK", false);
            state.put("FLG-YES-NO-NOT-OK", true);
            if (CobolRuntime.isTruthy(state.get("WS-RETURN-MSG-OFF"))) {
                state.addBranch(99);
                state.put("WS-RETURN-MSG", String.valueOf(state.get("FUNCTION")) + String.valueOf(state.get("TRIM")) + String.valueOf(state.get("WS-EDIT-VARIABLE-NAME")) + " must be Y or N.");
            } else {
                state.addBranch(-99);
            }
            registry.get("1220-EDIT-YESNO-EXIT").execute(state);
            return;
        }
    }

    void do_1220_EDIT_YESNO_EXIT(ProgramState state) {
        // EXIT
    }

    void do_1225_EDIT_ALPHA_REQD(ProgramState state) {
        state.put("FLG-ALPHA-BLANK", false);
        state.put("FLG-ALPHA-ISVALID", false);
        state.put("FLG-ALPHA-NOT-OK", true);
        if ((java.util.Objects.equals(state.get("WS-EDIT-ALPHANUM-ONLY(1:WS-EDIT-ALPHANUM-LENGTH)"), "\u0000")) || (java.util.List.of(" ", state.get("FUNCTION")).contains(state.get("WS-EDIT-ALPHANUM-ONLY(1:WS-EDIT-ALPHANUM-LENGTH)")))) {
            state.addBranch(100);
            state.put("INPUT-ERROR", true);
            state.put("FLG-ALPHA-ISVALID", false);
            state.put("FLG-ALPHA-NOT-OK", false);
            state.put("FLG-ALPHA-BLANK", true);
            if (CobolRuntime.isTruthy(state.get("WS-RETURN-MSG-OFF"))) {
                state.addBranch(101);
                state.put("WS-RETURN-MSG", String.valueOf(state.get("FUNCTION")) + String.valueOf(state.get("TRIM")) + String.valueOf(state.get("WS-EDIT-VARIABLE-NAME")) + " must be supplied.");
            } else {
                state.addBranch(-101);
            }
            registry.get("1225-EDIT-ALPHA-REQD-EXIT").execute(state);
            return;
        } else {
            state.addBranch(-100);
        }
        state.put("LIT-ALL-ALPHA-FROM", state.get("LIT-ALL-ALPHA-FROM-X"));
        // INSPECT: INSPECT WS-EDIT-ALPHANUM-ONLY(1:WS-EDIT-ALPHANUM-LENGTH) CON
        if (CobolRuntime.isTruthy(state.get("FUNCTION"))) {
            state.addBranch(102);
            // CONTINUE
        } else {
            state.addBranch(-102);
            state.put("INPUT-ERROR", true);
            state.put("FLG-ALPHA-BLANK", false);
            state.put("FLG-ALPHA-ISVALID", false);
            state.put("FLG-ALPHA-NOT-OK", true);
            if (CobolRuntime.isTruthy(state.get("WS-RETURN-MSG-OFF"))) {
                state.addBranch(103);
                state.put("WS-RETURN-MSG", String.valueOf(state.get("FUNCTION")) + String.valueOf(state.get("TRIM")) + String.valueOf(state.get("WS-EDIT-VARIABLE-NAME")) + " can have alphabets only.");
            } else {
                state.addBranch(-103);
            }
            registry.get("1225-EDIT-ALPHA-REQD-EXIT").execute(state);
            return;
        }
        state.put("FLG-ALPHA-BLANK", false);
        state.put("FLG-ALPHA-NOT-OK", false);
        state.put("FLG-ALPHA-ISVALID", true);
    }

    void do_1225_EDIT_ALPHA_REQD_EXIT(ProgramState state) {
        // EXIT
    }

    void do_1230_EDIT_ALPHANUM_REQD(ProgramState state) {
        state.put("FLG-ALPHNANUM-BLANK", false);
        state.put("FLG-ALPHNANUM-ISVALID", false);
        state.put("FLG-ALPHNANUM-NOT-OK", true);
        if ((java.util.Objects.equals(state.get("WS-EDIT-ALPHANUM-ONLY(1:WS-EDIT-ALPHANUM-LENGTH)"), "\u0000")) || (java.util.List.of(" ", state.get("FUNCTION")).contains(state.get("WS-EDIT-ALPHANUM-ONLY(1:WS-EDIT-ALPHANUM-LENGTH)")))) {
            state.addBranch(104);
            state.put("INPUT-ERROR", true);
            state.put("FLG-ALPHNANUM-ISVALID", false);
            state.put("FLG-ALPHNANUM-NOT-OK", false);
            state.put("FLG-ALPHNANUM-BLANK", true);
            if (CobolRuntime.isTruthy(state.get("WS-RETURN-MSG-OFF"))) {
                state.addBranch(105);
                state.put("WS-RETURN-MSG", String.valueOf(state.get("FUNCTION")) + String.valueOf(state.get("TRIM")) + String.valueOf(state.get("WS-EDIT-VARIABLE-NAME")) + " must be supplied.");
            } else {
                state.addBranch(-105);
            }
            registry.get("1230-EDIT-ALPHANUM-REQD-EXIT").execute(state);
            return;
        } else {
            state.addBranch(-104);
        }
        state.put("LIT-ALL-ALPHANUM-FROM", state.get("LIT-ALL-ALPHANUM-FROM-X"));
        // INSPECT: INSPECT WS-EDIT-ALPHANUM-ONLY(1:WS-EDIT-ALPHANUM-LENGTH) CON
        if (CobolRuntime.isTruthy(state.get("FUNCTION"))) {
            state.addBranch(106);
            // CONTINUE
        } else {
            state.addBranch(-106);
            state.put("INPUT-ERROR", true);
            state.put("FLG-ALPHNANUM-BLANK", false);
            state.put("FLG-ALPHNANUM-ISVALID", false);
            state.put("FLG-ALPHNANUM-NOT-OK", true);
            if (CobolRuntime.isTruthy(state.get("WS-RETURN-MSG-OFF"))) {
                state.addBranch(107);
                state.put("WS-RETURN-MSG", String.valueOf(state.get("FUNCTION")) + String.valueOf(state.get("TRIM")) + String.valueOf(state.get("WS-EDIT-VARIABLE-NAME")) + " can have numbers or alphabets only.");
            } else {
                state.addBranch(-107);
            }
            registry.get("1230-EDIT-ALPHANUM-REQD-EXIT").execute(state);
            return;
        }
        state.put("FLG-ALPHNANUM-BLANK", false);
        state.put("FLG-ALPHNANUM-NOT-OK", false);
        state.put("FLG-ALPHNANUM-ISVALID", true);
    }

    void do_1230_EDIT_ALPHANUM_REQD_EXIT(ProgramState state) {
        // EXIT
    }

    void do_1235_EDIT_ALPHA_OPT(ProgramState state) {
        state.put("FLG-ALPHA-BLANK", false);
        state.put("FLG-ALPHA-ISVALID", false);
        state.put("FLG-ALPHA-NOT-OK", true);
        if ((java.util.Objects.equals(state.get("WS-EDIT-ALPHANUM-ONLY(1:WS-EDIT-ALPHANUM-LENGTH)"), "\u0000")) || (java.util.List.of(" ", state.get("FUNCTION")).contains(state.get("WS-EDIT-ALPHANUM-ONLY(1:WS-EDIT-ALPHANUM-LENGTH)")))) {
            state.addBranch(108);
            state.put("FLG-ALPHA-BLANK", false);
            state.put("FLG-ALPHA-NOT-OK", false);
            state.put("FLG-ALPHA-ISVALID", true);
            registry.get("1235-EDIT-ALPHA-OPT-EXIT").execute(state);
            return;
        } else {
            state.addBranch(-108);
            // CONTINUE
        }
        state.put("LIT-ALL-ALPHA-FROM", state.get("LIT-ALL-ALPHA-FROM-X"));
        // INSPECT: INSPECT WS-EDIT-ALPHANUM-ONLY(1:WS-EDIT-ALPHANUM-LENGTH) CON
        if (CobolRuntime.isTruthy(state.get("FUNCTION"))) {
            state.addBranch(109);
            // CONTINUE
        } else {
            state.addBranch(-109);
            state.put("INPUT-ERROR", true);
            state.put("FLG-ALPHA-BLANK", false);
            state.put("FLG-ALPHA-ISVALID", false);
            state.put("FLG-ALPHA-NOT-OK", true);
            if (CobolRuntime.isTruthy(state.get("WS-RETURN-MSG-OFF"))) {
                state.addBranch(110);
                state.put("WS-RETURN-MSG", String.valueOf(state.get("FUNCTION")) + String.valueOf(state.get("TRIM")) + String.valueOf(state.get("WS-EDIT-VARIABLE-NAME")) + " can have alphabets only.");
            } else {
                state.addBranch(-110);
            }
            registry.get("1235-EDIT-ALPHA-OPT-EXIT").execute(state);
            return;
        }
        state.put("FLG-ALPHA-BLANK", false);
        state.put("FLG-ALPHA-NOT-OK", false);
        state.put("FLG-ALPHA-ISVALID", true);
    }

    void do_1235_EDIT_ALPHA_OPT_EXIT(ProgramState state) {
        // EXIT
    }

    void do_1240_EDIT_ALPHANUM_OPT(ProgramState state) {
        state.put("FLG-ALPHNANUM-BLANK", false);
        state.put("FLG-ALPHNANUM-ISVALID", false);
        state.put("FLG-ALPHNANUM-NOT-OK", true);
        if ((java.util.Objects.equals(state.get("WS-EDIT-ALPHANUM-ONLY(1:WS-EDIT-ALPHANUM-LENGTH)"), "\u0000")) || (java.util.List.of(" ", state.get("FUNCTION")).contains(state.get("WS-EDIT-ALPHANUM-ONLY(1:WS-EDIT-ALPHANUM-LENGTH)")))) {
            state.addBranch(111);
            state.put("FLG-ALPHNANUM-BLANK", false);
            state.put("FLG-ALPHNANUM-NOT-OK", false);
            state.put("FLG-ALPHNANUM-ISVALID", true);
            registry.get("1240-EDIT-ALPHANUM-OPT-EXIT").execute(state);
            return;
        } else {
            state.addBranch(-111);
            // CONTINUE
        }
        state.put("LIT-ALL-ALPHANUM-FROM", state.get("LIT-ALL-ALPHANUM-FROM-X"));
        // INSPECT: INSPECT WS-EDIT-ALPHANUM-ONLY(1:WS-EDIT-ALPHANUM-LENGTH) CON
        if (CobolRuntime.isTruthy(state.get("FUNCTION"))) {
            state.addBranch(112);
            // CONTINUE
        } else {
            state.addBranch(-112);
            state.put("INPUT-ERROR", true);
            state.put("FLG-ALPHNANUM-BLANK", false);
            state.put("FLG-ALPHNANUM-ISVALID", false);
            state.put("FLG-ALPHNANUM-NOT-OK", true);
            if (CobolRuntime.isTruthy(state.get("WS-RETURN-MSG-OFF"))) {
                state.addBranch(113);
                state.put("WS-RETURN-MSG", String.valueOf(state.get("FUNCTION")) + String.valueOf(state.get("TRIM")) + String.valueOf(state.get("WS-EDIT-VARIABLE-NAME")) + " can have numbers or alphabets only.");
            } else {
                state.addBranch(-113);
            }
            registry.get("1240-EDIT-ALPHANUM-OPT-EXIT").execute(state);
            return;
        }
        state.put("FLG-ALPHNANUM-BLANK", false);
        state.put("FLG-ALPHNANUM-NOT-OK", false);
        state.put("FLG-ALPHNANUM-ISVALID", true);
    }

    void do_1240_EDIT_ALPHANUM_OPT_EXIT(ProgramState state) {
        // EXIT
    }

    void do_1245_EDIT_NUM_REQD(ProgramState state) {
        state.put("FLG-ALPHNANUM-BLANK", false);
        state.put("FLG-ALPHNANUM-ISVALID", false);
        state.put("FLG-ALPHNANUM-NOT-OK", true);
        if ((java.util.Objects.equals(state.get("WS-EDIT-ALPHANUM-ONLY(1:WS-EDIT-ALPHANUM-LENGTH)"), "\u0000")) || (java.util.List.of(" ", state.get("FUNCTION")).contains(state.get("WS-EDIT-ALPHANUM-ONLY(1:WS-EDIT-ALPHANUM-LENGTH)")))) {
            state.addBranch(114);
            state.put("INPUT-ERROR", true);
            state.put("FLG-ALPHNANUM-ISVALID", false);
            state.put("FLG-ALPHNANUM-NOT-OK", false);
            state.put("FLG-ALPHNANUM-BLANK", true);
            if (CobolRuntime.isTruthy(state.get("WS-RETURN-MSG-OFF"))) {
                state.addBranch(115);
                state.put("WS-RETURN-MSG", String.valueOf(state.get("FUNCTION")) + String.valueOf(state.get("TRIM")) + String.valueOf(state.get("WS-EDIT-VARIABLE-NAME")) + " must be supplied.");
            } else {
                state.addBranch(-115);
            }
            registry.get("1245-EDIT-NUM-REQD-EXIT").execute(state);
            return;
        } else {
            state.addBranch(-114);
        }
        if (CobolRuntime.isNumeric(state.get("WS-EDIT-ALPHANUM-ONLY(1:WS-EDIT-ALPHANUM-LENGTH)"))) {
            state.addBranch(116);
            // CONTINUE
        } else {
            state.addBranch(-116);
            state.put("INPUT-ERROR", true);
            state.put("FLG-ALPHNANUM-BLANK", false);
            state.put("FLG-ALPHNANUM-ISVALID", false);
            state.put("FLG-ALPHNANUM-NOT-OK", true);
            if (CobolRuntime.isTruthy(state.get("WS-RETURN-MSG-OFF"))) {
                state.addBranch(117);
                state.put("WS-RETURN-MSG", String.valueOf(state.get("FUNCTION")) + String.valueOf(state.get("TRIM")) + String.valueOf(state.get("WS-EDIT-VARIABLE-NAME")) + " must be all numeric.");
            } else {
                state.addBranch(-117);
            }
            registry.get("1245-EDIT-NUM-REQD-EXIT").execute(state);
            return;
        }
        if (CobolRuntime.isTruthy(state.get("FUNCTION"))) {
            state.addBranch(118);
            state.put("INPUT-ERROR", true);
            state.put("FLG-ALPHNANUM-BLANK", false);
            state.put("FLG-ALPHNANUM-ISVALID", false);
            state.put("FLG-ALPHNANUM-NOT-OK", true);
            if (CobolRuntime.isTruthy(state.get("WS-RETURN-MSG-OFF"))) {
                state.addBranch(119);
                state.put("WS-RETURN-MSG", String.valueOf(state.get("FUNCTION")) + String.valueOf(state.get("TRIM")) + String.valueOf(state.get("WS-EDIT-VARIABLE-NAME")) + " must not be zero.");
            } else {
                state.addBranch(-119);
            }
            registry.get("1245-EDIT-NUM-REQD-EXIT").execute(state);
            return;
        } else {
            state.addBranch(-118);
            // CONTINUE
        }
        state.put("FLG-ALPHNANUM-BLANK", false);
        state.put("FLG-ALPHNANUM-NOT-OK", false);
        state.put("FLG-ALPHNANUM-ISVALID", true);
    }

    void do_1245_EDIT_NUM_REQD_EXIT(ProgramState state) {
        // EXIT
    }

    void do_1250_EDIT_SIGNED_9V2(ProgramState state) {
        state.put("FLG-SIGNED-NUMBER-BLANK", false);
        state.put("FLG-SIGNED-NUMBER-ISVALID", false);
        state.put("FLG-SIGNED-NUMBER-NOT-OK", true);
        if ((java.util.Objects.equals(state.get("WS-EDIT-SIGNED-NUMBER-9V2-X"), "\u0000")) || (java.util.Objects.equals(state.get("WS-EDIT-SIGNED-NUMBER-9V2-X"), " "))) {
            state.addBranch(120);
            state.put("INPUT-ERROR", true);
            state.put("FLG-SIGNED-NUMBER-ISVALID", false);
            state.put("FLG-SIGNED-NUMBER-NOT-OK", false);
            state.put("FLG-SIGNED-NUMBER-BLANK", true);
            if (CobolRuntime.isTruthy(state.get("WS-RETURN-MSG-OFF"))) {
                state.addBranch(121);
                state.put("WS-RETURN-MSG", String.valueOf(state.get("FUNCTION")) + String.valueOf(state.get("TRIM")) + String.valueOf(state.get("WS-EDIT-VARIABLE-NAME")) + " must be supplied.");
            } else {
                state.addBranch(-121);
            }
            registry.get("1250-EDIT-SIGNED-9V2-EXIT").execute(state);
            return;
        } else {
            state.addBranch(-120);
            // CONTINUE
        }
        if (CobolRuntime.isTruthy(state.get("FUNCTION"))) {
            state.addBranch(122);
            // CONTINUE
        } else {
            state.addBranch(-122);
            state.put("INPUT-ERROR", true);
            state.put("FLG-SIGNED-NUMBER-BLANK", false);
            state.put("FLG-SIGNED-NUMBER-ISVALID", false);
            state.put("FLG-SIGNED-NUMBER-NOT-OK", true);
            if (CobolRuntime.isTruthy(state.get("WS-RETURN-MSG-OFF"))) {
                state.addBranch(123);
                state.put("WS-RETURN-MSG", String.valueOf(state.get("FUNCTION")) + String.valueOf(state.get("TRIM")) + String.valueOf(state.get("WS-EDIT-VARIABLE-NAME")) + " is not valid");
            } else {
                state.addBranch(-123);
            }
            registry.get("1250-EDIT-SIGNED-9V2-EXIT").execute(state);
            return;
        }
        state.put("FLG-SIGNED-NUMBER-BLANK", false);
        state.put("FLG-SIGNED-NUMBER-NOT-OK", false);
        state.put("FLG-SIGNED-NUMBER-ISVALID", true);
    }

    void do_1250_EDIT_SIGNED_9V2_EXIT(ProgramState state) {
        // EXIT
    }

    void do_1260_EDIT_US_PHONE_NUM(ProgramState state) {
        state.put("WS-EDIT-US-PHONE-IS-VALID", false);
        state.put("WS-EDIT-US-PHONE-IS-INVALID", true);
        if ((((java.util.Objects.equals(state.get("WS-EDIT-US-PHONE-NUMA"), " ")) || ((java.util.Objects.equals(state.get("WS-EDIT-US-PHONE-NUMA"), "\u0000")) && (java.util.Objects.equals(state.get("WS-EDIT-US-PHONE-NUMB"), " ")))) || ((java.util.Objects.equals(state.get("WS-EDIT-US-PHONE-NUMB"), "\u0000")) && (java.util.Objects.equals(state.get("WS-EDIT-US-PHONE-NUMA"), " ")))) || (java.util.Objects.equals(state.get("WS-EDIT-US-PHONE-NUMC"), "\u0000"))) {
            state.addBranch(124);
            state.put("WS-EDIT-US-PHONE-IS-INVALID", false);
            state.put("WS-EDIT-US-PHONE-IS-VALID", true);
            registry.get("EDIT-US-PHONE-EXIT").execute(state);
            return;
        } else {
            state.addBranch(-124);
            // CONTINUE
        }
    }

    void do_1260_EDIT_US_PHONE_NUM_EXIT(ProgramState state) {
        // EXIT
    }

    void do_1265_EDIT_US_SSN(ProgramState state) {
        state.put("WS-EDIT-VARIABLE-NAME", "SSN: First 3 chars");
        state.put("WS-EDIT-ALPHANUM-ONLY", state.get("ACUP-NEW-CUST-SSN-1"));
        state.put("WS-EDIT-ALPHANUM-LENGTH", 3);
        performThru(state, "1245-EDIT-NUM-REQD", "1245-EDIT-NUM-REQD-EXIT");
        state.put("WS-EDIT-US-SSN-PART1-FLGS", state.get("WS-EDIT-ALPHANUM-ONLY-FLAGS"));
        if (CobolRuntime.isTruthy(state.get("FLG-EDIT-US-SSN-PART1-ISVALID"))) {
            state.addBranch(125);
            state.put("WS-EDIT-US-SSN-PART1", state.get("ACUP-NEW-CUST-SSN-1"));
            if (CobolRuntime.isTruthy(state.get("INVALID-SSN-PART1"))) {
                state.addBranch(126);
                state.put("INPUT-ERROR", true);
                state.put("FLG-EDIT-US-PHONEA-BLANK", false);
                state.put("FLG-EDIT-US-PHONEA-ISVALID", false);
                state.put("FLG-EDIT-US-PHONEA-NOT-OK", false);
                state.put("FLG-EDIT-US-PHONEB-BLANK", false);
                state.put("FLG-EDIT-US-PHONEB-ISVALID", false);
                state.put("FLG-EDIT-US-PHONEB-NOT-OK", false);
                state.put("FLG-EDIT-US-PHONEC-BLANK", false);
                state.put("FLG-EDIT-US-PHONEC-ISVALID", false);
                state.put("FLG-EDIT-US-PHONEC-NOT-OK", false);
                state.put("FLG-EDIT-US-SSN-PART1-NOT-OK", true);
                if (CobolRuntime.isTruthy(state.get("WS-RETURN-MSG-OFF"))) {
                    state.addBranch(127);
                    state.put("WS-RETURN-MSG", String.valueOf(state.get("FUNCTION")) + String.valueOf(state.get("TRIM")) + String.valueOf(state.get("WS-EDIT-VARIABLE-NAME")) + ": should not be 000, 666, or between 900 and 999");
                } else {
                    state.addBranch(-127);
                    // CONTINUE
                }
            } else {
                state.addBranch(-126);
            }
            state.put("WS-EDIT-VARIABLE-NAME", "SSN 4th & 5th chars");
            state.put("WS-EDIT-ALPHANUM-ONLY", state.get("ACUP-NEW-CUST-SSN-2"));
            state.put("WS-EDIT-ALPHANUM-LENGTH", 2);
            performThru(state, "1245-EDIT-NUM-REQD", "1245-EDIT-NUM-REQD-EXIT");
            state.put("WS-EDIT-US-SSN-PART2-FLGS", state.get("WS-EDIT-ALPHANUM-ONLY-FLAGS"));
            state.put("WS-EDIT-VARIABLE-NAME", "SSN Last 4 chars");
            state.put("WS-EDIT-ALPHANUM-ONLY", state.get("ACUP-NEW-CUST-SSN-3"));
            state.put("WS-EDIT-ALPHANUM-LENGTH", 4);
            performThru(state, "1245-EDIT-NUM-REQD", "1245-EDIT-NUM-REQD-EXIT");
            state.put("WS-EDIT-US-SSN-PART3-FLGS", state.get("WS-EDIT-ALPHANUM-ONLY-FLAGS"));
        } else {
            state.addBranch(-125);
        }
    }

    void do_1265_EDIT_US_SSN_EXIT(ProgramState state) {
        // EXIT
    }

    void do_1270_EDIT_US_STATE_CD(ProgramState state) {
        state.put("US-STATE-CODE-TO-EDIT", state.get("ACUP-NEW-CUST-ADDR-STATE-CD"));
        if (CobolRuntime.isTruthy(state.get("VALID-US-STATE-CODE"))) {
            state.addBranch(128);
            // CONTINUE
        } else {
            state.addBranch(-128);
            state.put("INPUT-ERROR", true);
            state.put("FLG-ACCTFILTER-BLANK", false);
            state.put("FLG-ACCTFILTER-NOT-OK", false);
            state.put("FLG-EDIT-US-SSN-PART1-NOT-OK", false);
            state.put("FLG-FICO-SCORE-NOT-OK", false);
            state.put("FLG-ZIPCODE-NOT-OK", false);
            state.put("FLG-STATE-NOT-OK", true);
            if (CobolRuntime.isTruthy(state.get("WS-RETURN-MSG-OFF"))) {
                state.addBranch(129);
                state.put("WS-RETURN-MSG", String.valueOf(state.get("FUNCTION")) + String.valueOf(state.get("TRIM")) + String.valueOf(state.get("WS-EDIT-VARIABLE-NAME")) + ": is not a valid state code");
            } else {
                state.addBranch(-129);
            }
            registry.get("1270-EDIT-US-STATE-CD-EXIT").execute(state);
            return;
        }
    }

    void do_1270_EDIT_US_STATE_CD_EXIT(ProgramState state) {
        // EXIT
    }

    void do_1275_EDIT_FICO_SCORE(ProgramState state) {
        if (CobolRuntime.isTruthy(state.get("FICO-RANGE-IS-VALID"))) {
            state.addBranch(130);
            // CONTINUE
        } else {
            state.addBranch(-130);
            state.put("INPUT-ERROR", true);
            state.put("FLG-ACCTFILTER-BLANK", false);
            state.put("FLG-ACCTFILTER-NOT-OK", false);
            state.put("FLG-EDIT-US-SSN-PART1-NOT-OK", false);
            state.put("FLG-STATE-NOT-OK", false);
            state.put("FLG-ZIPCODE-NOT-OK", false);
            state.put("FLG-FICO-SCORE-NOT-OK", true);
            if (CobolRuntime.isTruthy(state.get("WS-RETURN-MSG-OFF"))) {
                state.addBranch(131);
                state.put("WS-RETURN-MSG", String.valueOf(state.get("FUNCTION")) + String.valueOf(state.get("TRIM")) + String.valueOf(state.get("WS-EDIT-VARIABLE-NAME")) + ": should be between 300 and 850");
            } else {
                state.addBranch(-131);
            }
            registry.get("1275-EDIT-FICO-SCORE-EXIT").execute(state);
            return;
        }
    }

    void do_1275_EDIT_FICO_SCORE_EXIT(ProgramState state) {
        // EXIT
    }

    void do_1280_EDIT_US_STATE_ZIP_CD(ProgramState state) {
        state.put("US-STATE-AND-FIRST-ZIP2", String.valueOf(state.get("ACUP-NEW-CUST-ADDR-STATE-CD")) + String.valueOf(state.get("ACUP-NEW-CUST-ADDR-ZIP")));
        if (CobolRuntime.isTruthy(state.get("VALID-US-STATE-ZIP-CD2-COMBO"))) {
            state.addBranch(132);
            // CONTINUE
        } else {
            state.addBranch(-132);
            state.put("INPUT-ERROR", true);
            state.put("FLG-ACCTFILTER-BLANK", false);
            state.put("FLG-ACCTFILTER-NOT-OK", false);
            state.put("FLG-EDIT-US-SSN-PART1-NOT-OK", false);
            state.put("FLG-FICO-SCORE-NOT-OK", false);
            state.put("FLG-ZIPCODE-NOT-OK", false);
            state.put("FLG-STATE-NOT-OK", true);
            state.put("FLG-ACCTFILTER-BLANK", false);
            state.put("FLG-ACCTFILTER-NOT-OK", false);
            state.put("FLG-EDIT-US-SSN-PART1-NOT-OK", false);
            state.put("FLG-FICO-SCORE-NOT-OK", false);
            state.put("FLG-STATE-NOT-OK", false);
            state.put("FLG-ZIPCODE-NOT-OK", true);
            if (CobolRuntime.isTruthy(state.get("WS-RETURN-MSG-OFF"))) {
                state.addBranch(133);
                state.put("WS-RETURN-MSG", "Invalid zip code for state");
            } else {
                state.addBranch(-133);
            }
            registry.get("1280-EDIT-US-STATE-ZIP-CD-EXIT").execute(state);
            return;
        }
    }

    void do_1280_EDIT_US_STATE_ZIP_CD_EXIT(ProgramState state) {
        // EXIT
    }

}
