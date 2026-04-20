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
└─────────┬───────────────┘   │  llm_coverage.py (LLM calls) │
          │                   │  llm_test_states.py          │
          │                   │  supervisor_channel.py       │
          │                   │   (teacher/student IPC on    │
          │                   │    reviewer deadlock)        │
          ▼                   └──────────┬───────────────────┘
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

**Unified Branch Registry (`specter/branch_registry.py`)**: Single source of truth for branch identity across Python (`code_generator`) and COBOL (`cobol_mock._add_branch_tracing`). Each branch gets a content hash — `sha1(paragraph || normalized_condition || type || per-paragraph-per-type ordinal)` — computed identically on both sides. `code_generator` emits `_BRANCH_META` and `_BRANCH_CONTENT_HASHES` from the registry; `cobol_mock` stamps `content_hash` (IF) and `when_hashes[direction]` (EVALUATE WHEN arms) onto its `branch_meta` entries; `cobol_executor.prepare_context` joins the two by hash and stores the result in `CobolExecutionContext.python_to_cobol_bid`. `ctx.translate_py_branch("py:<N>:T")` returns the matching `"<cobol_bid>:<direction>"` probe (or `None` when there is no counterpart, e.g. PERFORM VARYING or EVALUATE `:F`).

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
- **Scribe / challenger LLM review** (`specter/llm_review.py`): After the rule-based gate accepts a proposal, a second LLM call (the *challenger*) is asked to verify the fix is non-destructive against an explicit rubric (commenting out referenced lines, renaming undefined symbols, narrowing PIC clauses, mid-paragraph GOBACK/EXIT, replaced business statements, ...). The challenger returns `{"verdict": "accept" | "reject", "reason": "...", "severity": "high" | "low", "guidance": "..."}`. `ReviewVerdict` carries `verdict`, `reason`, `severity` (`high` = revise, `low` = abandon), and an optional `guidance` string the scribe can follow to find a better fix location. On `reject` the scribe is re-prompted with the reviewer's reason (and guidance if any) appended and tries again, up to `_LLM_REVIEW_MAX_REVISIONS = 3` revisions per error attempt before the proposal is recorded as failed. On `unknown` (reviewer outage / parse failure / kill switch active) the proposal passes through unblocked. Worst-case cost is 4 scribe calls + 4 reviewer calls per error attempt; most attempts pass on the first review. Bypassed via `--no-llm-review` CLI flag or `SPECTER_LLM_REVIEW=0` env var.
- **Failed-attempt memory**: LLM sees "WHAT WORKED" and "WHAT FAILED" sections with prior attempts from this cycle (now also includes reviewer-blocked attempts).
- **Error clustering**: Adjacent errors (within 10 lines) are treated as one root cause — failing one marks the whole cluster.
- **Relaxed verification**: Accept if total error count drops (not just the specific line). **Teacher-patch parity exception**: when a patch arrives via the supervisor channel (`is_teacher_patch=True`), it is kept as long as error count doesn't *increase* — teacher authority bypasses the scribe's strict-decrease gate because the teacher can see structural context the scribe can't (e.g. the fix addresses one of N parallel errors on related lines). Teacher patches are still appended to `resolution_log.json` so they replay on future runs via `_apply_preventive_fixes()`.
- **Supervisor escalation on reviewer deadlock**: When the scribe exhausts `_LLM_REVIEW_MAX_REVISIONS` or the compile swarm produces a duplicate, `_compile_and_fix` escalates through `specter/supervisor_channel.py` (env-gated via `SPECTER_SUPERVISOR=<run_dir>`). A teacher `patch` verdict replaces `fixes` and falls through to apply-and-verify. `skip` abandons this error. `abort`/`restart` raise `SupervisorAbort`/`SupervisorRestart` — both inherit from `BaseException` so the `except RuntimeError` fallback in `cobol_coverage.py:2463` cannot silently retry them. Disabled (no-op) when `SPECTER_SUPERVISOR` is unset.
- **Pre-Phase-3 error deferral**: `_is_deferred_to_later_phase(line, msg, src, phase)` flags errors inside `EXEC CICS`/`EXEC SQL`/`EXEC DLI` blocks during `copy_resolution` / `mock_infrastructure` as owned by Phase 3's `_replace_exec_blocks` transform. The fix loop drops deferred errors from the actionable set (the scribe is never asked to "repair" a block Phase 3 will transform), and `_count_actionable_errors()` excludes them from the phase gate. `_normalize_phase_token()` strips suffixes (`_transformed`, `_resumed`, `_done`) and applies aliases (`mock_infra` → `mock_infrastructure`, `copy` → `copy_resolution`, etc.) so checkpoint names used by `_assert_clean` resolve to canonical phase tokens. Teacher-taught skip rules (`TeacherRulesStore`) extend this hardcoded deferral with patterns the student doesn't know about yet.
- **Audit log** (`fix_audit.log`): Every accepted fix logged with BEFORE/AFTER per line, tagged [COMMENTED OUT], [ADDED], or [MODIFIED]. Teacher-patch acceptances are logged as "ACCEPTED — teacher patch kept at parity".

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
- **`_fix_condition_name_moves(errors, src_lines)`**: Deterministic pre-fix for "condition-name not allowed here" errors. When the mock generator produces `MOVE MOCK-ALPHA-STATUS TO <88-LEVEL-FLAG>` (from checkpoint-resumed builds or copybook variables not in `condition_names_88`), this rewrites it to `SET <FLAG> TO TRUE` before the LLM loop runs. Zero LLM cost; prevents destructive LLM fixes that spread multi-value lists across unrelated lines.
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

**`MockConfig`** (L62): Configuration dataclass — copybook_dirs, trace_paragraphs, mock_file_name, stop_on_exec_return/xctl, eib_calen, eib_aid, initial_values, payload_variables, `condition_names_88` (dict[str, str] mapping 88-level child name → activating value, populated from copybooks + `_extract_88_values_from_source` at instrumentation time). When generating mock status-setting code for an 88-level flag, the generator emits `IF MOCK-ALPHA-STATUS = '<activating_value>' SET <flag> TO TRUE END-IF` instead of the invalid `MOVE MOCK-ALPHA-STATUS TO <flag>`. Three emission sites: `_replace_io_verbs`, `SPECTER-READ-INIT-VARS`, `SPECTER-APPLY-MOCK-PAYLOAD`.

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
- Probe counts reflect directions actually inserted (including deterministic `ELSE` injection for structured IFs that originally had no ELSE), not assumed T/F pairs.

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

### `specter/branch_swarm.py` — Swarm + planner pipeline with iterative deepening (~1200 lines)

Combines parallel specialist proposals (diverse LLM perspectives) with hierarchical execution planning (correct end-to-end trace construction) and iterative deepening (decompose into reachability then branch flipping). When the coverage loop plateaus (`stale_rounds >= 3`), the swarm picks the top-K uncovered branches and runs up to `max_rounds` attempts per branch.

**Iterative deepening — two-phase per branch:**

- **Phase 1 (Reach)**: When the target paragraph hasn't been visited by any test case, the first 1–2 rounds focus exclusively on getting the COBOL binary to execute the target paragraph. The condition text is temporarily replaced with `(Phase 1: just reach paragraph X)` so specialists propose stubs for reachability, not the branch condition. Validated by `paragraph in result.paragraphs_hit`.

- **Phase 2 (Flip)**: Once reachability is solved (or was already solved from prior strategies), remaining rounds focus on flipping the specific branch condition. Phase 1's working input_state and stubs are warm-started into `nearest_hit` so the History Miner and other specialists build on the known-working base.

Round allocation: if the paragraph is already in `cov.paragraphs_hit`, Phase 1 is skipped and all rounds go to Phase 2. Otherwise 2 rounds for Phase 1, remaining for Phase 2. Each round runs `_run_swarm_round()`.

**Round flow (Phase 1 or Phase 2):**

1. **Specialist swarm** (4 parallel LLM calls): Condition Cracker, Path Finder, Stub Architect, History Miner. Proposals merged with priority: path_finder > condition_cracker > stub_architect > history_miner. Specialists see the **full COBOL execution trace** from the previous round via `_format_prior_feedback()` — including which paragraphs executed, where execution stopped, and COBOL DISPLAY error messages (filtered for ERROR/ABEND/STATUS/FAIL keywords).

2. **Route Planner** (deterministic): `_plan_route(bctx, ctx)` uses `StaticCallGraph.path_to(paragraph)` and `gating_conds` to compute the ordered paragraph path from program entry to the target.

3. **Python validation** (~3 ms): `_validate_python()` forward-runs the merged candidate. On failure, produces per-gate diagnosis.

4. **Gate Solver** (0–1 LLM call): Only called when Python validation fails. `_solve_gates()` sends a backward-chaining prompt with route + proposals + diagnosis. Refines the merged proposal.

5. **Tape Builder** (deterministic): `_build_tape()` runs `_python_pre_run` for execution-ordered `stub_log`.

6. **Direct Execution**: `_execute_directly()` calls `run_test_case` directly, bypassing `_execute_and_save`. Captures `cobol_trace` (ordered paragraph list) and `display_output` into `JudgeFeedback` for the next round's specialists.

**Failure logging**: `_write_failure_log()` appends a structured JSON entry to `<store_stem>.swarm_failures.jsonl` with full diagnostic context including `cobol_trace` and `display_output` per round.

**LLM budget**: 4–5 calls per round (4 specialists + 0–1 gate solver refinement). Total per branch: up to `max_rounds × 5` calls.

**`run_branch_swarm(ctx, cov, report, tc_count, ...)`** — top-level entry. Signature-compatible with `run_branch_agent()`. Returns `(journals, n_solved, tc_count)`. `SwarmJournal` backward-compatible with `BranchAgentJournal`.

Configuration: `SPECTER_BRANCH_SWARM=0` to fall back to single-agent `branch_agent.py`. `--agent-iterations N` controls max rounds per branch, `--no-branch-agent` disables both.

### `specter/branch_agent.py` — Single-agent fallback for stubborn branches (~450 lines)

Legacy single-agent loop retained as fallback when `SPECTER_BRANCH_SWARM=0`. Focused, multi-turn LLM investigation: gather context → propose → execute → feed back → repeat up to `max_iterations` turns.

**`run_branch_agent(ctx, cov, report, tc_count, ...)`** — top-level entry point. Picks top-K branches via `_select_priority_branch_targets`, runs `investigate_branch()` for each, persists journals, returns `(journals, n_solved, tc_count)`.

Configuration: `--agent-iterations N` (LLM turns per branch), `--no-branch-agent` (kill switch), `SPECTER_BRANCH_AGENT=0` (env var kill switch). Capped at `_BRANCH_AGENT_MAX_INVOCATIONS = 3` per coverage run.

### `specter/compile_swarm.py` — 3-specialist swarm for compilation fixes (~320 lines)

Invoked from `_compile_and_fix` (see `incremental_mock.py`) when the challenger reviewer (`llm_review.py`) rejects the scribe's first proposal. Instead of re-prompting the same scribe, three specialists run **in parallel** via `ThreadPoolExecutor(max_workers=3)` — each with a different focus.

**Specialists** (each receives error line, error message, ±15-line code context):

1. **Syntax Specialist** (`_syntax_prompt`): COBOL fixed-format rules — columns 8–72, Area A for section/paragraph headers, Area B for statements, periods, reserved words, literal formats, line continuation (col 7 = `-`).

2. **Semantic Specialist** (`_semantic_prompt`): preserves business logic. Hard rules the specialist must follow: NEVER comment out referenced code, NEVER rename undefined symbols, NEVER insert GOBACK/EXIT to short-circuit, NEVER narrow PIC clauses, NEVER delete EVALUATE/WHEN clauses or IF branches. Prefer adding missing definitions over removing references.

3. **Structure Specialist** (`_structure_prompt`): data definitions — 88-level condition-names (MOVE to 88-flag → `SET <flag> TO TRUE`), group items vs elementary PIC clauses, record structures, FILLER, REDEFINES, USAGE COMP/BINARY/DISPLAY, qualified names (`FIELD OF RECORD`).

**Judge** (`_judge_proposals` + `_score_proposal`): rule-based scoring that **hard-rejects (-999 score)** any proposal taking the easy way out:

- Commenting out a previously-active line (turning it into `*COMMENT`)
- Replacing an active statement with `CONTINUE` / `EXIT` / `NEXT SENTENCE`
- Whitespace-only replacement (line deletion)
- Inserting `GOBACK` / `STOP RUN` / `EXIT PROGRAM` in a line that wasn't already one

Soft scoring for acceptable fixes: +10 for addressing the error line, +5 per structural keyword (SET/PIC/01-level). A proposal must score above -100 to be accepted; otherwise the judge returns empty fixes and the scribe revision path takes over.

`propose_compile_fix_swarm(error_line, error_msg, context, src_lines, llm_provider, llm_model)` — top-level entry. Returns `(fixes_dict, reasoning)`, signature-compatible with a single-scribe call.

Configuration: `SPECTER_COMPILE_SWARM=0` to disable and fall back to single-scribe revision for all rejections.

### `specter/supervisor_channel.py` — Teacher/student IPC channel (~465 lines)

Env-gated JSONL channel between a long-running Specter run (the *student*) and a supervisory agent or human session (the *teacher*). The channel fires when `_compile_and_fix` hits a reviewer deadlock it cannot break on its own — scribe 3× rejected, compile swarm producing duplicates, or a phase gate about to raise — and blocks until the teacher appends a reply correlated by UUID. On timeout the student falls back to its existing abandonment path, so headless runs never deadlock.

**Activation — two gates**:
1. `SPECTER_SUPERVISOR=<run_dir>` configures the channel's file location.
2. `SPECTER_ESCALATE=1` (or pass `--escalate` on the CLI) opts in to escalation.

Both must be set for `SupervisorChannel.from_env()` to return an enabled instance. The split is intentional: a mature student runs autonomously by default, even when a channel directory is available. Escalation is an explicit opt-in that you turn on when iterating with a teacher agent and off once the student handles this class of program without help. When either gate is missing every method is a no-op (zero overhead on the hot path). The teacher side is `scripts/teach.sh <run_dir>` (or any equivalent watcher that tails `escalations.jsonl` and appends replies to `resolutions.jsonl`).

**Escalation sites**:
- `_compile_and_fix` — on reviewer deadlock (scribe exhausted `_LLM_REVIEW_MAX_REVISIONS` or compile swarm produced a duplicate).
- `branch_swarm.run_branch_swarm` — once per stubborn branch after all rounds are exhausted and the paragraph still isn't hit. The escalation is advisory: teacher verdicts are logged for human review but not applied as inline line-patches (the branch case has no line-patch semantics). `abort`/`restart` still propagate; `skip`/timeout/unknown all drop through to the normal failure-log path. Explicit design contract: *it is ok if teacher cannot help and student should not insist*.

**Files written into `<run_dir>`**:
| File | Producer | Purpose |
|------|----------|---------|
| `escalations.jsonl` | student | Append-only event log — UUID, kind, summary, full context, artifact paths, student_hints pointing at the files the teacher should consider editing, and `related_findings` (prior teacher knowledge for this class). |
| `resolutions.jsonl` | teacher | Append-only replies — `{id, verdict, fix?, notes, save_rule?, finding?}`. Student polls for matching `id` with a bounded timeout. |
| `status.jsonl` | student | Heartbeat snapshots (phase, round, coverage). |
| `teacher_rules.jsonl` | channel | Durable skip rules persisted from `save_rule` replies. |
| `teacher_findings.jsonl` | channel | Structural observations persisted from `finding` replies (lint inbox). |
| `teacher_facts.jsonl` | channel | Program-specific domain facts persisted from `save_fact` replies (shape values on the next run). |

**Verdicts** (`_VALID_VERDICTS`): `patch` (inline `{line: content}` fix applied at error-count parity), `skip` (abandon this error and continue), `abort` (raise `SupervisorAbort`), `restart` (raise `SupervisorRestart`), `retry_with` (accept altered flags — reserved).

**Exception contract**: `SupervisorAbort` and `SupervisorRestart` inherit from `BaseException`, not `Exception`. The broad `except RuntimeError:` fallback in `cobol_coverage.py:2463` (and similar `except Exception:` handlers across the codebase) cannot catch them. Only explicit `except SupervisorAbort` / `except BaseException` / bare `except:` will catch. Modeled on `KeyboardInterrupt`/`SystemExit`.

**Durable teacher knowledge**:
- **`TeacherRule`** — dataclass carrying `kind` (currently `skip_error_class`), `phase`, `msg_contains: list[str]`, optional `source_context_contains`, free-form `reason`, `issued_by`, `ts`. `matches(phase, msg, source_window)` returns True when the phase matches (wildcard `*` allowed), every token in `msg_contains` is a substring of the error message, AND (if set) the source window contains `source_context_contains` (case-insensitive).
- **`TeacherRulesStore`** — append-only JSONL store keyed on a single file path. `reload()` re-reads, `append(rule)` writes + caches, `match(phase, msg, source_window)` returns the first matching rule or `None`. `_compile_and_fix` consults this alongside `_is_deferred_to_later_phase`, so a teacher-taught rule skips the escalation entirely on the next compile pass. `_count_actionable_errors` (used by `_assert_clean`) also honors it, so a taught skip rule passes the phase gate.
- **`TeacherFindingsStore`** — append-only JSONL store of structural observations (never auto-applied). Each entry: `{severity, title, suggested_files?, notes, ts}`. Intended as a lint inbox the operator reviews between runs.
- **`TeacherFact`** — dataclass carrying `kind` (`variable_format` / `variable_values` / `stub_outcome` / `note` / free-form), `target` (variable name / paragraph / stub op key, uppercased), `scope` (`variable` | `paragraph` | `stub_op` | `global`), `content` (human-readable rule), `examples: list[str]`, `reason`, `issued_by`, `ts`. Represents program-specific domain knowledge the student can't derive from names or PIC clauses.
- **`TeacherFactsStore`** — append-only JSONL store at `<run_dir>/teacher_facts.jsonl`. `match(scope, target)` returns every fact matching that scope/target plus every `scope=global` fact, so generic system-wide notes get threaded into every prompt. Consumed by `JITValueInferenceService` via its `facts_store` constructor parameter: matching facts are rendered into the LLM inference prompt as "Teacher-curated domain facts" (authoritative), and a short digest over the facts is mixed into `_cache_key` so a newly-learned fact invalidates previously cached profiles.

**End-of-cycle review** (`cobol_coverage._end_of_cycle_review`): fires once after the final uncovered-branch report is written, gated on `SPECTER_SUPERVISOR` + `SPECTER_ESCALATE`. Packages a compact summary of up to 25 uncovered branches (bid, direction, paragraph, condition text) and escalates with `kind="end_of_cycle_review"`. The teacher reviews and optionally replies with `save_fact` entries; the channel persists them automatically. Policy is explicit in the summary text: facts are for **program-specific** knowledge only — if something should become a code heuristic (e.g. any variable whose name ends in `-DATE` should default to a 6-digit date), the teacher records a `finding` and edits student code instead.

**`Resolution`** dataclass: `id`, `verdict`, `fix: dict[int, str]`, `notes`, `raw`, plus optional `save_rule: dict`, `finding: dict`, `save_fact: list[dict]` (accepted as a single dict or a list) that the channel persists via `_persist_durable_fields()`, and `test_cases: list[dict]` (also accepted as single dict). JSON fix keys arrive as strings; `_parse_resolution()` coerces to `int`.

**Teacher test cases** (`Resolution.test_cases`): optional data-only field carrying concrete test inputs the teacher validated in its own Python. Each entry is `{"input_state": {VAR: VALUE, ...}, "stub_log": [[op_key, [[var, val], ...]], ...], "target"?: "branch:<bid>:<dir>", "notes"?: "..."}`. No teacher code runs on the student side. Consumed at the `branch_swarm.py` exhaustion escalation: `_consume_teacher_test_cases()` normalizes the stub_log shape (list or dict), uppercases variable keys, and feeds each entry through `_execute_directly()` — the same path specialist proposals use. Successful cases persist into the test store tagged `target="direct:<para>|swarm:<branch>"`. Malformed entries (missing `input_state`, non-dict shapes, unknown verbs) are dropped silently with a warning. See `test_resolution_parses_test_cases_list`, `test_resolution_accepts_single_test_case_shorthand`, and `test_normalize_stub_log_accepts_list_and_dict_shapes` in `tests/test_supervisor_persistence.py` for the contract.

**`_related_findings(kind, context)`** (called by `escalate()`): scans the findings store for entries whose title or notes mention the current error message or phase, and summarizes the rules store (`count` + `reasons[:5]`) when any rule matches the current event class. Capped at 8 items so the escalation payload stays readable.

**Hook site in `incremental_mock.py`**: `_compile_and_fix` instantiates `supervisor = SupervisorChannel.from_env()` once at entry and calls `supervisor.rules_store.reload()` so any prior-run rules apply immediately. When `review_blocked=True`, the hook builds an escalation payload (error line/msg, scribe revision count, last proposed fix, ±15-line source snippet, artifact paths, student-file hints) and consumes the reply:
- `abort` / `restart` → raise the matching `BaseException` subclass.
- `patch` + non-empty fix → overwrite `fixes = _resolution.fix`, set `review_blocked = False` and `is_teacher_patch = True`, fall through to apply-and-verify.
- `skip` / unknown verdict / `None` (timeout) → fall through to existing abandonment.

Integration surfaces:
- `scripts/teach.sh <run_dir>` — thin `tail -F` helper; pair with `Monitor` in a teacher session.
- `tests/test_supervisor_channel.py` — channel round-trip, timeout, disabled mode, unknown verdict, heartbeat.
- `tests/test_supervisor_fixes.py` — `SupervisorAbort` uncatchable by `except Exception` / `except RuntimeError`; `_is_deferred_to_later_phase` classification; phase-token normalization.
- `tests/test_supervisor_persistence.py` — `TeacherRule.matches` (phase, tokens, source window), rules-store round-trip, findings store, `TeacherFact` round-trip, `TeacherFactsStore.match` (scope-specific + global fallthrough), full escalate → `save_rule` / `finding` / `save_fact` persistence flows, related_findings inclusion, shorthand `msg_contains` as string, JIT prompt includes facts, `_facts_digest` cache-key invalidation.

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

#### Debugging Unreachable Coverage Gaps

When a branch shows **`Attempts: 0`** — meaning no strategy ever generated a test case for its paragraph — the root cause is typically one of:

1. **Structural unreachability**: The paragraph has no incoming edges in the call graph
   - **Check**: Use `build_static_call_graph(program)` to verify an edge path connects the program entry to the target paragraph via PERFORM or GO TO
   - **Fix**: If no path exists, the paragraph may be dead code or only reachable via external entry points not captured in the AST
   - **Example**: `3173-00-MONTA-BUCKET` with 48 uncovered branches saw 0 attempts → likely gated by a high-level condition that constrains which paragraphs are PERFORMed at all

2. **Input variable underspecification**: Gating conditions depend on input variables that don't carry sufficient literal diversity
   - **Check**: Run `variable_extractor.extract_variables(program)` and inspect the `condition_literals` for each input variable; expand with `--init-var VAR=value` CLI overrides
   - **Example**: `BUCKET-AGED-PENALTY LESS ZEROS` with known literals `{0, -1, 1, ''}` means the harvester found the boundary but random fuzzing may still miss the true case; seed with `--init-var 'BUCKET-AGED-PENALTY=-1'`
   - **Harvester gaps**: Check `_harvest_condition_literals()` in `variable_extractor.py` — it supports basic IF `<var> op <literal>` forms; EVALUATE WHEN or complex AND/OR may not be harvested

3. **88-level sibling activation**: A branch condition references an 88-level flag (e.g., `IF APPL-EOF`) but the parent variable is not set to the activating value in any test case
   - **Check**: The uncovered report shows the 88-level child name and the parent + activating value (e.g., `{'APPL-EOF': ('APPL-RESULT', 16)}`)
   - **Fix**: Ensure `BaselineStrategy` Phase 3 injects the parent variable with that value; verify `variable_domain.py` correctly parsed the 88 VALUE clauses from copybooks or inline program source
   - **Example**: If `APPL-RESULT = 16` activates `88 APPL-EOF VALUE 16` but coverage never hits the `IF APPL-EOF` branch, check that the test-store contains at least one case with `APPL-RESULT=16` in its `input_state`

4. **Stub-return variable gating**: A branch depends on the result of a previous operation's mock response (e.g., `IF SQLCODE = 0`)
   - **Check**: Verify the `op_key` in the variable report (e.g., `CICS-READ:MYFILE`) appears in test-case `stub_outcomes`; FaultInjectionStrategy should rotate through all expected return codes
   - **Fix**: Expand the stub domain in `coverage_strategies.py` or ensure `--coverage-budget` is large enough for `FaultInjectionStrategy` to explore all fault codes

#### Performance Tuning for Coverage

Common adjustments when plateau occurs:

| Symptom | Tuning |
|---------|--------|
| Conditions with high literal diversity (>5 unique known values) never covered | Increase `--coverage-batch-size` (e.g., 500 → 1000) to generate more cases per strategy round |
| File-status or SQL-error branches stuck at 0% | Run `--coverage-rounds` longer or explicitly call `FaultInjectionStrategy` via `coverage-config.yaml` with higher priority |
| 88-level flag siblings in uncovered → baseline phase not running long enough | Verify `BaselineStrategy` priority is high (default 20) and phase count allows per-88-sibling fan-out |
| Compound AND/OR (`compound_and_or` category) rarely hit | Use `--llm-guided` to seed semantic inputs that naturally satisfy multi-variable constraints |
| Random walk exhausted corpus but coverage stalled | Try `--coverage-config` with `strategies: [direct_paragraph, corpus_fuzz]` (drop baseline/fault_injection if 0 attempts on most) |

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
    --java-package com.example --test-store tests.jsonl --copybook-dir ./cpy
```

### Unified Pipeline (end-to-end equivalence harness)

```bash
python3 -m specter program.ast --pipeline \
    --cobol-source program.cbl --copybook-dir ./cpy -o out/
```

`--pipeline` runs six phases in sequence with no manual steps:

1. **coverage** — `specter.cobol_coverage.run_cobol_coverage(...)` produces
   `out/tests.jsonl` and an instrumented COBOL binary cached under
   `<source>/.specter_build_<stem>/`.
2. **snapshot** — `specter.cobol_snapshot.capture_snapshots(...)` replays
   every test case through the same compiled binary (via
   `cobol_executor.run_test_case`) and writes
   `out/cobol_snapshots/<tc_id>.json` with `{abended, displays,
   paragraphs_covered, branches, stub_log_keys, final_state}`. Values are
   normalised in `specter.cobol_snapshot.normalize_value` (rstrip PIC X
   trailing spaces; canonical numeric form for leading-zero ints/decimals).
3. **java** — `generate_java_project(..., snapshot_dir=...)` emits the
   Maven project + Docker compose (PostgreSQL + RabbitMQ + WireMock) +
   per-test seed SQL + per-test WireMock mappings, and copies the
   snapshots into `integration-tests/src/test/resources/cobol_snapshots/`.
   Two new Java classes (`CobolSnapshot`, `EquivalenceAssert`) are emitted
   alongside the IT class.
4. **deploy** — `docker compose up -d db rabbitmq wiremock` (skippable via
   `--pipeline-skip-docker`).
5. **validate** — `mvn install -DskipTests` (parent) +
   `mvn verify` (`integration-tests/`). Each parameterised test loads its
   snapshot via `CobolSnapshot.loadFor(..., tc.id)` and calls
   `EquivalenceAssert.assertEquivalent(snapshot, state)`. Strict checks:
   `abended`, `displays`, paragraph trace order, and `final_state` values
   for every key in the snapshot. Branches are NOT compared (IDs are
   independently assigned by the COBOL probe inserter and the Java
   generator). Skippable via `--pipeline-skip-mvn`.
6. **report** — Surefire/Failsafe XML is parsed; tc IDs are extracted
   from `EquivalenceAssert` failure messages; a markdown summary is
   written to `out/equivalence-report.md` and a one-line summary printed
   to stdout. Exit code is 0 only when every test case passes.

Modules added for the unified pipeline:
- `specter/pipeline.py` — `run_pipeline`, `_parse_test_reports`,
  `_write_report`, `PipelineResult`.
- `specter/cobol_snapshot.py` — `CobolSnapshot`, `capture_snapshots`,
  `normalize_value`, `values_equivalent`, `iter_test_cases`.
- `specter/java_templates/equivalence.py` — `COBOL_SNAPSHOT_JAVA`,
  `EQUIVALENCE_ASSERT_JAVA`.

`--java` now defaults to emitting a fully wired harness for batch jobs:
- Maven POM swaps Jakarta JMS / ActiveMQ Artemis for `com.rabbitmq:amqp-client:5.21.0`
  and adds Apache HttpClient5 (`5.3.1`) for outbound CALL routing.
- `docker-compose.yml` runs three sidecars: `postgres:16-alpine`,
  `rabbitmq:3-management`, and `wiremock/wiremock:3.5.4` (with
  `./wiremock/mappings/` mounted into the container).
- `JdbcStubExecutor` uses the typed RabbitMQ client (`Channel.queueDeclare` /
  `basicGet` / `basicPublish`) for `mqOpen/Get/Put1/Close`, and routes every
  non-MQ `CALL 'PROGNAME'` through `callProgram(...)` which POSTs JSON to
  `${SPECTER_CALL_BASE_URL}/<progname-lowercase>` (default
  `http://wiremock:8080`) and maps the JSON response back into `ProgramState`.
- For each test case in the JSONL store, the generator emits:
  - `wiremock/mappings/<tc_id>/<seq>_<progname>.json` — one stub per non-MQ
    `CALL:*` outcome; multi-outcome chains use WireMock scenario state.
  - `integration-tests/src/test/resources/seeds/<tc_id>.sql` — `TRUNCATE` +
    `INSERT` per `CICS-READ` / `READ:<file>` / `DLI-GU` outcome, mapped to the
    real application tables defined by copybook DDL in `sql/init.sql`.
- The `MOCKITO_INTEGRATION_TEST_JAVA` template loads the per-test seed SQL in
  the test body via `seedRealTables(tc)`, and `seedRabbitMq(tc)` publishes
  `CALL:MQ*` outcomes to AMQP queues so a real `JdbcStubExecutor` exercises
  the code paths end-to-end.

Defaults are always-on; the legacy `--docker` and `--integration-tests` flags
remain accepted for back-compat but are no-ops when `--java` is set.

Generator modules added for this work:
- `specter/java_templates/wiremock.py` — `render_mapping`, `write_mappings`,
  `is_routable_call_key`.
- `specter/java_templates/seed_sql.py` — `build_seed_sql`, `build_table_index`,
  `is_seedable_op_key`.
- `specter/java_code_generator.py::_extract_call_using_vars` — parses the
  COBOL CALL USING clause to thread input variable names into `callProgram`.

**File-status reset before I/O stubs** (`_emit_file_status_reset`). The COBOL
mock for OPEN/READ/CLOSE unconditionally does `MOVE MOCK-ALPHA-STATUS TO
<status-var>` inside each replaced I/O verb — on an exhausted FIFO this is
SPACES, so the status variable is always freshly blanked. Java's
`applyStubOutcome` only sets variables that appear in an outcome pair; with no
outcome it leaves the status var at whatever value was there before (often an
injected test-input). `_JavaCodeBuilder.file_status_map` (populated in
`generate_java_project` via `cobol_mock._extract_file_status_map`) maps each
file to its status-var. `_gen_open_java` / `_gen_read_java` / `_gen_close_java`
emit `state.put("<status-var>", "")` before every `applyStubOutcome(...)` call
so the Java runtime matches COBOL's "blanked by default, overwritten by
outcome" semantics. Without this, tests with empty stub FIFOs produce
systematic display divergences (e.g. `FILE STATUS IS: NNNN0000` instead of
`FILE STATUS IS: NNNN 032` from an injected numeric zero in an alpha group).

**Strict `isNumeric`** (`CobolRuntime.isNumeric`). Matches COBOL's `IS NUMERIC`
class test: every character must be a digit (plus optional leading sign; one
optional decimal point). No `trim()` — embedded or trailing spaces disqualify.
Diverges from `Double.parseDouble` on e.g. `"0 "` (trailing space): strict
returns false, parseDouble returns true. Matters for conditions like
`IF IO-STATUS NOT NUMERIC OR IO-STAT1 = '9'` where the IS-less form of
`NOT NUMERIC` now also parses correctly in `java_condition_parser` (both
`IS NUMERIC` and bare `NUMERIC` are recognised).

**Snapshot abend threshold**. `CobolSnapshot.abended = (result.return_code >= 8)`
(not `!= 0`). GnuCOBOL emits rc=4 for runtime warnings (e.g. numeric overflow)
even when the program completes all close paragraphs cleanly; Java's explicit
`state.abended` flag only flips on ABEND paths, so matching the IBM/mainframe
convention (rc=0 OK, rc=4 warning, rc>=8 fatal) keeps the two aligned.

**ABEND routines terminate the program** (`cobol_mock._replace_call_stmts`
+ `java_code_generator._gen_call_java`). `CALL 'CEE3ABD'` (and the
IBM-family `ILBOABN0`, `DSNTIAR`, `CICSABEND`, etc.) are program-termination
routines on real z/OS. Under the mock, a naive replacement (consume stub +
RETURN-CODE move) let them act as no-ops — batch programs' `9999-ABEND-
PROGRAM` would return to the main loop, re-enter the failing path, and blow
GnuCOBOL's call stack (rc=160) after thousands of retries. The COBOL mock
now emits `STOP RUN` after the stub consume, and Java's `_gen_call_java`
emits `state.abended = true; throw new GobackSignal();` — both terminate at
the first abend, matching real-mainframe behaviour. Without this pairing,
equivalence pass-rate on CBTRN02C was 13/31; with it, 31/32.

**LLM provider threaded through pipeline** (`pipeline.run_pipeline`,
`__main__`). `--pipeline` now accepts `--llm-provider` / `--llm-model` and
threads them into both `run_cobol_coverage` and `prepare_context` so the
incremental-mock compile-and-fix loop can actually repair the copybook
resolution errors that only surface after COPY inlining. Without this,
the pipeline stalls at "Phase 1 (COPY resolution) stalled with N errors"
the moment a generated mock has any non-trivial syntax issue.

---

## Testing

### Test Files

| File | Tests | Coverage |
|------|-------|----------|
| `test_cobol_coverage.py` | 102 | Integration: AST → Python → COBOL execution, JIT scope/gating, allowlist building, concolic escalation hook, FaultInjection re-entrant, branch-id conversion |
| `test_java_condition_parser.py` | 56 | Java condition code generation |
| `test_copybook_parser.py` | 38 | Copybook parsing, PIC types, 88-level values |
| `test_uncovered_report.py` | 36 | Post-run diagnostic report: condition classification, variable extraction, branch-condition scanning, attempt counting, hint generation, incremental + exception-path writes, stub_outcomes dual-shape |
| `test_incremental_mock.py` | 36 | Incremental pipeline, resolutions, max_count batching, mock infrastructure |
| `test_88_siblings.py` | 36 | COBOL 88-level sibling detection, inline 88-value extraction from source, BaselineStrategy Phase 3 enumeration |
| `test_llm_fuzzer.py` | 33 | LLM-guided fuzzing |
| `test_fuzzer.py` | 29 | Coverage-guided fuzzing, energy, corpus |
| `test_concolic.py` | 28 | Z3 concolic solver |
| `test_condition_parser.py` | 27 | COBOL condition → Python translation |
| `test_variable_extractor.py` | 24 | Variable classification, literal harvesting, EVALUATE WHEN literal harvest, subscript filtering |
| `test_llm_review.py` | 22 | Scribe/challenger LLM review: verdict parsing, kill switch, accept/reject paths, exception safety |
| `test_llm_coverage.py` | 22 | LLM provider abstraction, coverage gaps |
| `test_static_analysis.py` | 18 | Call graph, gating conditions, equality constraints |
| `test_test_synthesis.py` | 17 | 5-layer synthesis, gating constraints |
| `test_code_generator.py` | 15 | Python code generation for all statement types |
| `test_analysis.py` | 14 | Dynamic analysis |
| `test_coverage_config.py` | 13 | Configuration management |
| `test_backward_slicer.py` | 12 | Program slicing for variable deps |
| `test_stub_diversification.py` | 12 | Stub diversification |
| `test_multi_program.py` | 11 | Multi-program XCTL routing |
| `test_integration_uncovered_fixes.py` | 8 | Integration: uncovered-branch fix workflows |
| `test_end_to_end.py` | 8 | Full pipeline (skipped if AST files missing) |
| `test_ast_parser.py` | 5 | AST deserialization |
| `test_memory_store.py` | 3 | Memory persistence: derive_memory_dir, round-trip save/load, prune+checkpoint |
| `test_supervisor_persistence.py` | 11 | Durable teacher knowledge: `TeacherRule.matches`, `TeacherRulesStore`/`TeacherFindingsStore` round-trip, full escalate → save_rule + finding persistence, related_findings in payload, shorthand msg_contains normalization |
| `test_supervisor_fixes.py` | 11 | `SupervisorAbort` uncatchable by `except Exception`/`except RuntimeError`, `_is_deferred_to_later_phase` classification (msg tokens + source context + phase gating), `_normalize_phase_token` alias handling, teacher-patch verdict shape |
| `test_supervisor_channel.py` | 6 | Channel round-trip: disabled mode, env toggle, patch reply, timeout, unknown verdict, heartbeat append |

**Total: 882 tests**

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
12. **Phase-owned error deferral**: Errors owned by later phases are skipped by earlier ones rather than being attempted and reverted. `_is_deferred_to_later_phase` catches EXEC CICS/SQL/DLI syntax errors during copy_resolution / mock_infrastructure, since `_replace_exec_blocks` will transform those blocks in Phase 3. Before this, reviewer-correct destructive rejections on CICS programs stalled Phase 1 indefinitely.
13. **Teacher/student escalation over file-based IPC**: On reviewer deadlock the student doesn't give up silently — it appends an escalation to `<run_dir>/escalations.jsonl` and blocks polling `resolutions.jsonl` for a UUID-correlated reply. Durable (crash-safe, auditable), works whether the teacher is online or not. `SupervisorAbort`/`SupervisorRestart` inherit from `BaseException` so outer `except` blocks can't silently retry a terminal teacher verdict. Teacher replies may carry `save_rule` (appended to `teacher_rules.jsonl` for persistent skip patterns) and `finding` (appended to `teacher_findings.jsonl` for structural review).