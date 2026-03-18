package com.specter.generated;

/**
 * Thrown by {@link TerminalStubExecutor} when the program issues
 * EXEC CICS RETURN TRANSID — signals end of a pseudo-conversational
 * turn.  The {@link TerminalMain} loop catches this and waits for
 * the next user action before re-invoking the program.
 */
public class CicsReturnSignal extends RuntimeException {
    public final boolean hasTransid;

    public CicsReturnSignal(boolean hasTransid) {
        super("CICS RETURN");
        this.hasTransid = hasTransid;
    }
}
