# AGENTS.md — Specter COBOL Coverage System

## Overview

Specter is a COBOL AST-to-executable-Python code generator with coverage-guided test synthesis. It reads a JSON AST (from the cobalt parser), generates a standalone Python simulator, and runs an agentic loop to maximize paragraph and branch coverage — optionally cross-validated against real GnuCOBOL binaries.

The system has two main pipelines:
1. **Python-only**: AST → Python code → coverage-guided fuzzing
2. **GnuCOBOL hybrid**: COBOL source → incremental mock instrumentation → compile → run with mock data

---

## Architecture

```
JSON AST + COBOL source + copybooks
        │
        ▼
┌─────────────────────────────────┐
│  Core Pipeline                  │
│  ast_parser → code_generator    │  AST → Python simulator
│  condition_parser               │  COBOL conditions → Python
│  variable_extractor             │  Variable classification
└─────────┬───────────────────────┘
          │
          ├──────────────────────────────────────┐
          ▼                                      ▼
┌─────────────────────────┐   ┌──────────────────────────────┐
│  Python Coverage Engine │   │  GnuCOBOL Mock Pipeline      │
│  monte_carlo.py         │   │  incremental_mock.py          │
│  test_synthesis.py      │   │  cobol_mock.py (transforms)   │
│  coverage_strategies.py │   │  branch_instrumenter.py       │
│  cobol_coverage.py      │   │  cobol_executor.py            │
└─────────┬───────────────┘   │  cobol_fix_cache.py           │
          │                   │  llm_coverage.py (LLM calls)  │
          ▼                   └──────────┬─────────────────────┘
   JSONL test store                      │
   (input_state + stubs + coverage)      ▼
                               Compiled COBOL executable
                               + mock data → coverage traces
```

---

## Core AST Pipeline

### `specter/models.py` — Data Classes (44 lines)

| Class | Fields | Purpose |
|-------|--------|---------|
| `Statement` | type, text, line_start, line_end, attributes, children | Recursive tree node for a COBOL statement |
| `Paragraph` | name, line_start, line_end, statements | Named paragraph containing statements |
| `Program` | program_id, paragraphs, paragraph_index, entry_statements | Top-level program with paragraph lookup dict |

`Statement.walk()` provides pre-order tree traversal.

### `specter/ast_parser.py` — AST Deserialization (58 lines)

- **`parse_ast(source)`** (L33): Accepts file path, Path, or dict. Returns `Program`.
- Recursively deserializes via `_parse_statement()` (L11) and `_parse_paragraph()` (L23).
- Builds `paragraph_index` dict for O(1) lookups.

### `specter/code_generator.py` — Python Code Generation (~2400 lines)

**Entry**: `generate_code(program, var_report, instrument, copybook_records, cobol_source)` (L1853)

Generates a complete Python module with:
- `para_XXXX(state)` functions for each COBOL paragraph
- `run(state)` entry function
- ~40 statement generators (`_gen_move`, `_gen_if`, `_gen_evaluate`, `_gen_perform`, etc.)

**Runtime Helpers** (emitted into generated code):
| Class/Function | Purpose |
|----------------|---------|
| `_SafeDict(dict)` (L2056) | Returns `''` for missing keys (COBOL default behavior) |
| `_InstrumentedState(_SafeDict)` (L2074) | Tracks reads/writes/trace/call_events |
| `_GobackSignal(Exception)` (L1943) | Signal for GOBACK/STOP RUN |
| `_to_num(v)` (L1967) | Coerce to number (int/float/0) |
| `_apply_stub_outcome(state, key)` (L1993) | Pop stub outcome queue, apply variable assignments |
| `_dummy_call(name, state)` (L2037) | Stub for CALL statements |
| `_dummy_exec(kind, text, state)` (L2046) | Stub for EXEC blocks |

**Branch Instrumentation**: Every IF/EVALUATE gets a unique branch ID. Positive = TRUE taken, negative = FALSE taken. Stored in `state['_branches']` (set of int). Module-level `_BRANCH_META` maps IDs to metadata.

**State Dictionary Convention**:
```python
state['MY-VAR']           # COBOL variables (uppercase, safe access)
state['_display']         # list[str] - DISPLAY output
state['_branches']        # set[int] - Branch coverage (±ID)
state['_trace']           # list[str] - Paragraph call sequence
state['_stub_outcomes']   # dict[op_key, list] - Queued stub outcomes
state['_stub_defaults']   # dict[op_key, list] - Exhaustion defaults
state['_stub_log']        # list - Applied outcome log
state['_abended']         # bool - Abend signal
```

### `specter/condition_parser.py` — COBOL Conditions → Python (~500 lines)

**Entry**: `cobol_condition_to_python(condition)` — converts COBOL IF/WHEN text to Python expression.

Handles: comparisons, figurative constants (SPACES, ZEROS, HIGH-VALUES), DFHRESP codes (NORMAL→0, ERROR→1, NOTFND→13, etc.), IS NUMERIC, multi-value OR, AND/OR/NOT, subscripted variables.

### `specter/variable_extractor.py` — Variable Discovery (~700 lines)

**Entry**: `extract_variables(program)` → `VariableReport`

Classifies each variable as: `input` (read-before-write), `internal`, `status` (SQLCODE, EIBRESP, FS-*), or `flag` (boolean). Harvests `condition_literals` from IF/EVALUATE comparisons for biased test generation.

### `specter/variable_domain.py` — Domain Model (~450 lines)

**`VariableDomain`** (L22): Merges PIC clauses (from copybooks), AST analysis, stub mappings, and naming heuristics.

**`build_variable_domains()`** (L117): Builds domain for every variable.

**`generate_value(domain, strategy)`** (L219): 6 strategies — condition_literal, 88_value, boundary, semantic, random_valid, adversarial.

### `specter/copybook_parser.py` — Copybook Parsing (~550 lines)

**`parse_copybook(text)`** (L110): Parses COBOL copybook → `CopybookRecord` with `CopybookField` entries (level, name, PIC type/length/precision, OCCURS, 88-level values).

Also generates SQL DDL and Java DAO classes.

---

## GnuCOBOL Mock Pipeline (Incremental Instrumentation)

### `specter/incremental_mock.py` — Main Pipeline (~1600 lines)

**Entry**: `incremental_instrument(source_path, copybook_dirs, output_dir, llm_provider, ...)`

Returns `(mock_cbl_path, branch_meta, total_branches)`.

#### 10 Phases (compile + fix after each):

| Phase | Name | Incremental? | Description |
|-------|------|-------------|-------------|
| 0 | Baseline | No | Compile original, record pre-existing errors |
| 1 | COPY resolution | No | Inline copybooks via `_resolve_copies()` |
| 2 | Mock infrastructure | No | Add MOCK-FILE to FILE-CONTROL, FD, WORKING-STORAGE |
| 3 | EXEC replacement | **Yes** (batch_size) | Replace EXEC CICS/SQL/DLI with mock reads |
| 4 | I/O replacement | **Yes** (batch_size) | Replace READ/WRITE/OPEN/CLOSE with mocks |
| 5 | CALL replacement | **Yes** (batch_size) | Replace CALL 'prog' with mock reads |
| 6 | Paragraph tracing | No | Insert SPECTER-TRACE:/SPECTER-CALL: DISPLAYs |
| 7 | Normalization | No | LINKAGE conversion, REDEFINES, common stubs, etc. |
| 8 | Compile-and-fix | No | LLM handles remaining undefined symbols |
| 9 | Branch probes | No | LLM inserts @@B: probes, one paragraph at a time |

**Batch loop** (Phases 3-5): Replace `batch_size` blocks → write → compile → fix → next batch. If batch causes >10 errors, revert and retry one-by-one.

**Sequential fix loop**: `_compile_and_fix` runs sequentially — compile, pick error, fix, compile, repeat — until errors reach 0 or stall. Minimum 50 rounds always, 100 for 1 error. Formula: `max(50, 100 // n_errors)`. When all errors have been attempted, `failed_error_lines` resets for a fresh round with accumulated failed-attempt memory. Duplicate fixes are fingerprinted and rejected instantly. After batch mode fails for an error type, falls back to single-error mode.

**Hard phase gates**: Every phase calls `_assert_clean()` after compile-and-fix. If ANY errors remain, the pipeline raises `RuntimeError` — it will never proceed to the next phase with unresolved errors. The error propagates to the caller (not swallowed). The sub-checkpoint ensures restart resumes from compile-and-fix (not re-doing the transform).

**Resume**: Checkpoint file (`phase_checkpoint.json`) tracks last completed phase. Each phase saves a sub-checkpoint after its transform but before compile-and-fix (e.g., `copy_resolution_transformed`). On restart, the transform is skipped and only compile-and-fix runs — preserving all LLM fixes from the interrupted run.

#### Key Data Structures

**`Resolution`** (L54): Records a verified error fix:
```python
@dataclass
class Resolution:
    phase: str          # e.g., "exec_replacement"
    batch: int          # Batch number within phase
    transformation: str # What was being done
    error: str          # The compilation error message
    fix: str            # Human-readable fix description
    fix_lines: dict     # line_number → fixed content
    verified: bool      # True if error gone on recompile
```

#### Smart Agent Error Fixing: `_compile_and_fix()` (L510)

Two modes, chosen automatically per attempt:

**Batch mode** (when 5+ errors share the same type, e.g., all "not defined"):
- ALL similar errors presented in one prompt (up to 30)
- LLM sees TWO context chunks: error area + WORKING-STORAGE tail
- LLM adds all stubs at once instead of one at a time
- Parse range is the entire file (stubs in WS, errors in PROCEDURE)

**Single-error mode** (mixed error types):
1. **Choose**: Present top 15 errors to LLM → LLM picks one + requests context (max 1000 lines)
2. **Fix**: Send error + context → LLM returns JSON `{"<line>": "<content>"}`

**Safeguards**:
- **Quality gate**: Rejects fixes that are >50% commenting out code with no stubs added
- **Failed-attempt memory**: LLM sees "WHAT WORKED" and "WHAT FAILED" sections with prior attempts from this cycle
- **Error clustering**: Adjacent errors (within 10 lines) are treated as one root cause — failing one marks the whole cluster
- **Relaxed verification**: Accept if total error count drops (not just the specific line)
- **Audit log** (`fix_audit.log`): Every accepted fix logged with BEFORE/AFTER per line, tagged [COMMENTED OUT], [ADDED], or [MODIFIED]

**Integrity check** (end of pipeline): Reports paragraph trace count, mock probe count, and comment ratio. Warns if >40% of lines are comments.

#### Helper Functions

- **`_cluster_errors(errors, gap=10)`**: Group adjacent errors as one root cause
- **`_group_errors_by_type(errors)`**: Group by error type for batch fixing
- **`_find_working_storage_range(src_lines)`**: Find WS boundaries for dual-context prompts
- **`_audit_fix(audit_path, ...)`**: Write human-readable fix diff to audit log

#### Resolution Persistence

- **`_load_resolutions(path)`** (L168): Load from `resolution_log.json`
- **`_save_resolutions(resolutions, path)`** (L195): Save after each batch
- **`_apply_preventive_fixes(src_lines, resolutions)`**: Apply verified fixes from prior runs (skip LLM)

#### Checkpoint/Resume

- **`_load_checkpoint(output_dir)`** (L210): Load `phase_checkpoint.json`
- **`_save_checkpoint(output_dir, phase, number, mock_path)`** (L233): Save after each phase with SHA-256 hash validation

### `specter/cobol_mock.py` — Mock Transformations (~4400 lines)

The underlying transformation functions called by `incremental_mock.py`.

**`MockConfig`** (L49): Configuration dataclass — copybook_dirs, trace_paragraphs, mock_file_name, stop_on_exec_return/xctl, eib_calen, eib_aid, initial_values.

#### Core Replacement Functions (all support `max_count` for incremental batching)

| Function | Line | Purpose |
|----------|------|---------|
| `_resolve_copies(lines, dirs)` | L236 | Inline COPY statements from copybook dirs |
| `_replace_exec_blocks(lines, config, max_count=0)` | L450 | Replace EXEC CICS/SQL/DLI → mock reads |
| `_replace_io_verbs(lines, max_count=0)` | L703 | Replace READ/WRITE/OPEN/CLOSE → mocks |
| `_replace_call_stmts(lines, max_count=0)` | L841 | Replace CALL 'prog' → mock reads |
| `_replace_accept_stmts(lines)` | L918 | Replace ACCEPT → CONTINUE |
| `_add_paragraph_tracing(lines)` | L971 | Insert SPECTER-TRACE:/SPECTER-CALL: |
| `_add_mock_infrastructure(lines, divs, config)` | L1447 | Add MOCK-FILE SELECT/FD/WS entries |
| `_disable_original_selects(lines, config)` | L1550 | Comment out original SELECTs |
| `_convert_linkage(lines)` | L1734 | Move LINKAGE items to WORKING-STORAGE |
| `_fix_procedure_division(lines)` | L1780 | Remove USING clause from PROCEDURE DIVISION |
| `_add_mock_file_handling(lines, config)` | L1831 | Insert OPEN/CLOSE MOCK-FILE |
| `_add_common_stubs(lines, config)` | L1934 | Add DFHAID/DFHBMSCA/EIB stubs if referenced |

**Mock data format** (80-byte LINE SEQUENTIAL):
```
Cols 1-30:   Op key (CICS-READ, SQL, CALL:PROG, INIT:VAR, etc.)
Cols 31-50:  Alpha status ('00' for success)
Cols 51-59:  Numeric status (right-justified)
Cols 60-80:  Filler
```

### `specter/branch_instrumenter.py` — Post-Compilation Branch Probes (~300 lines)

**Entry**: `instrument_branches(mock_cbl_path, llm_provider, llm_model)` (L31)

Returns `(probes_inserted, paragraphs_done, branch_meta)`.

Per paragraph with IF/EVALUATE:
1. Extract paragraph source
2. Send to LLM with rules (@@B:id:T/F for IF, @@B:id:Wn for EVALUATE, within col 72)
3. Replace paragraph in source
4. `cobc -fsyntax-only` to verify
5. Revert if compilation fails

### `specter/cobol_executor.py` — Compile & Run (~500 lines)

**`prepare_context(cobol_source, copybook_dirs, ...)`** (L210): Calls `incremental_instrument()`, returns `CobolExecutionContext`.

**`run_test_case(context, input_state, stub_log, ...)`** (L357): Write mock data → run COBOL binary → parse SPECTER-TRACE/@@B:/SPECTER-CALL output.

**`run_batch(context, test_cases, workers)`** (L464): Parallel execution via ProcessPoolExecutor.

### `specter/cobol_fix_cache.py` — LLM Investigation (~650 lines)

**`llm_investigate_cascade(llm_provider, llm_model, first_error_line, error_msg, all_errors, src_lines, ...)`** (L383): Multi-turn (up to 10) LLM investigation for cascade failures. LLM can request additional code chunks via `{"need_context": {"start": N, "end": M}}`.

**`_parse_llm_fix_response(response, min_line, max_line)`** (L600): Handles JSON, nested JSON, markdown code blocks, plain text formats.

### `specter/llm_coverage.py` — LLM Provider Abstraction (~550 lines)

**`_query_llm_sync(provider, prompt, model)`** (L331): Synchronous LLM query with 401 retry/reconnect. Supports single string or multi-turn `list[Message]`.

**`build_coverage_gaps(uncovered, constraints, gating)`** (L391): Build CoverageGap objects for LLM prompts.

**`generate_llm_suggestions(state, uncovered, ...)`** (L443): LLM suggests variable values to reach uncovered paths.

Uses `llm_providers` package with Protocol-based abstraction (`LLMProvider`, `Message`, `CompletionResponse`). Supports Anthropic, OpenAI, OpenRouter.

---

## Coverage Engine

### `specter/cobol_coverage.py` — Agentic Loop (~1600 lines)

**`run_cobol_coverage(ast_source, cobol_source, copybook_dirs, ...)`** (L989): Main COBOL coverage entry point. Compiles, prepares context, runs agentic loop.

**`_run_agentic_loop(strategies, context, ...)`** (L1242): Strategy selector picks strategy → generate test cases → execute → track coverage → repeat until budget/timeout/plateau.

**`run_coverage(ast_source, ...)`** (L1473): Python-only coverage (no COBOL binary).

### `specter/coverage_strategies.py` — Pluggable Strategies (~2030 lines)

| Strategy | Priority | Method |
|----------|----------|--------|
| `BaselineStrategy` (L124) | 20 | All-success baseline with 5 value generation strategies |
| `DirectParagraphStrategy` (L488) | 35 | **7-phase rotation**: param hill-climb → stub sweep → dataflow backprop → frontier → harvest → inverse → LLM |
| `FaultInjectionStrategy` (L1667) | 50 | Inject fault values into stub operations |
| `CorpusFuzzStrategy` (L1733) | 45 | AFL-inspired energy-based corpus scheduling with greedy set cover |

**`HeuristicSelector`** (L1985): Scoring = `priority - yield_bonus + staleness_penalty`. Adaptive batch sizing per strategy.

### `specter/static_analysis.py` — Call Graph & Gating (~545 lines)

- **`build_static_call_graph(program)`** (L86): PERFORM/GO_TO edge extraction
- **`extract_gating_conditions(program)`** (L332): IF/EVALUATE conditions gating paragraph entry
- **`compute_path_constraints(graph, target)`** (L514): Constraints along path from entry to target

### `specter/backward_slicer.py` — Code Slicing (~290 lines)

**`backward_slice(module_source, branch_id, max_lines)`** (L73): Extract minimal code leading to a branch for LLM steering. 5-phase: locate → control path → variable deps → stubs → assemble.

### `specter/program_analysis.py` — Per-Paragraph Analysis (~450 lines)

**`prepare_program_analysis(program, cobol_source, ...)`** (L103): Structured JSON per paragraph (comments, calls, stub ops, gating conditions, branch count). No LLM calls.

### `specter/coverage_bundle.py` — Portable Bundle (~1100 lines)

**`export_bundle(ast_source, cobol_source, ...)`** (L194): Export binary + `coverage-spec.yaml`. Optional LLM enrichment and obfuscation.

**`run_bundle(bundle_dir, ...)`** (L773): Run coverage from bundle (no source/AST/copybooks needed).

### `specter/coverage_config.py` — Strategy Config (~270 lines)

**`CoverageConfig`**: selector, strategies, rounds, termination thresholds.

**`load_config(path)`** (L102): YAML config (or JSON fallback).

### `specter/cobol_validate.py` — Two-Pass Validation (~200 lines)

**`validate_store(ast_source, cobol_source, store_path, ...)`** (L21): Python pass → COBOL pass → reconcile → `.validated.jsonl`.

---

## Monte Carlo & Test Synthesis

### `specter/monte_carlo.py` — Randomized Execution (~2400 lines)

**`run_monte_carlo(module_path, n_iterations, seed, ...)`** (L2252): Main entry. Dispatches to guided fuzzing or random walk.

**`_run_paragraph_directly(module, para_name, state)`** (L944): Direct paragraph invocation for unreachable code.

**Corpus management**: Energy-based seed selection, eviction at 500 entries, frontier bonus, recency bonus, yield penalty.

**Input generation**: Status vars 80% success-biased, flags 70% from literals, semantic heuristics for dates/amounts/IDs.

### `specter/test_synthesis.py` — 5-Layer Synthesis (~4000 lines)

**`synthesize_test_set(module, program, ...)`** (L3904): Systematic test generation.

| Layer | Goal | Method |
|-------|------|--------|
| 1 | All-success baseline | Success for all status vars |
| 2 | Gating conditions | Solve path constraints to reach uncovered paragraphs |
| 2.5 | Frontier expansion | Random walk from layer 2 solutions |
| 3 | Stub exhaustion | Exhaust stub queues to explore error paths |
| 3.5 | Branch coverage | Targeted mutation for uncovered branches |
| 4 | Loop analysis | PERFORM UNTIL analysis |
| 5 | Corpus walking | Guided fuzzing corpus exploration |

### `specter/test_store.py` — JSONL Persistence (227 lines)

**`TestCase`** (L21): id (SHA-256), input_state, stub_outcomes, stub_defaults, paragraphs_covered, branches_covered, layer, target.

**`TestStore.load(path)`** (L119): Load + deduplicate + restore progress.

**`TestStore.append(path, tc)`** (L157): Atomic append (crash-safe).

---

## CLI Usage

### Basic Code Generation
```bash
python3 -m specter program.ast [-o output.py] [--verify] [--analyze]
```

### Python-Only Coverage
```bash
python3 -m specter program.ast --guided --test-store tests.jsonl \
    [--llm-guided --llm-provider openrouter]
```

### Test Synthesis
```bash
python3 -m specter program.ast --synthesize --test-store tests.jsonl \
    --synthesis-layers 5
```

### GnuCOBOL Hybrid Coverage
```bash
python3 -m specter program.ast --cobol-coverage \
    --cobol-source program.cbl --copybook-dir ./cpy \
    --coverage-budget 5000 --coverage-timeout 1800 \
    [--coverage-config config.yaml] [--llm-guided --llm-provider openrouter]
```

### COBOL Mock Instrumentation Only
```bash
python3 -m specter program.cbl --mock-cobol -o program.mock.cbl \
    --copybook-dir ./cpy [--init-var VAR-NAME=VALUE]
```

### Portable Bundle Export
```bash
python3 -m specter program.ast --export-bundle ./bundle \
    --cobol-source program.cbl --copybook-dir ./cpy [--obfuscate]
```

### Run from Bundle
```bash
python3 -m specter --run-bundle ./bundle --test-store tests.jsonl \
    --coverage-budget 5000
```

### Two-Pass Validation
```bash
python3 -m specter program.ast --cobol-validate-store tests.jsonl \
    --cobol-source program.cbl --copybook-dir ./cpy
```

### Java Generation
```bash
python3 -m specter program.ast --java -o project/ \
    --java-package com.example [--docker] [--integration-tests]
```

---

## Testing

### Test Files

| File | Tests | Coverage |
|------|-------|----------|
| `test_incremental_mock.py` | 24 | Incremental pipeline, resolutions, max_count batching |
| `test_cobol_coverage.py` | 61 | Integration: AST → Python → COBOL execution |
| `test_condition_parser.py` | 27 | COBOL condition → Python translation |
| `test_copybook_parser.py` | 38 | Copybook parsing, PIC types, 88-level values |
| `test_code_generator.py` | 15 | Python code generation for all statement types |
| `test_variable_extractor.py` | 15 | Variable classification, literal harvesting |
| `test_llm_coverage.py` | 22 | LLM provider abstraction, coverage gaps |
| `test_fuzzer.py` | 28 | Coverage-guided fuzzing, energy, corpus |
| `test_test_synthesis.py` | 17 | 5-layer synthesis, gating constraints |
| `test_static_analysis.py` | 18 | Call graph, gating conditions, equality constraints |
| `test_backward_slicer.py` | 12 | Program slicing for variable deps |
| `test_concolic.py` | 28 | Z3 concolic solver |
| `test_88_siblings.py` | 15 | COBOL 88-level sibling detection |
| `test_llm_fuzzer.py` | 32 | LLM-guided fuzzing |
| `test_coverage_config.py` | 13 | Configuration management |
| `test_java_condition_parser.py` | 56 | Java condition code generation |
| `test_end_to_end.py` | 8 | Full pipeline (skipped if AST files missing) |

**Total: ~436 tests**

### Running Tests
```bash
python3 -m pytest                                    # Full suite (~3 min)
python3 -m pytest tests/test_incremental_mock.py     # Single file
python3 -m pytest tests/test_condition_parser.py::TestConditionParser::test_simple_equality  # Single test
python3 -m pytest -x -q                              # Stop on first failure, quiet
```

---

## Key Design Decisions

1. **Incremental over monolithic**: Each phase independently verifiable, compile-after-each-step
2. **Batch loop with fallback**: Batch transformations, revert + one-by-one if >10 errors
3. **Resolution log for learning**: Prior fixes applied proactively (skip LLM for known issues)
4. **Two-step agent model**: LLM chooses error (broad context) then fixes (narrow context)
5. **Post-compilation branch probes**: Avoid LLM errors by inserting @@B: after successful compile
6. **Cached executables**: Reuse compiled binary if source unchanged
7. **Coverage mode**: RETURN/XCTL read mock data + continue instead of terminating
8. **State dict convention**: All COBOL vars uppercase, internals prefixed `_`
9. **Stub outcome queues**: list of (var, value) pairs per operation, pop on each call
10. **JSONL persistence**: Append-only, crash-safe, resumable with progress records
