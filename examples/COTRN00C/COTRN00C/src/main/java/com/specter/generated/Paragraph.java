package com.specter.generated;

/**
 * Abstract base class for generated COBOL paragraph implementations.
 *
 * <p>Each COBOL paragraph becomes a concrete subclass whose
 * {@link #doExecute(ProgramState)} method contains the translated
 * statement logic.  The public {@link #execute(ProgramState)} method
 * wraps it with call-depth guarding and trace recording.
 */
public abstract class Paragraph {

    /** The COBOL paragraph name (e.g. {@code "0100-MAIN-LOGIC"}). */
    protected final String name;

    /** Registry for looking up other paragraphs by name. */
    protected final ParagraphRegistry registry;

    /** Stub executor for CALL / EXEC / file operations. */
    protected final StubExecutor stubs;

    protected Paragraph(String name, ParagraphRegistry registry, StubExecutor stubs) {
        this.name = name;
        this.registry = registry;
        this.stubs = stubs;
    }

    // -----------------------------------------------------------------------
    // Execution
    // -----------------------------------------------------------------------

    /**
     * Execute this paragraph with call-depth guarding.
     *
     * <p>Increments {@link ProgramState#callDepth} on entry, checks
     * against {@link CobolRuntime#CALL_DEPTH_LIMIT}, and decrements
     * in a {@code finally} block.  Records the paragraph name in
     * the execution trace before delegating to {@link #doExecute}.
     */
    public void execute(ProgramState state) {
        state.callDepth++;
        if (state.callDepth > CobolRuntime.CALL_DEPTH_LIMIT) {
            state.callDepth--;
            return;
        }
        try {
            state.addTrace(name);
            doExecute(state);
        } finally {
            state.callDepth--;
        }
    }

    /**
     * Paragraph body &mdash; implemented by each generated subclass.
     */
    protected abstract void doExecute(ProgramState state);

    // -----------------------------------------------------------------------
    // Helpers available to generated code
    // -----------------------------------------------------------------------

    /**
     * PERFORM another paragraph by COBOL name.
     */
    protected void perform(ProgramState state, String paraName) {
        Paragraph p = registry.get(paraName);
        if (p != null) {
            p.execute(state);
        }
    }

    /**
     * PERFORM THRU &mdash; execute all paragraphs in registration order
     * from {@code from} to {@code thru} inclusive.
     */
    protected void performThru(ProgramState state, String from, String thru) {
        for (Paragraph p : registry.getThruRange(from, thru)) {
            p.execute(state);
        }
    }

    /**
     * PERFORM ... TIMES &mdash; execute a paragraph {@code n} times.
     */
    protected void performTimes(ProgramState state, String paraName, int n) {
        Paragraph p = registry.get(paraName);
        if (p != null) {
            for (int i = 0; i < n; i++) {
                p.execute(state);
            }
        }
    }

    /**
     * DISPLAY &mdash; concatenate parts and record in state.
     */
    protected void display(ProgramState state, String... parts) {
        state.addDisplay(String.join("", parts));
    }

    /**
     * GOBACK / STOP RUN &mdash; throw {@link GobackSignal} to unwind.
     */
    protected void goback() {
        throw new GobackSignal();
    }
}
