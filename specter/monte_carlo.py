"""Monte Carlo analysis of generated Python code.

Runs multiple iterations with randomized input parameters to explore
execution paths, branch coverage, and external call patterns.
"""

from __future__ import annotations

import importlib.util
import random
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class IterationResult:
    """Result of a single Monte Carlo iteration."""

    iteration: int
    initial_state: dict
    final_state: dict
    display_output: list[str]
    calls_made: list[dict]
    execs_made: list[dict]
    reads: list[str]
    writes: list[str]
    abended: bool
    error: str | None = None
    trace: list[str] | None = None
    var_writes: list[tuple[str, str]] | None = None
    var_reads: list[tuple[str, str]] | None = None
    state_diffs: dict | None = None


@dataclass
class MonteCarloReport:
    """Aggregated results from Monte Carlo analysis."""

    n_iterations: int
    n_successful: int = 0
    n_errors: int = 0
    n_abended: int = 0
    call_frequency: dict[str, int] = field(default_factory=dict)
    exec_frequency: dict[str, int] = field(default_factory=dict)
    display_patterns: dict[str, int] = field(default_factory=dict)
    variable_distributions: dict[str, Counter] = field(default_factory=dict)
    error_messages: list[str] = field(default_factory=list)
    iterations: list[IterationResult] = field(default_factory=list)
    analysis_report: object | None = None

    def summary(self) -> str:
        lines = [
            f"Monte Carlo Analysis: {self.n_iterations} iterations",
            f"  Successful: {self.n_successful}",
            f"  Errors: {self.n_errors}",
            f"  Abended: {self.n_abended}",
            "",
            "External Calls:",
        ]
        for name, count in sorted(self.call_frequency.items(),
                                   key=lambda x: -x[1]):
            lines.append(f"  {name}: {count}")

        lines.append("")
        lines.append("Exec Blocks:")
        for kind, count in sorted(self.exec_frequency.items(),
                                   key=lambda x: -x[1]):
            lines.append(f"  {kind}: {count}")

        lines.append("")
        lines.append("Display Patterns (top 20):")
        sorted_displays = sorted(self.display_patterns.items(),
                                  key=lambda x: -x[1])[:20]
        for msg, count in sorted_displays:
            truncated = msg[:80] if len(msg) > 80 else msg
            lines.append(f"  [{count}x] {truncated}")

        if self.error_messages:
            lines.append("")
            lines.append("Errors (unique):")
            for msg in sorted(set(self.error_messages))[:10]:
                lines.append(f"  {msg[:100]}")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Input parameter generation
# ---------------------------------------------------------------------------

# Known status code values for different categories
_STATUS_VALUES = {
    "file": [" ", "00", "10", "21", "30", "35", "41", "42", "43", "44", "46", "47", "48", "49"],
    "ims": [" ", "  ", "II", "GE", "GB", "AI"],
    "sql": [0, 100, -803, -805, -811, -904, -911, -913],
    "cics": [0, 1, 12, 13, 16, 22, 26, 27, 70, 84],
}


def _generate_random_state(var_report, rng: random.Random) -> dict:
    """Generate a randomized initial state based on variable classification."""
    state = {}

    for name, info in var_report.variables.items():
        upper = name.upper()
        harvested = info.condition_literals if hasattr(info, "condition_literals") else []

        if info.classification == "status":
            # 80% success bias — most programs need success defaults
            # to survive initialization before interesting divergence
            if rng.random() < 0.8:
                # Use first harvested literal as success value when available
                if harvested:
                    state[name] = harvested[0]
                elif "SQLCODE" in upper or "SQLSTATE" in upper:
                    state[name] = 0
                elif "PCB" in upper and "STATUS" in upper:
                    state[name] = " "
                elif "EIBRESP" in upper:
                    state[name] = 0
                elif "STATUS" in upper or upper.startswith("FS-"):
                    state[name] = "00"
                elif "RETURN-CODE" in upper or upper.endswith("-RC"):
                    state[name] = 0
                else:
                    state[name] = "00"
            elif harvested:
                state[name] = rng.choice(harvested)
            elif "SQLCODE" in upper or "SQLSTATE" in upper:
                state[name] = rng.choice(_STATUS_VALUES["sql"])
            elif "PCB" in upper and "STATUS" in upper:
                state[name] = rng.choice(_STATUS_VALUES["ims"])
            elif "EIBRESP" in upper:
                state[name] = rng.choice(_STATUS_VALUES["cics"])
            elif "EIBAID" in upper:
                state[name] = rng.choice(["DFHENTER", "DFHPF3", "DFHPF7", "DFHPF8", "DFHCLEAR"])
            elif "STATUS" in upper or upper.startswith("FS-"):
                state[name] = rng.choice(_STATUS_VALUES["file"])
            elif "RETURN-CODE" in upper or upper.endswith("-RC"):
                state[name] = rng.choice([0, "0000", "00"])
            else:
                state[name] = rng.choice([" ", "00", "10"])

        elif info.classification == "flag":
            if harvested and rng.random() < 0.7:
                state[name] = rng.choice(harvested)
            else:
                state[name] = rng.choice([True, False])

        elif info.classification == "input":
            if harvested and rng.random() < 0.7:
                state[name] = rng.choice(harvested)
            # Heuristic: check name patterns
            elif "DATE" in upper or "YYDDD" in upper:
                state[name] = f"{rng.randint(20, 25):02d}{rng.randint(1, 12):02d}{rng.randint(1, 28):02d}"
            elif "TIME" in upper:
                state[name] = f"{rng.randint(0, 23):02d}{rng.randint(0, 59):02d}{rng.randint(0, 59):02d}"
            elif "KEY" in upper or "NUM" in upper or "ID" in upper:
                state[name] = str(rng.randint(10000, 99999))
            elif "CNT" in upper or "COUNT" in upper or "FREQ" in upper:
                state[name] = rng.randint(0, 100)
            elif "AMT" in upper or "AMOUNT" in upper:
                state[name] = rng.randint(0, 10000)
            elif "DAYS" in upper:
                state[name] = rng.randint(1, 30)
            elif "FLAG" in upper or "FLG" in upper:
                state[name] = rng.choice(["Y", "N"])
            elif harvested:
                state[name] = rng.choice(harvested)
            else:
                state[name] = rng.choice(["", " ", "TEST", "A", "12345"])

        elif info.classification == "internal" and harvested:
            # Internals normally get no initial value, but if we have
            # harvested literals they're worth seeding.
            if rng.random() < 0.5:
                state[name] = rng.choice(harvested)

    return state


# ---------------------------------------------------------------------------
# Coverage-guided fuzzing
# ---------------------------------------------------------------------------

_MAX_CORPUS = 500
_MAX_FINGERPRINTS = 10000
_STALE_THRESHOLD = 1000
_STALE_RANDOM_BURST = 50
_ENERGY_UPDATE_INTERVAL = 100


@dataclass
class _CorpusEntry:
    input_state: dict
    coverage: frozenset  # paragraph names reached
    edges: frozenset     # (caller, callee) transitions
    energy: float = 1.0
    mutation_count: int = 0
    children_produced: int = 0
    added_at: int = 0
    stub_outcomes: dict | None = None


@dataclass
class _FuzzerState:
    corpus: list[_CorpusEntry] = field(default_factory=list)
    global_coverage: set[str] = field(default_factory=set)
    global_edges: set[tuple[str, str]] = field(default_factory=set)
    coverage_timeline: list[tuple[int, int]] = field(default_factory=list)
    stale_counter: int = 0
    n_successful: int = 0
    n_errors: int = 0
    n_abended: int = 0
    call_frequency: Counter = field(default_factory=Counter)
    exec_frequency: Counter = field(default_factory=Counter)
    display_patterns: Counter = field(default_factory=Counter)
    error_messages: list[str] = field(default_factory=list)
    recursion_fingerprints: set[frozenset] = field(default_factory=set)
    para_hits: Counter = field(default_factory=Counter)
    var_writes: Counter = field(default_factory=Counter)
    var_reads: Counter = field(default_factory=Counter)
    change_counts: Counter = field(default_factory=Counter)
    call_graph: dict[str, set[str]] = field(default_factory=dict)


def _should_add_to_corpus(fuzzer: _FuzzerState, coverage: frozenset, edges: frozenset) -> bool:
    new_paras = coverage - fuzzer.global_coverage
    new_edges = edges - fuzzer.global_edges
    return bool(new_paras or new_edges)


def _add_to_corpus(fuzzer: _FuzzerState, entry: _CorpusEntry) -> None:
    fuzzer.corpus.append(entry)
    fuzzer.global_coverage.update(entry.coverage)
    fuzzer.global_edges.update(entry.edges)
    fuzzer.stale_counter = 0
    fuzzer.coverage_timeline.append((entry.added_at, len(fuzzer.global_coverage)))

    if len(fuzzer.corpus) > _MAX_CORPUS:
        _evict_corpus(fuzzer)


def _evict_corpus(fuzzer: _FuzzerState) -> None:
    """Remove lowest-energy entry whose coverage is redundantly covered."""
    candidates = sorted(range(len(fuzzer.corpus)),
                        key=lambda i: fuzzer.corpus[i].energy)
    for idx in candidates:
        entry = fuzzer.corpus[idx]
        other_coverage: set[str] = set()
        for i, e in enumerate(fuzzer.corpus):
            if i != idx:
                other_coverage.update(e.coverage)
        if entry.coverage.issubset(other_coverage):
            fuzzer.corpus.pop(idx)
            return
    # No redundant entry — drop lowest energy
    fuzzer.corpus.pop(candidates[0])


def _select_seed(fuzzer: _FuzzerState, rng: random.Random) -> _CorpusEntry:
    """Weighted random selection by energy."""
    total = sum(e.energy for e in fuzzer.corpus)
    if total <= 0:
        return rng.choice(fuzzer.corpus)
    r = rng.random() * total
    cumulative = 0.0
    for entry in fuzzer.corpus:
        cumulative += entry.energy
        if cumulative >= r:
            return entry
    return fuzzer.corpus[-1]


def _update_energy(fuzzer: _FuzzerState, all_paragraphs: list[str]) -> None:
    """Recalculate energy for all corpus entries."""
    uncovered = set(all_paragraphs) - fuzzer.global_coverage

    # Frontier paragraphs: covered paragraphs that are callers in the call
    # graph (potential branch points with undiscovered callees).  Give extra
    # weight to callers whose known callees include uncovered paragraphs via
    # transitive edges.
    frontier_paras: set[str] = set()
    for caller, callees in fuzzer.call_graph.items():
        if caller in fuzzer.global_coverage:
            # If any callee is uncovered, this caller is directly frontier
            if callees & uncovered:
                frontier_paras.add(caller)
            else:
                # Caller is a branch point that might have more branches
                frontier_paras.add(caller)

    max_added = max((e.added_at for e in fuzzer.corpus), default=1) or 1

    for entry in fuzzer.corpus:
        energy = 1.0

        # Frontier bonus
        frontier_count = len(entry.coverage & frontier_paras)
        energy += frontier_count * 3.0

        # Recency bonus (0..1)
        energy += entry.added_at / max_added

        # Yield penalty
        if entry.mutation_count > 10 and entry.children_produced == 0:
            energy *= 0.1

        entry.energy = max(energy, 0.01)


def _fingerprint_state(state: dict, var_report) -> frozenset:
    """Fingerprint only status/flag variables (these control flow)."""
    items = []
    for name, info in var_report.variables.items():
        if info.classification in ("status", "flag"):
            val = state.get(name)
            if val is not None:
                items.append((name, val))
    return frozenset(items)


def _is_recursion_prone(fuzzer: _FuzzerState, state: dict, var_report) -> bool:
    if not fuzzer.recursion_fingerprints:
        return False
    fp = _fingerprint_state(state, var_report)
    return fp in fuzzer.recursion_fingerprints


def _generate_random_value(name: str, info, rng: random.Random):
    """Generate a single random value for a variable."""
    harvested = info.condition_literals if hasattr(info, "condition_literals") else []
    if harvested and rng.random() < 0.5:
        return rng.choice(harvested)

    upper = name.upper()
    if info.classification == "status":
        if "SQLCODE" in upper or "SQLSTATE" in upper:
            return rng.choice(_STATUS_VALUES["sql"])
        elif "PCB" in upper and "STATUS" in upper:
            return rng.choice(_STATUS_VALUES["ims"])
        elif "EIBRESP" in upper:
            return rng.choice(_STATUS_VALUES["cics"])
        elif "EIBAID" in upper:
            return rng.choice(["DFHENTER", "DFHPF3", "DFHPF7", "DFHPF8", "DFHCLEAR"])
        elif "STATUS" in upper or upper.startswith("FS-"):
            return rng.choice(_STATUS_VALUES["file"])
        elif "RETURN-CODE" in upper or upper.endswith("-RC"):
            return rng.choice([0, "0000", "00"])
        return rng.choice([" ", "00", "10"])

    elif info.classification == "flag":
        return rng.choice([True, False])

    elif info.classification == "input":
        if "DATE" in upper or "YYDDD" in upper:
            return f"{rng.randint(20, 25):02d}{rng.randint(1, 12):02d}{rng.randint(1, 28):02d}"
        elif "TIME" in upper:
            return f"{rng.randint(0, 23):02d}{rng.randint(0, 59):02d}{rng.randint(0, 59):02d}"
        elif "KEY" in upper or "NUM" in upper or "ID" in upper:
            return str(rng.randint(10000, 99999))
        elif "CNT" in upper or "COUNT" in upper or "FREQ" in upper:
            return rng.randint(0, 100)
        elif "AMT" in upper or "AMOUNT" in upper:
            return rng.randint(0, 10000)
        elif "DAYS" in upper:
            return rng.randint(1, 30)
        elif "FLAG" in upper or "FLG" in upper:
            return rng.choice(["Y", "N"])
        elif harvested:
            return rng.choice(harvested)
        return rng.choice(["", " ", "TEST", "A", "12345"])

    elif info.classification == "internal" and harvested:
        return rng.choice(harvested)

    return rng.choice(["", " ", "0"])


def _generate_stub_outcomes(
    stub_mapping: dict[str, list[str]],
    var_report,
    rng: random.Random,
) -> dict[str, list]:
    """Generate randomized stub outcomes for external operations.

    For each operation key in stub_mapping, pick status values:
    60% success bias, 40% random error/alternate values.
    Each outcome entry is a list of (var, val) pairs so that ALL
    status variables for an operation are set in a single invocation.

    Returns dict suitable for state['_stub_outcomes'].
    """
    outcomes: dict[str, list] = {}

    for op_key, status_vars in stub_mapping.items():
        # Build one outcome entry that sets ALL status vars for this op
        entry: list[tuple[str, object]] = []
        for svar in status_vars:
            harvested = []
            if var_report and svar in var_report.variables:
                harvested = var_report.variables[svar].condition_literals

            upper = svar.upper()
            # 60% success bias for stub outcomes
            if rng.random() < 0.6:
                if harvested:
                    val = harvested[0]
                elif "SQLCODE" in upper or "SQLSTATE" in upper:
                    val = 0
                elif "EIBRESP" in upper:
                    val = 0
                elif "STATUS" in upper or upper.startswith("FS-"):
                    val = "00"
                elif "RETURN-CODE" in upper or upper.endswith("-RC"):
                    val = 0
                else:
                    val = "00"
            else:
                if "SQLCODE" in upper or "SQLSTATE" in upper:
                    val = rng.choice(_STATUS_VALUES["sql"])
                elif "EIBRESP" in upper:
                    val = rng.choice(_STATUS_VALUES["cics"])
                elif "STATUS" in upper or upper.startswith("FS-"):
                    val = rng.choice(_STATUS_VALUES["file"])
                elif "RETURN-CODE" in upper or upper.endswith("-RC"):
                    val = rng.choice([0, 4, 8, 12, 16])
                else:
                    val = rng.choice([0, " ", "00"])
            entry.append((svar, val))

        # Determine repetition count based on operation type
        is_read = op_key.startswith("READ:")
        is_start = op_key.startswith("START:")
        is_sql = op_key == "SQL"
        is_call = op_key.startswith("CALL:")
        if is_read:
            n_reps = 5
        elif is_sql:
            n_reps = 20
        elif is_start or is_call:
            n_reps = 5
        else:
            n_reps = 3
        for _ in range(n_reps):
            outcomes.setdefault(op_key, []).append(list(entry))

    return outcomes


def _generate_all_success_state(var_report, equality_constraints=None) -> dict:
    """Generate a state where ALL status/flag variables are set to success values.

    This guarantees passage through initialization gauntlets where many
    sequential checks must all pass (e.g. OPEN file → IF status ≠ '00').
    If equality_constraints is provided, variables that must be equal
    are set to the same value.
    """
    state = {}
    for name, info in var_report.variables.items():
        upper = name.upper()
        harvested = info.condition_literals if hasattr(info, "condition_literals") else []

        if info.classification == "status":
            if harvested:
                state[name] = harvested[0]
            elif "SQLCODE" in upper or "SQLSTATE" in upper:
                state[name] = 0
            elif "PCB" in upper and "STATUS" in upper:
                state[name] = " "
            elif "EIBRESP" in upper:
                state[name] = 0
            elif "STATUS" in upper or upper.startswith("FS-"):
                state[name] = "00"
            elif "RETURN-CODE" in upper or upper.endswith("-RC"):
                state[name] = 0
            else:
                state[name] = "00"
        elif info.classification == "flag":
            if harvested:
                state[name] = harvested[0]
            else:
                state[name] = False
        elif info.classification == "input":
            # For counter/index variables, prefer a non-zero literal
            # since zero often means "no data loaded" (error condition).
            if harvested:
                non_zero = [v for v in harvested
                            if v not in (0, "0", "", " ", "0000")]
                state[name] = non_zero[0] if non_zero else harvested[0]
            elif "DATE" in upper or "YYDDD" in upper:
                state[name] = "250101"
            elif "TIME" in upper:
                state[name] = "120000"
            elif "KEY" in upper or "NUM" in upper or "ID" in upper:
                state[name] = "10001"
            elif "CNT" in upper or "COUNT" in upper or "FREQ" in upper:
                state[name] = 1
            elif "AMT" in upper or "AMOUNT" in upper:
                state[name] = 100
            else:
                state[name] = "TEST"
        elif info.classification == "internal" and harvested:
            non_zero = [v for v in harvested
                        if v not in (0, "0", "", " ")]
            state[name] = non_zero[0] if non_zero else harvested[0]

    # Apply equality constraints: set var_b = var_a for each constraint
    if equality_constraints:
        for ec in equality_constraints:
            a_val = state.get(ec.var_a)
            b_val = state.get(ec.var_b)
            if a_val is not None and b_val is not None:
                # Copy a -> b (or b -> a if b is already set more meaningfully)
                state[ec.var_b] = a_val

    return state


def _generate_all_success_stubs(
    stub_mapping: dict[str, list[str]],
    var_report,
) -> dict[str, list]:
    """Generate stub outcomes where every operation succeeds.

    For READ operations, provides multiple success outcomes followed by EOF
    to allow loops to complete naturally.  For SQL operations, provides
    a few success results then SQLCODE=100 (not found / end of cursor).
    Each outcome entry is a list of (var, val) pairs so that ALL
    status variables for an operation are set in a single invocation.
    """
    outcomes: dict[str, list] = {}
    for op_key, status_vars in stub_mapping.items():
        is_read = op_key.startswith("READ:")
        is_start = op_key.startswith("START:")
        is_sql = op_key == "SQL"

        # Build a success entry that sets ALL status vars
        success_entry: list[tuple[str, object]] = []
        eof_entry: list[tuple[str, object]] = []
        for svar in status_vars:
            harvested = []
            if var_report and svar in var_report.variables:
                harvested = var_report.variables[svar].condition_literals

            upper = svar.upper()
            if harvested:
                val = harvested[0]
            elif "SQLCODE" in upper or "SQLSTATE" in upper:
                val = 0
            elif "EIBRESP" in upper:
                val = 0
            elif "STATUS" in upper or upper.startswith("FS-"):
                val = "00"
            elif "RETURN-CODE" in upper or upper.endswith("-RC"):
                val = 0
            else:
                val = "00"

            success_entry.append((svar, val))
            # EOF/end entry
            if "SQLCODE" in upper or "SQLSTATE" in upper:
                eof_entry.append((svar, 100))
            else:
                eof_entry.append((svar, "10"))

        is_call = op_key.startswith("CALL:")
        if is_read:
            for _ in range(5):
                outcomes.setdefault(op_key, []).append(list(success_entry))
            outcomes.setdefault(op_key, []).append(list(eof_entry))
        elif is_start:
            for _ in range(10):
                outcomes.setdefault(op_key, []).append(list(success_entry))
        elif is_sql:
            for _ in range(50):
                outcomes.setdefault(op_key, []).append(list(success_entry))
            outcomes.setdefault(op_key, []).append(list(eof_entry))
        elif is_call:
            # CALLs may be invoked multiple times; provide enough outcomes
            for _ in range(10):
                outcomes.setdefault(op_key, []).append(list(success_entry))
        else:
            # OPEN/CLOSE/etc — typically invoked once or twice
            for _ in range(3):
                outcomes.setdefault(op_key, []).append(list(success_entry))
    return outcomes


def _pick_target(
    uncovered: set[str],
    path_constraints_map: dict[str, object],
    rng: random.Random,
) -> str | None:
    """Weighted selection of an uncovered paragraph by 1/path_length."""
    candidates = []
    weights = []
    for para in uncovered:
        pc = path_constraints_map.get(para)
        if pc is not None:
            path_len = len(pc.path) if pc.path else 10
            candidates.append(para)
            weights.append(1.0 / max(path_len, 1))

    if not candidates:
        return None

    total = sum(weights)
    r = rng.random() * total
    cumulative = 0.0
    for c, w in zip(candidates, weights):
        cumulative += w
        if cumulative >= r:
            return c
    return candidates[-1]


def _generate_directed_input(
    target: str,
    path_constraints,
    var_report,
    stub_mapping: dict[str, list[str]] | None,
    rng: random.Random,
    fuzzer: _FuzzerState,
) -> tuple[dict, dict | None]:
    """Generate an input state directed toward reaching a specific target paragraph.

    1. Find corpus entry covering longest prefix of the path.
    2. Set variables to satisfy gating conditions along remaining path.
    3. Generate stub outcomes that succeed along the path but may error at target.

    Returns (input_state, stub_outcomes).
    """
    # Start from best matching corpus entry or random state
    best_entry = None
    best_overlap = 0
    path_set = set(path_constraints.path) if path_constraints else set()

    for entry in fuzzer.corpus:
        overlap = len(entry.coverage & path_set)
        if overlap > best_overlap:
            best_overlap = overlap
            best_entry = entry

    if best_entry is not None:
        state = dict(best_entry.input_state)
    elif var_report is not None:
        state = _generate_random_state(var_report, rng)
    else:
        state = {}

    # Apply gating condition constraints
    if path_constraints and path_constraints.constraints:
        for gc in path_constraints.constraints:
            if gc.values:
                if gc.negated:
                    # Need to NOT match these values — pick something different
                    if gc.values == [True]:
                        # Bare flag condition negated: flag must be falsy
                        state[gc.variable] = False
                    elif var_report and gc.variable in var_report.variables:
                        info = var_report.variables[gc.variable]
                        all_lits = info.condition_literals
                        non_matching = [v for v in all_lits if v not in gc.values]
                        if non_matching:
                            state[gc.variable] = rng.choice(non_matching)
                        else:
                            state[gc.variable] = _generate_random_value(
                                gc.variable, info, rng,
                            )
                    else:
                        state[gc.variable] = False
                else:
                    # Need to match one of these values
                    state[gc.variable] = rng.choice(gc.values)

    # Generate stub outcomes
    stub_out = None
    if stub_mapping:
        stub_out = _generate_stub_outcomes(stub_mapping, var_report, rng)

    return state, stub_out


def _mutate_state(parent_state: dict, var_report, rng: random.Random,
                  fuzzer: _FuzzerState,
                  stub_mapping: dict[str, list[str]] | None = None,
                  parent_stub_outcomes: dict | None = None) -> tuple[dict, dict | None]:
    """Apply a random mutation to the parent state.

    Returns (mutated_state, stub_outcomes).
    """
    state = dict(parent_state)
    var_names = list(var_report.variables.keys())
    stub_out = dict(parent_stub_outcomes) if parent_stub_outcomes else None
    if not var_names:
        return state, stub_out

    r = rng.random()

    if r < 0.30:
        # Single-var flip
        name = rng.choice(var_names)
        state[name] = _generate_random_value(name, var_report.variables[name], rng)

    elif r < 0.48:
        # Literal-guided
        candidates = [n for n in var_names if var_report.variables[n].condition_literals]
        if candidates:
            name = rng.choice(candidates)
            state[name] = rng.choice(var_report.variables[name].condition_literals)
        else:
            name = rng.choice(var_names)
            state[name] = _generate_random_value(name, var_report.variables[name], rng)

    elif r < 0.60:
        # Gate-preserving mutation: only mutate non-status variables
        # This preserves initialization passage while exploring post-init logic
        non_status = [n for n in var_names
                      if var_report.variables[n].classification not in ("status",)]
        if non_status:
            n_changes = rng.randint(1, min(3, len(non_status)))
            for name in rng.sample(non_status, n_changes):
                state[name] = _generate_random_value(name, var_report.variables[name], rng)
        else:
            name = rng.choice(var_names)
            state[name] = _generate_random_value(name, var_report.variables[name], rng)

    elif r < 0.72:
        # Multi-var flip (2-4 variables)
        n_changes = rng.randint(2, min(4, len(var_names)))
        for name in rng.sample(var_names, n_changes):
            state[name] = _generate_random_value(name, var_report.variables[name], rng)

    elif r < 0.80:
        # Crossover from a different corpus entry
        if len(fuzzer.corpus) >= 2:
            donor = rng.choice(fuzzer.corpus)
            n_vars = rng.randint(1, min(3, len(var_names)))
            for name in rng.sample(var_names, n_vars):
                if name in donor.input_state:
                    state[name] = donor.input_state[name]
            # Also cross stub outcomes
            if donor.stub_outcomes:
                stub_out = dict(donor.stub_outcomes)
        else:
            name = rng.choice(var_names)
            state[name] = _generate_random_value(name, var_report.variables[name], rng)

    elif r < 0.85:
        # Reset one variable to zero/empty default
        name = rng.choice(var_names)
        info = var_report.variables[name]
        if info.classification == "status":
            state[name] = " "
        elif info.classification == "flag":
            state[name] = False
        else:
            state[name] = ""

    elif r < 0.95 and stub_mapping:
        # Stub-flip: change one operation's status outcome
        op_keys = list(stub_mapping.keys())
        if op_keys:
            op_key = rng.choice(op_keys)
            new_outcomes = _generate_stub_outcomes(
                {op_key: stub_mapping[op_key]}, var_report, rng,
            )
            if stub_out is None:
                stub_out = {}
            stub_out.update(new_outcomes)

    else:
        # Full stub regeneration or single-var flip fallback
        if stub_mapping:
            stub_out = _generate_stub_outcomes(stub_mapping, var_report, rng)
        else:
            name = rng.choice(var_names)
            state[name] = _generate_random_value(name, var_report.variables[name], rng)

    return state, stub_out


_DIRECTED_ATTEMPT_LIMIT = 200


def _run_guided(module, n_iterations: int, seed: int, var_report,
                all_paragraphs: list[str] | None,
                call_graph=None, gating_conditions=None,
                stub_mapping=None,
                equality_constraints=None) -> MonteCarloReport:
    """Coverage-guided fuzzing loop with optional directed fuzzing."""
    rng = random.Random(seed)
    fuzzer = _FuzzerState()

    explore_end = max(50, int(n_iterations * 0.3))
    stale_random_remaining = 0

    # Pre-compute path constraints for directed fuzzing
    path_constraints_map: dict[str, object] = {}
    if call_graph is not None and gating_conditions is not None:
        from .static_analysis import compute_path_constraints
        reachable = call_graph.reachable
        for para in reachable:
            pc = compute_path_constraints(para, call_graph, gating_conditions)
            if pc is not None:
                path_constraints_map[para] = pc

    directed_target: str | None = None
    directed_attempts = 0

    # --- All-success seed injection ---
    # Inject seeds that pass all initialization gates, guaranteeing corpus
    # entries that survive sequential gate gauntlets.
    if var_report is not None:
        all_success_state = _generate_all_success_state(var_report, equality_constraints)
        all_success_stubs = (
            _generate_all_success_stubs(stub_mapping, var_report)
            if stub_mapping else None
        )
        for seed_idx in range(3):
            seed_state = dict(all_success_state)
            seed_stub = (
                {k: list(v) for k, v in all_success_stubs.items()}
                if all_success_stubs else None
            )
            if seed_stub:
                seed_state["_stub_outcomes"] = seed_stub
            try:
                rs = module.run(seed_state)
                trace = rs.get("_trace", [])
                cov = frozenset(trace)
                edg = frozenset(
                    (trace[j], trace[j + 1])
                    for j in range(len(trace) - 1)
                    if trace[j] != trace[j + 1]
                )
                fuzzer.n_successful += 1
                for p in trace:
                    fuzzer.para_hits[p] += 1
                if _should_add_to_corpus(fuzzer, cov, edg):
                    entry = _CorpusEntry(
                        input_state={k: v for k, v in seed_state.items()
                                     if k != "_stub_outcomes"},
                        coverage=cov,
                        edges=edg,
                        added_at=0,
                        stub_outcomes=seed_stub,
                    )
                    _add_to_corpus(fuzzer, entry)
            except (RecursionError, Exception):
                pass

    for i in range(n_iterations):
        in_explore = (i < explore_end or not fuzzer.corpus
                      or stale_random_remaining > 0)

        if stale_random_remaining > 0:
            stale_random_remaining -= 1

        stub_out = None

        if in_explore:
            # During exploration, use all-success states 30% of the time
            # to keep the corpus fed with diverse post-initialization states.
            if (var_report is not None and i < explore_end
                    and rng.random() < 0.3):
                input_state = _generate_all_success_state(var_report, equality_constraints)
                # Add small random perturbations to non-status vars
                for name, info in var_report.variables.items():
                    if (info.classification not in ("status",)
                            and rng.random() < 0.3):
                        input_state[name] = _generate_random_value(
                            name, info, rng)
                if stub_mapping:
                    stub_out = _generate_all_success_stubs(
                        stub_mapping, var_report)
            elif var_report is not None:
                input_state = _generate_random_state(var_report, rng)
                if stub_mapping:
                    stub_out = _generate_stub_outcomes(stub_mapping, var_report, rng)
            else:
                input_state = {}
                if stub_mapping:
                    stub_out = _generate_stub_outcomes(stub_mapping, var_report, rng)
            parent = None
        else:
            parent = _select_seed(fuzzer, rng)
            input_state, stub_out = _mutate_state(
                parent.input_state, var_report, rng, fuzzer,
                stub_mapping=stub_mapping,
                parent_stub_outcomes=parent.stub_outcomes,
            )

        # Attach stub outcomes to state
        if stub_out:
            # Deep copy lists so mutations don't share references
            input_state["_stub_outcomes"] = {
                k: list(v) for k, v in stub_out.items()
            }

        # Recursion avoidance
        if var_report and _is_recursion_prone(fuzzer, input_state, var_report):
            continue

        try:
            result_state = module.run(input_state)
        except RecursionError:
            fuzzer.n_errors += 1
            if var_report and len(fuzzer.recursion_fingerprints) < _MAX_FINGERPRINTS:
                fp = _fingerprint_state(input_state, var_report)
                fuzzer.recursion_fingerprints.add(fp)
            fuzzer.error_messages.append(f"Iteration {i}: RecursionError")
            continue
        except Exception as e:
            fuzzer.n_errors += 1
            fuzzer.error_messages.append(f"Iteration {i}: {type(e).__name__}: {e}")
            continue

        # Aggregate stats
        abended = result_state.get("_abended", False)
        fuzzer.n_successful += 1
        if abended:
            fuzzer.n_abended += 1

        for call in result_state.get("_calls", []):
            fuzzer.call_frequency[call.get("name", "UNKNOWN")] += 1
        for ex in result_state.get("_execs", []):
            fuzzer.exec_frequency[ex.get("kind", "UNKNOWN")] += 1
        for msg in result_state.get("_display", []):
            fuzzer.display_patterns[str(msg)[:100]] += 1

        # Coverage signal from instrumentation
        trace = result_state.get("_trace", [])
        coverage = frozenset(trace)
        edges = frozenset(
            (trace[j], trace[j + 1])
            for j in range(len(trace) - 1)
            if trace[j] != trace[j + 1]
        )

        for p in trace:
            fuzzer.para_hits[p] += 1

        for j in range(len(trace) - 1):
            caller, callee = trace[j], trace[j + 1]
            if caller != callee:
                fuzzer.call_graph.setdefault(caller, set()).add(callee)

        for var, _para in result_state.get("_var_writes", []):
            fuzzer.var_writes[var] += 1
        for var, _para in result_state.get("_var_reads", []):
            fuzzer.var_reads[var] += 1
        for var in result_state.get("_state_diffs", {}):
            fuzzer.change_counts[var] += 1

        # Corpus update
        if _should_add_to_corpus(fuzzer, coverage, edges):
            entry = _CorpusEntry(
                input_state={k: v for k, v in input_state.items()
                             if k != "_stub_outcomes"},
                coverage=coverage,
                edges=edges,
                added_at=i,
                stub_outcomes=stub_out,
            )
            _add_to_corpus(fuzzer, entry)
            if parent is not None:
                parent.children_produced += 1
            # Reset directed target if we just covered it
            if directed_target and directed_target in coverage:
                directed_target = None
                directed_attempts = 0
        else:
            fuzzer.stale_counter += 1
            if fuzzer.stale_counter >= _STALE_THRESHOLD:
                if path_constraints_map and call_graph is not None:
                    # Directed fuzzing: pick an uncovered target
                    uncovered = (set(call_graph.reachable)
                                 - fuzzer.global_coverage)
                    if uncovered:
                        if (directed_target is None
                                or directed_attempts >= _DIRECTED_ATTEMPT_LIMIT
                                or directed_target not in uncovered):
                            directed_target = _pick_target(
                                uncovered, path_constraints_map, rng,
                            )
                            directed_attempts = 0

                        if directed_target and directed_target in path_constraints_map:
                            pc = path_constraints_map[directed_target]
                            input_state, stub_out = _generate_directed_input(
                                directed_target, pc, var_report,
                                stub_mapping, rng, fuzzer,
                            )
                            if stub_out:
                                input_state["_stub_outcomes"] = {
                                    k: list(v) for k, v in stub_out.items()
                                }
                            directed_attempts += 1

                            # Run the directed input immediately
                            try:
                                ds = module.run(input_state)
                                d_trace = ds.get("_trace", [])
                                d_cov = frozenset(d_trace)
                                d_edges = frozenset(
                                    (d_trace[j], d_trace[j + 1])
                                    for j in range(len(d_trace) - 1)
                                    if d_trace[j] != d_trace[j + 1]
                                )
                                for p in d_trace:
                                    fuzzer.para_hits[p] += 1
                                fuzzer.n_successful += 1
                                if _should_add_to_corpus(fuzzer, d_cov, d_edges):
                                    d_entry = _CorpusEntry(
                                        input_state={k: v for k, v in input_state.items()
                                                     if k != "_stub_outcomes"},
                                        coverage=d_cov,
                                        edges=d_edges,
                                        added_at=i,
                                        stub_outcomes=stub_out,
                                    )
                                    _add_to_corpus(fuzzer, d_entry)
                                    if directed_target in d_cov:
                                        directed_target = None
                                        directed_attempts = 0
                            except (RecursionError, Exception):
                                pass
                    else:
                        # All reachable paragraphs covered
                        stale_random_remaining = _STALE_RANDOM_BURST
                else:
                    # No static analysis — fall back to random burst
                    stale_random_remaining = _STALE_RANDOM_BURST
                fuzzer.stale_counter = 0

        if parent is not None:
            parent.mutation_count += 1

        # Periodically update energy scores
        if (i > 0 and i % _ENERGY_UPDATE_INTERVAL == 0
                and fuzzer.corpus and all_paragraphs):
            _update_energy(fuzzer, all_paragraphs)

    return _build_report_from_fuzzer(fuzzer, n_iterations, all_paragraphs,
                                    call_graph=call_graph)


def _build_report_from_fuzzer(fuzzer: _FuzzerState, n_iterations: int,
                              all_paragraphs: list[str] | None,
                              call_graph=None) -> MonteCarloReport:
    """Build MonteCarloReport from aggregated fuzzer state."""
    report = MonteCarloReport(
        n_iterations=n_iterations,
        n_successful=fuzzer.n_successful,
        n_errors=fuzzer.n_errors,
        n_abended=fuzzer.n_abended,
        call_frequency=dict(fuzzer.call_frequency),
        exec_frequency=dict(fuzzer.exec_frequency),
        display_patterns=dict(fuzzer.display_patterns),
        error_messages=fuzzer.error_messages,
    )

    # Store corpus entries as representative iterations (for compatibility)
    for idx, entry in enumerate(fuzzer.corpus):
        report.iterations.append(IterationResult(
            iteration=idx,
            initial_state=entry.input_state,
            final_state={},
            display_output=[],
            calls_made=[],
            execs_made=[],
            reads=[],
            writes=[],
            abended=False,
        ))

    # Build analysis report directly from aggregated data
    from .analysis import AnalysisReport

    analysis = AnalysisReport(n_iterations=fuzzer.n_successful)
    analysis.paragraph_hit_counts = dict(fuzzer.para_hits)
    analysis.call_graph = fuzzer.call_graph
    analysis.variable_write_counts = dict(fuzzer.var_writes)
    analysis.variable_read_counts = dict(fuzzer.var_reads)

    all_para_set = set(all_paragraphs or [])
    hit_names = set(fuzzer.para_hits.keys())
    analysis.dead_paragraphs = sorted(all_para_set - hit_names)

    written_vars = set(fuzzer.var_writes.keys())
    read_vars = set(fuzzer.var_reads.keys())
    analysis.dead_writes = sorted(written_vars - read_vars)
    analysis.read_only_vars = sorted(read_vars - written_vars)

    for var in sorted(fuzzer.change_counts.keys()):
        analysis.state_diffs[var] = {"changed_in": fuzzer.change_counts[var]}

    # Add reachability information if static call graph available
    if call_graph is not None:
        unreachable = sorted(call_graph.unreachable)
        analysis.structurally_unreachable = unreachable
        reachable_set = set(call_graph.reachable)
        analysis.reachable_uncovered = sorted(reachable_set - hit_names)
        n_reachable = len(reachable_set)
        analysis.max_theoretical_coverage = (
            (n_reachable / len(all_para_set) * 100) if all_para_set else 0.0
        )

    report.analysis_report = analysis
    return report


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def _load_module(module_path: str | Path):
    """Dynamically import a generated Python module."""
    path = Path(module_path)
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = module
    spec.loader.exec_module(module)
    return module


def run_monte_carlo(
    generated_module_path: str | Path,
    n_iterations: int = 1000,
    seed: int = 42,
    var_report=None,
    instrument: bool = False,
    all_paragraphs: list[str] | None = None,
    guided: bool = False,
    call_graph=None,
    gating_conditions=None,
    stub_mapping=None,
    equality_constraints=None,
) -> MonteCarloReport:
    """Run Monte Carlo analysis on a generated Python module.

    Args:
        generated_module_path: Path to the generated .py file.
        n_iterations: Number of random iterations.
        seed: Random seed for reproducibility.
        var_report: Optional VariableReport for input generation.
        instrument: If True, collect instrumentation data from each run.
        all_paragraphs: All paragraph names (for dead-paragraph detection).
        guided: If True, use coverage-guided fuzzing instead of random.
        call_graph: Optional StaticCallGraph for directed fuzzing.
        gating_conditions: Optional gating conditions map.
        stub_mapping: Optional stub-to-status-variable mapping.

    Returns:
        MonteCarloReport with aggregated results.
    """
    module = _load_module(generated_module_path)

    # Raise recursion limit for deep COBOL call chains
    old_limit = sys.getrecursionlimit()
    if guided:
        # In guided mode, use a tighter limit so RecursionErrors fail fast
        # instead of unwinding 50K frames.  3x paragraph count is plenty.
        n_paras = len(all_paragraphs) if all_paragraphs else 500
        needed = max(old_limit, n_paras * 5, 5000)
    else:
        needed = max(old_limit, 50000)
    if needed != old_limit:
        sys.setrecursionlimit(needed)

    if guided:
        return _run_guided(
            module, n_iterations, seed, var_report, all_paragraphs,
            call_graph=call_graph,
            gating_conditions=gating_conditions,
            stub_mapping=stub_mapping,
            equality_constraints=equality_constraints,
        )

    rng = random.Random(seed)
    report = MonteCarloReport(n_iterations=n_iterations)

    for i in range(n_iterations):
        if var_report is not None:
            initial = _generate_random_state(var_report, rng)
        else:
            initial = {}

        try:
            result_state = module.run(initial)

            display = result_state.get("_display", [])
            calls = result_state.get("_calls", [])
            execs = result_state.get("_execs", [])
            reads = result_state.get("_reads", [])
            writes = result_state.get("_writes", [])
            abended = result_state.get("_abended", False)

            iteration = IterationResult(
                iteration=i,
                initial_state=initial,
                final_state={k: v for k, v in result_state.items()
                             if not k.startswith("_")},
                display_output=display,
                calls_made=calls,
                execs_made=execs,
                reads=reads,
                writes=writes,
                abended=abended,
            )

            if instrument:
                iteration.trace = result_state.get("_trace", [])
                iteration.var_writes = result_state.get("_var_writes", [])
                iteration.var_reads = result_state.get("_var_reads", [])
                iteration.state_diffs = result_state.get("_state_diffs", {})

            report.iterations.append(iteration)
            report.n_successful += 1

            if abended:
                report.n_abended += 1

            # Aggregate calls
            for call in calls:
                name = call.get("name", "UNKNOWN")
                report.call_frequency[name] = report.call_frequency.get(name, 0) + 1

            # Aggregate execs
            for ex in execs:
                kind = ex.get("kind", "UNKNOWN")
                report.exec_frequency[kind] = report.exec_frequency.get(kind, 0) + 1

            # Aggregate display messages
            for msg in display:
                key = str(msg)[:100]
                report.display_patterns[key] = report.display_patterns.get(key, 0) + 1

        except Exception as e:
            report.n_errors += 1
            report.error_messages.append(f"Iteration {i}: {type(e).__name__}: {e}")
            report.iterations.append(IterationResult(
                iteration=i,
                initial_state=initial,
                final_state={},
                display_output=[],
                calls_made=[],
                execs_made=[],
                reads=[],
                writes=[],
                abended=False,
                error=str(e),
            ))

    if instrument:
        from .analysis import build_analysis_report
        inst_data = []
        for it in report.iterations:
            if it.trace is not None:
                inst_data.append({
                    "trace": it.trace,
                    "var_writes": it.var_writes or [],
                    "var_reads": it.var_reads or [],
                    "state_diffs": it.state_diffs or {},
                })
        report.analysis_report = build_analysis_report(
            inst_data, all_paragraphs or [],
        )

    return report
