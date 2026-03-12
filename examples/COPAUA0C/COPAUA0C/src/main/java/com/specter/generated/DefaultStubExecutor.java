package com.specter.generated;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Default {@link StubExecutor} implementation.
 *
 * <p>Pops entries from {@link ProgramState#stubOutcomes} FIFO queues.
 * When a queue is exhausted, falls back to
 * {@link ProgramState#stubDefaults}.  Every consumption (including
 * defaults) is logged to {@link ProgramState#stubLog}.
 */
public class DefaultStubExecutor implements StubExecutor {

    @Override
    public List<Object[]> applyStubOutcome(ProgramState state, String key) {
        List<Object[]> applied = null;

        // Try the FIFO queue first.
        List<List<Object[]>> queue = state.stubOutcomes.get(key);
        if (queue != null && !queue.isEmpty()) {
            applied = queue.remove(0);
        } else {
            // Fall back to defaults.
            List<Object[]> defaults = state.stubDefaults.get(key);
            if (defaults != null && !defaults.isEmpty()) {
                applied = new ArrayList<>(defaults);
            }
        }

        // Apply variable assignments.
        if (applied != null) {
            for (Object[] pair : applied) {
                state.put(pair[0].toString(), pair[1]);
            }
        }

        // Log the consumption.
        state.stubLog.add(new Object[]{key, applied});

        return applied;
    }

    @Override
    public void dummyCall(ProgramState state, String programName) {
        String opKey = "CALL:" + programName;

        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("name", programName);
        state.calls.add(entry);

        applyStubOutcome(state, opKey);
    }

    @Override
    public void dummyExec(ProgramState state, String kind, String rawText) {
        String opKey = kind;

        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("kind", kind);
        entry.put("text", rawText);
        state.execs.add(entry);

        applyStubOutcome(state, opKey);
    }

    // -------------------------------------------------------------------
    // CICS typed operations
    // -------------------------------------------------------------------

    @Override
    public void cicsRead(ProgramState state, String dataset, String ridfld, String intoRecord, String respVar, String resp2Var) {
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("kind", "CICS");
        entry.put("text", "READ DATASET(" + dataset + ") RIDFLD(" + ridfld + ")");
        state.execs.add(entry);
        applyStubOutcome(state, "CICS");
    }

    @Override
    public void cicsReturn(ProgramState state) {
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("kind", "CICS");
        entry.put("text", "RETURN");
        state.execs.add(entry);
        applyStubOutcome(state, "CICS");
    }

    @Override
    public void cicsRetrieve(ProgramState state, String intoVar) {
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("kind", "CICS");
        entry.put("text", "RETRIEVE INTO(" + (intoVar != null ? intoVar : "") + ")");
        state.execs.add(entry);
        applyStubOutcome(state, "CICS");
    }

    @Override
    public void cicsSyncpoint(ProgramState state) {
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("kind", "CICS");
        entry.put("text", "SYNCPOINT");
        state.execs.add(entry);
        applyStubOutcome(state, "CICS");
    }

    @Override
    public void cicsAsktime(ProgramState state, String abstimeVar) {
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("kind", "CICS");
        entry.put("text", "ASKTIME ABSTIME(" + (abstimeVar != null ? abstimeVar : "") + ")");
        state.execs.add(entry);
        applyStubOutcome(state, "CICS");
    }

    @Override
    public void cicsFormattime(ProgramState state, String abstimeVar, String dateVar, String timeVar, String msVar) {
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("kind", "CICS");
        entry.put("text", "FORMATTIME ABSTIME(" + (abstimeVar != null ? abstimeVar : "") + ")");
        state.execs.add(entry);
        applyStubOutcome(state, "CICS");
    }

    @Override
    public void cicsWriteqTd(ProgramState state, String queue, String fromRecord) {
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("kind", "CICS");
        entry.put("text", "WRITEQ TD QUEUE(" + (queue != null ? queue : "") + ")");
        state.execs.add(entry);
        applyStubOutcome(state, "CICS");
    }

    // -------------------------------------------------------------------
    // DLI / IMS typed operations
    // -------------------------------------------------------------------

    @Override
    public void dliSchedulePsb(ProgramState state, String psbName) {
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("kind", "DLI");
        entry.put("text", "SCHD PSB(" + (psbName != null ? psbName : "") + ")");
        state.execs.add(entry);
        applyStubOutcome(state, "DLI");
    }

    @Override
    public void dliTerminate(ProgramState state) {
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("kind", "DLI");
        entry.put("text", "TERM");
        state.execs.add(entry);
        applyStubOutcome(state, "DLI");
    }

    @Override
    public void dliGetUnique(ProgramState state, String segment, String intoRecord, String whereCol, String whereVar) {
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("kind", "DLI");
        entry.put("text", "GU SEGMENT(" + segment + ") WHERE(" + whereCol + " = " + whereVar + ")");
        state.execs.add(entry);
        applyStubOutcome(state, "DLI");
    }

    @Override
    public void dliInsert(ProgramState state, String segment, String fromRecord) {
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("kind", "DLI");
        entry.put("text", "ISRT SEGMENT(" + segment + ") FROM(" + (fromRecord != null ? fromRecord : "") + ")");
        state.execs.add(entry);
        applyStubOutcome(state, "DLI");
    }

    @Override
    public void dliInsertChild(ProgramState state, String parentSegment, String parentWhereCol, String parentWhereVar, String childSegment, String fromRecord) {
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("kind", "DLI");
        entry.put("text", "ISRT SEGMENT(" + parentSegment + ") WHERE(" + parentWhereCol + " = " + parentWhereVar + ") SEGMENT(" + childSegment + ") FROM(" + (fromRecord != null ? fromRecord : "") + ")");
        state.execs.add(entry);
        applyStubOutcome(state, "DLI");
    }

    @Override
    public void dliReplace(ProgramState state, String segment, String fromRecord) {
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("kind", "DLI");
        entry.put("text", "REPL SEGMENT(" + segment + ") FROM(" + (fromRecord != null ? fromRecord : "") + ")");
        state.execs.add(entry);
        applyStubOutcome(state, "DLI");
    }

    // -------------------------------------------------------------------
    // MQ typed operations
    // -------------------------------------------------------------------

    @Override
    public void mqOpen(ProgramState state, String queueNameVar) {
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("name", "MQOPEN");
        state.calls.add(entry);
        applyStubOutcome(state, "CALL:MQOPEN");
    }

    @Override
    public void mqGet(ProgramState state, String bufferVar, String datalenVar, String waitIntervalVar) {
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("name", "MQGET");
        state.calls.add(entry);
        applyStubOutcome(state, "CALL:MQGET");
    }

    @Override
    public void mqPut1(ProgramState state, String replyQueueVar, String bufferVar, String buflenVar) {
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("name", "MQPUT1");
        state.calls.add(entry);
        applyStubOutcome(state, "CALL:MQPUT1");
    }

    @Override
    public void mqClose(ProgramState state) {
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("name", "MQCLOSE");
        state.calls.add(entry);
        applyStubOutcome(state, "CALL:MQCLOSE");
    }
}
