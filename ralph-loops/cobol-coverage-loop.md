# GnuCOBOL Hybrid Coverage Loop

## Variables — EDIT THESE BEFORE LAUNCHING

```
PROGRAM_ID       = CBPAUP0C
AST_FILE         = /tmp/CBPAUP0C.ast
COBOL_SOURCE     = /Users/andraslferenczi/war_rig/aws-mainframe-modernization-carddemo/app/app-authorization-ims-db2-mq/cbl/CBPAUP0C.cbl
COPYBOOK_DIRS    = /Users/andraslferenczi/war_rig/aws-mainframe-modernization-carddemo/app/app-authorization-ims-db2-mq/cpy /Users/andraslferenczi/war_rig/aws-mainframe-modernization-carddemo/app/cpy
TEST_STORE       = /tmp/specter_cov/CBPAUP0C_testset.jsonl
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

Check if AST_FILE exists. If not:

```bash
cd ~/war_rig && uv run cobalt \
  COBOL_SOURCE \
  --copybook-dir <each dir from COPYBOOK_DIRS> \
  -o AST_FILE
```

### 2. Clear previous test store and run coverage

```bash
rm -f TEST_STORE
cd ~/specter && python3 -m specter AST_FILE --cobol-coverage \
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
  Check that the synthesis engine tries values above P-CHKP-FREQ / P-CHKP-DIS-FREQ.

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

---

## Program Structure: CBPAUP0C

```
MAIN-PARA
  -> 1000-INITIALIZE / 1000-EXIT
     - ACCEPT date, params
     - Validate P-EXPIRY-DAYS (numeric check)
     - Default P-CHKP-FREQ, P-CHKP-DIS-FREQ, P-DEBUG-FLAG
  -> 2000-FIND-NEXT-AUTH-SUMMARY / 2000-EXIT  [loop entry]
     - DLI GN PAUTSUM0
     - EVALUATE DIBSTAT: '  ' / 'GB' / OTHER
  -> LOOP UNTIL ERR-FLG-ON OR END-OF-AUTHDB:
     -> 3000-FIND-NEXT-AUTH-DTL / 3000-EXIT
        - DLI GNP PAUTDTL1
        - EVALUATE DIBSTAT: '  ' / 'GE','GB' / OTHER
     -> INNER LOOP UNTIL NO-MORE-AUTHS:
        -> 4000-CHECK-IF-EXPIRED / 4000-EXIT
           - COMPUTE day difference
           - IF expired: approved vs declined path
           - ELSE: not qualified
        -> IF QUALIFIED-FOR-DELETE:
           -> 5000-DELETE-AUTH-DTL / 5000-EXIT
              - DLI DLET PAUTDTL1
              - IF DIBSTAT = SPACES vs error
        -> 3000-FIND-NEXT-AUTH-DTL (next iteration)
     -> IF PA-APPROVED-AUTH-CNT <= 0 AND PA-APPROVED-AUTH-CNT <= 0:
        -> 6000-DELETE-AUTH-SUMMARY / 6000-EXIT
           - DLI DLET PAUTSUM0
           - IF DIBSTAT = SPACES vs error
     -> IF WS-AUTH-SMRY-PROC-CNT > P-CHKP-FREQ:
        -> 9000-TAKE-CHECKPOINT / 9000-EXIT
           - DLI CHKP
           - IF DIBSTAT = SPACES:
              - IF WS-NO-CHKP >= P-CHKP-DIS-FREQ: display
           - ELSE: error -> 9999-ABEND
     -> 2000-FIND-NEXT-AUTH-SUMMARY (next iteration)
  -> 9000-TAKE-CHECKPOINT (final)
  -> GOBACK

  9999-ABEND / 9999-EXIT
     - MOVE 16 TO RETURN-CODE, GOBACK
```

**17 paragraphs, 41 branch probes**

Baseline: 12/17 paragraphs (70.6%), 12/41 branches (29.3%)

Missing at baseline: likely 5000-DELETE-AUTH-DTL, 6000-DELETE-AUTH-SUMMARY,
9000-TAKE-CHECKPOINT, and several branch arms in EVALUATE/IF blocks.
