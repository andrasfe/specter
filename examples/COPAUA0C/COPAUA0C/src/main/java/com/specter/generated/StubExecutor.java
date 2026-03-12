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
     * Record a CALL operation and apply its stub outcome (fallback).
     */
    void dummyCall(ProgramState state, String programName);

    /**
     * Record an EXEC operation and apply its stub outcome (fallback).
     */
    void dummyExec(ProgramState state, String kind, String rawText);

    // -------------------------------------------------------------------
    // CICS typed operations
    // -------------------------------------------------------------------

    void cicsRead(ProgramState state, String dataset, String ridfld, String intoRecord, String respVar, String resp2Var);

    void cicsReturn(ProgramState state);

    void cicsRetrieve(ProgramState state, String intoVar);

    void cicsSyncpoint(ProgramState state);

    void cicsAsktime(ProgramState state, String abstimeVar);

    void cicsFormattime(ProgramState state, String abstimeVar, String dateVar, String timeVar, String msVar);

    void cicsWriteqTd(ProgramState state, String queue, String fromRecord);

    // -------------------------------------------------------------------
    // DLI / IMS typed operations
    // -------------------------------------------------------------------

    void dliSchedulePsb(ProgramState state, String psbName);

    void dliTerminate(ProgramState state);

    void dliGetUnique(ProgramState state, String segment, String intoRecord, String whereCol, String whereVar);

    void dliInsert(ProgramState state, String segment, String fromRecord);

    void dliInsertChild(ProgramState state, String parentSegment, String parentWhereCol, String parentWhereVar, String childSegment, String fromRecord);

    void dliReplace(ProgramState state, String segment, String fromRecord);

    // -------------------------------------------------------------------
    // MQ typed operations
    // -------------------------------------------------------------------

    void mqOpen(ProgramState state, String queueNameVar);

    void mqGet(ProgramState state, String bufferVar, String datalenVar, String waitIntervalVar);

    void mqPut1(ProgramState state, String replyQueueVar, String bufferVar, String buflenVar);

    void mqClose(ProgramState state);
}
