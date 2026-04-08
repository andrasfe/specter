"""Pluggable coverage strategies for the agentic coverage loop.

Each strategy is a generator that yields (input_state, stubs, defaults, target)
tuples.  The agentic loop in cobol_coverage.py handles execution and saving.
"""

from __future__ import annotations

import logging
import random
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional, Tuple

from .cobol_executor import CobolExecutionContext
from .models import Program
from .static_analysis import StaticCallGraph
from .variable_domain import (
    VariableDomain,
    build_payload_value_candidates,
    format_value_for_cobol,
    generate_value,
)
from .variable_extractor import VariableReport

log = logging.getLogger(__name__)

# Type alias for what strategies yield
CaseT = Tuple[dict, Optional[dict], Optional[dict], str]


# ---------------------------------------------------------------------------
# Shared context
# ---------------------------------------------------------------------------

@dataclass
class StrategyContext:
    """Shared immutable context for all strategies."""

    module: object                          # Python pre-run module
    context: CobolExecutionContext | None   # compiled COBOL (None in Python-only mode)
    domains: dict[str, VariableDomain]
    stub_mapping: dict[str, list[str]]
    call_graph: StaticCallGraph
    gating_conds: dict[str, list]
    var_report: VariableReport
    program: Program
    all_paragraphs: set[str]
    success_stubs: dict[str, list]
    success_defaults: dict[str, list]
    rng: random.Random
    store_path: Path
    branch_meta: dict = field(default_factory=dict)
    cobol_source_path: Path | None = None
    llm_provider: object | None = None
    llm_model: str | None = None
    jit_inference: object | None = None
    paragraph_comments: dict[str, list[str]] = field(default_factory=dict)
    siblings_88: dict[str, set[str]] = field(default_factory=dict)
    flag_88_added: set[str] = field(default_factory=set)
    payload_candidates: dict[str, dict[str, list]] = field(default_factory=dict)
    probe_cache: dict = field(default_factory=dict)  # para → list[BranchProbeResult]
    target_variable_allowlists: dict[str, set[str]] = field(default_factory=dict)
    current_target_key: str | None = None
    preferred_target_key: str | None = None
    memory_store: object | None = None
    memory_state: object | None = None


def _generate_domain_value(
    ctx: StrategyContext,
    var_name: str,
    dom: VariableDomain,
    strategy: str,
    target_paragraph: str | None = None,
) -> str | int | float:
    comment_hints = ctx.paragraph_comments.get(target_paragraph, []) if target_paragraph else []
    if ctx.jit_inference is not None:
        target_key = ctx.current_target_key
        if not target_key and target_paragraph:
            target_key = f"para:{target_paragraph}"
        allowed_vars = None
        if target_key:
            allowed_vars = ctx.target_variable_allowlists.get(target_key)

        before_hits = int(getattr(ctx.jit_inference, "cache_hits", 0) or 0)
        before_misses = int(getattr(ctx.jit_inference, "cache_misses", 0) or 0)
        before_skip_untargeted = int(getattr(ctx.jit_inference, "skipped_untargeted", 0) or 0)
        before_skip_scope = int(getattr(ctx.jit_inference, "skipped_out_of_scope", 0) or 0)
        inferred = ctx.jit_inference.generate_value(
            var_name,
            dom,
            strategy,
            ctx.rng,
            target_paragraph=target_paragraph,
            comment_hints=comment_hints,
            op_key=dom.set_by_stub,
            allowed_variables=allowed_vars,
            target_key=target_key,
        )
        if inferred is not None:
            if log.isEnabledFor(logging.DEBUG):
                debug_counter = int(getattr(ctx, "_jit_debug_counter", 0) or 0) + 1
                setattr(ctx, "_jit_debug_counter", debug_counter)
                if debug_counter % 25 == 0:
                    req_delta = (
                        int(getattr(ctx.jit_inference, "cache_hits", 0) or 0)
                        + int(getattr(ctx.jit_inference, "cache_misses", 0) or 0)
                        + int(getattr(ctx.jit_inference, "skipped_untargeted", 0) or 0)
                        + int(getattr(ctx.jit_inference, "skipped_out_of_scope", 0) or 0)
                        - (before_hits + before_misses)
                        - (before_skip_untargeted + before_skip_scope)
                    )
                    log.debug(
                        "JIT value var=%s strategy=%s para=%s value=%s req_delta=%d",
                        var_name,
                        strategy,
                        target_paragraph or "none",
                        inferred,
                        req_delta,
                    )
            return inferred
        if log.isEnabledFor(logging.DEBUG):
            debug_counter = int(getattr(ctx, "_jit_debug_counter", 0) or 0) + 1
            setattr(ctx, "_jit_debug_counter", debug_counter)
            if debug_counter % 25 == 0:
                req_delta = (
                    int(getattr(ctx.jit_inference, "cache_hits", 0) or 0)
                    + int(getattr(ctx.jit_inference, "cache_misses", 0) or 0)
                    + int(getattr(ctx.jit_inference, "skipped_untargeted", 0) or 0)
                    + int(getattr(ctx.jit_inference, "skipped_out_of_scope", 0) or 0)
                    - (before_hits + before_misses)
                    - (before_skip_untargeted + before_skip_scope)
                )
                log.debug(
                    "JIT fallback var=%s strategy=%s para=%s req_delta=%d",
                    var_name,
                    strategy,
                    target_paragraph or "none",
                    req_delta,
                )
    return generate_value(dom, strategy, ctx.rng)


def _set_target_key_for_paragraph(ctx: StrategyContext, paragraph: str | None) -> None:
    """Set active target key for paragraph-scoped generation paths."""
    if paragraph:
        ctx.current_target_key = f"para:{paragraph}"
    else:
        ctx.current_target_key = None


def _set_target_key_for_branch(
    ctx: StrategyContext,
    branch_id: int | str | None,
    direction: str,
    *,
    paragraph_fallback: str | None = None,
) -> None:
    """Set active target key for branch-scoped generation paths."""
    try:
        bid = int(branch_id) if branch_id is not None else None
    except (TypeError, ValueError):
        bid = None

    d = str(direction or "").strip().upper()
    if bid is not None and d in {"T", "F"}:
        ctx.current_target_key = f"branch:{bid}:{d}"
        return

    _set_target_key_for_paragraph(ctx, paragraph_fallback)


def _matches_preferred_branch_target(
    ctx: StrategyContext,
    branch_id: int | str | None,
    direction: str,
) -> bool:
    """Return whether a candidate branch matches the round's preferred target."""
    preferred = str(getattr(ctx, "preferred_target_key", "") or "").strip().lower()
    if not preferred or not preferred.startswith("branch:"):
        return True

    try:
        bid = int(branch_id)
    except (TypeError, ValueError):
        return True

    d = str(direction or "").strip().upper()
    return preferred == f"branch:{bid}:{d}".lower()


@dataclass
class StrategyYield:
    """Tracks yield per strategy across rounds."""

    total_cases: int = 0
    total_new_coverage: int = 0
    rounds: int = 0
    last_yield_round: int = 0


@dataclass
class BranchProbeResult:
    """Result of probing a branch via direct paragraph execution."""

    branch_key: str                          # e.g. "17:F"
    paragraph: str
    hit_count: int
    total_probes: int
    hit_inputs: list = field(default_factory=list)       # up to 5 concrete inputs
    discriminating_vars: dict = field(default_factory=dict)  # var → set of values
    discriminating_stubs: dict = field(default_factory=dict)  # op_key → set of values


@dataclass
class StubBranchMap:
    """Maps stub operation outcomes to the branches they activate."""

    op_key: str
    outcome_to_branches: dict = field(default_factory=dict)  # str(value) → set[str]


# ---------------------------------------------------------------------------
# Strategy ABC
# ---------------------------------------------------------------------------

class Strategy(ABC):
    """Base class for coverage strategies."""

    name: str = "unknown"
    priority: int = 50
    requires_llm: bool = False

    @abstractmethod
    def generate_cases(
        self,
        ctx: StrategyContext,
        cov: "CoverageState",  # forward ref to avoid circular import
        batch_size: int,
    ) -> Iterator[CaseT]:
        """Yield (input_state, stub_outcomes, stub_defaults, target_label)."""
        ...

    def should_run(self, cov: "CoverageState", round_num: int) -> bool:
        """Return True if this strategy is eligible to run."""
        return True


# ---------------------------------------------------------------------------
# Strategy implementations
# ---------------------------------------------------------------------------

class BaselineStrategy(Strategy):
    """Layer 1: All-success baseline with domain strategies."""

    name = "baseline"
    priority = 20

    def __init__(self):
        self._ran = False

    def should_run(self, cov, round_num: int) -> bool:
        return not self._ran

    def generate_cases(self, ctx, cov, batch_size) -> Iterator[CaseT]:
        from .cobol_coverage import _build_input_state

        self._ran = True
        prev_target_key = ctx.current_target_key
        ctx.current_target_key = None

        try:
            # Phase 1: one case per value-generation strategy
            strategies = ["condition_literal", "semantic", "random_valid", "88_value", "boundary"]
            for strat in strategies:
                input_state = _build_input_state(
                    ctx.domains,
                    strat,
                    ctx.rng,
                    jit_inference=ctx.jit_inference,
                    paragraph_comments=ctx.paragraph_comments,
                )
                yield input_state, ctx.success_stubs, ctx.success_defaults, "baseline"

            # Phase 2: condition_literal values per input variable
            for name, dom in ctx.domains.items():
                if dom.condition_literals and dom.classification == "input":
                    for lit in dom.condition_literals[:3]:
                        base = _build_input_state(
                            ctx.domains,
                            "semantic",
                            ctx.rng,
                            jit_inference=ctx.jit_inference,
                            paragraph_comments=ctx.paragraph_comments,
                        )
                        base[name] = format_value_for_cobol(dom, lit)
                        yield base, ctx.success_stubs, ctx.success_defaults, f"lit:{name}"
        finally:
            ctx.current_target_key = prev_target_key


# ---------------------------------------------------------------------------
# Branch probing helpers (execution-guided, no LLM cost)
# ---------------------------------------------------------------------------


def _probe_branches_for_paragraph(
    ctx: StrategyContext,
    cov,
    para: str,
    branch_meta: dict,
    max_probes: int = 200,
) -> list[BranchProbeResult]:
    """Execute *para* with a grid of inputs to discover branch-activating states.

    Returns one ``BranchProbeResult`` per uncovered branch in the paragraph.
    """
    from .monte_carlo import _run_paragraph_directly

    # 1. Find uncovered branches in this paragraph
    uncovered: list[tuple[int, str, str]] = []  # (bid_int, direction, bkey)
    for bid, meta in branch_meta.items():
        if meta.get("paragraph") != para:
            continue
        try:
            bid_int = int(bid)
        except (ValueError, TypeError):
            continue
        for d in ("T", "F"):
            bkey = f"{bid}:{d}"
            if bkey not in cov.branches_hit:
                uncovered.append((bid_int, d, bkey))

    if not uncovered:
        return []

    if log.isEnabledFor(logging.DEBUG):
        log.debug(
            "probe_start para=%s uncovered=%d max_probes=%d",
            para,
            len(uncovered),
            max_probes,
        )

    # 2. Build probe-value grid from condition variables
    probe_vars: dict[str, list] = {}
    kw = {"NOT", "AND", "OR", "EQUAL", "GREATER", "LESS", "THAN",
          "ZERO", "ZEROS", "ZEROES", "SPACES", "SPACE", "OTHER",
          "NUMERIC", "TRUE", "FALSE"}
    for bid, meta in branch_meta.items():
        if meta.get("paragraph") != para:
            continue
        cond = meta.get("condition", "")
        if not cond:
            continue
        for var_name in set(re.findall(r"\b([A-Z][A-Z0-9_-]+)\b", cond)) - kw:
            if var_name in probe_vars:
                continue
            dom = ctx.domains.get(var_name)
            if not dom:
                continue
            vals: list = []
            for lit in (dom.condition_literals or []):
                if lit not in vals:
                    vals.append(lit)
            for v88 in (dom.valid_88_values or {}).values():
                if v88 not in vals:
                    vals.append(v88)
            if dom.data_type == "numeric":
                for bv in [0, 1, -1]:
                    if bv not in vals:
                        vals.append(bv)
                if dom.max_value is not None and dom.max_value not in vals:
                    vals.append(dom.max_value)
            else:
                for sv in ["", " ", "Y", "N"]:
                    if sv not in vals:
                        vals.append(sv)
            probe_vars[var_name] = vals[:15]

    # 3. Build stub fault configurations
    default_state_fn = getattr(ctx.module, "_default_state", None)
    ds = default_state_fn() if default_state_fn else {}

    stub_configs: list[tuple[dict, dict, dict]] = [
        (dict(ctx.success_stubs), dict(ctx.success_defaults), {}),
    ]
    for op_key, status_vars in ctx.stub_mapping.items():
        fault_vals: list = []
        for var in status_vars:
            dom = ctx.domains.get(var)
            if dom:
                for lit in (dom.condition_literals or [])[:3]:
                    if lit not in fault_vals:
                        fault_vals.append(lit)
                for v88 in list((dom.valid_88_values or {}).values())[:3]:
                    if v88 not in fault_vals:
                        fault_vals.append(v88)
        if not fault_vals:
            fault_vals = ["10", "23", "00"]
        for fv in fault_vals[:4]:
            fs = dict(ctx.success_stubs)
            fd = dict(ctx.success_defaults)
            entry = [(sv, fv) for sv in status_vars]
            fs[op_key] = [entry] * 50
            fd[op_key] = entry
            stub_configs.append((fs, fd, {op_key: fv}))

    # 4. Generate probe inputs via grid sampling
    probe_inputs: list[dict] = []
    var_names = list(probe_vars.keys())
    n_per_config = max(1, max_probes // max(len(stub_configs), 1))
    for _ in range(n_per_config):
        state: dict = {}
        for vn in var_names:
            vals = probe_vars[vn]
            if vals:
                state[vn] = ctx.rng.choice(vals)
        probe_inputs.append(state)
    # Pad with domain-aware random states
    while len(probe_inputs) < max_probes // 2:
        state = {}
        for vn in var_names:
            dom = ctx.domains.get(vn)
            if dom:
                state[vn] = generate_value(
                    dom,
                    ctx.rng.choice(["boundary", "random_valid", "condition_literal"]),
                    ctx.rng,
                )
        probe_inputs.append(state)

    # 5. Execute probes
    tracker: dict[str, dict] = {
        bkey: {"hits": 0, "inputs": [], "var_hits": {}, "stub_hits": {}}
        for _, _, bkey in uncovered
    }
    total_probes = 0

    for probe_state in probe_inputs:
        for stubs, defaults, stub_label in stub_configs:
            if total_probes >= max_probes:
                break
            total_probes += 1
            run_state = dict(ds)
            run_state.update(probe_state)
            run_state["_stub_outcomes"] = {
                k: [list(e) if isinstance(e, list) else e for e in v]
                for k, v in stubs.items()
            }
            run_state["_stub_defaults"] = dict(defaults)
            try:
                final = _run_paragraph_directly(ctx.module, para, run_state)
            except Exception:
                continue
            if not final:
                continue

            branches = final.get("_branches", set())
            for bid_int, direction, bkey in uncovered:
                target = bid_int if direction == "T" else -bid_int
                if target in branches:
                    t = tracker[bkey]
                    t["hits"] += 1
                    if len(t["inputs"]) < 5:
                        t["inputs"].append(dict(probe_state))
                    for vn, vv in probe_state.items():
                        if vn.startswith("_"):
                            continue
                        t["var_hits"].setdefault(vn, {})
                        vv_key = str(vv)
                        t["var_hits"][vn][vv_key] = (
                            t["var_hits"][vn].get(vv_key, 0) + 1
                        )
                    for ok, fv in stub_label.items():
                        t["stub_hits"].setdefault(ok, {})
                        fv_str = str(fv)
                        t["stub_hits"][ok][fv_str] = (
                            t["stub_hits"][ok].get(fv_str, 0) + 1
                        )
        if total_probes >= max_probes:
            break

    # 6. Build results
    results: list[BranchProbeResult] = []
    for bid_int, direction, bkey in uncovered:
        t = tracker[bkey]
        disc_vars: dict[str, set] = {}
        disc_stubs: dict[str, set] = {}
        if t["hits"] > 0:
            threshold = max(1, int(t["hits"] * 0.3))
            for vn, vc in t["var_hits"].items():
                top = {v for v, c in vc.items() if c >= threshold}
                if top and len(top) <= 5:
                    disc_vars[vn] = top
            for ok, vc in t["stub_hits"].items():
                top = {v for v, c in vc.items() if c >= threshold}
                if top:
                    disc_stubs[ok] = top
        results.append(BranchProbeResult(
            branch_key=bkey,
            paragraph=para,
            hit_count=t["hits"],
            total_probes=total_probes,
            hit_inputs=t["inputs"],
            discriminating_vars=disc_vars,
            discriminating_stubs=disc_stubs,
        ))
    if log.isEnabledFor(logging.DEBUG):
        total_hits = sum(r.hit_count for r in results)
        log.debug(
            "probe_end para=%s uncovered=%d probes=%d hits=%d",
            para,
            len(uncovered),
            total_probes,
            total_hits,
        )
    return results


def _discover_stub_branch_mapping(
    ctx: StrategyContext,
    para: str,
    branch_meta: dict,
) -> list[StubBranchMap]:
    """For each stub op, discover which status values activate which branches."""
    from .monte_carlo import _run_paragraph_directly

    default_state_fn = getattr(ctx.module, "_default_state", None)
    ds = default_state_fn() if default_state_fn else {}

    para_bids: list[int] = []
    for bid, meta in branch_meta.items():
        if meta.get("paragraph") != para:
            continue
        try:
            para_bids.append(int(bid))
        except (ValueError, TypeError):
            continue
    if not para_bids:
        return []

    results: list[StubBranchMap] = []
    for op_key, status_vars in ctx.stub_mapping.items():
        values_to_try: set = set()
        for var in status_vars:
            dom = ctx.domains.get(var)
            if dom:
                for lit in (dom.condition_literals or []):
                    values_to_try.add(lit)
                for v88 in (dom.valid_88_values or {}).values():
                    values_to_try.add(v88)
        if not values_to_try:
            values_to_try = {"00", "10", "23", "35", 0, 13, 27}

        outcome_to_branches: dict[str, set] = {}
        for fv in values_to_try:
            stubs = dict(ctx.success_stubs)
            defaults = dict(ctx.success_defaults)
            entry = [(sv, fv) for sv in status_vars]
            stubs[op_key] = [entry] * 50
            defaults[op_key] = entry

            run_state = dict(ds)
            run_state["_stub_outcomes"] = {
                k: [list(e) if isinstance(e, list) else e for e in v]
                for k, v in stubs.items()
            }
            run_state["_stub_defaults"] = dict(defaults)
            try:
                final = _run_paragraph_directly(ctx.module, para, run_state)
            except Exception:
                continue
            if not final:
                continue

            activated: set[str] = set()
            branches = final.get("_branches", set())
            for bid_int in para_bids:
                if bid_int in branches:
                    activated.add(f"{bid_int}:T")
                if -bid_int in branches:
                    activated.add(f"{bid_int}:F")
            if activated:
                outcome_to_branches[str(fv)] = activated

        if outcome_to_branches:
            results.append(StubBranchMap(
                op_key=op_key,
                outcome_to_branches=outcome_to_branches,
            ))
    return results


def _format_probing_results(
    probe_results: list[BranchProbeResult],
    stub_maps: list[StubBranchMap],
) -> str:
    """Format probing results as a prompt section for the LLM."""
    if not probe_results and not stub_maps:
        return ""

    lines: list[str] = ["\n\n## Execution Probing Results"]
    for r in probe_results[:12]:
        lines.append(f"### Branch {r.branch_key} (para={r.paragraph})")
        lines.append(f"- Reached in {r.hit_count}/{r.total_probes} probes")
        if r.discriminating_vars:
            for var, vals in list(r.discriminating_vars.items())[:3]:
                lines.append(f"- Discriminating: {var} in {vals}")
        if r.discriminating_stubs:
            for op, vals in r.discriminating_stubs.items():
                lines.append(f"- Stub map: {op} → values {vals} activate this branch")
        if r.hit_inputs:
            preview = {
                k: v
                for k, v in list(r.hit_inputs[0].items())[:6]
                if not str(k).startswith("_")
            }
            lines.append(f"- Example hit: {preview}")
        if r.hit_count == 0:
            lines.append(
                "- NOT reached by any probe — may need specific stub+input combo"
            )

    if stub_maps:
        lines.append("\n### Stub-to-Branch Mapping")
        for sm in stub_maps[:8]:
            for val, brs in list(sm.outcome_to_branches.items())[:5]:
                lines.append(f"- {sm.op_key}={val} activates {brs}")

    return "\n".join(lines)


def _best_probed_state_for_para(
    ctx: StrategyContext, para: str,
) -> dict | None:
    """Return the best probing-discovered input state for a paragraph, or None."""
    cached = ctx.probe_cache.get(para)
    if not cached:
        return None
    # Pick the hit_input from the result with highest hit_count
    best = None
    best_hits = -1
    for r in cached:
        if r.hit_inputs and r.hit_count > best_hits:
            best = r.hit_inputs[0]
            best_hits = r.hit_count
    return dict(best) if best else None


class DirectParagraphStrategy(Strategy):
    """Interlaced param / stub / dataflow tuning via direct paragraph invocation.

    Alternates between three modes each time the agentic loop calls us:
      - **param round**: freeze stubs from best TCs, hill-climb input params
      - **stub round**: freeze inputs from best TCs, sweep stub configs
      - **dataflow round**: backprop constraints through computation chains

    Each round uses direct invocation (~1ms/trial) for throughput.
    """

    name = "direct_paragraph"
    priority = 35

    def should_run(self, cov, round_num: int) -> bool:
        cobol_hits = sum(1 for b in cov.branches_hit if not b.startswith("py:"))
        return cov.total_branches > 0 and cobol_hits < cov.total_branches

    _FAULT_TABLES = {
        "status_file": ["10", "23", "35", "39", "46", "47"],
        "status_sql": [0, 100, -803, -805, -904],
        "status_cics": [0, 12, 13, 16, 22, 27],
    }

    def __init__(self):
        self._round = 0  # 0=param, 1=stub, 2=dataflow, 3=frontier

    def _fault_values_for_op(self, ctx, op_key: str) -> list:
        """Compute interesting fault values for a stub operation.

        Prefers domain-specific values (condition_literals, 88-level values)
        over generic fault tables — these are the actual values the program
        checks for in IF/EVALUATE conditions.
        """
        status_vars = ctx.stub_mapping.get(op_key, [])
        values: list = []
        seen: set = set()

        for var in status_vars:
            dom = ctx.domains.get(var)
            if not dom:
                continue
            # 1. Condition literals — values seen in IF conditions
            for lit in (dom.condition_literals or []):
                k = str(lit)
                if k not in seen:
                    values.append(lit)
                    seen.add(k)
            # 2. 88-level values — COBOL-declared valid values
            for val_88 in (dom.valid_88_values or {}).values():
                k = str(val_88)
                if k not in seen:
                    values.append(val_88)
                    seen.add(k)
            # 3. Generic fault table fallback
            for fv in self._FAULT_TABLES.get(dom.semantic_type, []):
                k = str(fv)
                if k not in seen:
                    values.append(fv)
                    seen.add(k)

        # DLI/PCB status codes
        if op_key.startswith("DLI") or any("PCB" in v.upper() for v in status_vars):
            for fv in ["  ", "GE", "GB", "II", "AI"]:
                if fv not in seen:
                    values.append(fv)
                    seen.add(fv)

        if not values:
            values = ["10", "23", "35", "00", " "]

        return values

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _paragraphs_with_gaps(self, branch_meta, cov):
        """Paragraphs with uncovered branches, sorted by gap size desc."""
        gaps: dict[str, int] = {}
        for bid, meta in branch_meta.items():
            p = meta.get("paragraph", "")
            if not p or p not in cov.paragraphs_hit:
                continue
            for d in ("T", "F"):
                if f"{bid}:{d}" not in cov.branches_hit:
                    gaps[p] = gaps.get(p, 0) + 1
        return sorted(gaps.keys(), key=lambda p: gaps[p], reverse=True)

    def _best_tc_for_para(self, cov, para):
        best = None
        for tc in cov.test_cases:
            if para in tc.get("paragraphs_hit", []):
                if not best or len(tc.get("branches_hit", [])) > len(
                    best.get("branches_hit", [])
                ):
                    best = tc
        return best

    def _collect_cond_vars(self, branch_meta, para, ctx):
        """Condition variables + interesting values for a paragraph."""
        import re

        from .static_analysis import _parse_condition_variables

        kw = {"NOT", "AND", "OR", "EQUAL", "GREATER", "LESS", "THAN",
              "ZERO", "ZEROS", "ZEROES", "SPACES", "SPACE", "OTHER",
              "NUMERIC", "ALPHABETIC", "TRUE", "FALSE", "HIGH", "LOW",
              "VALUES", "DFHRESP", "NORMAL", "ERROR", "NOTFND",
              "NEXT", "SENTENCE", "THEN", "PERFORM", "NEGATIVE", "POSITIVE"}
        cv: dict[str, list] = {}
        for bid, meta in branch_meta.items():
            if meta.get("paragraph") != para:
                continue
            cond = meta.get("condition", "")
            if meta.get("type") == "EVALUATE" and meta.get("subject"):
                subj = meta["subject"]
                if subj not in cv:
                    cv[subj] = []
                w = cond
                if w.startswith("'") and w.endswith("'"):
                    cv[subj].append(w[1:-1])
                elif w.lstrip("+-").isdigit():
                    cv[subj].append(int(w))
                elif w not in ("OTHER", ""):
                    cv[subj].append(w)
                info = ctx.var_report.variables.get(subj)
                if info and hasattr(info, "condition_literals"):
                    for lit in info.condition_literals:
                        if lit not in cv[subj]:
                            cv[subj].append(lit)
                if -99999 not in cv[subj]:
                    cv[subj].append(-99999)
                continue
            if not cond:
                continue
            try:
                parsed = _parse_condition_variables(cond)
            except Exception:
                continue
            for var, vals, _ in parsed:
                if var not in cv:
                    cv[var] = []
                for v in vals:
                    if v not in cv[var]:
                        cv[var].append(v)
            for var in set(re.findall(r'\b([A-Z][A-Z0-9_-]+)\b', cond)) - kw:
                if var not in cv:
                    cv[var] = []
                info = ctx.var_report.variables.get(var)
                if info and hasattr(info, "condition_literals"):
                    for lit in info.condition_literals:
                        if lit not in cv[var]:
                            cv[var].append(lit)
                if not cv[var]:
                    cv[var] = ["", "00", "Y", "N", 0, 1]
        return cv

    # ------------------------------------------------------------------
    # Param round: freeze stubs, hill-climb inputs
    # ------------------------------------------------------------------

    def _param_round(self, ctx, cov, batch_size, branch_meta) -> Iterator[CaseT]:
        default_state_fn = getattr(ctx.module, "_default_state", None)
        ds = default_state_fn() if default_state_fn else {}
        var_list = list(ds.keys())
        str_vals = ["", " ", "Y", "N", "00", "04", "05", "10",
                    "001", "002", "013", "019", "XX", "I", "T", "R"]
        int_vals = [0, 1, -1, 99, 100, 999, -999, 1000000]
        flag_vals = [True, False, "Y", "N", " ", "X"]

        sorted_paras = self._paragraphs_with_gaps(branch_meta, cov)
        trials_per = max(20, batch_size // max(len(sorted_paras), 1))
        yielded = 0

        for para in sorted_paras:
            if yielded >= batch_size:
                break
            _set_target_key_for_paragraph(ctx, para)
            # Prefer probing-discovered state as base (empirically better)
            probed = _best_probed_state_for_para(ctx, para)
            tc = self._best_tc_for_para(cov, para)
            base_state = probed if probed else (
                dict(tc.get("input_state", {})) if tc else {}
            )
            # Freeze stubs from best TC (or success)
            stubs = dict(ctx.success_stubs)
            defaults = dict(ctx.success_defaults)
            if tc and tc.get("stub_outcomes"):
                for op, entries in tc["stub_outcomes"]:
                    stubs[op] = [entries] * 50
                    defaults[op] = entries

            cond_vars = self._collect_cond_vars(branch_meta, para, ctx)

            for trial in range(trials_per):
                if yielded >= batch_size:
                    break
                state = dict(base_state)
                # Condition-aware random perturbation
                for var, literals in cond_vars.items():
                    r = ctx.rng.random()
                    if r < 0.4 and literals:
                        state[var] = ctx.rng.choice(literals)
                    elif r < 0.7:
                        dom = ctx.domains.get(var)
                        if dom:
                            strat = ctx.rng.choice(["semantic", "boundary", "random_valid"])
                            state[var] = _generate_domain_value(ctx, var, dom, strat, para)
                        else:
                            info = ctx.var_report.variables.get(var)
                            if info and info.classification == "flag":
                                state[var] = ctx.rng.choice(flag_vals)
                            elif isinstance(ds.get(var), int):
                                state[var] = ctx.rng.choice(int_vals)
                            else:
                                state[var] = ctx.rng.choice(str_vals)
                # Random perturbation of a few extra vars (domain-aware)
                for _ in range(ctx.rng.randint(1, 8)):
                    if not var_list:
                        break
                    v = ctx.rng.choice(var_list)
                    if v not in cond_vars:
                        dom = ctx.domains.get(v)
                        if dom:
                            strat = ctx.rng.choice(["semantic", "boundary", "random_valid"])
                            state[v] = _generate_domain_value(ctx, v, dom, strat, para)
                        else:
                            dv = ds.get(v)
                            if isinstance(dv, int):
                                state[v] = ctx.rng.choice(int_vals)
                            elif isinstance(dv, str):
                                state[v] = ctx.rng.choice(str_vals)

                yield state, stubs, defaults, f"direct:{para}|p:{trial}"
                yielded += 1

    # ------------------------------------------------------------------
    # Stub round: freeze inputs, sweep stub configs
    # ------------------------------------------------------------------

    def _stub_round(self, ctx, cov, batch_size, branch_meta) -> Iterator[CaseT]:
        from .cobol_coverage import _build_fault_stubs

        sorted_paras = self._paragraphs_with_gaps(branch_meta, cov)
        yielded = 0

        # Build fault configs using domain-aware values
        fault_configs: list[tuple[dict, dict, str]] = []
        for op_key in ctx.stub_mapping:
            for fv in self._fault_values_for_op(ctx, op_key)[:8]:
                fs, fd = _build_fault_stubs(
                    ctx.stub_mapping, ctx.domains,
                    target_op=op_key, fault_value=fv, rng=ctx.rng,
                )
                fault_configs.append((fs, fd, f"f:{op_key}={fv}"))

        if not fault_configs:
            # No stubs → fall back to a param round
            yield from self._param_round(ctx, cov, batch_size, branch_meta)
            return

        for para in sorted_paras:
            if yielded >= batch_size:
                break
            _set_target_key_for_paragraph(ctx, para)
            tc = self._best_tc_for_para(cov, para)
            base_state = dict(tc.get("input_state", {})) if tc else {}

            for stubs, defaults, label in fault_configs:
                if yielded >= batch_size:
                    break
                yield base_state, stubs, defaults, f"direct:{para}|{label}"
                yielded += 1

    # ------------------------------------------------------------------
    # Dataflow round: backprop constraints through computation chains
    # ------------------------------------------------------------------

    def _dataflow_round(self, ctx, cov, batch_size, branch_meta) -> Iterator[CaseT]:
        from .cobol_coverage import _build_fault_stubs
        from .static_analysis import _parse_condition_variables
        from .test_synthesis import (
            _extract_paragraph_dataflow,
            _solve_backward_constraint,
            _trace_backward,
            _trace_interprocedural,
        )

        sorted_paras = self._paragraphs_with_gaps(branch_meta, cov)
        yielded = 0
        df_cache: dict[str, tuple] = {}

        # Pre-build stub configs using domain-aware values
        stub_configs: list[tuple[dict, dict, str]] = [
            (ctx.success_stubs, ctx.success_defaults, "ok"),
        ]
        for op_key in ctx.stub_mapping:
            for fv in self._fault_values_for_op(ctx, op_key)[:3]:
                fs, fd = _build_fault_stubs(
                    ctx.stub_mapping, ctx.domains,
                    target_op=op_key, fault_value=fv, rng=ctx.rng,
                )
                stub_configs.append((fs, fd, f"f:{op_key}={fv}"))

        for para in sorted_paras:
            if yielded >= batch_size:
                break
            _set_target_key_for_paragraph(ctx, para)

            # Extract dataflow for this paragraph (cached)
            if para not in df_cache:
                df_cache[para] = _extract_paragraph_dataflow(ctx.module, para)
            assignments, branch_checks = df_cache[para]
            if not assignments and not branch_checks:
                continue

            tc = self._best_tc_for_para(cov, para)
            base_state = dict(tc.get("input_state", {})) if tc else {}

            # For each uncovered branch in this paragraph
            for bid, meta in branch_meta.items():
                if meta.get("paragraph") != para:
                    continue
                for direction in ("T", "F"):
                    if not _matches_preferred_branch_target(ctx, bid, direction):
                        continue
                    bkey = f"{bid}:{direction}"
                    if bkey in cov.branches_hit:
                        continue
                    _set_target_key_for_branch(
                        ctx,
                        bid,
                        direction,
                        paragraph_fallback=para,
                    )
                    if yielded >= batch_size:
                        break

                    negate = direction == "F"
                    condition = meta.get("condition", "")
                    if not condition:
                        continue

                    # Find the branch check line.  In COBOL mode branch IDs
                    # are strings ("1", "2"); in Python mode they are ints.
                    branch_line = None
                    try:
                        bid_int = int(bid)
                    except (ValueError, TypeError):
                        bid_int = None
                    for line_idx, check_bid, _cond_line, _indent in branch_checks:
                        if check_bid == bid or check_bid == bid_int:
                            branch_line = line_idx
                            break
                        if bid_int is not None and check_bid == -bid_int:
                            branch_line = line_idx
                            break
                    if branch_line is None:
                        continue

                    try:
                        parsed = _parse_condition_variables(condition)
                    except Exception:
                        continue

                    for pvar, vals, neg in parsed:
                        # Trace backward from condition var
                        chain = _trace_backward(pvar, branch_line, assignments)
                        if not chain:
                            chain = _trace_interprocedural(
                                ctx.module, pvar, branch_line,
                                assignments, branch_checks, df_cache,
                            )
                        if not chain:
                            continue

                        # Solve backward constraints
                        overrides = _solve_backward_constraint(
                            pvar, condition, chain, negate, meta,
                            ctx.var_report, base_state,
                        )
                        if not overrides:
                            continue

                        # Build solved state variations
                        states: list[tuple[dict, str]] = []
                        for attempt in range(5):
                            state = dict(base_state)
                            state.update(overrides)

                            if attempt == 0 and vals:
                                effective_neg = neg ^ negate
                                if not effective_neg:
                                    state[pvar] = vals[0]
                                else:
                                    state[pvar] = ("__NOMATCH__"
                                                   if isinstance(vals[0], str)
                                                   else vals[0] + 99999)
                            elif attempt == 1:
                                for k, v in overrides.items():
                                    if isinstance(v, (int, float)) and v != 0:
                                        state[k] = v * 10
                            elif attempt == 2:
                                if pvar in state and pvar in [c[0] for c in chain]:
                                    del state[pvar]
                            elif attempt == 3:
                                state[pvar] = 999999
                                for k, v in overrides.items():
                                    if isinstance(v, (int, float)):
                                        state[k] = v * 100
                            elif attempt == 4:
                                state = dict(base_state)
                                state.update(overrides)

                            states.append((state, str(attempt)))

                        # Try each state × each stub config
                        for state, att in states:
                            for stubs, defaults, slabel in stub_configs:
                                if yielded >= batch_size:
                                    break
                                yield (state, stubs, defaults,
                                       f"direct:{para}|df:{bid}:{direction}:{att}:{slabel}")
                                yielded += 1
                            if yielded >= batch_size:
                                break

                        break  # found a chain for this branch, move on

    # ------------------------------------------------------------------
    # Frontier round: flip branches that gate uncovered paragraphs
    # ------------------------------------------------------------------

    def _frontier_round(self, ctx, cov, batch_size, branch_meta) -> Iterator[CaseT]:
        from .monte_carlo import _run_paragraph_directly
        from .static_analysis import _parse_condition_variables

        yielded = 0

        # Find frontier: covered paragraphs that call uncovered ones
        frontier: list[tuple[int, str, str]] = []
        for covered_para in cov.paragraphs_hit:
            callees = ctx.call_graph.edges.get(covered_para, set())
            for callee in callees:
                if callee not in cov.paragraphs_hit:
                    for bid, meta in branch_meta.items():
                        if meta.get("paragraph") == covered_para:
                            for direction in ("T", "F"):
                                bkey = f"{bid}:{direction}"
                                if bkey not in cov.branches_hit:
                                    frontier.append((bid, direction, covered_para, callee))

        if not frontier:
            # No uncovered paragraphs reachable — fall back to param round
            yield from self._param_round(ctx, cov, batch_size, branch_meta)
            return

        # For each frontier branch, find TCs that reach the paragraph,
        # run them to inspect final state, then flip the condition
        for bid, direction, bpara, target_para in frontier:
            if yielded >= batch_size:
                break
            if not _matches_preferred_branch_target(ctx, bid, direction):
                continue
            _set_target_key_for_branch(
                ctx,
                bid,
                direction,
                paragraph_fallback=bpara,
            )

            meta = branch_meta.get(bid, {})
            condition = meta.get("condition", "")
            if not condition:
                continue

            try:
                parsed = _parse_condition_variables(condition)
            except Exception:
                continue
            if not parsed:
                continue

            negate = direction == "F"

            # Find TCs that reach bpara
            relevant_tcs = [
                tc for tc in cov.test_cases
                if bpara in tc.get("paragraphs_hit", [])
            ][:3]
            if not relevant_tcs:
                continue

            for tc in relevant_tcs:
                if yielded >= batch_size:
                    break

                # Run TC and inspect final state
                base_state = dict(tc.get("input_state", {}))
                default_state_fn = getattr(ctx.module, "_default_state", None)
                run_state = default_state_fn() if default_state_fn else {}
                run_state.update(base_state)

                stubs_for_run = {}
                if tc.get("stub_outcomes"):
                    for op, entries in tc["stub_outcomes"]:
                        stubs_for_run[op] = [entries] * 50
                run_state["_stub_outcomes"] = stubs_for_run
                run_state["_stub_defaults"] = dict(ctx.success_defaults)

                try:
                    final_state = ctx.module.run(run_state)
                except Exception:
                    final_state = run_state

                # Build flipped state
                state = dict(base_state)
                stubs = dict(stubs_for_run)

                for pvar, vals, neg in parsed:
                    effective_neg = neg != negate
                    current_val = final_state.get(pvar)

                    if not effective_neg and vals:
                        state[pvar] = vals[0]
                    elif effective_neg and vals:
                        if current_val in vals or current_val is None:
                            info = ctx.var_report.variables.get(pvar)
                            literals = (info.condition_literals
                                        if info and hasattr(info, "condition_literals")
                                        else [])
                            found_alt = False
                            for lit in literals:
                                if lit not in vals:
                                    state[pvar] = lit
                                    found_alt = True
                                    break
                            if not found_alt:
                                state[pvar] = (vals[0] + 999
                                               if isinstance(vals[0], (int, float))
                                               else "XX")

                    # Also set via stubs
                    if ctx.stub_mapping:
                        for op_key, svars in ctx.stub_mapping.items():
                            if pvar in svars and pvar in state:
                                stubs[op_key] = [[(pvar, state[pvar])]] * 50

                defaults = dict(ctx.success_defaults)
                for op_key in stubs:
                    if stubs[op_key]:
                        defaults[op_key] = stubs[op_key][0]

                # Yield both full-run and direct invocation versions
                yield (state, stubs, defaults,
                       f"frontier:{bid}:{direction}->{target_para}")
                yielded += 1

                if yielded < batch_size:
                    yield (state, stubs, defaults,
                           f"direct:{bpara}|frontier:{bid}:{direction}")
                    yielded += 1

    # ------------------------------------------------------------------
    # Harvest round: rainbow table for paragraphs
    # ------------------------------------------------------------------

    def _harvest_round(self, ctx, cov, batch_size, branch_meta) -> Iterator[CaseT]:
        """Run paragraphs with random inputs, record (input→output) pairs,
        then look up inputs that produce desired branch conditions."""
        from .monte_carlo import _run_paragraph_directly
        from .static_analysis import _parse_condition_variables

        sorted_paras = self._paragraphs_with_gaps(branch_meta, cov)
        yielded = 0

        default_state_fn = getattr(ctx.module, "_default_state", None)
        ds = default_state_fn() if default_state_fn else {}
        var_list = list(ds.keys())
        # Fallback pools (used when no domain exists)
        str_vals = ["", " ", "Y", "N", "00", "04", "05", "10",
                    "001", "002", "013", "019", "XX", "I", "T", "R"]
        int_vals = [0, 1, -1, 99, 100, 999, -999, 1000000]
        flag_vals = [True, False, "Y", "N", " ", "X"]

        trials_per = max(200, batch_size // max(len(sorted_paras), 1))

        for para in sorted_paras:
            if yielded >= batch_size:
                break
            _set_target_key_for_paragraph(ctx, para)

            # Collect what we need: uncovered branch conditions in this para
            needs: list[tuple[str, str, list, bool]] = []  # (bkey, var, vals, want_match)
            for bid, meta in branch_meta.items():
                if meta.get("paragraph") != para:
                    continue
                for direction in ("T", "F"):
                    if not _matches_preferred_branch_target(ctx, bid, direction):
                        continue
                    bkey = f"{bid}:{direction}"
                    if bkey in cov.branches_hit:
                        continue
                    cond = meta.get("condition", "")
                    if not cond:
                        continue
                    try:
                        parsed = _parse_condition_variables(cond)
                    except Exception:
                        continue
                    negate = direction == "F"
                    for pvar, vals, neg in parsed:
                        want_match = not (neg ^ negate)
                        needs.append((bkey, pvar, vals, want_match))

            if not needs:
                continue

            # Get base TC for stubs
            tc = self._best_tc_for_para(cov, para)
            base_state = dict(tc.get("input_state", {})) if tc else {}
            stubs = dict(ctx.success_stubs)
            defaults = dict(ctx.success_defaults)
            if tc and tc.get("stub_outcomes"):
                for op, entries in tc["stub_outcomes"]:
                    stubs[op] = [entries] * 50
                    defaults[op] = entries

            cond_vars = self._collect_cond_vars(branch_meta, para, ctx)

            # Phase 1: Run paragraph many times, record final states
            rainbow: list[tuple[dict, dict]] = []  # (input_state, final_state)

            for trial in range(trials_per):
                state = dict(base_state)
                # Random perturbation (domain-aware)
                for var, literals in cond_vars.items():
                    r = ctx.rng.random()
                    if r < 0.4 and literals:
                        state[var] = ctx.rng.choice(literals)
                    elif r < 0.7:
                        dom = ctx.domains.get(var)
                        if dom:
                            strat = ctx.rng.choice(["semantic", "boundary", "random_valid"])
                            state[var] = _generate_domain_value(ctx, var, dom, strat, para)
                        else:
                            info = ctx.var_report.variables.get(var)
                            if info and info.classification == "flag":
                                state[var] = ctx.rng.choice(flag_vals)
                            elif isinstance(ds.get(var), int):
                                state[var] = ctx.rng.choice(int_vals)
                            else:
                                state[var] = ctx.rng.choice(str_vals)
                # Extra perturbation (domain-aware)
                for _ in range(ctx.rng.randint(1, 8)):
                    if not var_list:
                        break
                    v = ctx.rng.choice(var_list)
                    if v not in cond_vars:
                        dom = ctx.domains.get(v)
                        if dom:
                            strat = ctx.rng.choice(["semantic", "boundary", "random_valid"])
                            state[v] = _generate_domain_value(ctx, v, dom, strat, para)
                        else:
                            dv = ds.get(v)
                            if isinstance(dv, int):
                                state[v] = ctx.rng.choice(int_vals)
                            elif isinstance(dv, str):
                                state[v] = ctx.rng.choice(str_vals)

                # Build run state with stubs
                run_state = dict(ds)
                run_state.update(state)
                run_state["_stub_outcomes"] = {
                    k: [list(e) if isinstance(e, list) else e for e in v]
                    for k, v in stubs.items()
                }
                run_state["_stub_defaults"] = dict(defaults)

                try:
                    final = _run_paragraph_directly(ctx.module, para, run_state)
                except Exception:
                    continue
                if final:
                    rainbow.append((state, final))

            if not rainbow:
                continue

            # Phase 2: For each unsatisfied branch, scan rainbow for a match
            for bkey, pvar, vals, want_match in needs:
                if yielded >= batch_size:
                    break
                if bkey in cov.branches_hit:
                    continue

                for input_state, final_state in rainbow:
                    final_val = final_state.get(pvar)
                    if final_val is None:
                        continue

                    match = False
                    if vals:
                        # Check if final value matches/doesn't match condition
                        str_final = str(final_val).strip()
                        for v in vals:
                            if str_final == str(v).strip():
                                match = True
                                break
                            # Numeric comparison
                            try:
                                if float(final_val) == float(v):
                                    match = True
                                    break
                            except (ValueError, TypeError):
                                pass
                    else:
                        # No specific values — truthiness check
                        match = bool(final_val)

                    if match == want_match:
                        yield (input_state, stubs, defaults,
                               f"direct:{para}|harvest:{bkey}")
                        yielded += 1
                        break  # found one for this branch, move on

    # ------------------------------------------------------------------
    # Inverse round: synthesize inverse functions on-the-fly
    # ------------------------------------------------------------------

    def _inverse_round(self, ctx, cov, batch_size, branch_meta) -> Iterator[CaseT]:
        """For each uncovered branch, parse the paragraph source, build a
        symbolic inverse of the computation chain, exec() it, and use the
        result to compute required input values."""
        import inspect
        import re

        from .monte_carlo import _run_paragraph_directly
        from .static_analysis import _parse_condition_variables

        sorted_paras = self._paragraphs_with_gaps(branch_meta, cov)
        yielded = 0

        # Patterns for parsing generated Python
        assign_pat = re.compile(
            r"^\s*state\['([A-Z][A-Z0-9_-]*)'\]\s*=\s*(.*)"
        )
        dep_pat = re.compile(
            r"state\.get\('([A-Z][A-Z0-9_-]*)'|state\['([A-Z][A-Z0-9_-]*)'\]"
        )
        # Arithmetic operators in generated code
        arith_pat = re.compile(
            r"_to_num\(state\.get\('([A-Z][A-Z0-9_-]*)'[^)]*\)\)"
        )

        for para in sorted_paras:
            if yielded >= batch_size:
                break
            _set_target_key_for_paragraph(ctx, para)

            # Get paragraph source
            func_name = "para_" + re.sub(
                r"_+", "_", para.replace("-", "_")
            ).strip("_")
            para_func = getattr(ctx.module, func_name, None)
            if not para_func:
                continue
            try:
                src = inspect.getsource(para_func)
            except (OSError, TypeError):
                continue

            lines = src.split("\n")

            # Parse all assignments: (line_idx, target_var, expr, dep_vars)
            assignments: list[tuple[int, str, str, list[str]]] = []
            for i, line in enumerate(lines):
                m = assign_pat.match(line)
                if m:
                    target = m.group(1)
                    expr = m.group(2)
                    deps = [g1 or g2 for g1, g2 in dep_pat.findall(expr)]
                    assignments.append((i, target, expr, deps))

            if not assignments:
                continue

            # Get best TC for stubs
            tc = self._best_tc_for_para(cov, para)
            base_state = dict(tc.get("input_state", {})) if tc else {}
            stubs = dict(ctx.success_stubs)
            defaults = dict(ctx.success_defaults)
            if tc and tc.get("stub_outcomes"):
                for op, entries in tc["stub_outcomes"]:
                    stubs[op] = [entries] * 50
                    defaults[op] = entries

            # For each uncovered branch in this paragraph
            for bid, meta in branch_meta.items():
                if meta.get("paragraph") != para:
                    continue
                for direction in ("T", "F"):
                    bkey = f"{bid}:{direction}"
                    if bkey in cov.branches_hit:
                        continue
                    _set_target_key_for_branch(
                        ctx,
                        bid,
                        direction,
                        paragraph_fallback=para,
                    )
                    if yielded >= batch_size:
                        break

                    condition = meta.get("condition", "")
                    if not condition:
                        continue
                    try:
                        parsed = _parse_condition_variables(condition)
                    except Exception:
                        continue

                    negate = direction == "F"

                    for pvar, vals, neg in parsed:
                        want_match = not (neg ^ negate)

                        # Build inverse: walk backward from pvar through
                        # assignments, collecting the computation chain
                        chain: list[tuple[str, str, list[str]]] = []
                        frontier = {pvar}
                        seen: set[str] = set()

                        for depth in range(5):
                            if not frontier:
                                break
                            next_frontier: set[str] = set()
                            for var in frontier:
                                if var in seen:
                                    continue
                                seen.add(var)
                                # Find last assignment to var
                                last = None
                                for _, tvar, expr, deps in assignments:
                                    if tvar == var:
                                        last = (tvar, expr, deps)
                                if last:
                                    chain.append(last)
                                    for dep in last[2]:
                                        if dep not in seen and dep != "__STUB__":
                                            next_frontier.add(dep)
                            frontier = next_frontier

                        if not chain:
                            continue

                        # Identify leaf variables (inputs — not assigned in
                        # this paragraph)
                        assigned_vars = {tvar for _, tvar, _, _ in assignments}
                        leaf_vars = set()
                        for _, _, deps in chain:
                            for d in deps:
                                if d not in assigned_vars and d != "__STUB__":
                                    leaf_vars.add(d)

                        if not leaf_vars:
                            continue

                        # Build an inverse solver function as Python code.
                        # Strategy: for the target value, try to satisfy
                        # the chain by setting leaf vars to make arithmetic
                        # work out.
                        #
                        # Generate: given target_val, compute what each leaf
                        # var should be by inverting one step at a time.
                        solver_lines = [
                            "def _solve(target_val, base):",
                            "    result = dict(base)",
                        ]

                        # Walk chain from condition var toward leaves
                        first_var, first_expr, first_deps = chain[0]

                        # Detect expression type and generate inverse
                        operands = arith_pat.findall(first_expr)
                        if " * " in first_expr and operands:
                            # A * B = target → set each operand to sqrt(|target|)+1
                            for op in operands:
                                solver_lines.append(
                                    f"    result['{op}'] = "
                                    f"max(1, int(abs(target_val) ** 0.5) + 1)"
                                )
                        elif " + " in first_expr and operands:
                            # A + B = target → set first to target, rest to 0
                            if operands:
                                solver_lines.append(
                                    f"    result['{operands[0]}'] = target_val"
                                )
                                for op in operands[1:]:
                                    solver_lines.append(
                                        f"    result['{op}'] = 0"
                                    )
                        elif " - " in first_expr and len(operands) >= 2:
                            # A - B = target → set A = target + 100, B = 100
                            solver_lines.append(
                                f"    result['{operands[0]}'] = "
                                f"int(target_val) + 100"
                            )
                            solver_lines.append(
                                f"    result['{operands[1]}'] = 100"
                            )
                        elif " / " in first_expr and operands:
                            # A / B = target → set A = target * 100, B = 100
                            if operands:
                                solver_lines.append(
                                    f"    result['{operands[0]}'] = "
                                    f"int(target_val) * 100"
                                )
                                if len(operands) > 1:
                                    solver_lines.append(
                                        f"    result['{operands[1]}'] = 100"
                                    )
                        elif " % " in first_expr and operands:
                            # A % B = target → set A = target (mod identity)
                            mod_m = re.search(r'%\s*\(?(\d+)', first_expr)
                            mod_val = int(mod_m.group(1)) if mod_m else 4
                            solver_lines.append(
                                f"    result['{operands[0]}'] = "
                                f"int(target_val) + {mod_val} * 500"
                            )
                        elif "state.get('" in first_expr:
                            # Simple MOVE: state['X'] = state.get('Y', '')
                            # → set Y to target
                            copy_m = re.match(
                                r"state\.get\('([A-Z][A-Z0-9_-]*)'", first_expr
                            )
                            if copy_m:
                                solver_lines.append(
                                    f"    result['{copy_m.group(1)}'] = target_val"
                                )
                        else:
                            # Can't invert — set leaf vars to non-zero
                            for lv in leaf_vars:
                                solver_lines.append(
                                    f"    result['{lv}'] = target_val"
                                )

                        solver_lines.append("    return result")
                        solver_code = "\n".join(solver_lines)

                        # Compile and execute the solver
                        try:
                            ns: dict = {}
                            exec(compile(solver_code, f"<inverse:{para}:{bid}>", "exec"), ns)
                            solve_fn = ns["_solve"]
                        except Exception:
                            continue

                        # Determine target values to try
                        targets_to_try: list = []
                        if want_match and vals:
                            targets_to_try.extend(vals)
                        elif not want_match and vals:
                            # Need NOT to match — try values far from condition
                            for v in vals:
                                if isinstance(v, (int, float)):
                                    targets_to_try.extend([v + 99999, 0, -v])
                                else:
                                    targets_to_try.extend(["__NOMATCH__", "XX", ""])
                        if not targets_to_try:
                            targets_to_try = [0, 1, 100, -1, "00", "XX"]

                        for tv in targets_to_try[:5]:
                            if yielded >= batch_size:
                                break
                            try:
                                solved = solve_fn(tv, base_state)
                            except Exception:
                                continue

                            yield (solved, stubs, defaults,
                                   f"direct:{para}|inv:{bid}:{direction}:{tv}")
                            yielded += 1

                        break  # found chain for this branch

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Chain constraint round: solve EVALUATE/if-elif chains
    # ------------------------------------------------------------------

    def _chain_constraint_round(self, ctx, cov, batch_size, branch_meta) -> Iterator[CaseT]:
        """For uncovered branches inside if/elif chains, compute the compound
        state needed by negating all prior conditions in the chain.

        This handles cases like EVALUATE TRUE with multiple WHEN clauses
        where reaching the Nth clause requires all N-1 prior clauses to be false.
        """
        if ctx.module is None:
            return

        from .cobol_coverage import _MQ_CONSTANTS
        from .monte_carlo import _run_paragraph_directly

        default_state_fn = getattr(ctx.module, "_default_state", None)
        ds = default_state_fn() if default_state_fn else {}
        source = ""
        module_file = getattr(ctx.module, "__file__", None)
        if module_file:
            try:
                source = open(module_file).read()
            except OSError:
                return

        yielded = 0
        # Find EVALUATE-type branches that are uncovered
        eval_groups: dict[str, list[tuple[int, str, dict]]] = {}
        for bid, meta in branch_meta.items():
            if meta.get("type") != "EVALUATE":
                continue
            para = meta.get("paragraph", "")
            eval_groups.setdefault(para, []).append((bid, "T", meta))

        for para, branches in eval_groups.items():
            _set_target_key_for_paragraph(ctx, para)
            # Find uncovered T-direction branches in this EVALUATE
            uncovered_bids = []
            covered_bids = []
            for bid, direction, meta in branches:
                bkey = f"{bid}:{direction}"
                if bkey not in cov.branches_hit:
                    uncovered_bids.append((bid, meta))
                else:
                    covered_bids.append((bid, meta))

            if not uncovered_bids:
                continue

            # For each uncovered WHEN, build state where:
            # - All prior WHEN conditions are False
            # - The target WHEN condition is True
            # - Any gating conditions above the EVALUATE are satisfied
            for target_bid, target_meta in uncovered_bids:
                if yielded >= batch_size:
                    return
                if not _matches_preferred_branch_target(ctx, target_bid, "T"):
                    continue
                _set_target_key_for_branch(
                    ctx,
                    target_bid,
                    "T",
                    paragraph_fallback=para,
                )

                cond = target_meta.get("condition", "")
                state = dict(ds)

                # Set the target condition variable to True
                cond_var = cond.strip().upper()
                if cond_var and cond_var != "OTHER":
                    state[cond_var] = True

                # Negate all prior WHEN conditions (lower bid = earlier in chain)
                for prior_bid, _, prior_meta in branches:
                    if prior_bid >= target_bid:
                        continue
                    prior_cond = prior_meta.get("condition", "").strip().upper()
                    if prior_cond and prior_cond != "OTHER":
                        # Handle compound OR conditions
                        for part in prior_cond.split(" OR "):
                            part = part.strip()
                            if part:
                                state[part] = False

                # Set up gating: the EVALUATE is inside an IF block
                # that checks AUTH-RESP-DECLINED, DECLINE-AUTH, etc.
                # Use branch_meta to find the enclosing IF conditions
                for gating_bid, gating_meta in branch_meta.items():
                    if (gating_meta.get("paragraph") == para
                            and gating_meta.get("type") == "IF"):
                        gating_cond = gating_meta.get("condition", "").strip().upper()
                        if gating_cond:
                            # If this gating branch is covered in T direction,
                            # the condition must be true to reach the EVALUATE
                            gating_bkey = f"{gating_bid}:T"
                            if gating_bkey in cov.branches_hit:
                                state[gating_cond] = True

                # Inject MQ constants
                for name, value in _MQ_CONSTANTS.items():
                    if name.upper() in ds:
                        state[name.upper()] = value

                # Ensure stub outcomes are available
                stubs = dict(ctx.success_stubs)
                defaults = dict(ctx.success_defaults)

                yield (state, stubs, defaults,
                       f"direct:{para}|chain:{target_bid}")
                yielded += 1

                # Also try with perturbations
                for trial in range(min(5, batch_size - yielded)):
                    perturbed = dict(state)
                    # Randomly flip a few non-critical variables
                    for var in list(ds.keys())[:20]:
                        if var not in state and ctx.rng.random() < 0.2:
                            dom = ctx.domains.get(var)
                            if dom and dom.condition_literals:
                                perturbed[var] = ctx.rng.choice(dom.condition_literals)
                    yield (perturbed, stubs, defaults,
                           f"direct:{para}|chain-perturb:{target_bid}:{trial}")
                    yielded += 1

        # Also handle IF branches with compound state requirements
        # (e.g., loop counters, pre-loaded flags)
        for bid, meta in branch_meta.items():
            if yielded >= batch_size:
                return
            if meta.get("type") != "IF":
                continue
            para = meta.get("paragraph", "")
            _set_target_key_for_paragraph(ctx, para)
            for direction in ("T", "F"):
                if not _matches_preferred_branch_target(ctx, bid, direction):
                    continue
                bkey = f"{bid}:{direction}"
                if bkey in cov.branches_hit:
                    continue
                _set_target_key_for_branch(
                    ctx,
                    bid,
                    direction,
                    paragraph_fallback=para,
                )
                cond = meta.get("condition", "").strip()
                if not cond:
                    continue

                state = dict(ds)
                # Parse comparison: VAR > VAR2 or VAR = LITERAL
                import re
                m = re.match(r"([A-Z0-9-]+)\s*(>|<|=|NOT\s*=|>=|<=)\s*(.+)", cond, re.I)
                if m:
                    lhs = m.group(1).strip().upper()
                    op = m.group(2).strip().upper()
                    rhs = m.group(3).strip().upper()

                    if direction == "T":
                        # Make the condition true
                        if ">" in op and "=" not in op:
                            state[lhs] = 999999
                            if rhs in ds:
                                state[rhs] = 0
                        elif "NOT" in op:
                            state[lhs] = "MISMATCH"
                        elif "=" in op:
                            if rhs in ds:
                                state[lhs] = state.get(rhs, 0)
                            else:
                                try:
                                    state[lhs] = int(rhs)
                                except ValueError:
                                    state[lhs] = rhs
                    else:
                        # Make the condition false
                        if ">" in op and "=" not in op:
                            state[lhs] = 0
                            if rhs in ds:
                                state[rhs] = 999999
                        elif "NOT" in op:
                            if rhs in ds:
                                state[lhs] = state.get(rhs, 0)
                        elif "=" in op:
                            state[lhs] = "MISMATCH_VALUE"

                # Inject MQ constants
                for name, value in _MQ_CONSTANTS.items():
                    if name.upper() in ds:
                        state[name.upper()] = value

                stubs = dict(ctx.success_stubs)
                defaults = dict(ctx.success_defaults)
                yield (state, stubs, defaults,
                       f"direct:{para}|chain-if:{bid}:{direction}")
                yielded += 1

    # ------------------------------------------------------------------
    # Main: rotate param → stub → dataflow → frontier → harvest → inverse → chain
    # ------------------------------------------------------------------

    def generate_cases(self, ctx, cov, batch_size) -> Iterator[CaseT]:
        branch_meta = ctx.branch_meta
        if not branch_meta:
            return

        prev_target_key = ctx.current_target_key

        try:
            n_phases = 7
            phase = self._round % n_phases
            # Run chain constraint solver on first round (phase 0) to hit
            # compound-state branches early, then rotate normally
            if self._round == 0:
                yield from self._chain_constraint_round(ctx, cov, batch_size, branch_meta)
            elif phase == 0:
                yield from self._param_round(ctx, cov, batch_size, branch_meta)
            elif phase == 1:
                if ctx.stub_mapping:
                    yield from self._stub_round(ctx, cov, batch_size, branch_meta)
                else:
                    yield from self._param_round(ctx, cov, batch_size, branch_meta)
            elif phase == 2:
                yield from self._dataflow_round(ctx, cov, batch_size, branch_meta)
            elif phase == 3:
                yield from self._frontier_round(ctx, cov, batch_size, branch_meta)
            elif phase == 4:
                yield from self._harvest_round(ctx, cov, batch_size, branch_meta)
            elif phase == 5:
                yield from self._inverse_round(ctx, cov, batch_size, branch_meta)
            elif phase == 6:
                yield from self._chain_constraint_round(ctx, cov, batch_size, branch_meta)
            else:
                yield from self._param_round(ctx, cov, batch_size, branch_meta)

            self._round += 1
        finally:
            ctx.current_target_key = prev_target_key


class FaultInjectionStrategy(Strategy):
    """Layer 4: Stub fault injection."""

    name = "fault_injection"
    priority = 50

    def __init__(self):
        self._ran = False

    def should_run(self, cov, round_num: int) -> bool:
        return bool(cov._stub_mapping) and not self._ran

    def generate_cases(self, ctx, cov, batch_size) -> Iterator[CaseT]:
        from .cobol_coverage import _build_fault_stubs, _build_input_state

        prev_target_key = ctx.current_target_key
        ctx.current_target_key = None

        fault_tables = {
            "status_file": ["10", "23", "35", "39", "46", "47"],
            "status_sql": [0, 100, -803, -805, -904],
            "status_cics": [0, 12, 13, 16, 22, 27],
        }

        # Get 88-level sibling info from context (set by coverage runner)
        flag_88_added = getattr(ctx, 'flag_88_added', None) or set()
        siblings_88 = getattr(ctx, 'siblings_88', None) or {}

        try:
            for op_key, status_vars in ctx.stub_mapping.items():
                fault_values: list = []
                for var in status_vars:
                    dom = ctx.domains.get(var)
                    if dom:
                        table = fault_tables.get(dom.semantic_type, [])
                        fault_values.extend(table)

                if op_key.startswith("DLI") or any("PCB" in v.upper() for v in status_vars):
                    fault_values.extend(["GE", "GB", "II", "AI"])

                if op_key.startswith("CALL:MQ"):
                    fault_values.extend([0, 1, 2])  # MQCC-OK, WARNING, FAILED (int)

                if not fault_values:
                    fault_values = ["10", "23", "35"]

                for fv in fault_values[:5]:
                    base = _build_input_state(
                        ctx.domains,
                        "semantic",
                        ctx.rng,
                        jit_inference=ctx.jit_inference,
                        paragraph_comments=ctx.paragraph_comments,
                    )
                    fault_stubs, fault_defaults = _build_fault_stubs(
                        ctx.stub_mapping, ctx.domains,
                        target_op=op_key, fault_value=fv, rng=ctx.rng,
                        flag_88_added=flag_88_added, siblings_88=siblings_88,
                    )
                    yield base, fault_stubs, fault_defaults, f"fault:{op_key}={fv}"

                # Also try 88-level flag faults: activate each sibling flag
                for var in status_vars:
                    var_upper = var.upper()
                    if var_upper in flag_88_added:
                        base = _build_input_state(
                            ctx.domains,
                            "semantic",
                            ctx.rng,
                            jit_inference=ctx.jit_inference,
                            paragraph_comments=ctx.paragraph_comments,
                        )
                        fault_stubs, fault_defaults = _build_fault_stubs(
                            ctx.stub_mapping, ctx.domains,
                            target_op=op_key, fault_value=var_upper, rng=ctx.rng,
                            flag_88_added=flag_88_added, siblings_88=siblings_88,
                        )
                        yield base, fault_stubs, fault_defaults, f"fault-88:{op_key}={var}"

            self._ran = True
        finally:
            ctx.current_target_key = prev_target_key


class TranscriptSearchStrategy(Strategy):
    """Mutate ordered READ transcripts with domain-aware payload assignments."""

    name = "transcript_search"
    priority = 40

    def __init__(self):
        self._ran = False

    def should_run(self, cov, round_num: int) -> bool:
        return not self._ran

    def generate_cases(self, ctx, cov, batch_size) -> Iterator[CaseT]:
        from .cobol_coverage import _build_input_state

        self._ran = True
        yielded = 0
        payload_candidates = getattr(ctx, "payload_candidates", {}) or {}
        prev_target_key = ctx.current_target_key
        ctx.current_target_key = None

        try:
            for op_key, var_map in payload_candidates.items():
                if yielded >= batch_size:
                    break
                if not op_key.startswith("READ:"):
                    continue
                if op_key not in ctx.success_stubs:
                    continue

                for var_name, candidates in var_map.items():
                    if yielded >= batch_size:
                        break

                    domain = ctx.domains.get(var_name)
                    values = list(candidates) if candidates else []
                    if not values and domain is not None:
                        values = build_payload_value_candidates(domain, rng=ctx.rng)

                    for raw_value in values[:4]:
                        if yielded >= batch_size:
                            break

                        state = _build_input_state(
                            ctx.domains,
                            "semantic",
                            ctx.rng,
                            jit_inference=ctx.jit_inference,
                            paragraph_comments=ctx.paragraph_comments,
                        )
                        encoded_value = (
                            format_value_for_cobol(domain, raw_value)
                            if domain is not None else raw_value
                        )

                        stubs = {
                            name: [list(entry) for entry in entries]
                            for name, entries in ctx.success_stubs.items()
                        }
                        defaults = {
                            name: list(entry) if isinstance(entry, list) else entry
                            for name, entry in ctx.success_defaults.items()
                        }

                        mutated_entries: list[list] = []
                        for idx, entry in enumerate(stubs.get(op_key, [])):
                            current = list(entry)
                            if idx < 2 and not any(name == var_name for name, _ in current):
                                current.append((var_name, encoded_value))
                            mutated_entries.append(current)

                        if not mutated_entries:
                            mutated_entries = [[(var_name, encoded_value)]]
                        elif not any(
                            any(name == var_name for name, _ in entry)
                            for entry in mutated_entries[:2]
                        ):
                            mutated_entries[0].append((var_name, encoded_value))

                        stubs[op_key] = mutated_entries
                        yield (
                            state,
                            stubs,
                            defaults,
                            f"transcript:{op_key}:{var_name}={encoded_value}",
                        )
                        yielded += 1
        finally:
            ctx.current_target_key = prev_target_key


class CorpusFuzzStrategy(Strategy):
    """Coverage-guided fuzzing with energy-based corpus scheduling.

    AFL-inspired strategy that maintains a deduplicated corpus of test cases
    selected for branch-coverage uniqueness.  Seeds are chosen via an
    energy-based power schedule that favours TCs covering rare branches
    and penalises over-mutated entries.

    Mutations are 60% targeted (condition variables of uncovered branches)
    and 40% random, with 40% stub mutation probability.
    """

    name = "corpus_fuzz"
    priority = 45  # between direct_paragraph (35) and fault_injection (50)

    def __init__(self):
        self._corpus: list[dict] = []
        self._energy: list[float] = []
        self._mutations_done: list[int] = []
        self._branch_rarity: dict[str, int] = {}
        self._initialized = False

    def should_run(self, cov, round_num: int) -> bool:
        return len(cov.test_cases) >= 3

    def _initialize_corpus(self, cov, ctx):
        """Build corpus via greedy set cover, compute rarity-weighted energy."""
        self._initialized = True
        self._corpus = []
        self._energy = []
        self._mutations_done = []
        self._branch_rarity = {}

        for tc in cov.test_cases:
            for b in tc.get("branches_hit", []):
                self._branch_rarity[b] = self._branch_rarity.get(b, 0) + 1

        covered_by_corpus: set[str] = set()
        scored = []
        for i, tc in enumerate(cov.test_cases):
            branches = set(tc.get("branches_hit", []))
            unique = branches - covered_by_corpus
            scored.append((len(unique), i, tc, branches))

        scored.sort(key=lambda x: x[0], reverse=True)

        for _, _, tc, branches in scored:
            unique = branches - covered_by_corpus
            if not unique and len(self._corpus) >= 10:
                continue
            covered_by_corpus.update(branches)
            self._corpus.append(tc)
            energy = sum(
                1.0 / max(self._branch_rarity.get(b, 1), 1)
                for b in branches
            )
            self._energy.append(energy)
            self._mutations_done.append(0)
            if len(self._corpus) >= 100:
                break

    def _select_seed(self, rng) -> tuple[int, dict]:
        """Select seed TC using energy-weighted power schedule."""
        if not self._corpus:
            return 0, {}

        import math
        weights = []
        for i in range(len(self._corpus)):
            e = self._energy[i]
            m = self._mutations_done[i]
            decay = 1.0 / (1.0 + math.log2(max(m, 1)))
            weights.append(max(e * decay, 0.01))

        total = sum(weights)
        if total <= 0:
            idx = rng.randint(0, len(self._corpus) - 1)
        else:
            r = rng.random() * total
            cumulative = 0.0
            idx = 0
            for i, w in enumerate(weights):
                cumulative += w
                if cumulative >= r:
                    idx = i
                    break

        return idx, self._corpus[idx]

    def generate_cases(self, ctx, cov, batch_size) -> Iterator[CaseT]:
        from .cobol_coverage import _build_fault_stubs

        prev_target_key = ctx.current_target_key
        ctx.current_target_key = None

        try:
            if not self._initialized or len(cov.test_cases) > len(self._corpus) * 2:
                self._initialize_corpus(cov, ctx)

            if not self._corpus:
                return

            input_vars = [
                name for name, dom in ctx.domains.items()
                if dom.classification in ("input", "flag") and not dom.set_by_stub
            ]
            if not input_vars:
                return

            # v1: simple uncovered-branch list (no difficulty scoring)
            easy_branches = [
                (f"{bid}:{d}", 0)
                for bid in ctx.branch_meta
                for d in ("T", "F")
                if f"{bid}:{d}" not in cov.branches_hit
            ]

            # Collect condition variables from uncovered branches
            priority_vars: dict[str, list] = {}
            for bkey, _ in easy_branches[:20]:
                bid_str = bkey.split(":")[0]
                try:
                    bid = int(bid_str)
                except ValueError:
                    continue
                meta = ctx.branch_meta.get(bid, {})
                cond = meta.get("condition", "")
                if cond:
                    for var_name in set(re.findall(r"\b([A-Z][A-Z0-9_-]+)\b", cond)):
                        if var_name in ctx.domains and var_name not in priority_vars:
                            dom = ctx.domains[var_name]
                            vals = list(dom.condition_literals or [])
                            priority_vars[var_name] = vals

            for iteration in range(batch_size):
                idx, seed_tc = self._select_seed(ctx.rng)
                self._mutations_done[idx] = self._mutations_done[idx] + 1

                base_state = dict(seed_tc.get("input_state", {}))
                mutated = dict(base_state)

                n_mutations = ctx.rng.randint(1, min(5, len(input_vars)))

                # 60% targeted: mutate priority variables
                if ctx.rng.random() < 0.6 and priority_vars:
                    vars_to_mutate = ctx.rng.sample(
                        list(priority_vars.keys()),
                        min(n_mutations, len(priority_vars)),
                    )
                    for var_name in vars_to_mutate:
                        dom = ctx.domains.get(var_name)
                        if not dom:
                            continue
                        vals = priority_vars[var_name]
                        if ctx.rng.random() < 0.5 and vals:
                            mutated[var_name] = format_value_for_cobol(dom, ctx.rng.choice(vals))
                        else:
                            strat = ctx.rng.choice(["boundary", "random_valid", "condition_literal"])
                            mutated[var_name] = format_value_for_cobol(
                                dom, generate_value(dom, strat, ctx.rng),
                            )
                else:
                    # 40% random mutation
                    vars_to_mutate = ctx.rng.sample(
                        input_vars, min(n_mutations, len(input_vars)),
                    )
                    for var_name in vars_to_mutate:
                        dom = ctx.domains.get(var_name)
                        if not dom:
                            continue
                        if ctx.rng.random() < 0.7 and (dom.condition_literals or dom.valid_88_values):
                            strat = "condition_literal" if dom.condition_literals else "88_value"
                        else:
                            strat = "random_valid"
                        mutated[var_name] = format_value_for_cobol(
                            dom, generate_value(dom, strat, ctx.rng),
                        )

                # Stub mutation: 40% chance
                if ctx.rng.random() < 0.4 and ctx.stub_mapping:
                    op_key = ctx.rng.choice(list(ctx.stub_mapping.keys()))
                    stubs, defaults = _build_fault_stubs(
                        ctx.stub_mapping, ctx.domains,
                        target_op=op_key, rng=ctx.rng,
                    )
                else:
                    # Inherit stubs from seed TC
                    stubs = dict(ctx.success_stubs)
                    defaults = dict(ctx.success_defaults)
                    if seed_tc.get("stub_outcomes"):
                        for entry in seed_tc["stub_outcomes"]:
                            if isinstance(entry, (list, tuple)) and len(entry) == 2:
                                op, entries = entry
                                stubs[op] = [entries] * 50
                                defaults[op] = entries

                yield mutated, stubs, defaults, f"fuzz:{idx}"
        finally:
            ctx.current_target_key = prev_target_key


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _convert_llm_state(lts, ctx: StrategyContext) -> dict:
    """Convert an LLMTestState to the input_state format."""
    input_state = {}
    for var, val in lts.input_values.items():
        dom = ctx.domains.get(var.upper())
        if dom:
            input_state[var.upper()] = format_value_for_cobol(dom, val)
        else:
            input_state[var.upper()] = str(val)
    return input_state


def _apply_llm_stub_overrides(
    lts,
    success_stubs: dict[str, list],
    success_defaults: dict[str, list],
    stub_mapping: dict[str, list[str]],
) -> tuple[dict[str, list], dict[str, list]]:
    """Build stubs from success + LLM overrides."""
    from .cobol_coverage import _match_stub_operation

    stubs = {k: list(v) for k, v in success_stubs.items()}
    defaults = dict(success_defaults)

    for op_key, status_val in lts.stub_overrides.items():
        matched_op = _match_stub_operation(op_key, stub_mapping)
        if matched_op:
            status_vars = stub_mapping[matched_op]
            entry = [(sv, status_val) for sv in status_vars]
            stubs[matched_op] = [entry] * 50
            defaults[matched_op] = entry

    return stubs, defaults


# ---------------------------------------------------------------------------
# Strategy selectors
# ---------------------------------------------------------------------------

class StrategySelector(ABC):
    """Base class for strategy selectors."""

    @abstractmethod
    def select(
        self,
        strategies: list[Strategy],
        cov: "CoverageState",
        round_num: int,
    ) -> tuple[Strategy, int]:
        """Pick the next strategy and batch size."""
        ...


class HeuristicSelector(StrategySelector):
    """Priority-queue with yield-based re-ranking.

    score = priority - yield_bonus + staleness_penalty
    """

    def __init__(self, default_batch_size: int = 200):
        self.default_batch_size = default_batch_size

    def select(self, strategies, cov, round_num):
        eligible = [s for s in strategies if s.should_run(cov, round_num)]
        if not eligible:
            eligible = [s for s in strategies if s.name == "direct_paragraph"]
            if not eligible:
                eligible = strategies[:1]

        best = min(eligible, key=lambda s: self._score(s, cov, round_num))
        batch_size = self._compute_batch_size(best, cov)
        log.debug("Selector picked %s (score=%.1f, batch=%d)",
                  best.name, self._score(best, cov, round_num), batch_size)
        return best, batch_size

    def _score(self, strategy: Strategy, cov, round_num: int) -> float:
        """Lower is better."""
        score = float(strategy.priority)

        yields = cov.strategy_yields.get(strategy.name)
        if yields and yields.rounds > 0:
            hit_rate = yields.total_new_coverage / max(yields.total_cases, 1)
            score -= hit_rate * 30

            rounds_since_yield = round_num - yields.last_yield_round
            if rounds_since_yield > 3:
                score += rounds_since_yield * 5

        return score

    def _compute_batch_size(self, strategy: Strategy, cov) -> int:
        if strategy.name in ("baseline",):
            return 500
        if strategy.name == "direct_paragraph":
            return min(self.default_batch_size * 25, 5000)
        if strategy.name == "corpus_fuzz":
            return min(self.default_batch_size * 5, 2000)
        return self.default_batch_size
