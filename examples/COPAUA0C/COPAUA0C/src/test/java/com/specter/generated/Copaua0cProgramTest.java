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
 * Generated integration tests for Copaua0cProgram.
 *
 * <p>Loads test cases from the JSONL test store (src/test/resources/test_store.jsonl).
 * Each test case provides input state, stub outcomes, and stub defaults that
 * reproduce a specific execution path through the COBOL program.
 */
class Copaua0cProgramTest {

    private static final Gson GSON = new Gson();

    // --- Smoke tests ---

    @Test
    @DisplayName("Program runs with default state")
    void testRunCompletes() {
        Copaua0cProgram program = new Copaua0cProgram();
        // Program may abend without stubs, but should not throw unhandled exceptions
        ProgramState result = assertDoesNotThrow(() -> program.run());
        assertNotNull(result);
    }

    @Test
    @DisplayName("Default state is populated")
    void testDefaultState() {
        Map<String, Object> defaults = Copaua0cProgram.defaultState();
        assertNotNull(defaults);
        assertFalse(defaults.isEmpty(), "default state should have variables");
    }

    // --- Parameterized integration tests from test store ---

    static Stream<TestCaseData> testCases() throws IOException {
        InputStream is = Copaua0cProgramTest.class.getResourceAsStream("/test_store.jsonl");
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
        Copaua0cProgram program = new Copaua0cProgram();

        // Build initial state with stub wiring
        Map<String, Object> overrides = new LinkedHashMap<>(tc.inputState);

        ProgramState state = ProgramState.withDefaults();
        state.putAll(Copaua0cProgram.defaultState());
        state.putAll(overrides);

        // Wire stub outcomes
        for (Map.Entry<String, List<List<Object[]>>> e : tc.stubOutcomes.entrySet()) {
            state.stubOutcomes.put(e.getKey(), new ArrayList<>(e.getValue()));
        }
        for (Map.Entry<String, List<Object[]>> e : tc.stubDefaults.entrySet()) {
            state.stubDefaults.put(e.getKey(), new ArrayList<>(e.getValue()));
        }

        // Execute using the program's run(ProgramState) method
        program.run(state);

        // Assertions
        assertFalse(state.abended,
            "TC " + tc.id.substring(0, 8) + " abended unexpectedly");

        // Verify paragraph coverage
        if (!tc.expectedParagraphs.isEmpty()) {
            Set<String> covered = new LinkedHashSet<>(state.trace);
            for (String expected : tc.expectedParagraphs) {
                assertTrue(covered.contains(expected),
                    "Expected paragraph " + expected + " not covered in TC " + tc.id.substring(0, 8));
            }
        }
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
