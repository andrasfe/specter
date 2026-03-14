package com.specter.generated;

import java.io.IOException;
import java.util.List;

/**
 * Interactive terminal entrypoint for {@link Cotrn00cProgram}.
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
        state.put("WS-TRANID", "COTR");
        state.put("WS-PGMNAME", "COTRN00C");
        try {
            boolean running = true;
            while (running) {
                try {
                    Cotrn00cProgram program =
                            new Cotrn00cProgram(stubs);
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
