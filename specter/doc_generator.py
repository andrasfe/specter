"""Generate structured documentation from a test store + generated module.

Produces a Markdown report with:
- Program overview and coverage summary
- Execution flow examples (paragraph traces per test case)
- External interface specifications (SQL, file I/O, CALL, CICS mocks)
- Decision tables (branch conditions and triggering values)
- Variable value domains across all test cases
- Error path catalog
- Display output samples
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .monte_carlo import _load_module, _run_paragraph_directly
from .test_store import TestStore, TestCase, _build_run_state


def generate_docs(
    module_path: str | Path,
    store_path: str | Path,
    max_trace_examples: int = 10,
) -> str:
    """Generate Markdown documentation from test store + generated module.

    Args:
        module_path: Path to the generated Python module.
        store_path: Path to the JSONL test store.
        max_trace_examples: Max execution flow examples to include.

    Returns:
        Markdown string.
    """
    module = _load_module(module_path)
    test_cases, _progress = TestStore.load(store_path)

    if not test_cases:
        return "# No test cases found\n"

    branch_meta = getattr(module, "_BRANCH_META", {})

    sections = [
        _section_overview(test_cases, branch_meta, module),
        _section_execution_flows(module, test_cases, max_trace_examples),
        _section_external_interfaces(test_cases),
        _section_decision_tables(test_cases, branch_meta),
        _section_variable_domains(test_cases),
        _section_error_paths(module, test_cases),
        _section_display_output(module, test_cases),
    ]

    return "\n\n".join(sections) + "\n"


# ---------------------------------------------------------------------------
# Section generators
# ---------------------------------------------------------------------------

def _section_overview(
    test_cases: list[TestCase],
    branch_meta: dict,
    module,
) -> str:
    """Program overview and coverage summary."""
    all_paras: set[str] = set()
    all_branches: set[int] = set()
    for tc in test_cases:
        all_paras.update(tc.paragraphs_covered)
        all_branches.update(tc.branches_covered)

    total_branches = len(set(branch_meta.keys())) * 2  # pos + neg

    # Stub operations used
    all_ops: set[str] = set()
    for tc in test_cases:
        all_ops.update(tc.stub_outcomes.keys())

    # Layer breakdown
    layer_counts: Counter[int] = Counter()
    for tc in test_cases:
        layer_counts[tc.layer] += 1

    lines = [
        "# Program Dynamic Analysis Documentation",
        "",
        "## Overview",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Test cases | {len(test_cases)} |",
        f"| Paragraphs covered | {len(all_paras)} |",
        f"| Branch directions covered | {len(all_branches)}/{total_branches} |",
        f"| External operations | {len(all_ops)} |",
        "",
        "### Test Cases by Layer",
        "",
        "| Layer | Count | Description |",
        "|-------|-------|-------------|",
    ]
    layer_desc = {
        1: "All-success baseline",
        2: "Direct paragraph invocation",
        3: "Branch condition solving",
        4: "Stub outcome combinatorics",
        5: "Targeted mutation walks",
        25: "Frontier expansion",
    }
    for layer in sorted(layer_counts):
        desc = layer_desc.get(layer, "")
        lines.append(f"| {layer} | {layer_counts[layer]} | {desc} |")

    return "\n".join(lines)


def _section_execution_flows(
    module,
    test_cases: list[TestCase],
    max_examples: int,
) -> str:
    """Execution flow examples showing paragraph traces."""
    lines = [
        "## Execution Flow Examples",
        "",
        "Each example shows the paragraph-by-paragraph execution trace",
        "for a specific test case.",
        "",
    ]

    # Pick diverse examples: one from each layer, prioritizing high coverage
    seen_layers: set[int] = set()
    examples: list[TestCase] = []
    sorted_tcs = sorted(test_cases, key=lambda tc: len(tc.paragraphs_covered), reverse=True)
    for tc in sorted_tcs:
        if len(examples) >= max_examples:
            break
        if tc.layer not in seen_layers:
            seen_layers.add(tc.layer)
            examples.append(tc)

    # Fill remaining slots with highest-coverage TCs
    for tc in sorted_tcs:
        if len(examples) >= max_examples:
            break
        if tc not in examples:
            examples.append(tc)

    for i, tc in enumerate(examples, 1):
        trace = _replay_trace(module, tc)
        if not trace:
            trace = tc.paragraphs_covered

        lines.append(f"### Example {i}: Layer {tc.layer} — {tc.target}")
        lines.append("")
        lines.append(f"- **Paragraphs covered**: {len(tc.paragraphs_covered)}")
        lines.append(f"- **Branches covered**: {len(tc.branches_covered)}")
        lines.append("")

        # Show trace as numbered flow
        if trace:
            # Deduplicate consecutive duplicates for readability
            deduped = [trace[0]]
            for p in trace[1:]:
                if p != deduped[-1]:
                    deduped.append(p)

            if len(deduped) <= 30:
                lines.append("```")
                lines.append(" → ".join(deduped))
                lines.append("```")
            else:
                lines.append("```")
                for j in range(0, len(deduped), 10):
                    chunk = deduped[j:j + 10]
                    prefix = "  " if j > 0 else ""
                    suffix = " →" if j + 10 < len(deduped) else ""
                    lines.append(prefix + " → ".join(chunk) + suffix)
                lines.append("```")

        # Show key input values (non-default, non-empty)
        interesting_inputs = {
            k: v for k, v in tc.input_state.items()
            if v not in ("", " ", "TEST", None) and not k.startswith("_")
        }
        if interesting_inputs:
            lines.append("")
            lines.append("**Key inputs**:")
            lines.append("")
            shown = 0
            for var, val in sorted(interesting_inputs.items()):
                if shown >= 15:
                    lines.append(f"- ... and {len(interesting_inputs) - shown} more")
                    break
                lines.append(f"- `{var}` = `{val}`")
                shown += 1

        lines.append("")

    return "\n".join(lines)


def _section_external_interfaces(test_cases: list[TestCase]) -> str:
    """External interface specs: SQL, file I/O, CALL, CICS."""
    # Aggregate stub outcomes across all TCs
    op_values: dict[str, Counter] = defaultdict(Counter)
    op_queue_lengths: dict[str, list[int]] = defaultdict(list)

    for tc in test_cases:
        for op_key, queue in tc.stub_outcomes.items():
            op_queue_lengths[op_key].append(len(queue))
            for entry in queue:
                if isinstance(entry, list):
                    for pair in entry:
                        if isinstance(pair, (list, tuple)) and len(pair) == 2:
                            var, val = pair
                            op_values[op_key][(var, val)] += 1

    # Also collect from defaults
    for tc in test_cases:
        for op_key, default in tc.stub_defaults.items():
            if isinstance(default, list):
                for pair in default:
                    if isinstance(pair, (list, tuple)) and len(pair) == 2:
                        var, val = pair
                        op_values[op_key][(var, f"{val} (default)")] += 1

    lines = [
        "## External Interface Specifications",
        "",
        "Mock values observed across all test cases for each external operation.",
        "",
    ]

    # Group by operation type
    sql_ops = sorted(k for k in op_values if k == "SQL" or k.startswith("SQL:"))
    read_ops = sorted(k for k in op_values if k.startswith("READ:"))
    write_ops = sorted(k for k in op_values if k.startswith("WRITE:"))
    call_ops = sorted(k for k in op_values if k.startswith("CALL:"))
    cics_ops = sorted(k for k in op_values if k == "CICS" or k.startswith("CICS:"))
    open_ops = sorted(k for k in op_values if k.startswith("OPEN:"))
    close_ops = sorted(k for k in op_values if k.startswith("CLOSE:"))
    start_ops = sorted(k for k in op_values if k.startswith("START:"))
    other_ops = sorted(
        k for k in op_values
        if k not in sql_ops + read_ops + write_ops + call_ops + cics_ops
        + open_ops + close_ops + start_ops
    )

    def _format_op_group(title: str, ops: list[str]) -> list[str]:
        if not ops:
            return []
        result = [f"### {title}", ""]
        for op_key in ops:
            values = op_values[op_key]
            lengths = op_queue_lengths.get(op_key, [])
            avg_len = sum(lengths) / len(lengths) if lengths else 0
            max_len = max(lengths) if lengths else 0

            result.append(f"**`{op_key}`**")
            result.append("")
            if lengths:
                result.append(
                    f"- Queue depth: avg {avg_len:.0f}, max {max_len}"
                )

            # Group by status variable
            var_vals: dict[str, list[tuple]] = defaultdict(list)
            for (var, val), count in values.most_common():
                var_vals[var].append((val, count))

            result.append("")
            result.append("| Variable | Value | Occurrences |")
            result.append("|----------|-------|-------------|")
            for var in sorted(var_vals):
                for val, count in var_vals[var]:
                    result.append(f"| `{var}` | `{val}` | {count} |")
            result.append("")

        return result

    lines.extend(_format_op_group("SQL Operations", sql_ops))
    lines.extend(_format_op_group("File READ Operations", read_ops))
    lines.extend(_format_op_group("File WRITE Operations", write_ops))
    lines.extend(_format_op_group("File OPEN Operations", open_ops))
    lines.extend(_format_op_group("File CLOSE Operations", close_ops))
    lines.extend(_format_op_group("File START Operations", start_ops))
    lines.extend(_format_op_group("CALL Operations", call_ops))
    lines.extend(_format_op_group("CICS Operations", cics_ops))
    if other_ops:
        lines.extend(_format_op_group("Other Operations", other_ops))

    return "\n".join(lines)


def _section_decision_tables(
    test_cases: list[TestCase],
    branch_meta: dict,
) -> str:
    """Decision tables: for each branch condition, what values trigger each path."""
    lines = [
        "## Decision Tables",
        "",
        "Branch conditions and the input values that trigger each direction.",
        "",
    ]

    # Build: branch_id -> set of TC ids that cover it
    branch_to_tcs: dict[int, list[TestCase]] = defaultdict(list)
    for tc in test_cases:
        for bid in tc.branches_covered:
            branch_to_tcs[bid].append(tc)

    # Group branches by paragraph
    para_branches: dict[str, list[int]] = defaultdict(list)
    for abs_id, meta in sorted(branch_meta.items()):
        para = meta.get("paragraph", "")
        para_branches[para].append(abs_id)

    for para in sorted(para_branches):
        branch_ids = para_branches[para]
        if not branch_ids:
            continue

        lines.append(f"### {para}")
        lines.append("")
        lines.append("| Branch | Condition | True | False |")
        lines.append("|--------|-----------|------|-------|")

        for abs_id in branch_ids:
            meta = branch_meta[abs_id]
            cond = meta.get("condition", "?")
            btype = meta.get("type", "IF")

            true_count = len(branch_to_tcs.get(abs_id, []))
            false_count = len(branch_to_tcs.get(-abs_id, []))

            true_mark = f"✓ ({true_count})" if true_count else "✗"
            false_mark = f"✓ ({false_count})" if false_count else "✗"

            # Truncate long conditions
            if len(cond) > 60:
                cond = cond[:57] + "..."

            lines.append(
                f"| {abs_id} | `{cond}` | {true_mark} | {false_mark} |"
            )

        lines.append("")

        # For branches with both directions covered, show differentiating values
        for abs_id in branch_ids:
            true_tcs = branch_to_tcs.get(abs_id, [])
            false_tcs = branch_to_tcs.get(-abs_id, [])
            if not true_tcs or not false_tcs:
                continue

            meta = branch_meta[abs_id]
            cond = meta.get("condition", "")

            # Extract variables from condition
            cond_vars = set(re.findall(r'\b([A-Z][A-Z0-9_-]+)\b', cond))
            # Filter out keywords
            keywords = {
                "NOT", "AND", "OR", "EQUAL", "GREATER", "LESS", "THAN",
                "ZERO", "ZEROS", "ZEROES", "SPACES", "SPACE", "OTHER",
                "NUMERIC", "ALPHABETIC", "TRUE", "FALSE", "HIGH", "LOW",
                "VALUES", "DFHRESP", "NORMAL", "ERROR", "NOTFND",
            }
            cond_vars -= keywords

            if not cond_vars:
                continue

            # Show example values for true vs false
            lines.append(
                f"**Branch {abs_id}**: `{cond}`"
            )
            lines.append("")
            lines.append("| Variable | True example | False example |")
            lines.append("|----------|-------------|---------------|")

            true_tc = true_tcs[0]
            false_tc = false_tcs[0]
            for var in sorted(cond_vars):
                true_val = true_tc.input_state.get(var, "—")
                false_val = false_tc.input_state.get(var, "—")
                if true_val != false_val:
                    lines.append(f"| `{var}` | `{true_val}` | `{false_val}` |")

            lines.append("")

    return "\n".join(lines)


def _section_variable_domains(test_cases: list[TestCase]) -> str:
    """Variable value domains across all test cases."""
    lines = [
        "## Variable Value Domains",
        "",
        "Distinct values observed for each input variable across all test cases.",
        "Variables with only one value or default-like values are omitted.",
        "",
    ]

    # Collect all values per variable
    var_values: dict[str, Counter] = defaultdict(Counter)
    for tc in test_cases:
        for var, val in tc.input_state.items():
            if var.startswith("_"):
                continue
            var_values[var][repr(val)] += 1

    # Filter to interesting variables (more than 1 distinct value)
    interesting = {
        var: counts
        for var, counts in var_values.items()
        if len(counts) > 1
    }

    if not interesting:
        lines.append("All variables have uniform values across test cases.")
        return "\n".join(lines)

    # Sort by number of distinct values (most varied first)
    sorted_vars = sorted(
        interesting.items(),
        key=lambda x: len(x[1]),
        reverse=True,
    )

    lines.append(
        f"**{len(sorted_vars)}** variables have multiple distinct values "
        f"(out of {len(var_values)} total)."
    )
    lines.append("")

    lines.append("| Variable | Distinct Values | Most Common | All Values |")
    lines.append("|----------|----------------|-------------|------------|")

    for var, counts in sorted_vars:
        n_distinct = len(counts)
        most_common_val, most_common_count = counts.most_common(1)[0]

        # Format all values (cap at 8 for readability)
        all_vals = [v for v, _ in counts.most_common(8)]
        vals_str = ", ".join(all_vals)
        if n_distinct > 8:
            vals_str += f", ... (+{n_distinct - 8})"

        lines.append(
            f"| `{var}` | {n_distinct} | "
            f"{most_common_val} ({most_common_count}x) | "
            f"{vals_str} |"
        )

    return "\n".join(lines)


def _section_error_paths(module, test_cases: list[TestCase]) -> str:
    """Error path catalog: test cases that trigger error handling."""
    lines = [
        "## Error Path Catalog",
        "",
        "Test cases that exercise error handling paragraphs or produce",
        "error-related DISPLAY output.",
        "",
    ]

    error_tcs: list[tuple[TestCase, list[str], list[str]]] = []

    for tc in test_cases:
        # Check for error-related paragraphs
        error_paras = [
            p for p in tc.paragraphs_covered
            if any(kw in p.upper() for kw in ("ERROR", "ABEND", "ERR", "FATAL", "9999"))
        ]

        # Replay to check for error display output
        displays = _replay_displays(module, tc)
        error_displays = [
            d for d in displays
            if any(kw in d.upper() for kw in ("ERROR", "ABEND", "FATAL", "INVALID", "FAIL"))
        ]

        if error_paras or error_displays:
            error_tcs.append((tc, error_paras, error_displays))

    if not error_tcs:
        lines.append("No error paths detected in test cases.")
        return "\n".join(lines)

    lines.append(f"**{len(error_tcs)}** test cases exercise error paths.")
    lines.append("")

    for tc, error_paras, error_displays in error_tcs[:20]:
        lines.append(f"### TC `{tc.id}` (Layer {tc.layer}, target: {tc.target})")
        lines.append("")

        if error_paras:
            lines.append("**Error paragraphs hit:**")
            for p in error_paras:
                lines.append(f"- `{p}`")
            lines.append("")

        if error_displays:
            lines.append("**Error messages:**")
            for d in error_displays[:5]:
                lines.append(f"- `{d[:120]}`")
            lines.append("")

        # Show what stub failures caused this path
        error_stubs = {}
        for op_key, queue in tc.stub_outcomes.items():
            for entry in queue:
                if isinstance(entry, list):
                    for pair in entry:
                        if isinstance(pair, (list, tuple)) and len(pair) == 2:
                            var, val = pair
                            # Non-success values
                            if val not in (0, "0", "00", "0000", ""):
                                error_stubs.setdefault(op_key, []).append(
                                    (var, val)
                                )

        if error_stubs:
            lines.append("**Triggering stub values:**")
            for op_key, pairs in sorted(error_stubs.items())[:10]:
                unique_pairs = list(dict.fromkeys(
                    (v, val) for v, val in pairs
                ))[:3]
                vals = ", ".join(f"`{v}`=`{val}`" for v, val in unique_pairs)
                lines.append(f"- `{op_key}`: {vals}")
            lines.append("")

    if len(error_tcs) > 20:
        lines.append(f"... and {len(error_tcs) - 20} more error paths.")

    return "\n".join(lines)


def _section_display_output(module, test_cases: list[TestCase]) -> str:
    """Display output samples from test case execution."""
    lines = [
        "## Display Output Samples",
        "",
        "DISPLAY statements produced during test case execution,",
        "grouped by frequency.",
        "",
    ]

    all_displays: Counter[str] = Counter()
    display_by_para: dict[str, Counter[str]] = defaultdict(Counter)

    # Sample a subset of TCs for performance (replay is expensive)
    sample = test_cases[:50]
    for tc in sample:
        displays = _replay_displays(module, tc)
        for d in displays:
            truncated = d[:120]
            all_displays[truncated] += 1
            # Associate with first paragraph in trace
            if tc.paragraphs_covered:
                display_by_para[tc.paragraphs_covered[0]][truncated] += 1

    if not all_displays:
        lines.append("No DISPLAY output captured.")
        return "\n".join(lines)

    lines.append(f"Sampled from {len(sample)} test cases.")
    lines.append("")
    lines.append("| Message | Count |")
    lines.append("|---------|-------|")

    for msg, count in all_displays.most_common(50):
        # Escape pipe characters for markdown
        escaped = msg.replace("|", "\\|")
        lines.append(f"| `{escaped}` | {count} |")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Replay helpers
# ---------------------------------------------------------------------------

def _replay_trace(module, tc: TestCase) -> list[str]:
    """Replay a test case and return its paragraph trace."""
    try:
        state = _build_run_state(module, tc)
        if tc.target.startswith("direct:"):
            rest = tc.target[len("direct:"):]
            para_name = rest.split("|", 1)[0]
            rs = _run_paragraph_directly(module, para_name, state)
        else:
            rs = module.run(state)
        return rs.get("_trace", [])
    except Exception:
        return []


def _replay_displays(module, tc: TestCase) -> list[str]:
    """Replay a test case and return DISPLAY output."""
    try:
        state = _build_run_state(module, tc)
        if tc.target.startswith("direct:"):
            rest = tc.target[len("direct:"):]
            para_name = rest.split("|", 1)[0]
            rs = _run_paragraph_directly(module, para_name, state)
        else:
            rs = module.run(state)
        return [str(d) for d in rs.get("_display", [])]
    except Exception:
        return []
