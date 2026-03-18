package com.specter.generated;

import java.io.IOException;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Stub executor that intercepts CICS screen operations and delegates
 * them to a {@link TerminalScreen} for rendering (Lanterna or headless).
 *
 * <p>Non-screen operations (READ, WRITE, etc.) are forwarded to the
 * wrapped {@link DefaultStubExecutor} so that FIFO stub queues still
 * work for business logic.
 */
public class TerminalStubExecutor extends DefaultStubExecutor {

    private static final Pattern SEND_MAP_PAT =
            Pattern.compile("SEND\\s+MAP", Pattern.CASE_INSENSITIVE);
    private static final Pattern RECEIVE_MAP_PAT =
            Pattern.compile("RECEIVE\\s+MAP", Pattern.CASE_INSENSITIVE);
    private static final Pattern SEND_TEXT_PAT =
            Pattern.compile("SEND\\s+TEXT", Pattern.CASE_INSENSITIVE);
    private static final Pattern XCTL_PAT =
            Pattern.compile("XCTL\\s+PROGRAM\\s*\\(?'?([^)']+)'?\\)?",
                    Pattern.CASE_INSENSITIVE);
    private static final Pattern RETURN_TRANSID_PAT =
            Pattern.compile("RETURN\\s+TRANSID", Pattern.CASE_INSENSITIVE);
    private static final Pattern RETURN_PAT =
            Pattern.compile("RETURN\\s+END", Pattern.CASE_INSENSITIVE);
    private static final Pattern ASSIGN_PAT =
            Pattern.compile(
                    "ASSIGN\\s+(\\w+)\\s*\\(([^)]+)\\)",
                    Pattern.CASE_INSENSITIVE);

    private final TerminalScreen bmsScreen;

    public TerminalStubExecutor(TerminalScreen bmsScreen) {
        this.bmsScreen = bmsScreen;
    }

    @Override
    public void dummyExec(ProgramState state, String type, String rawText) {
        if (!"CICS".equalsIgnoreCase(type)) {
            super.dummyExec(state, type, rawText);
            return;
        }

        try {
            if (SEND_MAP_PAT.matcher(rawText).find()) {
                bmsScreen.sendMap(state);
                state.execs.add(java.util.Map.of("op", "SEND MAP"));
            } else if (RECEIVE_MAP_PAT.matcher(rawText).find()) {
                bmsScreen.receiveMap(state);
                state.execs.add(java.util.Map.of("op", "RECEIVE MAP"));
            } else if (SEND_TEXT_PAT.matcher(rawText).find()) {
                bmsScreen.sendText(state, rawText);
                state.execs.add(java.util.Map.of("op", "SEND TEXT"));
            } else if (XCTL_PAT.matcher(rawText).find()) {
                Matcher m = XCTL_PAT.matcher(rawText);
                m.find();
                String program = m.group(1).trim();
                // Resolve variable reference
                if (program.contains("-") || program.equals(program.toUpperCase())) {
                    Object resolved = state.get(program);
                    if (resolved != null && !String.valueOf(resolved).isBlank()) {
                        program = String.valueOf(resolved).trim();
                    }
                }
                bmsScreen.showXctl(program);
                state.execs.add(java.util.Map.of("op", "XCTL:" + program));
                throw new GobackSignal();
            } else if (ASSIGN_PAT.matcher(rawText).find()) {
                Matcher m = ASSIGN_PAT.matcher(rawText);
                while (m.find()) {
                    String keyword = m.group(1).toUpperCase();
                    String target = m.group(2).trim();
                    // Strip OF qualification
                    int ofIdx = target.toUpperCase().indexOf(" OF ");
                    if (ofIdx > 0) target = target.substring(0, ofIdx).trim();
                    switch (keyword) {
                        case "APPLID" -> state.put(target, "CICSA001");
                        case "SYSID" -> state.put(target, "CICS");
                        default -> state.put(target, keyword);
                    }
                }
                state.execs.add(java.util.Map.of("op", "ASSIGN"));
            } else {
                super.dummyExec(state, type, rawText);
            }
        } catch (IOException e) {
            throw new RuntimeException("Screen I/O error", e);
        }
    }

    @Override
    public void cicsRead(ProgramState state, String dataset, String ridfld,
                         String intoRecord, String respVar, String resp2Var) {
        state.put(respVar, 0);
        state.put(resp2Var, 0);

        // Populate mock record data based on the target record type.
        if ("CARD-XREF-RECORD".equals(intoRecord)) {
            String acctId = String.valueOf(state.get(ridfld)).trim();
            state.put("XREF-CUST-ID", acctId);
            state.put("XREF-CARD-NUM", "4111111111111111");
        } else if ("ACCOUNT-RECORD".equals(intoRecord)) {
            String acctId = String.valueOf(state.get(ridfld)).trim();
            state.put("ACCT-ID", acctId);
            state.put("ACCT-ACTIVE-STATUS", "Y");
            state.put("ACCT-CURR-BAL", 1500.00);
            state.put("ACCT-CREDIT-LIMIT", 5000.00);
            state.put("ACCT-CASH-CREDIT-LIMIT", 1000.00);
            state.put("ACCT-CURR-CYC-CREDIT", 200.00);
            state.put("ACCT-CURR-CYC-DEBIT", 100.00);
            state.put("ACCT-OPEN-DATE", "2020-01-15");
            state.put("ACCT-EXPIRAION-DATE", "2027-12-31");
            state.put("ACCT-REISSUE-DATE", "2024-01-15");
            state.put("ACCT-GROUP-ID", "RETAIL");
        } else if ("CUSTOMER-RECORD".equals(intoRecord)) {
            Object custId = state.get("WS-CARD-RID-CUST-ID");
            state.put("CUST-ID", custId != null ? custId : "00001");
            state.put("CUST-FIRST-NAME", "John");
            state.put("CUST-MIDDLE-NAME", "M");
            state.put("CUST-LAST-NAME", "Smith");
            state.put("CUST-SSN", "123456789");
            state.put("CUST-DOB-YYYY-MM-DD", "1985-06-15");
            state.put("CUST-FICO-CREDIT-SCORE", 750);
            state.put("CUST-ADDR-LINE-1", "123 Main Street");
            state.put("CUST-ADDR-LINE-2", "Apt 4B");
            state.put("CUST-ADDR-LINE-3", "Springfield");
            state.put("CUST-ADDR-STATE-CD", "IL");
            state.put("CUST-ADDR-COUNTRY-CD", "US");
            state.put("CUST-ADDR-ZIP", "62701");
            state.put("CUST-PHONE-NUM-1", "(217)555-1234");
            state.put("CUST-PHONE-NUM-2", "(217)555-5678");
            state.put("CUST-GOVT-ISSUED-ID", "IL-DL-12345");
            state.put("CUST-EFT-ACCOUNT-ID", "9876543210");
            state.put("CUST-PRI-CARD-HOLDER-IND", "Y");
        } else {
            // Security or other file — mirror password for auth checks
            Object pwd = state.get("WS-USER-PWD");
            if (pwd != null) {
                state.put("SEC-USR-PWD", pwd);
            }
            state.putIfAbsent("SEC-USR-TYPE", "U");
        }

        state.execs.add(java.util.Map.of("op",
                "READ DATASET(" + dataset + ") [simulated]"));
    }

    @Override
    public void cicsReturn(ProgramState state, boolean hasTransid) {
        state.execs.add(java.util.Map.of("op", "CICS RETURN"));
        throw new CicsReturnSignal(hasTransid);
    }
}
