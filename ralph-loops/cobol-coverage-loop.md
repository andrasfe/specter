# GnuCOBOL Hybrid Coverage Loop

## Variables — EDIT THESE BEFORE LAUNCHING

```
PROGRAM_ID       = <program-id>
AST_FILE         = /tmp/<program-id>.ast
COBOL_SOURCE     = <path-to-source>.cbl
COPYBOOK_DIRS    = <copybook-dir-1> <copybook-dir-2>
TEST_STORE       = /tmp/specter_cov/<program-id>_testset.jsonl
COVERAGE_BUDGET  = 5000
COVERAGE_TIMEOUT = 300
BATCH_SIZE       = 500
TARGET_COVERAGE  = 98
```

## Goal

Achieve **>= TARGET_COVERAGE % paragraph AND >= TARGET_COVERAGE % branch coverage**
for PROGRAM_ID using specter's `--cobol-coverage` mode.

Fix specter's Python synthesis engine to improve coverage. **Never modify the COBOL source.**

## Instructions

On each iteration, execute these steps in order:

### 1. Generate AST if missing

Check if AST_FILE exists. If not, generate it with your COBOL parser (e.g.
cobalt) using COBOL_SOURCE and each directory from COPYBOOK_DIRS, writing the
output to AST_FILE.

### 2. Clear previous test store and run coverage

```bash
rm -f TEST_STORE
python3 -m specter AST_FILE --cobol-coverage \
  --cobol-source COBOL_SOURCE \
  --copybook-dir <each dir from COPYBOOK_DIRS> \
  --test-store TEST_STORE \
  --coverage-budget COVERAGE_BUDGET \
  --coverage-timeout COVERAGE_TIMEOUT \
  --coverage-batch-size BATCH_SIZE
```

### 3. Parse the coverage report

Extract from stdout:
- `Paragraphs: X/Y (Z%)`
- `Branches: X/Y (Z%)`

### 4. Check completion

If paragraph% >= TARGET_COVERAGE AND branch% >= TARGET_COVERAGE:

```
<promise>COVERAGE 98 PERCENT REACHED</promise>
```

Stop here.

### 5. Diagnose coverage gaps

Read the coverage run output carefully. Identify:

**Missing paragraphs:** Which paragraphs were never reached? Trace back through
the call graph to find why. Common causes:
- Stub orchestration doesn't produce the right return codes to reach that path
- Loop-controlling flags (EOF, error) never get set correctly
- DLI/EXEC stubs don't cycle through enough status codes

**Missing branches:** Which IF/EVALUATE arms were never taken? Find the condition
and determine what variable values would trigger it. Common causes:
- The synthesis engine doesn't try the specific values needed
- 88-level conditions aren't explored
- Compound conditions (AND/OR) require specific combinations
- EVALUATE WHEN OTHER requires all prior WHEN arms to miss

### 6. Fix specter's synthesis code

Key files to investigate and modify (in ~/specter/specter/):

| File | What to fix |
|------|-------------|
| `coverage_strategies.py` | Add/improve strategies for reaching uncovered paths |
| `test_synthesis.py` | Fix stub orchestration, test case building, variable injection |
| `cobol_coverage.py` | Fix COBOL instrumentation if branch probes are missed |
| `cobol_executor.py` | Fix trace parsing if coverage data is lost |
| `cobol_mock.py` | Fix mock COBOL generation if compilation fails |
| `monte_carlo.py` | Improve random input generation for domain coverage |
| `variable_domain.py` | Add domain knowledge for variable types |
| `static_analysis.py` | Fix reachability analysis, branch detection |
| `condition_parser.py` | Fix condition parsing for complex EVALUATE/IF |

**Fix patterns for common gaps:**

- **DLI/IMS paragraphs not reached:** The `fault_injection` and `stub_walk` strategies
  need to produce DIBSTAT values ('  ', 'GE', 'GB', 'II', etc.) that drive different
  code paths. Check if DLI EXEC stubs return varied status codes.

- **EVALUATE WHEN OTHER not taken:** All prior WHEN conditions must fail simultaneously.
  The `branch_solver` strategy should identify the required variable state.

- **Nested loop bodies not entered:** The outer loop's controlling condition must be
  true AND the inner condition must trigger. Check that `direct_paragraph` tries
  combinations where both flags are set.

- **Error branches not taken:** The `fault_injection` strategy should produce error
  return codes from EXEC/CALL stubs.

- **Checkpoint/frequency branches:** Counters must exceed threshold values.
  Check that the synthesis engine tries values above the relevant checkpoint
  frequency variables defined in working storage.

### 7. Run unit tests

```bash
cd ~/specter && python3 -m pytest --ignore=tests/test_llm_coverage.py -x -q
```

If tests fail, fix the regressions before proceeding.

### 8. Commit progress

```bash
cd ~/specter
git add specter/
git commit -m "coverage(PROGRAM_ID): improve to X% para / Y% branch

Fixes: <brief description of what was changed>"
```

### 9. Loop

Go back to step 2.

