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

## 3. Generate Python + synthesize with COBOL validation

Each candidate test case is validated against the compiled COBOL binary before being accepted into the test store.

```sh
specter examples/COPAUA0C.cbl.ast -o examples/COPAUA0C.py --synthesize --test-store examples/tests.jsonl --exclude-values examples/exclude.txt --cobol-validate examples/COPAUA0C.mock
```

## 4. Compare Python vs COBOL outputs (standalone)

Runs each test case through both the generated Python and the compiled COBOL mock, then compares DISPLAY output.

```sh
python3 examples/run_mock.py examples/COPAUA0C.mock examples/COPAUA0C.py examples/tests.jsonl
```

## How it works

For each test case the validation pipeline:
1. Runs the generated Python with `_stub_log` to capture execution-ordered stub calls
2. Generates a mock data file with records in the exact order the COBOL program will consume them
3. Runs the compiled COBOL binary with that mock data
4. Compares DISPLAY output between Python and COBOL — rejects mismatches
