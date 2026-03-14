package com.specter.generated;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.MethodSource;
import static org.junit.jupiter.api.Assertions.*;

import com.google.gson.Gson;
import com.google.gson.JsonObject;
import com.google.gson.JsonElement;
import com.google.gson.JsonArray;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.stream.*;

/**
 * Generated integration tests for Cotrn00cProgram.
 *
 * <p>Loads test cases from the JSONL test store (src/test/resources/test_store.jsonl).
 * Each test case provides input state, stub outcomes, and stub defaults that
 * reproduce a specific execution path through the COBOL program.
 */
class Cotrn00cProgramTest {

    private static final Gson GSON = new Gson();

    // --- Smoke tests ---

    @Test
    @DisplayName("Program runs with default state")
    void testRunCompletes() {
        Cotrn00cProgram program = new Cotrn00cProgram();
        // Program may abend without stubs, but should not throw unhandled exceptions
        ProgramState result = assertDoesNotThrow(() -> program.run());
        assertNotNull(result);
    }

    @Test
    @DisplayName("Default state is populated")
    void testDefaultState() {
        Map<String, Object> defaults = Cotrn00cProgram.defaultState();
        assertNotNull(defaults);
        assertFalse(defaults.isEmpty(), "default state should have variables");
    }

    // --- Parameterized integration tests from test store ---

    static Stream<TestCaseData> testCases() throws IOException {
        InputStream is = Cotrn00cProgramTest.class.getResourceAsStream("/test_store.jsonl");
        if (is == null) {
            return Stream.empty();
        }
        BufferedReader reader = new BufferedReader(new InputStreamReader(is, StandardCharsets.UTF_8));
        List<TestCaseData> cases = new ArrayList<>();
        String line;
        while ((line = reader.readLine()) != null) {
            line = line.trim();
            if (line.isEmpty()) continue;
            JsonObject obj = GSON.fromJson(line, JsonObject.class);
            if (!obj.has("input_state")) continue;  // skip progress records
            cases.add(TestCaseData.fromJson(obj));
        }
        reader.close();
        return cases.stream();
    }

    @ParameterizedTest(name = "TC#{index} layer={0} target={1}")
    @MethodSource("testCases")
    void testFromStore(TestCaseData tc) {
        Cotrn00cProgram program = new Cotrn00cProgram();
        Set<String> knownParagraphs = new LinkedHashSet<>(program.getRegistry().allNames());

        // Build initial state with stub wiring
        Map<String, Object> overrides = new LinkedHashMap<>(tc.inputState);

        ProgramState state = ProgramState.withDefaults();
        state.putAll(Cotrn00cProgram.defaultState());
        state.putAll(overrides);

        // Wire stub outcomes
        for (Map.Entry<String, List<List<Object[]>>> e : tc.stubOutcomes.entrySet()) {
            state.stubOutcomes.put(e.getKey(), new ArrayList<>(e.getValue()));
        }
        for (Map.Entry<String, List<Object[]>> e : tc.stubDefaults.entrySet()) {
            state.stubDefaults.put(e.getKey(), new ArrayList<>(e.getValue()));
        }

        // Execute with the same target semantics as synthesis replay.
        String resolvedDirect = null;
        if (tc.target != null && tc.target.startsWith("direct:")) {
            String para = tc.target.substring("direct:".length());
            int pipe = para.indexOf('|');
            if (pipe >= 0) {
                para = para.substring(0, pipe);
            }
            resolvedDirect = resolveParagraphName(para, knownParagraphs);
            Paragraph p = resolvedDirect == null ? null : program.getRegistry().get(resolvedDirect);
            if (p != null) {
                p.execute(state);
            } else {
                // If target can't be resolved against this registry, run entry.
                program.run(state);
            }
        } else {
            // For non-direct targets, execute normal program entry.
            program.run(state);
        }

        // Assertions
        assertFalse(state.abended,
            "TC " + tc.id.substring(0, 8) + " abended unexpectedly");

        Set<String> covered = new LinkedHashSet<>(state.trace);

        // For direct targets, require the resolved paragraph to execute.
        if (resolvedDirect != null) {
            assertTrue(covered.contains(resolvedDirect),
                "Expected direct paragraph " + resolvedDirect + " not covered in TC " + tc.id.substring(0, 8));
        }

        // Optional strict mode: validate all resolvable expected paragraphs.
        boolean strictCoverage = Boolean.parseBoolean(System.getProperty("specter.strictCoverage", "false"));
        if (strictCoverage && !tc.expectedParagraphs.isEmpty()) {
            for (String expected : tc.expectedParagraphs) {
                String resolved = resolveParagraphName(expected, knownParagraphs);
                if (resolved != null) {
                    assertTrue(covered.contains(resolved),
                        "Expected paragraph " + expected + " (resolved=" + resolved + ") not covered in TC " + tc.id.substring(0, 8));
                }
            }
        }
    }

    private static String normalizeParaName(String s) {
        if (s == null) return "";
        return s.toUpperCase().replaceAll("[^A-Z0-9]", "");
    }

    private static String resolveParagraphName(String requested, Set<String> known) {
        if (requested == null || requested.isBlank() || known == null || known.isEmpty()) {
            return null;
        }
        if (known.contains(requested)) {
            return requested;
        }
        String req = requested.toUpperCase();
        for (String k : known) {
            if (k.equalsIgnoreCase(req)) return k;
        }
        String nreq = normalizeParaName(requested);
        for (String k : known) {
            if (normalizeParaName(k).equals(nreq)) return k;
        }
        for (String k : known) {
            String nk = normalizeParaName(k);
            if (nk.endsWith(nreq) || nreq.endsWith(nk)) return k;
        }
        return null;
    }

    // --- Test case data holder ---

    static class TestCaseData {
        final String id;
        final int layer;
        final String target;
        final Map<String, Object> inputState;
        final Map<String, List<List<Object[]>>> stubOutcomes;
        final Map<String, List<Object[]>> stubDefaults;
        final List<String> expectedParagraphs;

        TestCaseData(String id, int layer, String target,
                     Map<String, Object> inputState,
                     Map<String, List<List<Object[]>>> stubOutcomes,
                     Map<String, List<Object[]>> stubDefaults,
                     List<String> expectedParagraphs) {
            this.id = id;
            this.layer = layer;
            this.target = target;
            this.inputState = inputState;
            this.stubOutcomes = stubOutcomes;
            this.stubDefaults = stubDefaults;
            this.expectedParagraphs = expectedParagraphs;
        }

        static TestCaseData fromJson(JsonObject obj) {
            String id = obj.has("id") ? obj.get("id").getAsString() : "";
            int layer = obj.has("layer") ? obj.get("layer").getAsInt() : 0;
            String target = obj.has("target") ? obj.get("target").getAsString() : "";

            Map<String, Object> inputState = new LinkedHashMap<>();
            if (obj.has("input_state")) {
                for (Map.Entry<String, JsonElement> e : obj.getAsJsonObject("input_state").entrySet()) {
                    inputState.put(e.getKey(), jsonToJava(e.getValue()));
                }
            }

            Map<String, List<List<Object[]>>> stubOutcomes = new LinkedHashMap<>();
            if (obj.has("stub_outcomes")) {
                for (Map.Entry<String, JsonElement> e : obj.getAsJsonObject("stub_outcomes").entrySet()) {
                    JsonArray queue = e.getValue().getAsJsonArray();
                    List<List<Object[]>> entries = new ArrayList<>();
                    for (JsonElement qe : queue) {
                        List<Object[]> pairs = new ArrayList<>();
                        for (JsonElement pe : qe.getAsJsonArray()) {
                            JsonArray pair = pe.getAsJsonArray();
                            String var = pair.get(0).getAsString();
                            Object val = jsonToJava(pair.get(1));
                            pairs.add(new Object[]{var, val});
                        }
                        entries.add(pairs);
                    }
                    stubOutcomes.put(e.getKey(), entries);
                }
            }

            Map<String, List<Object[]>> stubDefaults = new LinkedHashMap<>();
            if (obj.has("stub_defaults")) {
                for (Map.Entry<String, JsonElement> e : obj.getAsJsonObject("stub_defaults").entrySet()) {
                    List<Object[]> pairs = new ArrayList<>();
                    for (JsonElement pe : e.getValue().getAsJsonArray()) {
                        JsonArray pair = pe.getAsJsonArray();
                        String var = pair.get(0).getAsString();
                        Object val = jsonToJava(pair.get(1));
                        pairs.add(new Object[]{var, val});
                    }
                    stubDefaults.put(e.getKey(), pairs);
                }
            }

            List<String> paras = new ArrayList<>();
            if (obj.has("paragraphs_covered")) {
                for (JsonElement e : obj.getAsJsonArray("paragraphs_covered")) {
                    paras.add(e.getAsString());
                }
            }

            return new TestCaseData(id, layer, target, inputState,
                                    stubOutcomes, stubDefaults, paras);
        }

        private static Object jsonToJava(JsonElement e) {
            if (e.isJsonNull()) return "";
            if (e.isJsonPrimitive()) {
                var p = e.getAsJsonPrimitive();
                if (p.isBoolean()) return p.getAsBoolean();
                if (p.isNumber()) {
                    double d = p.getAsDouble();
                    if (d == Math.floor(d) && !Double.isInfinite(d)) {
                        long l = p.getAsLong();
                        if (l >= Integer.MIN_VALUE && l <= Integer.MAX_VALUE) {
                            return (int) l;
                        }
                        return l;
                    }
                    return d;
                }
                return p.getAsString();
            }
            return e.toString();
        }

        @Override
        public String toString() {
            return "layer=" + layer + " target=" + target;
        }
    }
}
