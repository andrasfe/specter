package com.specter.generated;

import java.io.IOException;
import java.util.*;
import java.util.function.Function;

/**
 * Multi-program CICS XCTL router.
 *
 * <p>Manages a registry of {@link CicsProgram} factory functions and
 * handles XCTL transfers between them.  Each program runs in its own
 * pseudo-conversational loop until it either completes normally,
 * issues GOBACK, or transfers control via {@link XctlSignal}.
 *
 * <p>Program factories accept a {@link StubExecutor} so the runner
 * can wire a {@link TerminalStubExecutor} backed by the correct
 * screen for each program.
 *
 * <p>Usage:
 * <pre>{@code
 *   new MultiProgramRunner(false).run();
 * }</pre>
 */
public class MultiProgramRunner {

    private final Map<String, Function<StubExecutor, CicsProgram>> registry = new LinkedHashMap<>();
    private final boolean headless;
    private String firstProgram;

    public MultiProgramRunner(boolean headless) {
        this.headless = headless;
        firstProgram = "COACTUPC";
        registry.put("COACTUPC", (stubs) -> new CoactupcProgram(stubs));
        registry.put("COSGN00C", (stubs) -> new Cosgn00cProgram(stubs));
        registry.put("COTRN00C", (stubs) -> new Cotrn00cProgram(stubs));
    }

    public void run() throws IOException {
        String currentProgram = firstProgram;
        ProgramState state = new ProgramState();
        state.put("EIBCALEN", 0);
        CicsScreen screen = null;

        while (currentProgram != null) {
            Function<StubExecutor, CicsProgram> factory = registry.get(currentProgram);
            if (factory == null) {
                System.err.println("Unknown program: " + currentProgram);
                break;
            }

            // Probe the layout by creating a temporary instance
            CicsProgram probe = factory.apply(new DefaultStubExecutor());
            List<CicsScreen.Field> layout = probe.screenLayout();

            // Set up screen for this program's layout
            if (screen != null) {
                try { screen.close(); } catch (IOException ignored) {}
            }
            if (!layout.isEmpty()) {
                screen = headless ? new HeadlessScreen(layout) : new BmsScreen(layout);
            } else {
                screen = null;
            }

            // Wire TerminalStubExecutor for this screen
            StubExecutor stubs = screen != null
                ? new TerminalStubExecutor(screen)
                : new DefaultStubExecutor();

            // Create actual program instance with terminal stubs
            CicsProgram prog = factory.apply(stubs);

            // Seed per-program CICS state (LIT-*, CCDA-*, WS-TRANID, etc.)
            prog.initState(state);
            state.abended = false;
            state.trace.clear();
            state.execs.clear();

            // Run pseudo-conversational loop for this program
            currentProgram = runProgram(factory, stubs, state, screen);
        }
        if (screen != null) {
            try { screen.close(); } catch (IOException ignored) {}
        }
    }

    private String runProgram(Function<StubExecutor, CicsProgram> factory,
                              StubExecutor stubs,
                              ProgramState state, CicsScreen screen) {
        while (true) {
            try {
                // Create fresh program instance per turn (like real CICS)
                CicsProgram prog = factory.apply(stubs);
                prog.run(state);
                return null; // Normal completion
            } catch (CicsReturnSignal ret) {
                if (!ret.hasTransid) return null;
                if (screen == null) return null;
                // Pseudo-conversational: wait for user action
                try {
                    String eibaid = screen.waitForAction();
                    state.put("EIBAID", eibaid);
                    state.put("EIBCALEN", 1);
                    state.put("CCARD-AID-ENTER", "DFHENTER".equals(eibaid));
                    state.put("CCARD-AID-PFK03", "DFHPF3".equals(eibaid));
                    state.put("CCARD-AID-PFK05", "DFHPF5".equals(eibaid));
                    state.put("CCARD-AID-PFK07", "DFHPF7".equals(eibaid));
                    state.put("CCARD-AID-PFK08", "DFHPF8".equals(eibaid));
                    state.put("CCARD-AID-PFK12", "DFHPF12".equals(eibaid));
                    state.abended = false;
                    state.trace.clear();
                    state.execs.clear();
                } catch (IOException e) {
                    System.err.println("Screen I/O error: " + e.getMessage());
                    return null;
                }
            } catch (XctlSignal xctl) {
                return xctl.targetProgram; // Transfer to target
            } catch (GobackSignal g) {
                return null;
            }
        }
    }

    public static void main(String[] args) throws IOException {
        boolean headless = args.length > 0 && "--headless".equals(args[0]);
        new MultiProgramRunner(headless).run();
    }
}
