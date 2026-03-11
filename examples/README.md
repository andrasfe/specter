# How to run examples

## 1. Instrument COBOL source for mock execution

Requires the [CardDemo](https://github.com/aws-samples/aws-mainframe-modernization-carddemo) repo cloned alongside this one.

```sh
specter ../aws-mainframe-modernization-carddemo/app/app-authorization-ims-db2-mq/cbl/COPAUA0C.cbl --copybook-dir ../aws-mainframe-modernization-carddemo/app/app-authorization-ims-db2-mq/cpy --copybook-dir ../aws-mainframe-modernization-carddemo/app/app-authorization-ims-db2-mq/cpy-bms -o ./examples/COPAUA0C.mock.cbl
```

## 2. Compile mock with GnuCOBOL

```sh
cobc -x -o examples/COPAUA0C.mock ./examples/COPAUA0C.mock.cbl
```

## 3. Generate Python + COBOL-first synthesis

Synthesis generates candidate inputs using Python (fast, in-process), then validates each candidate against the compiled COBOL binary. **COBOL coverage drives acceptance** — a test case is only accepted if it adds new COBOL paragraph coverage and Python DISPLAY output matches COBOL.

```sh
specter examples/COPAUA0C.cbl.ast -o examples/COPAUA0C.py --synthesize --test-store examples/tests.jsonl --exclude-values examples/exclude.txt --cobol-validate examples/COPAUA0C.mock
```

## 4. Compare Python vs COBOL outputs (standalone)

Runs each test case through both the generated Python and the compiled COBOL mock, then compares DISPLAY output.

```sh
python3 examples/run_mock.py examples/COPAUA0C.mock examples/COPAUA0C.py examples/tests.jsonl
```

## How it works

COBOL-first synthesis pipeline for each candidate test case:
1. Python generates candidate inputs/stub values (fast exploration via 7 synthesis layers)
2. Python runs the candidate with `_stub_log` to capture execution-ordered stub calls
3. A mock data file is generated with records in the exact order COBOL will consume them
4. The compiled COBOL binary runs with that mock data — paragraph coverage extracted from `SPECTER-TRACE:` output
5. DISPLAY outputs are compared between Python and COBOL — mismatches are rejected
6. The test case is accepted only if it adds new **COBOL** paragraph coverage
