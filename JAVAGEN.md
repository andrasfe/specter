# Java Code Generation

Specter can generate a complete Maven Java project from a COBOL AST. The generated project includes the translated program logic, a runtime framework, unit tests, optional Mockito integration tests, and optional Docker deployment.

## Quick Start

```bash
# Generate Java project from AST + synthesized test store
specter program.ast --java --test-store tests.jsonl -o output/

# With integration tests and Docker support
specter program.ast --java --test-store tests.jsonl \
  --docker --integration-tests \
  --copybook-dir ./cpy \
  -o output/

# Build and test
cd output/ProgramName/
mvn install                          # compile + unit tests
cd integration-tests && mvn verify   # Mockito integration tests

# Run with Docker
docker compose up -d db activemq     # start PostgreSQL + ActiveMQ
docker compose build app             # build the app image
docker compose run --rm app          # run the program
```

## Generated Project Structure

```
ProgramName/
├── pom.xml                          Maven POM (JUnit, Gson, Lanterna, PG, HikariCP, JMS, Mockito)
├── Dockerfile                       Multi-stage build (Maven → JRE Alpine)
├── docker-compose.yml               PostgreSQL 16 + ActiveMQ Artemis + app
├── sql/
│   └── init.sql                     DDL from copybooks (if --copybook-dir provided)
├── src/main/java/.../
│   ├── ProgramState.java            Flat key-value state (COBOL WORKING-STORAGE)
│   ├── StubExecutor.java            Interface for external operations (CICS, DLI, MQ, SQL)
│   ├── DefaultStubExecutor.java     FIFO queue stub (for unit tests)
│   ├── JdbcStubExecutor.java        Real JDBC + JMS connectivity (for Docker/production)
│   ├── AppConfig.java               Environment variable configuration
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
    └── src/test/java/.../
        └── <Program>ProgramIT.java  Mockito spy-based integration tests
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
| CALL | `stubs.applyStubOutcome(state, "CALL:program")` |
| GOBACK / STOP RUN | `throw new GobackSignal()` |

All program state lives in `ProgramState`, a flat `Map<String, Object>` mirroring COBOL's WORKING-STORAGE. Internal bookkeeping uses underscore-prefixed keys (`_display`, `_calls`, `_abended`, `_stubLog`).

### Stub Architecture

External operations (database, messaging, CICS) are abstracted behind the `StubExecutor` interface. Two implementations exist:

**`DefaultStubExecutor`** — used by unit tests. Pops pre-configured values from FIFO queues (`stubOutcomes` map). Each test case provides the exact sequence of status codes and return values for every external call the program makes. When a queue is exhausted, falls back to `stubDefaults`.

**`JdbcStubExecutor`** — used in Docker/production. Connects to real PostgreSQL (via HikariCP) and ActiveMQ Artemis (via Jakarta JMS). Maps COBOL operations to actual database queries and message queue operations:

| Operation | JdbcStubExecutor Behavior |
|---|---|
| `CICS-READ` / `DLI-GU` | `SELECT` from mapped table |
| `CICS-WRITE` / `DLI-ISRT` | `INSERT` into mapped table |
| `CICS-REWRITE` / `DLI-REPL` | `UPDATE` mapped table |
| `CICS-DELETE` / `DLI-DLET` | `DELETE` from mapped table |
| `MQ-OPEN` | Open JMS session + consumer/producer for named queue |
| `MQ-GET` | `MessageConsumer.receiveNoWait()` |
| `MQ-PUT1` | `MessageProducer.send()` |
| `MQ-CLOSE` | Close JMS session |
| `SQL-*` | Direct JDBC `PreparedStatement` execution |

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

Use Mockito spies wrapping `DefaultStubExecutor` to verify that the program interacts with external systems correctly:

1. `Mockito.spy(new DefaultStubExecutor())` — preserves proven FIFO queue behavior while adding verification
2. Same test data as unit tests (identical JSONL source)
3. After execution, verifies operations were actually invoked using `state.stubLog` (the runtime log of consumed stub keys)
4. Only verifies operations that were actually consumed — avoids false failures when a test case doesn't exercise certain code paths

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
| `activemq` | `apache/activemq-artemis:2.31.2` | JMS message broker |
| `app` | Built from `Dockerfile` | The translated COBOL program |

### Configuration

The app reads configuration from environment variables (set in `docker-compose.yml`):

| Variable | Default | Description |
|---|---|---|
| `SPECTER_DB_URL` | `jdbc:postgresql://localhost:5432/specter` | JDBC connection URL |
| `SPECTER_DB_USER` | `specter` | Database username |
| `SPECTER_DB_PASSWORD` | `specter` | Database password |
| `SPECTER_JMS_URL` | *(none — JMS disabled)* | ActiveMQ broker URL |
| `SPECTER_JMS_USER` | `admin` | JMS username |
| `SPECTER_JMS_PASSWORD` | `admin` | JMS password |

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
| `--java` | Generate Maven Java project instead of Python |
| `--java-package PKG` | Java package name (default: `com.specter.generated`) |
| `--test-store PATH` | Path to JSONL test store for unit/integration tests |
| `--docker` | Generate `Dockerfile` + `docker-compose.yml` |
| `--integration-tests` | Generate `integration-tests/` with Mockito tests |
| `--copybook-dir DIR` | Copybook directory for SQL DDL generation (repeatable) |

## Dependencies

The generated Maven project uses:

| Dependency | Version | Scope | Purpose |
|---|---|---|---|
| JUnit Jupiter | 5.10.2 | test | Unit + integration test framework |
| Gson | 2.10.1 | test | JSONL test store parsing |
| Mockito | 5.11.0 | test | Spy-based integration test verification |
| Lanterna | 3.1.1 | compile | Terminal UI (CICS screen emulation) |
| PostgreSQL JDBC | 42.7.2 | compile | Database connectivity |
| HikariCP | 5.1.0 | compile | JDBC connection pooling |
| Jakarta JMS API | 3.1.0 | compile | JMS messaging API |
| ActiveMQ Artemis | 2.31.2 | compile | JMS client implementation |

Build requires Java 17+ and Maven 3.9+.
