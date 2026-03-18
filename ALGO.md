# Specter Coverage Algorithm

Specter uses a strategy-based agentic loop to explore execution paths through generated COBOL simulations. The technique is program-agnostic — all heuristics derive from the AST structure, variable naming conventions, and runtime feedback.

## Pipeline

```
COBOL AST
  → variable extraction (classify each var as status/flag/input/internal)
  → static analysis (call graph, gating conditions, equality constraints)
  → Python code generation (instrumented: traces paragraphs, tracks branches)
  → strategy-based coverage loop
```

## State Model

All COBOL state lives in a single flat dictionary (`state`). Keys are uppercase variable names (`'WS-STATUS'`). Internal bookkeeping keys are prefixed with `_` (`_trace`, `_calls`, `_stub_outcomes`, etc.).

External operations (CALL, READ, EXEC SQL, OPEN, CLOSE) are replaced with **stubs** that pop pre-generated outcomes from `state['_stub_outcomes'][op_key]`. Each outcome is a list of `(variable, value)` pairs, setting all status variables for that operation in one shot.

## Variable Classification

Variables are classified by naming conventions and access patterns:

| Classification | Detection | Examples |
|---|---|---|
| **status** | Names containing `STATUS`, `SQLCODE`, `RETURN-CODE`, `EIBRESP`, `FS-` prefix | `WS-FILE-STATUS`, `SQLCODE` |
| **flag** | Names containing `FLAG`, `FLG`, `SW-`, boolean-like usage | `WS-EOF-FLAG`, `SW-VALID` |
| **input** | Read-before-write in the AST (consumed before produced) | `WS-ACCOUNT-NUM` |
| **internal** | Everything else (written before read, workspace temps) | `WS-WORK-AREA` |

### Domain-Aware Value Generation

Each classification gets domain-aware random value generation:
- **Status vars**: file status codes (`00`, `10`, `35`...), SQL codes (`0`, `100`, `-803`...), CICS response codes, IMS status codes
- **Flags**: boolean or harvested condition literals (`Y`/`N`, `True`/`False`)
- **Inputs**: pattern-matched by name — dates, times, keys, amounts, counts
- **Internals**: seeded from condition literals found in the AST when available

### Condition Literal Harvesting

The variable extractor scans all IF/EVALUATE conditions in the AST and collects the literal values each variable is compared against. For example, `IF WS-STATUS = '00' OR '10'` harvests `['00', '10']` for `WS-STATUS`. These are used everywhere: stub default generation, value pools for random exploration, and domain-aware fault tables.

## Static Analysis

### Call Graph
Built by walking PERFORM/CALL statements. Classifies every paragraph as reachable or unreachable from the entry point.

### Gating Conditions
For each paragraph, extracts the IF conditions that guard entry along the call path from the entry point.

### Equality Constraints
Detects `IF A NOT EQUAL B` patterns where both operands are variables. Applied when generating success states to ensure constrained variable pairs hold equal values.

## Strategy-Based Agentic Loop

The coverage engine uses a **strategy selector** that picks the next strategy based on coverage feedback. Each strategy generates `(input_state, stubs, defaults, target)` tuples. The agentic loop executes them and saves test cases that discover new coverage.

### Execution Modes

- **Full run**: `module.run(state)` — executes from the program entry point
- **Direct paragraph invocation**: `_run_paragraph_directly(module, para, state)` — calls a single paragraph function directly (~1ms), bypassing the entry point. Reaches branches not reachable through normal control flow. Signaled by `target` strings starting with `"direct:"`.

### Strategy Rotation

The primary strategy is `DirectParagraphStrategy`, which rotates through **six phases** on each invocation. Each phase uses direct paragraph invocation for speed and benefits from coverage gains made by the previous phases.

```
Phase 0: Param    → Phase 1: Stub    → Phase 2: Dataflow
  ↑                                           ↓
Phase 5: Inverse  ← Phase 4: Harvest ← Phase 3: Frontier
```

#### Phase 0 — Param (Hill-Climb Inputs)

Freeze stubs from the best existing test case for each paragraph. Hill-climb input parameters using condition-aware random perturbation:
- 40%: pick from condition literals (values seen in IF/EVALUATE conditions)
- 30%: random domain-aware value (flag, numeric, or string)
- 30%: leave at base value

Plus 1-8 extra random variable perturbations per trial. This is the primary coverage driver — handles directly settable conditions.

#### Phase 1 — Stub (Sweep Fault Configurations)

Freeze inputs from the best test case for each paragraph. Sweep through **domain-aware fault values** for each stub operation:

1. **Condition literals** from the status variable's domain (actual values the program checks)
2. **88-level values** from COBOL declarations
3. **Generic fault table** fallback (file status codes, SQL codes, CICS codes)

Each fault config is tried with the frozen inputs via direct invocation. Unlocks stub-dependent branches (error handling, EOF processing, etc.).

#### Phase 2 — Dataflow (Backpropagation of Constraints)

For branches where the condition variable is **computed** (not directly settable), traces backward through the generated Python code to find what input values produce the needed output:

1. **Parse paragraph source**: extract `state['VAR'] = expr` assignments and their dependency variables
2. **Trace backward**: from condition variable through assignment chain (up to 5 levels deep)
3. **Inter-procedural**: if no local assignment exists, traces through sub-paragraph calls
4. **Solve inverse**: given the computation type (multiply, add, subtract, divide, modulo, MOVE), compute input values that satisfy the branch condition
5. **Cross with stubs**: try each solved state with success stubs AND fault configs

Example: branch checks `IF WS-RESULT > 0` where `WS-RESULT = WS-AMT * WS-RATE`. Backprop determines `WS-AMT` and `WS-RATE` must both be non-zero.

#### Phase 3 — Frontier (Flip Branches to Unlock Paragraphs)

Goal-directed: identifies branches in covered paragraphs that **gate uncovered paragraphs** via the call graph.

1. Walk call graph: for each covered paragraph A that calls uncovered paragraph B, find untaken branches in A
2. Run best test case for A, **inspect final runtime state** to see current variable values
3. Flip the condition: set variables to values that make the branch go the other direction
4. Also handle stub-controlled variables in the condition

#### Phase 4 — Harvest (Rainbow Table)

Empirical inverse: run each paragraph hundreds of times with random inputs, record `(input_state, final_state)` pairs. Then for each uncovered branch, scan the rainbow table for an input that produces the desired output value.

This solves complex multi-variable conditions that symbolic analysis can't crack — the brute-force mapping finds inputs that happen to satisfy the condition through arbitrary computation paths.

#### Phase 5 — Inverse (Synthesized Inverse Functions)

For each uncovered branch gated by arithmetic, **dynamically generates and `exec()`s an inverse function**:

1. Parse the paragraph's assignment chain for the condition variable
2. Identify the computation type (multiply, add, subtract, divide, modulo, MOVE)
3. Generate Python source for an inverse solver (e.g., `A * B = target → A = sqrt(target) + 1`)
4. `exec()` the solver with the desired target value
5. Use the solved input values as test case inputs

This is effectively on-the-fly program synthesis — creating the inverse of a paragraph's computation chain as executable code.

### Supporting Strategies

In addition to `DirectParagraphStrategy`, the loop includes:

| Strategy | Priority | Purpose |
|----------|----------|---------|
| **BaselineStrategy** | 20 | Initial seeds: 5 value-generation strategies + condition literal sweeps |
| **ConstraintSolverStrategy** | 30 | Path-constraint satisfaction for uncovered paragraphs |
| **BranchSolverStrategy** | 40 | Per-branch condition solving via full program run |
| **FaultInjectionStrategy** | 50 | Single-fault stub injection with random inputs |
| **StubWalkStrategy** | 55 | Frozen good inputs × fault sweeps + pairwise faults |
| **GuidedMutationStrategy** | 60 | Random walks mutating high-coverage test cases |
| **MonteCarloStrategy** | 70 | Broad random exploration with mixed strategies |

### Selector

`HeuristicSelector` picks the next strategy by priority, adjusted by yield history:
- **Yield bonus**: strategies that found coverage recently get priority boost
- **Staleness penalty**: strategies that haven't yielded in 3+ rounds get deprioritized
- Exhausted deterministic strategies self-disable until new coverage appears from other strategies

### Termination

- **Full coverage**: all paragraphs and all branches covered
- **Extended plateau**: 30 consecutive rounds with no new coverage (at >90% paragraph coverage and >80% branch coverage, threshold drops to 10 rounds)
- **Budget/timeout**: configurable test case budget and wall-clock timeout

## Stub Outcome Generation

External operations are stubbed with pre-generated return values. Each outcome entry is a batch of `(variable, value)` pairs — one per status variable associated with the operation.

| Operation | Success Reps | Notes |
|---|---|---|
| CALL | 10 | May be invoked many times |
| READ | 5 + EOF | 5 successes then status `"10"` (end of file) |
| SQL | 50 + end | 50 successes then SQLCODE `100` (not found) |
| START | 10 | Positioning operations |
| OPEN/CLOSE | 3 | Typically invoked once or twice |

When stub outcomes are exhausted at runtime, a **default fallback** is applied. Defaults prefer harvested condition literals (the first value the variable is compared against in IF conditions), which captures domain-specific success conventions — e.g., IMS PCB status codes use spaces `' '` for success rather than file-status `'00'`.

## Branch Instrumentation

Every IF statement emits both `+bid` (TRUE taken) and `-bid` (FALSE taken) branch IDs, including an explicit `else` clause for IF-without-ELSE patterns. EVALUATE WHEN clauses emit `+bid` only (FALSE is implicit when a different WHEN matches). PERFORM UNTIL and SEARCH emit both directions.

Branch metadata is stored in `_BRANCH_META`, a module-level dict mapping each absolute branch ID to `{condition, paragraph, type, subject}`.

## Generated Code Resilience

- **SafeDict**: returns `''` for missing keys instead of raising KeyError (handles COBOL subscripted variables)
- **Call depth guard**: every paragraph checks and increments a depth counter on entry, decrements in `finally`
- **ZeroDivisionError catch**: COMPUTE/DIVIDE expressions with zero divisors set `_abended = True`
- **PERFORM THRU**: executes all paragraphs in program order from target through thru-target

## GnuCOBOL Coverage Mode

When `--cobol-coverage` is used, the engine compiles and runs real COBOL via GnuCOBOL. This adds a second execution path alongside the Python simulation.

### COBOL Instrumentation Pipeline

```
COBOL source + copybooks
  → Phase 1-5:   COPY resolution, EXEC/IO/CALL replacement with mock reads
  → Phase 6:     Paragraph tracing (DISPLAY 'SPECTER-TRACE:<para>')
  → Phase 6b:    Branch tracing (DISPLAY '@@B:<id>:<direction>')
  → Phase 7-10:  Mock infrastructure, linkage conversion, file handling
  → Phase 11:    Common stubs (DFHAID, EIB fields, DFHRESP)
  → Phase 12:    Auto-stub undefined symbols via cobc diagnostics
  → Phase 12b:   Restore trace probes destroyed by Phase 12
  → Phase 13:    ASCII normalization
  → compile with cobc -x → executable
```

### Hybrid Execution

The agentic loop uses two execution modes:

| Target | Execution | Speed | Use case |
|--------|-----------|-------|----------|
| Full program | Python pre-run → COBOL binary | ~10-50ms | Baseline, fault injection, monte carlo |
| Direct paragraph | Python only | ~0.01ms | DirectParagraphStrategy's 6 phases |

Direct paragraph invocation can't run through COBOL (no way to enter mid-program), so it uses the Python simulation. Python branch IDs are prefixed with `py:` to avoid collision with COBOL `@@B:` IDs. Only COBOL branches count toward the reported coverage percentage.

### CICS Coverage Mode

CICS online programs use pseudo-conversational design (RECEIVE MAP → process → SEND MAP → RETURN). Three fixes enable deep coverage:

1. **No-terminate mode**: `EXEC CICS RETURN/XCTL` replaced with mock-read + `CONTINUE` instead of `GO TO SPECTER-EXIT-PARA`
2. **EIB stub initialization**: `EIBCALEN VALUE 100` and `EIBAID VALUE X'7D'` (DFHENTER) hardcoded in VALUE clauses so programs skip first-time initialization
3. **EIBAID injection**: `CICS RECEIVE MAP` mock adds `MOVE MOCK-ALPHA-STATUS(1:1) TO EIBAID` so EVALUATE EIBAID branches are reachable

### File I/O Mocking

File READ/WRITE/OPEN/CLOSE verbs are replaced with sequential reads from a mock data file. Key mechanisms:

- **File status propagation**: `FILE STATUS IS <var>` is extracted from SELECT clauses; after each mock read, `MOVE MOCK-ALPHA-STATUS TO <status-var>` is inserted so 88-level conditions evaluate correctly
- **READ loop termination**: Stub outcomes for READ operations include 5 success records followed by EOF (status `'10'`), with EOF as the default, so PERFORM UNTIL loops terminate
- **Mock record format**: 80-byte LINE SEQUENTIAL records: op-key `PIC X(30)` + alpha-status `PIC X(20)` + num-status `PIC S9(09)` (9 bytes) + filler `PIC X(21)`
- **Padding**: 50 extra success records appended to prevent EOF when COBOL consumes more records than the Python pre-run predicted

### Trace Probe Resilience

Phase 12 (`_auto_stub_undefined_with_cobc`) neutralizes paragraphs with undefined symbols by replacing their bodies with `CONTINUE`. This destroys trace probes and branch probes. Phase 12b (`_restore_paragraph_tracing`) re-inserts `DISPLAY 'SPECTER-TRACE:<para>'` for any paragraph header missing one after all compilation fixes are done.

### Results

Tested on 14 CardDemo programs:

| Category | Programs | Paragraph Coverage |
|----------|----------|-------------------|
| CICS online | 11 | **100%** (all 11) |
| IMS batch | 1 (COPAUA0C) | **100%** (43/43) |
| Batch file I/O | 3 (CBEXPORT, CBACT04C, CBTRN02C) | 52-73% |

Branch coverage ranges 26-62% across all programs.

## Coverage Ceiling

Some branch directions are structurally unreachable:
- EVALUATE WHEN FALSE: only TRUE is instrumented per WHEN clause
- Sub-paragraph state overwrite: branches depending on variables set by called sub-paragraphs may require specific execution ordering not achievable via direct invocation
- Neutralized paragraph bodies: Phase 12 may comment out IF/EVALUATE structures in paragraphs with undefined external symbols (MQ, DLI), eliminating their branch probes
