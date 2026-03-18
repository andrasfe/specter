package com.specter.generated;

import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Headless smoke test that exercises the CICS pseudo-conversational loop
 * without Lanterna — the same flow as TerminalMain but driven programmatically.
 *
 * Scenario: user enters account ID "10001" and presses Enter.
 */
public class TerminalFlowTest {

    /**
     * A stub executor that throws CicsReturnSignal on cicsReturn,
     * like the terminal executor does, but doesn't need a real screen.
     */
    static class HeadlessStubExecutor extends DefaultStubExecutor {

        /** Captured SEND MAP calls */
        final List<String> sentMaps = new ArrayList<>();

        /** Collected input values (simulating RECEIVE MAP) */
        final java.util.Map<String, String> inputValues = new java.util.LinkedHashMap<>();

        @Override
        public void cicsReturn(ProgramState state, boolean hasTransid) {
            super.cicsReturn(state, hasTransid);
            throw new CicsReturnSignal(hasTransid);
        }

        @Override
        public void dummyExec(ProgramState state, String kind, String rawText) {
            // Intercept SEND MAP and RECEIVE MAP
            if ("CICS".equals(kind)) {
                String upper = rawText.toUpperCase();
                if (upper.contains("SEND MAP")) {
                    sentMaps.add(rawText);
                    // Don't call super — just log
                    return;
                }
                if (upper.contains("RECEIVE MAP")) {
                    // Populate state with simulated input
                    for (var e : inputValues.entrySet()) {
                        state.put(e.getKey(), e.getValue());
                    }
                    state.put("WS-RESP-CD", 0);
                    state.put("WS-REAS-CD", 0);
                    return;
                }
                if (upper.contains("XCTL")) {
                    // Transfer control — treat as exit
                    sentMaps.add("XCTL: " + rawText);
                    return;
                }
            }
            super.dummyExec(state, kind, rawText);
        }
    }

    private ProgramState createInitialState() {
        ProgramState state = new ProgramState();
        state.put("EIBCALEN", 0);
        state.put("WS-TRANID", "COAC");
        state.put("WS-PGMNAME", "COACTUPC");
        state.put("LIT-THISTRANID", "COAC");
        state.put("LIT-THISPGM", "COACTUPC");
        state.put("LIT-THISMAP", "CACTUPA");
        state.put("LIT-THISMAPSET", "CACTUP");
        state.put("LIT-MENUPGM", "COMEN01C");
        state.put("LIT-MENUTRANID", "COME");
        state.put("CCDA-TITLE01", "Credit Card Demo Application");
        state.put("CCDA-TITLE02", "COACTUPC - Account Update");
        state.put("CCDA-MSG-THANK-YOU", "Thank you for using the application");
        state.put("CCDA-MSG-INVALID-KEY", "Invalid key pressed");
        return state;
    }

    @Test
    void testAccountFetchFlow() {
        HeadlessStubExecutor stubs = new HeadlessStubExecutor();
        ProgramState state = createInitialState();

        // --- Turn 1: Initial entry (EIBCALEN=0) ---
        CoactupcProgram prog1 = new CoactupcProgram(stubs);
        boolean gotReturn1 = false;
        try {
            prog1.run(state);
        } catch (CicsReturnSignal ret) {
            gotReturn1 = true;
            assertTrue(ret.hasTransid, "Turn 1 should RETURN with TRANSID");
        }
        assertTrue(gotReturn1, "Turn 1 should end with CICS RETURN");
        assertFalse(stubs.sentMaps.isEmpty(), "Turn 1 should SEND MAP (initial screen)");

        System.out.println("=== After Turn 1 ===");
        System.out.println("  CDEMO-PGM-REENTER    = " + state.get("CDEMO-PGM-REENTER"));
        System.out.println("  ACUP-DETAILS-NOT-FETCHED = " + state.get("ACUP-DETAILS-NOT-FETCHED"));
        System.out.println("  CDEMO-PGM-ENTER      = " + state.get("CDEMO-PGM-ENTER"));
        System.out.println("  Sent maps: " + stubs.sentMaps);

        // Verify state after turn 1
        assertEquals(true, state.get("CDEMO-PGM-REENTER"),
                "Should set CDEMO-PGM-REENTER after initial map");
        assertEquals(true, state.get("ACUP-DETAILS-NOT-FETCHED"),
                "Should set ACUP-DETAILS-NOT-FETCHED after initial map");

        // --- Turn 2: User entered account ID "10001" and pressed Enter ---
        stubs.sentMaps.clear();
        state.put("EIBAID", "DFHENTER");
        state.put("EIBCALEN", 1);
        state.put("CCARD-AID-ENTER", true);
        state.put("CCARD-AID-PFK03", false);
        state.put("CCARD-AID-PFK05", false);
        state.put("CCARD-AID-PFK12", false);
        state.abended = false;
        state.trace.clear();
        state.execs.clear();

        // Simulate user input: account ID in the input field
        stubs.inputValues.put("ACCTSIDI", "00010001");

        // Queue CICS READ stub outcomes for the account fetch:
        // The reads all use applyStubOutcome(state, "CICS").
        // 9200: XREF read
        List<Object[]> xrefOutcome = List.of(
            new Object[]{"XREF-ACCT-ID", "00010001"},
            new Object[]{"XREF-CUST-ID", "0000050001"},
            new Object[]{"XREF-CARD-NUM", "4111111111111111"},
            new Object[]{"WS-RESP-CD", 0}
        );
        // 9300: Account read
        List<Object[]> acctOutcome = List.of(
            new Object[]{"ACCT-ID", "00010001"},
            new Object[]{"ACCT-ACTIVE-STATUS", "Y"},
            new Object[]{"ACCT-CURR-BAL", "5000.00"},
            new Object[]{"ACCT-CREDIT-LIMIT", "15000.00"},
            new Object[]{"ACCT-CASH-CREDIT-LIMIT", "3000.00"},
            new Object[]{"ACCT-OPEN-DATE", "2020-01-15"},
            new Object[]{"ACCT-EXPIRAION-DATE", "2026-12-31"},
            new Object[]{"ACCT-REISSUE-DATE", "2024-06-01"},
            new Object[]{"ACCT-CURR-CYC-CREDIT", "1200.00"},
            new Object[]{"ACCT-CURR-CYC-DEBIT", "800.00"},
            new Object[]{"ACCT-GROUP-ID", "GRP001"},
            new Object[]{"WS-RESP-CD", 0}
        );
        // 9400: Customer read
        List<Object[]> custOutcome = List.of(
            new Object[]{"CUST-ID", "0000050001"},
            new Object[]{"CUST-FIRST-NAME", "John"},
            new Object[]{"CUST-LAST-NAME", "Doe"},
            new Object[]{"CUST-ADDR-LINE-1", "123 Main St"},
            new Object[]{"CUST-ADDR-LINE-2", "Apt 4B"},
            new Object[]{"CUST-ADDR-LINE-3", "Springfield"},
            new Object[]{"CUST-ADDR-STATE-CD", "IL"},
            new Object[]{"CUST-ADDR-ZIP", "62701"},
            new Object[]{"CUST-ADDR-COUNTRY-CD", "US"},
            new Object[]{"CUST-PHONE-NUM-1", "555-0101"},
            new Object[]{"CUST-PHONE-NUM-2", "555-0102"},
            new Object[]{"CUST-SSN", "123456789"},
            new Object[]{"CUST-GOVT-ISSUED-ID", "IL-DL-987654"},
            new Object[]{"CUST-DOB-YYYYMMDD", "19850315"},
            new Object[]{"CUST-EFT-ACCOUNT-ID", "CHK-99887766"},
            new Object[]{"CUST-PRI-CARD-HOLDER-IND", "Y"},
            new Object[]{"CUST-FICO-CREDIT-SCORE", "750"},
            new Object[]{"WS-RESP-CD", 0}
        );

        // Queue all CICS stubs (all operations use "CICS" key)
        List<List<Object[]>> cicsQueue = new ArrayList<>();
        cicsQueue.add(List.of());  // HANDLE ABEND
        cicsQueue.add(xrefOutcome);   // 9200 XREF read
        cicsQueue.add(acctOutcome);   // 9300 Account read
        cicsQueue.add(custOutcome);   // 9400 Customer read
        // Extra for any additional CICS operations (SEND MAP, etc.)
        cicsQueue.add(List.of());
        cicsQueue.add(List.of());
        cicsQueue.add(List.of());
        cicsQueue.add(List.of());
        cicsQueue.add(List.of());
        cicsQueue.add(List.of());
        state.stubOutcomes.put("CICS", cicsQueue);

        CoactupcProgram prog2 = new CoactupcProgram(stubs);
        boolean gotReturn2 = false;
        try {
            prog2.run(state);
        } catch (CicsReturnSignal ret) {
            gotReturn2 = true;
        } catch (GobackSignal g) {
            // Also acceptable
        }

        System.out.println("\n=== After Turn 2 (Account Fetch) ===");
        System.out.println("  abended              = " + state.abended);
        System.out.println("  gotReturn2           = " + gotReturn2);
        System.out.println("  ACUP-SHOW-DETAILS    = " + state.get("ACUP-SHOW-DETAILS"));
        System.out.println("  FOUND-CUST-IN-MASTER = " + state.get("FOUND-CUST-IN-MASTER"));
        System.out.println("  ACCT-ID              = " + state.get("ACCT-ID"));
        System.out.println("  ACCT-ACTIVE-STATUS   = " + state.get("ACCT-ACTIVE-STATUS"));
        System.out.println("  ACCT-CURR-BAL        = " + state.get("ACCT-CURR-BAL"));
        System.out.println("  CUST-FIRST-NAME      = " + state.get("CUST-FIRST-NAME"));
        System.out.println("  CUST-LAST-NAME       = " + state.get("CUST-LAST-NAME"));
        System.out.println("  Sent maps: " + stubs.sentMaps.size());

        // Print paragraph trace
        System.out.println("\n  Paragraph trace:");
        for (String t : state.trace) {
            System.out.println("    " + t);
        }

        assertFalse(state.abended, "Program should not abend");
        assertTrue(gotReturn2, "Turn 2 should end with CICS RETURN");
    }
}
