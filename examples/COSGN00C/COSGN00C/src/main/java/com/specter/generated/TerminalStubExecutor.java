package com.specter.generated;

import java.io.IOException;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Stub executor that intercepts CICS screen operations and delegates
 * them to a {@link BmsScreen} for Lanterna terminal rendering.
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
            Pattern.compile("XCTL\\s+PROGRAM\\s*\\('([^']+)'\\)",
                    Pattern.CASE_INSENSITIVE);
    private static final Pattern RETURN_TRANSID_PAT =
            Pattern.compile("RETURN\\s+TRANSID", Pattern.CASE_INSENSITIVE);
    private static final Pattern RETURN_PAT =
            Pattern.compile("RETURN\\s+END", Pattern.CASE_INSENSITIVE);
    private static final Pattern ASSIGN_PAT =
            Pattern.compile(
                    "ASSIGN\\s+(\\w+)\\s*\\(([^)]+)\\)",
                    Pattern.CASE_INSENSITIVE);

    private final BmsScreen bmsScreen;

    public TerminalStubExecutor(BmsScreen bmsScreen) {
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
                String program = m.group(1);
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
    public void cicsReturn(ProgramState state, boolean hasTransid) {
        state.execs.add(java.util.Map.of("op", "CICS RETURN"));
        throw new CicsReturnSignal(hasTransid);
    }
}
