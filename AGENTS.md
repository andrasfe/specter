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
│  jit_value_inference.py │   │  cobol_fix_cache.py           │
└─────────┬───────────────┘   │  llm_coverage.py (LLM calls)  │
       │                   │  llm_test_states.py           │
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

**`_harvest_condition_literals(report, condition)`**: Parses `IF <var> op <literal>` style conditions (supports multi-value OR/AND lists, figurative constants, ordering comparisons with boundary expansion) and appends the literals to `condition_literals[var]`.

**`_harvest_evaluate_when_literals(report, subject, evaluate_stmt)`**: Complements the IF-style harvester. Walks `WHEN` children of a single-subject EVALUATE and appends each bare WHEN literal (quoted string, numeric, figurative constant) to `condition_literals[subject]`. This is what lets `EVALUATE WS-FL-DD WHEN 'TRNXFILE' WHEN 'XREFFILE' …` seed `WS-FL-DD` with the exact entry-gate values so random fuzzing can actually reach the gated paragraphs. Multi-subject `ALSO` forms and `WHEN OTHER` are intentionally skipped.

### `specter/variable_domain.py` — Domain Model (~450 lines)

**`VariableDomain`** (L22): Merges PIC clauses (from copybooks), AST analysis, stub mappings, and naming heuristics.

**`build_variable_domains()`** (L117): Builds domain for every variable. Accepts an optional `cobol_source` argument which, when provided, scans the COBOL source file directly for 88-level `VALUE` clauses on variables defined inline in the program (outside copybooks) and populates `VariableDomain.valid_88_values` with the activating values. This is what lets `BaselineStrategy` inject `APPL-RESULT = 16` to activate `88 APPL-EOF VALUE 16` on programs where the 88-level items live in the program source itself rather than a copybook.

**`_extract_88_values_from_source(cobol_source)`**: Helper that walks the COBOL source line by line, tracks the current non-88-level parent identifier, and records every `88 <name> VALUE <literal>` child under that parent. Returns `dict[parent_name, dict[child_88_name, child_value]]`. Handles numeric / quoted string / figurative constant literals, collapses `THRU`/`THROUGH` ranges to the low end, and uses the first entry of multi-value lists.

**`format_value_for_cobol(domain, value)`** (L614): Formats a value for INIT records. When `domain.data_type == "unknown"` (common for variables defined inline in the program rather than in a copybook), the formatter now infers numeric vs alpha from the value's Python type so an 88-level literal like `APPL-AOK VALUE 0` is written as the numeric string `"0"` instead of the space-padded alpha string `"0         "` that would fail a `MOVE` into a `PIC S9(9) COMP` field at runtime.

**`generate_value(domain, strategy)`** (L219): 6 strategies — condition_literal, 88_value, boundary, semantic, random_valid, adversarial. In current coverage flows, `semantic` is usually attempted first through `jit_value_inference.py`; `generate_value()` remains the deterministic fallback.

### `specter/copybook_parser.py` — Copybook Parsing (~550 lines)

**`parse_copybook(text)`** (L110): Parses COBOL copybook → `CopybookRecord` with `CopybookField` entries (level, name, PIC type/length/precision, OCCURS, 88-level values).

Also generates SQL DDL and Java DAO classes.

---

## GnuCOBOL Mock Pipeline (Incremental Instrumentation)

### `specter/incremental_mock.py` — Main Pipeline (~2600 lines)

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
| 9 | Branch probes | No | Deterministic branch tracer inserts @@B: probes; insertion-only LLM fallback is used only if deterministic tracing fails syntax check |

**Batch loop** (Phases 3-5): Replace `batch_size` blocks → write → compile → fix → next batch. If batch causes >10 errors, revert and retry one-by-one.

**Sequential fix loop**: `_compile_and_fix` runs sequentially — compile, pick error, fix, compile, repeat — until errors reach 0 or stalls for 50 no-progress rounds. When all errors have been attempted, `failed_error_lines` resets for a fresh round with accumulated failed-attempt memory. Duplicate fixes are fingerprinted and rejected instantly. After batch mode fails for an error type, falls back to single-error mode. `copy_resolution` is biased toward context-driven single-error investigation, while later phases still prefer batching when many similar instrumentation-induced errors appear.

**Hard phase gates**: Every phase calls `_assert_clean()` after compile-and-fix. If ANY errors remain, the pipeline raises `RuntimeError` — it will never proceed to the next phase with unresolved errors. The error propagates to the caller (not swallowed). The sub-checkpoint ensures restart resumes from compile-and-fix (not re-doing the transform).

**Resume**: Checkpoint file (`phase_checkpoint.json`) tracks last completed phase. Each phase saves a sub-checkpoint after its transform but before compile-and-fix (e.g., `copy_resolution_transformed`). On restart, the transform is skipped and only compile-and-fix runs — preserving all LLM fixes from the interrupted run. On hash mismatch (from interrupted compile-and-fix), warns and resumes instead of starting from scratch.

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

#### Smart Agent Error Fixing: `_compile_and_fix()` (L980)

**Deterministic pre-fixes** (run before or alongside the LLM loop — zero LLM cost where possible):
1. **Long lines**: Wrap lines extending past column 72, including operator-only overflow fragments caused by fixed-format truncation.
2. **Commented-statement continuations**: `_fix_commented_statement_continuations()` comments orphaned operand/continuation lines that remain active after the first line of a multi-line statement was already commented out.
3. **Group item PIC**: Remove PIC from group items (IBM allows, GnuCOBOL rejects).
4. **FILE STATUS definitions**: `_ensure_file_status_definitions()` adds missing WORKING-STORAGE declarations referenced by FILE-CONTROL `FILE STATUS` clauses.
5. **Missing periods / structure cleanup**: `_fix_missing_periods()` repairs common `expecting SECTION or .` cases before escalating to the LLM.
6. **Missing paragraph stubs** (`_generate_missing_paragraph_stubs`): For undefined PERFORM / GO TO targets, add deterministic no-op paragraph stubs near the end of PROCEDURE DIVISION.
7. **Record stubs** (`_generate_record_stubs`): Analyze OF qualifiers to build parent-child record structures, infer PIC from usage patterns, and skip likely procedure names so paragraph targets are not mis-stubbed into WORKING-STORAGE.
8. **File stubs** (`_generate_file_stubs`): For "not a file name" errors, generate SELECT + FD stubs in FILE-CONTROL and FILE SECTION.

**Two LLM modes**, chosen automatically per attempt:

**Batch mode** (when 5+ errors share the same type, e.g., all "not defined"):
- ALL similar errors presented in one prompt (up to 30)
- LLM sees TWO context chunks: error area + WORKING-STORAGE tail (for "not defined") or FILE-CONTROL + FILE SECTION (for "not a file name")
- LLM adds all stubs at once instead of one at a time
- Parse range is the entire file (stubs in WS, errors in PROCEDURE)

**Single-error mode** (mixed error types):
1. **Choose**: Present top 15 errors to LLM → LLM picks one + requests context (max 1000 lines)
2. **Fix**: Send error + context → LLM returns JSON `{"<line>": "<content>"}`

**Copy-resolution investigation mode**: For structural early-phase errors (`syntax error`, continuation failures, group-item PIC issues, redefinitions, malformed headers), `_compile_and_fix()` can call `llm_investigate_cascade()` first. The LLM may request additional context in multiple turns before proposing any edits, which reduces guess-fixes against broken COPY-expanded structure.

**Error grouping** (`_group_errors_by_type`): Groups errors by normalized type for batch mode. Known types: `is not defined`, `not a file name`, `not a procedure name`, `not a field`, `redefinition`, `ambiguous`, `KEY clause invalid`, `not allowed on SEQUENTIAL`, `syntax error`, `PICTURE clause`, `duplicate`.

**Safeguards**:
- **Rule-based quality gate**: Cheap pre-filter that rejects fixes which are >50% commenting out code with no stubs added.
- **Scribe / challenger LLM review** (`specter/llm_review.py`): After the rule-based gate accepts a proposal, a second LLM call (the *challenger*) is asked to verify the fix is non-destructive against an explicit rubric (commenting out referenced lines, renaming undefined symbols, narrowing PIC clauses, mid-paragraph GOBACK/EXIT, replaced business statements, ...). The challenger returns `{"verdict": "accept" | "reject", "reason": "...", "severity": "high" | "low"}`. On `reject` the scribe is re-prompted with the reviewer's reason appended and tries again, up to `_LLM_REVIEW_MAX_REVISIONS = 3` revisions per error attempt before the proposal is recorded as failed. On `unknown` (reviewer outage / parse failure / kill switch active) the proposal passes through unblocked. Worst-case cost is 4 scribe calls + 4 reviewer calls per error attempt; most attempts pass on the first review. Bypassed via `--no-llm-review` CLI flag or `SPECTER_LLM_REVIEW=0` env var.
- **Failed-attempt memory**: LLM sees "WHAT WORKED" and "WHAT FAILED" sections with prior attempts from this cycle (now also includes reviewer-blocked attempts).
- **Error clustering**: Adjacent errors (within 10 lines) are treated as one root cause — failing one marks the whole cluster.
- **Relaxed verification**: Accept if total error count drops (not just the specific line).
- **Audit log** (`fix_audit.log`): Every accepted fix logged with BEFORE/AFTER per line, tagged [COMMENTED OUT], [ADDED], or [MODIFIED].

**COBOL knowledge base** (`_COBOL_FIX_KNOWLEDGE`): ~90-line reference appended to every LLM prompt. Covers fixed-format rules (cols 1-72, Area A/B), section and paragraph headers, 88-level rules, qualified `FIELD OF RECORD` references, common I/O and SELECT syntax, error patterns with specific remediation, PIC clause inference rules, and hard constraints (never comment out referenced lines).

**Phase-aware prompting**: `_phase_fix_guidance()` injects different instructions by phase. `copy_resolution` emphasizes structural root-cause analysis and requesting wider context before editing; later phases explicitly assume many failures were introduced by Specter instrumentation and bias the LLM toward repairing injected mock I/O, generated stubs, and related scaffolding before touching original business logic.

**Post-progress restubbing**: After any successful error-count drop, `_compile_and_fix()` reruns deterministic paragraph stubs and undefined-symbol stubs because newly surfaced targets often appear only after the first root cause is fixed.

**In-loop paragraph restubbing**: `_compile_and_fix()` also performs a deterministic paragraph-stub pass on each loop iteration (before LLM fixing) and keeps the insertion only when error count improves. This catches late-batch `'<PARA-EXIT>' is not defined` cases (including double-hyphen legacy labels) even when no prior LLM fix reduced total errors.

**Integrity check** (end of pipeline): Reports paragraph trace count, mock probe count, and comment ratio. Warns if >40% of lines are comments.

#### Helper Functions

- **`_generate_record_stubs(errors, src_lines)`**: Deterministic pre-fix for "not defined" errors
- **`_generate_missing_paragraph_stubs(errors, src_lines)`**: Deterministic no-op stubs for missing paragraph targets
- **`_generate_file_stubs(errors, src_lines)`**: Deterministic pre-fix for "not a file name" errors
- **`_ensure_file_status_definitions(src_lines)`**: Add missing FILE STATUS variables referenced by SELECT clauses
- **`_fix_redefinitions(errors, src_lines)`**: Intentional no-op placeholder; duplicate definitions are no longer auto-commented out
- **`_fix_commented_statement_continuations(src_lines)`**: Comment orphaned continuation lines after already-commented statements
- **`_fix_group_item_pic(errors, src_lines)`**: Deterministic pre-fix for group item PIC errors
- **`_fix_long_lines(src_lines)`**: Wrap lines past col 72
- **`_find_procedure_insertion_point(src_lines)`**: Find a safe insertion point for paragraph stubs near end of PROCEDURE DIVISION
- **`_find_file_control_end(src_lines)`**: Find insertion point for SELECT stubs
- **`_find_file_section_end(src_lines)`**: Find insertion point for FD stubs
- **`_group_errors_by_type(errors)`**: Group by error type for batch fixing
- **`_find_working_storage_range(src_lines)`**: Find WS boundaries for dual-context prompts
- **`_phase_fix_guidance(phase)`**: Phase-specific debugging instructions for LLM prompts
- **`_audit_fix(audit_path, ...)`**: Write human-readable fix diff to audit log

#### Resolution Persistence

- **`_load_resolutions(path)`** (L168): Load from `resolution_log.json`
- **`_save_resolutions(resolutions, path)`** (L195): Save after each batch
- **`_apply_preventive_fixes(src_lines, resolutions)`**: Apply verified fixes from prior runs (skip LLM)

#### Checkpoint/Resume

- **`_load_checkpoint(output_dir)`** (L210): Load `phase_checkpoint.json`
- **`_save_checkpoint(output_dir, phase, number, mock_path)`** (L233): Save after each phase with SHA-256 hash validation
- **Run manifest mirror**: checkpoint progress is also mirrored into `.specter_run_manifest.json` via `run_manifest.record_phase_checkpoint(...)` for easier resume auditing.

### `specter/cobol_mock.py` — Mock Transformations (~4600 lines)

The underlying transformation functions called by `incremental_mock.py`.

**`_strip_cobc_metadata(name)`**: Strips GnuCOBOL compiler metadata (`(MAIN SECTION:TRUE)`, `IN RECORD`) from symbol names in error messages. Applied to all error extraction points.

**Non-destructive fallback policy**: `cobol_mock.py` no longer uses broad paragraph neutralization, exact-line comment-out salvage, or hard-comment procedure fallback as a generic recovery path. Fallback recovery now prefers targeted normalization, paragraph-header canonicalization, injected stub repair, and diagnostics, preserving original business logic unless an actual I/O block is being replaced by design.

**`MockConfig`** (L62): Configuration dataclass — copybook_dirs, trace_paragraphs, mock_file_name, stop_on_exec_return/xctl, eib_calen, eib_aid, initial_values, payload_variables.

#### Core Replacement Functions (all support `max_count` for incremental batching)

| Function | Line | Purpose |
|----------|------|---------|
| `_resolve_copies(lines, dirs)` | L236 | Inline COPY statements + EXEC SQL INCLUDE (DCLGEN) from copybook dirs |
| `_replace_exec_blocks(lines, config, max_count=0)` | L450 | Replace EXEC CICS/SQL/DLI → mock reads |
| `_replace_io_verbs(lines, max_count=0)` | L703 | Replace READ/WRITE/OPEN/CLOSE → mocks |
| `_replace_call_stmts(lines, max_count=0)` | L841 | Replace CALL 'prog' → mock reads |
| `_replace_accept_stmts(lines)` | L918 | Replace ACCEPT → CONTINUE |
| `_add_paragraph_tracing(lines)` | L971 | Insert SPECTER-TRACE:/SPECTER-CALL: |
| `_add_mock_infrastructure(lines, divs, config)` | L1569 | Add MOCK-FILE SELECT/FD/WS entries (skips SQLCODE/DIBSTAT if already defined) |
| `_disable_original_selects(lines, config)` | L1685 | Replace original SELECTs with dummy assigns (preserves INDEXED org + RECORD KEY) |
| `_convert_linkage(lines)` | L1734 | Move LINKAGE items to WORKING-STORAGE |
| `_fix_procedure_division(lines)` | L1780 | Remove `USING` from PROCEDURE DIVISION and comment orphaned continuation lines left behind by split headers |
| `_add_mock_file_handling(lines, config)` | L1831 | Insert OPEN/CLOSE MOCK-FILE |
| `_strip_skip_directives(lines)` | L1900s | Remove printer-control / SKIP directives not accepted by GnuCOBOL |
| `_add_common_stubs(lines, config)` | L1934 | Add DFHAID/DFHBMSCA/EIB stubs if referenced |

#### Recent transformation hardening

- **Copybook normalization** (`_normalize_copy_line`): Better distinguishes prose/banner lines from real arithmetic or declarations. This preserves expression lines from copybooks while still turning decorative text blocks into fixed-format COBOL comments.
- **Procedure-division cleanup**: `_fix_procedure_division()` now also handles plain `PROCEDURE DIVISION.` headers followed by split continuation lines, commenting the continuation debris instead of leaving invalid identifiers active.
- **Legacy label normalization**: normalization also repairs paragraph labels ending in ellipsis (`...`) into valid COBOL paragraph headers before later phases compile.

**Mock data format** (80-byte LINE SEQUENTIAL):
```
Cols 1-30:   Op key (CICS-READ, SQL, CALL:PROG, INIT:VAR, etc.)
Cols 31-50:  Alpha status ('00' for success)
Cols 51-59:  Numeric status (right-justified)
Cols 60-80:  Filler
```

Payload continuation records:
- Primary operation records may be followed by `SET:<var>` records.
- Instrumented COBOL applies these through `SPECTER-NEXT-MOCK-RECORD` + `SPECTER-APPLY-MOCK-PAYLOAD` paragraphs.
- This enables transcript-style variable payload replay for READ/CALL/EXEC/I-O replacements.

### `specter/branch_instrumenter.py` — Post-Compilation Branch Probes (~300 lines)

**Entry**: `instrument_branches(mock_cbl_path, llm_provider, llm_model)` (L31)

Returns `(probes_inserted, paragraphs_done, branch_meta)`.

Current behavior:
1. Strip any existing active `@@B:` / `@@V:` lines so repeated instrumentation is idempotent.
2. Run deterministic full-file branch tracing using `cobol_mock._add_branch_tracing()`.
3. `cobc -fsyntax-only` verifies the fully instrumented source.
4. If deterministic tracing compiles, write it directly and return the resulting `branch_meta`.
5. Only if deterministic tracing fails syntax check, fall back to paragraph-by-paragraph insertion-only LLM instrumentation with compiler-feedback retries.

Safety rules now enforced by the deterministic tracer:
- Inline `ELSE IF ...` and `ELSE <verb> ...` forms are skipped rather than split by inserted probes.
- Period-delimited IFs are skipped rather than rewritten into structured IFs.
- Probe counts reflect directions actually inserted, not assumed T/F pairs.

After Phase 9 writes probes, `incremental_mock.py` recompiles the executable so the runtime binary matches the final instrumented source.

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

### `specter/llm_test_states.py` — COBOL Comment & Seed Extraction (~650 lines)

**`extract_paragraph_comments(program, source_lines)`** (L60): Extracts nearby COBOL comments keyed by paragraph name.

Used by `cobol_coverage.py`, `program_analysis.py`, and JIT value inference so prompts can include local business-language hints instead of relying only on field names and literals.

### `specter/jit_value_inference.py` — Lazy Semantic Value Inference (~360 lines)

Shared on-demand LLM inference service used by both COBOL coverage and Monte Carlo fuzzing. It replaces eager startup-wide semantic inference on active paths with just-in-time profile generation plus cache reuse.

**`JITValueInferenceService`**: Main service class.

Key methods:
- **`infer_profile(var_name, domain, *, target_paragraph, op_key, comment_hints, allowed_variables, target_key)`**: Two-layer gating before any LLM call: (1) if `require_target_paragraph_context` is True and `target_paragraph` is absent, increments `skipped_untargeted` and returns `None`; (2) if `allowed_variables` is non-empty and `var_name` is not in it, increments `skipped_out_of_scope` and returns `None`. On pass, builds a prompt, queries the LLM, parses a `SemanticProfile`, and caches by variable/domain/paragraph/comment context.
- **`generate_value(var_name, domain, strategy, rng, *, allowed_variables, target_key, ...)`**: Returns a semantic candidate only for `strategy == "semantic"`; passes through the scope parameters to `infer_profile`; returns `None` so callers can fall back to deterministic generation otherwise.
- **`snapshot_metrics()`**: Returns `requests`, `cache_hits`, `cache_misses`, `skipped_untargeted`, `skipped_out_of_scope`, `cache_hit_pct`, `llm_successes`, `llm_failures`, `avg_latency_ms`.
- **`_emit_periodic_summary()`**: Logs `skip_u` and `skip_scope` counters alongside hit/miss rates. Fires every `summary_every_requests` events or `summary_interval_sec` seconds.

Gating flags:
- **`require_target_paragraph_context`** (default `True`): Skip any call without an explicit target paragraph. Controlled by `JITLoggingConfig.require_target_paragraph_context`.
- **`allowed_variables`** (per-call set): Caller passes a pre-computed per-target allowlist; variables outside it are skipped as out-of-scope.

Prompt inputs:
- variable name and classification
- PIC/domain facts (`data_type`, length, precision, signedness, ranges)
- harvested condition literals and 88-level values
- target paragraph / stub operation context
- nearby paragraph comments from `llm_test_states.extract_paragraph_comments()`

Cache model:
- In-memory cache keyed by `_cache_key(...)` (SHA-256 of all inputs)
- Optional persistent JSON cache on disk
- `cache_hits` / `cache_misses` / `skipped_untargeted` / `skipped_out_of_scope` counters

This module reuses `SemanticProfile`, `_parse_semantic_profiles`, and `generate_value_from_profile` from `llm_fuzzer.py` rather than introducing a second semantic-profile format.

### `specter/llm_fuzzer.py` — LLM-Guided Input Mutation (~600 lines)

Contains the semantic-profile schema and adaptive mutation helpers used by Monte Carlo guidance.

Core pieces:
- **`SemanticProfile`**: Structured semantic description (`description`, `valid_values`, `value_range`, `format_pattern`, `related_variables`).
- **`_parse_semantic_profiles(response_text)`**: Parses JSON-ish LLM responses into `SemanticProfile` objects.
- **`generate_value_from_profile(profile, rng)`**: Lightweight sampling helper used by both guided fuzzing and JIT inference fallback.
- **`apply_strategy_to_state(...)`**: Now accepts `jit_inference` and `domains`; semantic mutations try the shared JIT service first, then fall back to cached `semantic_profiles`.

Legacy note: `infer_variable_semantics()` still exists as the older eager bootstrap path, but the active COBOL coverage and guided Monte Carlo flows now use `jit_value_inference.py` instead.

---

## Coverage Engine

### `specter/cobol_coverage.py` — Agentic Loop (~2200 lines)

**`run_cobol_coverage(ast_source, cobol_source, copybook_dirs, ...)`** (L989): Main COBOL coverage entry point. Compiles, prepares context, extracts paragraph comments, builds a shared `JITValueInferenceService`, builds per-target variable allowlists, and runs the agentic loop.

Important helpers:
- **Injectable variables filter**: Variables that feed the runtime `SPECTER-READ-INIT-VARS` dispatch. A variable is injectable when it carries actionable signal (`condition_literals` OR `valid_88_values`), is not a stub-return variable, and is not a CICS EIB register. Classification is **not** a gating constraint — internal variables with 88-level children (e.g. `APPL-RESULT` on CBACT02C/03C/CBCUS01C) are included so `BaselineStrategy` Phase 3 can actually land their injected values at runtime instead of having the INIT record silently dropped.
- **`_build_input_state(...)`**: Generates baseline input state from variable domains. Semantic generation now consults the shared JIT service first, then falls back to `generate_value()`.
- **`extract_paragraph_comments(...)` integration**: COBOL source comments are harvested once and threaded into `StrategyContext` so paragraph-targeted semantic prompts can use nearby business hints.
- **`_build_target_variable_allowlists(module, branch_meta, gating_conds, stub_mapping, *, include_gates, include_slice)`** (L520): Builds a `dict[str, set[str]]` keyed by `"para:<para_name>"`. For each paragraph in `branch_meta`, combines: gating variables from `extract_gating_variables_for_target`, stub-return variables from `stub_mapping`, and backward-slice variables from `slice_variable_names` (both ± branch IDs). Result is attached to `StrategyContext.target_variable_allowlists` and drives per-call JIT scope filtering. Controlled by `jit_scope_policy` (see `JITLoggingConfig`).
- **`_jit_status_suffix()`**: Emits the JIT metrics banner appended to coverage log lines. Format: `[JIT reqs={n} hit={pct:.1f}% skip_u={n} skip_scope={n} ok={n} fail={n} avg={ms:.0f}ms]`.

**`_run_agentic_loop(strategies, context, ...)`** (L1242): Strategy selector picks strategy → generate test cases → execute → track coverage → repeat until budget/timeout/plateau.

**`run_coverage(ast_source, ...)`** (L1473): Python-only coverage (no COBOL binary).

Phase-1 memory-guided persistence now runs as an additive layer in both COBOL and Python-only coverage entry points:
- Load memory state from a run-local directory derived from test-store stem (e.g., `tests.jsonl` → `tests_memory/`).
- Track successful coverage-producing states and per-target attempt metadata during `_execute_and_save(...)`.
- Checkpoint memory state at end-of-round and finalization so interrupted runs can resume with retained context.

### `specter/coverage_strategies.py` — Pluggable Strategies (~2170 lines)

| Strategy | Priority | Method |
|----------|----------|--------|
| `BaselineStrategy` (L124) | 20 | Three phases: (1) one case per value-generation strategy (condition_literal, semantic, random_valid, 88_value, boundary); (2) per-variable `condition_literal` fan-out for variables classified as `input`; (3) per-88-level-value fan-out for **every** variable that carries 88-level children in its domain, regardless of classification — this covers internal variables like `APPL-RESULT` whose 88-level children (`APPL-AOK` / `APPL-EOF`) gate downstream branches. |
| `DirectParagraphStrategy` (L488) | 35 | **7-phase rotation**: param hill-climb → stub sweep → dataflow backprop → frontier → harvest → inverse → LLM |
| `TranscriptSearchStrategy` (L1897) | 40 | Mutates ordered READ transcripts with domain-aware payload assignments |
| `CorpusFuzzStrategy` (L1733) | 45 | AFL-inspired energy-based corpus scheduling with greedy set cover |
| `FaultInjectionStrategy` (L1885) | 50 | Stub fault injection across the full GnuCOBOL file-status, SQL, CICS, DLI, MQ and generic CALL return-code tables. Re-entrant per priority-branch target (not one-shot) and filters op keys by the current target's backward-slice allowlist when a `preferred_target_key` is set. Activates every 88-level sibling flag on stub-return variables. |

**`HeuristicSelector`** (L1985): Scoring = `priority - yield_bonus + staleness_penalty`. Adaptive batch sizing per strategy.

**`StrategyContext`** now carries:
- `domains`: variable domain map
- `jit_inference`: shared `JITValueInferenceService`
- `paragraph_comments`: extracted COBOL comments by paragraph
- `payload_candidates`: per-op payload candidate map used by transcript search
- `target_variable_allowlists: dict[str, set[str]]`: per-target JIT variable scope (keyed `"para:<name>"`; built by `_build_target_variable_allowlists`)
- `current_target_key: str | None`: set by each strategy to the active per-target key before generating domain values
- `preferred_target_key: str | None`: round-level branch preference (e.g., `branch:17:F`) to focus direct rounds
- `memory_store`, `memory_state`: optional memory persistence handles

Semantic value generation inside baseline, direct-paragraph, and transcript-driven strategies is funneled through `_generate_domain_value(...)`, which resolves the active allowlist from `current_target_key`, passes `allowed_variables` and `target_key` to the JIT service, and falls back to deterministic domain generation when JIT returns `None`.

### `specter/static_analysis.py` — Call Graph & Gating (~560 lines)

- **`build_static_call_graph(program)`** (L86): PERFORM/GO_TO edge extraction
- **`extract_gating_conditions(program)`** (L332): IF/EVALUATE conditions gating paragraph entry
- **`compute_path_constraints(graph, target)`** (L514): Constraints along path from entry to target
- **`extract_gating_variables_for_target(gating_conditions, target)`** (L532): Returns the set of normalized variable names that gate entry to `target` (sourced from `extract_gating_conditions` output). Used by `_build_target_variable_allowlists` to seed per-target JIT scope.

### `specter/backward_slicer.py` — Code Slicing (~390 lines)

**`backward_slice(module_source, branch_id, max_lines)`** (L73): Extract minimal code leading to a branch for LLM steering. 5-phase: locate → control path → variable deps → stubs → assemble.

**`slice_variable_names(module_source, target_bid)`** (L354): Lightweight variant that returns only the set of state variable names (uppercase) referenced by the backward slice for a given branch ID. Both the positive (`+bid`) and negative (`-bid`) directions are called by `_build_target_variable_allowlists` to gather T- and F-arm dependencies.

### `specter/program_analysis.py` — Per-Paragraph Analysis (~450 lines)

**`prepare_program_analysis(program, cobol_source, ...)`** (L103): Structured JSON per paragraph (comments, calls, stub ops, gating conditions, branch count). No LLM calls.

### `specter/uncovered_report.py` — Post-run diagnostic report (~700 lines)

Produces per-branch diagnostics for everything the coverage loop failed to hit, written next to the test store as `<stem>.uncovered.json` (tooling) and `<stem>.uncovered.md` (human review). Runs automatically at the end of `_run_agentic_loop`; can be disabled with `--uncovered-report off` or the `SPECTER_UNCOVERED_REPORT` env var.

**`generate_uncovered_report(ctx, cov, report, program_id, mock_source_path, out_path_stem, format)`** — public entry. Defensive: on any internal failure it logs a warning and returns an empty report so the main coverage loop is never blocked.

Per uncovered branch direction, the report captures:
- **Identity**: branch id, direction (T/F), paragraph, source file + line
- **Condition**: raw text (extracted from the instrumented `.mock.cbl` via `_extract_branch_conditions`) and a category label (`file_status_eq`, `status_flag_88`, `compound_and_or`, `numeric_cmp`, `not_numeric`, `string_eq`, `evaluate_when`, `evaluate_head`, `loop_until`, `other`, `unknown`)
- **Variable dependencies**: variables referenced in the condition, their classification (`input`/`internal`/`status`/`flag`), harvested `condition_literals`, `valid_88_values`, and whether each is a stub-return variable (with the op key)
- **88-level parent lookup**: when the condition variable is itself an 88-level child (e.g. `IF APPL-EOF`), a reverse-map entry `{'APPL-EOF': ('APPL-RESULT', 16)}` so the hint generator can point at the parent variable and activating value directly
- **Reachability**: gating conditions on the enclosing paragraph (from `extract_gating_conditions`)
- **Attempts**: reconstructed from the saved test-case list by matching (a) direct bid references in the `target` string (strong signal) and (b) paragraph hits (weaker). Counts are grouped by strategy
- **Nearest hit**: the test case that came closest to the target branch — picked by "reaches the target paragraph AND covers the most nearby bids". Includes its `input_state`, `stub_outcomes`, and the originating strategy
- **Hints**: heuristic next-step suggestions generated from the condition category (e.g. *"Needs file-status '22' on CARDFILE-STATUS. Verify FaultInjectionStrategy emits a `fault:READ:CARDFILE-FILE=22` case"*, or *"APPL-EOF is an 88-level flag child of APPL-RESULT. Set APPL-RESULT=16 in input_state to activate it"*)

The Markdown companion groups entries by paragraph and leads with a category summary + top-paragraphs table so a reviewer can spot patterns at a glance.

### `specter/coverage_bundle.py` — Portable Bundle (~1100 lines)

**`export_bundle(ast_source, cobol_source, ...)`** (L194): Export binary + `coverage-spec.yaml`. Optional LLM enrichment and obfuscation.

**`run_bundle(bundle_dir, ...)`** (L773): Run coverage from bundle (no source/AST/copybooks needed).

### `specter/coverage_config.py` — Strategy Config (~290 lines)

**`CoverageConfig`**: selector, strategies, rounds, termination thresholds.

**`load_config(path)`** (L102): YAML config (or JSON fallback).

**`JITLoggingConfig`**: Controls JIT observability and scope filtering:
| Field | Default | Purpose |
|-------|---------|--------|
| `enabled` | `True` | Emit periodic JIT status lines |
| `periodic_interval_ms` | 10000 | Minimum ms between status lines |
| `summary_every_requests` | 50 | Also emit after N events regardless of time |
| `debug_min_interval_ms` | 100 | Minimum ms between DEBUG-level per-call logs |
| `require_target_paragraph_context` | `True` | Skip JIT when no target paragraph supplied |
| `jit_scope_policy` | `"target_gates_plus_slice"` | Variable-level scope filter: `all` (no filtering), `target_gates_only` (gating vars only), `target_gates_plus_slice` (gating + backward-slice vars) |

### `specter/cobol_validate.py` — Two-Pass Validation (~200 lines)

**`validate_store(ast_source, cobol_source, store_path, ...)`** (L21): Python pass → COBOL pass → reconcile → `.validated.jsonl`.

---

## Monte Carlo & Test Synthesis

### `specter/monte_carlo.py` — Randomized Execution (~2400 lines)

**`run_monte_carlo(module_path, n_iterations, seed, ...)`** (L2252): Main entry. Dispatches to guided fuzzing or random walk.

**`_run_paragraph_directly(module, para_name, state)`** (L944): Direct paragraph invocation for unreachable code.

**Corpus management**: Energy-based seed selection, eviction at 500 entries, frontier bonus, recency bonus, yield penalty.

**Input generation**:
- Status vars remain 80% success-biased.
- Flags and inputs still prefer harvested literals when available.
- Guided semantic generation now uses a shared `JITValueInferenceService` plus `build_variable_domains(...)` so values are inferred lazily per variable/target paragraph instead of eagerly for the whole session.
- When JIT inference succeeds, inferred profiles are also cached into the Monte Carlo semantic-profile store for reuse by later strategy mutations.

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

### `specter/memory_models.py` — Memory-Guided State Schema (~240 lines)

Additive persisted schema for memory-guided loop state:
- `SuccessState`: coverage-producing test input/stub snapshot
- `FailureFragment`: no-gain fragment (schema ready)
- `TargetStatus`: per-target attempts/nearest-hit/solved metadata
- `StrategyStats`: per-strategy yield counters
- `APIBudgetLedger`: persisted API usage counters
- `MemoryState`: top-level aggregate with `meta`

### `specter/memory_store.py` — Crash-Safe Memory Persistence (~170 lines)

Run-local memory storage with atomic writes:
- `derive_memory_dir(store_path)`: deterministic memory directory from JSONL stem
- `MemoryStore.load_state()` / `save_state()`: resilient state load/save
- `append_success()` / `append_failure()` / `upsert_target_status()` / `upsert_strategy_stats()` / `update_api_ledger()`
- `checkpoint(...)`: writes round/final progress markers into memory `meta`
- `prune_state(...)`: bounded retention for successes/failures

### `specter/persistence_utils.py` — Atomic File I/O Helpers

Shared persistence primitives for crash-safe writes:
- `atomic_write_text(...)`
- `atomic_write_json(...)`
- `append_line_with_fsync(...)`

Used by test-store appends, memory checkpoints, resolution/checkpoint writes, and JIT cache persistence.

### `specter/run_manifest.py` — Run Metadata Manifest

Tracks source hash, copybook roots, and latest phase/checkpoint state in `.specter_run_manifest.json`.

Key functions:
- `ensure_manifest(...)`
- `record_phase_checkpoint(...)`
- `load_manifest(...)` / `save_manifest(...)`

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
    [--coverage-config config.yaml] [--llm-guided --llm-provider openrouter] \
    [--debug]
```

The `--debug` flag enables `logging.DEBUG` on the root logger for the coverage run, which surfaces per-call JIT gate decisions (untargeted / out-of-scope / cache-hit / cache-miss) and per-round strategy details.

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
| `test_cobol_coverage.py` | 81 | Integration: AST → Python → COBOL execution, JIT scope/gating, allowlist building |
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
| `test_memory_store.py` | 3 | Memory persistence: derive_memory_dir, round-trip save/load, prune+checkpoint |

**Total: ~459 tests**

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
11. **JIT scope restriction**: JIT LLM calls are allowed only when a concrete target paragraph is known AND the variable is within the per-target allowlist (gating vars ∪ backward-slice vars ∪ stub-return vars). This eliminates low-signal "Target paragraph: none" prompts and keeps semantic inference tightly coupled to the currently blocked coverage target.