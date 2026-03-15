package com.specter.generated;

/**
 * Thrown by {@link TerminalStubExecutor} when the program issues
 * EXEC CICS XCTL PROGRAM — signals a transfer of control to
 * another CICS program.  The {@link MultiProgramRunner} catches
 * this and routes to the target program.
 */
public class XctlSignal extends RuntimeException {
    private static final long serialVersionUID = 1L;

    public final String targetProgram;

    public XctlSignal(String targetProgram) {
        super("XCTL to " + targetProgram);
        this.targetProgram = targetProgram;
    }
}
