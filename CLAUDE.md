# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

Specter is a COBOL AST-to-executable-Python code generator with coverage-guided test synthesis. It reads a JSON AST file (produced by an external COBOL parser called cobalt) and generates a standalone Python module that simulates the COBOL program's execution. A strategy-based agentic loop maximizes paragraph and branch coverage by generating test cases — optionally cross-validated against real GnuCOBOL binaries.

## Commands

```bash
# Run all tests
python3 -m pytest

# Run a single test file
python3 -m pytest tests/test_condition_parser.py

# Run a single test
python3 -m pytest tests/test_condition_parser.py::TestConditionParser::test_simple_equality

# Generate Python from AST
python3 -m specter <ast_file.ast> [-o output.py] [--verify] [--monte-carlo N] [--seed S]

# Coverage-guided synthesis (Python-only)
python3 -m specter <ast_file.ast> --synthesize --test-store tests.jsonl \
    --coverage-budget 5000 --coverage-timeout 300

# GnuCOBOL hybrid coverage (compile + run real COBOL)
python3 -m specter <ast_file.ast> --cobol-coverage \
    --cobol-source <program.cbl> --copybook-dir <cpy_dir> \
    --coverage-budget 5000 --coverage-timeout 300

# With LLM-guided strategies
python3 -m specter <ast_file.ast> --cobol-coverage \
    --cobol-source <program.cbl> --copybook-dir <cpy_dir> \
    --llm-guided --llm-provider openrouter
```

No dependencies beyond Python 3.9+ stdlib for core functionality. Optional: `z3-solver` for concolic engine, LLM provider env vars for `--llm-guided`.

## Architecture

### Core Pipeline

**JSON AST → parse → extract variables → generate Python code → strategy-based coverage loop**

### Pipeline Modules

- **`ast_parser.py`** — Deserializes JSON AST dicts into `Program`/`Paragraph`/`Statement` dataclasses. Entry: `parse_ast(source)` accepts a file path or dict.

- **`models.py`** — Core dataclasses: `Program` (top-level, has `paragraphs` list and `paragraph_index` dict), `Paragraph` (named, contains `Statement` list), `Statement` (recursive tree via `children`, has `type`, `text`, `attributes`).

- **`variable_extractor.py`** — Walks the AST to discover all COBOL variables. Classifies each as `input`, `internal`, `status`, or `flag` based on naming conventions and access patterns (read-before-write = input). Harvests condition literals from IF comparisons (via `_harvest_condition_literals`) and from EVALUATE WHEN clauses (via `_harvest_evaluate_when_literals` — walks every single-subject `EVALUATE … WHEN 'LIT' …` and seeds the subject variable's `condition_literals` with each literal). Produces a `VariableReport`.

- **`code_generator.py`** — Converts each `Paragraph` into a Python function (`para_XXXX(state)`) and each `Statement` into Python code. All COBOL state lives in a single `state` dict. Generated code includes runtime helpers (`_SafeDict`, `_InstrumentedState`, `_GobackSignal`, `_to_num`, `_apply_stub_outcome`, stubs for CALL/EXEC). Branch instrumentation emits `+bid`/`-bid` for every IF/EVALUATE/PERFORM UNTIL; module-level `_BRANCH_META` maps IDs to metadata.

- **`condition_parser.py`** — Recursive descent parser that converts COBOL condition strings to Python expressions. Handles comparisons, figurative constants (SPACES, ZEROS, etc.), DFHRESP codes, IS NUMERIC, multi-value OR, and logical AND/OR/NOT.

- **`static_analysis.py`** — Call graph construction from PERFORM/GO_TO edges, gating condition extraction per paragraph, path constraint computation, sequential gate detection, equality constraint extraction.

- **`variable_domain.py`** — Unified domain model bridging PIC clauses (from copybooks), AST condition analysis, stub mappings, and naming heuristics. Six value generation strategies: condition_literal, 88_value, boundary, semantic, random_valid, adversarial. `build_variable_domains()` optionally takes `cobol_source` and scans the source for 88-level `VALUE` clauses on variables defined inline in the program (not in a copybook) via `_extract_88_values_from_source()`, so `valid_88_values` gets populated for internal variables like `APPL-RESULT` whose 88-level children gate downstream branches. In current coverage flows, `semantic` is funneled through `jit_value_inference.py`; `generate_value()` is the deterministic fallback.

### Coverage Engine

- **`coverage_strategies.py`** — Pluggable strategies for the agentic loop. Each yields `(input_state, stubs, defaults, target)` tuples. Current strategies: `BaselineStrategy` (priority 20, three phases: cross-strategy fan-out, per-input-var `condition_literal` fan-out, **per-88-level-value fan-out for any variable with 88-level children regardless of classification**), `DirectParagraphStrategy` (priority 35, 7-phase rotation: param hill-climb → stub sweep → dataflow backprop → frontier → harvest rainbow table → inverse synthesis → LLM gap), `TranscriptSearchStrategy` (priority 40), `CorpusFuzzStrategy` (priority 45, AFL-inspired energy + greedy set cover), `FaultInjectionStrategy` (priority 50, enumerates the full GnuCOBOL file-status / SQL / CICS / DLI / MQ / CALL-return-code tables; re-entrant per `preferred_target_key` and filters op keys through the target's backward-slice allowlist). All semantic value generation funnels through `_generate_domain_value(...)`, which consults the JIT service with the active per-target allowlist. The runtime `injectable_vars` filter in `cobol_coverage.py` passes any variable that carries `condition_literals` or `valid_88_values` — classification is no longer a gating constraint, so internal variables seeded by Phase 3 above actually land their values at runtime.

- **`cobol_coverage.py`** — Agentic loop orchestrator. `run_cobol_coverage()` for GnuCOBOL hybrid mode, `run_coverage()` for Python-only. Builds shared `JITValueInferenceService` and per-target variable allowlists via `_build_target_variable_allowlists()`. `HeuristicSelector` picks strategies by `priority - yield_bonus + staleness_penalty` with adaptive batch sizing. Memory-guided persistence is layered in via `memory_store` (run-local memory directory derived from test-store stem).

- **`backward_slicer.py`** — Extracts minimal code slices from generated Python paragraphs leading to specific branch probes. `backward_slice()` produces full slices for LLM steering; `slice_variable_names()` returns just the variable name set used by `_build_target_variable_allowlists` to seed per-target JIT scope.

- **`jit_value_inference.py`** — Shared on-demand LLM semantic-value inference. `JITValueInferenceService.infer_profile()` is two-layer-gated: skipped if `target_paragraph` is missing (when `require_target_paragraph_context` is True) or if `var_name` is outside the per-target `allowed_variables` allowlist. Cache keyed by SHA-256 of inputs, optional disk persistence. Reuses `SemanticProfile`/`generate_value_from_profile` from `llm_fuzzer.py`.

- **`branch_instrumenter.py`** — Post-compilation `@@B:` branch probes. `instrument_branches()` first runs deterministic full-file branch tracing via `cobol_mock._add_branch_tracing()`, verifies with `cobc -fsyntax-only`, and only falls back to insertion-only LLM instrumentation if deterministic tracing fails syntax check. Idempotent (strips existing probes before reinstrumenting).

- **`program_analysis.py`** — Upfront static analysis producing structured JSON per paragraph (comments, calls, stub ops, gating conditions, branch count). No LLM calls. Used as input for LLM seed generation. Supports incremental caching for resume after interruption.

- **`coverage_bundle.py`** — Portable coverage bundle export/import. `export_bundle()` compiles COBOL, extracts all metadata, queries LLM for per-variable hints and business scenarios, packages as binary + `coverage-spec.yaml`. `run_bundle()` loads spec + binary and runs coverage without AST/source/copybooks. Spec format is YAML, human-editable.

- **`branch_swarm.py`** — Swarm + planner pipeline for stubborn uncovered branches. Combines 4 parallel specialist agents (Condition Cracker, Path Finder, Stub Architect, History Miner) with a hierarchical planner: deterministic Route Planner (BFS path + gating conditions), Python forward validation (~3 ms with per-gate diagnosis), Gate Solver (backward-chaining LLM refinement, only on Python failure), deterministic Tape Builder (`_python_pre_run` for execution-ordered stub_log), and direct COBOL execution (bypasses `_execute_and_save`). Writes `<store_stem>.swarm_failures.jsonl` with structured diagnostics for unsolved branches. Controlled by `SPECTER_BRANCH_SWARM=0` (falls back to `branch_agent.py`), `--agent-iterations N`, `--no-branch-agent`.

- **`branch_agent.py`** — Legacy single-agent fallback for stubborn branches. Focused multi-turn LLM investigation: gather context → propose → execute → feed back → repeat. Used when `SPECTER_BRANCH_SWARM=0`. Controlled by `--agent-iterations N`, `--no-branch-agent`, `SPECTER_BRANCH_AGENT=0`.

- **`compile_swarm.py`** — 3-specialist swarm for COBOL compilation fixes, invoked from `_compile_and_fix` when the challenger reviewer rejects the scribe's first proposal (instead of re-prompting the single scribe). Specialists run in parallel: **Syntax** (column boundaries, periods, reserved words), **Semantic** (preserve business logic, never comment out referenced code), **Structure** (data definitions, PIC clauses, 88-level condition-names → SET). Rule-based judge **hard-rejects** (-999 score) any proposal that takes the easy way out: commenting out an active line, replacing with CONTINUE/EXIT/NEXT, whitespace deletion, or unwanted GOBACK. Controlled by `SPECTER_COMPILE_SWARM=0`.

- **`uncovered_report.py`** — Post-run diagnostic report. Writes `<store_stem>.uncovered.json` + `.uncovered.md` next to the test store when `_run_agentic_loop` finishes. Per uncovered branch direction captures: condition text (scanned from `.mock.cbl`), source line, condition category (file_status / 88_level / compound / numeric / etc.), variable dependencies with their classification and literals, 88-level parent lookup, reconstructed attempt counts by strategy, the nearest-hit test case, and heuristic next-step hints. Disabled with `--uncovered-report off` or `SPECTER_UNCOVERED_REPORT=off`. Defensive: any internal failure is logged, never aborts the coverage loop.

- **`coverage_config.py`** — Pluggable strategy configuration. `CoverageConfig` supports explicit round sequences or selector-driven mode. `SeedConfig` for LLM seed generation parameters. `ValidationConfig` for auto-validation against COBOL. `JITLoggingConfig` controls JIT observability and `jit_scope_policy` (`all` / `target_gates_only` / `target_gates_plus_slice`). `load_config()` reads YAML (or JSON fallback).

- **`cobol_validate.py`** — Two-pass COBOL validation. `validate_store()` compiles COBOL once, runs each test case from a `.jsonl` store through the binary, outputs a `.validated.jsonl` with only confirmed coverage.

### GnuCOBOL Mock Framework

- **`incremental_mock.py`** — Main pipeline. `incremental_instrument()` runs 10 phases with compile-and-fix after each: (0) baseline → (1) COPY resolution → (2) mock infrastructure → (3) EXEC replacement → (4) I/O replacement → (5) CALL replacement → (6) paragraph tracing → (7) normalization → (8) compile-and-fix → (9) branch probes (delegated to `branch_instrumenter.py`). Phases 3–5 batch transformations (revert + one-by-one if >10 errors). `_compile_and_fix()` runs an LLM-driven sequential fix loop with batch mode for grouped errors, single-error mode for mixed types, and copy-resolution investigation mode (multi-turn cascade). Every LLM-proposed fix passes through a rule-based quality gate AND a scribe/challenger LLM review (`specter/llm_review.py`); on reviewer reject the scribe is re-prompted with the reviewer's reason up to `_LLM_REVIEW_MAX_REVISIONS = 3` times before the proposal is recorded as failed. On reviewer deadlock (post-revisions), `_compile_and_fix` escalates through `supervisor_channel.py`; a `patch` reply is applied and kept at error-count parity (teacher-authority bypass of the scribe's strict decrease gate), and `abort`/`restart` raise `SupervisorAbort`/`SupervisorRestart` (BaseException subclasses) so outer `except Exception` / `except RuntimeError` handlers cannot swallow them. Pre-Phase-3 errors inside `EXEC CICS`/`EXEC SQL`/`EXEC DLI` blocks are **deferred** by `_is_deferred_to_later_phase()` — the scribe is never asked to repair blocks that `_replace_exec_blocks` exists to transform. Hard phase gates: every phase calls `_assert_clean()` and raises `RuntimeError` if errors remain; the gate uses `_count_actionable_errors()` which subtracts both hardcoded deferrals and teacher-taught skip rules. Checkpoint/resume via `phase_checkpoint.json` (sub-checkpoint after transform but before compile-and-fix). Deterministic pre-fixes include long-line wrap, group-item PIC removal, missing periods, paragraph stubs, record stubs, file stubs, FILE STATUS definitions.

- **`llm_review.py`** — Scribe/challenger validation for LLM-proposed source modifications. `review_fix()` takes a proposed fix dict (`{line_number: new_content}`), the original source lines, and the error summary, then asks the LLM challenger (same provider as the scribe) to verify the fix is non-destructive against an explicit rubric (commenting out referenced lines, renaming undefined symbols, narrowing PIC clauses, mid-paragraph GOBACK/EXIT, replaced business statements, ...). Returns `ReviewVerdict(verdict, reason, severity, guidance)` with `verdict ∈ {accept, reject, unknown}`. The optional `guidance` field lets the challenger point the scribe at a specific location or approach for the next revision. Caller treats `unknown` (reviewer outage / parse failure) as a pass-through so reviewer issues never block the fix loop. Bypassed via `--no-llm-review` CLI flag or `SPECTER_LLM_REVIEW=0` env var.

- **`cobol_mock.py`** — Underlying transformation functions called by `incremental_mock.py`: `_resolve_copies`, `_replace_exec_blocks`, `_replace_io_verbs`, `_replace_call_stmts`, `_add_paragraph_tracing`, `_add_mock_infrastructure`, `_disable_original_selects`, `_convert_linkage`, `_fix_procedure_division`, `_add_common_stubs`, `_add_branch_tracing`. Coverage mode disables CICS RETURN/XCTL termination and sets EIBCALEN/EIBAID. Non-destructive fallback policy: no broad paragraph neutralization or hard-comment salvage; preserves original business logic unless an actual I/O block is being replaced.

- **`cobol_fix_cache.py`** — `llm_investigate_cascade()` multi-turn (up to 10) LLM investigation for cascade failures. LLM can request additional code chunks via `{"need_context": {"start": N, "end": M}}`. `_parse_llm_fix_response()` handles JSON, nested JSON, markdown code blocks, plain text.

- **`cobol_executor.py`** — Compile-once/run-many executor. `prepare_context()` calls `incremental_instrument()` and compiles. `run_test_case()` writes mock data → executes COBOL → parses SPECTER-TRACE/@@B: output. `run_batch()` for parallel execution via ProcessPoolExecutor. Coverage mode sets `stop_on_exec_return=False`, `eib_calen=100`, `eib_aid=X'7D'`.

### Supporting Modules

- **`test_store.py`** — JSONL-based persistent test case storage. Each TC has: `id`, `input_state`, `stub_outcomes`, `stub_defaults`, `paragraphs_covered`, `branches_covered`, `layer`, `target`. Append-only; survives interruption.

- **`monte_carlo.py`** — Randomized execution with domain-aware inputs. `_load_module()` dynamically loads generated `.py`. `_run_paragraph_directly()` for direct paragraph invocation. Guided semantic generation now uses the shared `JITValueInferenceService`; inferred profiles are also cached into the Monte Carlo semantic-profile store for reuse.

- **`copybook_parser.py`** — Parses COBOL copybooks into `CopybookRecord`/`CopybookField` with PIC type, length, precision, OCCURS, 88-level values. Also generates SQL DDL and Java DAO classes.

- **`llm_coverage.py`** — LLM provider abstraction. `_query_llm_sync()` with HTTP 401 retry/reconnect (single string or multi-turn `list[Message]`), `build_coverage_gaps()`, `generate_llm_suggestions()`. Uses `llm_providers` package with Protocol-based abstraction; supports Anthropic, OpenAI, OpenRouter.

- **`llm_fuzzer.py`** — Semantic-profile schema and adaptive mutation helpers. `SemanticProfile`, `_parse_semantic_profiles`, `generate_value_from_profile`, `apply_strategy_to_state` (now JIT-aware). Legacy `infer_variable_semantics()` retained but bypassed by current flows.

- **`llm_test_states.py`** — `extract_paragraph_comments(program, source_lines)` harvests nearby COBOL comments keyed by paragraph name; threaded into JIT prompts and `StrategyContext.paragraph_comments`.

- **`memory_models.py`** / **`memory_store.py`** / **`persistence_utils.py`** / **`run_manifest.py`** — Memory-guided persistence layer. `MemoryState` aggregates `SuccessState`, `FailureFragment`, `TargetStatus`, `StrategyStats`, `APIBudgetLedger`. `MemoryStore` writes atomically (`atomic_write_text`, `atomic_write_json`, `append_line_with_fsync`) into a run-local directory derived from the test-store stem (e.g. `tests.jsonl` → `tests_memory/`). `run_manifest.py` tracks source hash, copybook roots, and phase checkpoints in `.specter_run_manifest.json`.

- **`supervisor_channel.py`** — Teacher/student IPC for long-running jobs. Env-gated via `SPECTER_SUPERVISOR=<run_dir>` (no-op when unset). `SupervisorChannel.escalate()` appends a JSON event to `<run_dir>/escalations.jsonl` and blocks polling `<run_dir>/resolutions.jsonl` for a UUID-correlated reply; `.heartbeat()` writes to `status.jsonl`. Valid verdicts: `patch` (inline `{line: content}` fix), `skip` (abandon this error), `abort`/`restart` (raise `SupervisorAbort`/`SupervisorRestart` which inherit from `BaseException` so `except Exception`/`except RuntimeError` cannot silently retry them). Replies may carry durable fields: `save_rule` → appended to `teacher_rules.jsonl` as a `TeacherRule` (phase + `msg_contains` + optional `source_context_contains`); `finding` → appended to `teacher_findings.jsonl` for later operator review. `TeacherRulesStore.match()` is consulted by `_compile_and_fix` and `_count_actionable_errors` so a taught skip rule applies on the next compile without another escalation round-trip. Escalation payloads include `related_findings` (prior findings + rules summary) so the teacher sees history. `scripts/teach.sh` is a `tail -F` helper for watching events from a teacher session.

### Key Patterns

- Generated code uses a flat `state: dict` for all COBOL variables (uppercase keys like `'WS-STATUS'`). Internal bookkeeping keys are prefixed with `_` (`_display`, `_calls`, `_execs`, `_reads`, `_writes`, `_abended`, `_trace`, `_branches`, `_stub_log`).
- COBOL paragraphs become `para_UPPER_NAME(state)` functions. GOBACK/STOP RUN raise `_GobackSignal`.
- External operations are replaced with stubs that pop from `state['_stub_outcomes'][op_key]`. Each outcome is a list of `(variable, value)` pairs.
- Mock record format: 80-byte LINE SEQUENTIAL: op-key `PIC X(30)` + alpha-status `PIC X(20)` + num-status `PIC S9(09)` (9 bytes) + filler `PIC X(21)`.
- In COBOL hybrid mode, direct paragraph strategies run through Python (fast), full-program strategies run through COBOL binary. Python branch IDs prefixed with `py:` to avoid collision with COBOL `@@B:` IDs.
- End-to-end tests in `test_end_to_end.py` depend on external AST files (not in repo) and are auto-skipped when unavailable. Unit tests are self-contained.
- Coverage strategy pipeline is configurable via `--coverage-config` YAML. Two modes: explicit round sequences (strategy + batch_size per round) or selector-driven (list of strategies, heuristic picks). See `examples/coverage-config.yaml`.
- Portable bundles (`--export-bundle` / `--run-bundle`) decouple source analysis from coverage execution. Export bakes LLM intelligence into a `coverage-spec.yaml` that travels with the compiled binary.
- **88-level condition rewriting**: The code generator rewrites bare 88-level conditions (`IF APPL-AOK`) to parent-value checks (`_to_num(state['APPL-RESULT']) == 0`) when `cobol_source` is provided. The `level_88_map` is populated from copybook records and `_extract_88_values_from_source`. The `stub_mapping` also includes 88-level parent variables alongside children so `_build_success_stubs` generates entries that set both.
- **JIT scope restriction**: JIT LLM calls happen only when a concrete target paragraph is known AND the variable is within the per-target allowlist (gating vars ∪ backward-slice vars ∪ stub-return vars). This eliminates low-signal "Target paragraph: none" prompts and keeps semantic inference tightly coupled to the currently blocked coverage target.
- **Pre-Phase-3 error deferral**: `_is_deferred_to_later_phase(line, msg, src, phase)` recognizes `EXEC CICS/SQL/DLI` syntax errors in `copy_resolution` / `mock_infrastructure` and flags them as owned by Phase 3's `_replace_exec_blocks` transform. The fix loop drops them from its actionable set so the scribe is never asked to "repair" a block that will be transformed anyway, and `_assert_clean` lets them pass the phase gate. `_normalize_phase_token()` maps checkpoint-name aliases (e.g. `mock_infra_transformed` → `mock_infrastructure`) back to canonical phase tokens. Teacher-taught skip rules (`TeacherRulesStore`) extend this hardcoded set with patterns the student doesn't know about yet.
- **Teacher/student channel**: `SPECTER_SUPERVISOR=<run_dir>` enables a durable IPC loop. On reviewer deadlock, `_compile_and_fix` escalates to a watcher (typically a Claude Code session running `scripts/teach.sh`); verdicts are `patch`/`skip`/`abort`/`restart`/`retry_with`. Teacher `patch` replies are applied at error-count parity (not just strict decrease), `abort`/`restart` raise `BaseException` subclasses so they can't be retried away, and replies carrying `save_rule`/`finding` are persisted durably. Files written: `escalations.jsonl`, `resolutions.jsonl`, `status.jsonl`, `teacher_rules.jsonl`, `teacher_findings.jsonl`.
- `--debug` enables `logging.DEBUG` on the root logger for the coverage run, surfacing per-call JIT gate decisions and per-round strategy details.

### Important: Fixing Bugs

When bugs are found in generated output (Python, COBOL mock, Java), **always fix the generator**, never the generated code directly. The generated code is a product of the pipeline — fixing it directly will be overwritten on the next run and doesn't fix the root cause for other programs.

### Ralph Loops

The `ralph-loops/` directory contains structured iteration workflows (`.md` files) for improving coverage on specific programs. Each loop defines: target program, goal metrics, diagnostic steps, and fix strategies. Used with the Ralph Loop plugin for automated iteration.
