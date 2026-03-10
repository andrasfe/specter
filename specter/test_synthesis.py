"""Layered test set synthesis engine.

Systematically analyzes every paragraph to determine the exact inputs,
SQL results, CICS responses, file I/O outcomes, and CALL return codes
needed to reach it.  Saves every coverage-expanding discovery to
persistent storage so progress is never lost.

**Resumability**: progress records (attempted targets, completed layers,
walked TC IDs) are persisted to the same JSONL store alongside test cases.
A resumed run loads them and skips all previously-attempted work.
"""

from __future__ import annotations

import hashlib
import logging
import random
import time
from dataclasses import dataclass, field
from itertools import product
from pathlib import Path

from .monte_carlo import (
    _generate_all_success_state,
    _generate_all_success_stubs,
    _generate_stub_defaults,
    _load_module,
    _run_paragraph_directly,
)
from .static_analysis import (
    GatingCondition,
    compute_path_constraints,
    _parse_condition_variables,
)
from .test_store import (
    TestCase, TestStore, StoreProgress,
    _build_run_state, _compute_id,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# PERFORM UNTIL analysis
# ---------------------------------------------------------------------------

@dataclass
class _LoopGate:
    """A PERFORM UNTIL condition that gates entry to loop-body paragraphs."""
    condition_text: str       # raw COBOL condition
    target_paras: list[str]   # paragraphs inside the loop body
    containing_para: str      # paragraph containing the PERFORM UNTIL
    variables: list[tuple[str, list, bool]]  # parsed (var, vals, negated)


def _extract_loop_gates(program, module=None) -> list[_LoopGate]:
    """Find all PERFORM UNTIL conditions from AST and generated code.

    These generate ``while not (cond):`` loops in the generated code.
    To enter the loop body, the condition must be FALSE at the start.
    """
    import inspect
    import re
    gates: list[_LoopGate] = []

    # 1. From AST: PERFORM/PERFORM_THRU with UNTIL conditions
    for para in program.paragraphs:
        for stmt in para.statements:
            _find_loop_gates_in(stmt, para.name, gates)

    # 2. From generated code: scan for 'while not (state[...]):' patterns
    #    to catch loops the AST analysis misses (e.g., top-level PROCEDURE loops)
    if module is not None:
        try:
            source = inspect.getsource(module)
        except (TypeError, OSError):
            source = ""

        # Pattern: while not (state['VAR']):  followed by para_XXX(state) calls
        _while_re = re.compile(
            r"while not \(state\['([A-Z][A-Z0-9_-]+)'\]\):\s*\n"
            r"((?:\s+para_([A-Z][A-Z0-9_]+)\(state\)\s*\n)+)",
        )
        # Also pattern for function context
        _func_re = re.compile(r"def (para_[A-Z][A-Z0-9_]+|run)\(")

        for m in _while_re.finditer(source):
            var_name = m.group(1)
            body = m.group(2)
            # Extract paragraph names from para_XXX(state) calls
            call_paras = re.findall(r"para_([A-Z][A-Z0-9_]+)\(state\)", body)
            # Convert from Python name back to paragraph name (_ -> -)
            target_paras = [p.replace("_", "-") for p in call_paras]

            # Find containing function
            containing = "run"
            for fm in _func_re.finditer(source[:m.start()]):
                containing = fm.group(1)
            if containing.startswith("para_"):
                containing = containing[5:].replace("_", "-")

            # The while not (var) loop means: UNTIL var is TRUE
            # To enter: var must be falsy
            gates.append(_LoopGate(
                condition_text=var_name,
                target_paras=target_paras,
                containing_para=containing,
                variables=[(var_name, [True], False)],
            ))

    return gates


def _find_loop_gates_in(stmt, para_name: str, gates: list[_LoopGate]):
    """Recursively search statements for PERFORM UNTIL patterns."""
    import re

    if stmt.type in ("PERFORM_THRU", "PERFORM", "PERFORM_INLINE"):
        condition = stmt.attributes.get("condition", "")
        if condition:
            target = stmt.attributes.get("target", "")
            thru = stmt.attributes.get("thru", "")

            # From text: THRU parsing
            if stmt.text:
                m_thru = re.search(
                    r"THRU\s+([A-Z][A-Z0-9-]*)", stmt.text, re.IGNORECASE,
                )
                if m_thru:
                    thru = m_thru.group(1).upper()

            target_paras = []
            if target:
                target_paras.append(target)
                # If thru, there are intermediate paragraphs too
                # (we don't enumerate them here; the target is enough)
                if thru and thru != target:
                    target_paras.append(thru)

            parsed = _parse_condition_variables(condition)
            if target_paras or parsed:
                gates.append(_LoopGate(
                    condition_text=condition,
                    target_paras=target_paras,
                    containing_para=para_name,
                    variables=parsed,
                ))

    for child in stmt.children:
        _find_loop_gates_in(child, para_name, gates)


def _apply_loop_gates(
    state: dict,
    loop_gates: list[_LoopGate],
    target_paras: set[str],
    var_report,
) -> dict:
    """Modify state so that PERFORM UNTIL conditions are FALSE at entry.

    For ``PERFORM X UNTIL cond``, the generated code is ``while not (cond):``.
    To enter the loop, ``cond`` must be false.  For each variable in
    the condition, set it to a value that makes the overall condition false.
    """
    state = dict(state)
    for lg in loop_gates:
        # Check if any of the loop's target paragraphs are what we want
        if not (set(lg.target_paras) & target_paras):
            continue

        for var, vals, neg in lg.variables:
            # The UNTIL condition must be FALSE to enter the loop.
            # So if the condition is "var = val" (neg=False), we need var != val.
            # If the condition is "NOT var = val" (neg=True), we need var = val.
            if not neg and vals:
                # Condition is "var = val"; need var != val to enter loop
                info = var_report.variables.get(var)
                literals = (info.condition_literals
                           if info and hasattr(info, "condition_literals") else [])
                candidates = [lit for lit in literals if lit not in vals]
                if candidates:
                    state[var] = candidates[0]
                elif vals == [True]:
                    state[var] = False
                elif isinstance(vals[0], (int, float)):
                    state[var] = 0 if vals[0] != 0 else 1
                elif isinstance(vals[0], str):
                    state[var] = "" if vals[0] != "" else "X"
                else:
                    state[var] = False
            elif neg and vals:
                # Condition is "NOT var = val"; need var = val to enter loop
                state[var] = vals[0]
    return state


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

@dataclass
class SynthesisReport:
    """Summary of a synthesis run."""

    total_test_cases: int = 0
    new_test_cases: int = 0
    covered_paras: int = 0
    total_paras: int = 0
    covered_branches: int = 0
    total_branches: int = 0
    layer_stats: dict[int, int] = field(default_factory=dict)  # layer -> new TCs
    skipped_layers: list[int] = field(default_factory=list)
    elapsed_seconds: float = 0.0

    def summary(self) -> str:
        lines = [
            "Test Set Synthesis Report",
            f"  Total test cases: {self.total_test_cases} ({self.new_test_cases} new)",
            f"  Paragraphs: {self.covered_paras}/{self.total_paras}",
            f"  Branches: {self.covered_branches}/{self.total_branches}",
            f"  Time: {self.elapsed_seconds:.1f}s",
            "",
            "  Per layer:",
        ]
        for layer in sorted(self.layer_stats):
            lines.append(f"    Layer {layer}: {self.layer_stats[layer]} new test cases")
        if self.skipped_layers:
            lines.append(f"  Skipped (complete from prior run): {self.skipped_layers}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Synthesis state
# ---------------------------------------------------------------------------

@dataclass
class SynthesisState:
    test_cases: list[TestCase] = field(default_factory=list)
    covered_paras: set[str] = field(default_factory=set)
    covered_branches: set[int] = field(default_factory=set)
    covered_edges: set[tuple] = field(default_factory=set)
    failed_targets: dict[str, int] = field(default_factory=dict)
    progress: StoreProgress = field(default_factory=StoreProgress)
    excluded_values: set = field(default_factory=set)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _filter_excluded(state: dict, excluded: set) -> None:
    """Remove excluded values from a state dict, replacing with safe alternatives."""
    if not excluded:
        return
    for key in list(state):
        if key.startswith("_"):
            continue
        val = state[key]
        # Normalize for comparison: check both raw value and string form
        if val in excluded or str(val) in excluded:
            # Replace with a type-appropriate non-excluded alternative
            if isinstance(val, bool):
                alt = not val
                state[key] = alt if alt not in excluded and str(alt) not in excluded else val
            elif isinstance(val, (int, float)):
                # Try 0, 1, -1 until one is not excluded
                for candidate in [0, 1, -1, 42, 99]:
                    if candidate not in excluded and str(candidate) not in excluded:
                        state[key] = candidate
                        break
            else:
                for candidate in ["", " ", "00", "A"]:
                    if candidate not in excluded and str(candidate) not in excluded:
                        state[key] = candidate
                        break


def _filter_excluded_stubs(stub_outcomes: dict, excluded: set) -> None:
    """Remove excluded values from stub outcome queues."""
    if not excluded:
        return
    for op_key, queue in stub_outcomes.items():
        for entry in queue:
            if isinstance(entry, list):
                for i, pair in enumerate(entry):
                    if isinstance(pair, (list, tuple)) and len(pair) == 2:
                        var, val = pair
                        if val in excluded or str(val) in excluded:
                            # Replace with type-appropriate alternative
                            if isinstance(val, (int, float)):
                                for cand in [0, 1, -1]:
                                    if cand not in excluded and str(cand) not in excluded:
                                        entry[i] = (var, cand) if isinstance(pair, tuple) else [var, cand]
                                        break
                            else:
                                for cand in ["", " ", "00"]:
                                    if cand not in excluded and str(cand) not in excluded:
                                        entry[i] = (var, cand) if isinstance(pair, tuple) else [var, cand]
                                        break


def _execute_and_collect(
    module, input_state: dict, stub_outcomes: dict, stub_defaults: dict,
) -> tuple[list[str], list[int], list[tuple]]:
    """Run module with given inputs, return (paras, branches, edges)."""
    default_state_fn = getattr(module, "_default_state", None)
    state = default_state_fn() if default_state_fn else {}
    state.update(input_state)

    if stub_outcomes:
        state["_stub_outcomes"] = {
            k: [entry if not isinstance(entry, list) else list(entry)
                for entry in v]
            for k, v in stub_outcomes.items()
        }
    if stub_defaults:
        state["_stub_defaults"] = dict(stub_defaults)

    try:
        rs = module.run(state)
    except Exception:
        return [], [], []

    trace = rs.get("_trace", [])
    branches = list(rs.get("_branches", set()))
    edges = []
    for j in range(len(trace) - 1):
        if trace[j] != trace[j + 1]:
            edges.append((trace[j], trace[j + 1]))
    return list(dict.fromkeys(trace)), branches, edges


def _execute_direct_and_collect(
    module, para_name: str, input_state: dict,
    stub_outcomes: dict, stub_defaults: dict,
) -> tuple[list[str], list[int], list[tuple]]:
    """Run a single paragraph directly, return (paras, branches, edges)."""
    run_state = dict(input_state)
    if stub_outcomes:
        run_state["_stub_outcomes"] = {
            k: [entry if not isinstance(entry, list) else list(entry)
                for entry in v]
            for k, v in stub_outcomes.items()
        }
    if stub_defaults:
        run_state["_stub_defaults"] = dict(stub_defaults)

    try:
        rs = _run_paragraph_directly(module, para_name, run_state)
    except Exception:
        return [], [], []

    if not rs:
        return [], [], []

    trace = rs.get("_trace", [para_name])
    branches = list(rs.get("_branches", set()))
    edges = []
    for j in range(len(trace) - 1):
        if trace[j] != trace[j + 1]:
            edges.append((trace[j], trace[j + 1]))
    return list(dict.fromkeys(trace)), branches, edges


def _execute_and_collect_full(
    module, input_state: dict, stub_outcomes: dict, stub_defaults: dict,
) -> tuple[list[str], list[int], list[tuple], dict]:
    """Like _execute_and_collect but also returns the full final state.

    The returned state can be inspected to understand what values variables
    had at the point execution stopped, enabling targeted fixes.
    """
    default_state_fn = getattr(module, "_default_state", None)
    state = default_state_fn() if default_state_fn else {}
    state.update(input_state)

    if stub_outcomes:
        state["_stub_outcomes"] = {
            k: [entry if not isinstance(entry, list) else list(entry)
                for entry in v]
            for k, v in stub_outcomes.items()
        }
    if stub_defaults:
        state["_stub_defaults"] = dict(stub_defaults)

    try:
        rs = module.run(state)
    except Exception:
        return [], [], [], {}

    trace = rs.get("_trace", [])
    branches = list(rs.get("_branches", set()))
    edges = []
    for j in range(len(trace) - 1):
        if trace[j] != trace[j + 1]:
            edges.append((trace[j], trace[j + 1]))
    return list(dict.fromkeys(trace)), branches, edges, rs


def _record_attempt(synth: SynthesisState, store_path: Path,
                    layer: int, target: str) -> None:
    """Persist that a target was attempted (hit or miss) so we skip it on resume."""
    synth.progress.attempted_targets.setdefault(layer, set()).add(target)
    TestStore.append_progress(store_path, {
        "_type": "attempt", "layer": layer, "target": target,
    })


def _was_attempted(synth: SynthesisState, layer: int, target: str) -> bool:
    """Check if a target was already attempted in a previous or current run."""
    return target in synth.progress.attempted_targets.get(layer, set())


def _record_layer_done(synth: SynthesisState, store_path: Path,
                       layer: int) -> None:
    """Mark a layer as fully completed."""
    synth.progress.completed_layers.add(layer)
    TestStore.append_progress(store_path, {
        "_type": "layer_done", "layer": layer,
    })


def _record_walked(synth: SynthesisState, store_path: Path,
                   tc_id: str) -> None:
    """Mark a TC as walked by layer 5."""
    synth.progress.walked_tc_ids.add(tc_id)
    TestStore.append_progress(store_path, {
        "_type": "walked", "tc_id": tc_id,
    })


def _maybe_save(
    synth: SynthesisState,
    store_path: Path,
    input_state: dict,
    stub_outcomes: dict,
    stub_defaults: dict,
    paras: list[str],
    branches: list[int],
    edges: list[tuple],
    layer: int,
    target: str,
) -> bool:
    """Save test case if it expands coverage. Returns True if saved."""
    # Apply exclusion filter before saving
    if synth.excluded_values:
        _filter_excluded(input_state, synth.excluded_values)
        _filter_excluded_stubs(stub_outcomes, synth.excluded_values)

    new_paras = set(paras) - synth.covered_paras
    new_branches = set(branches) - synth.covered_branches
    new_edges = set(edges) - synth.covered_edges

    if not new_paras and not new_branches and not new_edges:
        return False

    tc_id = _compute_id(input_state, stub_outcomes)
    # If same input/stubs but different target (e.g. direct invocation),
    # make the ID unique by incorporating the target.
    if any(tc.id == tc_id for tc in synth.test_cases):
        tc_id = _compute_id(
            {**input_state, "_target": target}, stub_outcomes
        )
        if any(tc.id == tc_id for tc in synth.test_cases):
            return False

    tc = TestCase(
        id=tc_id,
        input_state=input_state,
        stub_outcomes=stub_outcomes,
        stub_defaults=stub_defaults,
        paragraphs_covered=paras,
        branches_covered=branches,
        layer=layer,
        target=target,
    )
    TestStore.append(store_path, tc)
    synth.test_cases.append(tc)
    synth.covered_paras.update(paras)
    synth.covered_branches.update(branches)
    synth.covered_edges.update(edges)

    log.info(
        "Layer %d: saved TC for %s (+%d paras, +%d branches)",
        layer, target, len(new_paras), len(new_branches),
    )
    return True


def _time_exceeded(start: float, max_time: float | None) -> bool:
    if max_time is None:
        return False
    return (time.time() - start) > max_time


def _detect_truthiness_overrides(module) -> dict[str, object]:
    """Scan _BRANCH_META for bare truthiness conditions.

    For variables checked with bare ``if state['VAR']:`` (error flags),
    returns a dict setting them to falsy values.
    For variables checked with ``if not (state['VAR']):`` (status checks),
    returns a dict setting them to truthy values.

    This prevents the all-success state from using truthy defaults like
    "TEST" for error flag variables, which would trigger early termination.
    """
    import re
    overrides: dict[str, object] = {}
    branch_meta = getattr(module, "_BRANCH_META", {})

    for _bid, meta in branch_meta.items():
        cond = meta.get("condition", "").strip()
        if not cond:
            continue

        # Match bare variable: "SYM00007" or "NOT SYM00190"
        m = re.match(r"^(NOT\s+)?([A-Z][A-Z0-9_-]+)$", cond)
        if not m:
            continue

        negated = bool(m.group(1))
        var = m.group(2)

        if var == "OTHER":
            continue  # EVALUATE OTHER, not a variable

        if negated:
            # Condition is NOT VAR → branch fires when VAR is falsy.
            # For success, we want VAR truthy (skip the error branch).
            if var not in overrides:
                overrides[var] = "00"
        else:
            # Condition is VAR → branch fires when VAR is truthy.
            # For success, we want VAR falsy (skip the error branch).
            if var not in overrides:
                overrides[var] = ""

    return overrides


# ---------------------------------------------------------------------------
# Layer 1: All-Success Baseline
# ---------------------------------------------------------------------------

def _run_layer_1(
    module, program, var_report, equality_constraints, stub_mapping,
    synth: SynthesisState, store_path: Path,
    start_time: float, max_time: float | None,
) -> int:
    """Generate all-success baseline + deterministic variants."""
    new_count = 0

    loop_gates = _extract_loop_gates(program, module)
    all_loop_paras = set()
    for lg in loop_gates:
        all_loop_paras.update(lg.target_paras)

    # Base all-success state
    base_state = _generate_all_success_state(var_report, equality_constraints)

    # Override bare-truthiness variables: error flags → falsy, status vars → truthy
    truthiness_overrides = _detect_truthiness_overrides(module)
    if truthiness_overrides:
        log.info("Layer 1: applying %d truthiness overrides", len(truthiness_overrides))
        base_state.update(truthiness_overrides)

    base_stubs = (
        _generate_all_success_stubs(stub_mapping, var_report)
        if stub_mapping else {}
    )
    base_defaults = (
        _generate_stub_defaults(stub_mapping, var_report)
        if stub_mapping else {}
    )

    target = "all-success"
    if not _was_attempted(synth, 1, target):
        paras, branches, edges = _execute_and_collect(
            module, base_state, base_stubs, base_defaults,
        )
        if _maybe_save(synth, store_path, base_state, base_stubs, base_defaults,
                       paras, branches, edges, layer=1, target=target):
            new_count += 1
        _record_attempt(synth, store_path, 1, target)

    # Try with loop gates applied (enter PERFORM UNTIL loops)
    if loop_gates:
        target = "all-success-loops"
        if not _was_attempted(synth, 1, target):
            loop_state = _apply_loop_gates(
                base_state, loop_gates, all_loop_paras, var_report,
            )
            paras, branches, edges = _execute_and_collect(
                module, loop_state, base_stubs, base_defaults,
            )
            if _maybe_save(synth, store_path, loop_state, base_stubs, base_defaults,
                           paras, branches, edges, layer=1, target=target):
                new_count += 1
            _record_attempt(synth, store_path, 1, target)

    # Try with reduced READ/START stub counts to handle programs where
    # later reads MUST return EOF (e.g., inverted AT END / NOT AT END checks).
    # Multiple read counts to find the sweet spot.
    if stub_mapping:
        for read_count in [20, 50, 100]:
            if _time_exceeded(start_time, max_time):
                break
            target = f"all-success-reads{read_count}"
            if _was_attempted(synth, 1, target):
                continue

            reduced_stubs = {}
            for op_key, entries in base_stubs.items():
                if op_key.startswith("READ:") or op_key.startswith("START:"):
                    # Keep first `read_count` success entries + 1 EOF
                    reduced_stubs[op_key] = entries[:read_count] + entries[-1:]
                else:
                    reduced_stubs[op_key] = list(entries)

            paras, branches, edges = _execute_and_collect(
                module, base_state, reduced_stubs, base_defaults,
            )
            if _maybe_save(synth, store_path, base_state, reduced_stubs, base_defaults,
                           paras, branches, edges, layer=1, target=target):
                new_count += 1
            _record_attempt(synth, store_path, 1, target)

    # Generate 3-5 variants with different non-status input values
    for variant_idx in range(5):
        if _time_exceeded(start_time, max_time):
            break

        target = f"variant-{variant_idx}"
        if _was_attempted(synth, 1, target):
            continue

        variant_state = dict(base_state)
        changed = False
        for name, info in var_report.variables.items():
            if info.classification in ("status", "flag"):
                continue
            literals = info.condition_literals if hasattr(info, "condition_literals") else []
            if literals and variant_idx < len(literals):
                variant_state[name] = literals[variant_idx]
                changed = True
            elif literals:
                variant_state[name] = literals[variant_idx % len(literals)]
                changed = True

        if not changed:
            _record_attempt(synth, store_path, 1, target)
            continue

        paras, branches, edges = _execute_and_collect(
            module, variant_state, base_stubs, base_defaults,
        )
        if _maybe_save(synth, store_path, variant_state, base_stubs, base_defaults,
                       paras, branches, edges, layer=1, target=target):
            new_count += 1
        _record_attempt(synth, store_path, 1, target)

    _record_layer_done(synth, store_path, 1)
    return new_count


# ---------------------------------------------------------------------------
# Layer 2: Path-Constraint Satisfaction
# ---------------------------------------------------------------------------

def _find_best_base(synth: SynthesisState, path: list[str]) -> TestCase | None:
    """Find test case with longest prefix overlap with a target path."""
    best = None
    best_overlap = -1
    path_set = set(path)

    for tc in synth.test_cases:
        overlap = len(set(tc.paragraphs_covered) & path_set)
        if overlap > best_overlap:
            best_overlap = overlap
            best = tc

    return best


def _find_top_bases(synth: SynthesisState, path: list[str], n: int) -> list[TestCase]:
    """Find top-n test cases with best overlap with the target path."""
    path_set = set(path)
    scored = []
    for tc in synth.test_cases:
        overlap = len(set(tc.paragraphs_covered) & path_set)
        scored.append((overlap, tc))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [tc for _, tc in scored[:n]]


def _apply_gating_constraints(
    state: dict,
    constraints: list[GatingCondition],
    var_report,
    variation: int = 0,
) -> dict:
    """Apply gating constraints deterministically to a state.

    *variation* selects alternative satisfying values when available:
    0 = first literal, 1 = second, etc.  This enables generating
    multiple distinct states for the same set of constraints.
    """
    state = dict(state)
    for gc in constraints:
        if not gc.negated and gc.values:
            # Set var to a satisfying value (cycle through available values)
            if gc.values == [True]:
                # Bare boolean flag — try various truthy representations
                _truthy = [True, "Y", "1", 1]
                state[gc.variable] = _truthy[variation % len(_truthy)]
            else:
                state[gc.variable] = gc.values[variation % len(gc.values)]
        elif gc.negated and gc.values:
            if gc.values == [True]:
                # Bare boolean negated — try various falsy representations
                _falsy = [False, "N", "0", 0, "", " "]
                state[gc.variable] = _falsy[variation % len(_falsy)]
            else:
                # Pick condition_literal NOT in the negated values
                info = var_report.variables.get(gc.variable)
                literals = (info.condition_literals if info and hasattr(info, "condition_literals")
                           else [])
                candidates = [lit for lit in literals if lit not in gc.values]
                if candidates:
                    state[gc.variable] = candidates[variation % len(candidates)]
                else:
                    # Use a sentinel that's different from the gated values
                    if isinstance(gc.values[0], int):
                        state[gc.variable] = gc.values[0] + 999 + variation
                    elif isinstance(gc.values[0], str):
                        state[gc.variable] = f"X{variation}" if variation else "XX"
                    else:
                        state[gc.variable] = f"X{variation}" if variation else "XX"
    return state


def _run_layer_2(
    module, program, var_report, call_graph, gating_conditions,
    stub_mapping, equality_constraints,
    synth: SynthesisState, store_path: Path,
    start_time: float, max_time: float | None,
) -> int:
    """For each uncovered paragraph, solve the full path of gating conditions.

    Runs iteratively: when new paragraphs are covered, re-evaluates paths
    since newly-covered paragraphs may be stepping stones.  Tries multiple
    constraint variations and multiple base test cases per target.
    """
    new_count = 0
    all_paras = {p.name for p in program.paragraphs}
    N_VARIATIONS = 6   # constraint value variations to try
    N_BASES = 3        # base TCs to try per target
    MAX_ROUNDS = 5     # max iterative rounds for path constraints

    base_defaults = (
        _generate_stub_defaults(stub_mapping, var_report)
        if stub_mapping else {}
    )

    # Extract loop gates for PERFORM UNTIL handling
    loop_gates = _extract_loop_gates(program, module)

    # Truthiness overrides for direct invocation
    truthiness_overrides = _detect_truthiness_overrides(module)

    # ---- PHASE 1: Direct invocation (fast, covers most paragraphs) ----
    # For ALL uncovered paragraphs, try running directly with proper stubs.
    # Many programs have most paragraphs only reachable via PERFORM from the
    # main flow, or in sequential fall-through after a GobackSignal.  Direct
    # invocation with good stubs is the most reliable way to cover them.
    still_uncovered = all_paras - synth.covered_paras
    for para in sorted(still_uncovered):
        if _time_exceeded(start_time, max_time):
            break

        direct_target = f"direct:{para}"
        if _was_attempted(synth, 2, direct_target):
            continue

        # Build a good state with all-success stubs
        direct_state = _generate_all_success_state(var_report, equality_constraints)
        if truthiness_overrides:
            direct_state.update(truthiness_overrides)

        direct_stubs = (
            _generate_all_success_stubs(stub_mapping, var_report)
            if stub_mapping else {}
        )

        # Try with: (1) fresh all-success state + stubs,
        #           (2) best existing TC states + stubs
        attempts = [(direct_state, direct_stubs)]
        for tc in synth.test_cases[:3]:
            tc_state = dict(tc.input_state)
            tc_stubs = dict(tc.stub_outcomes) if tc.stub_outcomes else dict(direct_stubs)
            attempts.append((tc_state, tc_stubs))

        for try_state, try_stubs in attempts:
            if _time_exceeded(start_time, max_time):
                break
            try:
                run_s = dict(try_state)
                if try_stubs:
                    run_s["_stub_outcomes"] = {
                        k: [e if not isinstance(e, list) else list(e)
                            for e in v]
                        for k, v in try_stubs.items()
                    }
                if base_defaults:
                    run_s["_stub_defaults"] = dict(base_defaults)
                rs = _run_paragraph_directly(module, para, run_s)
                trace = rs.get("_trace", [para])
                branches_r = list(rs.get("_branches", set()))
                paras_list = list(dict.fromkeys(trace)) if trace else [para]
                edges_list = [
                    (trace[j], trace[j + 1])
                    for j in range(len(trace) - 1)
                    if trace[j] != trace[j + 1]
                ] if trace else []
                if _maybe_save(synth, store_path, try_state, try_stubs, base_defaults,
                               paras_list, branches_r, edges_list,
                               layer=2, target=direct_target):
                    new_count += 1
                    break
            except Exception:
                pass
        _record_attempt(synth, store_path, 2, direct_target)

    _record_layer_done(synth, store_path, 2)
    return new_count


# ---------------------------------------------------------------------------
# Layer 2.5: Frontier Expansion (trace-based constraint discovery)
# ---------------------------------------------------------------------------

def _find_frontier_branches(
    synth: SynthesisState,
    call_graph,
    branch_meta: dict,
) -> list[tuple[int, str, str]]:
    """Find branches in covered paragraphs that gate uncovered paragraphs.

    Returns list of (branch_id, branch_paragraph, target_paragraph) where
    flipping the branch might unlock the target paragraph.
    """
    frontier = []
    for covered_para in synth.covered_paras:
        # What does this paragraph call?
        callees = call_graph.edges.get(covered_para, set())
        for callee in callees:
            if callee not in synth.covered_paras:
                # callee is uncovered — find branches in covered_para
                # that gate the PERFORM to callee
                for abs_id, meta in branch_meta.items():
                    if meta.get("paragraph", "") == covered_para:
                        for bid in (abs_id, -abs_id):
                            if bid not in synth.covered_branches:
                                frontier.append((bid, covered_para, callee))
    return frontier


def _run_layer_2_5(
    module, program, var_report, call_graph, gating_conditions,
    stub_mapping, equality_constraints,
    synth: SynthesisState, store_path: Path,
    start_time: float, max_time: float | None,
) -> int:
    """Frontier expansion: flip branches in covered paragraphs that gate
    uncovered callees.

    For each existing test case that reaches a frontier paragraph, run it
    and inspect the final state.  Use branch metadata to identify which
    condition blocked entry to uncovered callees, then construct a state
    that flips that condition.
    """
    new_count = 0
    branch_meta = getattr(module, "_BRANCH_META", {})
    if not branch_meta:
        return 0

    base_defaults = (
        _generate_stub_defaults(stub_mapping, var_report)
        if stub_mapping else {}
    )

    MAX_ROUNDS = 5
    for round_num in range(MAX_ROUNDS):
        if _time_exceeded(start_time, max_time):
            break

        frontier = _find_frontier_branches(synth, call_graph, branch_meta)
        if not frontier:
            break

        round_new = 0
        # Group by branch to avoid duplicate work
        seen_branches = set()
        for bid, bpara, target_para in frontier:
            if _time_exceeded(start_time, max_time):
                break
            if bid in seen_branches:
                continue
            seen_branches.add(bid)

            target_key = f"frontier:{bid}→{target_para}"
            if _was_attempted(synth, 25, target_key):  # layer 2.5
                continue

            abs_id = abs(bid)
            meta = branch_meta.get(abs_id, {})
            condition = meta.get("condition", "")

            # Find TCs that reach this paragraph
            relevant_tcs = [
                tc for tc in synth.test_cases
                if bpara in tc.paragraphs_covered
            ]
            if not relevant_tcs:
                _record_attempt(synth, store_path, 25, target_key)
                continue

            negate = bid < 0

            for tc in relevant_tcs[:3]:  # try top 3
                if _time_exceeded(start_time, max_time):
                    break
                if target_para in synth.covered_paras:
                    break

                # Run TC and inspect final state
                paras_now, branches_now, edges_now, final_state = (
                    _execute_and_collect_full(
                        module, tc.input_state,
                        tc.stub_outcomes or {},
                        tc.stub_defaults or base_defaults,
                    )
                )

                # The branch wasn't taken in the direction we want.
                # Parse condition to find what variables to change.
                if not condition:
                    continue

                parsed = _parse_condition_variables(condition)
                if not parsed:
                    continue

                # Build a modified state that flips the condition
                state = dict(tc.input_state)
                stubs = dict(tc.stub_outcomes) if tc.stub_outcomes else {}

                for var, vals, neg in parsed:
                    effective_neg = neg != negate
                    current_val = final_state.get(var)

                    if not effective_neg and vals:
                        # Need var to satisfy condition
                        if vals == [True]:
                            # Bare boolean — need truthy
                            state[var] = True
                        else:
                            state[var] = vals[0]
                    elif effective_neg and vals:
                        # Need var to NOT satisfy condition
                        if vals == [True]:
                            # Bare boolean — need falsy
                            state[var] = False
                        elif current_val in vals or current_val is None:
                            info = var_report.variables.get(var)
                            literals = (info.condition_literals
                                       if info and hasattr(info, "condition_literals")
                                       else [])
                            found_alt = False
                            for lit in literals:
                                if lit not in vals:
                                    state[var] = lit
                                    found_alt = True
                                    break
                            if not found_alt:
                                if isinstance(vals[0], (int, float)):
                                    state[var] = vals[0] + 999
                                else:
                                    state[var] = "XX"

                    # Also check if var is a stub-controlled variable
                    if stub_mapping:
                        for op_key, svars in stub_mapping.items():
                            if var in svars:
                                target_val = vals[0] if (not effective_neg and vals) else None
                                if target_val is None and vals:
                                    # Need != vals, pick something else
                                    info = var_report.variables.get(var)
                                    literals = (info.condition_literals
                                               if info and hasattr(info, "condition_literals")
                                               else [])
                                    for lit in literals:
                                        if lit not in vals:
                                            target_val = lit
                                            break
                                if target_val is not None:
                                    stubs[op_key] = [[(var, target_val)]] * 50

                p2, b2, e2 = _execute_and_collect(
                    module, state, stubs, base_defaults,
                )
                if _maybe_save(synth, store_path, state, stubs, base_defaults,
                               p2, b2, e2, layer=2, target=target_key):
                    new_count += 1
                    round_new += 1

            _record_attempt(synth, store_path, 25, target_key)

        if round_new == 0:
            break
        log.info("Layer 2.5 round %d: %d new TCs, covered %d/%d paras",
                 round_num + 1, round_new,
                 len(synth.covered_paras), len({p.name for p in program.paragraphs}))

    return new_count


# ---------------------------------------------------------------------------
# Layer 3: Branch-Level Solving
# ---------------------------------------------------------------------------

def _run_layer_3(
    module, var_report, stub_mapping,
    synth: SynthesisState, store_path: Path,
    start_time: float, max_time: float | None,
) -> int:
    """For each uncovered branch in reached paragraphs, find inputs that flip it.

    Uses direct paragraph invocation for branches in paragraphs that are
    only reachable that way.
    """
    new_count = 0

    branch_meta = getattr(module, "_BRANCH_META", {})
    if not branch_meta:
        return 0

    base_defaults = (
        _generate_stub_defaults(stub_mapping, var_report)
        if stub_mapping else {}
    )

    # Identify which paragraphs need direct invocation
    direct_paras: set[str] = set()
    run_paras: set[str] = set()
    for tc in synth.test_cases:
        if tc.target.startswith("direct:"):
            direct_paras.update(tc.paragraphs_covered)
        else:
            run_paras.update(tc.paragraphs_covered)
    direct_only = direct_paras - run_paras

    # Build paragraph -> best base TC map
    para_to_tc: dict[str, TestCase] = {}
    for tc in synth.test_cases:
        for p in tc.paragraphs_covered:
            if p not in para_to_tc:
                para_to_tc[p] = tc

    # Try Z3 first, fall back to heuristic
    has_z3 = False
    try:
        import z3 as _z3_test  # noqa: F401
        from .concolic import solve_for_branch, build_var_env
        has_z3 = True
    except ImportError:
        pass

    for abs_id in sorted(branch_meta.keys()):
        if _time_exceeded(start_time, max_time):
            break

        meta = branch_meta[abs_id]
        para = meta.get("paragraph", "")

        # Skip branches in unreached paragraphs
        if para and para not in synth.covered_paras:
            continue

        use_direct = para in direct_only

        for negate in (False, True):
            target_id = -abs_id if negate else abs_id
            if target_id in synth.covered_branches:
                continue

            target_key = f"branch:{target_id}"
            # For direct invocation, prefix target so replay knows
            save_target = (
                f"direct:{para}|{target_key}" if use_direct and para
                else target_key
            )
            if _was_attempted(synth, 3, target_key):
                continue

            base_tc = para_to_tc.get(para)
            if base_tc is None and synth.test_cases:
                base_tc = synth.test_cases[0]

            base_state = dict(base_tc.input_state) if base_tc else {}
            base_stubs = (
                dict(base_tc.stub_outcomes) if base_tc and base_tc.stub_outcomes
                else {}
            )

            def _try_execute(state, stubs):
                if use_direct and para:
                    return _execute_direct_and_collect(
                        module, para, state, stubs, base_defaults,
                    )
                return _execute_and_collect(
                    module, state, stubs, base_defaults,
                )

            solved = False
            if has_z3:
                var_env = build_var_env(var_report, base_state, stub_mapping=stub_mapping)
                sol = solve_for_branch(
                    target_id, branch_meta, var_env,
                    negate=negate, stub_mapping=stub_mapping,
                    var_report=var_report,
                )
                if sol is not None:
                    state = dict(base_state)
                    state.update(sol.assignments)
                    stubs = dict(base_stubs)
                    if sol.stub_outcomes:
                        stubs.update(sol.stub_outcomes)

                    paras, branches, edges = _try_execute(state, stubs)
                    if _maybe_save(synth, store_path, state, stubs, base_defaults,
                                   paras, branches, edges, layer=3,
                                   target=save_target):
                        new_count += 1
                        solved = True

            if not solved:
                # EVALUATE branch handling
                if meta.get("type") == "EVALUATE" and meta.get("subject"):
                    subject = meta["subject"]
                    when_val = meta.get("condition", "")
                    state = dict(base_state)

                    if negate:
                        # Need FALSE → subject should NOT match WHEN value
                        # Use a value that differs from WHEN
                        if when_val == "OTHER":
                            pass  # OTHER always matches; can't be made false
                        else:
                            state[subject] = -99999  # unlikely to match
                    else:
                        # Need TRUE → subject should match WHEN value
                        if when_val == "OTHER":
                            # OTHER matches when no other WHEN matches
                            # Use a value unlikely to match any WHEN
                            state[subject] = -99999
                        elif when_val.startswith("'") and when_val.endswith("'"):
                            state[subject] = when_val[1:-1]
                        elif when_val.startswith("+"):
                            state[subject] = int(when_val)
                        elif when_val.lstrip("-").isdigit():
                            state[subject] = int(when_val)
                        else:
                            state[subject] = when_val

                    # Also set via stubs
                    if stub_mapping:
                        for op_key, svars in stub_mapping.items():
                            if subject in svars:
                                base_stubs[op_key] = [
                                    [(subject, state[subject])]
                                ] * 50

                    paras, branches, edges = _try_execute(state, base_stubs)
                    if _maybe_save(synth, store_path, state, base_stubs,
                                   base_defaults, paras, branches, edges,
                                   layer=3, target=save_target):
                        new_count += 1
                        solved = True

            if not solved:
                # Heuristic fallback
                condition = meta.get("condition", "")
                if not condition:
                    _record_attempt(synth, store_path, 3, target_key)
                    continue
                parsed = _parse_condition_variables(condition)
                if not parsed:
                    _record_attempt(synth, store_path, 3, target_key)
                    continue

                state = dict(base_state)
                # Detect var-to-var comparison direction from condition text
                cond_upper = condition.upper()
                is_gt = ("GREATER" in cond_upper or ">" in condition)
                is_lt = ("LESS" in cond_upper or "<" in condition)
                is_eq = ("EQUAL" in cond_upper or "=" in condition)
                is_var_to_var = (len(parsed) >= 2
                                 and all(v == [0] for _, v, _ in parsed))

                for i, (var, vals, neg) in enumerate(parsed):
                    effective_neg = neg != negate
                    if is_var_to_var and vals == [0]:
                        # Variable-to-variable comparison — look up existing
                        # values in base_state / defaults so we match (or
                        # mismatch) the *actual* runtime values, not an
                        # arbitrary constant like 42.
                        other_var = (parsed[1][0] if i == 0
                                     else parsed[0][0])
                        # Current value of the other variable
                        other_val = state.get(other_var,
                                              base_defaults.get(other_var, ''))
                        if not effective_neg:
                            # Need condition TRUE
                            if is_gt and i == 0:
                                ov = state.get(other_var,
                                               base_defaults.get(other_var, 0))
                                try:
                                    state[var] = int(ov) + 100
                                except (ValueError, TypeError):
                                    state[var] = 100
                            elif is_gt and i > 0:
                                pass  # leave other var as-is
                            elif is_lt and i == 0:
                                ov = state.get(other_var,
                                               base_defaults.get(other_var, 0))
                                try:
                                    state[var] = int(ov) - 100
                                except (ValueError, TypeError):
                                    state[var] = ''
                            elif is_lt and i > 0:
                                pass
                            elif is_eq:
                                # Set this var to match the other var's value
                                state[var] = other_val
                            else:
                                state[var] = other_val
                        else:
                            # Need condition FALSE
                            if is_gt and i == 0:
                                ov = state.get(other_var,
                                               base_defaults.get(other_var, 0))
                                try:
                                    state[var] = int(ov) - 100
                                except (ValueError, TypeError):
                                    state[var] = ''
                            elif is_gt and i > 0:
                                pass
                            elif is_lt and i == 0:
                                ov = state.get(other_var,
                                               base_defaults.get(other_var, 0))
                                try:
                                    state[var] = int(ov) + 100
                                except (ValueError, TypeError):
                                    state[var] = 'ZZZZZZ'
                            elif is_lt and i > 0:
                                pass
                            elif is_eq:
                                # Set to something different from other var
                                if isinstance(other_val, int):
                                    state[var] = other_val + 99999
                                elif isinstance(other_val, str) and other_val:
                                    state[var] = other_val + '_DIFF'
                                else:
                                    state[var] = '__NOMATCH__'
                            else:
                                state[var] = '__NOMATCH__'
                    elif not effective_neg and vals:
                        state[var] = vals[0]
                    elif effective_neg and vals:
                        info = var_report.variables.get(var)
                        literals = (info.condition_literals
                                   if info and hasattr(info, "condition_literals") else [])
                        for lit in literals:
                            if lit not in vals:
                                state[var] = lit
                                break
                        else:
                            if isinstance(vals[0], int):
                                state[var] = vals[0] + 999
                            else:
                                state[var] = "XX"

                paras, branches, edges = _try_execute(state, base_stubs)
                if _maybe_save(synth, store_path, state, base_stubs, base_defaults,
                               paras, branches, edges, layer=3,
                               target=save_target):
                    new_count += 1

            _record_attempt(synth, store_path, 3, target_key)

    _record_layer_done(synth, store_path, 3)
    return new_count


# ---------------------------------------------------------------------------
# Layer 3.5: Paragraph-Level Condition Sweep with Nesting Analysis
# ---------------------------------------------------------------------------

def _extract_branch_nesting(module, paragraph: str) -> dict[int, list[int]]:
    """Extract branch nesting tree from generated Python code.

    Parses the generated function for a paragraph and analyzes indentation
    to determine which branches are nested inside other branches' IF blocks.

    Returns a dict mapping branch_id -> list of parent branch_ids (nesting chain).
    """
    import inspect
    import re

    func_name = "para_" + re.sub(r"_+", "_", paragraph.replace("-", "_")).strip("_")
    para_func = getattr(module, func_name, None)
    if para_func is None:
        return {}

    try:
        src = inspect.getsource(para_func)
    except (OSError, TypeError):
        return {}

    # Extract (line_number, indent_level, branch_id) for each .add(N)
    branch_pattern = re.compile(r"^(\s+).*?\.add\((-?\d+)\)", re.MULTILINE)
    entries = []
    for m in branch_pattern.finditer(src):
        indent = len(m.group(1))
        bid = int(m.group(2))
        line_num = src[:m.start()].count('\n')
        entries.append((line_num, indent, bid))

    if not entries:
        return {}

    # Find the base indentation (function body)
    base_indent = min(indent for _, indent, _ in entries)

    # Stack-based nesting: a branch at deeper indent is inside the preceding
    # branch at shallower indent.
    stack: list[tuple[int, int]] = []  # (indent, branch_id)
    parent_map: dict[int, int] = {}

    for _line, indent, bid in entries:
        while stack and stack[-1][0] >= indent:
            stack.pop()
        if stack:
            parent_map[bid] = stack[-1][1]
        stack.append((indent, bid))

    # Build full nesting chains
    nesting: dict[int, list[int]] = {}
    for bid in [e[2] for e in entries]:
        chain = []
        current = bid
        while current in parent_map:
            current = parent_map[current]
            chain.append(current)
        chain.reverse()
        nesting[bid] = chain

    return nesting


def _run_layer_35(
    module, program, var_report, stub_mapping,
    synth: SynthesisState, store_path: Path,
    start_time: float, max_time: float | None,
) -> int:
    """Paragraph-level condition sweep with nesting analysis.

    For each paragraph with uncovered branches:
    1. Extract the branch nesting tree from the generated Python code
    2. For each uncovered branch, compute its nesting chain (parent conditions)
    3. Sweep condition variables through their condition_literals,
       satisfying the entire nesting chain simultaneously
    4. Use direct invocation for fast execution (~1ms per attempt)

    This is more effective than Layer 3 (per-branch solving) because it
    handles nested IF blocks — setting a parent branch's variable to the
    right value makes child branches reachable.
    """
    import re

    new_count = 0
    branch_meta = getattr(module, "_BRANCH_META", {})
    if not branch_meta:
        _record_layer_done(synth, store_path, 35)
        return 0

    base_defaults = (
        _generate_stub_defaults(stub_mapping, var_report)
        if stub_mapping else {}
    )

    # Find paragraphs with uncovered branches
    para_uncovered: dict[str, list[int]] = {}
    for abs_id, meta in branch_meta.items():
        para = meta.get("paragraph", "")
        if not para or para not in synth.covered_paras:
            continue
        for bid in (abs_id, -abs_id):
            if bid not in synth.covered_branches:
                para_uncovered.setdefault(para, []).append(bid)

    # Sort by number of uncovered branches (most first = highest value)
    sorted_paras = sorted(
        para_uncovered.items(), key=lambda x: len(x[1]), reverse=True,
    )

    # Build paragraph -> best base TC map
    para_to_tc: dict[str, TestCase] = {}
    for tc in synth.test_cases:
        for p in tc.paragraphs_covered:
            if p not in para_to_tc or len(tc.branches_covered) > len(para_to_tc[p].branches_covered):
                para_to_tc[p] = tc

    keywords = {
        "NOT", "AND", "OR", "EQUAL", "GREATER", "LESS", "THAN",
        "ZERO", "ZEROS", "ZEROES", "SPACES", "SPACE", "OTHER",
        "NUMERIC", "ALPHABETIC", "TRUE", "FALSE", "HIGH", "LOW",
        "VALUES", "DFHRESP", "NORMAL", "ERROR", "NOTFND",
        "NEXT", "SENTENCE", "THEN", "PERFORM", "NEGATIVE",
        "POSITIVE",
    }

    for para, uncov_bids in sorted_paras:
        if _time_exceeded(start_time, max_time):
            break

        target_key = f"sweep:{para}"
        if _was_attempted(synth, 35, target_key):
            continue

        # Get branch nesting for this paragraph
        nesting = _extract_branch_nesting(module, para)

        # Collect all condition variables from uncovered branches
        # AND their parent branches (the full nesting chain)
        cond_vars_values: dict[str, set] = {}  # var -> set of interesting values

        all_relevant_bids = set(uncov_bids)
        for bid in uncov_bids:
            abs_bid = abs(bid)
            if abs_bid in nesting:
                all_relevant_bids.update(abs(p) for p in nesting[abs_bid])

        for bid in all_relevant_bids:
            meta = branch_meta.get(bid, {})
            cond = meta.get("condition", "")

            # Handle EVALUATE branches: subject + WHEN values
            if meta.get("type") == "EVALUATE" and meta.get("subject"):
                subject = meta["subject"]
                if subject not in cond_vars_values:
                    cond_vars_values[subject] = set()
                # Add the WHEN value
                when_val = cond
                if when_val.startswith("'") and when_val.endswith("'"):
                    cond_vars_values[subject].add(when_val[1:-1])
                elif when_val.startswith("+"):
                    try:
                        cond_vars_values[subject].add(int(when_val))
                    except ValueError:
                        pass
                elif when_val.lstrip("-").isdigit():
                    cond_vars_values[subject].add(int(when_val))
                elif when_val not in ("OTHER", ""):
                    cond_vars_values[subject].add(when_val)
                # Add condition_literals for subject
                info = var_report.variables.get(subject)
                if info and hasattr(info, "condition_literals"):
                    for lit in info.condition_literals:
                        cond_vars_values[subject].add(lit)
                # Add -99999 for "OTHER" match (no WHEN matches)
                cond_vars_values[subject].add(-99999)
                continue

            if not cond:
                continue

            # Extract variables from condition
            found_vars = set(re.findall(r'\b([A-Z][A-Z0-9_-]+)\b', cond))
            found_vars -= keywords

            for var in found_vars:
                if var not in cond_vars_values:
                    cond_vars_values[var] = set()

                # Add condition_literals from var_report
                info = var_report.variables.get(var)
                if info and hasattr(info, "condition_literals"):
                    for lit in info.condition_literals:
                        cond_vars_values[var].add(lit)

                # Parse literal values directly from condition text
                parsed = _parse_condition_variables(cond)
                for pvar, pvals, _neg in parsed:
                    if pvar == var:
                        for v in pvals:
                            cond_vars_values[var].add(v)

                # Add generic values for common patterns
                if not cond_vars_values[var]:
                    cond_vars_values[var].update(["", "00", "Y", "N", 0, 1])
                # For numeric comparisons (GREATER, LESS), add boundary values
                if any(kw in cond.upper() for kw in
                       ("GREATER", "LESS", ">", "<")):
                    cond_vars_values[var].update([0, -1, 1, 100, 999])

        if not cond_vars_values:
            _record_attempt(synth, store_path, 35, target_key)
            continue

        # Get base TC
        base_tc = para_to_tc.get(para)
        if not base_tc:
            _record_attempt(synth, store_path, 35, target_key)
            continue

        base_state = dict(base_tc.input_state)
        base_stubs = dict(base_tc.stub_outcomes) if base_tc.stub_outcomes else {}

        # Phase 1: Single-variable sweep — try each variable × each value
        for var, values in sorted(cond_vars_values.items(),
                                  key=lambda x: len(x[1])):
            if _time_exceeded(start_time, max_time):
                break

            for val in values:
                if _time_exceeded(start_time, max_time):
                    break

                state = dict(base_state)
                state[var] = val

                # Also set via stubs if this is a stub-controlled variable
                stubs = dict(base_stubs)
                if stub_mapping:
                    for op_key, status_vars in stub_mapping.items():
                        if var in status_vars:
                            stubs[op_key] = [[(var, val)]] * 50

                paras, branches, edges = _execute_direct_and_collect(
                    module, para, state, stubs, base_defaults,
                )
                save_target = f"direct:{para}|sweep:{var}={val}"
                if _maybe_save(synth, store_path, state, stubs, base_defaults,
                               paras, branches, edges, layer=35,
                               target=save_target):
                    new_count += 1
                    # Update base state to build on success
                    base_state = state
                    base_stubs = stubs

        # Phase 1b: Per-branch targeted variable combination
        # For each uncovered branch, parse its specific condition and set ALL
        # variables from that condition simultaneously (handles AND conditions)
        for bid in uncov_bids:
            if _time_exceeded(start_time, max_time):
                break
            if bid in synth.covered_branches:
                continue

            abs_bid = abs(bid)
            meta = branch_meta.get(abs_bid, {})
            cond = meta.get("condition", "")
            if not cond:
                continue

            parsed = _parse_condition_variables(cond)
            if len(parsed) < 2:
                continue  # Single-var already handled by Phase 1

            need_true = bid > 0

            # Build value sets for each variable in this condition
            per_var_vals: dict[str, list] = {}
            for pvar, pvals, neg in parsed:
                effective_neg = neg != (not need_true)
                if pvar not in per_var_vals:
                    per_var_vals[pvar] = []
                if not effective_neg and pvals:
                    # Need to satisfy: add the condition values
                    for v in pvals:
                        if v not in per_var_vals[pvar]:
                            per_var_vals[pvar].append(v)
                elif effective_neg and pvals:
                    # Need to NOT satisfy: add alternatives
                    info = var_report.variables.get(pvar)
                    literals = (info.condition_literals
                               if info and hasattr(info, "condition_literals")
                               else [])
                    for lit in literals:
                        if lit not in pvals and lit not in per_var_vals[pvar]:
                            per_var_vals[pvar].append(lit)
                    if not per_var_vals[pvar]:
                        per_var_vals[pvar].append(999 if isinstance(
                            pvals[0], (int, float)) else "XX")

            if not per_var_vals:
                continue

            # Try cartesian product (limited to avoid explosion)
            var_names_list = sorted(per_var_vals.keys())
            val_lists = [per_var_vals[v][:4] for v in var_names_list]  # max 4 per var
            combo_count = 1
            for vl in val_lists:
                combo_count *= len(vl)
            if combo_count > 64:
                # Too many — just try first value for each
                val_lists = [[vl[0]] for vl in val_lists]

            for combo in product(*val_lists):
                if _time_exceeded(start_time, max_time):
                    break
                state = dict(base_state)
                stubs = dict(base_stubs)
                for vname, val in zip(var_names_list, combo):
                    state[vname] = val
                    if stub_mapping:
                        for op_key, svars in stub_mapping.items():
                            if vname in svars:
                                stubs[op_key] = [[(vname, val)]] * 50

                paras, branches, edges = _execute_direct_and_collect(
                    module, para, state, stubs, base_defaults,
                )
                save_target = f"direct:{para}|combo:{bid}"
                if _maybe_save(synth, store_path, state, stubs, base_defaults,
                               paras, branches, edges, layer=35,
                               target=save_target):
                    new_count += 1
                    base_state = state
                    base_stubs = stubs
                    break

        # Phase 2: Nesting-chain-guided combinations
        # For each uncovered branch, set ALL variables in its nesting chain
        for bid in uncov_bids:
            if _time_exceeded(start_time, max_time):
                break
            if bid in synth.covered_branches:
                continue

            abs_bid = abs(bid)
            chain = nesting.get(abs_bid, [])
            if not chain:
                continue

            # For each parent in the chain, figure out what direction is needed
            # to reach the child. The child is inside the parent's block,
            # so we need the parent's direction (positive = true arm).
            state = dict(base_state)
            stubs = dict(base_stubs)

            for parent_bid in chain:
                parent_meta = branch_meta.get(abs(parent_bid), {})
                parent_cond = parent_meta.get("condition", "")
                if not parent_cond:
                    continue

                parsed = _parse_condition_variables(parent_cond)
                # The parent_bid sign tells us which arm: positive = true
                need_true = parent_bid > 0
                for pvar, pvals, neg in parsed:
                    effective_neg = neg != (not need_true)
                    if not effective_neg and pvals:
                        state[pvar] = pvals[0]
                    elif effective_neg and pvals:
                        info = var_report.variables.get(pvar)
                        literals = (info.condition_literals
                                   if info and hasattr(info, "condition_literals")
                                   else [])
                        for lit in literals:
                            if lit not in pvals:
                                state[pvar] = lit
                                break
                        else:
                            state[pvar] = "XX" if isinstance(pvals[0], str) else 999

                    # Also set via stubs
                    if stub_mapping:
                        for op_key, svars in stub_mapping.items():
                            if pvar in svars:
                                stubs[op_key] = [[(pvar, state[pvar])]] * 50

            # Also set the target branch's own condition
            target_meta = branch_meta.get(abs_bid, {})
            target_cond = target_meta.get("condition", "")
            if target_cond:
                parsed = _parse_condition_variables(target_cond)
                need_true = bid > 0
                for pvar, pvals, neg in parsed:
                    effective_neg = neg != (not need_true)
                    if not effective_neg and pvals:
                        state[pvar] = pvals[0]
                    elif effective_neg and pvals:
                        info = var_report.variables.get(pvar)
                        literals = (info.condition_literals
                                   if info and hasattr(info, "condition_literals")
                                   else [])
                        for lit in literals:
                            if lit not in pvals:
                                state[pvar] = lit
                                break
                        else:
                            state[pvar] = "XX" if isinstance(pvals[0], str) else 999

                    if stub_mapping:
                        for op_key, svars in stub_mapping.items():
                            if pvar in svars:
                                stubs[op_key] = [[(pvar, state[pvar])]] * 50

            paras, branches, edges = _execute_direct_and_collect(
                module, para, state, stubs, base_defaults,
            )
            save_target = f"direct:{para}|nest:{bid}"
            if _maybe_save(synth, store_path, state, stubs, base_defaults,
                           paras, branches, edges, layer=35,
                           target=save_target):
                new_count += 1

        # Phase 3: Targeted branch flip with multiple base TCs
        # For each still-uncovered branch, try different base TCs and set
        # all condition variables for each direction (true/false)
        all_bases = [tc for tc in synth.test_cases
                     if para in tc.paragraphs_covered][:5]
        for bid in uncov_bids:
            if _time_exceeded(start_time, max_time):
                break
            if bid in synth.covered_branches:
                continue

            abs_bid = abs(bid)

            # Handle SEARCH branches: inject stub outcomes
            target_meta_3 = branch_meta.get(abs_bid, {})
            if target_meta_3.get("type") == "SEARCH":
                cond_text = target_meta_3.get("condition", "")
                # Extract table name from "SEARCH TABLE_NAME FOUND"
                m_search = re.match(r"SEARCH\s+(\S+)", cond_text)
                if m_search:
                    table_name = m_search.group(1)
                    search_key = f"SEARCH:{table_name}"
                    want_found = bid > 0
                    for alt_base in (all_bases or [base_tc]):
                        if _time_exceeded(start_time, max_time):
                            break
                        state = dict(alt_base.input_state)
                        stubs = dict(
                            alt_base.stub_outcomes
                            if alt_base.stub_outcomes else {}
                        )
                        stubs[search_key] = [want_found] * 50
                        paras_s, branches_s, edges_s = (
                            _execute_direct_and_collect(
                                module, para, state, stubs, base_defaults,
                            )
                        )
                        save_target = (
                            f"direct:{para}|search:{search_key}={want_found}"
                        )
                        if _maybe_save(
                            synth, store_path, state, stubs,
                            base_defaults, paras_s, branches_s, edges_s,
                            layer=35, target=save_target,
                        ):
                            new_count += 1
                            break
                    continue
            target_meta = branch_meta.get(abs_bid, {})
            target_cond = target_meta.get("condition", "")
            if not target_cond:
                continue
            parsed = _parse_condition_variables(target_cond)
            if not parsed:
                continue

            need_true = bid > 0
            # Detect comparison direction for var-to-var
            cond_upper = target_cond.upper()
            is_gt = ("GREATER" in cond_upper or ">" in target_cond)
            is_lt = ("LESS" in cond_upper or "<" in target_cond)
            is_var_to_var = (len(parsed) >= 2
                             and all(v == [0] for _, v, _ in parsed))

            for base_tc_idx, alt_base in enumerate(all_bases):
                if _time_exceeded(start_time, max_time):
                    break
                state = dict(alt_base.input_state)
                stubs = dict(alt_base.stub_outcomes) if alt_base.stub_outcomes else {}

                # Also satisfy nesting chain
                chain = nesting.get(abs_bid, [])
                for parent_bid in chain:
                    parent_meta = branch_meta.get(abs(parent_bid), {})
                    parent_cond = parent_meta.get("condition", "")
                    if parent_cond:
                        pp = _parse_condition_variables(parent_cond)
                        p_need_true = parent_bid > 0
                        for pvar, pvals, pneg in pp:
                            eff_neg = pneg != (not p_need_true)
                            if not eff_neg and pvals:
                                state[pvar] = pvals[0]
                            elif eff_neg and pvals:
                                info = var_report.variables.get(pvar)
                                lits = (info.condition_literals
                                       if info and hasattr(info, "condition_literals")
                                       else [])
                                for lit in lits:
                                    if lit not in pvals:
                                        state[pvar] = lit
                                        break
                                else:
                                    state[pvar] = ("XX" if isinstance(
                                        pvals[0], str) else 999)

                # Set target condition variables
                for i, (pvar, pvals, pneg) in enumerate(parsed):
                    eff_neg = pneg != (not need_true)
                    if is_var_to_var and pvals == [0]:
                        other_var = (parsed[1][0] if i == 0
                                     else parsed[0][0])
                        other_val = state.get(other_var,
                                              base_defaults.get(other_var, ''))
                        if not eff_neg:
                            if is_gt:
                                try:
                                    state[pvar] = int(other_val) + 100 if i == 0 else state.get(pvar, '')
                                except (ValueError, TypeError):
                                    state[pvar] = 100 if i == 0 else 1
                            elif is_lt:
                                try:
                                    state[pvar] = int(other_val) - 100 if i == 0 else state.get(pvar, '')
                                except (ValueError, TypeError):
                                    state[pvar] = 1 if i == 0 else 100
                            else:
                                state[pvar] = other_val
                        else:
                            if is_gt:
                                try:
                                    state[pvar] = int(other_val) - 100 if i == 0 else state.get(pvar, '')
                                except (ValueError, TypeError):
                                    state[pvar] = 1 if i == 0 else 100
                            elif is_lt:
                                try:
                                    state[pvar] = int(other_val) + 100 if i == 0 else state.get(pvar, '')
                                except (ValueError, TypeError):
                                    state[pvar] = 100 if i == 0 else 1
                            else:
                                if isinstance(other_val, int):
                                    state[pvar] = other_val + 99999
                                elif isinstance(other_val, str) and other_val:
                                    state[pvar] = other_val + '_DIFF'
                                else:
                                    state[pvar] = '__NOMATCH__'
                    elif not eff_neg and pvals:
                        state[pvar] = pvals[0]
                    elif eff_neg and pvals:
                        info = var_report.variables.get(pvar)
                        lits = (info.condition_literals
                               if info and hasattr(info, "condition_literals")
                               else [])
                        for lit in lits:
                            if lit not in pvals:
                                state[pvar] = lit
                                break
                        else:
                            state[pvar] = ("XX" if isinstance(
                                pvals[0], str) else 999)

                    # Set via stubs if applicable
                    if stub_mapping:
                        for op_key, svars in stub_mapping.items():
                            if pvar in svars:
                                stubs[op_key] = [[(pvar, state.get(pvar, 0))]] * 50

                paras, branches, edges = _execute_direct_and_collect(
                    module, para, state, stubs, base_defaults,
                )
                save_target = f"direct:{para}|flip:{bid}:b{base_tc_idx}"
                if _maybe_save(synth, store_path, state, stubs, base_defaults,
                               paras, branches, edges, layer=35,
                               target=save_target):
                    new_count += 1
                    break

        _record_attempt(synth, store_path, 35, target_key)

    _record_layer_done(synth, store_path, 35)
    return new_count


# ---------------------------------------------------------------------------
# Layer 3.7: Stub Fault Injection via Python Dataflow Analysis
# ---------------------------------------------------------------------------

def _extract_stub_branch_map(
    module, stub_mapping: dict[str, list[str]],
) -> dict[int, list[dict]]:
    """Map each branch to stub operations that control its condition variable.

    Uses two complementary strategies:
    1. **Stub mapping**: For each branch, checks if its condition variable is a
       status variable set by any stub operation (from the stub_mapping).
    2. **Source analysis**: Parses generated Python to extract the exact comparison
       operator and values from each branch's ``if`` statement.

    Returns a dict: branch_id -> [
        {
            "stub_key": "READ:SYM00144",
            "status_var": "SYM03160",
            "op": "not_in",       # Python comparison operator
            "values": ["00", "04"],  # values from the condition
            "paragraph": "PARA-NAME",
        },
        ...
    ]
    """
    import inspect
    import re

    meta = getattr(module, "_BRANCH_META", {})
    if not meta or not stub_mapping:
        return {}

    # Build reverse map: status_variable -> list of stub_keys
    var_to_stubs: dict[str, list[str]] = {}
    for op_key, status_vars in stub_mapping.items():
        for svar in status_vars:
            var_to_stubs.setdefault(svar, []).append(op_key)

    # Cache function sources
    _source_cache: dict[str, str] = {}

    def _get_source(para: str) -> str:
        if para not in _source_cache:
            func_name = "para_" + re.sub(r"_+", "_", para.replace("-", "_")).strip("_")
            func = getattr(module, func_name, None)
            if func is None:
                _source_cache[para] = ""
                return ""
            try:
                _source_cache[para] = inspect.getsource(func)
            except (OSError, TypeError):
                _source_cache[para] = ""
        return _source_cache[para]

    # Patterns for parsing Python conditions
    var_access_pat = re.compile(
        r"state(?:\['([A-Z][A-Z0-9_]+)'\]|\.get\('([A-Z][A-Z0-9_]+)')"
    )
    val_pat = re.compile(r"'([^']*)'|(?<![A-Za-z_])(\d+)(?![A-Za-z_])")

    result: dict[int, list[dict]] = {}

    for abs_id, info in meta.items():
        para = info.get("paragraph", "")
        if not para:
            continue

        src = _get_source(para)
        if not src:
            continue

        lines = src.split("\n")

        # Find the line(s) where this branch ID appears (exact match)
        add_pattern = re.compile(
            rf"\.add\({abs_id}\b\)|\.add\(-{abs_id}\b\)"
        )

        for i, line in enumerate(lines):
            if not add_pattern.search(line):
                continue

            # Extract actual branch ID from this line
            bid_match = re.search(r"\.add\((-?\d+)\)", line)
            if not bid_match:
                continue
            actual_bid = int(bid_match.group(1))

            # Look backward for the if condition
            cond_line = ""
            cond_var = None
            for k in range(i - 1, max(i - 5, -1), -1):
                if k >= 0 and ("if " in lines[k] or "elif " in lines[k]):
                    cond_line = lines[k]
                    vm = var_access_pat.search(lines[k])
                    if vm:
                        cond_var = vm.group(1) or vm.group(2)
                    break

            if not cond_var:
                continue

            # Check if this variable is controlled by a stub
            controlling_stubs = var_to_stubs.get(cond_var, [])
            if not controlling_stubs:
                continue

            # Parse the Python comparison
            stripped = cond_line.strip()
            if "not in" in stripped:
                op = "not_in"
            elif " in " in stripped:
                op = "in"
            elif "!=" in stripped:
                op = "!="
            elif "==" in stripped:
                op = "=="
            elif ">=" in stripped:
                op = ">="
            elif "<=" in stripped:
                op = "<="
            elif ">" in stripped:
                op = ">"
            elif "<" in stripped:
                op = "<"
            else:
                op = "truthy"

            # Extract literal values from the condition.
            # For "not in ('00', '04')" extract the tuple contents.
            # For "!= '0000'" extract the comparison value.
            cond_values: list = []
            if op in ("not_in", "in"):
                # Extract values from the tuple: ('val1', 'val2', ...)
                tuple_match = re.search(r'\(([^)]+)\)', stripped)
                if tuple_match:
                    tuple_str = tuple_match.group(1)
                    for vm in val_pat.finditer(tuple_str):
                        s, n = vm.groups()
                        if s is not None:
                            cond_values.append(s)
                        elif n is not None:
                            cond_values.append(int(n))
            else:
                # Extract values after the operator
                op_str = {"!=": "!=", "==": "==", ">=": ">=",
                          "<=": "<=", ">": ">", "<": "<"}.get(op, "")
                if op_str:
                    op_pos = stripped.find(op_str)
                    if op_pos >= 0:
                        after_op = stripped[op_pos + len(op_str):]
                        for vm in val_pat.finditer(after_op):
                            s, n = vm.groups()
                            if s is not None:
                                cond_values.append(s)
                            elif n is not None:
                                cond_values.append(int(n))

            for stub_key in controlling_stubs:
                result.setdefault(actual_bid, []).append({
                    "stub_key": stub_key,
                    "status_var": cond_var,
                    "op": op,
                    "values": cond_values,
                    "paragraph": para,
                })

    return result


def _compute_fault_values(
    op: str, cond_values: list, var_report, status_var: str
) -> list:
    """Compute values to inject via stubs to trigger or avoid a branch.

    Given the comparison operator and values from the condition, returns
    a list of values to try that would satisfy or negate the condition.
    """
    results = []

    # Get condition_literals for this variable
    info = var_report.variables.get(status_var) if var_report else None
    all_literals = []
    if info and hasattr(info, "condition_literals"):
        all_literals = list(info.condition_literals)

    if op in ("!=", "not_in") and cond_values:
        # Condition: var not in (val1, val2, ...) or var != val
        # To make it TRUE (enter the branch): use something NOT in cond_values
        # To make it FALSE (skip the branch): use one of cond_values
        # Try BOTH directions
        for v in cond_values:
            results.append(v)  # FALSE direction (skip branch)
        # TRUE direction: values NOT in cond_values
        for lit in all_literals:
            if lit not in cond_values:
                results.append(lit)
        # Try generic error values
        first = cond_values[0] if cond_values else ""
        if isinstance(first, str):
            for v in ["10", "23", "35", "39", "46", "99", "XX"]:
                if v not in cond_values and v not in results:
                    results.append(v)
        elif isinstance(first, int):
            for v in [100, -803, 4, 8, 12, 13, 27, 99]:
                if v not in cond_values and v not in results:
                    results.append(v)

    elif op in ("==", "in") and cond_values:
        # Condition: var in (val1, val2) or var == val
        # TRUE: use one of cond_values
        # FALSE: use something else
        for v in cond_values:
            results.append(v)
        for lit in all_literals:
            if lit not in cond_values:
                results.append(lit)
        first = cond_values[0] if cond_values else ""
        if isinstance(first, str):
            for v in ["00", "10", "99", ""]:
                if v not in cond_values and v not in results:
                    results.append(v)
        elif isinstance(first, int):
            for v in [0, 100, -1, 999]:
                if v not in cond_values and v not in results:
                    results.append(v)

    elif op in (">", ">=", "<", "<=") and cond_values:
        # Try boundary values
        for v in cond_values:
            if isinstance(v, int):
                results.extend([v - 1, v, v + 1])
            elif isinstance(v, str) and v.isdigit():
                iv = int(v)
                results.extend([str(iv - 1), v, str(iv + 1)])

    # Always include common status values as fallback
    if not results:
        results = ["00", "10", "23", "35", 0, 100, -803, 4, 8]

    return results


def _run_layer_37(
    module, program, var_report, stub_mapping,
    synth: SynthesisState, store_path: Path,
    start_time: float, max_time: float | None,
) -> int:
    """Stub Fault Injection via Python Dataflow Analysis.

    Analyzes generated Python source code to find branches whose condition
    variables are SET by _apply_stub_outcome calls. For each such branch,
    crafts specific stub outcomes (error codes, EOF, etc.) that would
    trigger or avoid the branch condition.

    This is fundamentally different from Layer 3.5 (which sets input state
    variables) because it targets variables that are OVERWRITTEN by stub
    execution during the function — making input state manipulation useless
    for those branches.

    It also performs multi-stub coordination: when a paragraph has multiple
    stub operations before a branch, it tries combinations of success/failure
    across those stubs.
    """
    new_count = 0

    branch_meta = getattr(module, "_BRANCH_META", {})
    if not branch_meta or not stub_mapping:
        _record_layer_done(synth, store_path, 37)
        return 0

    base_defaults = (
        _generate_stub_defaults(stub_mapping, var_report)
        if stub_mapping else {}
    )

    # Build the stub-to-branch map
    stub_branch_map = _extract_stub_branch_map(module, stub_mapping)
    if not stub_branch_map:
        log.info("Layer 37: no stub-dependent branches found")
        _record_layer_done(synth, store_path, 37)
        return 0

    log.info("Layer 37: found %d branches with stub dependencies", len(stub_branch_map))

    # Build paragraph -> best base TC map
    para_to_tc: dict[str, TestCase] = {}
    for tc in synth.test_cases:
        for p in tc.paragraphs_covered:
            if p not in para_to_tc or len(tc.branches_covered) > len(para_to_tc[p].branches_covered):
                para_to_tc[p] = tc

    # Get nesting info for multi-level constraint satisfaction
    nesting_cache: dict[str, dict[int, list[int]]] = {}

    # Process each stub-dependent branch
    for bid, stub_entries in sorted(stub_branch_map.items()):
        if _time_exceeded(start_time, max_time):
            break

        # Check both positive and negative directions
        for direction in (bid, -abs(bid)):
            if direction in synth.covered_branches:
                continue

            target_key = f"fault:{direction}"
            if _was_attempted(synth, 37, target_key):
                continue

            para = stub_entries[0]["paragraph"]
            if para not in synth.covered_paras:
                _record_attempt(synth, store_path, 37, target_key)
                continue

            base_tc = para_to_tc.get(para)
            if not base_tc:
                _record_attempt(synth, store_path, 37, target_key)
                continue

            # Get nesting chain for this branch
            if para not in nesting_cache:
                nesting_cache[para] = _extract_branch_nesting(module, para)
            nesting = nesting_cache[para]

            base_state = dict(base_tc.input_state)
            base_stubs = dict(base_tc.stub_outcomes) if base_tc.stub_outcomes else {}

            found = False

            # For each controlling stub, try injecting fault values
            for entry in stub_entries:
                if found or _time_exceeded(start_time, max_time):
                    break

                stub_key = entry["stub_key"]
                status_var = entry["status_var"]
                op = entry["op"]
                cond_values = entry["values"]

                fault_values = _compute_fault_values(
                    op, cond_values, var_report, status_var,
                )

                for fval in fault_values:
                    if found or _time_exceeded(start_time, max_time):
                        break

                    state = dict(base_state)
                    stubs = dict(base_stubs)

                    # Inject the fault value via stub outcomes
                    stubs[stub_key] = [[(status_var, fval)]] * 50

                    # Also satisfy nesting chain parents
                    abs_bid = abs(direction)
                    chain = nesting.get(abs_bid, [])
                    for parent_bid in chain:
                        parent_meta = branch_meta.get(abs(parent_bid), {})
                        parent_cond = parent_meta.get("condition", "")
                        if parent_cond:
                            parsed = _parse_condition_variables(parent_cond)
                            for pvar, pvals, neg in parsed:
                                if not neg and pvals:
                                    state[pvar] = pvals[0]
                                    # Also set via stubs if applicable
                                    if stub_mapping:
                                        for sk, svars in stub_mapping.items():
                                            if pvar in svars:
                                                stubs[sk] = [[(pvar, pvals[0])]] * 50

                    paras, branches, edges = _execute_direct_and_collect(
                        module, para, state, stubs, base_defaults,
                    )
                    save_target = f"direct:{para}|fault:{stub_key}={fval}"
                    if _maybe_save(synth, store_path, state, stubs, base_defaults,
                                   paras, branches, edges, layer=37,
                                   target=save_target):
                        new_count += 1
                        found = True

            # Phase 2: Multi-stub combinations for the same paragraph
            # When multiple stubs precede a branch, try error on one + success on others
            if not found and len(stub_entries) > 1:
                unique_stubs = list({e["stub_key"] for e in stub_entries})
                for primary_idx, primary_stub in enumerate(unique_stubs):
                    if found or _time_exceeded(start_time, max_time):
                        break

                    primary_entry = next(
                        e for e in stub_entries if e["stub_key"] == primary_stub
                    )
                    primary_var = primary_entry["status_var"]
                    fault_values = _compute_fault_values(
                        primary_entry["op"], primary_entry["values"],
                        var_report, primary_var,
                    )

                    for fval in fault_values[:5]:  # Limit combos
                        if found or _time_exceeded(start_time, max_time):
                            break

                        state = dict(base_state)
                        stubs = dict(base_stubs)

                        # Error on primary stub, success on others
                        stubs[primary_stub] = [[(primary_var, fval)]] * 50
                        for other_stub in unique_stubs:
                            if other_stub == primary_stub:
                                continue
                            other_entry = next(
                                e for e in stub_entries if e["stub_key"] == other_stub
                            )
                            other_var = other_entry["status_var"]
                            # Success value: first value in condition (usually "00")
                            success_vals = other_entry["values"]
                            if success_vals:
                                stubs[other_stub] = [[(other_var, success_vals[0])]] * 50

                        paras, branches, edges = _execute_direct_and_collect(
                            module, para, state, stubs, base_defaults,
                        )
                        save_target = f"direct:{para}|multi-fault:{primary_stub}={fval}"
                        if _maybe_save(synth, store_path, state, stubs, base_defaults,
                                       paras, branches, edges, layer=37,
                                       target=save_target):
                            new_count += 1
                            found = True

            _record_attempt(synth, store_path, 37, target_key)

    _record_layer_done(synth, store_path, 37)
    return new_count


# ---------------------------------------------------------------------------
# Layer 4: Stub Outcome Combinatorics
# ---------------------------------------------------------------------------

def _compute_stub_combinations(
    target_branch: int,
    branch_meta: dict,
    stub_mapping: dict,
    var_report,
    program,
    max_combos: int = 100,
) -> list[dict[str, list]]:
    """Compute interesting stub outcome combinations for a target branch."""
    abs_id = abs(target_branch)
    meta = branch_meta.get(abs_id, {})
    para = meta.get("paragraph", "")
    if not para or not stub_mapping:
        return []

    # Collect interesting values per stub operation
    op_values: dict[str, list] = {}
    for op_key, status_vars in stub_mapping.items():
        interesting = set()
        for svar in status_vars:
            info = var_report.variables.get(svar)
            if info and hasattr(info, "condition_literals"):
                for lit in info.condition_literals:
                    interesting.add((svar, lit))
            # Also add generic success/failure
            upper = svar.upper()
            if "SQLCODE" in upper:
                interesting.update({(svar, 0), (svar, 100), (svar, -803)})
            elif "EIBRESP" in upper:
                interesting.update({(svar, 0), (svar, 13), (svar, 27)})
            elif "STATUS" in upper or upper.startswith("FS-"):
                interesting.update({(svar, "00"), (svar, "10"), (svar, "35")})
            elif "RETURN-CODE" in upper or upper.endswith("-RC"):
                interesting.update({(svar, 0), (svar, 4), (svar, 8)})
        if interesting:
            op_values[op_key] = [list(v) for v in interesting]

    if not op_values:
        return []

    # Build combinations, limited to max_combos
    op_keys = sorted(op_values.keys())
    value_lists = [op_values[k] for k in op_keys]

    combos = []
    for combo in product(*value_lists):
        if len(combos) >= max_combos:
            break
        stub_combo: dict[str, list] = {}
        for op_key, (svar, val) in zip(op_keys, combo):
            entry = [(svar, val)]
            stub_combo[op_key] = [entry] * 25
        combos.append(stub_combo)

    return combos


# ---------------------------------------------------------------------------
# Layer 3.8: Dataflow Constraint Propagation
# ---------------------------------------------------------------------------

def _extract_paragraph_dataflow(module, paragraph: str) -> tuple[
    list[tuple[int, str, str, list[str]]],   # assignments: (line, var, expr, deps)
    list[tuple[int, int, str, int]],          # branches: (line, bid, cond_line, indent)
]:
    """Parse a paragraph function to extract assignments and branch checks.

    Returns two lists ordered by line number:
    - assignments: (line_idx, target_var, raw_expr, [dep_vars])
    - branches: (line_idx, branch_id, condition_line_text, indent_level)
    """
    import inspect
    import re

    func_name = "para_" + re.sub(r"_+", "_", paragraph.replace("-", "_")).strip("_")
    para_func = getattr(module, func_name, None)
    if para_func is None:
        return [], []

    try:
        src = inspect.getsource(para_func)
    except (OSError, TypeError):
        return [], []

    lines = src.split("\n")

    # Pattern for state['VAR'] = expr
    assign_pat = re.compile(
        r"^(\s*)state\['([A-Z][A-Z0-9_-]*)'\]\s*=\s*(.*)"
    )
    # Pattern for dependency variables in an expression
    dep_pat = re.compile(
        r"state\.get\('([A-Z][A-Z0-9_-]*)'|state\['([A-Z][A-Z0-9_-]*)'\]"
    )
    # Pattern for branch .add(N)
    branch_pat = re.compile(r"\.add\((-?\d+)\)")
    # Pattern for stub outcome pop
    stub_pop_pat = re.compile(
        r"_stub_outcomes.*?\.get\('([^']+)'|_apply_stub_outcome"
    )

    assignments: list[tuple[int, str, str, list[str]]] = []
    branches: list[tuple[int, int, str, int]] = []

    for i, line in enumerate(lines):
        # Check for assignments
        am = assign_pat.match(line)
        if am:
            indent = len(am.group(1))
            target_var = am.group(2)
            expr = am.group(3)
            deps = [g1 or g2 for g1, g2 in dep_pat.findall(expr)]
            # Check if it's a stub-derived value (pop from _stub_outcomes)
            is_stub = bool(stub_pop_pat.search(expr))
            if is_stub:
                deps.append("__STUB__")
            assignments.append((i, target_var, expr, deps))

        # Check for branch checks
        bm = branch_pat.search(line)
        if bm:
            bid = int(bm.group(1))
            # Find the condition (look backward for if/elif/while)
            cond_line = ""
            cond_indent = 0
            for k in range(i - 1, max(i - 5, -1), -1):
                if k >= 0 and ("if " in lines[k] or "elif " in lines[k]
                               or "while " in lines[k]):
                    cond_line = lines[k]
                    cond_indent = len(lines[k]) - len(lines[k].lstrip())
                    break
            branches.append((i, bid, cond_line, cond_indent))

    return assignments, branches


def _trace_backward(
    target_var: str,
    branch_line: int,
    assignments: list[tuple[int, str, str, list[str]]],
    max_depth: int = 3,
) -> list[tuple[str, str]]:
    """Trace backward from a branch to find input dependencies.

    Starting from a condition variable at a specific line, walks backward
    through assignments to find the chain of computations.

    Returns list of (variable, expression) pairs representing the
    backward chain, from condition var to inputs.
    """
    chain: list[tuple[str, str]] = []
    frontier = {target_var}
    seen_vars: set[str] = set()

    for depth in range(max_depth):
        if not frontier:
            break
        next_frontier: set[str] = set()
        for var in frontier:
            if var in seen_vars or var == "__STUB__":
                continue
            seen_vars.add(var)

            # Find the LAST assignment to this var BEFORE the branch line
            last_assign = None
            for line_idx, avar, expr, deps in assignments:
                if avar == var and line_idx < branch_line:
                    last_assign = (avar, expr, deps)

            if last_assign:
                avar, expr, deps = last_assign
                chain.append((avar, expr))
                for dep in deps:
                    if dep not in seen_vars:
                        next_frontier.add(dep)
        frontier = next_frontier

    return chain


def _trace_interprocedural(
    module,
    target_var: str,
    branch_line: int,
    parent_assignments: list[tuple[int, str, str, list[str]]],
    parent_branches: list[tuple[int, int, str, int]],
    df_cache: dict[str, tuple],
) -> list[tuple[str, str]]:
    """Trace backward through sub-paragraph calls.

    When a variable is not assigned in the current paragraph, checks if
    any sub-paragraph called before the branch assigns it. If so, traces
    backward through that sub-paragraph's dataflow.
    """
    import inspect
    import re

    # Find the paragraph function source to locate sub-paragraph calls
    # We need to look at the raw source lines to find para_XXX(state) calls
    # before the branch_line
    # Since we have parent_assignments ordered by line, we can look at the
    # function source directly

    # Get the paragraph name from any branch check
    para_name = None
    for _, bid, _, _ in parent_branches:
        meta = getattr(module, "_BRANCH_META", {}).get(abs(bid))
        if meta:
            para_name = meta.get("paragraph")
            break

    if not para_name:
        return []

    func_name = "para_" + re.sub(r"_+", "_", para_name.replace("-", "_")).strip("_")
    para_func = getattr(module, func_name, None)
    if not para_func:
        return []

    try:
        src = inspect.getsource(para_func)
    except (OSError, TypeError):
        return []

    lines = src.split("\n")
    call_pat = re.compile(r"(para_[A-Z0-9_]+)\(state\)")

    # Find sub-paragraph calls before the branch line
    sub_calls = []
    for i in range(min(branch_line, len(lines))):
        cm = call_pat.search(lines[i])
        if cm:
            sub_calls.append((i, cm.group(1)))

    # Check each sub-paragraph (in reverse order — last one wins)
    for _call_line, sub_func_name in reversed(sub_calls):
        sub_func = getattr(module, sub_func_name, None)
        if not sub_func:
            continue

        # Get the sub-paragraph's COBOL name for cache lookup
        # Convert para_XXX_YYY back to XXX-YYY
        cobol_name = sub_func_name[5:].replace("_", "-")  # approximate

        # Extract dataflow from the sub-function
        try:
            sub_src = inspect.getsource(sub_func)
        except (OSError, TypeError):
            continue

        sub_lines = sub_src.split("\n")
        assign_pat = re.compile(
            r"^(\s*)state\['([A-Z][A-Z0-9_-]*)'\]\s*=\s*(.*)"
        )
        dep_pat = re.compile(
            r"state\.get\('([A-Z][A-Z0-9_-]*)'|state\['([A-Z][A-Z0-9_-]*)'\]"
        )

        # Check if this sub-paragraph assigns target_var
        sub_assigns = []
        for j, line in enumerate(sub_lines):
            am = assign_pat.match(line)
            if am:
                avar = am.group(2)
                expr = am.group(3)
                deps = [g1 or g2 for g1, g2 in dep_pat.findall(expr)]
                sub_assigns.append((j, avar, expr, deps))

        # Find the last assignment to target_var in the sub-paragraph
        last_assign = None
        for j, avar, expr, deps in sub_assigns:
            if avar == target_var:
                last_assign = (avar, expr, deps)

        if last_assign:
            avar, expr, deps = last_assign
            chain = [(avar, expr)]
            # Also trace one more level back through the sub-paragraph
            for dep in deps:
                for j, davar, dexpr, ddeps in sub_assigns:
                    if davar == dep:
                        chain.append((davar, dexpr))
            return chain

    return []


def _solve_backward_constraint(
    condition_var: str,
    condition_text: str,
    chain: list[tuple[str, str]],
    negate: bool,
    branch_meta_entry: dict,
    var_report,
    base_state: dict,
) -> dict[str, object]:
    """Given a backward dataflow chain, compute input values that satisfy the condition.

    Returns dict of variable -> value to set in input state.
    """
    import re

    result: dict[str, object] = {}

    # If chain is empty, condition var is directly settable (no intermediate computation)
    if not chain:
        return result

    # Classify what the chain tells us about the condition var
    first_var, first_expr = chain[0]

    # Case 1: Simple MOVE/copy — state['X'] = state.get('Y', '')
    copy_match = re.match(
        r"state\.get\('([A-Z][A-Z0-9_-]*)'\s*,\s*''\s*\)", first_expr
    )
    if copy_match:
        source_var = copy_match.group(1)
        # The condition on X is really a condition on Y
        # Parse what value we need
        from .static_analysis import _parse_condition_variables
        try:
            parsed = _parse_condition_variables(
                branch_meta_entry.get("condition", "")
            )
        except Exception:
            parsed = []
        for pvar, vals, neg in parsed:
            effective_neg = neg ^ negate
            if vals:
                if not effective_neg:
                    result[source_var] = vals[0]
                else:
                    # Need the opposite — try a different value
                    if isinstance(vals[0], str):
                        result[source_var] = "__DIFF__"
                    else:
                        result[source_var] = vals[0] + 99999
        return result

    # Case 2: Constant assignment — state['X'] = 'literal' or state['X'] = 0
    const_match = re.match(r"^'([^']*)'$|^(-?\d+(?:\.\d+)?)$|^(\d+)$", first_expr.strip())
    if const_match:
        # Variable is always set to a constant — can't change it via inputs
        # But maybe we can skip the paragraph call that does this
        return {}

    # Case 3: Arithmetic — state['X'] = _to_num(A) OP _to_num(B)
    # Extract the operation and operands
    arith_pat = re.compile(
        r"_to_num\(state\.get\('([A-Z][A-Z0-9_-]*)'"
    )
    operand_vars = arith_pat.findall(first_expr)

    if operand_vars:
        from .static_analysis import _parse_condition_variables
        try:
            parsed = _parse_condition_variables(
                branch_meta_entry.get("condition", "")
            )
        except Exception:
            parsed = []

        # Determine what value condition_var needs
        target_val = None
        need_nonzero = False
        need_zero = False
        need_greater = None
        need_equal = None

        cond_text = branch_meta_entry.get("condition", "")
        is_greater = "GREATER" in cond_text.upper() or ">" in cond_text

        for pvar, vals, neg in parsed:
            effective_neg = neg ^ negate
            if vals:
                if not effective_neg:
                    target_val = vals[0]
                    if isinstance(target_val, (int, float)) and target_val == 0:
                        need_zero = True
                    elif isinstance(target_val, (int, float)):
                        if is_greater:
                            need_greater = target_val
                        else:
                            need_equal = target_val
                else:
                    if isinstance(vals[0], (int, float)) and vals[0] == 0:
                        need_nonzero = True
                    else:
                        target_val = vals[0]
                        if is_greater:
                            # Negated GREATER means need <= val
                            need_equal = 0  # try zero
                        else:
                            need_nonzero = True

        # For modulo: A % B = target (REMAINDER)
        if " % " in first_expr and operand_vars:
            mod_match = re.search(r'%\s*\(?(\d+)', first_expr)
            modulus = int(mod_match.group(1)) if mod_match else 4
            if need_zero:
                # Need X % modulus == 0, so X must be a multiple
                result[operand_vars[0]] = modulus * 500  # e.g., 2000 for %4
            elif need_nonzero or need_equal:
                target_n = need_equal if need_equal else 1
                # Need X % modulus == target_n
                result[operand_vars[0]] = modulus * 500 + int(target_n)
            return result

        # For floor division: A // B = target
        if " // " in first_expr and operand_vars:
            div_match = re.search(r'//\s*\(?(\d+)', first_expr)
            divisor = int(div_match.group(1)) if div_match else 1
            if need_nonzero or need_greater or (need_equal and need_equal != 0):
                target_n = need_greater or need_equal or 1
                # Need A // divisor > target_n, so A > target_n * divisor
                for ov in operand_vars:
                    result[ov] = (int(target_n) + 1) * divisor
            elif need_zero:
                for ov in operand_vars:
                    result[ov] = 0
            return result

        # For multiplication: A * B = target
        if " * " in first_expr and operand_vars:
            if need_nonzero or need_greater or (need_equal and need_equal != 0):
                # Set all operands to non-zero values
                target_n = need_greater or need_equal or 100
                val = max(100, int(abs(target_n)) + 1)
                for ov in operand_vars:
                    cur = base_state.get(ov, 0)
                    try:
                        cur_num = float(cur) if cur else 0
                    except (ValueError, TypeError):
                        cur_num = 0
                    if cur_num == 0:
                        result[ov] = val
                    # Also check deeper chain for this operand
                    for cvar, cexpr in chain[1:]:
                        if cvar == ov:
                            inner_ops = arith_pat.findall(cexpr)
                            for iov in inner_ops:
                                cur2 = base_state.get(iov, 0)
                                try:
                                    cur2_num = float(cur2) if cur2 else 0
                                except (ValueError, TypeError):
                                    cur2_num = 0
                                if cur2_num == 0:
                                    result[iov] = val
            elif need_zero:
                # Set one operand to zero
                if operand_vars:
                    result[operand_vars[0]] = 0

        # For division: A / B = target
        elif " / " in first_expr:
            if need_nonzero or need_greater or (need_equal and need_equal != 0):
                # Need numerator large enough that division produces nonzero
                div_match = re.search(r'/\s*\(?(\d+)', first_expr)
                divisor = int(div_match.group(1)) if div_match else 1
                target_n = need_greater or need_equal or 1
                for ov in operand_vars:
                    result[ov] = divisor * (int(abs(target_n)) + 1)
            elif need_zero:
                for ov in operand_vars:
                    result[ov] = 0

        # For addition: A + B = target
        elif " + " in first_expr:
            if need_nonzero or need_greater or (need_equal and need_equal != 0):
                target_n = need_greater or need_equal or 100
                for ov in operand_vars:
                    result[ov] = int(abs(target_n)) + 1
            elif need_zero:
                for ov in operand_vars:
                    result[ov] = 0

        # For subtraction: A - B = target
        elif " - " in first_expr:
            if need_nonzero or need_greater:
                target_n = need_greater or 100
                if len(operand_vars) >= 2:
                    result[operand_vars[0]] = int(abs(target_n)) + 200
                    result[operand_vars[1]] = 0
                elif operand_vars:
                    result[operand_vars[0]] = int(abs(target_n)) + 200
            elif need_zero:
                if len(operand_vars) >= 2:
                    result[operand_vars[0]] = 100
                    result[operand_vars[1]] = 100

    # Case 4: Round/int truncation wrapping arithmetic
    round_match = re.match(r"round\((.*)\)$|int\((.*)\)$", first_expr.strip())
    if round_match and not result:
        inner = round_match.group(1) or round_match.group(2)
        operand_vars2 = arith_pat.findall(inner)
        if operand_vars2:
            for ov in operand_vars2:
                cur = base_state.get(ov, 0)
                try:
                    cur_num = float(cur) if cur else 0
                except (ValueError, TypeError):
                    cur_num = 0
                if cur_num == 0:
                    result[ov] = 10000  # large enough to survive truncation

    return result


def _run_layer_38(
    module, program, var_report, stub_mapping,
    synth: SynthesisState, store_path: Path,
    start_time: float, max_time: float | None,
) -> int:
    """Dataflow Constraint Propagation.

    For each uncovered branch, parses the paragraph's generated Python to
    build a dataflow graph, then traces backward from the condition variable
    through intermediate computations to find the actual input variables
    that need specific values. Handles MOVE chains, arithmetic, and
    stub-derived values.
    """
    import re

    new_count = 0

    branch_meta = getattr(module, "_BRANCH_META", {})
    if not branch_meta:
        _record_layer_done(synth, store_path, 38)
        return 0

    base_defaults = (
        _generate_stub_defaults(stub_mapping, var_report)
        if stub_mapping else {}
    )

    # Build paragraph -> best base TC map (prefer TCs with most branches)
    para_to_tc: dict[str, TestCase] = {}
    for tc in synth.test_cases:
        for p in tc.paragraphs_covered:
            if p not in para_to_tc or len(tc.branches_covered) > len(para_to_tc[p].branches_covered):
                para_to_tc[p] = tc

    # Identify paragraphs that need direct invocation
    direct_paras: set[str] = set()
    run_paras: set[str] = set()
    for tc in synth.test_cases:
        if tc.target.startswith("direct:"):
            direct_paras.update(tc.paragraphs_covered)
        else:
            run_paras.update(tc.paragraphs_covered)
    direct_only = direct_paras - run_paras

    # Cache dataflow extractions per paragraph
    df_cache: dict[str, tuple] = {}

    # Group uncovered branches by paragraph
    from collections import defaultdict
    para_branches: dict[str, list[tuple[int, bool]]] = defaultdict(list)
    for abs_id, meta in branch_meta.items():
        para = meta.get("paragraph", "")
        if not para or para not in synth.covered_paras:
            continue
        for negate in (False, True):
            target_id = -abs_id if negate else abs_id
            if target_id not in synth.covered_branches:
                para_branches[para].append((abs_id, negate))

    log.info(
        "Layer 38: %d paragraphs with %d uncovered branch directions to analyze",
        len(para_branches),
        sum(len(v) for v in para_branches.values()),
    )

    for para, branch_list in sorted(para_branches.items(),
                                     key=lambda x: -len(x[1])):
        if _time_exceeded(start_time, max_time):
            break

        # Extract dataflow for this paragraph (cached)
        if para not in df_cache:
            df_cache[para] = _extract_paragraph_dataflow(module, para)
        assignments, branch_checks = df_cache[para]

        if not assignments and not branch_checks:
            continue

        use_direct = para in direct_only
        base_tc = para_to_tc.get(para)
        if base_tc is None and synth.test_cases:
            base_tc = synth.test_cases[0]

        base_state = dict(base_tc.input_state) if base_tc else {}
        base_stubs = (
            dict(base_tc.stub_outcomes) if base_tc and base_tc.stub_outcomes
            else {}
        )

        for abs_id, negate in branch_list:
            if _time_exceeded(start_time, max_time):
                break

            target_id = -abs_id if negate else abs_id
            if target_id in synth.covered_branches:
                continue

            target_key = f"branch:{target_id}"
            if _was_attempted(synth, 38, target_key):
                continue

            meta = branch_meta[abs_id]
            condition = meta.get("condition", "")

            # Find the branch check line
            branch_line = None
            for line_idx, bid, cond_line, indent in branch_checks:
                if bid == abs_id or bid == -abs_id:
                    branch_line = line_idx
                    break

            if branch_line is None:
                _record_attempt(synth, store_path, 38, target_key)
                continue

            # Parse condition to get the variable
            from .static_analysis import _parse_condition_variables
            try:
                parsed = _parse_condition_variables(condition)
            except Exception:
                _record_attempt(synth, store_path, 38, target_key)
                continue

            found = False
            for pvar, vals, neg in parsed:
                # Trace backward from this variable
                chain = _trace_backward(pvar, branch_line, assignments)

                # If no chain in this paragraph, try inter-procedural:
                # look at sub-paragraph calls before the branch and check
                # if any of them assign the condition variable
                if not chain:
                    chain = _trace_interprocedural(
                        module, pvar, branch_line, assignments,
                        branch_checks, df_cache,
                    )

                if not chain:
                    continue  # No intermediate computation found

                # Check if the chain involves a stub
                has_stub = any(
                    "__STUB__" in adeps
                    for aline, avar, _aexpr, adeps in assignments
                    if aline < branch_line and avar == pvar
                )

                # Solve backward constraints
                overrides = _solve_backward_constraint(
                    pvar, condition, chain, negate, meta,
                    var_report, base_state,
                )

                if not overrides and not has_stub:
                    continue

                # Build candidate state
                state = dict(base_state)
                state.update(overrides)

                # Also try to set the condition variable directly
                # (some chains have conditional assignments that might not execute)
                effective_neg = neg ^ negate
                if vals:
                    if not effective_neg:
                        state[pvar] = vals[0]
                    else:
                        if isinstance(vals[0], str):
                            state[pvar] = "__NOMATCH__"
                        elif isinstance(vals[0], (int, float)):
                            state[pvar] = vals[0] + 99999
                        else:
                            state[pvar] = "__NOMATCH__"

                # Try multiple variations
                for attempt in range(5):
                    trial_state = dict(state)
                    trial_stubs = dict(base_stubs)

                    if attempt == 1:
                        # Variation: amplify numeric overrides
                        for k, v in overrides.items():
                            if isinstance(v, (int, float)) and v != 0:
                                trial_state[k] = v * 10
                    elif attempt == 2:
                        # Variation: don't set condition var directly
                        # (let computation produce it)
                        if pvar in trial_state and pvar in [c[0] for c in chain]:
                            del trial_state[pvar]
                    elif attempt == 3:
                        # Variation: set condition var to large value
                        # (for GREATER conditions)
                        trial_state[pvar] = 999999
                        for k, v in overrides.items():
                            if isinstance(v, (int, float)):
                                trial_state[k] = v * 100
                    elif attempt == 4:
                        # Variation: only set overrides, no direct condition var
                        trial_state = dict(base_state)
                        trial_state.update(overrides)

                    save_target = (
                        f"direct:{para}|{target_key}" if use_direct and para
                        else target_key
                    )

                    if use_direct and para:
                        paras, branches, edges = _execute_direct_and_collect(
                            module, para, trial_state, trial_stubs, base_defaults,
                        )
                    else:
                        paras, branches, edges = _execute_and_collect(
                            module, trial_state, trial_stubs, base_defaults,
                        )

                    if _maybe_save(synth, store_path, trial_state, trial_stubs,
                                   base_defaults, paras, branches, edges,
                                   layer=38, target=save_target):
                        new_count += 1
                        found = True
                        break

                if found:
                    break

            _record_attempt(synth, store_path, 38, target_key)

    _record_layer_done(synth, store_path, 38)
    return new_count


def _run_layer_4(
    module, program, var_report, stub_mapping,
    synth: SynthesisState, store_path: Path,
    start_time: float, max_time: float | None,
) -> int:
    """Systematically vary stub outcomes near uncovered branches.

    Uses direct paragraph invocation for branches in paragraphs that are
    only reachable that way (not through the main run() entry point).
    """
    new_count = 0

    branch_meta = getattr(module, "_BRANCH_META", {})
    if not branch_meta or not stub_mapping:
        _record_layer_done(synth, store_path, 4)
        return 0

    base_defaults = (
        _generate_stub_defaults(stub_mapping, var_report)
        if stub_mapping else {}
    )

    # Pre-generate all-success stubs once (expensive operation)
    all_success_stubs = (
        _generate_all_success_stubs(stub_mapping, var_report)
        if stub_mapping else {}
    )

    # Identify which TCs used direct invocation (for choosing execution mode)
    direct_paras: set[str] = set()
    run_paras: set[str] = set()
    for tc in synth.test_cases:
        if tc.target.startswith("direct:"):
            direct_paras.update(tc.paragraphs_covered)
        else:
            run_paras.update(tc.paragraphs_covered)
    # Paragraphs only reachable via direct invocation
    direct_only = direct_paras - run_paras

    # Build a map: paragraph -> best base TC
    para_to_tc: dict[str, TestCase] = {}
    for tc in synth.test_cases:
        for p in tc.paragraphs_covered:
            if p not in para_to_tc:
                para_to_tc[p] = tc

    for abs_id in sorted(branch_meta.keys()):
        if _time_exceeded(start_time, max_time):
            break

        for negate in (False, True):
            target_id = -abs_id if negate else abs_id
            if target_id in synth.covered_branches:
                continue

            target_key = f"stub-combo:{target_id}"
            if _was_attempted(synth, 4, target_key):
                continue

            meta = branch_meta[abs_id]
            para = meta.get("paragraph", "")
            if para and para not in synth.covered_paras:
                _record_attempt(synth, store_path, 4, target_key)
                continue

            use_direct = para in direct_only
            save_target = (
                f"direct:{para}|{target_key}" if use_direct and para
                else target_key
            )

            combos = _compute_stub_combinations(
                target_id, branch_meta, stub_mapping, var_report, program,
            )

            base_tc = para_to_tc.get(para)
            base_state = dict(base_tc.input_state) if base_tc else {}

            for combo in combos:
                if _time_exceeded(start_time, max_time):
                    break

                stubs = dict(all_success_stubs)
                stubs.update(combo)

                if use_direct and para:
                    paras, branches, edges = _execute_direct_and_collect(
                        module, para, base_state, stubs, base_defaults,
                    )
                else:
                    paras, branches, edges = _execute_and_collect(
                        module, base_state, stubs, base_defaults,
                    )
                if _maybe_save(synth, store_path, base_state, stubs, base_defaults,
                               paras, branches, edges, layer=4,
                               target=save_target):
                    new_count += 1
                    break

            _record_attempt(synth, store_path, 4, target_key)

    _record_layer_done(synth, store_path, 4)
    return new_count


# ---------------------------------------------------------------------------
# Layer 5: Targeted Refinement Walks
# ---------------------------------------------------------------------------

def _run_layer_5(
    module, var_report, stub_mapping,
    synth: SynthesisState, store_path: Path,
    start_time: float, max_time: float | None,
) -> int:
    """Squeeze incremental branch coverage via seeded mutation walks.

    Uses direct paragraph invocation for TCs originating from direct
    invocation, enabling branch exploration in paragraphs not reachable
    through the main run() entry point.
    """
    new_count = 0

    branch_meta = getattr(module, "_BRANCH_META", {})
    if not branch_meta:
        _record_layer_done(synth, store_path, 5)
        return 0

    base_defaults = (
        _generate_stub_defaults(stub_mapping, var_report)
        if stub_mapping else {}
    )

    for tc in list(synth.test_cases):
        if _time_exceeded(start_time, max_time):
            break

        # Skip TCs already walked in a previous run
        if tc.id in synth.progress.walked_tc_ids:
            continue

        # Find uncovered branches in this TC's covered paragraphs
        tc_paras = set(tc.paragraphs_covered)
        uncovered_in_reach = []
        for abs_id, meta in branch_meta.items():
            para = meta.get("paragraph", "")
            if para in tc_paras:
                for bid in (abs_id, -abs_id):
                    if bid not in synth.covered_branches:
                        uncovered_in_reach.append(bid)

        if not uncovered_in_reach:
            _record_walked(synth, store_path, tc.id)
            continue

        # Determine if this TC uses direct invocation
        use_direct = tc.target.startswith("direct:")
        direct_para = tc.target[len("direct:"):] if use_direct else None

        # Seeded RNG from TC id for determinism
        seed = int(hashlib.sha256(tc.id.encode()).hexdigest()[:8], 16)
        rng = random.Random(seed)

        best_state = dict(tc.input_state)
        best_stubs = dict(tc.stub_outcomes) if tc.stub_outcomes else {}

        no_improvement = 0
        for _round in range(100):
            if _time_exceeded(start_time, max_time):
                break
            if no_improvement >= 20:
                break

            # Mutate 1-3 variables or stubs per round
            state = dict(best_state)
            stubs = {k: [e if not isinstance(e, list) else list(e) for e in v]
                    for k, v in best_stubs.items()}
            n_mutations = rng.randint(1, 3)

            var_names = list(var_report.variables.keys())
            for _ in range(n_mutations):
                if var_names and rng.random() < 0.6:
                    name = rng.choice(var_names)
                    info = var_report.variables[name]
                    literals = info.condition_literals if hasattr(info, "condition_literals") else []
                    if literals:
                        state[name] = rng.choice(literals)
                    elif info.classification == "flag":
                        state[name] = rng.choice([True, False, "Y", "N"])
                    elif isinstance(state.get(name), int):
                        state[name] = rng.randint(-999, 999)
                    else:
                        state[name] = rng.choice(["", " ", "TEST", "00", "XX"])
                elif stub_mapping:
                    op_key = rng.choice(list(stub_mapping.keys()))
                    status_vars = stub_mapping[op_key]
                    svar = status_vars[0] if status_vars else None
                    if svar:
                        info = var_report.variables.get(svar)
                        literals = (info.condition_literals
                                   if info and hasattr(info, "condition_literals") else [])
                        if literals:
                            val = rng.choice(literals)
                        else:
                            val = rng.choice([0, "00", "10", 100])
                        stubs[op_key] = [[(svar, val)]] * 25

            if use_direct and direct_para:
                paras, branches, edges = _execute_direct_and_collect(
                    module, direct_para, state, stubs, base_defaults,
                )
            else:
                paras, branches, edges = _execute_and_collect(
                    module, state, stubs, base_defaults,
                )
            walk_target = (
                f"direct:{direct_para}|walk:{tc.id[:8]}"
                if use_direct and direct_para
                else f"walk:{tc.id[:8]}"
            )
            if _maybe_save(synth, store_path, state, stubs, base_defaults,
                           paras, branches, edges, layer=5,
                           target=walk_target):
                new_count += 1
                best_state = state
                best_stubs = stubs
                no_improvement = 0
            else:
                no_improvement += 1

        _record_walked(synth, store_path, tc.id)

    _record_layer_done(synth, store_path, 5)
    return new_count


# ---------------------------------------------------------------------------
# Layer 6: Branch Direction Flip
# ---------------------------------------------------------------------------

def _run_layer_6(
    module, program, var_report, stub_mapping,
    synth: SynthesisState, store_path: Path,
    start_time: float, max_time: float | None,
) -> int:
    """Flip branches where exactly one direction is covered.

    For each branch where only TRUE or only FALSE is covered, find TCs
    that reach the paragraph, then systematically try to flip the condition.
    Uses condition parsing + multiple value strategies.
    """
    import re

    new_count = 0
    branch_meta = getattr(module, "_BRANCH_META", {})
    if not branch_meta:
        _record_layer_done(synth, store_path, 6)
        return 0

    base_defaults = (
        _generate_stub_defaults(stub_mapping, var_report)
        if stub_mapping else {}
    )

    # Find flippable branches (one direction covered, other not)
    flippable: list[tuple[int, int, str]] = []  # (target_bid, covered_bid, para)
    for abs_id, meta in branch_meta.items():
        para = meta.get("paragraph", "")
        if not para or para not in synth.covered_paras:
            continue
        t_covered = abs_id in synth.covered_branches
        f_covered = -abs_id in synth.covered_branches
        if t_covered and not f_covered:
            flippable.append((-abs_id, abs_id, para))
        elif f_covered and not t_covered:
            flippable.append((abs_id, -abs_id, para))

    log.info("Layer 6: %d flippable branches", len(flippable))

    # Sort by paragraph (process all branches in same para together)
    flippable.sort(key=lambda x: x[2])

    # Build paragraph -> TCs map (top 3 TCs per paragraph)
    para_tcs: dict[str, list[TestCase]] = {}
    for tc in synth.test_cases:
        for p in tc.paragraphs_covered:
            if p not in para_tcs:
                para_tcs[p] = []
            if len(para_tcs[p]) < 5:
                para_tcs[p].append(tc)

    nesting_cache: dict[str, dict[int, list[int]]] = {}

    for target_bid, covered_bid, para in flippable:
        if _time_exceeded(start_time, max_time):
            break
        if target_bid in synth.covered_branches:
            continue

        target_key = f"flip6:{target_bid}"
        if _was_attempted(synth, 6, target_key):
            continue

        abs_id = abs(target_bid)
        meta = branch_meta.get(abs_id, {})
        condition = meta.get("condition", "")
        need_true = target_bid > 0

        # Get nesting chain
        if para not in nesting_cache:
            nesting_cache[para] = _extract_branch_nesting(module, para)
        nesting = nesting_cache[para]

        # Strategy 1: EVALUATE handling
        if meta.get("type") == "EVALUATE" and meta.get("subject"):
            subject = meta["subject"]
            when_val = condition
            tcs = para_tcs.get(para, synth.test_cases[:1])
            for tc in tcs:
                if _time_exceeded(start_time, max_time):
                    break
                state = dict(tc.input_state)
                stubs = dict(tc.stub_outcomes) if tc.stub_outcomes else {}
                if need_true:
                    if when_val == "OTHER":
                        state[subject] = -99999
                    elif when_val.startswith("'") and when_val.endswith("'"):
                        state[subject] = when_val[1:-1]
                    elif when_val.lstrip("+-").isdigit():
                        state[subject] = int(when_val)
                    else:
                        state[subject] = when_val
                else:
                    state[subject] = -99999  # unlikely to match
                if stub_mapping:
                    for op_key, svars in stub_mapping.items():
                        if subject in svars:
                            stubs[op_key] = [[(subject, state[subject])]] * 50
                use_direct = tc.target.startswith("direct:")
                if use_direct:
                    dp = tc.target.split("|")[0][len("direct:"):]
                    paras, branches, edges = _execute_direct_and_collect(
                        module, dp or para, state, stubs, base_defaults)
                else:
                    paras, branches, edges = _execute_and_collect(
                        module, state, stubs, base_defaults)
                if _maybe_save(synth, store_path, state, stubs, base_defaults,
                               paras, branches, edges, layer=6,
                               target=f"direct:{para}|{target_key}"):
                    new_count += 1
                    break
            _record_attempt(synth, store_path, 6, target_key)
            continue

        # Strategy 2: SEARCH handling
        if meta.get("type") == "SEARCH":
            m_search = re.match(r"SEARCH\s+(\S+)", condition)
            if m_search:
                table_name = m_search.group(1)
                search_key = f"SEARCH:{table_name}"
                want_found = need_true
                tcs = para_tcs.get(para, synth.test_cases[:1])
                for tc in tcs:
                    if _time_exceeded(start_time, max_time):
                        break
                    state = dict(tc.input_state)
                    stubs = dict(tc.stub_outcomes) if tc.stub_outcomes else {}
                    stubs[search_key] = [want_found] * 50
                    use_direct = tc.target.startswith("direct:")
                    if use_direct:
                        dp = tc.target.split("|")[0][len("direct:"):]
                        paras, branches, edges = _execute_direct_and_collect(
                            module, dp or para, state, stubs, base_defaults)
                    else:
                        paras, branches, edges = _execute_and_collect(
                            module, state, stubs, base_defaults)
                    if _maybe_save(synth, store_path, state, stubs, base_defaults,
                                   paras, branches, edges, layer=6,
                                   target=f"direct:{para}|{target_key}"):
                        new_count += 1
                        break
                _record_attempt(synth, store_path, 6, target_key)
                continue

        # Strategy 3: Condition variable manipulation
        parsed = _parse_condition_variables(condition)
        if not parsed:
            _record_attempt(synth, store_path, 6, target_key)
            continue

        # Detect var-to-var comparison
        cond_upper = condition.upper()
        is_gt = ("GREATER" in cond_upper or ">" in condition)
        is_lt = ("LESS" in cond_upper or "<" in condition)
        is_var_to_var = (len(parsed) >= 2
                         and all(v == [0] for _, v, _ in parsed))

        tcs = para_tcs.get(para, synth.test_cases[:1])
        found = False
        for tc in tcs:
            if found or _time_exceeded(start_time, max_time):
                break
            state = dict(tc.input_state)
            stubs = dict(tc.stub_outcomes) if tc.stub_outcomes else {}

            # Satisfy nesting chain
            chain = nesting.get(abs_id, [])
            for parent_bid in chain:
                parent_meta = branch_meta.get(abs(parent_bid), {})
                parent_cond = parent_meta.get("condition", "")
                if parent_cond:
                    pp = _parse_condition_variables(parent_cond)
                    p_need_true = parent_bid > 0
                    for pvar, pvals, pneg in pp:
                        eff_neg = pneg != (not p_need_true)
                        if not eff_neg and pvals:
                            state[pvar] = pvals[0]
                        elif eff_neg and pvals:
                            info = var_report.variables.get(pvar)
                            lits = (info.condition_literals
                                   if info and hasattr(info, "condition_literals")
                                   else [])
                            for lit in lits:
                                if lit not in pvals:
                                    state[pvar] = lit
                                    break
                            else:
                                state[pvar] = ("XX" if isinstance(
                                    pvals[0], str) else 999)

            # Set target condition variables
            for i, (pvar, pvals, pneg) in enumerate(parsed):
                eff_neg = pneg != (not need_true)
                if is_var_to_var and pvals == [0]:
                    other_var = (parsed[1][0] if i == 0
                                 else parsed[0][0])
                    other_val = state.get(other_var,
                                          base_defaults.get(other_var, ''))
                    if not eff_neg:
                        if is_gt:
                            try:
                                state[pvar] = int(other_val) + 100 if i == 0 else state.get(pvar, '')
                            except (ValueError, TypeError):
                                state[pvar] = 100 if i == 0 else 1
                        elif is_lt:
                            try:
                                state[pvar] = int(other_val) - 100 if i == 0 else state.get(pvar, '')
                            except (ValueError, TypeError):
                                state[pvar] = 1 if i == 0 else 100
                        else:
                            state[pvar] = other_val
                    else:
                        if is_gt:
                            try:
                                state[pvar] = int(other_val) - 100 if i == 0 else state.get(pvar, '')
                            except (ValueError, TypeError):
                                state[pvar] = 1 if i == 0 else 100
                        elif is_lt:
                            try:
                                state[pvar] = int(other_val) + 100 if i == 0 else state.get(pvar, '')
                            except (ValueError, TypeError):
                                state[pvar] = 100 if i == 0 else 1
                        else:
                            if isinstance(other_val, int):
                                state[pvar] = other_val + 99999
                            elif isinstance(other_val, str) and other_val:
                                state[pvar] = other_val + '_DIFF'
                            else:
                                state[pvar] = '__NOMATCH__'
                elif not eff_neg and pvals:
                    state[pvar] = pvals[0]
                elif eff_neg and pvals:
                    info = var_report.variables.get(pvar)
                    lits = (info.condition_literals
                           if info and hasattr(info, "condition_literals")
                           else [])
                    for lit in lits:
                        if lit not in pvals:
                            state[pvar] = lit
                            break
                    else:
                        state[pvar] = ("XX" if isinstance(
                            pvals[0], str) else 999)

                # Set via stubs
                if stub_mapping:
                    for op_key, svars in stub_mapping.items():
                        if pvar in svars:
                            stubs[op_key] = [
                                [(pvar, state.get(pvar, 0))]
                            ] * 50

            use_direct = tc.target.startswith("direct:")
            if use_direct:
                dp = tc.target.split("|")[0][len("direct:"):]
                paras, branches, edges = _execute_direct_and_collect(
                    module, dp or para, state, stubs, base_defaults)
            else:
                paras, branches, edges = _execute_and_collect(
                    module, state, stubs, base_defaults)
            if _maybe_save(synth, store_path, state, stubs, base_defaults,
                           paras, branches, edges, layer=6,
                           target=f"direct:{para}|{target_key}"):
                new_count += 1
                found = True

        _record_attempt(synth, store_path, 6, target_key)

    _record_layer_done(synth, store_path, 6)
    return new_count


# ---------------------------------------------------------------------------
# Layer 7: Targeted Random Exploration per Paragraph
# ---------------------------------------------------------------------------

def _run_layer_7(
    module, var_report, stub_mapping,
    synth: SynthesisState, store_path: Path,
    start_time: float, max_time: float | None,
) -> int:
    """Aggressively explore high-gap paragraphs with random states.

    For each paragraph with many uncovered branches, run it many times
    with condition-aware random inputs. Uses condition literals and
    classification-based random values.
    """
    import random as _random
    import re

    new_count = 0
    branch_meta = getattr(module, "_BRANCH_META", {})
    if not branch_meta:
        _record_layer_done(synth, store_path, 7)
        return 0

    base_defaults = (
        _generate_stub_defaults(stub_mapping, var_report)
        if stub_mapping else {}
    )
    all_success_stubs = (
        _generate_all_success_stubs(stub_mapping, var_report)
        if stub_mapping else {}
    )

    # Find paragraphs with uncovered branches
    from collections import Counter
    para_uncov = Counter()
    para_uncov_bids: dict[str, list[int]] = {}
    for abs_id, meta in branch_meta.items():
        para = meta.get("paragraph", "")
        for d in (abs_id, -abs_id):
            if d not in synth.covered_branches:
                para_uncov[para] += 1
                if para not in para_uncov_bids:
                    para_uncov_bids[para] = []
                para_uncov_bids[para].append(abs_id)

    if not para_uncov:
        _record_layer_done(synth, store_path, 7)
        return 0

    # Collect condition variables and their literals per paragraph
    para_cond_vars: dict[str, dict[str, set]] = {}
    for para, bids in para_uncov_bids.items():
        cond_vars: dict[str, set] = {}
        for bid in bids:
            m = branch_meta.get(bid, {})
            cond = m.get("condition", "")
            if not cond:
                continue
            parsed = _parse_condition_variables(cond)
            for var, vals, neg in parsed:
                if var not in cond_vars:
                    cond_vars[var] = set()
                for v in vals:
                    cond_vars[var].add(v)
        para_cond_vars[para] = cond_vars

    default_state_fn = getattr(module, "_default_state", None)
    ds = default_state_fn() if default_state_fn else {}

    rng = _random.Random(7777)
    # Values for random generation
    str_vals = ['', ' ', 'Y', 'N', '00', '04', '05', '10',
                '001', '002', '013', '019', 'XX', 'I', 'T', 'R']
    int_vals = [0, 1, -1, 99, 100, 999, -999, 1000000]
    flag_vals = [True, False, 'Y', 'N', ' ', 'X']
    if synth.excluded_values:
        _excl = synth.excluded_values
        str_vals = [v for v in str_vals if v not in _excl and str(v) not in _excl] or ['']
        int_vals = [v for v in int_vals if v not in _excl and str(v) not in _excl] or [0]
        flag_vals = [v for v in flag_vals if v not in _excl and str(v) not in _excl] or [False]

    max_trials_per_para = 500

    # Sort by most uncovered first
    for para, uncov_count in para_uncov.most_common(50):
        if _time_exceeded(start_time, max_time):
            break
        if uncov_count < 3:
            break

        target_key = f"rand7:{para}"
        if _was_attempted(synth, 7, target_key):
            continue

        cond_vars = para_cond_vars.get(para, {})
        var_list = list(ds.keys())

        # Find best base TC for this paragraph
        best_tc = None
        for tc in synth.test_cases:
            if para in set(tc.paragraphs_covered):
                best_tc = tc
                break

        # Hill-climbing: track best state for this paragraph
        best_state = dict(best_tc.input_state) if best_tc else {}
        best_stubs = dict(best_tc.stub_outcomes) if best_tc and best_tc.stub_outcomes else dict(all_success_stubs)

        for trial in range(max_trials_per_para):
            if _time_exceeded(start_time, max_time):
                break

            # 70% of the time start from best state, 30% from scratch
            if rng.random() < 0.7:
                state = dict(best_state)
                stubs = {k: [e if not isinstance(e, list) else list(e) for e in v]
                         for k, v in best_stubs.items()}
            else:
                state = dict(best_tc.input_state) if best_tc else {}
                stubs = dict(best_tc.stub_outcomes) if best_tc and best_tc.stub_outcomes else dict(all_success_stubs)

            # Set condition variables to their known literals (or random)
            for var, literals in cond_vars.items():
                lit_list = list(literals)
                r = rng.random()
                if r < 0.4 and lit_list:
                    state[var] = rng.choice(lit_list)
                elif r < 0.6:
                    info = var_report.variables.get(var)
                    if info and info.classification == "flag":
                        state[var] = rng.choice(flag_vals)
                    elif isinstance(ds.get(var), int):
                        state[var] = rng.choice(int_vals)
                    else:
                        state[var] = rng.choice(str_vals)
                # else: leave at default/base value

            # Also perturb a few random vars
            n_extra = rng.randint(1, 8)
            for _ in range(n_extra):
                var = rng.choice(var_list) if var_list else None
                if var and var not in cond_vars:
                    val = ds.get(var)
                    if isinstance(val, int):
                        state[var] = rng.choice(int_vals)
                    elif isinstance(val, str):
                        state[var] = rng.choice(str_vals)

            # Occasionally perturb stubs too
            if stub_mapping and rng.random() < 0.3:
                op_key = rng.choice(list(stub_mapping.keys()))
                svars = stub_mapping[op_key]
                if svars:
                    svar = svars[0]
                    info = var_report.variables.get(svar)
                    lits = (info.condition_literals
                           if info and hasattr(info, "condition_literals") else [])
                    sval = rng.choice(lits) if lits else rng.choice([0, "00", "10"])
                    stubs[op_key] = [[(svar, sval)]] * 25

            paras, branches, edges = _execute_direct_and_collect(
                module, para, state, stubs, base_defaults,
            )
            if _maybe_save(synth, store_path, state, stubs, base_defaults,
                           paras, branches, edges, layer=7,
                           target=f"direct:{para}|rand7:{trial}"):
                new_count += 1
                best_state = dict(state)
                best_stubs = {k: [e if not isinstance(e, list) else list(e) for e in v]
                              for k, v in stubs.items()}

        _record_attempt(synth, store_path, 7, target_key)

    _record_layer_done(synth, store_path, 7)
    return new_count


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def synthesize_test_set(
    module,
    program,
    var_report,
    call_graph,
    gating_conditions,
    stub_mapping,
    equality_constraints,
    store_path: str | Path,
    max_time_seconds: float | None = None,
    max_layers: int = 5,
    excluded_values: set | None = None,
) -> SynthesisReport:
    """Run the layered synthesis engine.

    Args:
        module: The loaded generated Python module.
        program: Parsed Program AST.
        var_report: VariableReport from extract_variables.
        call_graph: StaticCallGraph from build_static_call_graph.
        gating_conditions: Gating conditions map.
        stub_mapping: Operation → status variable mapping.
        equality_constraints: Equality constraints list.
        store_path: Path to JSONL test store file.
        max_time_seconds: Optional time limit.
        max_layers: Run only first N layers (default 5).
        excluded_values: Optional set of values to exclude from generated tests.

    Returns:
        SynthesisReport with coverage statistics.
    """
    store_path = Path(store_path)
    start_time = time.time()

    report = SynthesisReport()
    synth = SynthesisState()
    if excluded_values:
        synth.excluded_values = excluded_values

    # Load existing test cases and progress
    existing, progress = TestStore.load(store_path)
    synth.progress = progress
    if existing:
        log.info("Loaded %d existing test cases from %s", len(existing), store_path)
        if progress.completed_layers:
            log.info("Previously completed layers: %s",
                     sorted(progress.completed_layers))
        n_attempted = sum(len(v) for v in progress.attempted_targets.values())
        if n_attempted:
            log.info("Previously attempted targets: %d", n_attempted)
        if progress.walked_tc_ids:
            log.info("Previously walked TCs: %d", len(progress.walked_tc_ids))

        paras, branches, edges = TestStore.replay(module, existing)
        synth.test_cases = existing
        synth.covered_paras = paras
        synth.covered_branches = branches
        synth.covered_edges = edges
        log.info("Baseline: %d paras, %d branches", len(paras), len(branches))

    # Compute totals
    all_paras = {p.name for p in program.paragraphs}
    report.total_paras = len(all_paras)

    branch_meta = getattr(module, "_BRANCH_META", {})
    all_branch_ids = set()
    for bid in branch_meta:
        all_branch_ids.add(bid)
        all_branch_ids.add(-bid)
    report.total_branches = len(all_branch_ids)

    # Run layers (layer 25 = "2.5" = frontier expansion, runs after layer 2)
    layer_funcs = [
        (1, lambda: _run_layer_1(
            module, program, var_report, equality_constraints, stub_mapping,
            synth, store_path, start_time, max_time_seconds,
        )),
        (2, lambda: _run_layer_2(
            module, program, var_report, call_graph, gating_conditions,
            stub_mapping, equality_constraints,
            synth, store_path, start_time, max_time_seconds,
        )),
        (25, lambda: _run_layer_2_5(
            module, program, var_report, call_graph, gating_conditions,
            stub_mapping, equality_constraints,
            synth, store_path, start_time, max_time_seconds,
        )),
        (3, lambda: _run_layer_3(
            module, var_report, stub_mapping,
            synth, store_path, start_time, max_time_seconds,
        )),
        (35, lambda: _run_layer_35(
            module, program, var_report, stub_mapping,
            synth, store_path, start_time, max_time_seconds,
        )),
        (37, lambda: _run_layer_37(
            module, program, var_report, stub_mapping,
            synth, store_path, start_time, max_time_seconds,
        )),
        (38, lambda: _run_layer_38(
            module, program, var_report, stub_mapping,
            synth, store_path, start_time, max_time_seconds,
        )),
        (4, lambda: _run_layer_4(
            module, program, var_report, stub_mapping,
            synth, store_path, start_time, max_time_seconds,
        )),
        (5, lambda: _run_layer_5(
            module, var_report, stub_mapping,
            synth, store_path, start_time, max_time_seconds,
        )),
        (6, lambda: _run_layer_6(
            module, program, var_report, stub_mapping,
            synth, store_path, start_time, max_time_seconds,
        )),
        (7, lambda: _run_layer_7(
            module, var_report, stub_mapping,
            synth, store_path, start_time, max_time_seconds,
        )),
    ]

    initial_count = len(synth.test_cases)

    for layer_num, layer_fn in layer_funcs:
        # Layer 25 (2.5) and 35 (3.5) run within their surrounding layers
        effective_layer = {25: 3, 35: 4, 37: 4, 38: 4, 6: 5, 7: 5}.get(layer_num, layer_num)
        if effective_layer > max_layers:
            break
        if _time_exceeded(start_time, max_time_seconds):
            break

        # Skip fully completed layers from prior runs
        if layer_num in synth.progress.completed_layers:
            log.info("Layer %d: skipped (completed in prior run)", layer_num)
            report.skipped_layers.append(layer_num)
            report.layer_stats[layer_num] = 0
            continue

        log.info("Running Layer %d ...", layer_num)
        new = layer_fn()
        report.layer_stats[layer_num] = new
        log.info(
            "Layer %d done: %d new TCs, coverage: %d/%d paras, %d/%d branches",
            layer_num, new,
            len(synth.covered_paras), report.total_paras,
            len(synth.covered_branches), report.total_branches,
        )

    report.total_test_cases = len(synth.test_cases)
    report.new_test_cases = len(synth.test_cases) - initial_count
    report.covered_paras = len(synth.covered_paras)
    report.covered_branches = len(synth.covered_branches)
    report.elapsed_seconds = time.time() - start_time

    return report
