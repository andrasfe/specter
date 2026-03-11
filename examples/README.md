# How to run examples

## 1. Generate Python from AST + run synthesis

```sh
specter examples/COPAUA0C.cbl.ast -o examples/COPAUA0C.py --synthesize --test-store examples/tests.jsonl --exclude-values examples/exclude.txt
```

## 2. Instrument COBOL source for mock execution

Requires the [CardDemo](https://github.com/aws-samples/aws-mainframe-modernization-carddemo) repo cloned alongside this one.

```sh
specter ../aws-mainframe-modernization-carddemo/app/app-authorization-ims-db2-mq/cbl/COPAUA0C.cbl --copybook-dir ../aws-mainframe-modernization-carddemo/app/app-authorization-ims-db2-mq/cpy --copybook-dir ../aws-mainframe-modernization-carddemo/app/app-authorization-ims-db2-mq/cpy-bms -o ./examples/COPAUA0C.mock.cbl
```

## 3. Compile mock with GnuCOBOL

```sh
cobc -x -o examples/COPAUA0C.mock ./examples/COPAUA0C.mock.cbl
```

## 4. Compare Python vs COBOL outputs

Runs each test case through both the generated Python and the compiled COBOL mock, then compares DISPLAY output.

```sh
python3 examples/run_mock.py examples/COPAUA0C.mock examples/COPAUA0C.py examples/tests.jsonl
```

The pipeline for each test case:
1. Run Python with `_stub_log` enabled to capture execution-ordered stub calls
2. Generate mock data file with records in the exact execution order
3. Run the compiled COBOL binary with that mock data
4. Compare DISPLAY output between Python and COBOL
