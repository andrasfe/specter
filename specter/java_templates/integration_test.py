"""Mockito integration test templates for generated Specter Java projects.

Templates for the integration-tests Maven module: a separate POM and
a Mockito spy-based test class.
"""

# ---------------------------------------------------------------------------
# integration-tests/pom.xml
# ---------------------------------------------------------------------------

INTEGRATION_POM_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0
                             http://maven.apache.org/xsd/maven-4.0.0.xsd">
    <modelVersion>4.0.0</modelVersion>

    <groupId>{group_id}</groupId>
    <artifactId>{artifact_id}-integration-tests</artifactId>
    <version>1.0-SNAPSHOT</version>
    <packaging>jar</packaging>

    <name>{program_name} Integration Tests</name>

    <properties>
        <project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>
        <maven.compiler.source>17</maven.compiler.source>
        <maven.compiler.target>17</maven.compiler.target>
        <junit.version>5.10.2</junit.version>
        <mockito.version>5.11.0</mockito.version>
        <amqp.client.version>5.21.0</amqp.client.version>
        <httpclient5.version>5.3.1</httpclient5.version>
    </properties>

    <dependencies>
        <!-- Parent artifact (generated runtime classes) -->
        <dependency>
            <groupId>{group_id}</groupId>
            <artifactId>{artifact_id}</artifactId>
            <version>1.0-SNAPSHOT</version>
        </dependency>

        <!-- Gson (for loading test store JSONL) -->
        <dependency>
            <groupId>com.google.code.gson</groupId>
            <artifactId>gson</artifactId>
            <version>2.10.1</version>
            <scope>test</scope>
        </dependency>

        <!-- JUnit Jupiter -->
        <dependency>
            <groupId>org.junit.jupiter</groupId>
            <artifactId>junit-jupiter-api</artifactId>
            <version>${{junit.version}}</version>
            <scope>test</scope>
        </dependency>
        <dependency>
            <groupId>org.junit.jupiter</groupId>
            <artifactId>junit-jupiter-engine</artifactId>
            <version>${{junit.version}}</version>
            <scope>test</scope>
        </dependency>
        <dependency>
            <groupId>org.junit.jupiter</groupId>
            <artifactId>junit-jupiter-params</artifactId>
            <version>${{junit.version}}</version>
            <scope>test</scope>
        </dependency>

        <!-- Mockito -->
        <dependency>
            <groupId>org.mockito</groupId>
            <artifactId>mockito-core</artifactId>
            <version>${{mockito.version}}</version>
            <scope>test</scope>
        </dependency>
        <dependency>
            <groupId>org.mockito</groupId>
            <artifactId>mockito-junit-jupiter</artifactId>
            <version>${{mockito.version}}</version>
            <scope>test</scope>
        </dependency>

        <!-- PostgreSQL JDBC (for DB integration tests) -->
        <dependency>
            <groupId>org.postgresql</groupId>
            <artifactId>postgresql</artifactId>
            <version>42.7.2</version>
            <scope>test</scope>
        </dependency>

        <!-- HikariCP connection pooling -->
        <dependency>
            <groupId>com.zaxxer</groupId>
            <artifactId>HikariCP</artifactId>
            <version>5.1.0</version>
            <scope>test</scope>
        </dependency>

        <!-- RabbitMQ AMQP client (replaces ActiveMQ Artemis / JMS) -->
        <dependency>
            <groupId>com.rabbitmq</groupId>
            <artifactId>amqp-client</artifactId>
            <version>${{amqp.client.version}}</version>
            <scope>test</scope>
        </dependency>

        <!-- Apache HttpClient 5 (WireMock admin API + REST verification) -->
        <dependency>
            <groupId>org.apache.httpcomponents.client5</groupId>
            <artifactId>httpclient5</artifactId>
            <version>${{httpclient5.version}}</version>
            <scope>test</scope>
        </dependency>
    </dependencies>

    <build>
        <plugins>
            <!-- Failsafe for *IT.java integration tests -->
            <plugin>
                <groupId>org.apache.maven.plugins</groupId>
                <artifactId>maven-failsafe-plugin</artifactId>
                <version>3.2.5</version>
                <executions>
                    <execution>
                        <goals>
                            <goal>integration-test</goal>
                            <goal>verify</goal>
                        </goals>
                    </execution>
                </executions>
            </plugin>

            <!-- Compiler plugin -->
            <plugin>
                <groupId>org.apache.maven.plugins</groupId>
                <artifactId>maven-compiler-plugin</artifactId>
                <version>3.12.1</version>
                <configuration>
                    <source>17</source>
                    <target>17</target>
                </configuration>
            </plugin>
        </plugins>
    </build>
</project>
"""

# ---------------------------------------------------------------------------
# Mockito integration test class template
# ---------------------------------------------------------------------------

MOCKITO_INTEGRATION_TEST_JAVA = """\
package {package_name};

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

import com.rabbitmq.client.Channel;
import com.rabbitmq.client.ConnectionFactory;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.sql.Connection;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.*;
import java.util.stream.*;

/**
 * Mockito spy-based integration tests for {{@link {program_class_name}}}.
 *
 * <p>Uses {{@code Mockito.spy(new DefaultStubExecutor())}} to wrap the proven
 * FIFO queue behavior with Mockito verification. After each test case
 * executes, verifies that the expected stub operations were invoked.
 *
 * <p>When the environment variable {{@code SPECTER_DB_URL}} (or system
 * property {{@code specter.db.url}}) is set, the test loads the per-test-case
 * seed SQL from {{@code /seeds/<tc_id>.sql}} into the real application
 * tables (defined in {{@code sql/init.sql}}) so a {{@link JdbcStubExecutor}}
 * connected to a real PostgreSQL can also be exercised. Similarly,
 * {{@code SPECTER_AMQP_HOST}} enables RabbitMQ seeding for MQ-style ops.
 */
@ExtendWith(MockitoExtension.class)
class {program_class_name}IT {{

    private static final Gson GSON = new Gson();

    // --- Optional real-DB helpers ---

    /**
     * Detect whether a real database is available for integration testing.
     */
    private static String dbUrl() {{
        String url = System.getenv("SPECTER_DB_URL");
        if (url == null || url.isBlank()) url = System.getProperty("specter.db.url");
        return url;
    }}

    /**
     * Load the per-test-case seed SQL from {{@code /seeds/<tc.id>.sql}}
     * (a classpath resource produced by Specter's Java generator) and
     * execute each statement against the real application tables.
     *
     * <p>No-op when the seed file is absent — the test case has no
     * read-style outcomes that map to known tables.
     */
    private static void seedRealTables(javax.sql.DataSource ds, TestCaseData tc) {{
        String resource = "/seeds/" + tc.id + ".sql";
        InputStream is = {program_class_name}IT.class.getResourceAsStream(resource);
        if (is == null) return;
        String sql;
        try {{
            sql = new String(is.readAllBytes(), StandardCharsets.UTF_8);
        }} catch (IOException ex) {{
            System.err.println("Seed read failed: " + ex.getMessage());
            return;
        }}
        try (Connection conn = ds.getConnection(); Statement st = conn.createStatement()) {{
            for (String stmt : sql.split(";\\\\s*\\\\n")) {{
                String trimmed = stmt.trim();
                if (trimmed.isEmpty() || trimmed.startsWith("--")) continue;
                try {{
                    st.execute(trimmed);
                }} catch (SQLException ex) {{
                    System.err.println("Seed stmt warn: " + ex.getMessage()
                        + " :: " + trimmed.substring(0, Math.min(120, trimmed.length())));
                }}
            }}
        }} catch (SQLException ex) {{
            System.err.println("Seed connection warning: " + ex.getMessage());
        }}
    }}

    /**
     * If a RabbitMQ broker is reachable (controlled by
     * {{@code SPECTER_AMQP_HOST}}), publish one message per outcome entry
     * for every {{@code CALL:MQ*}} stub_outcome key. Queue names are
     * derived from the op_key (colon → dot) so the program's MQ GET
     * receives real data.
     */
    private static void seedRabbitMq(TestCaseData tc) {{
        String host = System.getenv("SPECTER_AMQP_HOST");
        if (host == null || host.isBlank()) return;
        ConnectionFactory factory = new ConnectionFactory();
        factory.setHost(host);
        String portStr = System.getenv("SPECTER_AMQP_PORT");
        try {{
            factory.setPort(portStr != null && !portStr.isBlank()
                ? Integer.parseInt(portStr.trim()) : 5672);
        }} catch (NumberFormatException ignored) {{
            factory.setPort(5672);
        }}
        String user = System.getenv("SPECTER_AMQP_USER");
        if (user != null && !user.isBlank()) factory.setUsername(user);
        String pass = System.getenv("SPECTER_AMQP_PASSWORD");
        if (pass != null && !pass.isBlank()) factory.setPassword(pass);
        String vhost = System.getenv("SPECTER_AMQP_VHOST");
        if (vhost != null && !vhost.isBlank()) factory.setVirtualHost(vhost);

        try (com.rabbitmq.client.Connection conn = factory.newConnection();
             Channel ch = conn.createChannel()) {{
            for (Map.Entry<String, List<List<Object[]>>> e : tc.stubOutcomes.entrySet()) {{
                if (!e.getKey().startsWith("CALL:MQ")) continue;
                String qName = "specter.test." + e.getKey().replace(":", ".");
                ch.queueDeclare(qName, true, false, false, null);
                for (List<Object[]> entry : e.getValue()) {{
                    StringBuilder body = new StringBuilder();
                    for (Object[] pair : entry) {{
                        if (body.length() > 0) body.append("|");
                        body.append(pair[0]).append("=").append(pair[1]);
                    }}
                    ch.basicPublish("", qName, null,
                        body.toString().getBytes(StandardCharsets.UTF_8));
                }}
            }}
        }} catch (Exception ex) {{
            System.err.println("RabbitMQ seed warning: " + ex.getMessage());
        }}
    }}

    // --- Test case loading from JSONL ---

    static Stream<TestCaseData> testCases() throws IOException {{
        InputStream is = {program_class_name}IT.class.getResourceAsStream("/test_store.jsonl");
        if (is == null) {{
            return Stream.empty();
        }}
        BufferedReader reader = new BufferedReader(new InputStreamReader(is, StandardCharsets.UTF_8));
        // Dedup by tc.id: cobol_coverage's test_store accumulates entries
        // across iterations and many can share the same id. Running every
        // duplicate as a separate JUnit case would inflate the apparent
        // failure count without testing anything new.
        java.util.LinkedHashMap<String, TestCaseData> uniq = new java.util.LinkedHashMap<>();
        String line;
        while ((line = reader.readLine()) != null) {{
            line = line.trim();
            if (line.isEmpty()) continue;
            JsonObject obj = GSON.fromJson(line, JsonObject.class);
            if (!obj.has("input_state") || !obj.has("id")) continue;
            String id = obj.get("id").getAsString();
            if (uniq.containsKey(id)) continue;
            uniq.put(id, TestCaseData.fromJson(obj));
        }}
        reader.close();
        return uniq.values().stream();
    }}

    @ParameterizedTest(name = "IT#{{index}} layer={{0}} target={{1}}")
    @MethodSource("testCases")
    @DisplayName("Mockito spy integration test")
    void testWithMockitoSpy(TestCaseData tc) {{
        // Seed real DB/MQ if available (same data as mock stubs)
        javax.sql.DataSource dataSource = null;
        String url = dbUrl();
        if (url != null) {{
            com.zaxxer.hikari.HikariConfig hc = new com.zaxxer.hikari.HikariConfig();
            hc.setJdbcUrl(url);
            hc.setUsername(System.getenv("SPECTER_DB_USER") != null
                ? System.getenv("SPECTER_DB_USER") : "specter");
            hc.setPassword(System.getenv("SPECTER_DB_PASSWORD") != null
                ? System.getenv("SPECTER_DB_PASSWORD") : "specter");
            hc.setMaximumPoolSize(2);
            dataSource = new com.zaxxer.hikari.HikariDataSource(hc);
            seedRealTables(dataSource, tc);
        }}
        seedRabbitMq(tc);

        // Create a spy wrapping the real DefaultStubExecutor
        DefaultStubExecutor realStubs = new DefaultStubExecutor();
        StubExecutor spyStubs = spy(realStubs);

        {program_class_name} program = new {program_class_name}(spyStubs);
        Set<String> knownParagraphs = new LinkedHashSet<>(program.getRegistry().allNames());

        // Build initial state.
        // 1. Filter input_state to the variables COBOL would actually accept
        //    via its INIT-record dispatch (INJECTABLE_VARS). COBOL silently
        //    drops INIT records for variables outside this set, so seeding
        //    them on the Java side would diverge from COBOL's runtime state.
        // 2. Apply COBOL PIC truncation to the surviving values so e.g.
        //    ``MOVE 'NVGFYGWWQC' TO XXXX`` matches COBOL's truncation
        //    rather than storing the whole 10-char string.
        ProgramState state = ProgramState.withDefaults();
        state.putAll({program_class_name}.defaultState());
        java.util.Set<String> _injectable = {program_class_name}.INJECTABLE_VARS;
        for (Map.Entry<String, Object> _e : tc.inputState.entrySet()) {{
            String _k = _e.getKey();
            if (!_injectable.isEmpty() && !_injectable.contains(_k)) continue;
            state.put(_k, {program_class_name}.truncateForPic(_k, _e.getValue()));
        }}

        // Wire stub outcomes
        for (Map.Entry<String, List<List<Object[]>>> e : tc.stubOutcomes.entrySet()) {{
            state.stubOutcomes.put(e.getKey(), new ArrayList<>(e.getValue()));
        }}
        for (Map.Entry<String, List<Object[]>> e : tc.stubDefaults.entrySet()) {{
            state.stubDefaults.put(e.getKey(), new ArrayList<>(e.getValue()));
        }}

        // Execute the full program from main entry. The COBOL snapshot is
        // always captured via full-program execution (cobol_executor runs
        // the binary's entrypoint, no direct-paragraph invocation), so the
        // Java side must do the same to keep traces and displays
        // comparable.
        program.run(state);

        // --- Equivalence assertion (subsumes abended check when snapshot present) ---
        CobolSnapshot snapshot = CobolSnapshot.loadFor({program_class_name}IT.class, tc.id);
        if (snapshot != null) {{
            EquivalenceAssert.assertEquivalent(snapshot, state);
        }} else {{
            assertFalse(state.abended,
                "TC " + tc.id.substring(0, Math.min(8, tc.id.length())) + " abended unexpectedly");
        }}

        // --- Mockito verification ---
        // Verify applyStubOutcome was called for each key that was actually
        // consumed during execution (recorded in the stub log).
        Set<String> consumedKeys = new LinkedHashSet<>();
        for (Object[] logEntry : state.stubLog) {{
            if (logEntry[0] != null) consumedKeys.add(logEntry[0].toString());
        }}
        for (String key : consumedKeys) {{
            verify(spyStubs, atLeastOnce()).applyStubOutcome(any(ProgramState.class), eq(key));
        }}

        // Verify typed operations based on consumed stub keys
{verify_calls}

        // Cleanup
        if (dataSource instanceof com.zaxxer.hikari.HikariDataSource) {{
            ((com.zaxxer.hikari.HikariDataSource) dataSource).close();
        }}
    }}

    private static String resolveParagraphName(String requested, Set<String> known) {{
        if (requested == null || requested.isBlank() || known == null || known.isEmpty()) {{
            return null;
        }}
        if (known.contains(requested)) return requested;
        String req = requested.toUpperCase();
        for (String k : known) {{
            if (k.equalsIgnoreCase(req)) return k;
        }}
        String nreq = req.replaceAll("[^A-Z0-9]", "");
        for (String k : known) {{
            String nk = k.toUpperCase().replaceAll("[^A-Z0-9]", "");
            if (nk.equals(nreq)) return k;
        }}
        return null;
    }}

    // --- Test case data holder (same as unit test) ---

    static class TestCaseData {{
        final String id;
        final String layer;
        final String target;
        final Map<String, Object> inputState;
        final Map<String, List<List<Object[]>>> stubOutcomes;
        final Map<String, List<Object[]>> stubDefaults;

        TestCaseData(String id, String layer, String target,
                     Map<String, Object> inputState,
                     Map<String, List<List<Object[]>>> stubOutcomes,
                     Map<String, List<Object[]>> stubDefaults) {{
            this.id = id;
            this.layer = layer;
            this.target = target;
            this.inputState = inputState;
            this.stubOutcomes = stubOutcomes;
            this.stubDefaults = stubDefaults;
        }}

        static TestCaseData fromJson(JsonObject obj) {{
            String id = obj.has("id") ? obj.get("id").getAsString() : "";
            // layer may be either an int (TestStore.append format) or a
            // string strategy name (cobol_coverage._save_test_case format).
            String layer = "";
            if (obj.has("layer") && !obj.get("layer").isJsonNull()) {{
                layer = obj.get("layer").getAsString();
            }}
            String target = obj.has("target") ? obj.get("target").getAsString() : "";

            Map<String, Object> inputState = new LinkedHashMap<>();
            if (obj.has("input_state")) {{
                for (Map.Entry<String, JsonElement> e : obj.getAsJsonObject("input_state").entrySet()) {{
                    inputState.put(e.getKey(), jsonToJava(e.getValue()));
                }}
            }}

            Map<String, List<List<Object[]>>> stubOutcomes = new LinkedHashMap<>();
            if (obj.has("stub_outcomes") && !obj.get("stub_outcomes").isJsonNull()) {{
                JsonElement so = obj.get("stub_outcomes");
                if (so.isJsonObject()) {{
                    // dict-of-FIFO shape: {{op_key: [entry, entry, ...]}}
                    for (Map.Entry<String, JsonElement> e : so.getAsJsonObject().entrySet()) {{
                        JsonArray queue = e.getValue().getAsJsonArray();
                        List<List<Object[]>> entries = new ArrayList<>();
                        for (JsonElement qe : queue) {{
                            entries.add(parsePairs(qe));
                        }}
                        stubOutcomes.put(e.getKey(), entries);
                    }}
                }} else if (so.isJsonArray()) {{
                    // list-of-pairs shape: [[op_key, entry], [op_key, entry], ...]
                    // (cobol_coverage._save_test_case format, execution-ordered).
                    for (JsonElement el : so.getAsJsonArray()) {{
                        JsonArray pair = el.getAsJsonArray();
                        if (pair.size() < 2) continue;
                        String opKey = pair.get(0).getAsString();
                        List<Object[]> pairs = parsePairs(pair.get(1));
                        stubOutcomes.computeIfAbsent(opKey, k -> new ArrayList<>()).add(pairs);
                    }}
                }}
            }}

            Map<String, List<Object[]>> stubDefaults = new LinkedHashMap<>();
            if (obj.has("stub_defaults") && !obj.get("stub_defaults").isJsonNull()
                    && obj.get("stub_defaults").isJsonObject()) {{
                for (Map.Entry<String, JsonElement> e : obj.getAsJsonObject("stub_defaults").entrySet()) {{
                    if (e.getValue().isJsonNull() || !e.getValue().isJsonArray()) continue;
                    List<Object[]> pairs = new ArrayList<>();
                    for (JsonElement pe : e.getValue().getAsJsonArray()) {{
                        JsonArray pair = pe.getAsJsonArray();
                        String var = pair.get(0).getAsString();
                        Object val = jsonToJava(pair.get(1));
                        pairs.add(new Object[]{{var, val}});
                    }}
                    stubDefaults.put(e.getKey(), pairs);
                }}
            }}

            return new TestCaseData(id, layer, target, inputState,
                                    stubOutcomes, stubDefaults);
        }}

        private static List<Object[]> parsePairs(JsonElement queueElement) {{
            List<Object[]> pairs = new ArrayList<>();
            if (queueElement == null || queueElement.isJsonNull()) return pairs;
            for (JsonElement pe : queueElement.getAsJsonArray()) {{
                JsonArray pair = pe.getAsJsonArray();
                String var = pair.get(0).getAsString();
                Object val = jsonToJava(pair.get(1));
                pairs.add(new Object[]{{var, val}});
            }}
            return pairs;
        }}

        private static Object jsonToJava(JsonElement e) {{
            if (e.isJsonNull()) return "";
            if (e.isJsonPrimitive()) {{
                var p = e.getAsJsonPrimitive();
                if (p.isBoolean()) return p.getAsBoolean();
                if (p.isNumber()) {{
                    double d = p.getAsDouble();
                    if (d == Math.floor(d) && !Double.isInfinite(d)) {{
                        long l = p.getAsLong();
                        if (l >= Integer.MIN_VALUE && l <= Integer.MAX_VALUE) {{
                            return (int) l;
                        }}
                        return l;
                    }}
                    return d;
                }}
                return p.getAsString();
            }}
            return e.toString();
        }}

        @Override
        public String toString() {{
            return "layer=" + layer + " target=" + target;
        }}
    }}
}}
"""
