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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _execute_and_collect(
    module, input_state: dict, stub_outcomes: dict, stub_defaults: dict,
) -> tuple[list[str], list[int], list[tuple]]:
    """Run module with given inputs, return (paras, branches, edges)."""
    default_state_fn = getattr(module, "_default_state", None)
    state = default_state_fn() if default_state_fn else {}
    state.update(input_state)

    if stub_outcomes:
        state["_stub_outcomes"] = {
            k: [list(entry) for entry in v]
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
    new_paras = set(paras) - synth.covered_paras
    new_branches = set(branches) - synth.covered_branches
    new_edges = set(edges) - synth.covered_edges

    if not new_paras and not new_branches and not new_edges:
        return False

    tc_id = _compute_id(input_state, stub_outcomes)
    # Check for duplicate IDs
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


# ---------------------------------------------------------------------------
# Layer 1: All-Success Baseline
# ---------------------------------------------------------------------------

def _run_layer_1(
    module, var_report, equality_constraints, stub_mapping,
    synth: SynthesisState, store_path: Path,
    start_time: float, max_time: float | None,
) -> int:
    """Generate all-success baseline + deterministic variants."""
    new_count = 0

    # Base all-success state
    base_state = _generate_all_success_state(var_report, equality_constraints)
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


def _apply_gating_constraints(
    state: dict,
    constraints: list[GatingCondition],
    var_report,
) -> dict:
    """Apply gating constraints deterministically to a state."""
    state = dict(state)
    for gc in constraints:
        if not gc.negated and gc.values:
            # Set var to first value
            state[gc.variable] = gc.values[0]
        elif gc.negated and gc.values:
            # Pick first condition_literal NOT in the negated values
            info = var_report.variables.get(gc.variable)
            literals = (info.condition_literals if info and hasattr(info, "condition_literals")
                       else [])
            found = False
            for lit in literals:
                if lit not in gc.values:
                    state[gc.variable] = lit
                    found = True
                    break
            if not found:
                # Use a sentinel that's different from the gated values
                if isinstance(gc.values[0], int):
                    state[gc.variable] = gc.values[0] + 999
                elif isinstance(gc.values[0], str):
                    state[gc.variable] = "XX"
                else:
                    state[gc.variable] = "XX"
    return state


def _run_layer_2(
    module, program, var_report, call_graph, gating_conditions,
    stub_mapping, equality_constraints,
    synth: SynthesisState, store_path: Path,
    start_time: float, max_time: float | None,
) -> int:
    """For each uncovered paragraph, solve the full path of gating conditions."""
    new_count = 0

    all_paras = {p.name for p in program.paragraphs}
    uncovered = all_paras - synth.covered_paras

    # Compute path constraints for all uncovered, sort by path length
    targets = []
    for para in uncovered:
        pc = compute_path_constraints(para, call_graph, gating_conditions)
        if pc is not None:
            targets.append(pc)
    targets.sort(key=lambda pc: len(pc.path))

    base_defaults = (
        _generate_stub_defaults(stub_mapping, var_report)
        if stub_mapping else {}
    )

    for pc in targets:
        if _time_exceeded(start_time, max_time):
            break
        if pc.target in synth.covered_paras:
            continue  # covered by side-effect of earlier target
        if _was_attempted(synth, 2, pc.target):
            continue

        # Find best base test case
        base_tc = _find_best_base(synth, pc.path)
        base_state = dict(base_tc.input_state) if base_tc else (
            _generate_all_success_state(var_report, equality_constraints)
        )
        base_stubs = (
            dict(base_tc.stub_outcomes) if base_tc and base_tc.stub_outcomes
            else (_generate_all_success_stubs(stub_mapping, var_report)
                  if stub_mapping else {})
        )

        # Apply gating constraints
        state = _apply_gating_constraints(base_state, pc.constraints, var_report)

        paras, branches, edges = _execute_and_collect(
            module, state, base_stubs, base_defaults,
        )
        if _maybe_save(synth, store_path, state, base_stubs, base_defaults,
                       paras, branches, edges, layer=2, target=pc.target):
            new_count += 1

        # Also generate error variant for stub operations in the target paragraph
        if stub_mapping:
            for op_key, status_vars in stub_mapping.items():
                if _time_exceeded(start_time, max_time):
                    break
                error_stubs = dict(base_stubs)
                for svar in status_vars:
                    info = var_report.variables.get(svar)
                    literals = (info.condition_literals
                               if info and hasattr(info, "condition_literals") else [])
                    for lit in literals[1:]:  # skip first (success) value
                        stub_target = f"{pc.target}:{op_key}={lit}"
                        if _was_attempted(synth, 2, stub_target):
                            continue
                        error_entry = [(svar, lit)]
                        error_stubs[op_key] = [error_entry] * 25
                        paras, branches, edges = _execute_and_collect(
                            module, state, error_stubs, base_defaults,
                        )
                        if _maybe_save(synth, store_path, state, error_stubs,
                                       base_defaults, paras, branches, edges,
                                       layer=2, target=stub_target):
                            new_count += 1
                        _record_attempt(synth, store_path, 2, stub_target)

        _record_attempt(synth, store_path, 2, pc.target)

    # For unreachable paragraphs, try running directly
    still_uncovered = all_paras - synth.covered_paras
    for para in still_uncovered:
        if _time_exceeded(start_time, max_time):
            break
        if call_graph.path_to(para) is not None:
            continue  # reachable but constraint solving failed

        direct_target = f"direct:{para}"
        if _was_attempted(synth, 2, direct_target):
            continue

        base_state = _generate_all_success_state(var_report, equality_constraints)
        try:
            rs = _run_paragraph_directly(module, para, base_state)
            trace = rs.get("_trace", [para])
            branches = list(rs.get("_branches", set()))
            paras_list = list(dict.fromkeys(trace)) if trace else [para]
            edges_list = [
                (trace[j], trace[j + 1])
                for j in range(len(trace) - 1)
                if trace[j] != trace[j + 1]
            ] if trace else []
            if _maybe_save(synth, store_path, base_state, {}, {},
                           paras_list, branches, edges_list,
                           layer=2, target=direct_target):
                new_count += 1
        except Exception:
            pass
        _record_attempt(synth, store_path, 2, direct_target)

    _record_layer_done(synth, store_path, 2)
    return new_count


# ---------------------------------------------------------------------------
# Layer 3: Branch-Level Solving
# ---------------------------------------------------------------------------

def _run_layer_3(
    module, var_report, stub_mapping,
    synth: SynthesisState, store_path: Path,
    start_time: float, max_time: float | None,
) -> int:
    """For each uncovered branch in reached paragraphs, find inputs that flip it."""
    new_count = 0

    branch_meta = getattr(module, "_BRANCH_META", {})
    if not branch_meta:
        return 0

    base_defaults = (
        _generate_stub_defaults(stub_mapping, var_report)
        if stub_mapping else {}
    )

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

        # Check which directions are uncovered
        for negate in (False, True):
            target_id = -abs_id if negate else abs_id
            if target_id in synth.covered_branches:
                continue

            target_key = f"branch:{target_id}"
            if _was_attempted(synth, 3, target_key):
                continue

            # Find base test case that reaches this paragraph
            base_tc = None
            for tc in synth.test_cases:
                if para in tc.paragraphs_covered:
                    base_tc = tc
                    break
            if base_tc is None and synth.test_cases:
                base_tc = synth.test_cases[0]

            base_state = dict(base_tc.input_state) if base_tc else {}
            base_stubs = (
                dict(base_tc.stub_outcomes) if base_tc and base_tc.stub_outcomes
                else {}
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

                    paras, branches, edges = _execute_and_collect(
                        module, state, stubs, base_defaults,
                    )
                    if _maybe_save(synth, store_path, state, stubs, base_defaults,
                                   paras, branches, edges, layer=3,
                                   target=target_key):
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
                for var, vals, neg in parsed:
                    effective_neg = neg != negate  # flip if we're negating
                    if not effective_neg and vals:
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

                paras, branches, edges = _execute_and_collect(
                    module, state, base_stubs, base_defaults,
                )
                if _maybe_save(synth, store_path, state, base_stubs, base_defaults,
                               paras, branches, edges, layer=3,
                               target=target_key):
                    new_count += 1

            _record_attempt(synth, store_path, 3, target_key)

    _record_layer_done(synth, store_path, 3)
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


def _run_layer_4(
    module, program, var_report, stub_mapping,
    synth: SynthesisState, store_path: Path,
    start_time: float, max_time: float | None,
) -> int:
    """Systematically vary stub outcomes near uncovered branches."""
    new_count = 0

    branch_meta = getattr(module, "_BRANCH_META", {})
    if not branch_meta or not stub_mapping:
        return 0

    base_defaults = (
        _generate_stub_defaults(stub_mapping, var_report)
        if stub_mapping else {}
    )

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

            combos = _compute_stub_combinations(
                target_id, branch_meta, stub_mapping, var_report, program,
            )

            # Find base state
            base_tc = None
            for tc in synth.test_cases:
                if para in tc.paragraphs_covered:
                    base_tc = tc
                    break

            base_state = dict(base_tc.input_state) if base_tc else {}

            for combo in combos:
                if _time_exceeded(start_time, max_time):
                    break

                # Merge combo with all-success base stubs
                stubs = (
                    dict(_generate_all_success_stubs(stub_mapping, var_report))
                    if stub_mapping else {}
                )
                stubs.update(combo)

                paras, branches, edges = _execute_and_collect(
                    module, base_state, stubs, base_defaults,
                )
                if _maybe_save(synth, store_path, base_state, stubs, base_defaults,
                               paras, branches, edges, layer=4,
                               target=target_key):
                    new_count += 1
                    break  # found new coverage, move to next branch

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
    """Squeeze incremental branch coverage via seeded mutation walks."""
    new_count = 0

    branch_meta = getattr(module, "_BRANCH_META", {})
    if not branch_meta:
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

        # Seeded RNG from TC id for determinism
        seed = int(hashlib.sha256(tc.id.encode()).hexdigest()[:8], 16)
        rng = random.Random(seed)

        best_state = dict(tc.input_state)
        best_stubs = dict(tc.stub_outcomes) if tc.stub_outcomes else {}

        for _round in range(20):
            if _time_exceeded(start_time, max_time):
                break

            # Mutate one variable or one stub
            state = dict(best_state)
            stubs = {k: [list(e) for e in v] for k, v in best_stubs.items()}

            var_names = list(var_report.variables.keys())
            if var_names and rng.random() < 0.6:
                # Mutate a variable
                name = rng.choice(var_names)
                info = var_report.variables[name]
                literals = info.condition_literals if hasattr(info, "condition_literals") else []
                if literals:
                    state[name] = rng.choice(literals)
                elif info.classification == "flag":
                    state[name] = rng.choice([True, False])
                elif isinstance(state.get(name), int):
                    state[name] = rng.randint(-999, 999)
                else:
                    state[name] = rng.choice(["", " ", "TEST", "00", "XX"])
            elif stub_mapping:
                # Mutate a stub outcome
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

            paras, branches, edges = _execute_and_collect(
                module, state, stubs, base_defaults,
            )
            if _maybe_save(synth, store_path, state, stubs, base_defaults,
                           paras, branches, edges, layer=5,
                           target=f"walk:{tc.id[:8]}"):
                new_count += 1
                best_state = state
                best_stubs = stubs

        _record_walked(synth, store_path, tc.id)

    _record_layer_done(synth, store_path, 5)
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

    Returns:
        SynthesisReport with coverage statistics.
    """
    store_path = Path(store_path)
    start_time = time.time()

    report = SynthesisReport()
    synth = SynthesisState()

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

    # Run layers
    layer_funcs = [
        (1, lambda: _run_layer_1(
            module, var_report, equality_constraints, stub_mapping,
            synth, store_path, start_time, max_time_seconds,
        )),
        (2, lambda: _run_layer_2(
            module, program, var_report, call_graph, gating_conditions,
            stub_mapping, equality_constraints,
            synth, store_path, start_time, max_time_seconds,
        )),
        (3, lambda: _run_layer_3(
            module, var_report, stub_mapping,
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
    ]

    initial_count = len(synth.test_cases)

    for layer_num, layer_fn in layer_funcs:
        if layer_num > max_layers:
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
