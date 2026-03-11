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
        // Build the operation key.  For EXEC SQL / CICS / DLI the key
        // is just the kind string, matching the Python generator's
        // behaviour (_apply_stub_outcome(state, kind)).
        String opKey = kind;

        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("kind", kind);
        entry.put("text", rawText);
        state.execs.add(entry);

        applyStubOutcome(state, opKey);
    }
}
