# Java Code Generation

Specter can generate a complete Maven Java project from a COBOL AST. The generated project includes the translated program logic, a runtime framework, unit tests, optional Mockito integration tests, and optional Docker deployment.

## Unified pipeline (recommended)

The `--pipeline` flag runs the entire workflow end-to-end and asserts that the generated Java behaves identically to the original COBOL on every synthesized test case:

```bash
specter program.ast --pipeline \
    --cobol-source program.cbl \
    --copybook-dir ./cpy \
    -o out/
```

What runs:

1. `cobol coverage` produces `out/tests.jsonl` (synthesized inputs + stub outcomes) and an instrumented COBOL binary.
2. `snapshot capture` replays each test case through the binary and writes `out/cobol_snapshots/<tc_id>.json` (final state + displays + abended + paragraph trace + branches).
3. `java generation` emits the Maven project + Docker compose with PostgreSQL + RabbitMQ + WireMock sidecars + per-test seed SQL + per-test WireMock mappings, and copies the snapshots into the IT classpath.
4. `docker compose up -d db rabbitmq wiremock` boots the sidecars.
5. `mvn install -DskipTests` (parent) + `mvn verify` (`integration-tests/`) runs the JUnit5 + Mockito + `EquivalenceAssert` matrix.
6. Surefire/Failsafe XML is parsed, an `out/equivalence-report.md` is written, and a one-line summary is printed.

Use `--pipeline-skip-docker` or `--pipeline-skip-mvn` to stop short of execution. The pipeline returns exit `0` when every test case passes equivalence assertions.

## Quick Start

```bash
# Generate Java project from AST + synthesized test store.
# Docker + integration-tests are emitted by default with --java; explicit
# flags are still accepted for back-compat.
specter program.ast --java --test-store tests.jsonl --copybook-dir ./cpy -o output/

# Build and test
cd output/ProgramName/
mvn install                          # compile + unit tests
cd integration-tests && mvn verify   # Mockito + real-DB + RabbitMQ + WireMock

# Run with Docker (PostgreSQL + RabbitMQ + WireMock + app)
docker compose up -d db rabbitmq wiremock   # start all sidecars
docker compose build app                    # build the app image
docker compose run --rm app                 # run the program
```

## Generated Project Structure

```
ProgramName/
├── pom.xml                          Maven POM (JUnit, Gson, Lanterna, PG, HikariCP,
│                                    RabbitMQ amqp-client, Apache HttpClient5, Mockito)
├── Dockerfile                       Multi-stage build (Maven → JRE Alpine)
├── docker-compose.yml               PostgreSQL 16 + RabbitMQ 3 + WireMock + app
├── sql/
│   └── init.sql                     DDL from copybooks (if --copybook-dir provided)
├── wiremock/
│   └── mappings/<tc_id>/            Per-test-case stub mappings for outbound CALLs
├── src/main/java/.../
│   ├── ProgramState.java            Flat key-value state (COBOL WORKING-STORAGE)
│   ├── StubExecutor.java            Interface for external operations + callProgram default
│   ├── DefaultStubExecutor.java     FIFO queue stub (for unit tests)
│   ├── JdbcStubExecutor.java        Real JDBC + RabbitMQ + HTTP for production/Docker
│   ├── AppConfig.java               Environment variable configuration (DB / AMQP / REST)
│   ├── Main.java                    Docker entrypoint (wires JdbcStubExecutor)
│   ├── CobolRuntime.java            Numeric conversion, string ops, COBOL semantics
│   ├── GobackSignal.java            GOBACK/STOP RUN control flow
│   ├── Paragraph.java               Functional interface for paragraph execution
│   ├── ParagraphRegistry.java       Paragraph lookup + PERFORM THRU range support
│   ├── SectionBase.java             Base class for section groupings
│   ├── SectionMain.java             Section containing MAIN-PARA, etc.
│   ├── Section1.java … Section9.java  Grouped by numeric prefix (1000s, 2000s, …)
│   └── <Program>Program.java        Top-level program class with run() entry point
├── src/test/java/.../
│   └── <Program>ProgramTest.java    JUnit 5 parameterized tests from test store
└── integration-tests/
    ├── pom.xml                      Separate Maven module (Mockito + failsafe)
    └── src/test/
        ├── java/.../
        │   ├── <Program>ProgramIT.java  Mockito spy + real DB / RabbitMQ tests
        │   ├── CobolSnapshot.java       POJO + Gson loader for /cobol_snapshots/<tc_id>.json
        │   └── EquivalenceAssert.java   Strict diff: abended + displays + trace + final state
        └── resources/
            ├── seeds/<tc_id>.sql        Per-test INSERTs into real app tables
            ├── wiremock/mappings/...    Mirror of project-root mappings (for CI use)
            └── cobol_snapshots/<tc_id>.json  COBOL ground truth (only when --pipeline used)
```

## Code Generation Approach

### AST to Java Translation

Each COBOL paragraph becomes a method on a `SectionBase` subclass. Paragraphs are grouped by their numeric prefix into sections (1000-series → `Section1`, 2000-series → `Section2`, etc.). The grouping keeps individual files manageable.

The translation handles:

| COBOL Construct | Java Translation |
|---|---|
| MOVE / SET | `state.set(key, value)` |
| IF / EVALUATE | Standard `if`/`else if`/`else` |
| PERFORM / PERFORM THRU | `registry.perform(name)` / `registry.performThru(from, to)` |
| COMPUTE / ADD / SUBTRACT / MULTIPLY / DIVIDE | Arithmetic via `CobolRuntime.toNum()` |
| STRING / UNSTRING | `StringBuilder` / `String.split()` operations |
| DISPLAY | `state.addDisplay(text)` |
| EXEC CICS / EXEC SQL / EXEC DLI | `stubs.applyStubOutcome(state, opKey)` |
| CALL `'PROGNAME'` (non-MQ) | `stubs.callProgram(state, "PROGNAME", inputVars, outputVars)` (HTTP POST) |
| CALL `'MQOPEN'` etc. | `stubs.mqOpen(...)` / `mqGet(...)` / `mqPut1(...)` / `mqClose(...)` (AMQP) |
| GOBACK / STOP RUN | `throw new GobackSignal()` |

All program state lives in `ProgramState`, a flat `Map<String, Object>` mirroring COBOL's WORKING-STORAGE. Internal bookkeeping uses underscore-prefixed keys (`_display`, `_calls`, `_abended`, `_stubLog`).

### Stub Architecture

External operations (database, messaging, CICS) are abstracted behind the `StubExecutor` interface. Two implementations exist:

**`DefaultStubExecutor`** — used by unit tests. Pops pre-configured values from FIFO queues (`stubOutcomes` map). Each test case provides the exact sequence of status codes and return values for every external call the program makes. When a queue is exhausted, falls back to `stubDefaults`. The interface's `callProgram` default method delegates to `applyStubOutcome("CALL:" + name)` so unit tests behave identically to before this feature.

**`JdbcStubExecutor`** — used in Docker/production. Connects to real PostgreSQL (via HikariCP), RabbitMQ (via the typed `com.rabbitmq:amqp-client` library), and an HTTP endpoint for CALL routing (via Apache HttpClient5). Maps COBOL operations to actual database / message-broker / REST operations:

| Operation | JdbcStubExecutor Behavior |
|---|---|
| `CICS-READ` / `DLI-GU` | `SELECT` from mapped table (per-test seed SQL primes the rows) |
| `CICS-WRITE` / `DLI-ISRT` | `INSERT` into mapped table |
| `CICS-REWRITE` / `DLI-REPL` | `UPDATE` mapped table |
| `CICS-DELETE` / `DLI-DLET` | `DELETE` from mapped table |
| `MQ-OPEN` | `Channel.queueDeclare(qName, ...)` against RabbitMQ |
| `MQ-GET` | `Channel.basicGet(qName, autoAck=true)` |
| `MQ-PUT1` | `Channel.basicPublish("", qName, ...)` |
| `MQ-CLOSE` | Close AMQP channel + connection |
| `SQL-*` | Direct JDBC `PreparedStatement` execution |
| `callProgram` (non-MQ CALL) | HTTP POST to `${{SPECTER_CALL_BASE_URL}}/<progname>`; JSON response body keys → `ProgramState` |

## Testing Methodology

### Unit Tests (`mvn test`)

Generated from the synthesized test store (JSONL). Each test case is a complete execution specification:

```json
{
  "id": "a1b2c3d4",
  "input_state": {"WS-STATUS": "00", "WS-AMOUNT": 100},
  "stub_outcomes": {"SQL": [[["SQLCODE", 0]], [["SQLCODE", 100]]]},
  "stub_defaults": {"SQL": [["SQLCODE", 100]]}
}
```

The test class uses JUnit 5 `@ParameterizedTest` with `@MethodSource`. Each test:

1. Loads test case data from `test-store.jsonl` (bundled as a test resource)
2. Creates a `ProgramState` with `input_state` values
3. Configures a `DefaultStubExecutor` with `stub_outcomes` and `stub_defaults`
4. Runs the program via `new <Program>Program(stubs).run(state)`
5. Asserts the program did not abend (`assertFalse(state.abended)`)

### Integration Tests (`mvn verify` in `integration-tests/`)

Use Mockito spies wrapping `DefaultStubExecutor` to verify that the program interacts with external systems correctly. When the appropriate sidecar env vars are set, the same tests also exercise real PostgreSQL + RabbitMQ + WireMock:

1. `Mockito.spy(new DefaultStubExecutor())` — preserves proven FIFO queue behavior while adding verification
2. Same test data as unit tests (identical JSONL source)
3. `seedRealTables(tc)` — when `SPECTER_DB_URL` is set, loads `/seeds/<tc.id>.sql` from classpath into the real application tables so `JdbcStubExecutor.cicsRead()` SELECTs return the values each test case expects
4. `seedRabbitMq(tc)` — when `SPECTER_AMQP_HOST` is set, publishes `CALL:MQ*` outcomes to RabbitMQ queues so `mqGet` receives real data
5. WireMock (loaded from `wiremock/mappings/<tc_id>/`) responds to non-MQ `callProgram` HTTP POSTs with each test's expected JSON body
6. After execution, verifies operations were actually invoked using `state.stubLog` (the runtime log of consumed stub keys)
7. Only verifies operations that were actually consumed — avoids false failures when a test case doesn't exercise certain code paths

The Mockito approach gives confidence that:
- The program calls the expected external operations in the expected order
- Status variables are correctly checked after each operation
- Error paths are exercised when stub outcomes return failure codes

### Test Store Synthesis

The test store is built by Specter's synthesis engine (`--synthesize`), which systematically generates test cases targeting maximum code coverage through layered strategies:

1. All-success baseline (status variables set to success values)
2. Path-constraint satisfaction (shortest path to each uncovered paragraph)
3. Branch-level solving (Z3 or heuristic condition solving)
4. Stub outcome combinatorics (enumerate failure/success combinations)
5. Targeted mutation walks (seeded hill-climbing from existing cases)

The store is incremental — re-running synthesis picks up where the last run left off.

## Docker Deployment

### Services

| Service | Image | Purpose |
|---|---|---|
| `db` | `postgres:16-alpine` | Application database (DDL from copybooks) |
| `rabbitmq` | `rabbitmq:3-management` | AMQP broker for MQ-style operations |
| `wiremock` | `wiremock/wiremock:3.5.4` | Mocks REST endpoints for outbound CALLs |
| `app` | Built from `Dockerfile` | The translated COBOL program |

### Configuration

The app reads configuration from environment variables (set in `docker-compose.yml`):

| Variable | Default | Description |
|---|---|---|
| `SPECTER_DB_URL` | `jdbc:postgresql://localhost:5432/specter` | JDBC connection URL |
| `SPECTER_DB_USER` | `specter` | Database username |
| `SPECTER_DB_PASSWORD` | `specter` | Database password |
| `SPECTER_AMQP_HOST` | `localhost` | RabbitMQ broker host |
| `SPECTER_AMQP_PORT` | `5672` | RabbitMQ broker port |
| `SPECTER_AMQP_USER` | `specter` | RabbitMQ username |
| `SPECTER_AMQP_PASSWORD` | `specter` | RabbitMQ password |
| `SPECTER_AMQP_VHOST` | `/` | RabbitMQ virtual host |
| `SPECTER_CALL_BASE_URL` | `http://localhost:8080` | Base URL for outbound CALL HTTP routing (WireMock) |

### Build Pipeline

The Dockerfile uses a multi-stage build:
1. **Build stage** (`maven:3.9-eclipse-temurin-17`): resolves dependencies, compiles, packages a fat JAR via maven-shade-plugin
2. **Runtime stage** (`eclipse-temurin:17-jre-alpine`): copies the fat JAR + SQL init scripts, runs with `java -jar`

### SQL Initialization

When `--copybook-dir` is provided, Specter parses COBOL copybooks and generates PostgreSQL DDL (`sql/init.sql`). This is mounted into the PostgreSQL container at `/docker-entrypoint-initdb.d/` for automatic schema creation on first start.

## CLI Reference

```bash
specter program.ast --java [options] -o output/
```

| Flag | Description |
|---|---|
| `--java` | Generate Maven Java project instead of Python (also implies `--docker` and `--integration-tests`) |
| `--java-package PKG` | Java package name (default: `com.specter.generated`) |
| `--test-store PATH` | Path to JSONL test store; required for per-test seed SQL + WireMock mappings |
| `--docker` | (No-op when `--java` is set; enabled by default) |
| `--integration-tests` | (No-op when `--java` is set; enabled by default) |
| `--copybook-dir DIR` | Copybook directory for SQL DDL + per-test seed SQL (repeatable; without it `JdbcStubExecutor.cicsRead` will NOTFND) |
| `--pipeline` | Run the unified end-to-end pipeline (coverage + snapshot capture + Java generation + docker + mvn verify + equivalence report). Requires `--cobol-source` and `--copybook-dir`. |
| `--pipeline-skip-docker` | With `--pipeline`: stop after generating artifacts; do not start sidecars. |
| `--pipeline-skip-mvn` | With `--pipeline`: stop after generating artifacts; do not run `mvn verify`. |

## Dependencies

The generated Maven project uses:

| Dependency | Version | Scope | Purpose |
|---|---|---|---|
| JUnit Jupiter | 5.10.2 | test | Unit + integration test framework |
| Gson | 2.10.1 | compile | JSONL test store parsing + JSON CALL bodies |
| Mockito | 5.11.0 | test | Spy-based integration test verification |
| Lanterna | 3.1.1 | compile | Terminal UI (CICS screen emulation) |
| PostgreSQL JDBC | 42.7.2 | compile | Database connectivity |
| HikariCP | 5.1.0 | compile | JDBC connection pooling |
| RabbitMQ amqp-client | 5.21.0 | compile | AMQP broker client for MQ ops |
| Apache HttpClient5 | 5.3.1 | compile | HTTP client for non-MQ CALL routing |

Build requires Java 17+ and Maven 3.9+.
