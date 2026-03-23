# Ralph Loop: GnuCOBOL Hybrid Coverage

Iterative Claude Code loop that runs specter's `--cobol-coverage` mode against a
COBOL program and fixes the synthesis engine until **>=98% paragraph AND >=98% branch
coverage** is achieved.

## Quick Start

```bash
cd ~/specter

# 1. Generate the AST (requires cobalt from war_rig)
cd ~/war_rig && uv run cobalt \
  <COBOL_SOURCE> \
  --copybook-dir <COPYBOOK_DIR> \
  -o <AST_OUTPUT>

# 2. Launch the Ralph Loop
cd ~/specter
/ralph-loop "$(cat ralph-loops/cobol-coverage-loop.md)" \
  --max-iterations 30 \
  --completion-promise "COVERAGE 98 PERCENT REACHED"
```

## Configuration

Edit the **variables block** at the top of `cobol-coverage-loop.md` before launching.
All paths are configurable:

| Variable | Description | Example |
|----------|-------------|---------|
| `PROGRAM_ID` | COBOL program name | `CBPAUP0C` |
| `AST_FILE` | Path to generated .ast | `/tmp/CBPAUP0C.ast` |
| `COBOL_SOURCE` | Path to .cbl source | `~/war_rig/.../cbl/CBPAUP0C.cbl` |
| `COPYBOOK_DIRS` | Copybook directories | `~/war_rig/.../cpy ~/war_rig/.../app/cpy` |
| `TEST_STORE` | Output .jsonl path | `/tmp/specter_cov/CBPAUP0C_testset.jsonl` |
| `COVERAGE_BUDGET` | Max test cases | `5000` |
| `COVERAGE_TIMEOUT` | Max seconds | `300` |
| `COVERAGE_BATCH_SIZE` | Cases per round | `500` |
| `TARGET_COVERAGE` | Target % (para & branch) | `98` |

## Example: CBPAUP0C (Batch IMS — Delete Expired Authorizations)

```bash
# Generate AST
cd ~/war_rig && uv run cobalt \
  ~/war_rig/aws-mainframe-modernization-carddemo/app/app-authorization-ims-db2-mq/cbl/CBPAUP0C.cbl \
  --copybook-dir ~/war_rig/aws-mainframe-modernization-carddemo/app/app-authorization-ims-db2-mq/cpy \
  --copybook-dir ~/war_rig/aws-mainframe-modernization-carddemo/app/cpy \
  -o /tmp/CBPAUP0C.ast

# Launch loop (edit cobol-coverage-loop.md first if paths differ)
cd ~/specter
/ralph-loop "$(cat ralph-loops/cobol-coverage-loop.md)" \
  --max-iterations 30 \
  --completion-promise "COVERAGE 98 PERCENT REACHED"
```

**Baseline:** 12/17 paragraphs (70.6%), 12/41 branches (29.3%)

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

## Programs Tested

| Program | Type | Paragraphs | Branches | Baseline |
|---------|------|------------|----------|----------|
| CBPAUP0C | Batch IMS | 17 | 41 | 70.6% / 29.3% |
| PAUDBLOD | Batch DB Load | 17 | 0 | 100% / N/A |
| CBEXPORT | Batch Export | 21 | 32 | 81.0% / 59.4% |
