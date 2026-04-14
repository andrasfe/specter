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

    /**
     * GROUP-item layouts: maps a parent name to the ordered list of its
     * leaf children, each described as {{@code String[]{{name, kind, length}}}}.
     * When a parent is read via {{@link #get}} the value is recomposed
     * by concatenating each child's PIC-padded current value; when a
     * parent is written the value is split back into the children. This
     * mirrors COBOL's flat-storage layout for groups so reference
     * modifiers and DISPLAYs of group items match the COBOL binary.
     *
     * <p>Populated by the generated program class via
     * {{@link #registerGroupLayouts}}.
     */
    public static final Map<String, Object[][]> GROUP_LAYOUTS = new LinkedHashMap<>();

    /** Install GROUP layouts (called once per JVM by the generated Program). */
    public static void registerGroupLayouts(Map<String, Object[][]> layouts) {{
        GROUP_LAYOUTS.putAll(layouts);
    }}

    // -----------------------------------------------------------------------
    // REDEFINES groups (byte-buffer storage for memory aliasing)
    // -----------------------------------------------------------------------

    /** Field → buffer membership for REDEFINES routing. ``Object[5]``:
     *  ``{{groupId(String), offset(Integer), length(Integer), kind(String),
     *  signed(Boolean), digits(Integer)}}``. The kind is one of ``binary``,
     *  ``alpha``, ``numeric`` (display), ``packed``, ``group``. */
    public static final Map<String, Object[]> REDEFINES_FIELD = new LinkedHashMap<>();

    /** Group id → byte buffer width. */
    public static final Map<String, Integer> REDEFINES_GROUP_WIDTH = new LinkedHashMap<>();

    /** Per-state byte buffers — lazily allocated on first access of any
     *  member of a REDEFINES group. */
    private final Map<String, byte[]> redefinesBuffers = new LinkedHashMap<>();

    /** Install REDEFINES layouts (called once per JVM by the generated
     *  Program class). Layouts are static; per-state buffers are lazy. */
    public static void registerRedefinesLayouts(
            Map<String, Integer> groupWidths,
            Map<String, Object[]> fieldEntries) {{
        REDEFINES_GROUP_WIDTH.putAll(groupWidths);
        REDEFINES_FIELD.putAll(fieldEntries);
    }}

    private byte[] bufferFor(String groupId) {{
        byte[] buf = redefinesBuffers.get(groupId);
        if (buf != null) return buf;
        Integer width = REDEFINES_GROUP_WIDTH.get(groupId);
        if (width == null) return null;
        buf = new byte[width];
        // Initialise alpha-style with spaces (COBOL default) — for binary
        // members the value reads as a small integer (likely 0x202020...).
        java.util.Arrays.fill(buf, (byte) ' ');
        redefinesBuffers.put(groupId, buf);
        return buf;
    }}

    /** Read a REDEFINES member from its backing byte buffer. */
    private Object redefinesGet(Object[] entry) {{
        String groupId = (String) entry[0];
        int offset = (Integer) entry[1];
        int length = (Integer) entry[2];
        String kind = (String) entry[3];
        boolean signed = (Boolean) entry[4];
        byte[] buf = bufferFor(groupId);
        if (buf == null || length <= 0) return " ";
        int end = Math.min(offset + length, buf.length);
        if ("alpha".equals(kind) || "group".equals(kind)) {{
            char[] out = new char[end - offset];
            for (int i = 0; i < out.length; i++) {{
                out[i] = (char) (buf[offset + i] & 0xFF);
            }}
            return new String(out);
        }}
        if ("binary".equals(kind)) {{
            long n = 0;
            for (int i = offset; i < end; i++) {{
                n = (n << 8) | (buf[i] & 0xFF);
            }}
            if (signed && length > 0 && (buf[offset] & 0x80) != 0) {{
                long mask = (1L << (8 * length)) - 1L;
                n = n - mask - 1L;
            }}
            return n;
        }}
        // "numeric" (DISPLAY): bytes are ASCII digits. Return the digit
        // string as-is so DISPLAY emits zero-padded numbers naturally.
        char[] out = new char[end - offset];
        for (int i = 0; i < out.length; i++) {{
            out[i] = (char) (buf[offset + i] & 0xFF);
        }}
        return new String(out);
    }}

    /** Write a REDEFINES member into its backing byte buffer. */
    private void redefinesPut(Object[] entry, Object value) {{
        String groupId = (String) entry[0];
        int offset = (Integer) entry[1];
        int length = (Integer) entry[2];
        String kind = (String) entry[3];
        boolean signed = (Boolean) entry[4];
        byte[] buf = bufferFor(groupId);
        if (buf == null || length <= 0) return;
        if ("alpha".equals(kind) || "group".equals(kind)) {{
            String s = value == null ? "" : value.toString();
            for (int i = 0; i < length; i++) {{
                int dst = offset + i;
                if (dst >= buf.length) break;
                buf[dst] = (byte) (i < s.length() ? s.charAt(i) : ' ');
            }}
            return;
        }}
        if ("binary".equals(kind)) {{
            long n;
            if (value instanceof Number) {{
                n = ((Number) value).longValue();
            }} else {{
                try {{
                    n = (long) Double.parseDouble(String.valueOf(value).trim());
                }} catch (NumberFormatException e) {{
                    n = 0;
                }}
            }}
            // Encode as big-endian, two's-complement for signed.
            for (int i = length - 1; i >= 0; i--) {{
                int dst = offset + i;
                if (dst >= buf.length) {{
                    n >>= 8;
                    continue;
                }}
                buf[dst] = (byte) (n & 0xFF);
                n >>= 8;
            }}
            return;
        }}
        // "numeric" (DISPLAY): write zero-padded ASCII digits.
        long n;
        if (value instanceof Number) {{
            n = ((Number) value).longValue();
        }} else {{
            try {{
                n = (long) Double.parseDouble(String.valueOf(value).trim());
            }} catch (NumberFormatException e) {{
                n = 0;
            }}
        }}
        n = Math.abs(n);
        for (int i = length - 1; i >= 0; i--) {{
            int dst = offset + i;
            if (dst >= buf.length) {{
                n /= 10;
                continue;
            }}
            buf[dst] = (byte) ('0' + (n % 10));
            n /= 10;
        }}
    }}

    // -----------------------------------------------------------------------
    // Overrides
    // -----------------------------------------------------------------------

    /**
     * Returns the value mapped to {{@code key}}, or a single space {{@code " "}}
     * if the key is absent. For GROUP items the value is composed from
     * the children's current values (PIC-padded). This mirrors COBOL's
     * default-spaces behavior for uninitialised alphanumeric variables.
     */
    @Override
    public Object get(Object key) {{
        if (key instanceof String) {{
            // REDEFINES routing wins (most specific): fields registered in
            // a byte-aliased group always read from the buffer.
            Object[] redef = REDEFINES_FIELD.get(key);
            if (redef != null) {{
                return redefinesGet(redef);
            }}
            Object[][] layout = GROUP_LAYOUTS.get(key);
            if (layout != null && layout.length > 0) {{
                StringBuilder sb = new StringBuilder();
                for (Object[] child : layout) {{
                    String name = (String) child[0];
                    String kind = (String) child[1];
                    int length = (Integer) child[2];
                    sb.append(formatChild(name, kind, length));
                }}
                return sb.toString();
            }}
        }}
        Object v = super.get(key);
        return v != null ? v : " ";
    }}

    /** Format one child for group composition: numeric → zero-padded
     *  unless the stored value already contains non-digit characters (a
     *  legitimate side effect of COBOL's MOVE-alpha-to-numeric, which
     *  stores raw bytes); alpha → space-padded right. */
    private String formatChild(String name, String kind, int length) {{
        Object raw = super.get(name);
        if (raw == null) {{
            // Missing child: alpha → spaces, numeric → zeros.
            char fill = "alpha".equals(kind) ? ' ' : '0';
            char[] buf = new char[length];
            java.util.Arrays.fill(buf, fill);
            return new String(buf);
        }}
        String s;
        boolean isNumeric = "numeric".equals(kind) || "packed".equals(kind) || "comp".equals(kind);
        if (isNumeric) {{
            // Numbers: format zero-padded. Strings: if the string is all
            // digits (possibly with leading sign / spaces COBOL would have
            // truncated), parse-and-format; otherwise the bytes are
            // literal (e.g. MOVE 'X' TO PIC 9 leaves byte 'X' in place).
            if (raw instanceof Number) {{
                long n = Math.abs(((Number) raw).longValue());
                s = String.format("%0" + length + "d", n % (long) Math.pow(10, length));
            }} else {{
                String rawStr = String.valueOf(raw);
                String trimmed = rawStr.trim();
                boolean digitsOnly = !trimmed.isEmpty()
                        && trimmed.chars().allMatch(c -> Character.isDigit(c)
                                || c == '+' || c == '-');
                if (digitsOnly) {{
                    long n;
                    try {{
                        n = Math.abs(Long.parseLong(trimmed));
                    }} catch (NumberFormatException e) {{
                        n = 0;
                    }}
                    s = String.format("%0" + length + "d", n % (long) Math.pow(10, length));
                }} else {{
                    // Non-numeric content stored in a numeric field: keep
                    // the bytes verbatim, padded/truncated to width.
                    s = rawStr;
                    if (s.length() < length) {{
                        StringBuilder sb = new StringBuilder(s);
                        for (int i = s.length(); i < length; i++) sb.append(' ');
                        s = sb.toString();
                    }} else if (s.length() > length) {{
                        s = s.substring(0, length);
                    }}
                }}
            }}
        }} else {{
            // Alpha: trim trailing spaces, right-pad with spaces.
            s = String.valueOf(raw);
            if (s.length() < length) {{
                StringBuilder sb = new StringBuilder(s);
                for (int i = s.length(); i < length; i++) sb.append(' ');
                s = sb.toString();
            }} else if (s.length() > length) {{
                s = s.substring(0, length);
            }}
        }}
        return s;
    }}

    /**
     * Override put: when the key is a GROUP parent, split the new value
     * across the children using the registered layout.
     */
    @Override
    public Object put(String key, Object value) {{
        // REDEFINES routing wins.
        Object[] redef = REDEFINES_FIELD.get(key);
        if (redef != null) {{
            redefinesPut(redef, value);
            return null;
        }}
        Object[][] layout = GROUP_LAYOUTS.get(key);
        if (layout != null && layout.length > 0 && value != null) {{
            String s = String.valueOf(value);
            int offset = 0;
            for (Object[] child : layout) {{
                String name = (String) child[0];
                String kind = (String) child[1];
                int length = (Integer) child[2];
                String chunk;
                if (offset >= s.length()) {{
                    char fill = "alpha".equals(kind) ? ' ' : '0';
                    char[] buf = new char[length];
                    java.util.Arrays.fill(buf, fill);
                    chunk = new String(buf);
                }} else if (offset + length <= s.length()) {{
                    chunk = s.substring(offset, offset + length);
                }} else {{
                    chunk = s.substring(offset);
                    StringBuilder sb = new StringBuilder(chunk);
                    char fill = "alpha".equals(kind) ? ' ' : '0';
                    for (int i = chunk.length(); i < length; i++) sb.append(fill);
                    chunk = sb.toString();
                }}
                super.put(name, chunk);
                offset += length;
            }}
            return null;
        }}
        return super.put(key, value);
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
     * Check whether a value is numeric per COBOL's IS NUMERIC class test:
     * every character must be a digit (plus optionally a leading sign).
     *
     * <p>This is STRICTER than {{@link Double#parseDouble}}: embedded or
     * trailing spaces make the value NOT NUMERIC, matching GnuCOBOL's
     * runtime behaviour. Examples:
     * <ul>
     *   <li>{{@code "123"}} → true
     *   <li>{{@code "+42"}} → true
     *   <li>{{@code "0 "}} (trailing space) → <b>false</b> (mainframe divergence)
     *   <li>{{@code " 42"}} (leading space) → <b>false</b>
     *   <li>{{@code ""}} → false
     * </ul>
     */
    public static boolean isNumeric(Object v) {{
        if (v == null) {{
            return false;
        }}
        if (v instanceof Number) {{
            return true;
        }}
        String s = String.valueOf(v);
        if (s.isEmpty()) {{
            return false;
        }}
        int start = 0;
        if (s.charAt(0) == '+' || s.charAt(0) == '-') {{
            if (s.length() == 1) return false;
            start = 1;
        }}
        boolean dotSeen = false;
        for (int i = start; i < s.length(); i++) {{
            char c = s.charAt(i);
            if (c == '.' && !dotSeen) {{
                dotSeen = true;
                continue;
            }}
            if (c < '0' || c > '9') {{
                return false;
            }}
        }}
        return true;
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

    /**
     * Route a synchronous outbound CALL to an external program through
     * an implementation-specific channel.
     *
     * <p>The default implementation delegates to
     * {{@link #applyStubOutcome(ProgramState, String)}} with key
     * {{@code "CALL:" + programName}} (FIFO semantics). The JDBC-backed
     * implementation overrides this to issue an HTTP POST to the
     * configured REST endpoint (e.g. WireMock) and map the JSON response
     * keys back into {{@link ProgramState}}.
     *
     * @param state       the current program state
     * @param programName the COBOL program name being called (e.g. {{@code "CUSTAPI"}})
     * @param inputVars   COBOL variable names to serialize as the request body
     * @param outputVars  COBOL variable names the response is expected to populate
     *                    (informational; the response keys are used as-is)
     */
    default void callProgram(
            ProgramState state,
            String programName,
            List<String> inputVars,
            List<String> outputVars) {{
        Map<String, Object> entry = new java.util.LinkedHashMap<>();
        entry.put("name", programName);
        state.calls.add(entry);
        applyStubOutcome(state, "CALL:" + programName);
    }}

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

    /**
     * Per-key memory of the most recently observed status variable. On
     * FIFO + defaults exhaustion for a read-style op (READ:* / CICS-READ /
     * DLI-G*), this var gets set to "10" to mirror the COBOL binary's
     * MOCK-EOF behaviour and let PERFORM UNTIL loops terminate naturally.
     */
    private final Map<String, String> stubStatusVars = new LinkedHashMap<>();

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
                if (pair == null || pair.length < 2 || pair[0] == null) continue;
                String var = pair[0].toString();
                state.put(var, pair[1]);
                // Remember the var for MOCK-EOF emission on later exhaustion.
                stubStatusVars.put(key, var);
            }}
        }} else {{
            // Both FIFO and defaults exhausted. Mirror COBOL's MOCK-EOF
            // for read-style ops so PERFORM UNTIL <eof> can terminate.
            String upper = key.toUpperCase();
            boolean isRead = upper.startsWith("READ:")
                    || upper.startsWith("CICS-READ")
                    || upper.startsWith("DLI-G");
            if (isRead) {{
                String sv = stubStatusVars.get(key);
                if (sv != null) {{
                    state.put(sv, "10");
                }}
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

import com.google.gson.Gson;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import com.rabbitmq.client.Channel;
import com.rabbitmq.client.ConnectionFactory;
import com.rabbitmq.client.GetResponse;

import org.apache.hc.client5.http.classic.methods.HttpPost;
import org.apache.hc.client5.http.impl.classic.CloseableHttpClient;
import org.apache.hc.client5.http.impl.classic.CloseableHttpResponse;
import org.apache.hc.client5.http.impl.classic.HttpClients;
import org.apache.hc.core5.http.ContentType;
import org.apache.hc.core5.http.io.entity.EntityUtils;
import org.apache.hc.core5.http.io.entity.StringEntity;

import java.nio.charset.StandardCharsets;
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
 * {{@link StubExecutor}} implementation backed by real JDBC, RabbitMQ (AMQP),
 * and HTTP (for CALL-to-REST routing) connections.
 *
 * <p>CICS READ / DLI GU / ISRT / REPL operations are translated to SQL
 * statements via JDBC. MQ CALL operations are translated to RabbitMQ
 * AMQP basicGet/basicPublish on a queue named after the COBOL queue
 * variable. Synchronous CALLs to external programs are routed through
 * {{@link #callProgram(ProgramState, String, List, List)}} as HTTP POSTs
 * to {{@link AppConfig#getCallBaseUrl()}}.
 *
 * <p>Implements {{@link AutoCloseable}} so it can be used in
 * try-with-resources blocks.
 */
public class JdbcStubExecutor implements StubExecutor, AutoCloseable {{

    private final javax.sql.DataSource dataSource;
    private Connection conn;

    /* RabbitMQ fields -- nullable (broker is optional at runtime). */
    private final ConnectionFactory amqpFactory;
    private com.rabbitmq.client.Connection amqpConn;
    private Channel amqpChannel;
    private String amqpCurrentQueue;

    /* HTTP client for synchronous outbound CALL routing. */
    private final CloseableHttpClient http = HttpClients.createDefault();
    private final Gson gson = new Gson();

    /**
     * Create a JdbcStubExecutor.
     *
     * @param dataSource  JDBC DataSource for database operations
     * @param amqpFactory RabbitMQ ConnectionFactory (may be {{@code null}}
     *                    to disable MQ — operations will fall back to FIFO stubs)
     */
    public JdbcStubExecutor(javax.sql.DataSource dataSource, ConnectionFactory amqpFactory) {{
        this.dataSource = dataSource;
        this.amqpFactory = amqpFactory;
    }}

    private Connection getConnection() throws SQLException {{
        if (conn == null || conn.isClosed()) {{
            conn = dataSource.getConnection();
        }}
        return conn;
    }}

    private Channel ensureAmqpChannel() throws Exception {{
        if (amqpFactory == null) {{
            return null;
        }}
        if (amqpConn == null || !amqpConn.isOpen()) {{
            amqpConn = amqpFactory.newConnection();
        }}
        if (amqpChannel == null || !amqpChannel.isOpen()) {{
            amqpChannel = amqpConn.createChannel();
        }}
        return amqpChannel;
    }}

    /**
     * Close all held connections (JDBC, AMQP, HTTP).
     */
    @Override
    public void close() {{
        try {{
            if (conn != null && !conn.isClosed()) {{
                conn.close();
            }}
        }} catch (SQLException ignored) {{
        }}
        closeAmqp();
        try {{
            http.close();
        }} catch (Exception ignored) {{
        }}
    }}

    private void closeAmqp() {{
        try {{
            if (amqpChannel != null && amqpChannel.isOpen()) {{
                amqpChannel.close();
            }}
        }} catch (Exception ignored) {{
        }}
        try {{
            if (amqpConn != null && amqpConn.isOpen()) {{
                amqpConn.close();
            }}
        }} catch (Exception ignored) {{
        }}
        amqpChannel = null;
        amqpConn = null;
        amqpCurrentQueue = null;
    }}

    // -------------------------------------------------------------------
    // Stub outcome support (delegates to DefaultStubExecutor logic)
    // -------------------------------------------------------------------

    private final Map<String, String> stubStatusVars = new LinkedHashMap<>();

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
                if (pair == null || pair.length < 2 || pair[0] == null) continue;
                String var = pair[0].toString();
                state.put(var, pair[1]);
                stubStatusVars.put(key, var);
            }}
        }} else {{
            String upper = key.toUpperCase();
            boolean isRead = upper.startsWith("READ:")
                    || upper.startsWith("CICS-READ")
                    || upper.startsWith("DLI-G");
            if (isRead) {{
                String sv = stubStatusVars.get(key);
                if (sv != null) state.put(sv, "10");
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
        try {{
            Channel ch = ensureAmqpChannel();
            if (ch == null) {{
                Map<String, Object> entry = new LinkedHashMap<>();
                entry.put("kind", "CICS");
                entry.put("text", "RETRIEVE INTO(" + (intoVar != null ? intoVar : "") + ")");
                state.execs.add(entry);
                applyStubOutcome(state, "CICS");
                return;
            }}
            String qName = (amqpCurrentQueue != null) ? amqpCurrentQueue : "specter.cics.retrieve";
            ch.queueDeclare(qName, true, false, false, null);
            GetResponse resp = ch.basicGet(qName, true);
            if (resp != null && intoVar != null) {{
                state.put(intoVar, new String(resp.getBody(), StandardCharsets.UTF_8));
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
        try {{
            Channel ch = ensureAmqpChannel();
            if (ch == null) {{
                Map<String, Object> entry = new LinkedHashMap<>();
                entry.put("kind", "CICS");
                entry.put("text", "WRITEQ TD QUEUE(" + (queue != null ? queue : "") + ")");
                state.execs.add(entry);
                applyStubOutcome(state, "CICS");
                return;
            }}
            String qName = (queue != null && !queue.isBlank()) ? queue : "specter.cics.td";
            ch.queueDeclare(qName, true, false, false, null);
            String body = (fromRecord != null) ? state.get(fromRecord).toString() : "";
            ch.basicPublish("", qName, null, body.getBytes(StandardCharsets.UTF_8));
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
        if (amqpFactory == null) {{
            dummyCall(state, "MQOPEN");
            return;
        }}
        try {{
            Channel ch = ensureAmqpChannel();
            String qName = (queueNameVar != null) ? state.get(queueNameVar).toString().trim() : "";
            if (qName.isEmpty()) qName = "SPECTER.DEFAULT";
            ch.queueDeclare(qName, true, false, false, null);
            amqpCurrentQueue = qName;
            state.put("WS-COMPLETION-CODE", 0);  // MQCC_OK
        }} catch (Exception e) {{
            System.err.println("MQ OPEN failed: " + e.getMessage());
            state.put("WS-COMPLETION-CODE", 2);  // MQCC_FAILED
            state.put("WS-REASON-CODE", 2085);   // MQRC_UNKNOWN_OBJECT_NAME
        }}
    }}

    @Override
    public void mqGet(ProgramState state, String bufferVar, String datalenVar, String waitIntervalVar) {{
        if (amqpFactory == null || amqpCurrentQueue == null) {{
            dummyCall(state, "MQGET");
            return;
        }}
        try {{
            Channel ch = ensureAmqpChannel();
            GetResponse resp = ch.basicGet(amqpCurrentQueue, true);
            if (resp != null && bufferVar != null) {{
                String text = new String(resp.getBody(), StandardCharsets.UTF_8);
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
        if (amqpFactory == null) {{
            dummyCall(state, "MQPUT1");
            return;
        }}
        try {{
            Channel ch = ensureAmqpChannel();
            String qName = (replyQueueVar != null) ? state.get(replyQueueVar).toString().trim() : "";
            if (qName.isEmpty()) qName = (amqpCurrentQueue != null) ? amqpCurrentQueue : "SPECTER.DEFAULT";
            ch.queueDeclare(qName, true, false, false, null);
            String body = (bufferVar != null) ? state.get(bufferVar).toString() : "";
            ch.basicPublish("", qName, null, body.getBytes(StandardCharsets.UTF_8));
            state.put("WS-COMPLETION-CODE", 0);
        }} catch (Exception e) {{
            System.err.println("MQ PUT1 failed: " + e.getMessage());
            state.put("WS-COMPLETION-CODE", 2);
            state.put("WS-REASON-CODE", 2085);
        }}
    }}

    @Override
    public void mqClose(ProgramState state) {{
        closeAmqp();
        state.put("WS-COMPLETION-CODE", 0);
    }}

    // -------------------------------------------------------------------
    // Synchronous outbound CALL routing -> REST
    // -------------------------------------------------------------------

    @Override
    public void callProgram(
            ProgramState state,
            String programName,
            List<String> inputVars,
            List<String> outputVars) {{
        // Record the call for trace / Mockito verification
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("name", programName);
        state.calls.add(entry);

        String url = AppConfig.getCallBaseUrl() + "/" + programName.toLowerCase();
        Map<String, Object> payload = new LinkedHashMap<>();
        if (inputVars != null) {{
            for (String v : inputVars) {{
                payload.put(v, state.get(v));
            }}
        }}

        HttpPost req = new HttpPost(url);
        req.setEntity(new StringEntity(gson.toJson(payload), ContentType.APPLICATION_JSON));

        boolean restOk = false;
        try (CloseableHttpResponse resp = http.execute(req)) {{
            int status = resp.getCode();
            String body = resp.getEntity() != null
                ? EntityUtils.toString(resp.getEntity(), StandardCharsets.UTF_8)
                : "";
            if (status >= 200 && status < 300 && body != null && !body.isBlank()) {{
                JsonElement parsed = JsonParser.parseString(body);
                if (parsed.isJsonObject()) {{
                    JsonObject obj = parsed.getAsJsonObject();
                    for (Map.Entry<String, JsonElement> e : obj.entrySet()) {{
                        state.put(e.getKey(), jsonToJava(e.getValue()));
                    }}
                    restOk = true;
                }}
            }}
        }} catch (Exception e) {{
            System.err.println("CALL " + programName + " HTTP failure: " + e.getMessage());
        }}

        // Always update the stub log so Mockito spies + uncovered-report can
        // see that this CALL was reached, regardless of HTTP success.
        if (restOk) {{
            state.stubLog.add(new Object[]{{"CALL:" + programName, null}});
        }} else {{
            applyStubOutcome(state, "CALL:" + programName);
        }}
    }}

    private static Object jsonToJava(JsonElement e) {{
        if (e == null || e.isJsonNull()) return "";
        if (e.isJsonPrimitive()) {{
            com.google.gson.JsonPrimitive p = e.getAsJsonPrimitive();
            if (p.isBoolean()) return p.getAsBoolean();
            if (p.isNumber()) {{
                double d = p.getAsDouble();
                if (d == Math.floor(d) && !Double.isInfinite(d)) {{
                    long l = p.getAsLong();
                    if (l >= Integer.MIN_VALUE && l <= Integer.MAX_VALUE) return (int) l;
                    return l;
                }}
                return d;
            }}
            return p.getAsString();
        }}
        return e.toString();
    }}
}}
"""

# ---------------------------------------------------------------------------
# AppConfig.java
# ---------------------------------------------------------------------------

APP_CONFIG_JAVA = """\
package {package_name};

/**
 * Environment-variable-based configuration for database, AMQP (RabbitMQ),
 * and the REST base URL used for outbound CALL routing.
 *
 * <p>Reads {{@code SPECTER_DB_*}}, {{@code SPECTER_AMQP_*}}, and
 * {{@code SPECTER_CALL_BASE_URL}} from the environment with sensible
 * localhost defaults suitable for the generated docker-compose.
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

    public static String getAmqpHost() {{
        return env("SPECTER_AMQP_HOST", "localhost");
    }}

    public static int getAmqpPort() {{
        String v = env("SPECTER_AMQP_PORT", "5672");
        try {{
            return Integer.parseInt(v.trim());
        }} catch (NumberFormatException e) {{
            return 5672;
        }}
    }}

    public static String getAmqpUser() {{
        return env("SPECTER_AMQP_USER", "specter");
    }}

    public static String getAmqpPassword() {{
        return env("SPECTER_AMQP_PASSWORD", "specter");
    }}

    public static String getAmqpVirtualHost() {{
        return env("SPECTER_AMQP_VHOST", "/");
    }}

    /**
     * Base URL for synchronous outbound CALLs (e.g. WireMock sidecar).
     * Defaults to {{@code http://localhost:8080}} for local dev.
     */
    public static String getCallBaseUrl() {{
        return env("SPECTER_CALL_BASE_URL", "http://localhost:8080");
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

import com.rabbitmq.client.ConnectionFactory;
import com.zaxxer.hikari.HikariConfig;
import com.zaxxer.hikari.HikariDataSource;

/**
 * Docker / standalone entrypoint for {{@link {program_class_name}}}.
 *
 * <p>Creates a {{@link HikariDataSource}} from {{@link AppConfig}},
 * configures a RabbitMQ {{@link ConnectionFactory}} for MQ-style
 * operations, wires a {{@link JdbcStubExecutor}}, runs the program,
 * and prints results.
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

        // RabbitMQ connection factory (lazy connect inside the executor)
        ConnectionFactory amqpFactory = new ConnectionFactory();
        amqpFactory.setHost(AppConfig.getAmqpHost());
        amqpFactory.setPort(AppConfig.getAmqpPort());
        amqpFactory.setUsername(AppConfig.getAmqpUser());
        amqpFactory.setPassword(AppConfig.getAmqpPassword());
        amqpFactory.setVirtualHost(AppConfig.getAmqpVirtualHost());

        // Wire and run
        try (JdbcStubExecutor stubs = new JdbcStubExecutor(dataSource, amqpFactory)) {{
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

# ---------------------------------------------------------------------------
# CicsProgram.java  (multi-program XCTL routing interface)
# ---------------------------------------------------------------------------

CICS_PROGRAM_JAVA = """\
package {package_name};

import java.util.List;

/**
 * Common interface for CICS programs participating in XCTL routing.
 *
 * <p>Each generated program class implements this interface so that
 * {{@link MultiProgramRunner}} can invoke any program polymorphically
 * and route XCTL transfers between them.
 */
public interface CicsProgram {{

    /**
     * Execute the program with the given state.
     *
     * @param state the shared program state carried across XCTL transfers
     * @return the state after execution
     */
    ProgramState run(ProgramState state);

    /**
     * Return the COBOL PROGRAM-ID (e.g. {{@code "COSGN00C"}}).
     */
    String programId();

    /**
     * Return the BMS screen layout for this program, or an empty list
     * if the program has no terminal screen.
     */
    List<CicsScreen.Field> screenLayout();

    /**
     * Seed per-program literal constants (LIT-*, CCDA-*) into the state.
     *
     * <p>Called by {{@link MultiProgramRunner}} before each program
     * execution to ensure COBOL literals like LIT-MENUPGM, LIT-THISMAP,
     * etc. are correctly set for the target program.
     *
     * @param state the program state to seed
     */
    void initState(ProgramState state);
}}
"""
