package com.specter.generated;

/**
 * Unchecked exception thrown by GOBACK / STOP RUN statements.
 *
 * <p>Generated paragraph code throws this to unwind the call stack
 * back to the program entry point, where it is caught and treated
 * as normal program termination.
 */
public class GobackSignal extends RuntimeException {

    private static final long serialVersionUID = 1L;

    public GobackSignal() {
        super("GOBACK");
    }

    public GobackSignal(String message) {
        super(message);
    }
}
