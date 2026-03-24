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

- **`variable_extractor.py`** — Walks the AST to discover all COBOL variables. Classifies each as `input`, `internal`, `status`, or `flag` based on naming conventions and access patterns (read-before-write = input). Harvests condition literals from IF/EVALUATE comparisons. Produces a `VariableReport`.

- **`code_generator.py`** — Converts each `Paragraph` into a Python function (`para_XXXX(state)`) and each `Statement` into Python code. All COBOL state lives in a single `state` dict. Generated code includes runtime helpers (`_GobackSignal`, `_to_num`, `_is_numeric`, stubs for CALL/EXEC). Branch instrumentation emits `+bid`/`-bid` for every IF/EVALUATE/PERFORM UNTIL.

- **`condition_parser.py`** — Recursive descent parser that converts COBOL condition strings to Python expressions. Handles comparisons, figurative constants (SPACES, ZEROS, etc.), DFHRESP codes, IS NUMERIC, multi-value OR, and logical AND/OR/NOT.

- **`static_analysis.py`** — Call graph construction from PERFORM/GO_TO edges, gating condition extraction per paragraph, path constraint computation, sequential gate detection, equality constraint extraction.

- **`variable_domain.py`** — Unified domain model bridging PIC clauses (from copybooks), AST condition analysis, stub mappings, and naming heuristics. Six value generation strategies: condition_literal, 88_value, boundary, semantic, random_valid, adversarial.

### Coverage Engine

- **`coverage_strategies.py`** — Pluggable strategies for the agentic loop. Each yields `(input_state, stubs, defaults, target)` tuples. Key strategies: `BaselineStrategy`, `DirectParagraphStrategy` (7-phase rotation: param hill-climb → stub sweep → dataflow backprop → frontier → harvest rainbow table → inverse synthesis → LLM gap), `FaultInjectionStrategy`, `StubWalkStrategy`, `GuidedMutationStrategy`, `MonteCarloStrategy`. LLM strategies: `LLMSeedStrategy`, `IntentDrivenStrategy`, `LLMRuntimeSteeringStrategy`.

- **`cobol_coverage.py`** — Agentic loop orchestrator. `run_cobol_coverage()` for GnuCOBOL hybrid mode, `run_coverage()` for Python-only. `HeuristicSelector` picks strategies by priority with yield-based re-ranking and staleness penalties. `LLMSelector` periodically consults LLM for strategy decisions.

- **`backward_slicer.py`** — Extracts minimal code slices from generated Python paragraphs leading to specific branch probes. Used by `LLMRuntimeSteeringStrategy` to give the LLM focused code context for uncovered branches (variable dependencies, stub calls, conditions).

- **`program_analysis.py`** — Upfront static analysis producing structured JSON per paragraph (comments, calls, stub ops, gating conditions, branch count). No LLM calls. Used as input for LLM seed generation.

### GnuCOBOL Mock Framework

- **`cobol_mock.py`** — 13-phase COBOL source instrumentation: COPY resolution, EXEC/IO/CALL replacement with mock reads, paragraph tracing (`DISPLAY 'SPECTER-TRACE:<para>'`), branch tracing (`DISPLAY '@@B:<id>:<direction>'`), mock infrastructure, EIB stubs, auto-stub undefined symbols via cobc diagnostics, trace probe restoration. Coverage mode disables CICS RETURN/XCTL termination and sets EIBCALEN/EIBAID for deep CICS coverage. File I/O mocks propagate `FILE STATUS IS <var>` to the actual status variable.

- **`cobol_executor.py`** — Compile-once/run-many executor. `prepare_context()` instruments + compiles COBOL (with optional hardening fallback). `run_test_case()` writes mock data → executes COBOL → parses trace/branches. `run_batch()` for parallel execution via ProcessPoolExecutor. Coverage mode sets `stop_on_exec_return=False`, `eib_calen=100`, `eib_aid=X'7D'`.

### Supporting Modules

- **`test_store.py`** — JSONL-based persistent test case storage. Each TC has: `id`, `input_state`, `stub_outcomes`, `stub_defaults`, `paragraphs_covered`, `branches_covered`, `layer`, `target`. Append-only; survives interruption.

- **`monte_carlo.py`** — Randomized execution with domain-aware inputs. `_load_module()` dynamically loads generated `.py`. `_run_paragraph_directly()` for direct paragraph invocation.

- **`copybook_parser.py`** — Parses COBOL copybooks into `CopybookRecord`/`CopybookField` with PIC type, length, precision, OCCURS, 88-level values. Also generates SQL DDL and Java DAO classes.

- **`llm_coverage.py`** — LLM integration: `_query_llm_sync()` with HTTP 401 retry/reconnect, `build_coverage_gaps()`, `generate_llm_suggestions()`. Supports Anthropic, OpenAI, OpenRouter providers.

### Key Patterns

- Generated code uses a flat `state: dict` for all COBOL variables (uppercase keys like `'WS-STATUS'`). Internal bookkeeping keys are prefixed with `_` (`_display`, `_calls`, `_execs`, `_reads`, `_writes`, `_abended`, `_trace`, `_branches`, `_stub_log`).
- COBOL paragraphs become `para_UPPER_NAME(state)` functions. GOBACK/STOP RUN raise `_GobackSignal`.
- External operations are replaced with stubs that pop from `state['_stub_outcomes'][op_key]`. Each outcome is a list of `(variable, value)` pairs.
- Mock record format: 80-byte LINE SEQUENTIAL: op-key `PIC X(30)` + alpha-status `PIC X(20)` + num-status `PIC S9(09)` (9 bytes) + filler `PIC X(21)`.
- In COBOL hybrid mode, direct paragraph strategies run through Python (fast), full-program strategies run through COBOL binary. Python branch IDs prefixed with `py:` to avoid collision with COBOL `@@B:` IDs.
- End-to-end tests in `test_end_to_end.py` depend on external AST files (not in repo) and are auto-skipped when unavailable. Unit tests are self-contained.

### Ralph Loops

The `ralph-loops/` directory contains structured iteration workflows (`.md` files) for improving coverage on specific programs. Each loop defines: target program, goal metrics, diagnostic steps, and fix strategies. Used with the Ralph Loop plugin for automated iteration.
