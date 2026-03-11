"""Java runtime class templates for generated Specter projects.

Each module-level constant is a Java source file template using Python
``str.format`` placeholders (e.g. ``{package_name}``, ``{program_id}``).
The code generator substitutes concrete values at generation time.
"""

# ---------------------------------------------------------------------------
# ProgramState.java
# ---------------------------------------------------------------------------

PROGRAM_STATE_JAVA = """\
package {package_name};

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
 * <p>Extends {{@link HashMap}} so that generated code can read/write COBOL
 * variables by name.  Missing keys return the empty string {{@code ""}}
 * (matching COBOL's default-spaces semantics).
 *
 * <p>Typed fields carry internal bookkeeping data that the generated
 * paragraph functions and the test harness inspect after execution.
 */
public class ProgramState extends HashMap<String, Object> {{

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

    /** Current recursion depth (checked by {{@link Paragraph#execute}}). */
    public int callDepth = 0;

    /**
     * Per-operation FIFO queues of stub outcomes.
     *
     * <p>Key: operation key (e.g. {{@code "CALL:PROGNAME"}}, {{@code "READ:FILE"}}).
     * Value: list of entries, where each entry is a list of
     * {{@code Object[2]}} pairs {{@code [variableName, value]}}.
     */
    public Map<String, List<List<Object[]>>> stubOutcomes = new LinkedHashMap<>();

    /**
     * Default stub outcomes used when the FIFO queue is exhausted.
     *
     * <p>Key: operation key.  Value: list of {{@code Object[2]}} pairs.
     */
    public Map<String, List<Object[]>> stubDefaults = new LinkedHashMap<>();

    // -----------------------------------------------------------------------
    // Overrides
    // -----------------------------------------------------------------------

    /**
     * Returns the value mapped to {{@code key}}, or the empty string {{@code ""}}
     * if the key is absent.  This mirrors COBOL's default-spaces behavior
     * for uninitialised variables.
     */
    @Override
    public Object get(Object key) {{
        Object v = super.get(key);
        return v != null ? v : "";
    }}

    /**
     * Convenience accessor that returns the value as a {{@link String}}.
     */
    public String getStr(String key) {{
        return String.valueOf(get(key));
    }}

    // -----------------------------------------------------------------------
    // Mutation helpers
    // -----------------------------------------------------------------------

    /** Append a DISPLAY output line. */
    public void addDisplay(String text) {{
        displays.add(text);
    }}

    /** Record a branch decision. */
    public void addBranch(int id) {{
        branches.add(id);
    }}

    /** Record a paragraph entry in the execution trace. */
    public void addTrace(String para) {{
        trace.add(para);
    }}

    // -----------------------------------------------------------------------
    // Factory
    // -----------------------------------------------------------------------

    /**
     * Create a fresh {{@link ProgramState}} with all collection fields
     * initialised to empty (non-null) instances.
     */
    public static ProgramState withDefaults() {{
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
    }}
}}
"""

# ---------------------------------------------------------------------------
# GobackSignal.java
# ---------------------------------------------------------------------------

GOBACK_SIGNAL_JAVA = """\
package {package_name};

/**
 * Unchecked exception thrown by GOBACK / STOP RUN statements.
 *
 * <p>Generated paragraph code throws this to unwind the call stack
 * back to the program entry point, where it is caught and treated
 * as normal program termination.
 */
public class GobackSignal extends RuntimeException {{

    private static final long serialVersionUID = 1L;

    public GobackSignal() {{
        super("GOBACK");
    }}

    public GobackSignal(String message) {{
        super(message);
    }}
}}
"""

# ---------------------------------------------------------------------------
# CobolRuntime.java
# ---------------------------------------------------------------------------

COBOL_RUNTIME_JAVA = """\
package {package_name};

/**
 * Static utility methods that mirror the Python runtime helpers
 * ({{@code _to_num}}, {{@code _is_numeric}}, etc.).
 *
 * <p>All methods are null-safe and never throw.
 */
public final class CobolRuntime {{

    /** Call-depth limit shared by all paragraphs. */
    public static final int CALL_DEPTH_LIMIT = 200;

    private CobolRuntime() {{
        // utility class
    }}

    // -----------------------------------------------------------------------
    // Numeric conversion
    // -----------------------------------------------------------------------

    /**
     * Coerce an arbitrary value to {{@code double}}.
     *
     * <ul>
     *   <li>{{@link Number}} &rarr; {{@code doubleValue()}}</li>
     *   <li>{{@link String}} &rarr; trimmed, then parsed; 0.0 on failure</li>
     *   <li>{{@code null}} or anything else &rarr; 0.0</li>
     * </ul>
     */
    public static double toNum(Object v) {{
        if (v instanceof Number) {{
            return ((Number) v).doubleValue();
        }}
        if (v instanceof String) {{
            String s = ((String) v).trim();
            if (s.isEmpty()) {{
                return 0.0;
            }}
            try {{
                return Double.parseDouble(s);
            }} catch (NumberFormatException e) {{
                return 0.0;
            }}
        }}
        return 0.0;
    }}

    /**
     * Check whether a value is numeric (parseable as a number).
     */
    public static boolean isNumeric(Object v) {{
        if (v == null) {{
            return false;
        }}
        if (v instanceof Number) {{
            return true;
        }}
        String s = String.valueOf(v).trim();
        if (s.isEmpty()) {{
            return false;
        }}
        try {{
            Double.parseDouble(s);
            return true;
        }} catch (NumberFormatException e) {{
            return false;
        }}
    }}

    /**
     * Convert a value to {{@link String}}; {{@code null}} becomes {{@code ""}}.
     */
    public static String toStr(Object v) {{
        if (v == null) {{
            return "";
        }}
        return String.valueOf(v);
    }}

    // -----------------------------------------------------------------------
    // COBOL comparison
    // -----------------------------------------------------------------------

    /**
     * COBOL-style comparison.
     *
     * <p>If both operands are numeric (or parseable as numbers), compare
     * numerically.  Otherwise compare as trimmed strings (case-sensitive,
     * matching COBOL EBCDIC collation for ASCII-range data).
     *
     * @return negative, zero, or positive (like {{@link Comparable#compareTo}}).
     */
    /**
     * COBOL truthiness: non-null, non-empty-string, non-zero, and Boolean.TRUE.
     */
    public static boolean isTruthy(Object v) {{
        if (v == null) return false;
        if (v instanceof Boolean) return (Boolean) v;
        if (v instanceof Number) return ((Number) v).doubleValue() != 0;
        String s = v.toString().trim();
        return !s.isEmpty();
    }}

    public static int cobolCompare(Object a, Object b) {{
        boolean aNum = isNumeric(a);
        boolean bNum = isNumeric(b);
        if (aNum && bNum) {{
            double da = toNum(a);
            double db = toNum(b);
            return Double.compare(da, db);
        }}
        String sa = toStr(a).trim();
        String sb = toStr(b).trim();
        return sa.compareTo(sb);
    }}
}}
"""

# ---------------------------------------------------------------------------
# Paragraph.java
# ---------------------------------------------------------------------------

PARAGRAPH_JAVA = """\
package {package_name};

/**
 * Abstract base class for generated COBOL paragraph implementations.
 *
 * <p>Each COBOL paragraph becomes a concrete subclass whose
 * {{@link #doExecute(ProgramState)}} method contains the translated
 * statement logic.  The public {{@link #execute(ProgramState)}} method
 * wraps it with call-depth guarding and trace recording.
 */
public abstract class Paragraph {{

    /** The COBOL paragraph name (e.g. {{@code "0100-MAIN-LOGIC"}}). */
    protected final String name;

    /** Registry for looking up other paragraphs by name. */
    protected final ParagraphRegistry registry;

    /** Stub executor for CALL / EXEC / file operations. */
    protected final StubExecutor stubs;

    protected Paragraph(String name, ParagraphRegistry registry, StubExecutor stubs) {{
        this.name = name;
        this.registry = registry;
        this.stubs = stubs;
    }}

    // -----------------------------------------------------------------------
    // Execution
    // -----------------------------------------------------------------------

    /**
     * Execute this paragraph with call-depth guarding.
     *
     * <p>Increments {{@link ProgramState#callDepth}} on entry, checks
     * against {{@link CobolRuntime#CALL_DEPTH_LIMIT}}, and decrements
     * in a {{@code finally}} block.  Records the paragraph name in
     * the execution trace before delegating to {{@link #doExecute}}.
     */
    public void execute(ProgramState state) {{
        state.callDepth++;
        if (state.callDepth > CobolRuntime.CALL_DEPTH_LIMIT) {{
            state.callDepth--;
            return;
        }}
        try {{
            state.addTrace(name);
            doExecute(state);
        }} finally {{
            state.callDepth--;
        }}
    }}

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
    protected void perform(ProgramState state, String paraName) {{
        Paragraph p = registry.get(paraName);
        if (p != null) {{
            p.execute(state);
        }}
    }}

    /**
     * PERFORM THRU &mdash; execute all paragraphs in registration order
     * from {{@code from}} to {{@code thru}} inclusive.
     */
    protected void performThru(ProgramState state, String from, String thru) {{
        for (Paragraph p : registry.getThruRange(from, thru)) {{
            p.execute(state);
        }}
    }}

    /**
     * PERFORM ... TIMES &mdash; execute a paragraph {{@code n}} times.
     */
    protected void performTimes(ProgramState state, String paraName, int n) {{
        Paragraph p = registry.get(paraName);
        if (p != null) {{
            for (int i = 0; i < n; i++) {{
                p.execute(state);
            }}
        }}
    }}

    /**
     * DISPLAY &mdash; concatenate parts and record in state.
     */
    protected void display(ProgramState state, String... parts) {{
        state.addDisplay(String.join("", parts));
    }}

    /**
     * GOBACK / STOP RUN &mdash; throw {{@link GobackSignal}} to unwind.
     */
    protected void goback() {{
        throw new GobackSignal();
    }}
}}
"""

# ---------------------------------------------------------------------------
# ParagraphRegistry.java
# ---------------------------------------------------------------------------

PARAGRAPH_REGISTRY_JAVA = """\
package {package_name};

import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Insertion-ordered registry of {{@link Paragraph}} instances.
 *
 * <p>Maintains both a {{@link LinkedHashMap}} for O(1) name lookup and
 * an {{@link ArrayList}} for index-based range queries needed by
 * PERFORM THRU.
 */
public class ParagraphRegistry {{

    private final Map<String, Paragraph> byName = new LinkedHashMap<>();
    private final List<Paragraph> ordered = new ArrayList<>();
    private final List<String> orderedNames = new ArrayList<>();

    /**
     * Register a paragraph.  Must be called in COBOL source order.
     */
    public void register(Paragraph p) {{
        byName.put(p.name, p);
        ordered.add(p);
        orderedNames.add(p.name);
    }}

    /**
     * Look up a paragraph by its COBOL name.
     *
     * @return the paragraph, or {{@code null}} if not found.
     */
    public Paragraph get(String name) {{
        return byName.get(name);
    }}

    /**
     * Return the sub-list of paragraphs from {{@code from}} to {{@code thru}}
     * inclusive, in registration (source) order.
     *
     * <p>If either name is not found the method returns an empty list
     * rather than throwing.
     */
    public List<Paragraph> getThruRange(String from, String thru) {{
        int start = orderedNames.indexOf(from);
        int end = orderedNames.indexOf(thru);
        if (start < 0 || end < 0 || start > end) {{
            return Collections.emptyList();
        }}
        return ordered.subList(start, end + 1);
    }}

    /**
     * Return an unmodifiable list of all paragraph names in registration
     * order.
     */
    public List<String> allNames() {{
        return Collections.unmodifiableList(orderedNames);
    }}
}}
"""

# ---------------------------------------------------------------------------
# StubExecutor.java
# ---------------------------------------------------------------------------

STUB_EXECUTOR_JAVA = """\
package {package_name};

import java.util.List;
import java.util.Map;

/**
 * Interface for stub execution during generated COBOL program runs.
 *
 * <p>Stubs simulate external operations (CALL, EXEC, file I/O) by
 * popping pre-configured outcomes from FIFO queues and applying
 * variable assignments to the program state.
 */
public interface StubExecutor {{

    /**
     * Pop one entry from the stub-outcome queue for {{@code key}},
     * apply all variable assignments, and return the entry.
     *
     * <p>Falls back to {{@link ProgramState#stubDefaults}} when the
     * queue is exhausted.
     *
     * @param state the current program state
     * @param key   the operation key (e.g. {{@code "CALL:PROG"}},
     *              {{@code "READ:FILE"}}, {{@code "SQL"}})
     * @return the applied entry (list of {{@code Object[2]}} pairs),
     *         or {{@code null}} if no outcome was available
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
     * @param kind    the EXEC kind ({{@code "SQL"}}, {{@code "CICS"}},
     *                {{@code "DLI"}}, {{@code "OTHER"}})
     * @param rawText the raw EXEC statement text
     */
    void dummyExec(ProgramState state, String kind, String rawText);
}}
"""

# ---------------------------------------------------------------------------
# DefaultStubExecutor.java
# ---------------------------------------------------------------------------

DEFAULT_STUB_EXECUTOR_JAVA = """\
package {package_name};

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Default {{@link StubExecutor}} implementation.
 *
 * <p>Pops entries from {{@link ProgramState#stubOutcomes}} FIFO queues.
 * When a queue is exhausted, falls back to
 * {{@link ProgramState#stubDefaults}}.  Every consumption (including
 * defaults) is logged to {{@link ProgramState#stubLog}}.
 */
public class DefaultStubExecutor implements StubExecutor {{

    @Override
    public List<Object[]> applyStubOutcome(ProgramState state, String key) {{
        List<Object[]> applied = null;

        // Try the FIFO queue first.
        List<List<Object[]>> queue = state.stubOutcomes.get(key);
        if (queue != null && !queue.isEmpty()) {{
            applied = queue.remove(0);
        }} else {{
            // Fall back to defaults.
            List<Object[]> defaults = state.stubDefaults.get(key);
            if (defaults != null && !defaults.isEmpty()) {{
                applied = new ArrayList<>(defaults);
            }}
        }}

        // Apply variable assignments.
        if (applied != null) {{
            for (Object[] pair : applied) {{
                state.put(pair[0].toString(), pair[1]);
            }}
        }}

        // Log the consumption.
        state.stubLog.add(new Object[]{{key, applied}});

        return applied;
    }}

    @Override
    public void dummyCall(ProgramState state, String programName) {{
        String opKey = "CALL:" + programName;

        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("name", programName);
        state.calls.add(entry);

        applyStubOutcome(state, opKey);
    }}

    @Override
    public void dummyExec(ProgramState state, String kind, String rawText) {{
        // Build the operation key.  For EXEC SQL / CICS / DLI the key
        // is just the kind string, matching the Python generator's
        // behaviour (_apply_stub_outcome(state, kind)).
        String opKey = kind;

        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("kind", kind);
        entry.put("text", rawText);
        state.execs.add(entry);

        applyStubOutcome(state, opKey);
    }}
}}
"""

# ---------------------------------------------------------------------------
# SectionBase.java
# ---------------------------------------------------------------------------

SECTION_BASE_JAVA = """\
package {package_name};

/**
 * Abstract base class for generated section classes.
 *
 * <p>Each section groups multiple COBOL paragraphs by numeric prefix.
 * Paragraphs are registered as anonymous {{@link Paragraph}} instances
 * that delegate to section methods.
 */
public abstract class SectionBase {{

    protected final ParagraphRegistry registry;
    protected final StubExecutor stubs;

    protected SectionBase(ParagraphRegistry registry, StubExecutor stubs) {{
        this.registry = registry;
        this.stubs = stubs;
    }}

    /**
     * Register a paragraph backed by a method reference.
     */
    protected void paragraph(String name, java.util.function.Consumer<ProgramState> body) {{
        registry.register(new Paragraph(name, registry, stubs) {{
            @Override protected void doExecute(ProgramState state) {{
                body.accept(state);
            }}
        }});
    }}

    // -----------------------------------------------------------------------
    // Helpers available to generated code (same signatures as Paragraph)
    // -----------------------------------------------------------------------

    protected void perform(ProgramState state, String paraName) {{
        Paragraph p = registry.get(paraName);
        if (p != null) {{
            p.execute(state);
        }}
    }}

    protected void performThru(ProgramState state, String from, String thru) {{
        for (Paragraph p : registry.getThruRange(from, thru)) {{
            p.execute(state);
        }}
    }}

    protected void performTimes(ProgramState state, String paraName, int n) {{
        Paragraph p = registry.get(paraName);
        if (p != null) {{
            for (int i = 0; i < n; i++) {{
                p.execute(state);
            }}
        }}
    }}

    protected void display(ProgramState state, String... parts) {{
        state.addDisplay(String.join("", parts));
    }}

    protected void goback() {{
        throw new GobackSignal();
    }}
}}
"""
