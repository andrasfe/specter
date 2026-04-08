"""Backward slicer for generated Python code.

Given a target branch ID, extracts the minimal code slice from paragraph
entry to the branch — including only assignments that feed the branch
condition, enclosing control flow, and stub calls.

Designed for generated code from code_generator.py where:
- All state access is through state['VAR'] / state.get('VAR', default)
- Branch probes: state.get('_branches', set()).add(bid)
- Indentation is consistent (4 spaces per level)
"""

from __future__ import annotations

import re


# ---------------------------------------------------------------------------
# Regex patterns for generated code analysis
# ---------------------------------------------------------------------------

_BRANCH_ADD_RE = re.compile(r"\.add\((-?\d+)\)")
_STATE_WRITE_RE = re.compile(r"state\['([A-Z][A-Z0-9_-]*)'\]\s*=")
_STATE_READ_RE = re.compile(
    r"state(?:\['([A-Z][A-Z0-9_-]*)'\]|\.get\('([A-Z][A-Z0-9_-]*)')"
)
_EVAL_SUBJECT_RE = re.compile(r"_eval_subject\s*=\s*")
_EVAL_TAKEN_RE = re.compile(r"_eval_taken_\d+\s*=\s*")
_STUB_RE = re.compile(
    r"_apply_stub_outcome\(state,\s*'([^']+)'\)"
    r"|_dummy_call\('([^']+)'"
    r"|_dummy_exec\('([^']+)'"
)
_PARA_CALL_RE = re.compile(r"(para_[A-Z0-9_]+)\(state\)")
_FUNC_DEF_RE = re.compile(r"^def (para_[A-Z0-9_]+)\(state\):")
_IF_RE = re.compile(r"^\s*(if|elif|else)\b")
_WHILE_RE = re.compile(r"^\s*while\b")
_FOR_BID_RE = re.compile(r"for _bid in \[")
_BOILERPLATE_RE = re.compile(
    r"_d = state\.get\('_call_depth'|state\['_call_depth'\]|"
    r"if _d > _CALL_DEPTH|state\._enter_para|state\._exit_para|"
    r"^\s*try:\s*$|^\s*finally:\s*$|^\s*return\s*$"
)


def _indent_level(line: str) -> int:
    """Count leading spaces (generated code uses 4-space indentation)."""
    return len(line) - len(line.lstrip())


def _vars_read(line: str) -> set[str]:
    """Extract state variable names read on this line."""
    names: set[str] = set()
    for m in _STATE_READ_RE.finditer(line):
        names.add(m.group(1) or m.group(2))
    return names


def _vars_written(line: str) -> set[str]:
    """Extract state variable names written on this line."""
    return {m.group(1) for m in _STATE_WRITE_RE.finditer(line)}


def _branch_id(line: str) -> int | None:
    """Extract branch ID from a branch probe line, or None."""
    m = _BRANCH_ADD_RE.search(line)
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------------------
# Core slicer
# ---------------------------------------------------------------------------

def backward_slice(
    module_source: str,
    target_bid: int,
    max_lines: int = 80,
) -> str:
    """Extract a backward slice of generated code leading to a target branch.

    Args:
        module_source: Complete generated Python module source.
        target_bid: Branch ID to slice toward (positive or negative).
        max_lines: Maximum output lines.

    Returns:
        The sliced code as a string, or empty string if branch not found.
    """
    lines = module_source.splitlines()

    # Phase 1: Locate the target branch probe line
    target_line_idx, func_start, func_end = _find_branch_location(
        lines, target_bid,
    )
    if target_line_idx is None:
        return ""

    func_lines = lines[func_start:func_end + 1]
    target_offset = target_line_idx - func_start

    # Phase 2: Find the enclosing control flow path
    path_lines = _find_control_path(func_lines, target_offset)

    # Phase 3: Backward variable dependency slice
    condition_vars = _extract_condition_vars(func_lines, target_offset)
    dep_lines = _backward_trace(func_lines, target_offset, condition_vars)

    # Phase 4: Collect relevant stub and para calls
    stub_lines = _find_relevant_stubs(func_lines, target_offset, condition_vars)

    # Phase 5: Assemble the slice
    keep = set(path_lines) | set(dep_lines) | set(stub_lines)
    # Always keep the function def and docstring
    keep.add(0)
    if len(func_lines) > 1 and '"""' in func_lines[1]:
        keep.add(1)

    return _assemble_slice(func_lines, sorted(keep), target_offset, max_lines)


def _find_branch_location(
    lines: list[str], target_bid: int,
) -> tuple[int | None, int, int]:
    """Find the line containing the target branch probe.

    Returns (target_line_idx, func_start, func_end) or (None, 0, 0).
    """
    # Search for the branch probe
    target_pattern = f".add({target_bid})"
    target_line_idx = None

    for i, line in enumerate(lines):
        if target_pattern in line and "_branches" in line:
            target_line_idx = i
            break

    # For negative EVALUATE probes, search in the for-loop pattern
    if target_line_idx is None and target_bid < 0:
        abs_bid = abs(target_bid)
        for i, line in enumerate(lines):
            if f".add(-_bid)" in line:
                # Check the for loop above for our bid
                for j in range(max(0, i - 3), i):
                    if _FOR_BID_RE.search(lines[j]) and str(abs_bid) in lines[j]:
                        target_line_idx = i
                        break
                if target_line_idx is not None:
                    break

    if target_line_idx is None:
        return None, 0, 0

    # Find enclosing function
    func_start = target_line_idx
    while func_start > 0:
        if _FUNC_DEF_RE.match(lines[func_start]):
            break
        func_start -= 1

    func_end = target_line_idx
    while func_end < len(lines) - 1:
        func_end += 1
        if _FUNC_DEF_RE.match(lines[func_end]):
            func_end -= 1
            break
        # Stop at module-level code (no indentation)
        if lines[func_end].strip() and not lines[func_end].startswith(" "):
            func_end -= 1
            break

    return target_line_idx, func_start, func_end


def _find_control_path(
    func_lines: list[str], target_offset: int,
) -> list[int]:
    """Find the chain of enclosing if/elif/else/while blocks to the target."""
    path: list[int] = [target_offset]
    target_indent = _indent_level(func_lines[target_offset])

    current_indent = target_indent
    scan_from = target_offset

    while current_indent > 4:  # 4 = base indent inside function body
        # Walk backward to find the enclosing block header
        for i in range(scan_from - 1, -1, -1):
            line = func_lines[i]
            if not line.strip():
                continue
            il = _indent_level(line)
            stripped = line.strip()
            if il < current_indent and (
                _IF_RE.match(line)
                or _WHILE_RE.match(line)
                or _FOR_BID_RE.search(line)
                or stripped.startswith("try:")
            ):
                path.append(i)
                current_indent = il
                scan_from = i
                break
        else:
            break

    return path


def _extract_condition_vars(
    func_lines: list[str], target_offset: int,
) -> set[str]:
    """Extract variables from the condition that gates the target branch."""
    vars_: set[str] = set()

    # The condition is on the if/elif line just above or at the target's indent
    target_indent = _indent_level(func_lines[target_offset])
    for i in range(target_offset, max(-1, target_offset - 5), -1):
        line = func_lines[i]
        if _IF_RE.match(line) and _indent_level(line) == target_indent - 4:
            vars_.update(_vars_read(line))
            break
        if _IF_RE.match(line) and _indent_level(line) < target_indent:
            vars_.update(_vars_read(line))
            break

    # Also check for _eval_subject setup
    if not vars_:
        for i in range(target_offset, max(-1, target_offset - 20), -1):
            if _EVAL_SUBJECT_RE.search(func_lines[i]):
                vars_.update(_vars_read(func_lines[i]))
                break

    return vars_


def _backward_trace(
    func_lines: list[str],
    target_offset: int,
    seed_vars: set[str],
    max_depth: int = 4,
) -> list[int]:
    """Trace backward from target to find assignments feeding seed_vars."""
    relevant: list[int] = []
    frontier = set(seed_vars)
    visited_vars: set[str] = set()

    for depth in range(max_depth):
        if not frontier:
            break
        new_frontier: set[str] = set()
        for var in frontier:
            if var in visited_vars:
                continue
            visited_vars.add(var)
            # Scan backward from target for the most recent assignment
            for i in range(target_offset - 1, -1, -1):
                line = func_lines[i]
                written = _vars_written(line)
                if var in written:
                    relevant.append(i)
                    # Add RHS variables to the frontier for next depth
                    new_frontier.update(_vars_read(line) - visited_vars)
                    break
                # _eval_subject setup
                if _EVAL_SUBJECT_RE.search(line) and var.startswith("_eval"):
                    relevant.append(i)
                    new_frontier.update(_vars_read(line) - visited_vars)
                    break
        frontier = new_frontier

    return relevant


def _find_relevant_stubs(
    func_lines: list[str],
    target_offset: int,
    dep_vars: set[str],
) -> list[int]:
    """Find stub/exec calls between function entry and target that may affect deps."""
    relevant: list[int] = []
    for i in range(target_offset):
        line = func_lines[i]
        if _STUB_RE.search(line):
            relevant.append(i)
        elif _PARA_CALL_RE.search(line):
            # Include para calls that precede the branch (may set dep vars)
            relevant.append(i)
    return relevant


def _assemble_slice(
    func_lines: list[str],
    keep_indices: list[int],
    target_offset: int,
    max_lines: int,
) -> str:
    """Assemble kept lines into a readable slice with omission markers."""
    if not keep_indices:
        return ""

    # Always include the target branch line
    keep_set = set(keep_indices)
    keep_set.add(target_offset)

    # Also include lines immediately around kept lines for context
    expanded = set()
    for idx in keep_set:
        expanded.add(idx)
        # Include the if/elif/else line above a branch probe
        if idx > 0 and _branch_id(func_lines[idx]) is not None:
            for j in range(idx - 1, max(-1, idx - 3), -1):
                if _IF_RE.match(func_lines[j]) or func_lines[j].strip().startswith("else"):
                    expanded.add(j)
                    break

    keep_sorted = sorted(expanded)

    # Filter out boilerplate
    keep_sorted = [
        i for i in keep_sorted
        if not _BOILERPLATE_RE.search(func_lines[i].strip())
        or i == 0  # always keep function def
    ]

    # Build output with omission markers
    output: list[str] = []
    prev_idx = -1
    for idx in keep_sorted:
        if len(output) >= max_lines - 2:
            output.append("    # ... (truncated)")
            break
        if prev_idx >= 0 and idx - prev_idx > 1:
            gap = idx - prev_idx - 1
            # Check if the gap contains only boilerplate
            gap_has_content = any(
                func_lines[j].strip()
                and not _BOILERPLATE_RE.search(func_lines[j].strip())
                for j in range(prev_idx + 1, idx)
            )
            if gap_has_content and gap > 0:
                indent = " " * _indent_level(func_lines[idx])
                output.append(f"{indent}# ... ({gap} lines omitted)")

        line = func_lines[idx]
        # Mark the target branch
        if idx == target_offset:
            output.append(line + "  # <-- TARGET")
        else:
            output.append(line)
        prev_idx = idx

    return "\n".join(output)


def slice_variable_names(module_source: str, target_bid: int) -> set[str]:
    """Return state variable names relevant to a target branch backward slice."""
    lines = module_source.splitlines()
    target_line_idx, func_start, func_end = _find_branch_location(lines, target_bid)
    if target_line_idx is None:
        return set()

    func_lines = lines[func_start:func_end + 1]
    target_offset = target_line_idx - func_start

    path_lines = _find_control_path(func_lines, target_offset)
    condition_vars = _extract_condition_vars(func_lines, target_offset)
    dep_lines = _backward_trace(func_lines, target_offset, condition_vars)
    stub_lines = _find_relevant_stubs(func_lines, target_offset, condition_vars)

    keep = set(path_lines) | set(dep_lines) | set(stub_lines)
    keep.add(target_offset)

    vars_out: set[str] = set(condition_vars)
    for idx in keep:
        if idx < 0 or idx >= len(func_lines):
            continue
        line = func_lines[idx]
        vars_out.update(_vars_read(line))
        vars_out.update(_vars_written(line))

    return {v.upper() for v in vars_out if v}
