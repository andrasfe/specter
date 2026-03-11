package com.specter.generated;

import java.util.List;
import java.util.Map;

/**
 * Interface for stub execution during generated COBOL program runs.
 *
 * <p>Stubs simulate external operations (CALL, EXEC, file I/O) by
 * popping pre-configured outcomes from FIFO queues and applying
 * variable assignments to the program state.
 */
public interface StubExecutor {

    /**
     * Pop one entry from the stub-outcome queue for {@code key},
     * apply all variable assignments, and return the entry.
     *
     * <p>Falls back to {@link ProgramState#stubDefaults} when the
     * queue is exhausted.
     *
     * @param state the current program state
     * @param key   the operation key (e.g. {@code "CALL:PROG"},
     *              {@code "READ:FILE"}, {@code "SQL"})
     * @return the applied entry (list of {@code Object[2]} pairs),
     *         or {@code null} if no outcome was available
     */
    List<Object[]> applyStubOutcome(ProgramState state, String key);

    /**
     * Record a CALL operation and apply its stub outcome.
     *
     * @param state       the current program state
     * @param programName the called program name
     */
    void dummyCall(ProgramState state, String programName);

    /**
     * Record an EXEC operation and apply its stub outcome.
     *
     * @param state   the current program state
     * @param kind    the EXEC kind ({@code "SQL"}, {@code "CICS"},
     *                {@code "DLI"}, {@code "OTHER"})
     * @param rawText the raw EXEC statement text
     */
    void dummyExec(ProgramState state, String kind, String rawText);
}
