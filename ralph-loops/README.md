# Ralph Loop: GnuCOBOL Hybrid Coverage

Iterative Claude Code loop that runs specter's `--cobol-coverage` mode against a
COBOL program and fixes the synthesis engine until **>=98% paragraph AND >=98% branch
coverage** is achieved.

## Quick Start

```bash
# 1. Generate the AST with your COBOL parser of choice.
#    Specter reads the JSON AST format produced by cobalt.

# 2. Edit the variables block at the top of cobol-coverage-loop.md
#    (PROGRAM_ID, AST_FILE, COBOL_SOURCE, COPYBOOK_DIRS, ...).

# 3. Launch the loop
/ralph-loop "$(cat ralph-loops/cobol-coverage-loop.md)" \
  --max-iterations 30 \
  --completion-promise "COVERAGE 98 PERCENT REACHED"
```

## Configuration

Edit the **variables block** at the top of `cobol-coverage-loop.md` before launching.
All paths are configurable:

| Variable | Description |
|----------|-------------|
| `PROGRAM_ID` | COBOL program name |
| `AST_FILE` | Path to generated `.ast` file |
| `COBOL_SOURCE` | Path to `.cbl` source |
| `COPYBOOK_DIRS` | Space-separated list of copybook directories |
| `TEST_STORE` | Output `.jsonl` path |
| `COVERAGE_BUDGET` | Max test cases |
| `COVERAGE_TIMEOUT` | Max seconds |
| `COVERAGE_BATCH_SIZE` | Cases per round |
| `TARGET_COVERAGE` | Target % (paragraphs and branches) |

## How It Works

Each iteration:
1. Runs `python3 -m specter <ast> --cobol-coverage ...`
2. Parses paragraph/branch coverage from the report
3. If >=98% both: emits completion promise and stops
4. Otherwise: reads the coverage trace, identifies uncovered paragraphs/branches,
   diagnoses root causes in specter's synthesis code, applies fixes
5. Runs `python3 -m pytest` to verify no regressions
6. Commits progress and loops

## What Gets Fixed

The loop modifies specter's Python test synthesis engine — **never** the COBOL source.
Typical fixes target:

- `specter/coverage_strategies.py` — Strategy implementations
- `specter/test_synthesis.py` — Core synthesis loop, stub orchestration
- `specter/cobol_coverage.py` — COBOL instrumentation
- `specter/cobol_executor.py` — Trace parsing
- `specter/monte_carlo.py` — Random input generation
- `specter/variable_domain.py` — Value domain models
- `specter/static_analysis.py` — Branch/paragraph reachability

