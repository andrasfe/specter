package com.specter.generated;

import java.io.IOException;
import java.util.List;

/**
 * Interactive terminal entrypoint for {@link CoactupcProgram}.
 *
 * <p>Implements the CICS pseudo-conversational loop:
 * <ol>
 *   <li>Run program (first call: EIBCALEN=0)</li>
 *   <li>Program sends BMS screen, issues RETURN TRANSID</li>
 *   <li>Wait for user action (Enter, PF3, etc.)</li>
 *   <li>Set EIBAID, EIBCALEN>0, re-run program</li>
 *   <li>Repeat until program exits or user presses F3</li>
 * </ol>
 *
 * <p>Usage: {@code java -cp app.jar com.specter.generated.TerminalMain}
 */
public class TerminalMain {

    public static void main(String[] args) throws IOException {
        List<BmsScreen.Field> layout = ScreenLayout.FIELDS;
        BmsScreen bmsScreen = new BmsScreen(layout);
        TerminalStubExecutor stubs = new TerminalStubExecutor(bmsScreen);

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
        try {
            boolean running = true;
            while (running) {
                try {
                    CoactupcProgram program =
                            new CoactupcProgram(stubs);
                    program.run(state);
                    running = false; // Normal completion
                } catch (CicsReturnSignal ret) {
                    if (!ret.hasTransid) {
                        running = false;
                    } else {
                        // Pseudo-conversational: wait for user action
                        String eibaid = bmsScreen.waitForAction();
                        // Preserve state across turns, update CICS fields
                        state.put("EIBAID", eibaid);
                        state.put("EIBCALEN", 1);
                        // Reset AID flags (CSSTRPFY copybook)
                        state.put("CCARD-AID-ENTER", false);
                        state.put("CCARD-AID-PFK03", false);
                        state.put("CCARD-AID-PFK05", false);
                        state.put("CCARD-AID-PFK12", false);
                        if ("DFHENTER".equals(eibaid)) {
                            state.put("CCARD-AID-ENTER", true);
                        } else if ("DFHPF3".equals(eibaid)) {
                            state.put("CCARD-AID-PFK03", true);
                        } else if ("DFHPF5".equals(eibaid)) {
                            state.put("CCARD-AID-PFK05", true);
                        } else if ("DFHPF12".equals(eibaid)) {
                            state.put("CCARD-AID-PFK12", true);
                        }
                        state.abended = false;
                        state.trace.clear();
                        state.execs.clear();
                    }
                } catch (GobackSignal g) {
                    running = false;
                }
            }
        } finally {
            bmsScreen.close();
        }
    }
}
