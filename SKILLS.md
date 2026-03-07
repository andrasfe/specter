# Skills for Agentic COBOL-to-Python Code Generation

This document teaches agentic coding tools how to approach COBOL mainframe programs that need to be understood, transpiled, tested, or simulated in Python. The lessons are general — not tied to any specific program.

---

## Skill 1: Understanding COBOL Program Structure

### The PROCEDURE DIVISION Driver Problem

COBOL programs often have an **unnamed code block** at the start of the PROCEDURE DIVISION, before the first named paragraph. This block is the actual entry point — it PERFORMs named paragraphs, then GOBACKs.

```cobol
       PROCEDURE DIVISION.
           PERFORM INIT-PARA THRU INIT-EXIT.
           PERFORM MAIN-PARA THRU MAIN-EXIT.
           GOBACK.
       INIT-PARA.
           ...
```

**Key insight:** If your AST parser only captures named paragraphs, you will miss the driver section entirely. The result is that static analysis will show almost everything as unreachable. When you see suspiciously low reachability (e.g., 2 out of 142 paragraphs), the first thing to check is whether the unnamed driver section was captured.

**Fix:** Add an `entry_statements` field to your program model. Parse the unnamed driver block into it. Use a synthetic `_ENTRY_` node in your call graph.

### PERFORM THRU Ranges

`PERFORM A THRU B` executes all paragraphs from A through B in source order. Your call graph must add edges to every paragraph in the range, not just A and B.

### Fall-Through vs. PERFORM-Based Programs

COBOL has two execution models:
1. **Fall-through:** Paragraphs execute sequentially top-to-bottom (old style).
2. **PERFORM-based:** The driver PERFORMs specific paragraphs, then GOBACKs. Paragraphs don't fall through.

Most production programs use model 2. Check for GOBACK/STOP RUN in the driver section to determine which model applies. Do NOT blindly implement fall-through — it will cause paragraphs to execute that shouldn't.

---

## Skill 2: Dealing with Scrambled/Obfuscated Source

Enterprise COBOL sources are often scrambled by security tools that replace meaningful names with symbols like `SYM00288`. Additional artifacts include:

### Change Tags
Columns 73-80 in fixed-format COBOL are the sequence/change-tag area. Scramblers also inject tags inline:
- `G##nnnnn`, `P##nnnnn` — change tags appended to lines
- `##nnnnn` — concatenated directly with variable names (e.g., `WS-STATUS##00142`)
- `Sym00nnn` — inline comment-style tags

**Strategy:** Strip columns 73-80 first, then use regex to remove `##\d*` anywhere, clean up orphaned `.G`/`.P` at end-of-line, and strip trailing tag letters.

### Scrambled Keywords
Some scramblers replace COBOL keywords with symbols:
- `SYM00003 SECTION` might be `INPUT-OUTPUT SECTION`
- `SYM00271` might be `COPY`
- `SYM00302` might be `TRUE`
- `SYM00372` might be `SQLCODE`

**Strategy:** Build a mapping table. You can infer many mappings from context (e.g., `SYM00372` appears after EXEC SQL blocks → it's SQLCODE). Document mappings as you discover them.

---

## Skill 3: Stubbing for Compilation

To validate generated code against the original COBOL, you need the COBOL to compile. Production COBOL typically won't compile as-is because it depends on:

### What to Stub

| Feature | Why it fails | Stub strategy |
|---------|-------------|---------------|
| EXEC SQL | No DB2 precompiler | Replace with SQLCODE assignments (+100 for SELECT/FETCH, 0 for DML) |
| EXEC CICS | No CICS runtime | Replace with EIBRESP assignments |
| COPY statements | Missing copybooks | Remove, inject stub variable declarations |
| File I/O (OPEN/READ/WRITE/CLOSE) | No file definitions | Comment out, set file status to EOF |
| CALL external programs | Missing subprograms | Comment out, add CONTINUE |
| RECORDING MODE | GnuCOBOL doesn't support it | Remove |
| FILE SECTION / FD entries | Depend on file definitions | Remove, move referenced vars to WORKING-STORAGE |

### Missing Variable Injection

After removing COPY statements and FILE SECTION, many variables will be undefined. Build a pass that:
1. Collects all variable names defined in WORKING-STORAGE
2. Collects all variable names referenced in PROCEDURE DIVISION
3. Injects stub declarations for `referenced - defined`
4. Detects 88-level condition names (used in `SET x TO TRUE`, `EVALUATE WHEN x`, bare `IF x`) and creates them under a parent variable
5. Uses PIC definitions from the original source when available

### Paragraph-Header Protection

When stubbing multi-line statements (CALL USING, CLOSE with file list), the continuation-line consumer must NOT eat paragraph headers. COBOL paragraph headers are at column 8 (7 spaces + name + period). Add a guard:

```python
# Stop at paragraph headers (col 8 name + period)
if re.match(r"       [A-Z]", raw_line) and re.match(r"[A-Z][A-Z0-9-]+\.\s*$", stripped):
    break  # This is the next paragraph, not a continuation
```

Without this, stubs will silently swallow EXIT paragraphs (THRU targets), causing "not a procedure name" errors.

### Single-Line EXEC SQL

Some EXEC SQL blocks fit on one line: `EXEC SQL COMMIT END-EXEC.` Your multi-line consumer must check whether END-EXEC is already in the first line to avoid eating subsequent lines.

### Iterative Compilation

Expect 5-15 rounds of fix-compile-fix. After each `cobc` run, parse the error messages, fix the most common class of error, and retry. Batch similar fixes rather than fixing one error at a time.

---

## Skill 4: Static Reachability Analysis

### Building the Call Graph

Walk every statement in every paragraph. For each PERFORM, PERFORM THRU, or GO TO, add an edge from the containing paragraph to the target.

For PERFORM THRU, add edges to ALL paragraphs in the range (by source order).

### Gating Conditions

Many paragraphs are only reachable through IF conditions. Extract these "gating conditions" to understand what variable values are needed to reach each paragraph:

```
IF WS-FILE-STATUS = '00'
    PERFORM PROCESS-RECORD THRU PROCESS-EXIT
```

Here, `PROCESS-RECORD` is gated by `WS-FILE-STATUS = '00'`. This information is critical for test generation.

### GO TO Guards

A common COBOL pattern:
```cobol
    IF ERROR-FLAG
        GO TO PARA-EXIT.
    PERFORM NEXT-STEP.
```

After the IF, `NEXT-STEP` is implicitly gated by `NOT ERROR-FLAG`. Detect GO TO in then-branches and propagate the negated condition to subsequent PERFORMs.

### Sequential Gates (Init Gauntlets)

Initialization paragraphs often have 3+ sequential operation-then-check patterns:
```cobol
    OPEN INPUT FILE-A.
    IF FS-FILE-A NOT = '00' GO TO INIT-EXIT.
    CALL 'PROGRAM-B' ...
    IF RETURN-CODE NOT = 0 GO TO INIT-EXIT.
```

All status variables must have success values for execution to proceed past the gauntlet. Propagate these constraints to all paragraphs called after the gauntlet.

---

## Skill 5: Monte Carlo / Fuzz Testing

### Variable Classification

Classify variables by their role to generate meaningful random values:

| Classification | Heuristic | Random strategy |
|---------------|-----------|-----------------|
| Status code | Name contains STATUS, FS-, RC, SQLCODE, EIBRESP | Weighted: 80% success value, 20% error |
| Flag | PIC X(1) or 88-level | 'Y'/'N' or TRUE/FALSE |
| Date | Name contains DATE, DT, YMD | Valid date strings |
| Amount | Name contains AMT, AMOUNT, BALANCE | Random numeric in realistic range |
| Counter/index | Name contains CNT, COUNT, IDX, IX | Small integers |
| Code/type | Name contains CODE, TYPE, CD, TYP | Short alphanumeric |
| General | Everything else | Random string/number matching PIC |

### Constraint-Directed Fuzzing

After initial random runs, identify uncovered paragraphs. For each:
1. Find the shortest path from entry in the call graph
2. Collect all gating conditions along the path
3. Set input variables to satisfy those conditions
4. Run again with the directed inputs

This reliably reaches 70-90% paragraph coverage vs. 5-15% with pure random.

### Direct Paragraph Invocation

For paragraphs that remain unreachable through the normal entry point (e.g., error handlers that require specific runtime state), invoke the paragraph function directly with a constructed state dict. This sacrifices end-to-end fidelity but ensures you exercise the code.

---

## Skill 6: Code Generation Patterns

### State Dict Pattern

All COBOL variables live in a single `state: dict[str, Any]` with uppercase keys matching COBOL names. Internal bookkeeping uses underscore-prefixed keys:
- `_display` — list of DISPLAY output lines
- `_calls` — list of CALL invocations
- `_abended` — whether ABEND was called
- `_execs` — list of EXEC SQL/CICS blocks encountered

### Paragraph Functions

Each paragraph becomes `para_UPPER_NAME(state)`. GOBACK/STOP RUN raise a signal exception caught at the top level. The `run()` function sets up initial state, executes the driver (entry_statements or fall-through), catches the signal, and returns final state.

### Numeric Handling

COBOL's type system is fundamentally different from Python's. Key issues:
- COBOL variables are strings that may contain numeric values
- Arithmetic requires explicit conversion (`_to_num()` helper)
- COMP/COMP-3 fields are binary — initialize as integers
- `IS NUMERIC` checks whether a string contains only digits
- Truncation rules differ (COBOL truncates on MOVE, Python doesn't)

### Condition Translation

COBOL conditions need careful translation:
- `IF X = 'A' OR 'B'` → `if state['X'] in ('A', 'B')`
- `IF X NOT = Y` → `if state['X'] != state['Y']`
- `IF X IS NUMERIC` → `if _is_numeric(state['X'])`
- `IF X` (bare) → `if state.get('X')` (88-level flag check)
- Figurative constants: SPACES→`' '`, ZEROS→`0`, HIGH-VALUES→`'\xff'`

---

## Skill 7: Comparison/Validation Harness

### The Gold Standard

If you can compile the original COBOL with GnuCOBOL (even with stubs), you have a gold standard to validate against. The approach:

1. **Preprocess** the COBOL to remove unsupported features (EXEC SQL, etc.)
2. **Compile** with `cobc -x`
3. **Feed identical inputs** to both the COBOL executable and the Python simulation
4. **Compare DISPLAY output** — this is the primary observable behavior
5. **Iterate** on mismatches to fix code generation bugs

### Input Encoding

COBOL reads input from files, ACCEPT statements, or embedded data. For the comparison harness:
- Generate a data file with test values
- Use ACCEPT/environment variables for the COBOL side
- Pass the same values as the Python state dict
- Compare DISPLAY output line by line

### What Mismatches Tell You

| Mismatch type | Likely cause |
|--------------|-------------|
| Missing output | Paragraph not reached — check gating conditions |
| Wrong numeric value | Arithmetic truncation or COMP handling |
| Wrong string | MOVE truncation, PIC-based formatting |
| Extra output | Fall-through where there shouldn't be, or wrong IF logic |
| Different branch taken | Condition parsing error |

---

## Skill 8: Iterative Discovery Workflow

The overall workflow for tackling an unknown COBOL program:

1. **Parse** the AST and build the program model
2. **Check reachability** — if suspiciously low, look for missing driver section
3. **Extract variables** — classify inputs vs. internals
4. **Generate Python** — start with what you can, emit `pass` for unknowns
5. **Run Monte Carlo** — get baseline coverage
6. **Analyze uncovered paths** — extract gating conditions, generate directed inputs
7. **Iterate** — each round should increase coverage
8. **Validate** — if COBOL compiles, compare outputs against the gold standard
9. **Document** — record symbol mappings, business logic patterns, and anomalies

Each step reveals information that feeds back into earlier steps. Expect to revisit the AST parser and code generator multiple times as you discover new patterns in the COBOL source.
