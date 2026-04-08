# Specter

Specter automatically generates test suites for COBOL programs. Give it a COBOL program and it figures out what inputs are needed to exercise every branch — including the tricky ones behind CICS calls, SQL queries, and external file I/O.

## The Problem It Solves

COBOL programs are full of external interactions (database reads, CICS transactions, file I/O) that testing normally requires a full mainframe environment to exercise. Specter mocks all of that out, letting you run the program as pure Python, and then systematically finds the input combinations that maximize branch coverage.

## How It Works

1. **Parse** — A JSON AST from your COBOL parser describes the program structure.
2. **Generate** — Specter converts the AST to a Python simulator: each COBOL paragraph becomes a Python function, all state lives in a flat dict, and every external call (CICS/SQL/CALL) becomes a stub that reads scripted responses from a queue.
3. **Cover** — An agentic loop drives four coverage strategies against the simulator, collecting test cases in a JSONL store.
4. **Validate** *(optional)* — Each discovered test case is replayed through a real GnuCOBOL binary compiled with mock instrumentation, confirming the coverage holds on the actual runtime.

```
COBOL AST → Python simulator → coverage loop → tests.jsonl → GnuCOBOL validation
```

## Quick Start

```bash
# Most programs: run with LLM seeds for better initial diversity
specter program.ast --synthesize \
  --cobol-source program.cbl --copybook-dir ./cpy \
  --test-store tests.jsonl \
  --llm-provider openrouter --llm-model gemini-3-flash

# Without LLM (algorithmic only — works well on smaller programs)
specter program.ast --synthesize \
  --cobol-source program.cbl --copybook-dir ./cpy \
  --test-store tests.jsonl

# Validate results against a real GnuCOBOL binary
specter program.ast --cobol-validate-store tests.jsonl \
  --cobol-source program.cbl --copybook-dir ./cpy
```

Each entry in `tests.jsonl` is a complete execution recipe: initial variable values + a scripted sequence of stub responses for every external call the program makes.

## Coverage Strategies

Four strategies run in rotation, managed by a heuristic selector that favours whichever is currently producing new coverage:

| Strategy | What it does |
|----------|-------------|
| **DirectParagraph** | Targets each uncovered paragraph directly. Rotates through hill-climbing, stub fault sweeps, dataflow backpropagation, frontier expansion, and LLM-guided mutation. |
| **CorpusFuzz** | AFL-style fuzzing. Keeps a corpus of branch-unique test cases and mutates the most promising seeds using a coverage-weighted power schedule. |
| **Baseline** | One-shot: generates a handful of representative cases using condition literals, 88-level values, and boundary inputs. |
| **FaultInjection** | One-shot: systematically injects domain-specific fault codes (DLI, MQ, file status) into stub responses to explore error paths. |

**Typical results**: branch coverage in the 90%+ range on real-world programs, with every accepted test case cross-validated against a GnuCOBOL binary.

## Output Modes

**Test store** (`--synthesize`): The primary output. A JSONL file where each line is a test case with its coverage metadata. Crash-safe and resumable — interrupted runs continue from where they left off.

**Java project** (`--java`): A Maven project with JUnit 5 parameterized tests generated from the test store. Each COBOL paragraph maps to a Java class; stubs use a queue-based executor framework that mirrors the Python simulation.

```bash
specter program.ast --java --test-store tests.jsonl -o output/
cd output/ProgramName/ && mvn install
```

**COBOL mock** (`--mock-cobol`): Instrument a COBOL source file for standalone GnuCOBOL execution without any supporting infrastructure, reading mock data from a flat file.

```bash
specter program.cbl --mock-cobol --copybook-dir ./cpy -o program.mock.cbl
cobc -x -o program.mock program.mock.cbl && ./program.mock
```

**Portable bundle** (`--export-bundle` / `--run-bundle`): Export a self-contained bundle (compiled binary + variable domain spec) from a machine with source access. Run it on any machine with GnuCOBOL, no source required.

```bash
specter program.ast --export-bundle ./bundle/ --cobol-source program.cbl --copybook-dir ./cpy
specter --run-bundle ./bundle/ --test-store results.jsonl --coverage-budget 10000
```

## Tuning

| Flag | Default | Effect |
|------|---------|--------|
| `--coverage-budget N` | 5000 | Max test cases |
| `--coverage-timeout N` | 600 | Max seconds |
| `--coverage-batch-size N` | 200 | Cases per strategy round |
| `--coverage-config PATH` | — | YAML pipeline config |

You can pin the exact strategy sequence or let the selector decide:

```yaml
# examples/coverage-config.yaml
selector: heuristic
strategies: [baseline, direct_paragraph, corpus_fuzz, fault_injection]
termination:
  max_stale_rounds: 10
  plateau_branch_pct: 0.8
```

## Requirements

- Python 3.10+, no external runtime dependencies
- Optional: `PyYAML` for YAML config support
- Optional: `z3-solver` for concolic mode
- Optional: GnuCOBOL for mock compilation and validation
- Optional: Java 17+ and Maven 3.9+ for Java project generation
- Optional: Docker for containerized Java deployment

See [JAVAGEN.md](JAVAGEN.md) for Java generation details and [AGENTS.md](AGENTS.md) for the full architecture reference.
