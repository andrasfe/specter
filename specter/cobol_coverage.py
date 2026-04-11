"""Agentic coverage-guided test generation engine.

Runs an execute-many loop with pluggable strategies to maximize paragraph and
branch coverage.  Supports both Python-only execution (from AST) and
GnuCOBOL-compiled programs.  A strategy selector picks the next strategy based
on coverage feedback.  All generated test cases are persisted to a JSONL test
store for downstream use.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import logging
import os
import random
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from .cobol_executor import (
    CobolExecutionContext,
    CobolTestResult,
    prepare_context,
    run_test_case,
)
from .backward_slicer import slice_variable_names
from .cobol_mock import generate_mock_data_ordered
from .coverage_strategies import (
    BaselineStrategy,
    CorpusFuzzStrategy,
    DirectParagraphStrategy,
    FaultInjectionStrategy,
    HeuristicSelector,
    Strategy,
    StrategyContext,
    StrategyYield,
    TranscriptSearchStrategy,
)
from .jit_value_inference import JITValueInferenceService
from .llm_test_states import extract_paragraph_comments
from .memory_models import APIBudgetLedger, StrategyStats as PersistedStrategyStats, SuccessState
from .memory_store import MemoryStore, derive_memory_dir
from .models import Program
from .static_analysis import (
    StaticCallGraph,
    extract_gating_variables_for_target,
    build_static_call_graph,
    compute_path_constraints,
    extract_gating_conditions,
    extract_sequential_gates,
    augment_gating_with_sequential_gates,
)
from .variable_domain import (
    VariableDomain,
    build_payload_value_candidates,
    build_variable_domains,
    format_value_for_cobol,
    generate_value,
    load_copybooks,
    payload_kind_for_domain,
    _FILE_STATUS_CODES,
    _SQL_STATUS_CODES,
    _CICS_STATUS_CODES,
    _DLI_STATUS_CODES,
)
from .variable_extractor import VariableReport, extract_stub_status_mapping, extract_variables

log = logging.getLogger(__name__)

# Well-known IBM MQ constants (from CMQV copybook).
# These are defined in external copybooks that are typically not shipped
# with application source, so we hardcode the standard values.
_MQ_CONSTANTS: dict[str, int] = {
    "MQCC-OK": 0,
    "MQCC-WARNING": 1,
    "MQCC-FAILED": 2,
    "MQRC-NONE": 0,
    "MQRC-NO-MSG-AVAILABLE": 2033,
    "MQRC-NOT-AUTHORIZED": 2035,
    "MQRC-Q-FULL": 2053,
    "MQRC-TRUNCATED-MSG-ACCEPTED": 2079,
    "MQOO-INPUT-AS-Q-DEF": 1,
    "MQOO-OUTPUT": 16,
    "MQOO-INQUIRE": 32,
}


def _enrich_domains_with_boolean_hints(
    domains: dict[str, VariableDomain],
    program: Program,
) -> None:
    """Add True/False as condition_literals for vars used as standalone boolean
    conditions in EVALUATE WHEN TRUE or IF statements.

    Variables like ACCOUNT-CLOSED, CARD-FRAUD etc. appear in EVALUATE WHEN
    as boolean checks but have no condition_literals in the domain model,
    so the coverage engine never tries setting them to True.
    """
    def _scan(stmt):
        if stmt.type == "EVALUATE" and stmt.attributes.get("subject", "").upper() == "TRUE":
            for child in stmt.children:
                if child.type == "WHEN":
                    cond = child.text.replace("WHEN", "", 1).strip().upper()
                    # Single variable name (not a compound condition)
                    if re.match(r"^[A-Z][A-Z0-9-]*$", cond):
                        dom = domains.get(cond)
                        if dom and True not in dom.condition_literals:
                            dom.condition_literals.append(True)
                            dom.condition_literals.append(False)
        for child in stmt.children:
            _scan(child)

    for para in program.paragraphs:
        for stmt in para.statements:
            _scan(stmt)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class CoverageState:
    """Tracks cumulative coverage across all test cases."""

    paragraphs_hit: set[str] = field(default_factory=set)
    runtime_only_paragraphs: set[str] = field(default_factory=set)
    branches_hit: set[str] = field(default_factory=set)
    total_paragraphs: int = 0
    total_branches: int = 0
    test_cases: list[dict] = field(default_factory=list)
    all_paragraphs: set[str] = field(default_factory=set)
    strategy_yields: dict[str, StrategyYield] = field(default_factory=dict)
    stale_rounds: int = 0
    consecutive_timeouts: int = 0
    repeat_signature_count: int = 0
    last_result_signature: tuple[frozenset[str], frozenset[str]] | None = None
    # Kept for strategies that check stub_mapping availability
    _stub_mapping: dict[str, list[str]] = field(default_factory=dict)
    # Infrastructure branch keys to exclude from reported coverage.
    _infra_keys: set[str] = field(default_factory=set)


@dataclass
class CobolCoverageReport:
    """Summary of a coverage generation run."""

    total_test_cases: int = 0
    paragraph_coverage: float = 0.0
    branch_coverage: float = 0.0
    paragraphs_hit: int = 0
    paragraphs_total: int = 0
    branches_hit: int = 0
    branches_total: int = 0
    elapsed_seconds: float = 0.0
    runtime_trace_total: int = 0
    runtime_only_paragraphs: int = 0
    layer_stats: dict[str, int] = field(default_factory=dict)

    def summary(self) -> str:
        lines = [
            "=== COBOL Coverage Report ===",
            f"  Test cases:  {self.total_test_cases}",
            f"  Paragraphs:  {self.paragraphs_hit}/{self.paragraphs_total} "
            f"({self.paragraph_coverage:.1%})",
            f"  Runtime paragraph labels: {self.runtime_trace_total} "
            f"(runtime-only: {self.runtime_only_paragraphs})",
            f"  Branches:    {self.branches_hit}/{self.branches_total} "
            f"({self.branch_coverage:.1%})",
            f"  Time:        {self.elapsed_seconds:.1f}s",
        ]
        if self.layer_stats:
            lines.append("  Per strategy:")
            for name, count in sorted(self.layer_stats.items()):
                lines.append(f"    {name}: {count} test cases")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# LLM seed injector (one-shot strategy from pre-generated seeds)
# ---------------------------------------------------------------------------

class _LLMSeedInjector(Strategy):
    """Injects pre-generated LLM seeds as test cases.  Runs once."""

    name = "llm_seeds"
    priority = 5  # run first

    def __init__(self, seeds: list[dict], stub_mapping: dict[str, list[str]]):
        self._seeds = seeds
        self._stub_mapping = stub_mapping
        self._ran = False

    def should_run(self, cov, round_num: int) -> bool:
        return not self._ran

    def generate_cases(self, ctx, cov, batch_size):
        self._ran = True
        for seed_data in self._seeds:
            input_state = {}
            for var, val in seed_data.get("input_values", {}).items():
                dom = ctx.domains.get(var.upper())
                if dom:
                    input_state[var.upper()] = format_value_for_cobol(dom, val)
                else:
                    input_state[var.upper()] = str(val)

            # Build stubs from overrides
            stubs = dict(ctx.success_stubs)
            defaults = dict(ctx.success_defaults)
            for op_key, status_val in seed_data.get("stub_overrides", {}).items():
                matched = _match_stub_operation(op_key, self._stub_mapping)
                if matched:
                    svars = self._stub_mapping[matched]
                    entry = [(sv, status_val) for sv in svars]
                    stubs[matched] = [entry] * 50
                    defaults[matched] = entry

            target = seed_data.get("target", "llm_seed")[:50]
            yield input_state, stubs, defaults, f"seed:{target}"


# ---------------------------------------------------------------------------
# Test case store (JSONL)
# ---------------------------------------------------------------------------

def _compute_tc_id(input_state: dict, stub_log: list) -> str:
    payload = json.dumps(
        {"input_state": input_state, "stub_log": stub_log},
        sort_keys=True, default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _save_test_case(
    store_path: Path,
    tc_id: str,
    input_state: dict,
    stub_log: list,
    result: CobolTestResult,
    layer: str | int,
    target: str,
) -> None:
    """Append a test case to the JSONL store."""
    record = {
        "id": tc_id,
        "input_state": {k: v for k, v in input_state.items() if not str(k).startswith("_")},
        "stub_outcomes": [[op, entries] for op, entries in stub_log],
        "paragraphs_hit": result.paragraphs_hit,
        "branches_hit": sorted(result.branches_hit),
        "display_output": result.display_output,
        "layer": layer,
        "target": target,
    }
    store_path.parent.mkdir(parents=True, exist_ok=True)
    with open(store_path, "a") as f:
        f.write(json.dumps(record, default=str) + "\n")


def load_existing_coverage(store_path: Path) -> tuple[list[dict], set[str], set[str]]:
    """Load existing test cases and compute baseline coverage."""
    if not store_path.exists():
        return [], set(), set()

    test_cases = []
    paras: set[str] = set()
    branches: set[str] = set()
    seen_ids: set[str] = set()

    for line in store_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "id" not in d or d.get("_type"):
            continue
        tc_id = d["id"]
        if tc_id in seen_ids:
            continue
        seen_ids.add(tc_id)
        test_cases.append(d)
        paras.update(d.get("paragraphs_hit", []))
        branches.update(d.get("branches_hit", []))

    return test_cases, paras, branches


def _counted_branches_for_mode(
    branches_hit: set[str],
    cobol_mode: bool,
    infra_keys: set[str] | None = None,
) -> set[str]:
    """Return the branch set that should count toward reported coverage.

    Filters out:
      * ``py:``-prefixed Python-only branches when in COBOL mode.
      * Infrastructure branches (specter's own SPECTER-* paragraphs)
        when *infra_keys* is provided — these are not real program
        logic and should not inflate the coverage numerator.
    """
    result = branches_hit
    if cobol_mode:
        result = {b for b in result if not b.startswith("py:")}
    if infra_keys:
        result = {b for b in result if b not in infra_keys}
    return result


def _infrastructure_branch_keys(branch_meta: dict) -> set[str]:
    """Return branch keys (e.g. ``"42:T"``, ``"42:F"``) that belong to
    specter's own instrumentation infrastructure and should be excluded
    from the user-facing coverage total.

    Infrastructure branches are injected by the mock pipeline (OPEN/CLOSE
    MOCK-FILE, SPECTER-READ-INIT-VARS, SPECTER-NEXT-MOCK-RECORD,
    SPECTER-APPLY-MOCK-PAYLOAD, SPECTER-EXIT-PARA, mock-file EOF
    handling). They are real COBOL code that compiles and runs, but they
    are NOT part of the user's business logic — counting them inflates
    the denominator and misleads the reviewer about what remains to
    cover.

    The filter is conservative: it only excludes branches whose
    enclosing paragraph starts with ``SPECTER-`` or is ``FILE-CONTROL``.
    A slightly broader heuristic (checking for ``MOCK-EOF-FLAG`` in the
    condition text) would catch more, but requires the full mock source
    scan which we don't always have at counting time.
    """
    infra: set[str] = set()
    for raw_bid, meta in branch_meta.items():
        try:
            bid = int(raw_bid)
        except (TypeError, ValueError):
            continue
        para = str(meta.get("paragraph", "")).upper()
        if (
            para.startswith("SPECTER-")
            or para == "FILE-CONTROL"
        ):
            infra.add(f"{bid}:T")
            infra.add(f"{bid}:F")
    return infra


def _extract_branch_target_from_label(target: str) -> tuple[int, str] | None:
    """Extract ``(branch_id, direction)`` from a strategy target label."""
    text = str(target or "").strip()
    if not text:
        return None

    direct_payload = text
    if text.startswith("direct:"):
        direct_payload = text[7:]
        if "|" in direct_payload:
            _, direct_payload = direct_payload.split("|", 1)
        else:
            direct_payload = ""

    m = re.search(r"(?:^|:)\s*(\d+)\s*:\s*([TF])(?:\b|:|$)", direct_payload, re.IGNORECASE)
    if not m:
        m = re.search(r"^branch\s*:\s*(\d+)\s*:\s*([TF])$", text, re.IGNORECASE)
    if not m:
        return None

    try:
        bid = int(m.group(1))
    except (TypeError, ValueError):
        return None
    return bid, m.group(2).upper()


def _canonical_target_key(target: str) -> str:
    """Normalize a raw strategy target label into a stable memory key."""
    text = str(target or "").strip()
    if not text:
        return "none"

    branch = _extract_branch_target_from_label(text)
    if branch is not None:
        bid, direction = branch
        return f"branch:{bid}:{direction}"

    if text.startswith("direct:"):
        para = text[7:].split("|", 1)[0].strip()
        if para:
            return f"para:{para}"
    return text


def _best_memory_seed_input(
    memory_state,
    target_key: str,
) -> dict[str, object]:
    """Pick the strongest prior successful input for a canonical target key."""
    if memory_state is None:
        return {}

    successes = list(getattr(memory_state, "successes", []) or [])
    if not successes:
        return {}

    exact: list[dict[str, object]] = []
    para_fallback: list[dict[str, object]] = []
    want_para = None
    if target_key.startswith("branch:"):
        branch_id = target_key.split(":", 2)[1]
        status = getattr(memory_state, "targets", {}).get(target_key)
        if status is not None and getattr(status, "last_error", "") == "":
            # keep exact-first; status lookup is just for future extension
            pass
        for success in successes:
            skey = _canonical_target_key(getattr(success, "target", ""))
            if skey == target_key:
                exact.append({
                    "input_state": dict(getattr(success, "input_state", {}) or {}),
                    "paragraphs_hit": list(getattr(success, "paragraphs_hit", []) or []),
                    "branches_hit": list(getattr(success, "branches_hit", []) or []),
                })
                continue
            if skey.startswith("para:") and any(
                str(b).startswith(f"{branch_id}:") for b in (getattr(success, "branches_hit", []) or [])
            ):
                para_fallback.append({
                    "input_state": dict(getattr(success, "input_state", {}) or {}),
                    "paragraphs_hit": list(getattr(success, "paragraphs_hit", []) or []),
                    "branches_hit": list(getattr(success, "branches_hit", []) or []),
                })
    else:
        want_para = target_key if target_key.startswith("para:") else None
        for success in successes:
            skey = _canonical_target_key(getattr(success, "target", ""))
            if skey == target_key:
                exact.append({
                    "input_state": dict(getattr(success, "input_state", {}) or {}),
                    "paragraphs_hit": list(getattr(success, "paragraphs_hit", []) or []),
                    "branches_hit": list(getattr(success, "branches_hit", []) or []),
                })

    candidates = exact or para_fallback
    if not candidates and want_para is None:
        return {}
    if not candidates and want_para is not None:
        return {}

    best = max(
        candidates,
        key=lambda tc: (
            len(tc.get("paragraphs_hit", [])),
            len(tc.get("branches_hit", [])),
        ),
    )
    return dict(best.get("input_state", {}))


def _select_priority_branch_target(ctx: StrategyContext, cov: CoverageState) -> str | None:
    """Choose the next branch target key using uncovered set + memory status."""
    if not getattr(ctx, "branch_meta", None):
        return None

    memory_state = getattr(ctx, "memory_state", None)
    target_status = getattr(memory_state, "targets", {}) if memory_state is not None else {}
    scored: list[tuple[int, int, int, str]] = []

    for raw_bid in ctx.branch_meta:
        try:
            bid = int(raw_bid)
        except (TypeError, ValueError):
            continue
        for direction in ("T", "F"):
            hit_key = f"{bid}:{direction}"
            if hit_key in cov.branches_hit:
                continue
            tkey = f"branch:{bid}:{direction}"
            status = target_status.get(tkey)
            solved = int(bool(getattr(status, "solved", False))) if status else 0
            attempts = int(getattr(status, "attempts", 0) or 0) if status else 0
            nearest = int(getattr(status, "nearest_branch_hits", 0) or 0) if status else 0
            scored.append((solved, attempts, -nearest, tkey))

    if not scored:
        return None
    scored.sort()
    return scored[0][3]


def _best_cobol_seed_input(cov: CoverageState) -> dict[str, object]:
    """Pick the best previously saved full-program COBOL seed state."""
    candidates = [
        tc for tc in cov.test_cases
        if tc.get("input_state")
        and not str(tc.get("target", "")).startswith("direct:")
        and not any(str(b).startswith("py:") for b in tc.get("branches_hit", []))
    ]
    if not candidates:
        return {}
    best = max(
        candidates,
        key=lambda tc: (
            len(tc.get("paragraphs_hit", [])),
            len(tc.get("branches_hit", [])),
        ),
    )
    return dict(best.get("input_state", {}))


def _project_cobol_replay_input(
    input_state: dict[str, object],
    injectable_vars: list[str],
    seed_state: dict[str, object] | None = None,
) -> dict[str, object]:
    """Project a Python direct-execution state down to COBOL entry inputs."""
    allowed = {name.upper() for name in injectable_vars}
    projected = {
        name: value
        for name, value in input_state.items()
        if isinstance(name, str)
        and not name.startswith("_")
        and name.upper() in allowed
    }
    if seed_state:
        merged = dict(seed_state)
        merged.update(projected)
        return merged
    return projected


# ---------------------------------------------------------------------------
# Python pre-run (for stub_log ordering)
# ---------------------------------------------------------------------------

def _python_pre_run(
    module,
    input_state: dict,
    stub_outcomes: dict | None = None,
    stub_defaults: dict | None = None,
) -> list[tuple[str, list]]:
    """Run the Python module to get execution-ordered stub_log.

    Returns stub_log: list of (op_key, entry) tuples.
    """
    state = {}
    default_state_fn = getattr(module, "_default_state", None)
    if default_state_fn:
        state = default_state_fn()

    # Inject MQ constants
    var_names = {k.upper() for k in state}
    for name, value in _MQ_CONSTANTS.items():
        if name.upper() in var_names:
            state[name.upper()] = value

    state.update(input_state)

    if stub_outcomes:
        state["_stub_outcomes"] = {
            k: [list(e) if isinstance(e, list) else e for e in v]
            for k, v in stub_outcomes.items()
        }
    if stub_defaults:
        state["_stub_defaults"] = dict(stub_defaults)
    state["_stub_log"] = []

    try:
        result = module.run(state)
    except Exception:
        result = state

    return result.get("_stub_log", state.get("_stub_log", []))


def _python_execute(
    module,
    input_state: dict,
    stub_outcomes: dict | None = None,
    stub_defaults: dict | None = None,
    paragraph: str | None = None,
) -> CobolTestResult:
    """Run the Python module and return a CobolTestResult-compatible object.

    If *paragraph* is given, invokes that paragraph directly instead of
    running from the program entry point.  This is much faster and can
    reach branches not reachable through the normal entry.
    """
    from .monte_carlo import _run_paragraph_directly

    default_state_fn = getattr(module, "_default_state", None)
    state = default_state_fn() if default_state_fn else {}

    # Inject well-known MQ constants so comparisons like
    # WS-COMPCODE = MQCC-OK work (MQCC-OK must be integer 0, not '').
    var_names = {k.upper() for k in state}
    for name, value in _MQ_CONSTANTS.items():
        if name.upper() in var_names:
            state[name.upper()] = value

    state.update(input_state)

    if stub_outcomes:
        state["_stub_outcomes"] = {
            k: [list(e) if isinstance(e, list) else e for e in v]
            for k, v in stub_outcomes.items()
        }
    if stub_defaults:
        state["_stub_defaults"] = dict(stub_defaults)
    state["_stub_log"] = []

    try:
        if paragraph:
            rs = _run_paragraph_directly(module, paragraph, state)
            if not rs:
                return CobolTestResult(error="paragraph not found")
        else:
            rs = module.run(state)
    except Exception as exc:
        return CobolTestResult(error=f"{type(exc).__name__}: {exc}")

    # Convert integer branches to "py:<bid>:T"/"py:<bid>:F" string format.
    # The "py:" prefix prevents collision with COBOL branch IDs (@@B:)
    # since the two numbering schemes are independent.
    raw_branches = rs.get("_branches", set())
    branches_hit: set[str] = set()
    for b in raw_branches:
        if b > 0:
            branches_hit.add(f"py:{b}:T")
        elif b < 0:
            branches_hit.add(f"py:{abs(b)}:F")

    trace = rs.get("_trace", [])
    paragraphs_hit = list(dict.fromkeys(trace))
    display_output = rs.get("_display", [])

    return CobolTestResult(
        paragraphs_hit=paragraphs_hit,
        branches_hit=branches_hit,
        display_output=display_output,
    )


# ---------------------------------------------------------------------------
# Value builders
# ---------------------------------------------------------------------------

def _compute_mq_overrides(var_report: VariableReport) -> dict[str, int]:
    """Compute MQ constant overrides for variables in the var_report."""
    overrides: dict[str, int] = {}
    var_names = {v.upper() for v in var_report.variables}
    for name, value in _MQ_CONSTANTS.items():
        if name.upper() in var_names:
            overrides[name.upper()] = value
    return overrides


def _is_replay_injectable_var(name: str, dom, eib_names: set) -> bool:
    """Return whether a variable is safe and useful for init replay injection.

    Internal variables are typically less useful, but internal parents with
    88-level values remain actionable because replay can activate those named
    conditions by setting the parent directly.
    """
    if not (getattr(dom, 'condition_literals', None) or getattr(dom, 'valid_88_values', None)):
        return False
    if getattr(dom, 'set_by_stub', None):
        return False
    if name.upper() in eib_names:
        return False
    classification = getattr(dom, 'classification', '')
    if classification in ("input", "status", "flag"):
        return True
    return bool(getattr(dom, 'valid_88_values', None))


def _build_input_state(
    domains: dict[str, VariableDomain],
    strategy: str,
    rng: random.Random,
    overrides: dict | None = None,
    mq_overrides: dict | None = None,
    jit_inference: object | None = None,
    target_paragraph: str | None = None,
    paragraph_comments: dict[str, list[str]] | None = None,
) -> dict[str, object]:
    """Build an input state dict using the domain model."""
    state: dict[str, object] = {}
    for name, dom in domains.items():
        if dom.classification not in ("input", "status", "flag"):
            continue
        if dom.set_by_stub:
            continue  # stub-controlled, not input
        val = None
        if jit_inference is not None:
            comment_hints = []
            if paragraph_comments and target_paragraph:
                comment_hints = paragraph_comments.get(target_paragraph, [])
            val = jit_inference.generate_value(
                name,
                dom,
                strategy,
                rng,
                target_paragraph=target_paragraph,
                comment_hints=comment_hints,
                op_key=dom.set_by_stub,
            )
        if val is None:
            val = generate_value(dom, strategy, rng)
        state[name] = format_value_for_cobol(dom, val)

    # CICS-aware defaults: ensure key EIB fields enable deeper execution
    upper_names = {n.upper(): n for n in state}
    if "EIBCALEN" in upper_names:
        # Set EIBCALEN > 0 to simulate returning transaction (not first entry)
        # This is critical for CICS programs to get past initialization logic
        state[upper_names["EIBCALEN"]] = str(rng.choice([20, 50, 100, 200]))
    if "EIBAID" in upper_names:
        # Common AID keys: ENTER, PF3 (return), PF7/PF8 (scroll)
        aids = ["ENTER", "DFHENTER", "DFHPF3", "DFHPF7", "DFHPF8", "DFHCLEAR"]
        state[upper_names["EIBAID"]] = rng.choice(aids)

    # MQ constants: ensure well-known IBM MQ constants have correct values
    if mq_overrides:
        state.update(mq_overrides)

    if overrides:
        state.update(overrides)
    return state


def _build_target_variable_allowlists(
    module: object,
    branch_meta: dict,
    gating_conds: dict[str, list],
    stub_mapping: dict[str, list[str]],
    *,
    include_gates: bool,
    include_slice: bool,
) -> dict[str, set[str]]:
    """Build per-target variable allowlists keyed by paragraph and branch.

    Keys include:
    - ``para:<paragraph>`` (fallback/default scope)
    - ``branch:<bid>:T`` and ``branch:<bid>:F`` when branch id is known
    """
    if not branch_meta:
        return {}

    out: dict[str, set[str]] = {}
    module_source = ""
    if include_slice:
        try:
            module_source = inspect.getsource(module)
        except Exception:
            module_source = ""

    stub_vars: set[str] = set()
    for vars_for_op in stub_mapping.values():
        for var in vars_for_op:
            name = str(var or "").strip().upper()
            if name:
                stub_vars.add(name)

    for bid, meta in branch_meta.items():
        para = str(meta.get("paragraph", "") or "").strip()
        if not para:
            continue
        key = f"para:{para}"
        allowed = out.setdefault(key, set())

        if include_gates:
            allowed.update(extract_gating_variables_for_target(gating_conds, para))
        if stub_vars:
            allowed.update(stub_vars)

        if include_slice and module_source:
            try:
                bid_int = int(bid)
            except (TypeError, ValueError):
                bid_int = None
            if bid_int is not None:
                t_slice = slice_variable_names(module_source, bid_int)
                f_slice = slice_variable_names(module_source, -bid_int)

                allowed.update(t_slice)
                allowed.update(f_slice)

                key_t = f"branch:{bid_int}:T"
                key_f = f"branch:{bid_int}:F"

                branch_t = out.setdefault(key_t, set())
                branch_f = out.setdefault(key_f, set())

                branch_t.update(allowed)
                branch_f.update(allowed)
                branch_t.update(t_slice)
                branch_f.update(f_slice)
        else:
            try:
                bid_int = int(bid)
            except (TypeError, ValueError):
                bid_int = None
            if bid_int is not None:
                key_t = f"branch:{bid_int}:T"
                key_f = f"branch:{bid_int}:F"
                out.setdefault(key_t, set()).update(allowed)
                out.setdefault(key_f, set()).update(allowed)

    return out


def _extract_88_siblings_from_source(cobol_source: str | Path) -> dict[str, set[str]]:
    """Extract 88-level sibling groups by scanning COBOL source.

    Reads the .cbl file line-by-line, tracking the current parent variable.
    Consecutive 88-level items under the same parent are siblings.
    """
    siblings: dict[str, set[str]] = {}
    current_group: list[str] = []
    path = Path(cobol_source)
    if not path.exists():
        return siblings

    _88_re = re.compile(r"^\s+88\s+([A-Z0-9][A-Z0-9-]*)\s+VALUE", re.IGNORECASE)
    _level_re = re.compile(r"^\s+(\d{1,2})\s+([A-Z0-9][A-Z0-9-]*)", re.IGNORECASE)

    def _flush_group():
        if len(current_group) > 1:
            names = set(current_group)
            for name in names:
                siblings.setdefault(name, set()).update(names - {name})

    for line in path.read_text(errors="replace").splitlines():
        m88 = _88_re.match(line)
        if m88:
            current_group.append(m88.group(1).upper())
            continue
        mlevel = _level_re.match(line)
        if mlevel and mlevel.group(1) != "88":
            _flush_group()
            current_group = []

    _flush_group()
    return siblings


def _build_siblings_88(
    copybook_records,
    cobol_source: str | Path | None = None,
) -> dict[str, set[str]]:
    """Build 88-level siblings map from copybook records and COBOL source.

    Combines siblings discovered from copybook field definitions with
    those extracted directly from the COBOL source (where 88-levels are
    often defined inline rather than in copybooks).
    """
    siblings: dict[str, set[str]] = {}
    if copybook_records:
        for rec in copybook_records:
            for fld in rec.fields:
                if fld.values_88:
                    names = {n.upper() for n in fld.values_88.keys()}
                    for name in names:
                        siblings.setdefault(name, set()).update(names - {name})
    # Also scan COBOL source for inline 88-level definitions
    if cobol_source:
        source_siblings = _extract_88_siblings_from_source(cobol_source)
        for name, sibs in source_siblings.items():
            siblings.setdefault(name, set()).update(sibs)
    return siblings


def _expand_stub_mapping(
    stub_mapping: dict[str, list[str]],
    siblings_88: dict[str, set[str]],
) -> set[str]:
    """Expand stub mapping to include 88-level sibling vars.

    Only expands ops where ALL original status vars are 88-level flags
    (i.e. all appear in siblings_88).  Ops that mix 88-level flags with
    non-88 status codes (like CICS with EIBRESP + ERR-CRITICAL) are left
    unchanged to avoid setting numeric status vars to booleans.

    Returns the set of var names that were added (not in the original mapping).
    """
    added: set[str] = set()
    for op_key in list(stub_mapping.keys()):
        status_vars = stub_mapping[op_key]
        original = {v.upper() for v in status_vars}
        # Only expand if ALL original vars are 88-level flags
        if not all(v.upper() in siblings_88 for v in status_vars):
            continue
        to_add: set[str] = set()
        for var in status_vars:
            to_add.update(siblings_88.get(var.upper(), set()))
        for var in sorted(to_add - original):
            status_vars.append(var)
            added.add(var.upper())
    return added


def _build_success_stubs(
    stub_mapping: dict[str, list[str]],
    domains: dict[str, VariableDomain],
    flag_88_added: set[str] | None = None,
    siblings_88: dict[str, set[str]] | None = None,
) -> tuple[dict[str, list], dict[str, list]]:
    """Build all-success stub outcomes and defaults.

    For READ operations: generates multiple success records followed by EOF
    ('10'), with default set to EOF so PERFORM UNTIL loops terminate.
    For other operations: single success entry with success default.

    88-level flags (identified by flag_88_added / siblings_88) are set to
    True for success indicators (original mapping vars) and False for their
    siblings (added vars).
    """
    flag_88_added = flag_88_added or set()
    siblings_88 = siblings_88 or {}
    outcomes: dict[str, list] = {}
    defaults: dict[str, list] = {}

    for op_key, status_vars in stub_mapping.items():
        is_read = op_key.startswith("READ:")

        # Identify the primary success flag among 88-level vars.
        # Heuristic: prefer vars with OK/SUCCESS in name, else first original.
        _88_originals = [v for v in status_vars
                         if v.upper() in siblings_88 and v.upper() not in flag_88_added]
        _success_flag = None
        for v in _88_originals:
            if any(kw in v.upper() for kw in ("OK", "SUCCESS", "FOUND")):
                _success_flag = v.upper()
                break
        if not _success_flag and _88_originals:
            _success_flag = _88_originals[0].upper()

        success_entries: list = []
        eof_entries: list = []
        for var in status_vars:
            dom = domains.get(var)
            var_upper = var.upper()
            is_88 = var_upper in siblings_88 or var_upper in flag_88_added
            # 88-level: only the primary success flag is True
            if is_88 and _success_flag:
                success_entries.append((var, var_upper == _success_flag))
                eof_entries.append((var, False))
            elif dom and dom.semantic_type == "status_file":
                success_entries.append((var, "00"))
                eof_entries.append((var, "10"))
            elif dom and dom.semantic_type == "status_sql":
                success_entries.append((var, 0))
                eof_entries.append((var, 100))
            elif dom and dom.semantic_type == "status_cics":
                success_entries.append((var, 0))
                eof_entries.append((var, 0))
            elif op_key.startswith("DLI") or "PCB" in var.upper():
                success_entries.append((var, "  "))
                eof_entries.append((var, "GB"))
            elif op_key.startswith("CALL:MQ"):
                success_entries.append((var, 0))      # MQCC-OK = 0 (integer)
                eof_entries.append((var, 2))           # MQCC-FAILED = 2
            else:
                success_entries.append((var, "00"))
                eof_entries.append((var, "10"))

        if success_entries:
            if is_read:
                # 5 success reads then EOF — enough for loop body coverage
                outcome_list = [success_entries] * 5 + [eof_entries]
                outcomes[op_key] = outcome_list
                defaults[op_key] = eof_entries  # loop terminates on exhaustion
            else:
                outcomes.setdefault(op_key, []).append(success_entries)
                defaults[op_key] = success_entries

    return outcomes, defaults


def _build_fault_stubs(
    stub_mapping: dict[str, list[str]],
    domains: dict[str, VariableDomain],
    target_op: str | None = None,
    fault_value: str | int | None = None,
    rng: random.Random | None = None,
    flag_88_added: set[str] | None = None,
    siblings_88: dict[str, set[str]] | None = None,
) -> tuple[dict[str, list], dict[str, list]]:
    """Build stubs with one operation returning an error code.

    For 88-level flags, fault_value is interpreted as the flag name to
    activate (set to True) while all siblings are set to False.
    """
    if rng is None:
        rng = random.Random()
    flag_88_added = flag_88_added or set()
    siblings_88 = siblings_88 or {}

    outcomes: dict[str, list] = {}
    defaults: dict[str, list] = {}

    for op_key, status_vars in stub_mapping.items():
        entries: list = []
        is_target = (target_op is not None and op_key == target_op)

        # Check if this op has 88-level flags
        has_88 = any(v.upper() in siblings_88 or v.upper() in flag_88_added
                     for v in status_vars)

        # If targeting an op with 88-level flags and fault_value is a flag name,
        # set that flag True and all others False
        target_flag = None
        if is_target and has_88 and isinstance(fault_value, str):
            fv_upper = fault_value.upper()
            if fv_upper in siblings_88 or fv_upper in flag_88_added:
                target_flag = fv_upper

        for var in status_vars:
            dom = domains.get(var)
            var_upper = var.upper()
            is_88 = var_upper in siblings_88 or var_upper in flag_88_added

            if is_target and target_flag:
                # 88-level targeted fault: activate the target, clear others
                entries.append((var, var_upper == target_flag))
            elif is_target and is_88 and not target_flag:
                # 88-level var but fault_value is a status code (e.g. "GE")
                # Set original flags to False, added siblings to False
                entries.append((var, False))
            elif is_target and fault_value is not None:
                entries.append((var, fault_value))
            elif is_target:
                # Pick a non-success value
                if dom and dom.semantic_type == "status_file":
                    entries.append((var, rng.choice(["10", "23", "35"])))
                elif dom and dom.semantic_type == "status_sql":
                    entries.append((var, rng.choice([100, -803, -805])))
                elif "PCB" in var.upper() or op_key.startswith("DLI"):
                    entries.append((var, rng.choice(["GE", "GB", "II"])))
                elif op_key.startswith("CALL:MQ"):
                    entries.append((var, rng.choice([2, 1])))  # MQCC-FAILED, WARNING
                else:
                    entries.append((var, "10"))
            else:
                # Success for non-target ops
                if var_upper in flag_88_added:
                    entries.append((var, False))
                elif var_upper in siblings_88:
                    entries.append((var, True))
                elif dom and dom.semantic_type == "status_file":
                    entries.append((var, "00"))
                elif dom and dom.semantic_type == "status_sql":
                    entries.append((var, 0))
                elif "PCB" in var.upper() or op_key.startswith("DLI"):
                    entries.append((var, "  "))
                elif op_key.startswith("CALL:MQ"):
                    entries.append((var, 0))  # MQCC-OK
                else:
                    entries.append((var, "00"))

        if entries:
            outcomes.setdefault(op_key, []).append(entries)
            defaults[op_key] = entries

    return outcomes, defaults


def _build_transcript_payload_candidates(
    domains: dict[str, VariableDomain],
    stub_mapping: dict[str, list[str]],
    injectable_vars: list[str],
    *,
    max_vars_per_op: int = 6,
    max_values_per_var: int = 5,
) -> tuple[dict[str, str], dict[str, dict[str, list[str | int | float]]]]:
    """Build payload type metadata and focused transcript mutation candidates."""
    payload_variables: dict[str, str] = {}
    payload_candidates: dict[str, dict[str, list[str | int | float]]] = {}

    for name in injectable_vars:
        payload_variables[name] = payload_kind_for_domain(domains.get(name))
    for status_vars in stub_mapping.values():
        for name in status_vars:
            payload_variables[name] = payload_kind_for_domain(domains.get(name))

    scored_candidates: list[tuple[int, str, list[str | int | float]]] = []
    for name in injectable_vars:
        domain = domains.get(name)
        if not domain:
            continue
        values = build_payload_value_candidates(
            domain,
            limit=max_values_per_var,
        )
        if not values:
            continue
        score = 0
        if domain.condition_literals:
            score += 4
        if domain.valid_88_values:
            score += 3
        if domain.semantic_type != "generic":
            score += 2
        if domain.classification == "flag":
            score += 1
        scored_candidates.append((score, name, values))

    scored_candidates.sort(key=lambda item: (-item[0], item[1]))

    for op_key in sorted(stub_mapping):
        if not op_key.startswith("READ:"):
            continue
        op_candidates: dict[str, list[str | int | float]] = {}
        for _, name, values in scored_candidates[:max_vars_per_op]:
            op_candidates[name] = list(values)
            payload_variables.setdefault(name, payload_kind_for_domain(domains.get(name)))
        if op_candidates:
            payload_candidates[op_key] = op_candidates

    payload_variables.setdefault("RETURN-CODE", "numeric")
    payload_variables.setdefault("SQLCODE", "numeric")
    payload_variables.setdefault("DIBSTAT", "alpha")
    payload_variables.setdefault("EIBAID", "alpha")

    return payload_variables, payload_candidates


# ---------------------------------------------------------------------------
# Stub matching helper
# ---------------------------------------------------------------------------

def _match_stub_operation(
    llm_key: str,
    stub_mapping: dict[str, list[str]],
) -> str | None:
    """Match an LLM-provided operation key to a stub_mapping key.

    The LLM might say "READ:XREF" but stub_mapping has "READ:XREF-FILE".
    Uses fuzzy matching on the operation type and file/program name.
    """
    upper = llm_key.upper().strip()
    # Exact match
    if upper in stub_mapping:
        return upper
    # Try case-insensitive
    for key in stub_mapping:
        if key.upper() == upper:
            return key
    # Fuzzy: match operation prefix + substring of target
    if ":" in upper:
        op_type, target = upper.split(":", 1)
        for key in stub_mapping:
            if ":" in key:
                k_op, k_target = key.split(":", 1)
                if k_op.upper() == op_type and target in k_target.upper():
                    return key
            elif key.upper().startswith(op_type):
                return key
    else:
        # No colon — match if the key starts with the LLM key
        for key in stub_mapping:
            if key.upper().startswith(upper):
                return key
    return None


def _strict_perturb_stub_log(
    stub_log: list[tuple[str, list]],
    strategy_name: str,
    tc_count: int,
) -> list[tuple[str, list]]:
    """Apply strict-mode status perturbation to early stub records.

    COBOL mock consumption is sequential and can get trapped in equivalent
    status streams. In strict mode, perturb the first N records for non-baseline
    strategies to force alternate external status paths.
    """
    if not stub_log or strategy_name == "baseline":
        return stub_log

    profiles: list[tuple[str, int]] = [
        ("10", 10),
        ("12", 12),
        ("16", 16),
        ("96", 96),
        ("99", 99),
    ]
    profile_index = (tc_count + len(strategy_name)) % len(profiles)
    alpha_code, num_code = profiles[profile_index]

    limit = min(24, len(stub_log))
    out: list[tuple[str, list]] = []
    for idx, (op_key, entry) in enumerate(stub_log):
        if idx >= limit or not isinstance(entry, list):
            out.append((op_key, entry))
            continue

        new_entry = []
        for pair in entry:
            if isinstance(pair, (list, tuple)) and len(pair) == 2:
                var, val = pair
                if isinstance(val, (int, float)):
                    new_entry.append((var, num_code))
                else:
                    new_entry.append((var, alpha_code))
            else:
                new_entry.append(pair)
        out.append((op_key, new_entry))

    return out


# ---------------------------------------------------------------------------
# Standalone execute-and-save
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Uncovered-branch diagnostic report helper
# ---------------------------------------------------------------------------

# Minimum wall-clock interval between two incremental report writes.
# Set low enough that round-boundary writes during a slow run (~30s/round)
# always flush, but high enough that a fast-looping strict run doesn't
# hammer the disk on every iteration.
_UNCOVERED_REPORT_MIN_INTERVAL_SEC = 5.0


def _resolve_uncovered_report_stem(ctx: StrategyContext) -> Path | None:
    """Return the path stem the uncovered-branch report should be written to.

    Priority:
      1. ``ctx.uncovered_report_path`` (set by the caller/CLI).
      2. ``SPECTER_UNCOVERED_REPORT`` env var.
      3. ``ctx.store_path`` — default to writing next to the test store.

    Returns ``None`` when any of the configured sources explicitly
    disable the reporter (``"off"/"false"/"0"/"none"``) or when no
    store path is available at all.
    """
    raw = getattr(ctx, "uncovered_report_path", None)
    if raw is None:
        raw = os.environ.get("SPECTER_UNCOVERED_REPORT")
    if raw is None:
        store = getattr(ctx, "store_path", None)
        return Path(store) if store else None
    if str(raw).strip().lower() in ("", "off", "false", "0", "none"):
        return None
    return Path(raw)


def _emit_uncovered_report(
    ctx: StrategyContext,
    cov: CoverageState,
    report: CobolCoverageReport,
    *,
    reason: str,
) -> None:
    """Write the uncovered-branch diagnostic report to disk.

    Called both from within the round loop (as an incremental
    snapshot so a canceled run still has a report on disk) and
    from the loop's finalize block (to capture the terminal state).
    Writes throttled by ``_UNCOVERED_REPORT_MIN_INTERVAL_SEC`` —
    the ``"final"`` reason is always honoured immediately and
    bypasses the throttle.

    Defensive: any internal failure is logged at WARNING and the
    main coverage loop continues unaffected.
    """
    try:
        from .uncovered_report import generate_uncovered_report

        report_stem = _resolve_uncovered_report_stem(ctx)
        if report_stem is None:
            return

        # Throttle incremental writes so a fast strict run doesn't
        # rewrite the files on every iteration. The final call
        # always writes.
        if reason != "final":
            last_ts = getattr(ctx, "_uncovered_last_write_ts", 0.0)
            now = time.time()
            if now - last_ts < _UNCOVERED_REPORT_MIN_INTERVAL_SEC:
                return
            ctx._uncovered_last_write_ts = now

        mock_src = None
        cobol_ctx = getattr(ctx, "context", None)
        if cobol_ctx is not None:
            candidate = getattr(cobol_ctx, "instrumented_source_path", None)
            if candidate:
                mock_src = Path(candidate)

        program_id = getattr(
            getattr(ctx, "program", None), "program_id", "",
        ) or "UNKNOWN"

        generate_uncovered_report(
            ctx=ctx,
            cov=cov,
            report=report,
            program_id=program_id,
            mock_source_path=mock_src,
            out_path_stem=report_stem,
            format="both",
        )
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "Uncovered-branch report skipped (reason=%s): %s",
            reason, exc,
        )


# ---------------------------------------------------------------------------
# Concolic escalation (T2-B)
# ---------------------------------------------------------------------------

# Minimum number of consecutive stale rounds before the concolic solver is
# invoked. Matches the monte_carlo path's trigger semantics: we don't want
# to spend Z3 time while random search is still making progress, but as
# soon as a plateau is detected we give the solver a chance to break it.
_CONCOLIC_STALE_TRIGGER = 3

# Hard cap on the total number of concolic invocations per coverage run.
_CONCOLIC_MAX_TRIGGERS = 3

# Branch agent (inner LLM loop for stubborn branches) — config.
_BRANCH_AGENT_STALE_TRIGGER = 3     # stale rounds before agent kicks in
_BRANCH_AGENT_MAX_INVOCATIONS = 3   # max times the agent runs per coverage run
_BRANCH_AGENT_MAX_BRANCHES = 3      # branches to investigate per invocation
_BRANCH_AGENT_DEFAULT_ITERATIONS = 3 # LLM turns per branch


def _cobol_branches_to_int_set(branches_hit: set[str]) -> set[int]:
    """Convert ``{"42:T", "42:F", ...}`` to ``{42, -42, ...}``.

    The COBOL coverage loop tracks branches as ``"<bid>:T"`` /
    ``"<bid>:F"`` string keys, while ``solve_for_uncovered_branches``
    expects a ``set[int]`` with positive IDs for the T direction and
    negative IDs for the F direction. We ignore anything that doesn't
    parse cleanly (e.g. EVALUATE WHEN-arm markers like ``"42:W1"``) so
    the solver doesn't crash on unexpected shapes.
    """
    out: set[int] = set()
    for key in branches_hit:
        if ":" not in key:
            continue
        bid_str, direction = key.split(":", 1)
        try:
            bid = int(bid_str)
        except ValueError:
            continue
        d = direction.upper()
        if d.startswith("T"):
            out.add(bid)
        elif d.startswith("F"):
            out.add(-bid)
    return out


@dataclass
class _CorpusEntryShim:
    """Lightweight corpus-entry wrapper used by the concolic escalation.

    ``solve_for_uncovered_branches`` reads ``.coverage`` (set of
    paragraph names that a corpus entry reaches) and ``.input_state``
    (dict) from each entry to pick the best observed state for each
    target branch. The COBOL loop stores test cases as plain dicts, so
    we wrap them in this minimal shim on demand.
    """

    input_state: dict
    coverage: frozenset


def _run_concolic_escalation(
    ctx: StrategyContext,
    cov: CoverageState,
    report: CobolCoverageReport,
    tc_count: int,
    trigger_idx: int,
) -> tuple[int, int]:
    """Invoke the Z3 solver against the current uncovered branches.

    Returns ``(n_executed, n_new)`` — the number of concolic solutions
    that were passed through ``_execute_and_save`` and the number that
    actually produced new coverage. Callers use the ``n_new`` signal to
    decide whether to reset ``stale_rounds``.

    Never raises: any failure (z3 missing, solver timeout, empty
    solution set, executor error) is logged and the escalation exits
    cleanly so the outer loop can continue.
    """
    try:
        from .concolic import solve_for_uncovered_branches
    except ImportError:
        log.debug("concolic engine not available")
        return (0, 0)

    branch_meta = getattr(ctx, "branch_meta", None)
    if not branch_meta:
        return (0, 0)

    # Normalise branch_meta keys to int so the solver's
    # ``sorted(branch_meta.keys())`` + ``abs_id`` arithmetic works.
    # The COBOL executor sometimes hands back string keys like "42"
    # which would crash the negate arithmetic (``-"42"``) downstream.
    normalised_meta: dict[int, dict] = {}
    for k, v in branch_meta.items():
        try:
            normalised_meta[int(k)] = v
        except (TypeError, ValueError):
            continue
    if not normalised_meta:
        log.debug("Concolic: no integer-keyed branches in branch_meta (type=%s)",
                  type(next(iter(branch_meta))).__name__ if branch_meta else "empty")
        return (0, 0)
    branch_meta = normalised_meta

    covered_int = _cobol_branches_to_int_set(cov.branches_hit)

    # Build observed states and corpus-entry shims from the last 10
    # saved test cases. The solver uses these to pick a realistic
    # starting point per target branch.
    recent = cov.test_cases[-10:] if cov.test_cases else []
    observed_states = [tc.get("input_state", {}) for tc in recent]
    corpus_entries: list[_CorpusEntryShim] = []
    for tc in cov.test_cases:
        paras = tc.get("paragraphs_covered") or tc.get("paragraphs_hit") or []
        corpus_entries.append(
            _CorpusEntryShim(
                input_state=tc.get("input_state", {}),
                coverage=frozenset(paras),
            )
        )

    try:
        solutions = solve_for_uncovered_branches(
            branch_meta,
            covered_int,
            ctx.var_report,
            observed_states,
            stub_mapping=ctx.stub_mapping,
            corpus_entries=corpus_entries,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("solve_for_uncovered_branches raised: %s", exc)
        return (0, 0)

    if not solutions:
        log.info("Concolic escalation #%d: no solutions found", trigger_idx)
        return (0, 0)

    log.info(
        "Concolic escalation #%d: %d solutions returned, executing ...",
        trigger_idx, len(solutions),
    )

    paras_before = len(cov.paragraphs_hit)
    branches_before = len(cov.branches_hit)

    executed = 0
    for sol in solutions:
        input_state = dict(sol.assignments) if sol.assignments else {}
        # solve_for_uncovered_branches may attach stub_outcomes to the
        # solution when the target branch is gated on a stub-returned
        # variable.
        stub_outcomes = sol.stub_outcomes if sol.stub_outcomes else None
        target = f"concolic:{sol.branch_id}"
        try:
            _, tc_count = _execute_and_save(
                ctx, cov, input_state, stub_outcomes, None,
                "concolic", target, report, tc_count,
            )
            executed += 1
        except Exception as exc:  # noqa: BLE001
            log.debug("Concolic solution %s failed to execute: %s",
                      sol.branch_id, exc)
            continue

    n_new_paras = len(cov.paragraphs_hit) - paras_before
    n_new_branches = len(cov.branches_hit) - branches_before
    n_new = n_new_paras + n_new_branches
    return (executed, n_new)


def _execute_and_save(
    ctx: StrategyContext,
    cov: CoverageState,
    input_state: dict,
    stub_outcomes: dict | None,
    stub_defaults: dict | None,
    strategy_name: str,
    target: str,
    report: CobolCoverageReport,
    tc_count: int,
) -> tuple[bool, int]:
    """Execute a test case and save if new coverage is found.

    Supports both COBOL (ctx.context is set) and Python-only (ctx.context is
    None) execution modes.  Returns (saved, updated_tc_count).
    """
    # Parse direct paragraph invocation from target string
    direct_para = None
    if target.startswith("direct:"):
        direct_para = target[7:].split("|", 1)[0]
    canonical_target = _canonical_target_key(target)

    # Memory-guided seed reuse: prefill candidate input with the strongest
    # prior winner for this canonical target, while preserving current overrides.
    memory_seed = _best_memory_seed_input(getattr(ctx, "memory_state", None), canonical_target)
    if memory_seed:
        merged_input = dict(memory_seed)
        merged_input.update(input_state)
        input_state = merged_input

    cobol_mode = ctx.context is not None

    if ctx.context is not None:
        if direct_para:
            # Direct paragraph invocation: use Python for speed, COBOL can't
            # invoke individual paragraphs.  Python execution still gives
            # valid branch coverage from the generated module.
            result = _python_execute(
                ctx.module, input_state, stub_outcomes, stub_defaults,
                paragraph=direct_para,
            )
            stub_log = []

            # Replay through COBOL if Python found new py: branches.
            # Project the direct-execution state down to entry-safe injected
            # variables so COBOL replays are not polluted by Python locals.
            py_new = {b for b in result.branches_hit if b.startswith("py:")} - cov.branches_hit
            if py_new:
                seed_state = _best_memory_seed_input(getattr(ctx, "memory_state", None), canonical_target)
                if not seed_state:
                    seed_state = _best_cobol_seed_input(cov)
                replay_states: list[dict[str, object]] = []
                seeded_state = _project_cobol_replay_input(
                    input_state,
                    ctx.context.injectable_vars,
                    seed_state=seed_state,
                )
                raw_projected_state = _project_cobol_replay_input(
                    input_state,
                    ctx.context.injectable_vars,
                )
                if seeded_state:
                    replay_states.append(seeded_state)
                if raw_projected_state and raw_projected_state != seeded_state:
                    replay_states.append(raw_projected_state)

                replay_stub_variants: list[tuple[dict | None, dict | None]] = [
                    (stub_outcomes, stub_defaults),
                ]
                if stub_outcomes != ctx.success_stubs or stub_defaults != ctx.success_defaults:
                    replay_stub_variants.append((ctx.success_stubs, ctx.success_defaults))

                exec_timeout = int(getattr(ctx, "execution_timeout", 120))
                remaining_timeout = int(getattr(ctx, "_remaining_timeout", exec_timeout))
                effective_timeout = max(1, min(exec_timeout, remaining_timeout))

                for replay_state in replay_states[:2]:
                    for replay_stubs, replay_defaults in replay_stub_variants[:2]:
                        cobol_stub_log = _python_pre_run(
                            ctx.module,
                            replay_state,
                            replay_stubs,
                            replay_defaults,
                        )
                        cobol_result = run_test_case(
                            ctx.context,
                            replay_state,
                            cobol_stub_log,
                            timeout=effective_timeout,
                        )
                        if cobol_result.error:
                            continue
                        result.paragraphs_hit = list(dict.fromkeys(
                            result.paragraphs_hit + cobol_result.paragraphs_hit
                        ))
                        result.branches_hit.update(cobol_result.branches_hit)
                        if cobol_result.branches_hit:
                            break
                    if any(not b.startswith("py:") for b in result.branches_hit):
                        break
        else:
            # Full program: pre-run Python for stub ordering, then COBOL
            strict_mode = bool(getattr(ctx, "strict_branch_coverage", False))
            strict_fast = False
            if strict_fast and stub_outcomes:
                # Strict-mode fast path keeps execution moving by avoiding
                # expensive pre-run ordering when validating branch reachability.
                stub_log = []
                for op_key, entries in stub_outcomes.items():
                    if not entries:
                        continue
                    chosen = entries[0]
                    default_entry = None
                    if stub_defaults and op_key in stub_defaults:
                        default_entry = stub_defaults.get(op_key)
                    if default_entry is not None:
                        for candidate in entries:
                            if candidate != default_entry:
                                chosen = candidate
                                break
                    stub_log.append((op_key, chosen))
                    if len(stub_log) >= 30:
                        break
            else:
                stub_log = _python_pre_run(ctx.module, input_state, stub_outcomes, stub_defaults)

            if strict_mode:
                stub_log = _strict_perturb_stub_log(stub_log, strategy_name, tc_count)

            exec_timeout = int(getattr(ctx, "execution_timeout", 120))
            remaining_timeout = int(getattr(ctx, "_remaining_timeout", exec_timeout))
            effective_timeout = max(1, min(exec_timeout, remaining_timeout))
            if strict_fast:
                effective_timeout = min(effective_timeout, 120)

            result = run_test_case(ctx.context, input_state, stub_log, timeout=effective_timeout)
            log.info(
                "  [%s] rc=%s time=%.0fms stubops=%d paras=%d branches=%d%s",
                strategy_name,
                result.return_code,
                result.execution_time_ms,
                len(stub_log),
                len(result.paragraphs_hit),
                len(result.branches_hit),
                f" error={result.error}" if result.error else "",
            )
            # Debug: show concrete paragraph/branch details and input fields
            if log.isEnabledFor(logging.DEBUG):
                paras_list = sorted(result.paragraphs_hit)[:5]  # Show first 5
                branches_list = sorted(str(b) for b in result.branches_hit)[:5]
                log.debug(
                    "    paragraphs hit: %s%s",
                    ", ".join(paras_list),
                    " ..." if len(result.paragraphs_hit) > 5 else "",
                )
                if branches_list:
                    log.debug(
                        "    branches hit: %s%s",
                        ", ".join(branches_list),
                        " ..." if len(result.branches_hit) > 5 else "",
                    )
                # Show input fields with non-default/non-empty values
                nontrivial_inputs = {
                    k: v for k, v in input_state.items()
                    if not k.startswith("_") and v and v not in ("", "0", 0, False)
                }
                if nontrivial_inputs:
                    sample_fields = sorted(nontrivial_inputs.items())[:8]
                    log.debug(
                        "    input fields: %s%s",
                        ", ".join(f"{k}={repr(v)}" for k, v in sample_fields),
                        " ..." if len(nontrivial_inputs) > 8 else "",
                    )
    else:
        # Python-only execution path
        result = _python_execute(
            ctx.module, input_state, stub_outcomes, stub_defaults,
            paragraph=direct_para,
        )
        stub_log = []

    if result.error:
        memory_store = getattr(ctx, "memory_store", None)
        memory_state = getattr(ctx, "memory_state", None)
        if memory_store is not None and memory_state is not None:
            try:
                memory_store.upsert_target_status(
                    memory_state,
                    canonical_target,
                    attempts_delta=1,
                    solved=False,
                    last_error=result.error,
                    nearest_paragraph_hits=len(result.paragraphs_hit),
                    nearest_branch_hits=len(result.branches_hit),
                )
            except Exception as exc:
                log.debug("Memory target update failed: %s", exc)
        if "timed out" in result.error.lower():
            cov.consecutive_timeouts += 1
        else:
            cov.consecutive_timeouts = 0
        return False, tc_count

    cov.consecutive_timeouts = 0

    # Normalize paragraph coverage to AST-known labels. Keep runtime-only labels
    # in a side channel for diagnostics/reporting.
    result_paras = set(result.paragraphs_hit)
    if cov.all_paragraphs:
        result_ast_paras = result_paras & cov.all_paragraphs
        result_runtime_only = result_paras - cov.all_paragraphs
    else:
        result_ast_paras = result_paras
        result_runtime_only = set()

    # Check for new coverage
    new_paras = result_ast_paras - cov.paragraphs_hit
    new_runtime_only = result_runtime_only - cov.runtime_only_paragraphs
    new_branches = result.branches_hit - cov.branches_hit
    counted_new_branches = _counted_branches_for_mode(new_branches, cobol_mode)

    if new_paras or new_branches or new_runtime_only:
        log.debug(
            "    >> NEW COVERAGE: paras=%s branches=%s",
            sorted(new_paras)[:5] if new_paras else "none",
            sorted(str(b) for b in new_branches)[:5] if new_branches else "none",
        )

    # Track repeated execution signatures (same paragraph+branch outcome)
    # to short-circuit strict runs that are stuck in equivalent paths.
    signature = (frozenset(result_ast_paras), frozenset(result.branches_hit))
    if cov.last_result_signature == signature:
        cov.repeat_signature_count += 1
    else:
        cov.last_result_signature = signature
        cov.repeat_signature_count = 0

    # Always save first few test cases; after that, only if new coverage
    force_save = tc_count < 5
    if not new_paras and not new_branches and not new_runtime_only and not force_save:
        memory_store = getattr(ctx, "memory_store", None)
        memory_state = getattr(ctx, "memory_state", None)
        if memory_store is not None and memory_state is not None:
            try:
                memory_store.upsert_target_status(
                    memory_state,
                    canonical_target,
                    attempts_delta=1,
                    solved=False,
                    nearest_paragraph_hits=len(result.paragraphs_hit),
                    nearest_branch_hits=len(result.branches_hit),
                )
            except Exception as exc:
                log.debug("Memory target update failed: %s", exc)
        return False, tc_count

    # Update coverage
    cov.paragraphs_hit.update(result_ast_paras)
    cov.runtime_only_paragraphs.update(result_runtime_only)
    cov.branches_hit.update(result.branches_hit)

    # Harvest successful values into domain condition_literals so that
    # subsequent strategies reuse values that produced new coverage.
    if new_branches and ctx.domains:
        for var, val in input_state.items():
            if isinstance(var, str) and not var.startswith("_"):
                dom = ctx.domains.get(var)
                if dom and val not in dom.condition_literals:
                    dom.condition_literals.append(val)
        # Also harvest stub outcome values that produced new branches
        if stub_outcomes:
            for op_key, entries in stub_outcomes.items():
                for entry in entries[:1]:  # first entry is what actually executed
                    if isinstance(entry, list):
                        for var, val in entry:
                            dom = ctx.domains.get(var)
                            if dom and val not in dom.condition_literals:
                                dom.condition_literals.append(val)

    # Save
    tc_id = _compute_tc_id(input_state, stub_log)
    _save_test_case(
        ctx.store_path, tc_id, input_state, stub_log, result,
        strategy_name, target,
    )
    tc_count += 1
    report.layer_stats[strategy_name] = report.layer_stats.get(strategy_name, 0) + 1

    # Keep in-memory test_cases in sync so mid-run strategies can use them
    cov.test_cases.append({
        "id": tc_id,
        "input_state": {k: v for k, v in input_state.items() if not str(k).startswith("_")},
        "stub_outcomes": [[op, entries] for op, entries in stub_log],
        "paragraphs_hit": result.paragraphs_hit,
        "branches_hit": sorted(result.branches_hit),
        "layer": strategy_name,
        "target": target,
    })

    memory_store = getattr(ctx, "memory_store", None)
    memory_state = getattr(ctx, "memory_state", None)
    if memory_store is not None and memory_state is not None:
        try:
            memory_store.upsert_target_status(
                memory_state,
                canonical_target,
                attempts_delta=1,
                solved=bool(new_paras or counted_new_branches),
                nearest_paragraph_hits=len(result.paragraphs_hit),
                nearest_branch_hits=len(result.branches_hit),
                last_error="",
            )
            memory_store.append_success(
                memory_state,
                SuccessState(
                    target=canonical_target,
                    input_state={k: v for k, v in input_state.items() if not str(k).startswith("_")},
                    stub_outcomes=[[op, entries] for op, entries in stub_log],
                    paragraphs_hit=list(result.paragraphs_hit),
                    branches_hit=sorted(result.branches_hit),
                    timestamp=time.time(),
                ),
            )
        except Exception as exc:
            log.debug("Memory success update failed: %s", exc)

    if new_paras:
        log.info("  [%s] +%d paras -> %d/%d: %s",
                 strategy_name, len(new_paras), len(cov.paragraphs_hit),
                 cov.total_paragraphs, sorted(new_paras))
    if counted_new_branches:
        counted_total = len(_counted_branches_for_mode(cov.branches_hit, cobol_mode))
        log.info("  [%s] +%d branches -> %d/%d",
                 strategy_name, len(counted_new_branches), counted_total,
                 cov.total_branches)
    if new_runtime_only:
        log.info("  [%s] +%d runtime-only paras (not in AST)",
                 strategy_name, len(new_runtime_only))
    return True, tc_count


def _sync_memory_runtime_state(ctx: StrategyContext, cov: CoverageState) -> None:
    """Mirror round-level strategy and API stats into persistent memory state."""
    memory_store = getattr(ctx, "memory_store", None)
    memory_state = getattr(ctx, "memory_state", None)
    if memory_store is None or memory_state is None:
        return

    try:
        for name, stats in cov.strategy_yields.items():
            memory_store.upsert_strategy_stats(
                memory_state,
                name,
                PersistedStrategyStats(
                    total_cases=stats.total_cases,
                    total_new_coverage=stats.total_new_coverage,
                    rounds=stats.rounds,
                    last_yield_round=stats.last_yield_round,
                    last_updated=time.time(),
                ),
            )

        jit = getattr(ctx, "jit_inference", None)
        if jit is not None:
            jit_hits = int(getattr(jit, "cache_hits", 0))
            jit_misses = int(getattr(jit, "cache_misses", 0))
            memory_store.update_api_ledger(
                memory_state,
                APIBudgetLedger(
                    jit_requests=jit_hits + jit_misses,
                    jit_cache_hits=jit_hits,
                    jit_cache_misses=jit_misses,
                    last_updated=time.time(),
                ),
            )
            log.debug(
                "Memory sync: jit_requests=%d hit=%d miss=%d",
                jit_hits + jit_misses,
                jit_hits,
                jit_misses,
            )
    except Exception as exc:
        log.debug("Memory runtime sync failed: %s", exc)


def _jit_status_suffix(ctx: StrategyContext, enabled: bool = True) -> str:
    """Build a compact JIT status suffix for progress/round logs."""
    if not enabled:
        return ""
    jit = getattr(ctx, "jit_inference", None)
    if jit is None:
        return ""

    snapshot = None
    if hasattr(jit, "snapshot_metrics"):
        try:
            snapshot = jit.snapshot_metrics()
        except Exception:
            snapshot = None

    if isinstance(snapshot, dict):
        reqs = int(snapshot.get("requests", 0) or 0)
        if reqs <= 0:
            return ""
        return (
            " [JIT reqs={reqs} hit={hit:.1f}% skip_u={skip_u} skip_scope={skip_scope} ok={ok} fail={fail} avg={avg:.0f}ms]"
        ).format(
            reqs=reqs,
            hit=float(snapshot.get("cache_hit_pct", 0.0) or 0.0),
            skip_u=int(snapshot.get("skipped_untargeted", 0) or 0),
            skip_scope=int(snapshot.get("skipped_out_of_scope", 0) or 0),
            ok=int(snapshot.get("llm_successes", 0) or 0),
            fail=int(snapshot.get("llm_failures", 0) or 0),
            avg=float(snapshot.get("avg_latency_ms", 0.0) or 0.0),
        )

    # Backward-compatible fallback for older jit implementations.
    hits = int(getattr(jit, "cache_hits", 0) or 0)
    misses = int(getattr(jit, "cache_misses", 0) or 0)
    reqs = hits + misses
    if reqs <= 0:
        return ""
    hit_pct = 100.0 * hits / reqs if reqs else 0.0
    return f" [JIT reqs={reqs} hit={hit_pct:.1f}%]"


# ---------------------------------------------------------------------------
# Agentic coverage loop
# ---------------------------------------------------------------------------

def run_cobol_coverage(
    ast_file: str | Path,
    cobol_source: str | Path,
    copybook_dirs: list[str | Path] | None = None,
    budget: int = 5000,
    timeout: int = 1800,
    execution_timeout: int = 900,
    store_path: str | Path | None = None,
    seed: int = 42,
    work_dir: str | Path | None = None,
    llm_provider=None,
    llm_model: str | None = None,
    max_rounds: int = 0,
    batch_size: int = 200,
    strict_branch_coverage: bool = False,
    coverage_config=None,
) -> CobolCoverageReport:
    """Run coverage-guided test generation against real COBOL.

    Args:
        ast_file: Path to JSON AST file.
        cobol_source: Path to COBOL source (.cbl).
        copybook_dirs: Directories containing copybooks.
        budget: Maximum test cases to generate.
        timeout: Maximum seconds.
        store_path: Path for JSONL test store output.
        seed: Random seed for determinism.
        work_dir: Directory for build artifacts.

    Returns:
        CobolCoverageReport with coverage statistics.
    """
    from .ast_parser import parse_ast
    from .code_generator import generate_code
    from .monte_carlo import _load_module

    setup_start = time.time()
    rng = random.Random(seed)
    copybook_dirs = list(copybook_dirs or [])

    # --- INITIALIZE ---
    log.info("Parsing AST: %s", ast_file)
    program = parse_ast(ast_file)
    var_report = extract_variables(program)
    call_graph = build_static_call_graph(program)
    gating_conds = extract_gating_conditions(program, call_graph)
    stub_mapping = extract_stub_status_mapping(program, var_report)
    paragraph_comments: dict[str, list[str]] = {}
    source_path = Path(cobol_source)
    if source_path.exists():
        try:
            paragraph_comments = extract_paragraph_comments(
                program,
                source_path.read_text(errors="replace").splitlines(),
            )
        except Exception as exc:
            log.debug("Failed to extract paragraph comments: %s", exc)
    seq_gates = extract_sequential_gates(program)
    if seq_gates:
        gating_conds = augment_gating_with_sequential_gates(
            gating_conds, seq_gates, call_graph,
        )

    # Build domain model
    log.info("Building variable domain model ...")
    copybook_records = load_copybooks(copybook_dirs) if copybook_dirs else []
    domains = build_variable_domains(
        var_report, copybook_records, stub_mapping,
        cobol_source=cobol_source,
    )
    _enrich_domains_with_boolean_hints(domains, program)
    log.info("Domain model: %d variables (%d from copybooks)",
             len(domains), sum(1 for d in domains.values() if d.data_type != "unknown"))

    # Generate Python module for pre-runs
    log.info("Generating Python module for pre-runs ...")
    import tempfile
    code = generate_code(program, var_report, instrument=True,
                         copybook_records=copybook_records,
                         cobol_source=str(cobol_source))
    tmpdir = Path(tempfile.mkdtemp(prefix="specter_cov_"))
    py_path = tmpdir / f"{program.program_id}.py"
    py_path.write_text(code)
    module = _load_module(py_path)

    # Injectable variables for the init dispatch.
    #
    # Historical behaviour restricted injection to variables classified as
    # ``input``, ``status`` or ``flag``. That excluded *internal* variables
    # like ``APPL-RESULT`` on CBACT02C/03C/CBCUS01C even though they carry
    # 88-level children that gate real branches (``APPL-AOK``/``APPL-EOF``).
    # Strategy Phase 3 (``BaselineStrategy``) can now emit cases that set
    # those 88-level activating values directly in ``input_state``, but
    # without a matching WHEN arm in the generated ``SPECTER-READ-INIT-VARS``
    # paragraph the runtime silently drops the INIT record.
    #
    # Relax the filter: any variable that carries enough signal to drive
    # targeted injection (either ``condition_literals`` or
    # ``valid_88_values``) is injectable regardless of classification, as
    # long as it is not a stub-return variable and not an EIB register.
    _EIB_NAMES = {"EIBCALEN", "EIBAID", "EIBTRNID", "EIBTIME", "EIBDATE",
                  "EIBTASKN", "EIBTRMID", "EIBCPOSN", "EIBFN", "EIBRCODE",
                  "EIBDS", "EIBREQID", "EIBRSRCE", "EIBRESP", "EIBRESP2"}

    def _is_safe_to_inject(name: str, dom) -> bool:
        """Return True if injecting a value at startup is safe.

        Excludes variables that would crash the binary when the
        generated ``SPECTER-READ-INIT-VARS`` dispatcher attempts
        ``MOVE MOCK-ALPHA-STATUS TO <var>``:

          * FILLER — unnamed padding; COBOL doesn't allow MOVE to FILLER.
          * Null-sentinel 88-level flags — variables whose **only**
            88-level children are LOW-VALUES / empty-string guards
            (e.g. ``88 NULL-UCB VALUES LOW-VALUES`` under ``UCB-ADDR``
            inside a BASED TIOT structure on CBSTM03A). Moving a
            string into these pointer-addressed fields causes a null-
            pointer dereference SIGSEGV at runtime.
          * EIB registers — CICS control block fields.
          * Stub-return variables — their values come from stubs, not
            from startup injection.
        """
        upper = name.upper()
        if upper == "FILLER" or upper.startswith("FILLER-"):
            return False
        if upper in _EIB_NAMES:
            return False
        if dom.set_by_stub:
            return False
        if dom.classification == "internal-no-inject":
            return False
        # Must carry actionable signal.
        if not dom.condition_literals and not dom.valid_88_values:
            return False
        # Null-sentinel check: if ALL 88-level values resolve to
        # empty-string / LOW-VALUES, the variable is almost certainly
        # a pointer-null guard (e.g. 88 END-OF-TIOT VALUE LOW-VALUES)
        # and injecting into it would dereference a null address.
        if dom.valid_88_values and not dom.condition_literals:
            all_null = all(
                v == "" or v == 0 or (isinstance(v, str) and not v.strip())
                for v in dom.valid_88_values.values()
            )
            if all_null:
                return False
        return True

    injectable = [
        name for name, dom in domains.items()
        if _is_safe_to_inject(name, dom)
    ]
    log.info("Injectable variables: %d", len(injectable))

    # Prepare COBOL context (instrument + compile)
    log.info("Instrumenting and compiling COBOL ...")
    replay_injectable = injectable[:40]
    payload_variables, payload_candidates = _build_transcript_payload_candidates(
        domains,
        stub_mapping,
        replay_injectable,
    )
    try:
        # Keep a bounded entry-input dispatch so COBOL can replay promising
        # Python-discovered states without injecting every internal variable.
        context = prepare_context(
            cobol_source, copybook_dirs,
            enable_branch_tracing=True,
            work_dir=work_dir,
            injectable_vars=replay_injectable,
            payload_variables=payload_variables,
            coverage_mode=True,
            allow_hardening_fallback=not strict_branch_coverage,
            llm_provider=llm_provider,
            llm_model=llm_model,
        )
    except RuntimeError as e:
        if replay_injectable:
            log.warning(
                "Compile with %d injectable vars failed, retrying without injection: %s",
                len(replay_injectable),
                e,
            )
            context = prepare_context(
                cobol_source, copybook_dirs,
                enable_branch_tracing=True,
                work_dir=work_dir,
                injectable_vars=[],
                payload_variables=payload_variables,
                coverage_mode=True,
                allow_hardening_fallback=not strict_branch_coverage,
                llm_provider=llm_provider,
                llm_model=llm_model,
            )
        else:
            log.error("COBOL compilation failed: %s", e)
            raise

    if strict_branch_coverage and context.total_branches == 0:
        msg = (
            "Strict branch coverage requested, but no COBOL branch probes were "
            "generated (0/0)."
        )
        if context.hardened_mode:
            msg += (
                " Hardening fallback is active (SPECTER-HARDENED-ENTRY), which "
                "typically removes executable IF/EVALUATE constructs."
            )
        raise RuntimeError(msg)

    # Setup store
    if store_path is None:
        store_path = tmpdir / f"{program.program_id}_cobol_testset.jsonl"
    store_path = Path(store_path)
    memory_store = MemoryStore(derive_memory_dir(store_path))
    memory_state = memory_store.load_state()
    memory_state.meta.setdefault("program_id", program.program_id)
    memory_state.meta.setdefault("mode", "cobol")
    jit_inference = None
    if llm_provider is not None:
        jit_inference = JITValueInferenceService(
            llm_provider,
            llm_model,
            cache_path=store_path.with_name(store_path.stem + "_jit_profiles.json"),
        )

    # Load existing coverage
    existing_tcs, existing_paras, existing_branches = load_existing_coverage(store_path)

    # Expand stub mapping with 88-level siblings
    siblings_88 = _build_siblings_88(copybook_records, cobol_source=cobol_source)
    flag_88_added = _expand_stub_mapping(stub_mapping, siblings_88)
    if flag_88_added:
        log.info("Expanded stub mapping with %d 88-level siblings: %s",
                 len(flag_88_added), sorted(flag_88_added))

    # Build success stubs
    success_stubs, success_defaults = _build_success_stubs(
        stub_mapping, domains,
        flag_88_added=flag_88_added, siblings_88=siblings_88,
    )

    all_paras = {p.name for p in program.paragraphs}
    existing_ast_paras = existing_paras & all_paras
    existing_runtime_only = existing_paras - all_paras

    # Coverage state
    # Subtract infrastructure branches (specter's own SPECTER-* paragraphs,
    # FILE-CONTROL) from the total so the reported coverage % reflects
    # real business logic, not instrumentation scaffolding. The raw
    # context.total_branches counts every @@B: probe including those
    # inside SPECTER-READ-INIT-VARS, SPECTER-NEXT-MOCK-RECORD, etc.
    infra_keys = _infrastructure_branch_keys(context.branch_meta)
    adjusted_total = max(0, context.total_branches - len(infra_keys))
    log.info("Branch total: %d raw, %d infrastructure excluded, %d counted",
             context.total_branches, len(infra_keys), adjusted_total)

    cov = CoverageState(
        paragraphs_hit=existing_ast_paras,
        runtime_only_paragraphs=existing_runtime_only,
        branches_hit=existing_branches,
        total_paragraphs=len(all_paras),
        total_branches=adjusted_total,
        test_cases=existing_tcs,
        all_paragraphs=all_paras,
        _stub_mapping=stub_mapping,
        _infra_keys=infra_keys,
    )
    report = CobolCoverageReport(
        total_test_cases=len(existing_tcs),
        paragraphs_total=len(all_paras),
        runtime_trace_total=context.total_paragraphs,
        runtime_only_paragraphs=len(existing_runtime_only),
        branches_total=adjusted_total,
    )

    if existing_tcs:
        log.info("Loaded %d existing TCs: %d AST paras, %d runtime-only paras, %d branches covered",
                 len(existing_tcs), len(existing_ast_paras), len(existing_runtime_only),
                 len(existing_branches))

    tc_count = len(existing_tcs)

    from .coverage_config import CoverageConfig, build_selector, build_strategies

    if coverage_config is None:
        coverage_config = CoverageConfig(default_batch_size=batch_size)

    jit_cfg = getattr(coverage_config, "jit_logging", None)
    scope_policy = str(getattr(jit_cfg, "jit_scope_policy", "target_gates_plus_slice") or "").strip().lower()
    if scope_policy not in {"all", "target_gates_only", "target_gates_plus_slice"}:
        scope_policy = "target_gates_plus_slice"
    include_gates = scope_policy in {"target_gates_only", "target_gates_plus_slice"}
    include_slice = scope_policy == "target_gates_plus_slice"
    target_variable_allowlists = {}
    if scope_policy != "all":
        target_variable_allowlists = _build_target_variable_allowlists(
            module,
            context.branch_meta,
            gating_conds,
            stub_mapping,
            include_gates=include_gates,
            include_slice=include_slice,
        )

    # --- BUILD STRATEGY CONTEXT ---
    ctx = StrategyContext(
        module=module,
        context=context,
        domains=domains,
        stub_mapping=stub_mapping,
        call_graph=call_graph,
        gating_conds=gating_conds,
        var_report=var_report,
        program=program,
        all_paragraphs=all_paras,
        success_stubs=success_stubs,
        success_defaults=success_defaults,
        rng=rng,
        store_path=store_path,
        branch_meta=context.branch_meta,
        cobol_source_path=Path(cobol_source),
        llm_provider=llm_provider,
        llm_model=llm_model,
        jit_inference=jit_inference,
        paragraph_comments=paragraph_comments,
        siblings_88=siblings_88,
        flag_88_added=flag_88_added,
        payload_candidates=payload_candidates,
        target_variable_allowlists=target_variable_allowlists,
        memory_store=memory_store,
        memory_state=memory_state,
    )
    setattr(ctx, "execution_timeout", max(1, int(execution_timeout)))
    setattr(ctx, "strict_branch_coverage", bool(strict_branch_coverage))

    # --- REGISTER STRATEGIES ---
    if jit_inference is not None and jit_cfg is not None:
        try:
            jit_inference.summary_interval_sec = max(1.0, float(jit_cfg.periodic_interval_ms) / 1000.0)
            jit_inference.summary_every_requests = max(1, int(jit_cfg.summary_every_requests))
            jit_inference.debug_min_interval_sec = max(0.0, float(jit_cfg.debug_min_interval_ms) / 1000.0)
            jit_inference.require_target_paragraph_context = bool(
                getattr(jit_cfg, "require_target_paragraph_context", True)
            )
            if not bool(jit_cfg.enabled):
                # Keep counters active for suffix reporting, silence periodic INFO summaries.
                jit_inference.summary_every_requests = 10**9
                jit_inference.summary_interval_sec = 10**9
        except Exception as exc:
            log.debug("Failed to apply JIT logging config: %s", exc)

    if coverage_config.strategies or coverage_config.rounds:
        strategies = build_strategies(coverage_config, llm_provider, llm_model)
    else:
        strategies: list[Strategy] = [
            BaselineStrategy(),
            DirectParagraphStrategy(),
            TranscriptSearchStrategy(),
            CorpusFuzzStrategy(),
            FaultInjectionStrategy(),
        ]

    if coverage_config.selector != "heuristic" or coverage_config.rounds:
        selector = build_selector(coverage_config, llm_provider, llm_model, var_report)
    else:
        selector = HeuristicSelector(default_batch_size=batch_size)

    loop_start_time = time.time()
    setup_elapsed = loop_start_time - setup_start
    if setup_elapsed > 0.5:
        log.info("Coverage setup complete in %.1fs; starting execution loop", setup_elapsed)

    return _run_agentic_loop(
        ctx, cov, report, strategies, selector,
        budget, timeout, loop_start_time, tc_count,
        max_rounds=max_rounds,
        config=coverage_config,
    )


# ---------------------------------------------------------------------------
# Shared agentic loop
# ---------------------------------------------------------------------------

def _run_agentic_loop(
    ctx: StrategyContext,
    cov: CoverageState,
    report: CobolCoverageReport,
    strategies: list[Strategy],
    selector,
    budget: int,
    timeout: int | float,
    start_time: float,
    tc_count: int,
    max_rounds: int = 0,
    config=None,
) -> CobolCoverageReport:
    """Run the strategy-based agentic coverage loop.

    Shared between run_cobol_coverage() and run_coverage().
    If *config* is a CoverageConfig with explicit rounds, those drive
    strategy selection instead of the selector.
    """
    from .coverage_config import CoverageConfig, TerminationConfig
    if config is None:
        config = CoverageConfig()
    term = config.termination if config.termination else TerminationConfig()

    # Build name→strategy index for explicit round mode
    strategies_by_name: dict[str, Strategy] = {s.name: s for s in strategies}
    explicit_rounds = config.rounds
    explicit_idx = 0
    round_num = 0
    strict_mode = bool(getattr(ctx, "strict_branch_coverage", False))
    # Concolic escalation state (T2-B). Counter is incremented each time
    # the plateau hook fires; _CONCOLIC_MAX_TRIGGERS caps the total Z3
    # invocations per run to keep wall-clock bounded.
    _concolic_triggers_used = 0
    # Branch agent invocation counter.
    _branch_agent_invocations_used = 0
    strict_case_cap = 3
    jit_logs_enabled = bool(getattr(config, "jit_logging", None).enabled) if getattr(config, "jit_logging", None) else True
    strict_strategy_order = [
        "baseline",
        "fault_injection",
        "branch_solver",
        "constraint_solver",
        "stub_walk",
        "guided_mutation",
        "llm_runtime",
        "monte_carlo",
    ]
    while tc_count < budget and (time.time() - start_time) < timeout:
        if max_rounds > 0 and round_num >= max_rounds:
            log.info("Max rounds (%d) reached", max_rounds)
            break
        strategy = None
        batch_size = 0

        # Mode 1: Explicit rounds from config
        if explicit_rounds:
            if explicit_idx >= len(explicit_rounds):
                explicit_idx = config.loop_from
            rc = explicit_rounds[explicit_idx]
            candidate = strategies_by_name.get(rc.strategy)
            if candidate is not None and candidate.should_run(cov, round_num):
                strategy = candidate
                batch_size = rc.batch_size or config.default_batch_size
            explicit_idx += 1

        # Mode 2: Strict mode round-robin
        if strategy is None and strict_mode:
            target_name = strict_strategy_order[round_num % len(strict_strategy_order)]
            for candidate in strategies:
                if candidate.name == target_name and candidate.should_run(cov, round_num):
                    strategy = candidate
                    break
            if strategy is not None:
                batch_size = min(50, int(getattr(selector, "default_batch_size", 50) or 50))

        # Mode 3: Selector-driven (default)
        if strategy is None:
            strategy, batch_size = selector.select(strategies, cov, round_num)

        preferred_target = _select_priority_branch_target(ctx, cov)
        setattr(ctx, "preferred_target_key", preferred_target)
        if preferred_target:
            status = getattr(getattr(ctx, "memory_state", None), "targets", {}).get(preferred_target)
            attempts = int(getattr(status, "attempts", 0) or 0) if status else 0
            log.debug("Round %d preferred branch target: %s (attempts=%d)", round_num, preferred_target, attempts)

        round_new = 0
        para_before = len(cov.paragraphs_hit)
        counted_before = len(_counted_branches_for_mode(cov.branches_hit, ctx.context is not None))
        round_cov_before = len(cov.paragraphs_hit) + counted_before

        log.info(
            "Round %d: %s (batch=%d)%s",
            round_num,
            strategy.name,
            batch_size,
            _jit_status_suffix(ctx, enabled=jit_logs_enabled),
        )

        cases_tried = 0
        for input_state, stubs, defaults, target in strategy.generate_cases(ctx, cov, batch_size):
            if tc_count >= budget or (time.time() - start_time) >= timeout:
                break

            remaining = max(1, int(timeout - (time.time() - start_time)))
            setattr(ctx, "_remaining_timeout", remaining)

            saved, tc_count = _execute_and_save(
                ctx, cov, input_state, stubs, defaults,
                strategy.name, target, report, tc_count,
            )
            if saved:
                round_new += 1

            cases_tried += 1

            if cases_tried % 200 == 0:
                counted_now = len(_counted_branches_for_mode(cov.branches_hit, ctx.context is not None))
                log.info("  %s progress: %d cases tried, %d/%d paras, %d/%d branches%s",
                         strategy.name, cases_tried,
                         len(cov.paragraphs_hit), cov.total_paragraphs,
                         counted_now, cov.total_branches,
                         _jit_status_suffix(ctx, enabled=jit_logs_enabled))

            if cov.consecutive_timeouts >= 5:
                log.info(
                    "Round %d: aborting %s after %d consecutive timeouts",
                    round_num,
                    strategy.name,
                    cov.consecutive_timeouts,
                )
                break

            if strict_mode and cov.repeat_signature_count >= 2:
                log.info(
                    "Round %d: aborting %s after repeated identical execution signatures",
                    round_num,
                    strategy.name,
                )
                break

            current_cap = strict_case_cap
            if strategy.name == "llm_runtime":
                current_cap = 2

            if strict_mode and cases_tried >= current_cap:
                log.info(
                    "Round %d: strict cap reached for %s (%d cases)",
                    round_num,
                    strategy.name,
                    current_cap,
                )
                break
            if round_new >= batch_size:
                break

        # Record yield for this strategy
        counted_after = len(_counted_branches_for_mode(cov.branches_hit, ctx.context is not None))
        para_after = len(cov.paragraphs_hit)
        round_cov_after = len(cov.paragraphs_hit) + counted_after
        para_delta = para_after - para_before
        branch_delta = counted_after - counted_before
        new_coverage = round_cov_after - round_cov_before

        sy = cov.strategy_yields.setdefault(strategy.name, StrategyYield())
        sy.total_cases += cases_tried
        sy.total_new_coverage += new_coverage
        sy.rounds += 1
        if new_coverage > 0:
            sy.last_yield_round = round_num

        log.info(
            "Round %d done: %s -> %d new TCs, +%d paras, +%d branches (+%d coverage) (%d/%d paras, %d/%d branches)%s",
            round_num,
            strategy.name,
            round_new,
            para_delta,
            branch_delta,
            new_coverage,
            len(cov.paragraphs_hit),
            cov.total_paragraphs,
            counted_after,
            cov.total_branches,
            _jit_status_suffix(ctx, enabled=jit_logs_enabled),
        )

        # Update adaptive LLM strategy tracking
        if hasattr(strategy, '_consecutive_dry'):
            if new_coverage > 0:
                strategy._consecutive_dry = 0
            else:
                strategy._consecutive_dry += 1

        # Staleness detection
        if new_coverage == 0:
            cov.stale_rounds += 1
        else:
            cov.stale_rounds = 0

        # Inner branch agent on plateau.
        #
        # When random + direct-paragraph + fault-injection search stalls,
        # run a focused, multi-turn LLM investigation for the top-K
        # stubbornest uncovered branches. Each investigation is up to
        # max_agent_iterations turns of: LLM proposes → execute → feed
        # result back → LLM proposes again. The agent journals what it
        # tried so the next run (or a human reviewer) can pick up where
        # it left off. Runs BEFORE concolic (which is cheaper but less
        # targeted) and BEFORE the plateau-stop decision.
        #
        # Bypassed by SPECTER_BRANCH_AGENT=0 or --no-branch-agent.
        if (
            cov.stale_rounds >= _BRANCH_AGENT_STALE_TRIGGER
            and _branch_agent_invocations_used < _BRANCH_AGENT_MAX_INVOCATIONS
        ):
            _branch_agent_invocations_used += 1
            try:
                from .branch_agent import run_branch_agent
                agent_max_iters = int(
                    os.environ.get("SPECTER_AGENT_ITERATIONS", _BRANCH_AGENT_DEFAULT_ITERATIONS),
                )
                # Recover the LLM provider/model from the JIT inference
                # service (which stored them at construction time). The
                # provider isn't passed into _run_agentic_loop directly.
                jit = getattr(ctx, "jit_inference", None)
                _agent_provider = getattr(jit, "provider", None) if jit else None
                _agent_model = getattr(jit, "model", None) if jit else None
                journals, n_solved, tc_count = run_branch_agent(
                    ctx=ctx,
                    cov=cov,
                    report=report,
                    tc_count=tc_count,
                    max_iterations=agent_max_iters,
                    max_branches=_BRANCH_AGENT_MAX_BRANCHES,
                    llm_provider=_agent_provider,
                    llm_model=_agent_model,
                    invocation_idx=_branch_agent_invocations_used,
                )
                if n_solved > 0:
                    cov.stale_rounds = 0
                # Attach journals to ctx so the uncovered report can include them.
                agent_journals = getattr(ctx, "_agent_journals", None) or []
                agent_journals.extend(journals)
                ctx._agent_journals = agent_journals
            except Exception as exc:  # noqa: BLE001
                log.warning("Branch agent failed: %s", exc)

        # Concolic escalation on plateau (T2-B).
        #
        # When random + direct-paragraph + fault-injection search stalls,
        # invoke Z3 against the remaining uncovered branches. The solver
        # lives in specter/concolic.py and is already used by the Python-
        # only monte_carlo path at three trigger points (:1326, :1839,
        # :1938) — we mirror that pattern here. Solutions are heuristic
        # because Z3 solves over the Python simulator's branch conditions,
        # not the compiled COBOL binary, so we feed each solution through
        # the normal _execute_and_save path and let coverage verification
        # confirm whether the branch actually fired.
        #
        # Bypassed by SPECTER_CONCOLIC=0. Capped at _CONCOLIC_MAX_TRIGGERS
        # invocations per coverage run to bound wall-clock Z3 time.
        if (
            cov.stale_rounds >= _CONCOLIC_STALE_TRIGGER
            and _concolic_triggers_used < _CONCOLIC_MAX_TRIGGERS
            and os.environ.get("SPECTER_CONCOLIC", "1").strip().lower() not in (
                "0", "false", "no", "off", "",
            )
        ):
            _concolic_triggers_used += 1
            try:
                n_solved, n_new = _run_concolic_escalation(
                    ctx, cov, report, tc_count,
                    trigger_idx=_concolic_triggers_used,
                )
                tc_count += n_solved
                if n_new > 0:
                    cov.stale_rounds = 0
                log.info(
                    "Concolic escalation #%d: %d solutions executed, %d added new coverage",
                    _concolic_triggers_used, n_solved, n_new,
                )
            except Exception as exc:  # noqa: BLE001 - never crash the loop
                log.warning("Concolic escalation failed: %s", exc)

        if strict_mode:
            stale_limit = 2
            llm_runtime_available = any(s.name == "llm_runtime" for s in strategies)
            llm_runtime_cases = cov.strategy_yields.get("llm_runtime", StrategyYield()).total_cases
            if llm_runtime_available and llm_runtime_cases == 0:
                # Give runtime LLM steering one chance before strict early-stop.
                stale_limit = max(stale_limit, 7)

            if cov.stale_rounds >= stale_limit:
                log.info(
                    "Strict plateau detected after %d stale rounds, stopping early",
                    cov.stale_rounds,
                )
                break

        _sync_memory_runtime_state(ctx, cov)
        memory_store = getattr(ctx, "memory_store", None)
        memory_state = getattr(ctx, "memory_state", None)
        if memory_store is not None and memory_state is not None:
            try:
                memory_store.checkpoint(
                    memory_state,
                    round_num=round_num,
                    tc_count=tc_count,
                    extra_meta={
                        "paragraphs_hit": len(cov.paragraphs_hit),
                        "branches_hit": counted_after,
                    },
                )
            except Exception as exc:
                log.debug("Memory checkpoint failed: %s", exc)

        # Early termination conditions
        full_para = (cov.total_paragraphs > 0
                     and len(cov.paragraphs_hit) >= cov.total_paragraphs)
        # Only count COBOL-validated branches (exclude py: prefixed + infrastructure)
        _infra = getattr(cov, "_infra_keys", None) or set()
        cobol_branches_hit = len(_counted_branches_for_mode(cov.branches_hit, True, _infra))
        full_branch = (cov.total_branches > 0
                       and cobol_branches_hit >= cov.total_branches)
        if full_para and full_branch:
            log.info("Full coverage achieved!")
            break

        if cov.stale_rounds >= term.max_stale_rounds and cov.total_paragraphs > 0:
            para_pct = len(cov.paragraphs_hit) / cov.total_paragraphs
            branch_pct = (cobol_branches_hit / cov.total_branches
                          if cov.total_branches > 0 else 1.0)
            if para_pct > term.plateau_para_pct and branch_pct > term.plateau_branch_pct:
                log.info("Plateau detected at %.1f%% para / %.1f%% branch, stopping",
                         para_pct * 100, branch_pct * 100)
                break
            # Extended patience when branch coverage is still low
            if cov.stale_rounds >= term.extended_stale_limit:
                log.info("Extended plateau at %.1f%% para / %.1f%% branch, stopping",
                         para_pct * 100, branch_pct * 100)
                break

        # Incremental uncovered-branch report snapshot. Writes the
        # current state to disk next to the test store so a canceled
        # run (Ctrl+C, SIGTERM, crash) leaves a fresh report behind.
        # Throttled inside _emit_uncovered_report so fast rounds
        # don't hammer the disk; the finalize-time call after the
        # loop exits always writes the terminal state.
        report.total_test_cases = tc_count
        report.paragraphs_hit = len(cov.paragraphs_hit)
        report.branches_hit = len(
            _counted_branches_for_mode(cov.branches_hit, ctx.context is not None)
        )
        if cov.total_paragraphs > 0:
            report.paragraph_coverage = (
                len(cov.paragraphs_hit) / cov.total_paragraphs
            )
        if cov.total_branches > 0:
            report.branch_coverage = (
                report.branches_hit / cov.total_branches
            )
        report.elapsed_seconds = time.time() - start_time
        _emit_uncovered_report(ctx, cov, report, reason="incremental")

        round_num += 1

    # --- FINALIZE ---
    elapsed = time.time() - start_time
    report.total_test_cases = tc_count
    report.paragraphs_hit = len(cov.paragraphs_hit)
    report.runtime_only_paragraphs = len(cov.runtime_only_paragraphs)
    # In COBOL mode, only count COBOL branches (not py:-prefixed Python ones)
    # and exclude specter infrastructure branches (SPECTER-* paragraphs).
    # In Python-only mode (ctx.context is None), all branches count.
    _infra = getattr(cov, "_infra_keys", None) or set()
    if ctx.context is not None:
        counted_branches = _counted_branches_for_mode(cov.branches_hit, True, _infra)
    else:
        counted_branches = _counted_branches_for_mode(cov.branches_hit, False, _infra)
    report.branches_hit = len(counted_branches)
    report.elapsed_seconds = elapsed
    if cov.total_paragraphs > 0:
        report.paragraph_coverage = len(cov.paragraphs_hit) / cov.total_paragraphs
    if cov.total_branches > 0:
        report.branch_coverage = len(counted_branches) / cov.total_branches

    _sync_memory_runtime_state(ctx, cov)
    memory_store = getattr(ctx, "memory_store", None)
    memory_state = getattr(ctx, "memory_state", None)
    if memory_store is not None and memory_state is not None:
        try:
            memory_store.checkpoint(
                memory_state,
                round_num=round_num,
                tc_count=tc_count,
                extra_meta={
                    "completed": True,
                    "paragraph_coverage": report.paragraph_coverage,
                    "branch_coverage": report.branch_coverage,
                },
            )
        except Exception as exc:
            log.debug("Final memory checkpoint failed: %s", exc)

    # --- Uncovered-branch diagnostic report ---
    # The helper also runs incrementally after every round (see the
    # round-end dump inside the while-loop above), so a canceled run
    # still has the latest snapshot on disk. This final call
    # overwrites the last incremental snapshot with the coverage
    # loop's terminal state.
    _emit_uncovered_report(ctx, cov, report, reason="final")

    log.info("Coverage complete: %s", report.summary())
    return report


# ---------------------------------------------------------------------------
# Python-only coverage entry point
# ---------------------------------------------------------------------------

def run_coverage(
    ast_file: str | Path,
    *,
    copybook_dirs: list[str | Path] | None = None,
    cobol_source: str | Path | None = None,
    budget: int = 5000,
    timeout: int | float = 1800,
    store_path: str | Path | None = None,
    seed: int = 42,
    llm_provider=None,
    llm_model: str | None = None,
    max_rounds: int = 0,
    batch_size: int = 200,
    coverage_config=None,
) -> CobolCoverageReport:
    """Run coverage-guided test generation using Python execution only.

    No GnuCOBOL required — executes the generated Python module directly.
    If *cobol_source* is provided, LLM strategies can read the COBOL source
    to extract paragraph comments and generate business-scenario-aware inputs.
    """
    from .ast_parser import parse_ast
    from .code_generator import generate_code
    from .monte_carlo import _load_module

    setup_start = time.time()
    rng = random.Random(seed)
    copybook_dirs = list(copybook_dirs or [])

    # --- PARSE + CODEGEN ---
    log.info("Parsing AST: %s", ast_file)
    program = parse_ast(ast_file)
    var_report = extract_variables(program)
    call_graph = build_static_call_graph(program)
    gating_conds = extract_gating_conditions(program, call_graph)
    stub_mapping = extract_stub_status_mapping(program, var_report)
    paragraph_comments: dict[str, list[str]] = {}
    if cobol_source_path and Path(cobol_source_path).exists():
        try:
            paragraph_comments = extract_paragraph_comments(
                program,
                Path(cobol_source_path).read_text(errors="replace").splitlines(),
            )
        except Exception as exc:
            log.debug("Failed to extract paragraph comments: %s", exc)
    seq_gates = extract_sequential_gates(program)
    if seq_gates:
        gating_conds = augment_gating_with_sequential_gates(
            gating_conds, seq_gates, call_graph,
        )

    # Build domain model
    copybook_records = load_copybooks(copybook_dirs) if copybook_dirs else []
    domains = build_variable_domains(
        var_report, copybook_records, stub_mapping,
        cobol_source=cobol_source,
    )
    _enrich_domains_with_boolean_hints(domains, program)
    log.info("Domain model: %d variables", len(domains))

    # Generate + load instrumented Python module
    import tempfile
    code = generate_code(program, var_report, instrument=True,
                         copybook_records=copybook_records,
                         cobol_source=str(cobol_source) if cobol_source else None)
    tmpdir = Path(tempfile.mkdtemp(prefix="specter_cov_"))
    py_path = tmpdir / f"{program.program_id}.py"
    py_path.write_text(code)
    module = _load_module(py_path)

    # Branch metadata (from generated module)
    raw_branch_meta = getattr(module, "_BRANCH_META", {})

    # Compute totals
    all_paras = {p.name for p in program.paragraphs}
    total_paragraphs = len(all_paras)
    total_branches = len(raw_branch_meta) * 2  # each branch: T + F

    # Setup store
    if store_path is None:
        store_path = tmpdir / f"{program.program_id}_testset.jsonl"
    store_path = Path(store_path)
    memory_store = MemoryStore(derive_memory_dir(store_path))
    memory_state = memory_store.load_state()
    memory_state.meta.setdefault("program_id", program.program_id)
    memory_state.meta.setdefault("mode", "python")

    # Load existing coverage
    existing_tcs, existing_paras, existing_branches = load_existing_coverage(store_path)

    # Expand stub mapping with 88-level siblings
    cobol_source_path = Path(cobol_source) if cobol_source else None
    siblings_88 = _build_siblings_88(copybook_records, cobol_source=cobol_source_path)
    flag_88_added = _expand_stub_mapping(stub_mapping, siblings_88)
    if flag_88_added:
        log.info("Expanded stub mapping with %d 88-level siblings: %s",
                 len(flag_88_added), sorted(flag_88_added))

    # Build success stubs
    success_stubs, success_defaults = _build_success_stubs(
        stub_mapping, domains,
        flag_88_added=flag_88_added, siblings_88=siblings_88,
    )

    # --- UPFRONT ANALYSIS (static, no LLM) ---
    from .program_analysis import (
        generate_seeds_from_analysis,
        prepare_program_analysis,
    )

    cobol_source_path = Path(cobol_source) if cobol_source else None
    if cobol_source_path and not cobol_source_path.exists():
        log.warning("COBOL source not found: %s", cobol_source_path)
        cobol_source_path = None

    analysis = prepare_program_analysis(
        program, var_report, domains, call_graph, gating_conds,
        stub_mapping, cobol_source=cobol_source_path,
        branch_meta=raw_branch_meta,
    )

    # Save analysis JSON alongside the test store
    analysis_path = store_path.with_suffix(".analysis.json")
    analysis_path.write_text(analysis.to_json())
    log.info("Analysis saved: %s", analysis_path)

    # --- LLM SEED GENERATION (one-time, from analysis JSON) ---
    from .coverage_config import CoverageConfig, SeedConfig
    if coverage_config is None:
        coverage_config = CoverageConfig(default_batch_size=batch_size)
    seed_cfg = coverage_config.seed_generation or SeedConfig()

    # Build coverage state + report early so we can execute seeds as they arrive
    existing_ast_paras = existing_paras & all_paras
    existing_runtime_only = existing_paras - all_paras

    cov = CoverageState(
        paragraphs_hit=existing_ast_paras,
        runtime_only_paragraphs=existing_runtime_only,
        branches_hit=existing_branches,
        total_paragraphs=total_paragraphs,
        total_branches=total_branches,
        test_cases=existing_tcs,
        all_paragraphs=all_paras,
        _stub_mapping=stub_mapping,
    )
    report = CobolCoverageReport(
        total_test_cases=len(existing_tcs),
        paragraphs_total=total_paragraphs,
        runtime_trace_total=total_paragraphs,
        runtime_only_paragraphs=len(existing_runtime_only),
        branches_total=total_branches,
    )
    tc_count = len(existing_tcs)

    # Callback: execute each seed batch immediately and report coverage
    _seed_exec_count = 0

    def _execute_seed_batch(seeds_batch: list[dict]) -> None:
        nonlocal tc_count, _seed_exec_count
        for seed_data in seeds_batch:
            _seed_exec_count += 1
            input_state = {}
            for var, val in seed_data.get("input_values", {}).items():
                dom = domains.get(var.upper())
                if dom:
                    input_state[var.upper()] = format_value_for_cobol(dom, val)
                else:
                    input_state[var.upper()] = str(val)

            stubs = dict(success_stubs)
            defaults = dict(success_defaults)
            for op_key, status_val in seed_data.get("stub_overrides", {}).items():
                matched = _match_stub_operation(op_key, stub_mapping)
                if matched:
                    svars = stub_mapping[matched]
                    entry = [(sv, status_val) for sv in svars]
                    stubs[matched] = [entry] * 50
                    defaults[matched] = entry

            result = _python_execute(module, input_state, stubs, defaults)
            if result.error:
                continue

            result_paras = set(result.paragraphs_hit)
            result_ast_paras = result_paras & all_paras if all_paras else result_paras
            new_paras = result_ast_paras - cov.paragraphs_hit
            new_branches = result.branches_hit - cov.branches_hit

            if not new_paras and not new_branches and tc_count >= 5:
                continue

            cov.paragraphs_hit.update(result_ast_paras)
            cov.branches_hit.update(result.branches_hit)

            # Harvest successful values
            if new_branches and domains:
                for var, val in input_state.items():
                    if isinstance(var, str) and not var.startswith("_"):
                        d = domains.get(var)
                        if d and val not in d.condition_literals:
                            d.condition_literals.append(val)

            tc_id = _compute_tc_id(input_state, [])
            _save_test_case(
                store_path, tc_id, input_state, [], result,
                "llm_seeds", seed_data.get("target", "seed")[:50],
            )
            tc_count += 1
            report.layer_stats["llm_seeds"] = report.layer_stats.get("llm_seeds", 0) + 1

            cov.test_cases.append({
                "id": tc_id,
                "input_state": {k: v for k, v in input_state.items() if not str(k).startswith("_")},
                "stub_outcomes": [],
                "paragraphs_hit": result.paragraphs_hit,
                "branches_hit": sorted(result.branches_hit),
                "layer": "llm_seeds",
                "target": seed_data.get("target", "seed")[:50],
            })

            if new_branches:
                log.info("  [llm_seeds] +%d branches -> %d/%d",
                         len(new_branches), len(cov.branches_hit), cov.total_branches)

        # Always log batch summary so user sees progress
        log.info("  [llm_seeds] executed %d seeds: %d/%d paras, %d/%d branches",
                 _seed_exec_count,
                 len(cov.paragraphs_hit), cov.total_paragraphs,
                 len(cov.branches_hit), cov.total_branches)

    llm_seeds: list[dict] = []
    _seeds_executed_live = False
    # Only generate seeds if llm_seed strategy is in the config (or default)
    _want_seeds = True
    if coverage_config and coverage_config.strategies:
        _want_seeds = "llm_seed" in coverage_config.strategies
    if coverage_config and coverage_config.rounds:
        _want_seeds = any(r.strategy == "llm_seed" for r in coverage_config.rounds)
    if llm_provider and _want_seeds:
        seed_cache = store_path.with_name(store_path.stem + "_seeds.json")
        llm_seeds = generate_seeds_from_analysis(
            analysis, llm_provider, llm_model,
            batch_size=seed_cfg.paragraphs_per_batch,
            seeds_per_batch=seed_cfg.seeds_per_batch,
            cache_path=seed_cache,
            use_cache=seed_cfg.cache,
            on_batch_ready=_execute_seed_batch,
        )
        # If seeds came from cache (on_batch_ready never fired), execute them now
        if llm_seeds and len(cov.branches_hit) == len(existing_branches):
            log.info("Executing %d cached seeds ...", len(llm_seeds))
            _execute_seed_batch(llm_seeds)
        _seeds_executed_live = True
        log.info("LLM seeds: %d total, %d/%d paras, %d/%d branches after seed execution",
                 len(llm_seeds), len(cov.paragraphs_hit), cov.total_paragraphs,
                 len(cov.branches_hit), cov.total_branches)

    # --- BUILD STRATEGY CONTEXT ---
    ctx = StrategyContext(
        module=module,
        context=None,  # Python-only mode
        domains=domains,
        stub_mapping=stub_mapping,
        call_graph=call_graph,
        gating_conds=gating_conds,
        var_report=var_report,
        program=program,
        all_paragraphs=all_paras,
        success_stubs=success_stubs,
        success_defaults=success_defaults,
        rng=rng,
        store_path=store_path,
        branch_meta=raw_branch_meta,
        cobol_source_path=cobol_source_path,
        llm_provider=llm_provider,
        llm_model=llm_model,
        jit_inference=None,
        paragraph_comments=paragraph_comments,
        siblings_88=siblings_88,
        flag_88_added=flag_88_added,
        payload_candidates={},
        memory_store=memory_store,
        memory_state=memory_state,
    )

    # --- REGISTER STRATEGIES ---
    from .coverage_config import CoverageConfig, build_selector, build_strategies

    if coverage_config is None:
        coverage_config = CoverageConfig(default_batch_size=batch_size)

    if coverage_config.strategies or coverage_config.rounds:
        strategies = build_strategies(coverage_config, llm_provider, llm_model)
    else:
        strategies: list[Strategy] = [
            BaselineStrategy(),
            DirectParagraphStrategy(),
            TranscriptSearchStrategy(),
            CorpusFuzzStrategy(),
            FaultInjectionStrategy(),
        ]

    # Skip _LLMSeedInjector if seeds were already executed live via callback
    if llm_seeds and not _seeds_executed_live:
        strategies.insert(0, _LLMSeedInjector(llm_seeds, stub_mapping))

    if coverage_config.selector != "heuristic" or coverage_config.rounds:
        selector = build_selector(coverage_config, llm_provider, llm_model, var_report)
    else:
        selector = HeuristicSelector(default_batch_size=batch_size)

    loop_start_time = time.time()
    setup_elapsed = loop_start_time - setup_start
    if setup_elapsed > 0.5:
        log.info("Coverage setup complete in %.1fs; starting execution loop", setup_elapsed)

    cov_report = _run_agentic_loop(
        ctx, cov, report, strategies, selector,
        budget, timeout, loop_start_time, tc_count,
        max_rounds=max_rounds,
        config=coverage_config,
    )

    # Auto-validate against COBOL if configured
    val_cfg = getattr(coverage_config, "validation", None)
    if (val_cfg and val_cfg.enabled
            and cobol_source and store_path
            and copybook_dirs):
        log.info("Running COBOL validation pass ...")
        from .cobol_validate import validate_store
        validated_path = Path(store_path).with_suffix(".validated.jsonl")
        try:
            val_report = validate_store(
                ast_file=ast_file,
                cobol_source=cobol_source,
                copybook_dirs=copybook_dirs,
                store_path=store_path,
                output_path=validated_path,
                timeout_per_case=val_cfg.timeout_per_case,
            )
            log.info("Validation complete:\n%s", val_report)
        except Exception as e:
            log.warning("COBOL validation failed: %s", e)

    return cov_report
