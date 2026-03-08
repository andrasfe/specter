"""Monte Carlo analysis of generated Python code.

Runs multiple iterations with randomized input parameters to explore
execution paths, branch coverage, and external call patterns.
"""

from __future__ import annotations

import importlib.util
import logging
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
    call_events: list[tuple] | None = None


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
    sample_call_events: list[list[tuple]] = field(default_factory=list)

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
            # harvested literals (including from gating conditions)
            # they're worth seeding with higher probability.
            if rng.random() < 0.7:
                state[name] = rng.choice(harvested)

    return state


# ---------------------------------------------------------------------------
# Coverage-guided fuzzing
# ---------------------------------------------------------------------------

_MAX_CORPUS = 500
_MAX_FINGERPRINTS = 10000
_STALE_THRESHOLD = 300
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
    global_branches: set[int] = field(default_factory=set)
    sample_call_events: list[list[tuple]] = field(default_factory=list)
    concolic_failed: set[int] = field(default_factory=set)
    concolic_cooldown: dict[int, int] = field(default_factory=dict)


def _should_add_to_corpus(fuzzer: _FuzzerState, coverage: frozenset, edges: frozenset,
                           branches: frozenset | None = None) -> bool:
    new_paras = coverage - fuzzer.global_coverage
    new_edges = edges - fuzzer.global_edges
    new_branches = (branches - fuzzer.global_branches) if branches else set()
    return bool(new_paras or new_edges or new_branches)


def _add_to_corpus(fuzzer: _FuzzerState, entry: _CorpusEntry,
                   branches: frozenset | None = None) -> None:
    fuzzer.corpus.append(entry)
    fuzzer.global_coverage.update(entry.coverage)
    fuzzer.global_edges.update(entry.edges)
    if branches:
        fuzzer.global_branches.update(branches)
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
            # 40% success bias for stub outcomes — lower bias explores more error paths
            if rng.random() < 0.4:
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
            n_reps = 10
        elif is_sql:
            n_reps = 50
        elif is_start or is_call:
            n_reps = 10
        else:
            n_reps = 5
        for _ in range(n_reps):
            outcomes.setdefault(op_key, []).append(list(entry))

    return outcomes


def _generate_stub_defaults(
    stub_mapping: dict[str, list[str]],
    var_report,
) -> dict[str, list[tuple[str, object]]]:
    """Generate default (exhaustion) outcomes for all stub operations.

    When stub outcomes are exhausted, these defaults are applied.
    READ → EOF ('10'), START → not-found ('23'), SQL → SQLCODE 100,
    others → success (so the program continues past the stub).
    """
    defaults: dict[str, list[tuple[str, object]]] = {}
    for op_key, status_vars in stub_mapping.items():
        entry: list[tuple[str, object]] = []
        for svar in status_vars:
            upper = svar.upper()

            # Check condition_literals first (most reliable for scrambled names)
            harvested = []
            if var_report and svar in var_report.variables:
                harvested = var_report.variables[svar].condition_literals

            if "SQLCODE" in upper or "SQLSTATE" in upper:
                if op_key.startswith("READ:") or op_key == "SQL":
                    entry.append((svar, 100))  # end of cursor / not found
                else:
                    entry.append((svar, 0))  # success
            elif op_key.startswith("READ:"):
                entry.append((svar, "10"))  # EOF
            elif op_key.startswith("START:"):
                entry.append((svar, "23"))  # not found
            elif "EIBRESP" in upper:
                entry.append((svar, 0))  # NORMAL
            elif "STATUS" in upper or upper.startswith("FS-"):
                entry.append((svar, "00"))  # success
            elif "RETURN-CODE" in upper or upper.endswith("-RC"):
                entry.append((svar, 0))
            elif harvested:
                # Use first condition_literal (typically the success value)
                entry.append((svar, harvested[0]))
            else:
                # Default: use string "00" for safety (matches file status checks
                # which are the most common pattern in COBOL programs)
                entry.append((svar, "00"))
        defaults[op_key] = entry
    return defaults


def _generate_search_outcomes(
    program_paragraphs,
    rng: random.Random,
    found_bias: float = 0.7,
) -> dict[str, list]:
    """Generate SEARCH stub outcomes (True=found, False=not found).

    Scans paragraph statements for SEARCH to find table names,
    then generates boolean outcome queues.
    """
    import re
    outcomes: dict[str, list] = {}
    seen_tables: set[str] = set()
    for para in program_paragraphs:
        for stmt in para.statements:
            if stmt.type == "SEARCH":
                m = re.match(r"SEARCH\s+([A-Z][A-Z0-9-]*)", stmt.text, re.IGNORECASE)
                if m:
                    table = m.group(1).upper()
                    if table not in seen_tables:
                        seen_tables.add(table)
                        key = f"SEARCH:{table}"
                        # Generate multiple outcomes (found/not found)
                        outcomes[key] = [
                            rng.random() < found_bias for _ in range(10)
                        ]
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
            # Generous count: programs may have multiple sequential loops
            # reading from the same file (e.g., 4 loops × 60 reads each).
            for _ in range(500):
                outcomes.setdefault(op_key, []).append(list(success_entry))
            outcomes.setdefault(op_key, []).append(list(eof_entry))
        elif is_start:
            for _ in range(500):
                outcomes.setdefault(op_key, []).append(list(success_entry))
        elif is_sql:
            for _ in range(100):
                outcomes.setdefault(op_key, []).append(list(success_entry))
            outcomes.setdefault(op_key, []).append(list(eof_entry))
        elif is_call:
            # CALLs may be invoked from loops; provide generous outcomes
            for _ in range(100):
                outcomes.setdefault(op_key, []).append(list(success_entry))
        else:
            # OPEN/CLOSE/etc — typically invoked once or twice per file
            for _ in range(20):
                outcomes.setdefault(op_key, []).append(list(success_entry))
    return outcomes


def _pick_concolic_base(
    fuzzer: _FuzzerState,
    target_para: str,
) -> tuple[dict, dict | None]:
    """Pick the best corpus entry as base state for a concolic solution.

    Prefers entries whose trace already reaches *target_para* (or a nearby
    paragraph).  Falls back to the highest-coverage entry.

    Returns (input_state_copy, stub_outcomes_copy_or_None).
    """
    if not fuzzer.corpus:
        return {}, None

    # First: find entries that already reach the target paragraph
    if target_para:
        for entry in fuzzer.corpus:
            if target_para in entry.coverage:
                stubs = {k: list(v) for k, v in entry.stub_outcomes.items()} if entry.stub_outcomes else None
                return dict(entry.input_state), stubs

    # Fallback: entry with most coverage
    best = max(fuzzer.corpus, key=lambda e: len(e.coverage))
    stubs = {k: list(v) for k, v in best.stub_outcomes.items()} if best.stub_outcomes else None
    return dict(best.input_state), stubs


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
                  parent_stub_outcomes: dict | None = None,
                  gating_values: dict[str, list] | None = None) -> tuple[dict, dict | None]:
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

    elif r < 0.82:
        # Reset one variable to zero/empty default
        name = rng.choice(var_names)
        info = var_report.variables[name]
        if info.classification == "status":
            state[name] = " "
        elif info.classification == "flag":
            state[name] = False
        else:
            state[name] = ""

    elif r < 0.90 and stub_mapping:
        # Multi-stub-flip: change 1-3 operations' status outcomes
        op_keys = list(stub_mapping.keys())
        if op_keys:
            n_ops = rng.randint(1, min(3, len(op_keys)))
            for op_key in rng.sample(op_keys, n_ops):
                new_outcomes = _generate_stub_outcomes(
                    {op_key: stub_mapping[op_key]}, var_report, rng,
                )
                if stub_out is None:
                    stub_out = {}
                stub_out.update(new_outcomes)

    elif r < 0.95 and stub_mapping:
        # Full stub regeneration — explore completely different stub combos
        stub_out = _generate_stub_outcomes(stub_mapping, var_report, rng)

    else:
        # Full stub regen or single-var flip fallback
        if stub_mapping:
            stub_out = _generate_stub_outcomes(stub_mapping, var_report, rng)
        else:
            name = rng.choice(var_names)
            state[name] = _generate_random_value(name, var_report.variables[name], rng)

    return state, stub_out


_DIRECTED_ATTEMPT_LIMIT = 200
_LLM_WALK_ROUNDS = 100  # max random walk rounds per LLM suggestion


def _run_paragraph_directly(module, para_name: str, input_state: dict) -> dict:
    """Invoke a single paragraph function directly, bypassing run().

    This allows the fuzzer to exercise paragraphs that are structurally
    unreachable from the program's entry point (disconnected call graphs).
    Sets up the same instrumented state that run() would, then calls the
    paragraph function and collects trace/branch/coverage data.
    """
    func_name = "para_" + para_name.replace("-", "_")
    para_func = getattr(module, func_name, None)
    if para_func is None:
        return {}

    # Build state the same way run() does
    default_state_fn = getattr(module, "_default_state", None)
    base = default_state_fn() if default_state_fn else {}
    base.update(input_state)

    # Use InstrumentedState if available
    instrumented_cls = getattr(module, "_InstrumentedState", None)
    if instrumented_cls:
        state = instrumented_cls(base)
    else:
        state = base

    state.setdefault("_display", [])
    state.setdefault("_calls", [])
    state.setdefault("_execs", [])
    state.setdefault("_reads", [])
    state.setdefault("_writes", [])
    state.setdefault("_abended", False)
    state.setdefault("_branches", set())
    goback_cls = getattr(module, "_GobackSignal", None)

    try:
        para_func(state)
    except Exception as e:
        if goback_cls and isinstance(e, goback_cls):
            pass
        elif isinstance(e, ZeroDivisionError):
            state["_abended"] = True
        else:
            raise

    return state


def _random_walk_suggestion(
    module, base_state: dict, var_report, rng: random.Random,
    fuzzer: _FuzzerState, stub_mapping, search_rng: random.Random,
    inject_defaults_fn, max_rounds: int = _LLM_WALK_ROUNDS,
    call_graph=None,
) -> int:
    """Random-walk around an LLM suggestion to maximize paragraph coverage.

    Starting from *base_state*, performs up to *max_rounds* mutations.
    Each round mutates the current best state, runs the program, and
    keeps the mutation if it discovers new paragraph coverage.  Stops
    early after 10 consecutive rounds with no improvement.

    Returns the number of new paragraphs covered across all rounds.
    """
    import logging as _log
    log = _log.getLogger(__name__)

    best_state = dict(base_state)
    best_stubs = {k: list(v) for k, v in base_state.get("_stub_outcomes", {}).items()}
    coverage_before = len(fuzzer.global_coverage)
    stale = 0
    _MAX_STALE = 10
    new_total = 0

    for walk_round in range(max_rounds):
        # Mutate from best known state
        mutated, mut_stubs = _mutate_state(
            {k: v for k, v in best_state.items() if not k.startswith("_stub")},
            var_report, rng, fuzzer,
            stub_mapping=stub_mapping,
            parent_stub_outcomes=best_stubs if best_stubs else None,
        )
        if mut_stubs:
            mutated["_stub_outcomes"] = {k: list(v) for k, v in mut_stubs.items()}
        inject_defaults_fn(mutated, search_rng)

        try:
            rs = module.run(mutated)
        except (RecursionError, Exception):
            stale += 1
            if stale >= _MAX_STALE:
                break
            continue

        trace = rs.get("_trace", [])
        cov = frozenset(trace)
        edges = frozenset(
            (trace[j], trace[j + 1])
            for j in range(len(trace) - 1)
            if trace[j] != trace[j + 1]
        )
        fuzzer.n_successful += 1
        for p in trace:
            fuzzer.para_hits[p] += 1
        branches = frozenset(rs.get("_branches", set()))

        if _should_add_to_corpus(fuzzer, cov, edges, branches):
            entry = _CorpusEntry(
                input_state={k: v for k, v in mutated.items()
                             if not k.startswith("_stub")},
                coverage=cov,
                edges=edges,
                added_at=0,
                stub_outcomes=mut_stubs,
            )
            _add_to_corpus(fuzzer, entry, branches)
            # Adopt this mutation as the new base for further walks
            best_state = dict(mutated)
            best_stubs = dict(mut_stubs) if mut_stubs else {}
            stale = 0
        else:
            stale += 1
            if stale >= _MAX_STALE:
                break

    new_total = len(fuzzer.global_coverage) - coverage_before
    if new_total > 0:
        log.info(
            "LLM walk: +%d paragraphs in %d rounds (total %d/%s)",
            new_total, walk_round + 1,
            len(fuzzer.global_coverage),
            len(call_graph.all_paragraphs) if call_graph else "?",
        )
    return new_total


def _run_guided(module, n_iterations: int, seed: int, var_report,
                all_paragraphs: list[str] | None,
                call_graph=None, gating_conditions=None,
                stub_mapping=None,
                equality_constraints=None,
                program=None,
                llm_provider=None,
                llm_model=None,
                llm_interval: int = 500,
                llm_walk_rounds: int = _LLM_WALK_ROUNDS,
                concolic: bool = False) -> MonteCarloReport:
    """Coverage-guided fuzzing loop with optional directed fuzzing.

    When *llm_provider* is given, the loop periodically queries an LLM
    (via war_rig's llm_providers) for input suggestions targeting
    uncovered paragraphs, combining static analysis with LLM reasoning
    to maximize path coverage.
    """
    rng = random.Random(seed)
    search_rng = random.Random(seed + 1_000_000)  # separate rng for SEARCH outcomes
    fuzzer = _FuzzerState()

    # LLM coverage state
    _llm_state = None
    _llm_suggestions: list = []
    # LLM-guided fuzzer state (adaptive strategy selection)
    _session_memory = None
    _active_decision = None  # current StrategyDecision
    _decision_iter_start = 0  # iteration when current decision started
    _decision_coverage_start = 0  # coverage count at decision start
    _decision_branch_start = 0
    _decision_edge_start = 0
    _decision_errors = 0
    _last_coverage_for_milestone = 0
    if llm_provider is not None:
        from .llm_coverage import LLMCoverageState
        _llm_state = LLMCoverageState()

        # Initialize LLM-guided fuzzer with variable semantics inference
        from .llm_fuzzer import (
            SessionMemory, infer_variable_semantics,
            should_consult_llm, get_strategy_decision,
            apply_strategy_to_state, record_strategy_result,
            record_error, record_coverage_checkpoint,
        )
        _session_memory = SessionMemory()
        if var_report is not None:
            profiles = infer_variable_semantics(
                llm_provider, var_report, model=llm_model,
            )
            _session_memory.semantic_profiles = profiles
            _session_memory.llm_calls += 1

    # Build gating value pool: maps variable -> set of values needed in gating conditions.
    # Used by the gating-targeted mutation strategy without modifying condition_literals.
    _gating_values: dict[str, list] = {}
    if gating_conditions:
        for _target, _gc_list in gating_conditions.items():
            for _gc in _gc_list:
                if _gc.values:
                    _gating_values.setdefault(_gc.variable, [])
                    for v in _gc.values:
                        if v not in _gating_values[_gc.variable]:
                            _gating_values[_gc.variable].append(v)

    explore_end = max(50, int(n_iterations * 0.3))
    stale_random_remaining = 0

    # Pre-compute path constraints for directed fuzzing
    path_constraints_map: dict[str, object] = {}
    if call_graph is not None and gating_conditions is not None:
        from .static_analysis import compute_path_constraints
        # Compute for ALL paragraphs — not just statically reachable ones.
        # The fuzzer can directly invoke unreachable paragraph functions.
        for para in call_graph.all_paragraphs:
            pc = compute_path_constraints(para, call_graph, gating_conditions)
            if pc is not None:
                path_constraints_map[para] = pc

    directed_target: str | None = None
    directed_attempts = 0

    # Pre-compute stub defaults (EOF for READs when stubs exhausted)
    stub_defaults = (
        _generate_stub_defaults(stub_mapping, var_report)
        if stub_mapping else None
    )

    # Pre-compute SEARCH table names (stable — doesn't consume rng)
    _search_tables: list[str] = []
    if program is not None:
        import re as _re
        _seen: set[str] = set()
        for _para in program.paragraphs:
            for _stmt in _para.statements:
                if _stmt.type == "SEARCH":
                    _m = _re.match(r"SEARCH\s+([A-Z][A-Z0-9-]*)", _stmt.text, _re.IGNORECASE)
                    if _m:
                        _t = _m.group(1).upper()
                        if _t not in _seen:
                            _seen.add(_t)
                            _search_tables.append(_t)

    def _inject_defaults(state: dict, local_rng: random.Random) -> None:
        """Inject stub defaults and SEARCH outcomes into state.

        Uses a separate rng to avoid corrupting the main fuzzer sequence.
        """
        # Note: stub_defaults (EOF on empty READ queue) disabled for now —
        # it terminates loops too early when stubs run out, reducing coverage.
        if _search_tables:
            so = state.setdefault("_stub_outcomes", {})
            for table in _search_tables:
                key = f"SEARCH:{table}"
                if key not in so:
                    so[key] = [local_rng.random() < 0.7 for _ in range(10)]

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
            _inject_defaults(seed_state, search_rng)
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
                br = frozenset(rs.get("_branches", set()))
                if _should_add_to_corpus(fuzzer, cov, edg, br):
                    entry = _CorpusEntry(
                        input_state={k: v for k, v in seed_state.items()
                                     if not k.startswith("_stub")},
                        coverage=cov,
                        edges=edg,
                        added_at=0,
                        stub_outcomes=seed_stub,
                    )
                    _add_to_corpus(fuzzer, entry, br)
                    # Walk around the successful seed to find more coverage
                    if var_report is not None and llm_walk_rounds > 0:
                        _random_walk_suggestion(
                            module, seed_state, var_report, rng, fuzzer,
                            stub_mapping, search_rng, _inject_defaults,
                            max_rounds=llm_walk_rounds,
                            call_graph=call_graph,
                        )
            except (RecursionError, Exception):
                pass

    # --- Early concolic seeding ---
    # Run concolic immediately to deterministically solve gating branches.
    # This stabilizes coverage by ensuring the initial corpus covers key
    # branch points regardless of random seed.
    if concolic and var_report is not None:
        _branch_meta = getattr(module, '_BRANCH_META', {})
        if _branch_meta and fuzzer.corpus:
            _clog = logging.getLogger("specter.monte_carlo")
            try:
                from .concolic import solve_for_uncovered_branches
                observed = [e.input_state for e in fuzzer.corpus[-10:]]
                solutions = solve_for_uncovered_branches(
                    _branch_meta, fuzzer.global_branches,
                    var_report, observed,
                    stub_mapping=stub_mapping,
                    corpus_entries=fuzzer.corpus,
                )
                _early_hits = 0
                for sol in solutions:
                    target_para = _branch_meta.get(
                        abs(sol.branch_id), {},
                    ).get("paragraph", "")
                    base, base_stubs = _pick_concolic_base(
                        fuzzer, target_para,
                    )
                    base.update(sol.assignments)
                    merged_stubs = dict(base_stubs) if base_stubs else {}
                    if sol.stub_outcomes:
                        merged_stubs.update(sol.stub_outcomes)
                    if merged_stubs:
                        base["_stub_outcomes"] = {
                            k: list(v) for k, v in merged_stubs.items()
                        }
                    _inject_defaults(base, search_rng)
                    try:
                        cs = module.run(base)
                        c_trace = cs.get("_trace", [])
                        c_cov = frozenset(c_trace)
                        c_edges = frozenset(
                            (c_trace[j], c_trace[j + 1])
                            for j in range(len(c_trace) - 1)
                            if c_trace[j] != c_trace[j + 1]
                        )
                        for p in c_trace:
                            fuzzer.para_hits[p] += 1
                        fuzzer.n_successful += 1
                        c_br = frozenset(cs.get("_branches", set()))
                        if _should_add_to_corpus(fuzzer, c_cov, c_edges, c_br):
                            _early_hits += 1
                            c_entry = _CorpusEntry(
                                input_state={k: v for k, v in base.items()
                                             if not k.startswith("_stub")},
                                coverage=c_cov,
                                edges=c_edges,
                                added_at=0,
                                stub_outcomes=merged_stubs if merged_stubs else None,
                            )
                            _add_to_corpus(fuzzer, c_entry, c_br)
                            if var_report is not None and llm_walk_rounds > 0:
                                _random_walk_suggestion(
                                    module, base, var_report,
                                    rng, fuzzer, stub_mapping,
                                    search_rng, _inject_defaults,
                                    max_rounds=llm_walk_rounds,
                                    call_graph=call_graph,
                                )
                    except (RecursionError, Exception):
                        pass
                if _early_hits:
                    _clog.info("Concolic seed: %d/%d solutions -> new coverage "
                               "(branches=%d, paras=%d)",
                               _early_hits, len(solutions),
                               len(fuzzer.global_branches),
                               len(fuzzer.global_coverage))
            except ImportError:
                pass

    for i in range(n_iterations):
        # --- LLM-guided strategy decision ---
        # Use adaptive LLM strategist when available; fall back to
        # original LLM suggestion injection otherwise.
        if (llm_provider is not None and _session_memory is not None
                and var_report is not None and i > 0):
            from .llm_fuzzer import (
                should_consult_llm, get_strategy_decision,
                apply_strategy_to_state, record_strategy_result,
                record_coverage_checkpoint,
            )

            # Record result of previous strategy batch
            if (_active_decision is not None
                    and i >= _decision_iter_start + _active_decision.iterations):
                record_strategy_result(
                    _session_memory,
                    _active_decision.strategy,
                    i - _decision_iter_start,
                    len(fuzzer.global_coverage) - _decision_coverage_start,
                    len(fuzzer.global_branches) - _decision_branch_start,
                    len(fuzzer.global_edges) - _decision_edge_start,
                    _decision_errors,
                )
                _active_decision = None
                _decision_errors = 0

            # Check if we should consult the LLM
            reason = should_consult_llm(
                i, _session_memory, fuzzer.stale_counter,
                _STALE_THRESHOLD, llm_interval,
                _last_coverage_for_milestone,
                len(fuzzer.global_coverage),
            )

            if reason and _active_decision is None:
                record_coverage_checkpoint(
                    _session_memory, i,
                    len(fuzzer.global_coverage),
                    len(fuzzer.global_branches),
                )
                _last_coverage_for_milestone = len(fuzzer.global_coverage)

                # Compute frontier for LLM context (use all paragraphs)
                _frontier: set[str] = set()
                if call_graph is not None:
                    uncov = set(call_graph.all_paragraphs) - fuzzer.global_coverage
                    for caller, callees in fuzzer.call_graph.items():
                        if caller in fuzzer.global_coverage and callees & uncov:
                            _frontier.add(caller)

                total_br = 0
                try:
                    import re as _re3, inspect as _insp
                    _src = _insp.getsource(module)
                    total_br = len(set(
                        int(m) for m in _re3.findall(
                            r"_branches.*?\.add\((-?\d+)\)", _src)
                    ))
                except Exception:
                    pass

                _all_paras = set(all_paragraphs) if all_paragraphs else set()
                decision = get_strategy_decision(
                    llm_provider, _session_memory,
                    fuzzer.global_coverage, _all_paras, _frontier,
                    total_br, len(fuzzer.global_branches),
                    var_report, model=llm_model,
                )
                if decision:
                    _active_decision = decision
                    _decision_iter_start = i
                    _decision_coverage_start = len(fuzzer.global_coverage)
                    _decision_branch_start = len(fuzzer.global_branches)
                    _decision_edge_start = len(fuzzer.global_edges)
                    _decision_errors = 0

        # --- LLM-guided suggestion injection (original path) ---
        # Falls back to gap-based suggestions when no active strategy decision,
        # or when the active strategy is directed_walk.
        if (llm_provider is not None and _llm_state is not None
                and call_graph is not None and path_constraints_map
                and i > 0 and i % llm_interval == 0
                and _active_decision is None):
            uncovered_for_llm = set(call_graph.all_paragraphs) - fuzzer.global_coverage
            if uncovered_for_llm:
                from .llm_coverage import (
                    generate_llm_suggestions,
                    apply_suggestion,
                )
                try:
                    _llm_suggestions = generate_llm_suggestions(
                        llm_provider,
                        fuzzer.global_coverage,
                        uncovered_for_llm,
                        path_constraints_map,
                        gating_conditions,
                        var_report,
                        _llm_state,
                        model=llm_model,
                    )
                except Exception as _llm_err:
                    import logging as _log
                    _log.getLogger(__name__).debug("LLM query error: %s", _llm_err)
                    _llm_suggestions = []

        # Try pending LLM suggestions as inputs, then random-walk around them
        if _llm_suggestions and _llm_state is not None and _active_decision is None:
            suggestion = _llm_suggestions.pop(0)
            _llm_state.suggestions_tried += 1
            from .llm_coverage import apply_suggestion
            base = (_generate_all_success_state(var_report, equality_constraints)
                    if var_report else {})
            input_state = apply_suggestion(suggestion, base, var_report, stub_mapping)
            if stub_mapping:
                stub_out = _generate_all_success_stubs(stub_mapping, var_report)
                input_state["_stub_outcomes"] = {
                    k: list(v) for k, v in stub_out.items()
                }
            _inject_defaults(input_state, search_rng)

            try:
                rs = module.run(input_state)
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
                br = frozenset(rs.get("_branches", set()))
                if _should_add_to_corpus(fuzzer, cov, edg, br):
                    entry = _CorpusEntry(
                        input_state={k: v for k, v in input_state.items()
                                     if not k.startswith("_stub")},
                        coverage=cov,
                        edges=edg,
                        added_at=i,
                        stub_outcomes=stub_out,
                    )
                    _add_to_corpus(fuzzer, entry, br)
                    _llm_state.suggestions_hit += 1
                    if suggestion.target in cov:
                        for gap in _llm_state.gaps:
                            if gap.target == suggestion.target:
                                gap.resolved = True
            except (RecursionError, Exception):
                pass

            # Random-walk around this suggestion to find more coverage
            if var_report is not None and llm_walk_rounds > 0:
                _random_walk_suggestion(
                    module, input_state, var_report, rng, fuzzer,
                    stub_mapping, search_rng, _inject_defaults,
                    max_rounds=llm_walk_rounds,
                    call_graph=call_graph,
                )
                # Update resolved gaps after walk
                for gap in _llm_state.gaps:
                    if gap.target in fuzzer.global_coverage:
                        gap.resolved = True

            continue  # consumed this iteration with the LLM suggestion

        in_explore = (i < explore_end or not fuzzer.corpus
                      or stale_random_remaining > 0)

        if stale_random_remaining > 0:
            stale_random_remaining -= 1

        stub_out = None

        # --- LLM strategy-driven input generation ---
        if (_active_decision is not None and _session_memory is not None
                and var_report is not None
                and _active_decision.strategy not in ("directed_walk",)):
            from .llm_fuzzer import apply_strategy_to_state
            base = (_generate_all_success_state(var_report, equality_constraints)
                    if var_report else {})
            input_state = apply_strategy_to_state(
                _active_decision, base, var_report, _session_memory, rng,
                fuzzer_corpus=fuzzer.corpus,
            )
            if stub_mapping:
                stub_out = _generate_stub_outcomes(stub_mapping, var_report, rng)
            parent = None

        elif in_explore:
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
                gating_values=None,  # don't use gating in normal mutation (changes rng)
            )

        # Attach stub outcomes to state
        if stub_out:
            # Deep copy lists so mutations don't share references
            input_state["_stub_outcomes"] = {
                k: list(v) for k, v in stub_out.items()
            }

        _inject_defaults(input_state, search_rng)

        # Recursion avoidance
        if var_report and _is_recursion_prone(fuzzer, input_state, var_report):
            continue

        try:
            result_state = module.run(input_state)
        except RecursionError:
            fuzzer.n_errors += 1
            if _active_decision is not None:
                _decision_errors += 1
            if var_report and len(fuzzer.recursion_fingerprints) < _MAX_FINGERPRINTS:
                fp = _fingerprint_state(input_state, var_report)
                fuzzer.recursion_fingerprints.add(fp)
            fuzzer.error_messages.append(f"Iteration {i}: RecursionError")
            if _session_memory is not None:
                from .llm_fuzzer import record_error
                record_error(_session_memory, "RecursionError", input_state)
            continue
        except Exception as e:
            fuzzer.n_errors += 1
            if _active_decision is not None:
                _decision_errors += 1
            fuzzer.error_messages.append(f"Iteration {i}: {type(e).__name__}: {e}")
            if _session_memory is not None:
                from .llm_fuzzer import record_error
                record_error(
                    _session_memory, f"{type(e).__name__}: {e}", input_state,
                    focus_variables=(_active_decision.focus_variables
                                     if _active_decision else None),
                )
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
        branches = frozenset(result_state.get("_branches", set()))
        if _should_add_to_corpus(fuzzer, coverage, edges, branches):
            entry = _CorpusEntry(
                input_state={k: v for k, v in input_state.items()
                             if not k.startswith("_stub")},
                coverage=coverage,
                edges=edges,
                added_at=i,
                stub_outcomes=stub_out,
            )
            _add_to_corpus(fuzzer, entry, branches)
            # Save call events from coverage-expanding runs (up to 20 samples)
            call_events = result_state.get("_call_events", [])
            if call_events and len(fuzzer.sample_call_events) < 20:
                fuzzer.sample_call_events.append(call_events)
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
                    # Directed fuzzing: pick any uncovered paragraph
                    all_paras = set(call_graph.all_paragraphs)
                    uncovered = all_paras - fuzzer.global_coverage
                    if uncovered:
                        if (directed_target is None
                                or directed_attempts >= _DIRECTED_ATTEMPT_LIMIT
                                or directed_target not in uncovered):
                            directed_target = _pick_target(
                                uncovered, path_constraints_map, rng,
                            )
                            directed_attempts = 0

                        if directed_target:
                            is_unreachable = directed_target not in call_graph.reachable
                            if directed_target in path_constraints_map:
                                pc = path_constraints_map[directed_target]
                                input_state, stub_out = _generate_directed_input(
                                    directed_target, pc, var_report,
                                    stub_mapping, rng, fuzzer,
                                )
                            else:
                                # No path constraints — use random state
                                input_state = (_generate_all_success_state(
                                    var_report, equality_constraints)
                                    if var_report else {})
                                stub_out = (_generate_stub_outcomes(
                                    stub_mapping, var_report, rng)
                                    if stub_mapping else None)
                            if stub_out:
                                input_state["_stub_outcomes"] = {
                                    k: list(v) for k, v in stub_out.items()
                                }
                            directed_attempts += 1
                            _inject_defaults(input_state, search_rng)

                            # Run: directly invoke unreachable paragraphs
                            try:
                                if is_unreachable:
                                    ds = _run_paragraph_directly(
                                        module, directed_target, input_state)
                                else:
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
                                d_br = frozenset(ds.get("_branches", set()))
                                if _should_add_to_corpus(fuzzer, d_cov, d_edges, d_br):
                                    d_entry = _CorpusEntry(
                                        input_state={k: v for k, v in input_state.items()
                                                     if not k.startswith("_stub")},
                                        coverage=d_cov,
                                        edges=d_edges,
                                        added_at=i,
                                        stub_outcomes=stub_out,
                                    )
                                    _add_to_corpus(fuzzer, d_entry, d_br)
                                    # Walk around successful directed input
                                    if var_report is not None and llm_walk_rounds > 0:
                                        _random_walk_suggestion(
                                            module, input_state, var_report,
                                            rng, fuzzer, stub_mapping,
                                            search_rng, _inject_defaults,
                                            max_rounds=llm_walk_rounds,
                                            call_graph=call_graph,
                                        )
                                    if directed_target in d_cov:
                                        directed_target = None
                                        directed_attempts = 0
                            except (RecursionError, Exception):
                                pass
                    else:
                        # All paragraphs covered
                        stale_random_remaining = _STALE_RANDOM_BURST
                else:
                    # No static analysis — fall back to random burst
                    stale_random_remaining = _STALE_RANDOM_BURST

                # Concolic phase: use Z3 to solve for uncovered branches
                if concolic and var_report is not None:
                    _branch_meta = getattr(module, '_BRANCH_META', {})
                    if _branch_meta:
                        _clog = logging.getLogger("specter.monte_carlo")
                        _clog.debug("Concolic stale-trigger at iter %d "
                                    "(branches=%d/%d)",
                                    i, len(fuzzer.global_branches),
                                    len(_branch_meta) * 2)
                        try:
                            from .concolic import solve_for_uncovered_branches
                            observed = [e.input_state for e in fuzzer.corpus[-10:]] if fuzzer.corpus else [{}]
                            solutions = solve_for_uncovered_branches(
                                _branch_meta, fuzzer.global_branches,
                                var_report, observed,
                                stub_mapping=stub_mapping,
                                corpus_entries=fuzzer.corpus,
                            )
                            _concolic_new = 0
                            for sol in solutions:
                                # Pick best base state: prefer a corpus entry
                                # that already reaches the target paragraph
                                target_para = _branch_meta.get(
                                    abs(sol.branch_id), {},
                                ).get("paragraph", "")
                                base, base_stubs = _pick_concolic_base(
                                    fuzzer, target_para,
                                )
                                base.update(sol.assignments)

                                # Merge stub outcomes: concolic-solved stubs
                                # override, others keep base stubs
                                merged_stubs = dict(base_stubs) if base_stubs else {}
                                if sol.stub_outcomes:
                                    merged_stubs.update(sol.stub_outcomes)
                                if merged_stubs:
                                    base["_stub_outcomes"] = {
                                        k: list(v) for k, v in merged_stubs.items()
                                    }
                                _inject_defaults(base, search_rng)
                                try:
                                    cs = module.run(base)
                                    c_trace = cs.get("_trace", [])
                                    c_cov = frozenset(c_trace)
                                    c_edges = frozenset(
                                        (c_trace[j], c_trace[j + 1])
                                        for j in range(len(c_trace) - 1)
                                        if c_trace[j] != c_trace[j + 1]
                                    )
                                    for p in c_trace:
                                        fuzzer.para_hits[p] += 1
                                    fuzzer.n_successful += 1
                                    c_br = frozenset(cs.get("_branches", set()))
                                    if _should_add_to_corpus(fuzzer, c_cov, c_edges, c_br):
                                        new_br = c_br - fuzzer.global_branches
                                        new_para = c_cov - fuzzer.global_coverage
                                        _clog.debug(
                                            "Concolic: branch %d +%d br +%d para",
                                            sol.branch_id,
                                            len(new_br), len(new_para))
                                        _concolic_new += 1
                                        c_entry = _CorpusEntry(
                                            input_state={k: v for k, v in base.items()
                                                         if not k.startswith("_stub")},
                                            coverage=c_cov,
                                            edges=c_edges,
                                            added_at=i,
                                            stub_outcomes=merged_stubs if merged_stubs else None,
                                        )
                                        _add_to_corpus(fuzzer, c_entry, c_br)
                                        if var_report is not None and llm_walk_rounds > 0:
                                            _random_walk_suggestion(
                                                module, base, var_report,
                                                rng, fuzzer, stub_mapping,
                                                search_rng, _inject_defaults,
                                                max_rounds=llm_walk_rounds,
                                                call_graph=call_graph,
                                            )
                                except (RecursionError, Exception):
                                    pass
                            _clog.debug("Concolic stale done: %d/%d new",
                                       _concolic_new, len(solutions))
                        except ImportError:
                            pass  # z3 not installed — skip concolic

                fuzzer.stale_counter = 0

        if parent is not None:
            parent.mutation_count += 1

        # Periodically update energy scores
        if (i > 0 and i % _ENERGY_UPDATE_INTERVAL == 0
                and fuzzer.corpus and all_paragraphs):
            _update_energy(fuzzer, all_paragraphs)

        # Periodic concolic phase — runs every 500 iterations
        # independent of stale counter, to continuously target
        # uncovered branches
        _CONCOLIC_INTERVAL = 500
        if (concolic and var_report is not None
                and i > 0 and i % _CONCOLIC_INTERVAL == 0):
            _branch_meta = getattr(module, '_BRANCH_META', {})
            if _branch_meta:
                _clog = logging.getLogger("specter.monte_carlo")
                _clog.debug("Concolic periodic at iter %d "
                            "(branches=%d/%d)",
                            i, len(fuzzer.global_branches),
                            len(_branch_meta) * 2)
                try:
                    from .concolic import solve_for_uncovered_branches
                    observed = [e.input_state for e in fuzzer.corpus[-10:]] if fuzzer.corpus else [{}]
                    solutions = solve_for_uncovered_branches(
                        _branch_meta, fuzzer.global_branches,
                        var_report, observed,
                        stub_mapping=stub_mapping,
                        corpus_entries=fuzzer.corpus,
                    )
                    _concolic_hits = 0
                    for sol in solutions:
                        target_para = _branch_meta.get(
                            abs(sol.branch_id), {},
                        ).get("paragraph", "")
                        base, base_stubs = _pick_concolic_base(
                            fuzzer, target_para,
                        )
                        base.update(sol.assignments)
                        merged_stubs = dict(base_stubs) if base_stubs else {}
                        if sol.stub_outcomes:
                            merged_stubs.update(sol.stub_outcomes)
                        if merged_stubs:
                            base["_stub_outcomes"] = {
                                k: list(v) for k, v in merged_stubs.items()
                            }
                        _inject_defaults(base, search_rng)
                        try:
                            cs = module.run(base)
                            c_trace = cs.get("_trace", [])
                            c_cov = frozenset(c_trace)
                            c_edges = frozenset(
                                (c_trace[j], c_trace[j + 1])
                                for j in range(len(c_trace) - 1)
                                if c_trace[j] != c_trace[j + 1]
                            )
                            for p in c_trace:
                                fuzzer.para_hits[p] += 1
                            fuzzer.n_successful += 1
                            c_br = frozenset(cs.get("_branches", set()))
                            if _should_add_to_corpus(fuzzer, c_cov, c_edges, c_br):
                                _concolic_hits += 1
                                c_entry = _CorpusEntry(
                                    input_state={k: v for k, v in base.items()
                                                 if not k.startswith("_stub")},
                                    coverage=c_cov,
                                    edges=c_edges,
                                    added_at=i,
                                    stub_outcomes=merged_stubs if merged_stubs else None,
                                )
                                _add_to_corpus(fuzzer, c_entry, c_br)
                                if var_report is not None and llm_walk_rounds > 0:
                                    _random_walk_suggestion(
                                        module, base, var_report,
                                        rng, fuzzer, stub_mapping,
                                        search_rng, _inject_defaults,
                                        max_rounds=llm_walk_rounds,
                                        call_graph=call_graph,
                                    )
                        except (RecursionError, Exception):
                            pass
                    if _concolic_hits:
                        _clog.info("Concolic @%d: %d/%d solutions -> new coverage",
                                   i, _concolic_hits, len(solutions))
                except ImportError:
                    pass

    # Count total branch points from the generated module source
    total_branches = 0
    try:
        import re as _re2
        src = __import__("inspect").getsource(module)
        total_branches = len(set(
            int(m) for m in _re2.findall(r"_branches.*?\.add\((-?\d+)\)", src)
        ))
    except Exception:
        pass

    return _build_report_from_fuzzer(fuzzer, n_iterations, all_paragraphs,
                                    call_graph=call_graph,
                                    total_branches=total_branches)


def _build_report_from_fuzzer(fuzzer: _FuzzerState, n_iterations: int,
                              all_paragraphs: list[str] | None,
                              call_graph=None,
                              total_branches: int = 0) -> MonteCarloReport:
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

    report.sample_call_events = fuzzer.sample_call_events

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

    analysis.branch_hits = len(fuzzer.global_branches)
    analysis.total_branches = total_branches

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
    program=None,
    llm_provider=None,
    llm_model: str | None = None,
    llm_interval: int = 500,
    llm_walk_rounds: int = _LLM_WALK_ROUNDS,
    concolic: bool = False,
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
        llm_provider: Optional LLMProvider instance (from war_rig llm_providers)
            for LLM-guided coverage maximization.
        llm_model: Optional model override for the LLM provider.
        llm_interval: How often (in iterations) to query the LLM for
            coverage suggestions (default 500).
        concolic: If True, use Z3 concolic engine to solve for uncovered
            branches when the fuzzer stalls (requires z3-solver).

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
            program=program,
            llm_provider=llm_provider,
            llm_model=llm_model,
            llm_walk_rounds=llm_walk_rounds,
            llm_interval=llm_interval,
            concolic=concolic,
        )

    rng = random.Random(seed)
    report = MonteCarloReport(n_iterations=n_iterations)
    _all_branches: set[int] = set()

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
                iteration.call_events = result_state.get("_call_events", [])
                _all_branches.update(result_state.get("_branches", set()))

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

        analysis = build_analysis_report(
            inst_data, all_paragraphs or [],
        )

        # Compute branch coverage from collected branches
        try:
            import re as _re2
            import inspect as _inspect
            src = _inspect.getsource(module)
            total_branches = len(set(
                int(m) for m in _re2.findall(r"_branches.*?\.add\((-?\d+)\)", src)
            ))
            analysis.total_branches = total_branches
            analysis.branch_hits = len(_all_branches)
        except Exception:
            pass

        report.analysis_report = analysis

    return report
