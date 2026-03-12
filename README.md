# Specter

COBOL AST-to-executable code generator. Takes a JSON AST (from an external COBOL parser) and produces either a standalone Python module or a complete Maven Java project that replicates the original program's behavior.

## Usage

```bash
# AST → Python
specter program.ast -o program.py

# AST → Java (Maven project with unit tests)
specter program.ast --java --test-store tests.jsonl -o output/

# AST → Java with Docker + integration tests
specter program.ast --java --test-store tests.jsonl \
  --docker --integration-tests --copybook-dir ./cpy -o output/

# Build and run the Java project
cd output/ProgramName/
mvn install                          # compile + unit tests
docker compose up                    # PostgreSQL + ActiveMQ + app
```

## What It Generates

**Python mode** (`specter program.ast`): A single `.py` file where each COBOL paragraph becomes a function, all state lives in a flat dict, and the `run()` function is the entry point. No dependencies.

**Java mode** (`--java`): A Maven project with section-grouped paragraph classes, a stub executor framework for external operations (CICS/SQL/DLI/MQ), JUnit 5 parameterized tests, and optionally Mockito integration tests + Docker deployment with PostgreSQL and ActiveMQ Artemis.

See [JAVAGEN.md](JAVAGEN.md) for full details on the Java generation approach, testing methodology, and Docker deployment.

## Test Synthesis

The `--synthesize` flag builds a minimal set of test cases targeting maximum code coverage:

```bash
# Generate test store
specter program.ast --synthesize --test-store tests.jsonl

# Then use it for Java generation
specter program.ast --java --test-store tests.jsonl -o output/
```

Each test case is a complete execution spec: input variables + mock orchestration for all external interactions (SQL results, CICS EIBRESP codes, file status codes). The synthesis engine uses five layers — from deterministic constraint solving to targeted mutation walks.

## Analysis Modes

```bash
specter program.ast --analyze                  # dynamic analysis (100 iterations)
specter program.ast --guided -m 10000          # coverage-guided fuzzing
specter program.ast --concolic -m 10000        # Z3 constraint solving
specter program.ast --llm-guided -m 20000      # LLM-steered adaptive fuzzing
specter program.ast --diagram                  # Mermaid execution diagrams
```

## COBOL Mock Execution

```bash
# Instrument COBOL source for standalone GnuCOBOL execution
specter program.cbl --mock-cobol --copybook-dir ./cpy -o program.mock.cbl
cobc -x -o program.mock program.mock.cbl
./program.mock
```

Replaces all EXEC CICS/SQL/DLI blocks, file I/O, and CALL statements with reads from a sequential mock data file. Adds paragraph-level tracing via DISPLAY.

## Requirements

- Python 3.10+
- No external dependencies for core functionality
- Optional: `z3-solver` for `--concolic` mode
- Optional: Java 17+ and Maven 3.9+ for `--java` mode
- Optional: GnuCOBOL for `--mock-cobol` mode
- Optional: Docker for containerized deployment
