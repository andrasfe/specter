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

Specter generates test cases targeting maximum branch coverage using four strategies:

- **DirectParagraphStrategy** — The main workhorse (~71% of test cases). Invokes each COBOL paragraph directly via the generated Python module, rotating through 7 phases: parameter hill-climbing, stub fault sweeps, dataflow backpropagation, frontier expansion, rainbow-table harvest, inverse function synthesis, and chain constraint solving for EVALUATE chains.
- **CorpusFuzzStrategy** — AFL-inspired coverage-guided fuzzing with energy-based corpus scheduling. Maintains a deduplicated corpus of test cases selected for branch-coverage uniqueness, mutates seeds via a power schedule that favours rare-branch coverage.
- **BaselineStrategy** — One-shot: generates 5 base cases across value strategies (condition_literal, semantic, boundary, random_valid, 88_value).
- **FaultInjectionStrategy** — One-shot: sweeps stub operations with domain-aware fault values (DLI status codes, MQ completion codes, file status codes).

**Results on CardDemo COPAUA0C**: 91/92 Python branches (98.9%), 20/20 test cases validated against GnuCOBOL (100% pass rate, 17/27 COBOL branches confirmed).

There are two modes: **Python-only** (from AST alone) and **GnuCOBOL hybrid** (AST + COBOL source).

### Python-only mode (`--synthesize`)

Requires the AST file, the COBOL source (for LLM comment extraction), and an LLM provider (for business-scenario seed generation):

```bash
# Full synthesis: AST + COBOL source + copybooks + LLM
specter COACTUPC.cbl.ast --synthesize \
  --cobol-source COACTUPC.cbl \
  --copybook-dir ./copybooks \
  --test-store tests.jsonl \
  --llm-guided --llm-provider anthropic

# With tuning: more trials per round (25x batch = more hill-climbing)
specter COACTUPC.cbl.ast --synthesize \
  --cobol-source COACTUPC.cbl \
  --copybook-dir ./copybooks \
  --test-store tests.jsonl \
  --coverage-budget 50000 \
  --coverage-timeout 120 \
  --coverage-batch-size 500 \
  --llm-provider anthropic
```

### Portable coverage bundle (`--export-bundle` / `--run-bundle`)

Two-phase workflow for cross-machine coverage. Export on a machine with source + LLM, run on any same-platform machine with just the bundle:

```bash
# Phase 1: Export (source machine — needs AST, COBOL, copybooks, optionally LLM)
specter program.ast --export-bundle ./bundle/ \
  --cobol-source program.cbl --copybook-dir ./cpy \
  --llm-provider openrouter

# Phase 2: Run (any machine — only needs GnuCOBOL runtime + the bundle)
specter --run-bundle ./bundle/ \
  --test-store results.jsonl \
  --coverage-budget 10000 --coverage-timeout 3600
```

The bundle contains the compiled COBOL binary and a `coverage-spec.yaml` with all variable domains, stub operations, 88-level siblings, MQ constants, and LLM-generated business scenarios. During export, the LLM analyzes the COBOL source to produce per-variable hints and 10-15 test scenarios that are baked into the spec — the run phase benefits from LLM intelligence without needing an LLM connection.

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

### Strategy configuration

The coverage engine supports 4 pluggable strategies. By default, a heuristic selector picks strategies based on yield history. You can override this with a YAML config file:

```bash
specter COPAUA0C.cbl.ast --cobol-coverage \
  --cobol-source COPAUA0C.cbl --copybook-dir ./cpy \
  --coverage-config pipeline.yaml
```

**Explicit rounds** — define the exact strategy sequence:

```yaml
rounds:
  - strategy: baseline
    batch_size: 500
  - strategy: direct_paragraph
    batch_size: 5000
  - strategy: corpus_fuzz
    batch_size: 2000
  - strategy: fault_injection
    batch_size: 500
loop_from: 1
termination:
  max_stale_rounds: 10
  plateau_branch_pct: 0.8
```

**Selector-driven** — list which strategies are available, let the selector pick:

```yaml
selector: heuristic
strategies:
  - baseline
  - direct_paragraph
  - corpus_fuzz
  - fault_injection
```

Available strategies: `baseline`, `direct_paragraph`, `corpus_fuzz`, `fault_injection`.

**Seed generation** — control how LLM initial seeds are generated:

```yaml
seed_generation:
  paragraphs_per_batch: 5    # fewer paragraphs = more focused seeds (default: 10)
  seeds_per_batch: 12        # more seeds per LLM call (default: 8)
  cache: false               # regenerate seeds instead of using cache
```

For large programs (1000+ paragraphs), smaller `paragraphs_per_batch` with higher `seeds_per_batch` produces better coverage.

**COBOL validation** — automatically validate Python-discovered test cases against the real COBOL binary after synthesis:

```yaml
validation:
  enabled: true
  timeout_per_case: 30
```

This compiles the COBOL once, runs each test case through the binary, and outputs a `*.validated.jsonl` with only confirmed coverage. Can also be run standalone:

```bash
specter program.ast --cobol-validate-store tests.jsonl \
  --cobol-source program.cbl --copybook-dir ./cpy
```

See `examples/coverage-config.yaml` for a fully commented example.

### Tuning parameters

| Flag | Default | Effect |
|------|---------|--------|
| `--coverage-budget N` | 5000 | Max test cases to generate |
| `--coverage-timeout N` | 600 | Max seconds |
| `--coverage-batch-size N` | 200 | Cases per strategy round (DirectParagraph gets 25x this) |
| `--coverage-rounds N` | 0 (unlimited) | Max strategy rounds |
| `--coverage-config PATH` | — | YAML config for strategy pipeline |
| `--coverage-execution-timeout N` | 900 | Per-test COBOL execution timeout (seconds) |
| `--export-bundle DIR` | — | Export portable bundle (binary + spec) |
| `--run-bundle DIR` | — | Run coverage from exported bundle |
| `--cobol-validate-store JSONL` | — | Validate test store against compiled COBOL |

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

## Branch Coverage Features

Specter includes several codegen and coverage engine features that maximize branch reachability:

- **EVALUATE :F probes** — Each WHEN clause gets both a True (matched) and False (not matched) branch ID, making EVALUATE coverage work like IF coverage.
- **Chain constraint solver** — For EVALUATE chains where reaching the Nth clause requires all prior clauses to be false, automatically computes the compound state (e.g., `DECLINE-AUTH=True + INSUFFICIENT-FUND=False + ACCOUNT-CLOSED=True`).
- **88-level mutual exclusivity** — `SET X TO TRUE` clears sibling 88-level flags. Siblings are discovered from copybook records, inline COBOL source scanning, and a FOUND/NFOUND naming heuristic.
- **MQ-aware stubs** — IBM MQ constants (MQCC-OK=0, MQCC-FAILED=2, etc.) are injected into the execution state so comparisons like `WS-COMPCODE = MQCC-OK` work correctly with integer types.
- **AFL-inspired corpus fuzzing** — Maintains a deduplicated corpus of branch-coverage-unique test cases, mutates seeds via a power schedule favouring rare-branch coverage, with 60% targeted mutations on uncovered branch conditions.
- **Value harvesting** — Successful test case values are automatically propagated across all strategies via `dom.condition_literals`, so values discovered by one strategy benefit all others.
- **Backward slicer** — Extracts the minimal code path from paragraph entry to each uncovered branch for LLM prompt context.
- **Boolean condition hints** — Variables appearing in `EVALUATE WHEN TRUE` as standalone conditions automatically get `True`/`False` added to their domain.
- **COBOL validation** — Two-pass workflow: fast Python synthesis followed by COBOL binary validation. 100% of generated test cases validated on CardDemo COPAUA0C.

## Requirements

- Python 3.10+
- No external dependencies for core functionality
- Optional: `PyYAML` for `--coverage-config` YAML support (JSON fallback works without it)
- Optional: `z3-solver` for `--concolic` mode
- Optional: Java 17+ and Maven 3.9+ for `--java` mode
- Optional: GnuCOBOL for `--mock-cobol` mode
- Optional: Docker for containerized deployment
