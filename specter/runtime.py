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

    void cicsReturn(ProgramState state, boolean hasTransid);

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
        String opKey = kind;

        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("kind", kind);
        entry.put("text", rawText);
        state.execs.add(entry);

        applyStubOutcome(state, opKey);
    }}

    // -------------------------------------------------------------------
    // CICS typed operations
    // -------------------------------------------------------------------

    @Override
    public void cicsRead(ProgramState state, String dataset, String ridfld, String intoRecord, String respVar, String resp2Var) {{
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("kind", "CICS");
        entry.put("text", "READ DATASET(" + dataset + ") RIDFLD(" + ridfld + ")");
        state.execs.add(entry);
        applyStubOutcome(state, "CICS");
    }}

    @Override
    public void cicsReturn(ProgramState state, boolean hasTransid) {{
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("kind", "CICS");
        entry.put("text", "RETURN");
        state.execs.add(entry);
        applyStubOutcome(state, "CICS");
    }}

    @Override
    public void cicsRetrieve(ProgramState state, String intoVar) {{
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("kind", "CICS");
        entry.put("text", "RETRIEVE INTO(" + (intoVar != null ? intoVar : "") + ")");
        state.execs.add(entry);
        applyStubOutcome(state, "CICS");
    }}

    @Override
    public void cicsSyncpoint(ProgramState state) {{
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("kind", "CICS");
        entry.put("text", "SYNCPOINT");
        state.execs.add(entry);
        applyStubOutcome(state, "CICS");
    }}

    @Override
    public void cicsAsktime(ProgramState state, String abstimeVar) {{
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("kind", "CICS");
        entry.put("text", "ASKTIME ABSTIME(" + (abstimeVar != null ? abstimeVar : "") + ")");
        state.execs.add(entry);
        applyStubOutcome(state, "CICS");
    }}

    @Override
    public void cicsFormattime(ProgramState state, String abstimeVar, String dateVar, String timeVar, String msVar) {{
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("kind", "CICS");
        entry.put("text", "FORMATTIME ABSTIME(" + (abstimeVar != null ? abstimeVar : "") + ")");
        state.execs.add(entry);
        applyStubOutcome(state, "CICS");
    }}

    @Override
    public void cicsWriteqTd(ProgramState state, String queue, String fromRecord) {{
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("kind", "CICS");
        entry.put("text", "WRITEQ TD QUEUE(" + (queue != null ? queue : "") + ")");
        state.execs.add(entry);
        applyStubOutcome(state, "CICS");
    }}

    // -------------------------------------------------------------------
    // DLI / IMS typed operations
    // -------------------------------------------------------------------

    @Override
    public void dliSchedulePsb(ProgramState state, String psbName) {{
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("kind", "DLI");
        entry.put("text", "SCHD PSB(" + (psbName != null ? psbName : "") + ")");
        state.execs.add(entry);
        applyStubOutcome(state, "DLI");
    }}

    @Override
    public void dliTerminate(ProgramState state) {{
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("kind", "DLI");
        entry.put("text", "TERM");
        state.execs.add(entry);
        applyStubOutcome(state, "DLI");
    }}

    @Override
    public void dliGetUnique(ProgramState state, String segment, String intoRecord, String whereCol, String whereVar) {{
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("kind", "DLI");
        entry.put("text", "GU SEGMENT(" + segment + ") WHERE(" + whereCol + " = " + whereVar + ")");
        state.execs.add(entry);
        applyStubOutcome(state, "DLI");
    }}

    @Override
    public void dliInsert(ProgramState state, String segment, String fromRecord) {{
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("kind", "DLI");
        entry.put("text", "ISRT SEGMENT(" + segment + ") FROM(" + (fromRecord != null ? fromRecord : "") + ")");
        state.execs.add(entry);
        applyStubOutcome(state, "DLI");
    }}

    @Override
    public void dliInsertChild(ProgramState state, String parentSegment, String parentWhereCol, String parentWhereVar, String childSegment, String fromRecord) {{
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("kind", "DLI");
        entry.put("text", "ISRT SEGMENT(" + parentSegment + ") WHERE(" + parentWhereCol + " = " + parentWhereVar + ") SEGMENT(" + childSegment + ") FROM(" + (fromRecord != null ? fromRecord : "") + ")");
        state.execs.add(entry);
        applyStubOutcome(state, "DLI");
    }}

    @Override
    public void dliReplace(ProgramState state, String segment, String fromRecord) {{
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("kind", "DLI");
        entry.put("text", "REPL SEGMENT(" + segment + ") FROM(" + (fromRecord != null ? fromRecord : "") + ")");
        state.execs.add(entry);
        applyStubOutcome(state, "DLI");
    }}

    // -------------------------------------------------------------------
    // MQ typed operations
    // -------------------------------------------------------------------

    @Override
    public void mqOpen(ProgramState state, String queueNameVar) {{
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("name", "MQOPEN");
        state.calls.add(entry);
        applyStubOutcome(state, "CALL:MQOPEN");
    }}

    @Override
    public void mqGet(ProgramState state, String bufferVar, String datalenVar, String waitIntervalVar) {{
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("name", "MQGET");
        state.calls.add(entry);
        applyStubOutcome(state, "CALL:MQGET");
    }}

    @Override
    public void mqPut1(ProgramState state, String replyQueueVar, String bufferVar, String buflenVar) {{
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("name", "MQPUT1");
        state.calls.add(entry);
        applyStubOutcome(state, "CALL:MQPUT1");
    }}

    @Override
    public void mqClose(ProgramState state) {{
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("name", "MQCLOSE");
        state.calls.add(entry);
        applyStubOutcome(state, "CALL:MQCLOSE");
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

# ---------------------------------------------------------------------------
# JdbcStubExecutor.java
# ---------------------------------------------------------------------------

JDBC_STUB_EXECUTOR_JAVA = """\
package {package_name};

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.ResultSetMetaData;
import java.sql.SQLException;
import java.time.Instant;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * {{@link StubExecutor}} implementation backed by real JDBC and JMS connections.
 *
 * <p>CICS READ / DLI GU / ISRT / REPL operations are translated to SQL
 * statements via JDBC.  MQ CALL operations are translated to JMS
 * operations.  Other operations fall back to the default stub behaviour.
 *
 * <p>Implements {{@link AutoCloseable}} so it can be used in
 * try-with-resources blocks.
 */
public class JdbcStubExecutor implements StubExecutor, AutoCloseable {{

    private final javax.sql.DataSource dataSource;
    private Connection conn;

    /* JMS fields -- nullable (JMS is optional at runtime). */
    private Object jmsFactory;   // jakarta.jms.ConnectionFactory
    private Object jmsConn;      // jakarta.jms.Connection
    private Object jmsSession;   // jakarta.jms.Session
    private Object jmsConsumer;  // jakarta.jms.MessageConsumer
    private Object jmsProducer;  // jakarta.jms.MessageProducer

    /**
     * Create a JdbcStubExecutor.
     *
     * @param dataSource JDBC DataSource for database operations
     * @param jmsFactory JMS ConnectionFactory (may be {{@code null}})
     */
    public JdbcStubExecutor(javax.sql.DataSource dataSource, Object jmsFactory) {{
        this.dataSource = dataSource;
        this.jmsFactory = jmsFactory;
    }}

    private Connection getConnection() throws SQLException {{
        if (conn == null || conn.isClosed()) {{
            conn = dataSource.getConnection();
        }}
        return conn;
    }}

    /**
     * Close all held connections (JDBC and JMS).
     */
    @Override
    public void close() {{
        try {{
            if (conn != null && !conn.isClosed()) {{
                conn.close();
            }}
        }} catch (SQLException ignored) {{
        }}
        // Close JMS resources via reflection (optional dependency)
        closeJms();
    }}

    private void closeJms() {{
        try {{
            if (jmsSession != null) {{
                jmsSession.getClass().getMethod("close").invoke(jmsSession);
            }}
            if (jmsConn != null) {{
                jmsConn.getClass().getMethod("close").invoke(jmsConn);
            }}
        }} catch (Exception ignored) {{
        }}
        jmsSession = null;
        jmsConn = null;
        jmsConsumer = null;
        jmsProducer = null;
    }}

    // -------------------------------------------------------------------
    // Stub outcome support (delegates to DefaultStubExecutor logic)
    // -------------------------------------------------------------------

    @Override
    public List<Object[]> applyStubOutcome(ProgramState state, String key) {{
        List<Object[]> applied = null;
        List<List<Object[]>> queue = state.stubOutcomes.get(key);
        if (queue != null && !queue.isEmpty()) {{
            applied = queue.remove(0);
        }} else {{
            List<Object[]> defaults = state.stubDefaults.get(key);
            if (defaults != null && !defaults.isEmpty()) {{
                applied = new java.util.ArrayList<>(defaults);
            }}
        }}
        if (applied != null) {{
            for (Object[] pair : applied) {{
                state.put(pair[0].toString(), pair[1]);
            }}
        }}
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
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("kind", kind);
        entry.put("text", rawText);
        state.execs.add(entry);
        applyStubOutcome(state, kind);
    }}

    // -------------------------------------------------------------------
    // CICS typed operations
    // -------------------------------------------------------------------

    @Override
    public void cicsRead(ProgramState state, String dataset, String ridfld, String intoRecord, String respVar, String resp2Var) {{
        try {{
            String tableName = dataset.replace("-", "_");
            String keyCol = ridfld.replace("-", "_");
            PreparedStatement ps = getConnection().prepareStatement(
                "SELECT * FROM " + tableName + " WHERE " + keyCol + " = ?");
            ps.setString(1, state.get(ridfld).toString());
            ResultSet rs = ps.executeQuery();
            if (rs.next()) {{
                ResultSetMetaData meta = rs.getMetaData();
                for (int i = 1; i <= meta.getColumnCount(); i++) {{
                    String colName = meta.getColumnName(i).replace("_", "-");
                    state.put(colName, rs.getObject(i));
                }}
                if (respVar != null) state.put(respVar, 0);  // NORMAL
            }} else {{
                if (respVar != null) state.put(respVar, 13);  // NOTFND
            }}
            rs.close();
            ps.close();
        }} catch (SQLException e) {{
            if (respVar != null) state.put(respVar, 12);  // ERROR
            throw new RuntimeException(e);
        }}
    }}

    @Override
    public void cicsReturn(ProgramState state, boolean hasTransid) {{
        throw new GobackSignal();
    }}

    @Override
    public void cicsRetrieve(ProgramState state, String intoVar) {{
        if (jmsConsumer == null) {{
            Map<String, Object> entry = new LinkedHashMap<>();
            entry.put("kind", "CICS");
            entry.put("text", "RETRIEVE INTO(" + (intoVar != null ? intoVar : "") + ")");
            state.execs.add(entry);
            applyStubOutcome(state, "CICS");
            return;
        }}
        try {{
            java.lang.reflect.Method recv = jmsConsumer.getClass().getMethod("receive", long.class);
            Object msg = recv.invoke(jmsConsumer, 5000L);
            if (msg != null && intoVar != null) {{
                java.lang.reflect.Method getText = msg.getClass().getMethod("getText");
                state.put(intoVar, getText.invoke(msg));
            }}
        }} catch (Exception e) {{
            throw new RuntimeException(e);
        }}
    }}

    @Override
    public void cicsSyncpoint(ProgramState state) {{
        try {{
            getConnection().commit();
        }} catch (SQLException e) {{
            throw new RuntimeException(e);
        }}
    }}

    @Override
    public void cicsAsktime(ProgramState state, String abstimeVar) {{
        if (abstimeVar != null) {{
            state.put(abstimeVar, Instant.now().toEpochMilli());
        }}
    }}

    @Override
    public void cicsFormattime(ProgramState state, String abstimeVar, String dateVar, String timeVar, String msVar) {{
        long abstime = 0;
        if (abstimeVar != null) {{
            Object v = state.get(abstimeVar);
            if (v instanceof Number) abstime = ((Number) v).longValue();
        }}
        LocalDateTime dt = LocalDateTime.ofInstant(Instant.ofEpochMilli(abstime), ZoneId.systemDefault());
        if (dateVar != null) {{
            state.put(dateVar, dt.format(DateTimeFormatter.ofPattern("yyDDD")));
        }}
        if (timeVar != null) {{
            state.put(timeVar, dt.format(DateTimeFormatter.ofPattern("HHmmss")));
        }}
        if (msVar != null) {{
            state.put(msVar, String.valueOf(abstime % 1000));
        }}
    }}

    @Override
    public void cicsWriteqTd(ProgramState state, String queue, String fromRecord) {{
        if (jmsProducer == null) {{
            Map<String, Object> entry = new LinkedHashMap<>();
            entry.put("kind", "CICS");
            entry.put("text", "WRITEQ TD QUEUE(" + (queue != null ? queue : "") + ")");
            state.execs.add(entry);
            applyStubOutcome(state, "CICS");
            return;
        }}
        try {{
            java.lang.reflect.Method createText = jmsSession.getClass()
                .getMethod("createTextMessage", String.class);
            Object msg = createText.invoke(jmsSession,
                fromRecord != null ? state.get(fromRecord).toString() : "");
            java.lang.reflect.Method send = jmsProducer.getClass()
                .getMethod("send", Class.forName("jakarta.jms.Message"));
            send.invoke(jmsProducer, msg);
        }} catch (Exception e) {{
            throw new RuntimeException(e);
        }}
    }}

    // -------------------------------------------------------------------
    // DLI / IMS typed operations
    // -------------------------------------------------------------------

    @Override
    public void dliSchedulePsb(ProgramState state, String psbName) {{
        try {{
            conn = dataSource.getConnection();
        }} catch (SQLException e) {{
            throw new RuntimeException(e);
        }}
    }}

    @Override
    public void dliTerminate(ProgramState state) {{
        try {{
            if (conn != null && !conn.isClosed()) {{
                conn.close();
            }}
        }} catch (SQLException e) {{
            throw new RuntimeException(e);
        }}
    }}

    @Override
    public void dliGetUnique(ProgramState state, String segment, String intoRecord, String whereCol, String whereVar) {{
        try {{
            String tableName = segment.replace("-", "_");
            String keyCol = whereCol != null ? whereCol.replace("-", "_") : "ID";
            PreparedStatement ps = getConnection().prepareStatement(
                "SELECT * FROM " + tableName + " WHERE " + keyCol + " = ?");
            ps.setString(1, whereVar != null ? state.get(whereVar).toString() : "");
            ResultSet rs = ps.executeQuery();
            if (rs.next()) {{
                ResultSetMetaData meta = rs.getMetaData();
                for (int i = 1; i <= meta.getColumnCount(); i++) {{
                    String colName = meta.getColumnName(i).replace("_", "-");
                    state.put(colName, rs.getObject(i));
                }}
            }}
            rs.close();
            ps.close();
        }} catch (SQLException e) {{
            throw new RuntimeException(e);
        }}
    }}

    @Override
    public void dliInsert(ProgramState state, String segment, String fromRecord) {{
        try {{
            String tableName = segment.replace("-", "_");
            PreparedStatement ps = getConnection().prepareStatement(
                "INSERT INTO " + tableName + " DEFAULT VALUES");
            ps.executeUpdate();
            ps.close();
        }} catch (SQLException e) {{
            throw new RuntimeException(e);
        }}
    }}

    @Override
    public void dliInsertChild(ProgramState state, String parentSegment, String parentWhereCol, String parentWhereVar, String childSegment, String fromRecord) {{
        try {{
            String tableName = childSegment.replace("-", "_");
            PreparedStatement ps = getConnection().prepareStatement(
                "INSERT INTO " + tableName + " DEFAULT VALUES");
            ps.executeUpdate();
            ps.close();
        }} catch (SQLException e) {{
            throw new RuntimeException(e);
        }}
    }}

    @Override
    public void dliReplace(ProgramState state, String segment, String fromRecord) {{
        try {{
            String tableName = segment.replace("-", "_");
            PreparedStatement ps = getConnection().prepareStatement(
                "UPDATE " + tableName + " SET dummy = 1 WHERE 1=0");
            ps.executeUpdate();
            ps.close();
        }} catch (SQLException e) {{
            throw new RuntimeException(e);
        }}
    }}

    // -------------------------------------------------------------------
    // MQ typed operations
    // -------------------------------------------------------------------

    @Override
    public void mqOpen(ProgramState state, String queueNameVar) {{
        if (jmsFactory == null) {{
            dummyCall(state, "MQOPEN");
            return;
        }}
        try {{
            java.lang.reflect.Method createConn = jmsFactory.getClass()
                .getMethod("createConnection", String.class, String.class);
            jmsConn = createConn.invoke(jmsFactory,
                AppConfig.getJmsUser(), AppConfig.getJmsPassword());
            java.lang.reflect.Method createSess = jmsConn.getClass()
                .getMethod("createSession", boolean.class, int.class);
            jmsSession = createSess.invoke(jmsConn, false, 1);
            String qName = queueNameVar != null ? state.get(queueNameVar).toString().trim() : "";
            if (qName.isEmpty()) qName = "SPECTER.DEFAULT";
            java.lang.reflect.Method createQueue = jmsSession.getClass()
                .getMethod("createQueue", String.class);
            Object queue = createQueue.invoke(jmsSession, qName);
            java.lang.reflect.Method createConsumer = jmsSession.getClass()
                .getMethod("createConsumer", Class.forName("jakarta.jms.Destination"));
            jmsConsumer = createConsumer.invoke(jmsSession, queue);
            java.lang.reflect.Method createProducer = jmsSession.getClass()
                .getMethod("createProducer", Class.forName("jakarta.jms.Destination"));
            jmsProducer = createProducer.invoke(jmsSession, queue);
            state.put("WS-COMPLETION-CODE", 0);  // MQCC_OK
        }} catch (Exception e) {{
            System.err.println("MQ OPEN failed: " + e.getMessage());
            state.put("WS-COMPLETION-CODE", 2);  // MQCC_FAILED
            state.put("WS-REASON-CODE", 2085);   // MQRC_UNKNOWN_OBJECT_NAME
        }}
    }}

    @Override
    public void mqGet(ProgramState state, String bufferVar, String datalenVar, String waitIntervalVar) {{
        if (jmsConsumer == null) {{
            dummyCall(state, "MQGET");
            return;
        }}
        try {{
            long timeout = 5000;
            if (waitIntervalVar != null) {{
                Object wv = state.get(waitIntervalVar);
                if (wv instanceof Number) timeout = ((Number) wv).longValue();
            }}
            java.lang.reflect.Method recv = jmsConsumer.getClass()
                .getMethod("receive", long.class);
            Object msg = recv.invoke(jmsConsumer, timeout);
            if (msg != null && bufferVar != null) {{
                java.lang.reflect.Method getText = msg.getClass().getMethod("getText");
                String text = (String) getText.invoke(msg);
                state.put(bufferVar, text);
                if (datalenVar != null) state.put(datalenVar, text.length());
                state.put("WS-COMPLETION-CODE", 0);
            }} else {{
                state.put("WS-COMPLETION-CODE", 2);
                state.put("WS-REASON-CODE", 2033);   // MQRC_NO_MSG_AVAILABLE
            }}
        }} catch (Exception e) {{
            System.err.println("MQ GET failed: " + e.getMessage());
            state.put("WS-COMPLETION-CODE", 2);
            state.put("WS-REASON-CODE", 2033);
        }}
    }}

    @Override
    public void mqPut1(ProgramState state, String replyQueueVar, String bufferVar, String buflenVar) {{
        if (jmsProducer == null) {{
            dummyCall(state, "MQPUT1");
            return;
        }}
        try {{
            java.lang.reflect.Method createText = jmsSession.getClass()
                .getMethod("createTextMessage", String.class);
            String body = bufferVar != null ? state.get(bufferVar).toString() : "";
            Object msg = createText.invoke(jmsSession, body);
            java.lang.reflect.Method send = jmsProducer.getClass()
                .getMethod("send", Class.forName("jakarta.jms.Message"));
            send.invoke(jmsProducer, msg);
            state.put("WS-COMPLETION-CODE", 0);
        }} catch (Exception e) {{
            System.err.println("MQ PUT1 failed: " + e.getMessage());
            state.put("WS-COMPLETION-CODE", 2);
            state.put("WS-REASON-CODE", 2085);
        }}
    }}

    @Override
    public void mqClose(ProgramState state) {{
        closeJms();
        state.put("WS-COMPLETION-CODE", 0);
    }}
}}
"""

# ---------------------------------------------------------------------------
# AppConfig.java
# ---------------------------------------------------------------------------

APP_CONFIG_JAVA = """\
package {package_name};

/**
 * Environment-variable-based configuration for database and JMS connections.
 *
 * <p>Reads {{@code SPECTER_DB_URL}}, {{@code SPECTER_DB_USER}},
 * {{@code SPECTER_DB_PASSWORD}}, and {{@code SPECTER_JMS_URL}} from the
 * environment with sensible localhost defaults.
 */
public final class AppConfig {{

    private AppConfig() {{
    }}

    public static String getDbUrl() {{
        return env("SPECTER_DB_URL", "jdbc:postgresql://localhost:5432/specter");
    }}

    public static String getDbUser() {{
        return env("SPECTER_DB_USER", "specter");
    }}

    public static String getDbPassword() {{
        return env("SPECTER_DB_PASSWORD", "specter");
    }}

    /** Returns the JMS broker URL, or {{@code null}} if not configured. */
    public static String getJmsBrokerUrl() {{
        return env("SPECTER_JMS_URL", null);
    }}

    public static String getJmsUser() {{
        return env("SPECTER_JMS_USER", "admin");
    }}

    public static String getJmsPassword() {{
        return env("SPECTER_JMS_PASSWORD", "admin");
    }}

    private static String env(String key, String defaultValue) {{
        String v = System.getenv(key);
        return (v != null && !v.isBlank()) ? v : defaultValue;
    }}
}}
"""

# ---------------------------------------------------------------------------
# Main.java  (Docker entrypoint)
# ---------------------------------------------------------------------------

MAIN_JAVA = """\
package {package_name};

import com.zaxxer.hikari.HikariConfig;
import com.zaxxer.hikari.HikariDataSource;

/**
 * Docker / standalone entrypoint for {{@link {program_class_name}}}.
 *
 * <p>Creates a {{@link HikariDataSource}} from {{@link AppConfig}},
 * optionally creates a JMS {{@code ConnectionFactory}}, wires a
 * {{@link JdbcStubExecutor}}, runs the program, and prints results.
 */
public class Main {{

    public static void main(String[] args) {{
        // Database connection pool
        HikariConfig hikari = new HikariConfig();
        hikari.setJdbcUrl(AppConfig.getDbUrl());
        hikari.setUsername(AppConfig.getDbUser());
        hikari.setPassword(AppConfig.getDbPassword());
        hikari.setMaximumPoolSize(5);
        HikariDataSource dataSource = new HikariDataSource(hikari);

        // JMS factory (nullable)
        Object jmsFactory = null;
        String jmsUrl = AppConfig.getJmsBrokerUrl();
        if (jmsUrl != null) {{
            try {{
                Class<?> factoryClass = Class.forName(
                    "org.apache.activemq.artemis.jms.client.ActiveMQConnectionFactory");
                jmsFactory = factoryClass
                    .getConstructor(String.class, String.class, String.class)
                    .newInstance(jmsUrl, AppConfig.getJmsUser(), AppConfig.getJmsPassword());
            }} catch (Exception e) {{
                System.err.println("JMS unavailable: " + e.getMessage());
            }}
        }}

        // Wire and run
        try (JdbcStubExecutor stubs = new JdbcStubExecutor(dataSource, jmsFactory)) {{
            {program_class_name} program = new {program_class_name}(stubs);
            ProgramState result = program.run();

            // Print results
            System.out.println("=== Execution complete ===");
            System.out.println("Abended: " + result.abended);
            System.out.println("Paragraphs executed: " + result.trace.size());
            System.out.println("Trace: " + result.trace);
            if (!result.displays.isEmpty()) {{
                System.out.println("Displays:");
                for (String d : result.displays) {{
                    System.out.println("  " + d);
                }}
            }}
            if (!result.execs.isEmpty()) {{
                System.out.println("EXEC operations: " + result.execs.size());
            }}
            if (!result.calls.isEmpty()) {{
                System.out.println("CALL operations: " + result.calls.size());
            }}
        }} catch (Exception e) {{
            System.err.println("Execution error: " + e.getMessage());
            e.printStackTrace();
            System.exit(1);
        }}

        dataSource.close();
    }}
}}
"""
