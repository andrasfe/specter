package com.specter.generated;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.MethodSource;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.junit.jupiter.MockitoExtension;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

import com.google.gson.Gson;
import com.google.gson.JsonObject;
import com.google.gson.JsonElement;
import com.google.gson.JsonArray;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSetMetaData;
import java.sql.SQLException;
import java.util.*;
import java.util.stream.*;

/**
 * Mockito spy-based integration tests for {@link Cosgn00cProgram}.
 *
 * <p>Uses {@code Mockito.spy(new DefaultStubExecutor())} to wrap the proven
 * FIFO queue behavior with Mockito verification.  After each test case
 * executes, verifies that the expected stub operations were invoked.
 *
 * <p>When the environment variables {@code SPECTER_DB_URL} (or the system
 * property {@code specter.db.url}) are set, the test pre-populates the
 * database and optionally JMS queues with the same values that the stub
 * outcomes mock, so a {@link JdbcStubExecutor} connected to a real
 * PostgreSQL/ActiveMQ can also be exercised.
 */
@ExtendWith(MockitoExtension.class)
class Cosgn00cProgramIT {

    private static final Gson GSON = new Gson();

    // --- Optional real-DB helpers ---

    /**
     * Detect whether a real database is available for integration testing.
     */
    private static String dbUrl() {
        String url = System.getenv("SPECTER_DB_URL");
        if (url == null || url.isBlank()) url = System.getProperty("specter.db.url");
        return url;
    }

    /**
     * Seed the database with stub-outcome variable assignments so that a
     * real JDBC read returns the same data that the FIFO queue would supply.
     *
     * <p>For each stub outcome entry whose key looks like a CICS/DLI read
     * (e.g. {@code "CICS"}, {@code "DLI"}), the variable assignments
     * are inserted into a staging table keyed by the operation key.
     * The table is created on-the-fly if it does not exist.
     */
    private static void seedDatabase(javax.sql.DataSource ds, TestCaseData tc) {
        try (Connection conn = ds.getConnection()) {
            // Create the staging table if it doesn't exist
            conn.createStatement().executeUpdate(
                "CREATE TABLE IF NOT EXISTS specter_stub_seed ("
                + "  op_key   VARCHAR(200),"
                + "  seq      INTEGER,"
                + "  var_name VARCHAR(200),"
                + "  val      TEXT"
                + ")"
            );
            // Clear previous seed data for this TC
            try (PreparedStatement del = conn.prepareStatement(
                    "DELETE FROM specter_stub_seed WHERE op_key LIKE ?")) {
                del.setString(1, "%");
                del.executeUpdate();
            }
            // Insert seed data from stub outcomes
            try (PreparedStatement ins = conn.prepareStatement(
                    "INSERT INTO specter_stub_seed (op_key, seq, var_name, val) VALUES (?, ?, ?, ?)")) {
                for (Map.Entry<String, List<List<Object[]>>> e : tc.stubOutcomes.entrySet()) {
                    int seq = 0;
                    for (List<Object[]> entry : e.getValue()) {
                        for (Object[] pair : entry) {
                            ins.setString(1, e.getKey());
                            ins.setInt(2, seq);
                            ins.setString(3, pair[0].toString());
                            ins.setString(4, pair[1] != null ? pair[1].toString() : "");
                            ins.addBatch();
                        }
                        seq++;
                    }
                }
                // Also seed from stub defaults
                for (Map.Entry<String, List<Object[]>> e : tc.stubDefaults.entrySet()) {
                    for (Object[] pair : e.getValue()) {
                        ins.setString(1, e.getKey() + ":DEFAULT");
                        ins.setInt(2, 0);
                        ins.setString(3, pair[0].toString());
                        ins.setString(4, pair[1] != null ? pair[1].toString() : "");
                        ins.addBatch();
                    }
                }
                ins.executeBatch();
            }
        } catch (SQLException ex) {
            // Non-fatal: DB seeding is best-effort for integration tests
            System.err.println("DB seed warning: " + ex.getMessage());
        }
    }

    /**
     * If ActiveMQ is available, publish stub-outcome messages to queues
     * so that MQ operations can read real data.
     */
    private static void seedJms(TestCaseData tc) {
        String jmsUrl = System.getenv("SPECTER_JMS_URL");
        if (jmsUrl == null || jmsUrl.isBlank()) return;
        try {
            Class<?> factoryClass = Class.forName(
                "org.apache.activemq.artemis.jms.client.ActiveMQConnectionFactory");
            Object factory = factoryClass.getConstructor(String.class).newInstance(jmsUrl);
            Object jmsConn = factory.getClass().getMethod("createConnection").invoke(factory);
            Object session = jmsConn.getClass()
                .getMethod("createSession", boolean.class, int.class)
                .invoke(jmsConn, false, 1);
            // Publish stub outcomes for CALL:MQ* keys as JMS text messages
            for (Map.Entry<String, List<List<Object[]>>> e : tc.stubOutcomes.entrySet()) {
                if (!e.getKey().startsWith("CALL:MQ")) continue;
                String qName = "specter.test." + e.getKey().replace(":", ".");
                Object queue = session.getClass()
                    .getMethod("createQueue", String.class).invoke(session, qName);
                Object producer = session.getClass()
                    .getMethod("createProducer", Class.forName("jakarta.jms.Destination"))
                    .invoke(session, queue);
                for (List<Object[]> entry : e.getValue()) {
                    StringBuilder body = new StringBuilder();
                    for (Object[] pair : entry) {
                        if (body.length() > 0) body.append("|");
                        body.append(pair[0]).append("=").append(pair[1]);
                    }
                    Object msg = session.getClass()
                        .getMethod("createTextMessage", String.class)
                        .invoke(session, body.toString());
                    producer.getClass()
                        .getMethod("send", Class.forName("jakarta.jms.Message"))
                        .invoke(producer, msg);
                }
            }
            session.getClass().getMethod("close").invoke(session);
            jmsConn.getClass().getMethod("close").invoke(jmsConn);
        } catch (Exception ex) {
            // Non-fatal: JMS seeding is best-effort
            System.err.println("JMS seed warning: " + ex.getMessage());
        }
    }

    // --- Test case loading from JSONL ---

    static Stream<TestCaseData> testCases() throws IOException {
        InputStream is = Cosgn00cProgramIT.class.getResourceAsStream("/test_store.jsonl");
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
            if (!obj.has("input_state")) continue;
            cases.add(TestCaseData.fromJson(obj));
        }
        reader.close();
        return cases.stream();
    }

    @ParameterizedTest(name = "IT#{index} layer={0} target={1}")
    @MethodSource("testCases")
    @DisplayName("Mockito spy integration test")
    void testWithMockitoSpy(TestCaseData tc) {
        // Seed real DB/MQ if available (same data as mock stubs)
        javax.sql.DataSource dataSource = null;
        String url = dbUrl();
        if (url != null) {
            com.zaxxer.hikari.HikariConfig hc = new com.zaxxer.hikari.HikariConfig();
            hc.setJdbcUrl(url);
            hc.setUsername(System.getenv("SPECTER_DB_USER") != null
                ? System.getenv("SPECTER_DB_USER") : "specter");
            hc.setPassword(System.getenv("SPECTER_DB_PASSWORD") != null
                ? System.getenv("SPECTER_DB_PASSWORD") : "specter");
            hc.setMaximumPoolSize(2);
            dataSource = new com.zaxxer.hikari.HikariDataSource(hc);
            seedDatabase(dataSource, tc);
        }
        seedJms(tc);

        // Create a spy wrapping the real DefaultStubExecutor
        DefaultStubExecutor realStubs = new DefaultStubExecutor();
        StubExecutor spyStubs = spy(realStubs);

        Cosgn00cProgram program = new Cosgn00cProgram(spyStubs);
        Set<String> knownParagraphs = new LinkedHashSet<>(program.getRegistry().allNames());

        // Build initial state
        ProgramState state = ProgramState.withDefaults();
        state.putAll(Cosgn00cProgram.defaultState());
        state.putAll(tc.inputState);

        // Wire stub outcomes
        for (Map.Entry<String, List<List<Object[]>>> e : tc.stubOutcomes.entrySet()) {
            state.stubOutcomes.put(e.getKey(), new ArrayList<>(e.getValue()));
        }
        for (Map.Entry<String, List<Object[]>> e : tc.stubDefaults.entrySet()) {
            state.stubDefaults.put(e.getKey(), new ArrayList<>(e.getValue()));
        }

        // Execute
        String resolvedDirect = null;
        if (tc.target != null && tc.target.startsWith("direct:")) {
            String para = tc.target.substring("direct:".length());
            int pipe = para.indexOf('|');
            if (pipe >= 0) para = para.substring(0, pipe);
            resolvedDirect = resolveParagraphName(para, knownParagraphs);
            Paragraph p = resolvedDirect == null ? null : program.getRegistry().get(resolvedDirect);
            if (p != null) {
                p.execute(state);
            } else {
                program.run(state);
            }
        } else {
            program.run(state);
        }

        // --- Assertions ---
        assertFalse(state.abended,
            "TC " + tc.id.substring(0, Math.min(8, tc.id.length())) + " abended unexpectedly");

        // --- Mockito verification ---
        // Verify applyStubOutcome was called for each key that was actually
        // consumed during execution (recorded in the stub log).
        Set<String> consumedKeys = new LinkedHashSet<>();
        for (Object[] logEntry : state.stubLog) {
            if (logEntry[0] != null) consumedKeys.add(logEntry[0].toString());
        }
        for (String key : consumedKeys) {
            verify(spyStubs, atLeastOnce()).applyStubOutcome(any(ProgramState.class), eq(key));
        }

        // Verify typed operations based on consumed stub keys
        // No stub operations detected

        // Cleanup
        if (dataSource instanceof com.zaxxer.hikari.HikariDataSource) {
            ((com.zaxxer.hikari.HikariDataSource) dataSource).close();
        }
    }

    private static String resolveParagraphName(String requested, Set<String> known) {
        if (requested == null || requested.isBlank() || known == null || known.isEmpty()) {
            return null;
        }
        if (known.contains(requested)) return requested;
        String req = requested.toUpperCase();
        for (String k : known) {
            if (k.equalsIgnoreCase(req)) return k;
        }
        String nreq = req.replaceAll("[^A-Z0-9]", "");
        for (String k : known) {
            String nk = k.toUpperCase().replaceAll("[^A-Z0-9]", "");
            if (nk.equals(nreq)) return k;
        }
        return null;
    }

    // --- Test case data holder (same as unit test) ---

    static class TestCaseData {
        final String id;
        final int layer;
        final String target;
        final Map<String, Object> inputState;
        final Map<String, List<List<Object[]>>> stubOutcomes;
        final Map<String, List<Object[]>> stubDefaults;

        TestCaseData(String id, int layer, String target,
                     Map<String, Object> inputState,
                     Map<String, List<List<Object[]>>> stubOutcomes,
                     Map<String, List<Object[]>> stubDefaults) {
            this.id = id;
            this.layer = layer;
            this.target = target;
            this.inputState = inputState;
            this.stubOutcomes = stubOutcomes;
            this.stubDefaults = stubDefaults;
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

            return new TestCaseData(id, layer, target, inputState,
                                    stubOutcomes, stubDefaults);
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
