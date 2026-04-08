# How to run examples

Replace `$PROG` below with your program name, and point the copybook and source
paths at your own COBOL sources.

## 1. Instrument COBOL source for mock execution

```sh
specter path/to/$PROG.cbl \
  --copybook-dir path/to/cpy \
  --copybook-dir path/to/cpy-bms \
  -o ./examples/$PROG.mock.cbl
```

## 2. Compile mock with GnuCOBOL

```sh
cobc -x -o examples/$PROG.mock ./examples/$PROG.mock.cbl
```

## 3. Generate Python + COBOL-first synthesis

Synthesis generates candidate inputs using Python (fast, in-process), then validates each candidate against the compiled COBOL binary. **COBOL coverage drives acceptance** — a test case is only accepted if it adds new COBOL paragraph coverage and Python DISPLAY output matches COBOL.

```sh
specter examples/$PROG.cbl.ast \
  -o examples/$PROG.py \
  --synthesize \
  --test-store examples/tests.jsonl \
  --exclude-values examples/exclude.txt \
  --cobol-validate examples/$PROG.mock
```

## 4. COBOL-first comparison

Runs each test case through the compiled COBOL mock (ground truth), then checks that the generated Python produces identical DISPLAY output.

```sh
python3 examples/run_mock.py examples/$PROG.mock examples/$PROG.py examples/tests.jsonl
```

## 5. Generate Java project

Generates a Maven project with one Paragraph subclass per COBOL paragraph, runtime support classes, and JUnit 5 integration tests from the test store.

```sh
specter examples/$PROG.cbl.ast \
  --java \
  --test-store examples/tests.jsonl \
  -o examples/$PROG/
```

The project is created at `examples/$PROG/$PROG/` with:
- `src/main/java/` — generated paragraph classes + runtime (ProgramState, CobolRuntime, etc.)
- `src/test/java/` — parameterized JUnit 5 tests (one per test store entry)
- `src/test/resources/test_store.jsonl` — test data copied from synthesis output
- `pom.xml` — Maven build with JUnit 5 + Gson (test) + Lanterna (UI)

## 6. Build and test Java project

```sh
cd examples/$PROG/$PROG
mvn test
```

Or without Maven (manual compile + JUnit console launcher):

```sh
cd examples/$PROG/$PROG
find src/main -name "*.java" | xargs javac -cp "lib/*" -d out/main
find src/test -name "*.java" | xargs javac -cp "lib/*:out/main" -d out/test
cp src/test/resources/test_store.jsonl out/test/
java -jar lib/junit-platform-console-standalone-1.10.2.jar \
  --class-path "out/main:out/test:lib/gson-2.10.1.jar" \
  --scan-class-path out/test
```

## How it works

COBOL-first pipeline for each test case:
1. Python runs the candidate (fast, in-process) to capture stub consumption order (`_stub_log`)
2. A mock data file is generated with records in the exact order COBOL will consume them
3. The compiled COBOL binary runs with that mock data — this is the **ground truth**
4. Paragraph coverage is extracted from `SPECTER-TRACE:` output
5. Python DISPLAY output is compared against COBOL DISPLAY output
6. If Python diverges from COBOL, the test case is flagged — COBOL is always right

Java generation uses the same AST and test store. Each test case from synthesis becomes a parameterized JUnit test that wires `input_state`, `stub_outcomes`, and `stub_defaults` into the Java program's `ProgramState`, runs it, and asserts no abend + expected paragraph coverage.
