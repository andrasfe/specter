# Specter Fuzzing Algorithm

Specter uses coverage-guided greybox fuzzing to explore execution paths through generated COBOL simulations. The technique is program-agnostic — all heuristics derive from the AST structure, variable naming conventions, and runtime feedback.

## Pipeline

```
COBOL AST
  -> variable extraction (classify each var as status/flag/input/internal)
  -> static analysis (call graph, gating conditions, equality constraints)
  -> Python code generation (instrumented: traces paragraphs, tracks var reads/writes)
  -> coverage-guided fuzzing loop
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

Each classification gets domain-aware random value generation:
- **Status vars**: file status codes (`00`, `10`, `35`...), SQL codes (`0`, `100`, `-803`...), CICS response codes, IMS status codes
- **Flags**: boolean or harvested condition literals (`Y`/`N`, `True`/`False`)
- **Inputs**: pattern-matched by name — dates, times, keys, amounts, counts, days
- **Internals**: seeded from condition literals found in the AST when available

## Condition Literal Harvesting

The variable extractor scans all IF/EVALUATE conditions in the AST and collects the literal values each variable is compared against. For example, `IF WS-STATUS = '00' OR '10'` harvests `['00', '10']` for `WS-STATUS`. These harvested literals are used throughout:

- The **first** harvested literal is assumed to be the "success" value
- Random generation prefers harvested literals 50-70% of the time
- Literal-guided mutation picks exclusively from harvested values

## Static Analysis

Three analyses feed into the fuzzer:

### Call Graph
Built by walking PERFORM/CALL statements. Classifies every paragraph as **reachable** or **unreachable** from the entry point. Used to avoid wasting effort on structurally dead code and to compute directed fuzzing paths.

### Gating Conditions
For each paragraph, extracts the IF conditions that guard entry along the call path from the entry point. These are the constraints that must be satisfied for execution to reach a given paragraph. Used by directed fuzzing to set variables that satisfy the path.

### Equality Constraints
Detects `IF A NOT EQUAL B` patterns where both operands are variables. These represent implicit invariants (e.g., two date fields that must match). Applied when generating all-success states to ensure constrained variable pairs hold equal values.

## Fuzzing Loop

### Seed Injection (pre-loop)

Before the main loop, inject 3 **all-success seeds** into the corpus:

1. Set every status variable to its success value (first harvested literal, or `"00"`/`0` by convention)
2. Set every flag to its first harvested literal (or `False`)
3. Set inputs to sensible non-zero defaults (dates, amounts, counts)
4. Apply equality constraints (copy var_a's value to var_b)
5. Generate all-success stub outcomes for every external operation, with EOF/end-of-cursor terminators for reads and SQL cursors

This guarantees the corpus starts with entries that survive initialization gauntlets — sequences of 40+ `OPEN file -> IF status != '00'` checks where P(all pass randomly) is near zero.

### Exploration Phase (first 30% of iterations)

Two strategies, mixed:

- **30% of explore iterations**: All-success state with random perturbations to non-status variables. Preserves initialization passage while diversifying post-initialization state.
- **70% of explore iterations**: Fully random state. Status variables get an 80% success bias. Flags and inputs prefer harvested condition literals 70% of the time.

### Exploitation Phase (remaining 70%)

Select a seed from the corpus (weighted by energy), then apply one mutation:

| Weight | Strategy | Description |
|---|---|---|
| 30% | Single-var flip | Replace one variable with a random domain-aware value |
| 18% | Literal-guided | Pick a variable that has harvested condition literals; set it to one of them |
| 12% | Gate-preserving | Mutate 1-3 non-status variables only, preserving initialization passage |
| 12% | Multi-var flip | Replace 2-4 variables simultaneously |
| 8% | Crossover | Copy 1-3 variables (and stub outcomes) from a different corpus entry |
| 5% | Reset-to-default | Set one variable to its zero/empty value |
| 10% | Stub flip | Re-randomize one external operation's return status |
| 5% | Full stub regen | Regenerate all stub outcomes from scratch |

### Corpus Management

A new entry is added to the corpus when it discovers:
- A **new paragraph** (not yet in global coverage), or
- A **new edge** (caller -> callee transition not yet seen), or
- A **new branch** (IF true/else or EVALUATE WHEN not yet taken)

The corpus is capped at 500 entries. When full, the lowest-energy entry whose coverage is fully redundant (subset of other entries' combined coverage) is evicted.

### Recursion Avoidance

COBOL programs can have mutual recursion via PERFORM (e.g., error handler calls termination, termination calls error handler). The fuzzer:

1. **Generated code** enforces a call depth limit of 200 per paragraph, with try/finally to always decrement
2. **Fuzzer** fingerprints the status/flag variable values of any state that triggers RecursionError
3. Future candidate states matching a known recursion fingerprint are skipped entirely

Up to 10,000 fingerprints are retained.

### Energy Scoring

Every 100 iterations, corpus entry energies are recalculated:

- **Frontier bonus** (+3.0 per covered paragraph that is a caller in the call graph — these are branch points that might lead to uncovered code)
- **Recency bonus** (0.0 to 1.0, linear by iteration number when added)
- **Yield penalty** (x0.1 if mutated >10 times with zero children added to corpus)
- **Floor**: energy never drops below 0.01

Seed selection uses weighted random sampling by energy.

### Stale Detection and Directed Fuzzing

When 1,000 consecutive iterations produce no new coverage:

1. **Pick a target**: select an uncovered-but-reachable paragraph, weighted by 1/path_length (shorter paths are easier to reach)
2. **Generate directed input**: start from the corpus entry with maximum overlap on the target's call path, then set variables to satisfy gating conditions along the remaining path
3. **Attempt limit**: 200 tries per target before switching to a new one
4. **Fallback**: if no static analysis is available or all reachable paragraphs are covered, emit a burst of 50 fully random iterations to escape local optima

## Stub Outcome Generation

External operations are stubbed with pre-generated return values. Each outcome entry is a batch of `(variable, value)` pairs — one per status variable associated with the operation.

Repetition counts per operation type:

| Operation | Success Reps | Notes |
|---|---|---|
| CALL | 10 | May be invoked many times |
| READ | 5 + EOF | 5 successes then status `"10"` (end of file) |
| SQL | 50 + end | 50 successes then SQLCODE `100` (not found) |
| START | 10 | Positioning operations |
| OPEN/CLOSE | 3 | Typically invoked once or twice |

Random stub generation uses a 60% success bias. All-success stubs use 100% success with explicit EOF terminators.

## Branch-Level Coverage

In addition to paragraph and edge coverage, the fuzzer tracks **branch-level coverage**. Each IF statement in the generated code is assigned a unique branch ID. When the true branch is taken, the positive ID is recorded; when the else branch is taken, the negative ID is recorded. Similarly, each WHEN clause in an EVALUATE statement gets its own branch ID.

This provides finer-grained feedback than paragraph coverage alone — two executions may reach the same paragraph but take different branches within it. The corpus accepts new entries that discover previously unseen branch IDs.

## COBOL Statement Coverage

### SEARCH (Table Lookup)

COBOL SEARCH statements (sequential table lookup with VARYING index, AT END, and WHEN clauses) are stubbed similarly to external operations. Each SEARCH generates a stub key (`SEARCH:<table_name>`) whose outcomes are boolean found/not-found values. The AT END and WHEN branches are extracted from the statement text and translated to Python assignments, PERFORM calls, and GO TO jumps.

SEARCH outcomes are generated using a separate RNG to avoid disrupting the main fuzzing sequence.

### REWRITE (Record Update)

REWRITE statements are handled identically to WRITE — they apply a stub outcome for the associated file operation, setting the file status variable.

### PERFORM VARYING (Counted Loops)

PERFORM VARYING statements (`PERFORM paragraph VARYING var FROM x BY y UNTIL condition`) generate proper loop initialization and increment logic. The loop variable is set to the FROM value before the loop, and incremented by the BY value after each iteration.

## Generated Code Resilience

The generated Python code includes several safety mechanisms:

- **SafeDict**: returns `''` for missing keys instead of raising KeyError (handles COBOL subscripted variables like `VAR(I)` where the index hasn't been set)
- **Call depth guard**: every paragraph checks and increments a depth counter on entry, decrements in a `finally` block
- **ZeroDivisionError catch**: COMPUTE/DIVIDE expressions with zero divisors set `_abended = True` instead of crashing
- **PERFORM THRU**: executes all paragraphs in program order from target through thru-target, not just the first

## Deterministic Test Set Synthesis (`--synthesize`)

In addition to the random fuzzer, Specter includes a deterministic, layered synthesis engine that generates a minimal test set targeting maximum branch coverage. Unlike the Monte Carlo fuzzer, synthesis is repeatable — given the same AST, it produces the same test set.

### Architecture

The engine runs layers sequentially, each building on prior coverage. Test cases are persisted to a JSONL test store, allowing incremental re-runs (completed layers are skipped).

### Layers

| Layer | Name | Strategy | Typical Yield |
|-------|------|----------|---------------|
| 1 | All-Success Seeds | 5 seed TCs with status=success, equality constraints applied | ~200 branch dirs |
| 2 | Per-Paragraph Direct Invocation | Invoke each paragraph function directly with default state | ~1100 branch dirs |
| 2.5 | Frontier Expansion | Try adjacent paragraphs from Layer 2's traces | ~40 branch dirs |
| 3 | Condition-Targeted | Parse each uncovered branch's condition, set variables to satisfy/negate it | ~700 branch dirs |
| 3.5 | Paragraph Sweep | Full condition sweep per paragraph with cartesian products, Phase 3 targeted flip | ~400 branch dirs |
| 3.7 | Stub Fault Injection | Dataflow analysis to find stub-dependent branches | 0-5 branch dirs |
| 4 | Stub Combination | Systematically vary external operation return codes | 0-5 branch dirs |
| 5 | Mutation Walks | Hill-climbing: mutate best TCs for 100 rounds, keep improvements | ~15 branch dirs |
| 6 | Branch Direction Flip | For each flippable branch (one direction covered), try to flip via condition manipulation | ~20 branch dirs |
| 7 | Random Exploration | Targeted random state generation per high-gap paragraph with hill-climbing | ~100+ branch dirs |

### Branch Instrumentation

Every IF statement emits both `+bid` (TRUE taken) and `-bid` (FALSE taken) branch IDs, including an explicit `else` clause for IF-without-ELSE patterns. EVALUATE WHEN clauses emit `+bid` only (FALSE is implicit when a different WHEN matches). PERFORM UNTIL and SEARCH emit both directions.

Branch metadata is stored in `_BRANCH_META`, a module-level dict mapping each absolute branch ID to `{condition, paragraph, type, subject}`.

### Condition Parser

`_parse_condition_variables()` extracts `(variable, values, negated)` triples from COBOL condition strings. It handles:

- Simple comparisons: `WS-STATUS = '00'`
- Multi-value lists: `FS-FILE NOT EQUAL '00' AND '04' AND '05'`
- Variable-to-variable: `TRANS-TYPE EQUAL REGLR-DEF-TXN-CODE` (both vars emitted with `[0]` marker)
- Compound AND/OR: split on top-level logical operators, recurse
- Figurative constants: ZEROS, SPACES, LOW-VALUES
- Flag conditions: bare `SCHEDULE-FILE-ERROR` or `NOT C-VSAM-FILE-OK`
- COBOL decimal commas: `1000000,00` parsed as `1000000.0`
- Subscripted variables: `VAR(I)` stripped to `VAR`

### Variable-to-Variable Comparisons

When the condition compares two variables (e.g., `A EQUAL B`), the synthesis looks up the current runtime value of the RHS variable in the base state or defaults, then sets the LHS to match (for TRUE) or differ (for FALSE). This avoids the problem of setting both to an arbitrary constant like `42` which fails when the RHS already has a different default value.

### Layer 7: Random Exploration

The most aggressive layer. For each paragraph with 3+ uncovered branch directions:

1. Collect all condition literals referenced by uncovered branches in that paragraph
2. For 500 trials, generate a state by randomly setting condition variables to known literals (40%), random domain values (20%), or leaving defaults (40%)
3. Also perturb 1-8 random variables and occasionally vary stub outcomes
4. Hill-climbing: when a trial discovers new branches, use that state as the base for subsequent trials (70% of the time; 30% restart from the original base TC)

### Paragraph Name Sanitization

COBOL paragraph names like `R--1CF2` (double dash) are sanitized to Python function names via `re.sub(r"_+", "_", name.replace("-", "_"))`, collapsing consecutive underscores. The synthesis engine and direct invocation use the same sanitization to correctly resolve function names.

### Coverage Ceiling

Some branch directions are structurally unreachable:
- EVALUATE WHEN FALSE: only TRUE (`+bid`) is instrumented per WHEN clause, since FALSE is implicit
- Sub-paragraph state overwrite: branches depending on variables set by called sub-paragraphs cannot be controlled via input state alone
