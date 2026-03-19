package com.specter.generated;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * Runtime state container for a generated COBOL program.
 *
 * <p>Extends {@link HashMap} so that generated code can read/write COBOL
 * variables by name.  Missing keys return the empty string {@code ""}
 * (matching COBOL's default-spaces semantics).
 *
 * <p>Typed fields carry internal bookkeeping data that the generated
 * paragraph functions and the test harness inspect after execution.
 */
public class ProgramState extends HashMap<String, Object> {

    private static final long serialVersionUID = 1L;

    /** Captured DISPLAY output lines. */
    public List<String> displays = new ArrayList<>();

    /** Branch IDs taken during execution (positive = true, negative = false). */
    public Set<Integer> branches = new HashSet<>();

    /** Paragraph execution trace (in call order). */
    public List<String> trace = new ArrayList<>();

    /** Captured CALL operations. */
    public List<Map<String, Object>> calls = new ArrayList<>();

    /** Captured EXEC operations. */
    public List<Map<String, Object>> execs = new ArrayList<>();

    /** File READ operations. */
    public List<String> reads = new ArrayList<>();

    /** File WRITE operations. */
    public List<String> writes = new ArrayList<>();

    /** Execution-ordered stub consumption log: [key, appliedEntry]. */
    public List<Object[]> stubLog = new ArrayList<>();

    /** Whether the program abended. */
    public boolean abended = false;

    /** Current recursion depth (checked by {@link Paragraph#execute}). */
    public int callDepth = 0;

    /**
     * Per-operation FIFO queues of stub outcomes.
     *
     * <p>Key: operation key (e.g. {@code "CALL:PROGNAME"}, {@code "READ:FILE"}).
     * Value: list of entries, where each entry is a list of
     * {@code Object[2]} pairs {@code [variableName, value]}.
     */
    public Map<String, List<List<Object[]>>> stubOutcomes = new LinkedHashMap<>();

    /**
     * Default stub outcomes used when the FIFO queue is exhausted.
     *
     * <p>Key: operation key.  Value: list of {@code Object[2]} pairs.
     */
    public Map<String, List<Object[]>> stubDefaults = new LinkedHashMap<>();

    // -----------------------------------------------------------------------
    // Overrides
    // -----------------------------------------------------------------------

    /**
     * Returns the value mapped to {@code key}, or a single space {@code " "}
     * if the key is absent.  This mirrors COBOL's default-spaces behavior
     * for uninitialised alphanumeric variables (PIC X fields are filled
     * with spaces).
     */
    @Override
    public Object get(Object key) {
        Object v = super.get(key);
        if (v != null) return v;
        // Resolve subscripted or reference-modified variables
        if (key instanceof String) {
            String k = (String) key;
            int lp = k.indexOf('(');
            int rp = k.lastIndexOf(')');
            if (lp > 0 && rp > lp) {
                String inner = k.substring(lp + 1, rp);
                String baseName = k.substring(0, lp);

                // Reference modification: VAR(start:length) — substring
                if (inner.contains(":")) {
                    String[] parts = inner.split(":", 2);
                    String startExpr = parts[0].trim();
                    String lenExpr = parts[1].trim();
                    Object baseVal = super.get(baseName);
                    if (baseVal == null) baseVal = super.get(k.substring(0, lp));
                    if (baseVal != null) {
                        String s = String.valueOf(baseVal);
                        int start = resolveInt(startExpr) - 1; // COBOL is 1-based
                        int len = resolveInt(lenExpr);
                        if (start >= 0 && start < s.length()) {
                            int end = Math.min(start + len, s.length());
                            return s.substring(start, end);
                        }
                    }
                } else {
                    // Subscript: VAR(SUB-VAR) → VAR(value-of-SUB-VAR)
                    if (!inner.isEmpty() && !Character.isDigit(inner.charAt(0))) {
                        Object subVal = super.get(inner);
                        if (subVal != null) {
                            String resolved = baseName + "("
                                + String.valueOf(subVal).trim() + ")";
                            Object rv = super.get(resolved);
                            if (rv != null) return rv;
                        }
                    }
                }
            }
        }
        return " ";
    }

    /** Resolve an expression to an int — either a literal or a variable name. */
    private int resolveInt(String expr) {
        try {
            return Integer.parseInt(expr);
        } catch (NumberFormatException e) {
            Object val = super.get(expr);
            if (val instanceof Number) return ((Number) val).intValue();
            if (val != null) {
                try { return Integer.parseInt(String.valueOf(val).trim()); }
                catch (NumberFormatException e2) { /* fall through */ }
            }
            return 1;
        }
    }

    /**
     * Convenience accessor that returns the value as a {@link String}.
     */
    public String getStr(String key) {
        return String.valueOf(get(key));
    }

    // -----------------------------------------------------------------------
    // Mutation helpers
    // -----------------------------------------------------------------------

    /** Append a DISPLAY output line. */
    public void addDisplay(String text) {
        displays.add(text);
    }

    /** Record a branch decision. */
    public void addBranch(int id) {
        branches.add(id);
    }

    /** Record a paragraph entry in the execution trace. */
    public void addTrace(String para) {
        trace.add(para);
    }

    // -----------------------------------------------------------------------
    // Factory
    // -----------------------------------------------------------------------

    /**
     * Create a fresh {@link ProgramState} with all collection fields
     * initialised to empty (non-null) instances.
     */
    public static ProgramState withDefaults() {
        ProgramState s = new ProgramState();
        s.displays = new ArrayList<>();
        s.branches = new HashSet<>();
        s.trace = new ArrayList<>();
        s.calls = new ArrayList<>();
        s.execs = new ArrayList<>();
        s.reads = new ArrayList<>();
        s.writes = new ArrayList<>();
        s.stubLog = new ArrayList<>();
        s.abended = false;
        s.callDepth = 0;
        s.stubOutcomes = new LinkedHashMap<>();
        s.stubDefaults = new LinkedHashMap<>();
        return s;
    }
}
