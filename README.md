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

Specter generates test cases targeting maximum branch coverage using a strategy-based engine that rotates through six phases — parameter hill-climbing, stub fault sweeps, dataflow backpropagation, frontier expansion, rainbow-table harvest, and on-the-fly inverse function synthesis. See [ALGO.md](ALGO.md) for details.

There are two modes: **Python-only** (from AST alone) and **GnuCOBOL hybrid** (AST + COBOL source).

### Python-only mode (`--synthesize`)

Needs the AST file. Optionally accepts `--cobol-source` so LLM strategies can read the COBOL source for paragraph comments and business context:

```bash
# Basic: generate test store from AST
specter COACTUPC.cbl.ast --synthesize --test-store tests.jsonl

# With tuning: more trials per round (25x batch = more hill-climbing)
specter COACTUPC.cbl.ast --synthesize \
  --test-store tests.jsonl \
  --coverage-budget 50000 \
  --coverage-timeout 120 \
  --coverage-batch-size 500

# With COBOL source + LLM: extract comments, generate business-scenario seeds
specter COACTUPC.cbl.ast --synthesize \
  --cobol-source COACTUPC.cbl \
  --copybook-dir ./copybooks \
  --test-store tests.jsonl \
  --llm-guided --llm-provider anthropic
```

### GnuCOBOL hybrid mode (`--cobol-coverage`)

Needs AST + COBOL source + copybook directories. Instruments and compiles real COBOL, then cross-validates with the Python simulation:

```bash
# Full pipeline: AST + COBOL source + copybooks
specter COACTUPC.cbl.ast --cobol-coverage \
  --cobol-source COACTUPC.cbl \
  --copybook-dir ./copybooks \
  --test-store tests.jsonl \
  --coverage-budget 5000 \
  --coverage-timeout 300 \
  --coverage-batch-size 500
```

### Using test stores for Java generation

```bash
# Generate test store, then build Java project from it
specter COACTUPC.cbl.ast --synthesize --test-store tests.jsonl
specter COACTUPC.cbl.ast --java --test-store tests.jsonl -o output/

# Multi-program: synthesize + generate Java project with per-program tests
specter --multi --java --synthesize \
  COSGN00C.cbl.ast COMEN01C.cbl.ast COACTUPC.cbl.ast \
  -o carddemo/ \
  --analysis-output carddemo/test-data \
  --coverage-timeout 300

# Exclude sensitive values from generated test data
specter --multi --java --synthesize \
  *.ast -o output/ --exclude-values excluded.txt
```

Each test case is a complete execution spec: input variables + mock orchestration for all external interactions (SQL results, CICS EIBRESP codes, file status codes). Multi-program synthesis generates per-program JSONL test stores, a combined `tests.catalog.md`, and JUnit 5 parameterized test classes.

### Tuning parameters

| Flag | Default | Effect |
|------|---------|--------|
| `--coverage-budget N` | 5000 | Max test cases to generate |
| `--coverage-timeout N` | 600 | Max seconds |
| `--coverage-batch-size N` | 200 | Cases per strategy round (DirectParagraph gets 25x this) |
| `--coverage-rounds N` | 0 (unlimited) | Max strategy rounds |

Higher `--coverage-batch-size` means more hill-climbing trials per paragraph per round. Values of 200-500 work well; the engine scales automatically.

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
