"""Java templates: CobolSnapshot POJO + EquivalenceAssert.

These two classes are emitted alongside the integration test class. At test
time, each parameterized test loads ``/cobol_snapshots/<tc_id>.json`` from
the classpath (written by ``specter.cobol_snapshot.capture_snapshots``)
and asserts that the Java program's execution matches the COBOL ground
truth on:

- ``abended`` — strict
- ``displays`` — strict (after trailing-space normalisation)
- ``paragraphs_covered`` — strict order
- ``final_state[k]`` — strict (after numeric/spaces normalisation) for
  every key in the snapshot's final_state that is also present in the
  Java state

``branches`` is captured for diagnostic value but NOT compared — branch
IDs are independently assigned by the COBOL probe inserter and the Java
generator and are not cross-tool comparable.
"""

# ---------------------------------------------------------------------------
# CobolSnapshot.java -- minimal POJO + Gson loader
# ---------------------------------------------------------------------------

COBOL_SNAPSHOT_JAVA = """\
package {package_name};

import com.google.gson.Gson;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * COBOL ground-truth execution snapshot for a single test case.
 *
 * <p>Loaded from {{@code /cobol_snapshots/<tc_id>.json}} on the test
 * classpath and consumed by {{@link EquivalenceAssert}}.
 */
public class CobolSnapshot {{

    private static final Gson GSON = new Gson();

    public final String id;
    public final boolean abended;
    public final List<String> displays;
    public final List<String> paragraphsCovered;
    public final List<String> branches;
    public final List<String> stubLogKeys;
    public final Map<String, String> finalState;
    public final int returnCode;
    public final String error;

    public CobolSnapshot(
            String id,
            boolean abended,
            List<String> displays,
            List<String> paragraphsCovered,
            List<String> branches,
            List<String> stubLogKeys,
            Map<String, String> finalState,
            int returnCode,
            String error) {{
        this.id = id;
        this.abended = abended;
        this.displays = displays != null ? displays : new ArrayList<>();
        this.paragraphsCovered = paragraphsCovered != null ? paragraphsCovered : new ArrayList<>();
        this.branches = branches != null ? branches : new ArrayList<>();
        this.stubLogKeys = stubLogKeys != null ? stubLogKeys : new ArrayList<>();
        this.finalState = finalState != null ? finalState : new LinkedHashMap<>();
        this.returnCode = returnCode;
        this.error = error;
    }}

    /**
     * Load a snapshot from {{@code /cobol_snapshots/<tc_id>.json}}.
     *
     * @return the parsed snapshot, or {{@code null}} if the resource is absent.
     */
    public static CobolSnapshot loadFor(Class<?> ctx, String tcId) {{
        String resource = "/cobol_snapshots/" + tcId + ".json";
        try (InputStream is = ctx.getResourceAsStream(resource)) {{
            if (is == null) return null;
            String body = new String(is.readAllBytes(), StandardCharsets.UTF_8);
            JsonObject obj = GSON.fromJson(body, JsonObject.class);
            return fromJson(obj);
        }} catch (IOException ex) {{
            return null;
        }}
    }}

    private static CobolSnapshot fromJson(JsonObject obj) {{
        String id = obj.has("id") ? obj.get("id").getAsString() : "";
        boolean abended = obj.has("abended") && obj.get("abended").getAsBoolean();
        List<String> displays = strList(obj, "displays");
        List<String> paragraphsCovered = strList(obj, "paragraphs_covered");
        List<String> branches = strList(obj, "branches");
        List<String> stubLogKeys = strList(obj, "stub_log_keys");
        Map<String, String> finalState = strMap(obj, "final_state");
        int returnCode = obj.has("return_code") ? obj.get("return_code").getAsInt() : 0;
        String error = obj.has("error") && !obj.get("error").isJsonNull()
                ? obj.get("error").getAsString() : null;
        return new CobolSnapshot(
                id, abended, displays, paragraphsCovered, branches, stubLogKeys,
                finalState, returnCode, error);
    }}

    private static List<String> strList(JsonObject obj, String key) {{
        List<String> out = new ArrayList<>();
        if (!obj.has(key) || !obj.get(key).isJsonArray()) return out;
        for (JsonElement e : obj.getAsJsonArray(key)) {{
            out.add(e.isJsonNull() ? "" : e.getAsString());
        }}
        return out;
    }}

    private static Map<String, String> strMap(JsonObject obj, String key) {{
        Map<String, String> out = new LinkedHashMap<>();
        if (!obj.has(key) || !obj.get(key).isJsonObject()) return out;
        for (Map.Entry<String, JsonElement> e : obj.getAsJsonObject(key).entrySet()) {{
            JsonElement v = e.getValue();
            if (v == null || v.isJsonNull()) {{
                out.put(e.getKey(), "");
            }} else if (v.isJsonPrimitive()) {{
                out.put(e.getKey(), v.getAsString());
            }} else {{
                out.put(e.getKey(), v.toString());
            }}
        }}
        return out;
    }}
}}
"""

# ---------------------------------------------------------------------------
# EquivalenceAssert.java
# ---------------------------------------------------------------------------

EQUIVALENCE_ASSERT_JAVA = """\
package {package_name};

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Pattern;

/**
 * Assert that a generated Java program's execution is equivalent to the
 * captured COBOL ground truth.
 *
 * <p>Strict checks: ``abended``, ``displays`` (in order), paragraph trace
 * (in order), and final state values for the keys recorded in the snapshot.
 * Branch IDs are NOT compared — they are independently assigned by the
 * COBOL probe inserter and the Java generator.
 *
 * <p>Value normalisation mirrors {{@code specter.cobol_snapshot.normalize_value}}:
 * trim trailing spaces (PIC X padding); collapse leading-zero numerics to
 * canonical form; treat {{@code null}} / "" / single space as empty.
 */
public final class EquivalenceAssert {{

    private static final Pattern NUMERIC = Pattern.compile("^[+-]?\\\\d+(\\\\.\\\\d+)?$");

    private EquivalenceAssert() {{}}

    /**
     * Assert program ``state`` is equivalent to the captured COBOL ``snapshot``.
     *
     * <p>When the snapshot is {{@code null}} (no resource present), the call
     * is a no-op so existing tests still run when snapshots aren't available.
     */
    public static void assertEquivalent(CobolSnapshot snapshot, ProgramState state) {{
        if (snapshot == null) return;

        List<String> diffs = new ArrayList<>();

        if (snapshot.abended != state.abended) {{
            diffs.add(String.format(
                "abended: snapshot=%s, java=%s", snapshot.abended, state.abended));
        }}

        // Displays: strict order match after normalisation.
        List<String> snapDisplays = normalizeList(snapshot.displays);
        List<String> javaDisplays = normalizeList(state.displays);
        if (!snapDisplays.equals(javaDisplays)) {{
            diffs.add(displayDiff(snapDisplays, javaDisplays));
        }}

        // Paragraph trace: compare deduplicated first-occurrence order.
        // COBOL's snapshot trace is the dedup'd unique-paragraph list
        // (parse_trace skips repeats), so Java's full execution trace
        // (which records every Paragraph.execute call, including loop
        // iterations) must be deduplicated the same way before equality.
        List<String> javaUniqueTrace = dedupPreserveOrder(state.trace);
        if (!snapshot.paragraphsCovered.equals(javaUniqueTrace)) {{
            diffs.add(traceDiff(snapshot.paragraphsCovered, javaUniqueTrace));
        }}

        // Final state: every key recorded in the snapshot must match in Java.
        for (Map.Entry<String, String> e : snapshot.finalState.entrySet()) {{
            String key = e.getKey();
            String snapValue = normalize(e.getValue());
            String javaValue = normalize(state.get(key));
            if (!snapValue.equals(javaValue)) {{
                diffs.add(String.format(
                    "final_state[%s]: snapshot=%s, java=%s",
                    key, quote(snapValue), quote(javaValue)));
            }}
        }}

        if (!diffs.isEmpty()) {{
            StringBuilder msg = new StringBuilder();
            msg.append("COBOL/Java equivalence FAILED for tc=")
               .append(snapshot.id).append("\\n");
            for (String d : diffs) {{
                msg.append("  - ").append(d).append("\\n");
            }}
            throw new AssertionError(msg.toString());
        }}
    }}

    // -----------------------------------------------------------------------
    // Normalisation helpers (mirror cobol_snapshot.normalize_value)
    // -----------------------------------------------------------------------

    static String normalize(Object v) {{
        if (v == null) return "";
        if (v instanceof Boolean) return ((Boolean) v) ? "true" : "false";
        if (v instanceof Number) {{
            double d = ((Number) v).doubleValue();
            if (d == Math.floor(d) && !Double.isInfinite(d)
                    && d >= Long.MIN_VALUE && d <= Long.MAX_VALUE) {{
                return Long.toString((long) d);
            }}
            String s = Double.toString(d);
            if (s.contains(".")) {{
                s = stripTrailing(s, '0');
                if (s.endsWith(".")) s = s.substring(0, s.length() - 1);
            }}
            return s;
        }}
        String s = String.valueOf(v);
        s = stripTrailing(s, ' ');
        if (s.isEmpty()) return "";
        if (NUMERIC.matcher(s).matches()) {{
            String sign = "";
            if (s.charAt(0) == '+' || s.charAt(0) == '-') {{
                sign = s.charAt(0) == '-' ? "-" : "";
                s = s.substring(1);
            }}
            if (s.contains(".")) {{
                int dot = s.indexOf('.');
                String intPart = stripLeading(s.substring(0, dot), '0');
                String decPart = stripTrailing(s.substring(dot + 1), '0');
                if (intPart.isEmpty()) intPart = "0";
                if (decPart.isEmpty()) return sign + intPart;
                return sign + intPart + "." + decPart;
            }}
            String stripped = stripLeading(s, '0');
            return sign + (stripped.isEmpty() ? "0" : stripped);
        }}
        return s;
    }}

    private static List<String> dedupPreserveOrder(List<String> in) {{
        java.util.LinkedHashSet<String> seen = new java.util.LinkedHashSet<>();
        for (String s : in) seen.add(s);
        return new ArrayList<>(seen);
    }}

    private static List<String> normalizeList(List<String> in) {{
        List<String> out = new ArrayList<>(in.size());
        for (String s : in) out.add(normalizeDisplay(s));
        return out;
    }}

    /** Display-line normaliser: handles COBOL zero-padded numerics
     *  (``000000001``) vs Java floats (``1.0``) by collapsing every numeric
     *  substring to its canonical form. Surrounding text is preserved. */
    static String normalizeDisplay(String s) {{
        if (s == null) return "";
        String trimmed = stripTrailing(s, ' ');
        // Replace each numeric token with its canonical (stripped) form.
        java.util.regex.Matcher m = NUM_TOKEN.matcher(trimmed);
        StringBuilder sb = new StringBuilder();
        int last = 0;
        while (m.find()) {{
            sb.append(trimmed, last, m.start());
            sb.append(normalize(m.group()));
            last = m.end();
        }}
        sb.append(trimmed, last, trimmed.length());
        return sb.toString();
    }}

    private static final java.util.regex.Pattern NUM_TOKEN =
        java.util.regex.Pattern.compile("[+-]?\\\\d+(\\\\.\\\\d+)?");

    private static String stripTrailing(String s, char c) {{
        int end = s.length();
        while (end > 0 && s.charAt(end - 1) == c) end--;
        return s.substring(0, end);
    }}

    private static String stripLeading(String s, char c) {{
        int start = 0;
        while (start < s.length() && s.charAt(start) == c) start++;
        return s.substring(start);
    }}

    private static String quote(String s) {{
        return "\\"" + s.replace("\\\\", "\\\\\\\\").replace("\\"", "\\\\\\"") + "\\"";
    }}

    private static String displayDiff(List<String> snap, List<String> java) {{
        StringBuilder sb = new StringBuilder("displays differ:");
        int n = Math.max(snap.size(), java.size());
        int shown = 0;
        for (int i = 0; i < n && shown < 5; i++) {{
            String a = i < snap.size() ? snap.get(i) : "<missing>";
            String b = i < java.size() ? java.get(i) : "<missing>";
            if (!a.equals(b)) {{
                sb.append(String.format("\\n      [%d] snap=%s java=%s",
                        i, quote(a), quote(b)));
                shown++;
            }}
        }}
        if (n > shown) sb.append("\\n      ... (").append(n - shown).append(" more)");
        return sb.toString();
    }}

    private static String traceDiff(List<String> snap, List<String> java) {{
        int firstDiff = -1;
        int n = Math.min(snap.size(), java.size());
        for (int i = 0; i < n; i++) {{
            if (!snap.get(i).equals(java.get(i))) {{ firstDiff = i; break; }}
        }}
        if (firstDiff < 0 && snap.size() != java.size()) firstDiff = n;
        if (firstDiff < 0) return "trace differs (unknown)";
        return String.format(
            "paragraph trace differs at index %d: snap=%s java=%s "
            + "(snap.size=%d java.size=%d)",
            firstDiff,
            firstDiff < snap.size() ? snap.get(firstDiff) : "<end>",
            firstDiff < java.size() ? java.get(firstDiff) : "<end>",
            snap.size(), java.size());
    }}
}}
"""
