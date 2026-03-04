# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

Specter is a COBOL AST-to-executable-Python code generator. It reads a JSON AST file (produced by an external COBOL parser) and generates a standalone Python module that simulates the COBOL program's execution. It also supports Monte Carlo analysis — running the generated code with randomized inputs to explore execution paths.

## Commands

```bash
# Run all tests
python3 -m pytest

# Run a single test file
python3 -m pytest tests/test_condition_parser.py

# Run a single test
python3 -m pytest tests/test_condition_parser.py::TestConditionParser::test_simple_equality

# Run the tool
python3 -m specter <ast_file.ast> [-o output.py] [--verify] [--monte-carlo N] [--seed S]
```

No dependencies beyond Python 3.10+ stdlib. No linter or formatter configured.

## Architecture

The pipeline flows: **JSON AST → parse → extract variables → generate Python code → (optionally) Monte Carlo**.

### Pipeline Modules

- **`ast_parser.py`** — Deserializes JSON AST dicts into `Program`/`Paragraph`/`Statement` dataclasses. Entry: `parse_ast(source)` accepts a file path or dict.

- **`models.py`** — Core dataclasses: `Program` (top-level, has `paragraphs` list and `paragraph_index` dict), `Paragraph` (named, contains `Statement` list), `Statement` (recursive tree via `children`, has `type`, `text`, `attributes`).

- **`variable_extractor.py`** — Walks the AST to discover all COBOL variables by analyzing statement types and text. Classifies each as `input`, `internal`, `status`, or `flag` based on naming conventions and access patterns (read-before-write = input). Produces a `VariableReport`.

- **`code_generator.py`** — The largest module. Converts each `Paragraph` into a Python function (`para_XXXX(state)`) and each `Statement` into Python code using `_CodeBuilder`. All COBOL state lives in a single `state` dict. Generated code includes runtime helpers (`_GobackSignal`, `_to_num`, `_is_numeric`, stubs for CALL/EXEC). The `run()` function is the generated entry point.

- **`condition_parser.py`** — Recursive descent parser that converts COBOL condition strings to Python expressions. Handles comparisons, figurative constants (SPACES, ZEROS, etc.), DFHRESP codes, IS NUMERIC, multi-value OR, and logical AND/OR/NOT.

- **`monte_carlo.py`** — Dynamically loads a generated `.py` module and runs it N times with randomized inputs. Generates domain-aware random values based on variable classification (status codes, flags, dates, amounts, etc.). Produces `MonteCarloReport`.

### Key Patterns

- Generated code uses a flat `state: dict` for all COBOL variables (uppercase keys like `'WS-STATUS'`). Internal bookkeeping keys are prefixed with `_` (`_display`, `_calls`, `_execs`, `_reads`, `_writes`, `_abended`).
- COBOL paragraphs become `para_UPPER_NAME(state)` functions. GOBACK/STOP RUN raise `_GobackSignal`.
- Each COBOL statement type has its own `_gen_<type>` function in `code_generator.py`. Unsupported statements emit `pass  # TYPE: ...` comments.
- End-to-end tests in `test_end_to_end.py` depend on external AST files (not in repo) and are auto-skipped when unavailable. Unit tests are self-contained and use inline AST dicts.
