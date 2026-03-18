"""Pluggable coverage strategies for the agentic coverage loop.

Each strategy is a generator that yields (input_state, stubs, defaults, target)
tuples.  The agentic loop in cobol_coverage.py handles execution and saving.
"""

from __future__ import annotations

import logging
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional, Tuple

from .cobol_executor import CobolExecutionContext
from .models import Program
from .static_analysis import StaticCallGraph, compute_path_constraints
from .variable_domain import (
    VariableDomain,
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


@dataclass
class StrategyYield:
    """Tracks yield per strategy across rounds."""

    total_cases: int = 0
    total_new_coverage: int = 0
    rounds: int = 0
    last_yield_round: int = 0


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

class LLMSeedStrategy(Strategy):
    """Layer 0: LLM-generated test states (initial seed)."""

    name = "llm_seed"
    priority = 10
    requires_llm = True

    def __init__(self, llm_provider, llm_model: str | None = None):
        self.llm_provider = llm_provider
        self.llm_model = llm_model
        self._ran = False

    def should_run(self, cov, round_num: int) -> bool:
        return not self._ran

    def generate_cases(self, ctx, cov, batch_size) -> Iterator[CaseT]:
        self._ran = True

        from .cobol_coverage import _match_stub_operation
        from .llm_test_states import generate_llm_test_states

        if ctx.cobol_source_path is None:
            return

        llm_cache = ctx.store_path.with_name(ctx.store_path.stem + "_llm_states.json")
        llm_states = generate_llm_test_states(
            self.llm_provider,
            ctx.cobol_source_path,
            ctx.program,
            ctx.var_report, ctx.stub_mapping, ctx.domains,
            llm_cache,
            call_graph=ctx.call_graph, gating_conds=ctx.gating_conds,
            model=self.llm_model,
        )
        if not llm_states:
            return

        log.info("LLM seed: %d test states", len(llm_states))
        for lts in llm_states:
            input_state = _convert_llm_state(lts, ctx)
            stubs, defaults = _apply_llm_stub_overrides(
                lts, ctx.success_stubs, ctx.success_defaults,
                ctx.stub_mapping,
            )
            yield input_state, stubs, defaults, f"llm:{lts.target_description[:40]}"


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

        # Phase 1: one case per value-generation strategy
        strategies = ["condition_literal", "semantic", "random_valid", "88_value", "boundary"]
        for strat in strategies:
            input_state = _build_input_state(ctx.domains, strat, ctx.rng)
            yield input_state, ctx.success_stubs, ctx.success_defaults, "baseline"

        # Phase 2: condition_literal values per input variable
        for name, dom in ctx.domains.items():
            if dom.condition_literals and dom.classification == "input":
                for lit in dom.condition_literals[:3]:
                    base = _build_input_state(ctx.domains, "semantic", ctx.rng)
                    base[name] = format_value_for_cobol(dom, lit)
                    yield base, ctx.success_stubs, ctx.success_defaults, f"lit:{name}"


class LLMGapStrategy(Strategy):
    """Layer 0b: LLM re-query targeting coverage gaps."""

    name = "llm_gap"
    priority = 25
    requires_llm = True

    def __init__(self, llm_provider, llm_model: str | None = None):
        self.llm_provider = llm_provider
        self.llm_model = llm_model
        self._ran = False

    def should_run(self, cov, round_num: int) -> bool:
        if self._ran:
            return False
        uncovered = cov.all_paragraphs - cov.paragraphs_hit
        return len(uncovered) > 0

    def generate_cases(self, ctx, cov, batch_size) -> Iterator[CaseT]:
        self._ran = True

        from .llm_test_states import generate_llm_test_states

        if ctx.cobol_source_path is None:
            return

        llm_cache = ctx.store_path.with_name(ctx.store_path.stem + "_llm_states.json")
        gap_states = generate_llm_test_states(
            self.llm_provider,
            ctx.cobol_source_path,
            ctx.program,
            ctx.var_report, ctx.stub_mapping, ctx.domains,
            llm_cache,
            call_graph=ctx.call_graph, gating_conds=ctx.gating_conds,
            model=self.llm_model,
            covered_paragraphs=cov.paragraphs_hit,
            covered_branches=cov.branches_hit,
        )
        if not gap_states:
            return

        log.info("LLM gap: %d gap-targeted states", len(gap_states))
        for lts in gap_states:
            input_state = _convert_llm_state(lts, ctx)
            stubs, defaults = _apply_llm_stub_overrides(
                lts, ctx.success_stubs, ctx.success_defaults,
                ctx.stub_mapping,
            )
            yield input_state, stubs, defaults, f"llm-gap:{lts.target_description[:36]}"


class IntentDrivenStrategy(Strategy):
    """NEW: Generate realistic business-scenario test data via LLM."""

    name = "intent_driven"
    priority = 15
    requires_llm = True

    def __init__(self, llm_provider, llm_model: str | None = None):
        self.llm_provider = llm_provider
        self.llm_model = llm_model
        self._ran = False

    def should_run(self, cov, round_num: int) -> bool:
        return not self._ran

    def generate_cases(self, ctx, cov, batch_size) -> Iterator[CaseT]:
        self._ran = True

        if ctx.cobol_source_path is None:
            return

        scenarios = self._generate_scenarios(ctx)
        if not scenarios:
            return

        log.info("Intent-driven: %d business scenarios", len(scenarios))
        for scenario in scenarios:
            input_state = _convert_llm_state(scenario, ctx)
            stubs, defaults = _apply_llm_stub_overrides(
                scenario, ctx.success_stubs, ctx.success_defaults,
                ctx.stub_mapping,
            )
            yield input_state, stubs, defaults, f"intent:{scenario.target_description[:36]}"

    def _generate_scenarios(self, ctx: StrategyContext):
        from .llm_coverage import _query_llm_sync
        from .llm_test_states import (
            LLMTestState,
            extract_flow_summary,
            extract_paragraph_comments,
            parse_test_states,
        )

        cobol_text = ctx.cobol_source_path.read_text(errors="replace")
        source_lines = cobol_text.splitlines()

        comments = extract_paragraph_comments(ctx.program, source_lines)
        flow_summary = extract_flow_summary(
            ctx.program, ctx.call_graph, ctx.stub_mapping,
            ctx.gating_conds,
        )

        prompt = _build_intent_prompt(
            ctx.program.program_id, comments, flow_summary,
            ctx.var_report, ctx.stub_mapping, ctx.domains,
        )

        try:
            response_text, tokens = _query_llm_sync(
                self.llm_provider, prompt, self.llm_model,
            )
            log.info("Intent LLM response: %d chars, %d tokens",
                     len(response_text), tokens)
            return parse_test_states(response_text)
        except Exception as e:
            log.warning("Intent-driven LLM query failed: %s", e)
            return []


class ConstraintSolverStrategy(Strategy):
    """Layer 2: Path-constraint satisfaction for uncovered paragraphs."""

    name = "constraint_solver"
    priority = 30

    def should_run(self, cov, round_num: int) -> bool:
        return len(cov.all_paragraphs - cov.paragraphs_hit) > 0

    def generate_cases(self, ctx, cov, batch_size) -> Iterator[CaseT]:
        from .cobol_coverage import _build_input_state

        uncovered = cov.all_paragraphs - cov.paragraphs_hit
        for target_para in sorted(uncovered):
            constraints = compute_path_constraints(
                target_para, ctx.call_graph, ctx.gating_conds,
            )
            if constraints is None:
                continue

            for variation in range(6):
                base = _build_input_state(ctx.domains, "semantic", ctx.rng)

                for gc in constraints.constraints:
                    dom = ctx.domains.get(gc.variable)
                    if dom and gc.values:
                        if gc.negated:
                            val = generate_value(dom, "random_valid", ctx.rng)
                            attempts = 0
                            while val in gc.values and attempts < 10:
                                val = generate_value(dom, "random_valid", ctx.rng)
                                attempts += 1
                        else:
                            if variation < len(gc.values):
                                val = gc.values[variation]
                            else:
                                val = ctx.rng.choice(gc.values)
                        base[gc.variable] = format_value_for_cobol(dom, val)

                yield base, ctx.success_stubs, ctx.success_defaults, target_para


class BranchSolverStrategy(Strategy):
    """Layer 3: Targeted branch solving."""

    name = "branch_solver"
    priority = 40

    def __init__(self):
        self._exhausted = False
        self._last_branches = 0

    def should_run(self, cov, round_num: int) -> bool:
        if self._exhausted:
            if len(cov.branches_hit) > self._last_branches:
                self._exhausted = False
            else:
                return False
        return cov.total_branches > 0 and len(cov.branches_hit) < cov.total_branches

    def generate_cases(self, ctx, cov, batch_size) -> Iterator[CaseT]:
        from .cobol_coverage import _build_input_state
        from .static_analysis import _parse_condition_variables

        self._last_branches = len(cov.branches_hit)

        branch_meta = ctx.branch_meta
        if not branch_meta:
            self._exhausted = True
            return

        for bid, meta in branch_meta.items():
            for direction in ("T", "F"):
                branch_key = f"{bid}:{direction}"
                if branch_key in cov.branches_hit:
                    continue

                condition = meta.get("condition", "")
                if not condition:
                    continue

                try:
                    parsed = _parse_condition_variables(condition)
                except Exception:
                    continue

                for attempt in range(3):
                    base = _build_input_state(ctx.domains, "semantic", ctx.rng)

                    for var_name, values, negated in parsed:
                        dom = ctx.domains.get(var_name)
                        if not dom:
                            continue

                        want_true = (direction == "T")
                        want_match = want_true != negated  # XOR

                        if want_match and values:
                            val = values[attempt % len(values)]
                        else:
                            val = generate_value(
                                dom,
                                "boundary" if attempt == 0 else "random_valid",
                                ctx.rng,
                            )
                            retry = 0
                            while val in values and retry < 10:
                                val = generate_value(dom, "random_valid", ctx.rng)
                                retry += 1

                        base[var_name] = format_value_for_cobol(dom, val)

                    yield (base, ctx.success_stubs, ctx.success_defaults,
                           f"branch:{bid}:{direction}")

        self._exhausted = True


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

    _FAULT_TABLES = {
        "status_file": ["10", "23", "35", "39", "46", "47"],
        "status_sql": [0, 100, -803, -805, -904],
        "status_cics": [0, 12, 13, 16, 22, 27],
    }

    def __init__(self):
        self._round = 0  # 0=param, 1=stub, 2=dataflow, 3=frontier
        self._llm_feedback: list[str] = []
        self._llm_prev_branches: list[tuple[str, str]] = []  # (bkey, condition)

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

    def should_run(self, cov, round_num: int) -> bool:
        return cov.total_branches > 0 and len(cov.branches_hit) < cov.total_branches

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
            tc = self._best_tc_for_para(cov, para)
            base_state = dict(tc.get("input_state", {})) if tc else {}
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
                            state[var] = generate_value(dom, strat, ctx.rng)
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
                            state[v] = generate_value(dom, strat, ctx.rng)
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
                    bkey = f"{bid}:{direction}"
                    if bkey in cov.branches_hit:
                        continue
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
        str_vals = ["", " ", "Y", "N", "00", "04", "05", "10",
                    "001", "002", "013", "019", "XX", "I", "T", "R"]
        int_vals = [0, 1, -1, 99, 100, 999, -999, 1000000]
        flag_vals = [True, False, "Y", "N", " ", "X"]

        trials_per = max(200, batch_size // max(len(sorted_paras), 1))

        for para in sorted_paras:
            if yielded >= batch_size:
                break

            # Collect what we need: uncovered branch conditions in this para
            needs: list[tuple[str, str, list, bool]] = []  # (bkey, var, vals, want_match)
            for bid, meta in branch_meta.items():
                if meta.get("paragraph") != para:
                    continue
                for direction in ("T", "F"):
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
                # Random perturbation (same as param round)
                for var, literals in cond_vars.items():
                    r = ctx.rng.random()
                    if r < 0.4 and literals:
                        state[var] = ctx.rng.choice(literals)
                    elif r < 0.7:
                        info = ctx.var_report.variables.get(var)
                        if info and info.classification == "flag":
                            state[var] = ctx.rng.choice(flag_vals)
                        elif isinstance(ds.get(var), int):
                            state[var] = ctx.rng.choice(int_vals)
                        else:
                            state[var] = ctx.rng.choice(str_vals)
                for _ in range(ctx.rng.randint(1, 8)):
                    if not var_list:
                        break
                    v = ctx.rng.choice(var_list)
                    if v not in cond_vars:
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
    # LLM gap round: per-branch focused prompts with feedback
    # ------------------------------------------------------------------

    def _llm_gap_round(self, ctx, cov, batch_size, branch_meta) -> Iterator[CaseT]:
        """Per-branch focused LLM prompts with semantic types, covered-direction
        context, and multi-turn execution feedback."""
        if not ctx.llm_provider:
            yield from self._param_round(ctx, cov, batch_size, branch_meta)
            return

        from .llm_coverage import _query_llm_sync
        from .program_analysis import _parse_yaml_seeds

        sorted_paras = self._paragraphs_with_gaps(branch_meta, cov)
        if not sorted_paras:
            return

        # --- Multi-turn feedback: check results of previous LLM round ---
        if self._llm_prev_branches:
            for bkey, cond in self._llm_prev_branches:
                if bkey in cov.branches_hit:
                    self._llm_feedback.append(f"SUCCESS: {bkey} was covered")
                else:
                    self._llm_feedback.append(
                        f"STILL UNCOVERED: {bkey} (condition: {cond[:80]})"
                    )
            self._llm_prev_branches = []
            # Keep only recent feedback to avoid prompt bloat
            self._llm_feedback = self._llm_feedback[-15:]

        # --- Collect the hardest uncovered branches ---
        hard_branches: list[tuple[str, str, str, dict]] = []
        for para in sorted_paras:
            for bid, meta in branch_meta.items():
                if meta.get("paragraph") != para:
                    continue
                for d in ("T", "F"):
                    bk = f"{bid}:{d}"
                    if bk not in cov.branches_hit:
                        cond = meta.get("condition", "")
                        if cond:
                            hard_branches.append((bid, d, para, meta))

        if not hard_branches:
            yield from self._param_round(ctx, cov, batch_size, branch_meta)
            return

        # --- Build per-branch focused prompts (top 5 branches) ---
        branch_prompts: list[str] = []
        targeted_branches: list[tuple[str, str]] = []

        for bid, direction, para, meta in hard_branches[:5]:
            cond = meta.get("condition", "")
            need = "TRUE" if direction == "T" else "FALSE"
            bkey = f"{bid}:{direction}"
            targeted_branches.append((bkey, cond))

            lines = [f"### Branch {bkey} in {para}"]
            lines.append(f"Condition: {cond}")
            lines.append(f"Need condition to be: {need}")

            # --- Covered-direction context (Option C) ---
            opp_dir = "F" if direction == "T" else "T"
            opp_key = f"{bid}:{opp_dir}"
            opp_tc = None
            for tc in cov.test_cases:
                if opp_key in tc.get("branches_hit", []):
                    opp_tc = tc
                    break

            cond_vars = self._collect_cond_vars(branch_meta, para, ctx)

            if opp_tc:
                opp_need = "TRUE" if opp_dir == "T" else "FALSE"
                lines.append(f"The {opp_need} direction IS already covered by TC with:")
                opp_state = opp_tc.get("input_state", {})
                shown = 0
                for var in cond_vars:
                    if var in opp_state and shown < 15:
                        lines.append(f"  {var} = {repr(opp_state[var])}")
                        shown += 1
                lines.append(f"To get {need}, change the relevant values.")

            # --- Variable semantic types and domains ---
            if cond_vars:
                lines.append("Variable details:")
                for var in list(cond_vars)[:10]:
                    dom = ctx.domains.get(var)
                    if dom:
                        parts = [f"  {var}: type={dom.data_type}"]
                        if dom.semantic_type != "generic":
                            parts.append(f"semantic={dom.semantic_type}")
                        if dom.max_length > 0:
                            parts.append(f"len={dom.max_length}")
                        if dom.precision > 0:
                            parts.append(f"precision={dom.precision}")
                        if dom.min_value is not None:
                            parts.append(f"range=[{dom.min_value},{dom.max_value}]")
                        if dom.condition_literals:
                            parts.append(f"known={dom.condition_literals[:6]}")
                        if dom.valid_88_values:
                            v88 = dict(list(dom.valid_88_values.items())[:4])
                            parts.append(f"88_vals={v88}")
                        lines.append(", ".join(parts))
                    else:
                        lines.append(f"  {var}: known_values={cond_vars[var][:6]}")

            # --- Best TC with all condition-relevant vars ---
            tc = self._best_tc_for_para(cov, para)
            if tc:
                lines.append("Best test case (condition-relevant vars):")
                ivars = tc.get("input_state", {})
                shown = 0
                for var in cond_vars:
                    if var in ivars and shown < 20:
                        lines.append(f"  {var} = {repr(ivars[var])}")
                        shown += 1
                # A few extra important vars not in cond_vars
                extra = 0
                for var, val in ivars.items():
                    if var not in cond_vars and extra < 5:
                        lines.append(f"  {var} = {repr(val)}")
                        extra += 1

            branch_prompts.append("\n".join(lines))

        # --- Build feedback section ---
        feedback_section = ""
        if self._llm_feedback:
            feedback_section = "\n\nFeedback from previous attempts:\n" + "\n".join(
                f"- {fb}" for fb in self._llm_feedback[-10:]
            )

        prompt = f"""\
You are a COBOL test engineer. We have {len(cov.branches_hit)}/{cov.total_branches} branches covered.

For each uncovered branch below, suggest input values that would flip the condition \
to the needed direction. Reason about ONE branch at a time — what must each variable \
be set to in order to satisfy (or negate) the specific condition shown.

COBOL notes:
- IS NUMERIC: true when field contains only digits (and optional sign/decimal point)
- NUMVAL(X): converts alphanumeric string X to a number (e.g. NUMVAL('123.45') = 123.45)
- SPACES = string of blanks, ZEROS = '0' characters (not numeric zero)
- Status codes: '00' = success, '10' = EOF, '23' = not found
- For a condition "X IS NOT NUMERIC" to be FALSE, X must contain only valid numeric chars
{feedback_section}

{chr(10).join(branch_prompts)}

For each branch, suggest 1-2 test inputs. Respond in YAML:
- target: branch_id:direction in paragraph_name
  reasoning: why these values should flip the condition
  input_values:
    VARIABLE-NAME: value
  stub_overrides:
    OPERATION-KEY: status"""

        try:
            response_text, _tokens = _query_llm_sync(
                ctx.llm_provider, prompt, ctx.llm_model,
            )
            suggestions = _parse_yaml_seeds(response_text)
            log.info("LLM gap: %d suggestions for %d hard branches",
                     len(suggestions), min(len(hard_branches), 5))
        except Exception as e:
            log.warning("LLM gap query failed: %s", e)
            yield from self._param_round(ctx, cov, batch_size, branch_meta)
            return

        if not suggestions:
            yield from self._param_round(ctx, cov, batch_size, branch_meta)
            return

        # Store targeted branches for feedback in next round
        self._llm_prev_branches = targeted_branches

        # --- For each suggestion: yield the seed + domain-aware perturbations ---
        yielded = 0
        default_state_fn = getattr(ctx.module, "_default_state", None)
        ds = default_state_fn() if default_state_fn else {}
        var_list = list(ds.keys())

        perturbations_per = max(10, (batch_size - len(suggestions)) // max(len(suggestions), 1))

        for seed_data in suggestions:
            if yielded >= batch_size:
                break

            # Build input state from LLM suggestion
            base_state = {}
            for var, val in seed_data.get("input_values", {}).items():
                dom = ctx.domains.get(var.upper())
                if dom:
                    base_state[var.upper()] = format_value_for_cobol(dom, val)
                else:
                    base_state[var.upper()] = str(val)

            # Build stubs from overrides
            stubs = dict(ctx.success_stubs)
            defaults = dict(ctx.success_defaults)
            for op_key, status_val in seed_data.get("stub_overrides", {}).items():
                from .cobol_coverage import _match_stub_operation
                matched = _match_stub_operation(op_key, ctx.stub_mapping)
                if matched:
                    svars = ctx.stub_mapping[matched]
                    entry = [(sv, status_val) for sv in svars]
                    stubs[matched] = [entry] * 50
                    defaults[matched] = entry

            target = seed_data.get("target", "llm_gap")[:40]

            # Determine target paragraph from suggestion
            target_para = None
            for para in sorted_paras:
                if para.lower() in target.lower():
                    target_para = para
                    break
            if not target_para:
                target_para = sorted_paras[0]

            # Yield the raw LLM suggestion
            yield (base_state, stubs, defaults,
                   f"direct:{target_para}|gap:{target}")
            yielded += 1

            # Hill-climb around the suggestion using domain-aware perturbation
            cond_vars_for_para = self._collect_cond_vars(
                branch_meta, target_para, ctx)

            for trial in range(perturbations_per):
                if yielded >= batch_size:
                    break
                state = dict(base_state)

                # Perturb condition variables (domain-aware)
                for var, literals in cond_vars_for_para.items():
                    r = ctx.rng.random()
                    if r < 0.3 and literals:
                        state[var] = ctx.rng.choice(literals)
                    elif r < 0.5:
                        dom = ctx.domains.get(var)
                        if dom:
                            strat = ctx.rng.choice(["semantic", "boundary", "random_valid"])
                            state[var] = generate_value(dom, strat, ctx.rng)
                        else:
                            info = ctx.var_report.variables.get(var)
                            if info and info.classification == "flag":
                                state[var] = ctx.rng.choice([True, False, "Y", "N", " ", "X"])
                            elif isinstance(ds.get(var), int):
                                state[var] = ctx.rng.choice([0, 1, -1, 99, 100, 999, -999, 1000000])
                            else:
                                state[var] = ctx.rng.choice(["", " ", "Y", "N", "00", "04", "05", "10",
                                                              "001", "002", "013", "019", "XX", "I", "T", "R"])
                    # else: keep LLM's value (higher probability to preserve)

                # Light random perturbation (domain-aware)
                for _ in range(ctx.rng.randint(1, 3)):
                    if not var_list:
                        break
                    v = ctx.rng.choice(var_list)
                    if v not in cond_vars_for_para:
                        dom = ctx.domains.get(v)
                        if dom:
                            strat = ctx.rng.choice(["semantic", "boundary", "random_valid"])
                            state[v] = generate_value(dom, strat, ctx.rng)
                        else:
                            dv = ds.get(v)
                            if isinstance(dv, int):
                                state[v] = ctx.rng.choice([0, 1, -1, 99, 100, 999, -999, 1000000])
                            elif isinstance(dv, str):
                                state[v] = ctx.rng.choice(["", " ", "Y", "N", "00", "04", "05", "10",
                                                            "001", "002", "013", "019", "XX", "I", "T", "R"])

                yield (state, stubs, defaults,
                       f"direct:{target_para}|gap-perturb:{trial}")
                yielded += 1

    # ------------------------------------------------------------------
    # Main: rotate param → stub → dataflow → frontier → harvest → inverse → llm_gap
    # ------------------------------------------------------------------

    def generate_cases(self, ctx, cov, batch_size) -> Iterator[CaseT]:
        branch_meta = ctx.branch_meta
        if not branch_meta:
            return

        n_phases = 7 if ctx.llm_provider else 6
        phase = self._round % n_phases
        if phase == 0:
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
        else:
            yield from self._llm_gap_round(ctx, cov, batch_size, branch_meta)

        self._round += 1


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

        fault_tables = {
            "status_file": ["10", "23", "35", "39", "46", "47"],
            "status_sql": [0, 100, -803, -805, -904],
            "status_cics": [0, 12, 13, 16, 22, 27],
        }

        for op_key, status_vars in ctx.stub_mapping.items():
            fault_values: list = []
            for var in status_vars:
                dom = ctx.domains.get(var)
                if dom:
                    table = fault_tables.get(dom.semantic_type, [])
                    fault_values.extend(table)

            if op_key.startswith("DLI") or any("PCB" in v.upper() for v in status_vars):
                fault_values.extend(["GE", "GB", "II", "AI"])

            if not fault_values:
                fault_values = ["10", "23", "35"]

            for fv in fault_values[:5]:
                base = _build_input_state(ctx.domains, "semantic", ctx.rng)
                fault_stubs, fault_defaults = _build_fault_stubs(
                    ctx.stub_mapping, ctx.domains,
                    target_op=op_key, fault_value=fv, rng=ctx.rng,
                )
                yield base, fault_stubs, fault_defaults, f"fault:{op_key}={fv}"

        self._ran = True


class StubWalkStrategy(Strategy):
    """Layer 4b: Fault injection with frozen good inputs + pairwise faults."""

    name = "stub_walk"
    priority = 55

    def __init__(self):
        self._ran = False

    def should_run(self, cov, round_num: int) -> bool:
        return bool(cov._stub_mapping) and len(cov.test_cases) > 0 and not self._ran

    def generate_cases(self, ctx, cov, batch_size) -> Iterator[CaseT]:
        from itertools import combinations

        from .cobol_coverage import _build_fault_stubs

        # Top 5 test cases by paragraph coverage as frozen bases
        ranked = sorted(
            cov.test_cases,
            key=lambda tc: len(tc.get("paragraphs_hit", [])),
            reverse=True,
        )[:5]
        bases = [dict(tc.get("input_state", {})) for tc in ranked]

        # Fallback if somehow empty after filter
        if not bases:
            from .cobol_coverage import _build_input_state
            bases = [
                _build_input_state(ctx.domains, "semantic", ctx.rng)
                for _ in range(3)
            ]

        fault_tables = {
            "status_file": ["10", "23", "35", "39", "46", "47"],
            "status_sql": [0, 100, -803, -805, -904],
            "status_cics": [0, 12, 13, 16, 22, 27],
        }

        # Part 1: single faults with frozen inputs
        for base in bases:
            for op_key, status_vars in ctx.stub_mapping.items():
                fault_values: list = []
                for var in status_vars:
                    dom = ctx.domains.get(var)
                    if dom:
                        table = fault_tables.get(dom.semantic_type, [])
                        fault_values.extend(table)
                if op_key.startswith("DLI") or any(
                    "PCB" in v.upper() for v in status_vars
                ):
                    fault_values.extend(["GE", "GB", "II", "AI"])
                if not fault_values:
                    fault_values = ["10", "23", "35"]

                for fv in fault_values[:5]:
                    fault_stubs, fault_defaults = _build_fault_stubs(
                        ctx.stub_mapping, ctx.domains,
                        target_op=op_key, fault_value=fv, rng=ctx.rng,
                    )
                    yield base, fault_stubs, fault_defaults, f"stubwalk:{op_key}={fv}"

        # Part 2: pairwise faults (two ops fail simultaneously)
        op_keys = list(ctx.stub_mapping.keys())
        if len(op_keys) >= 2:
            for base in bases:
                for op_a, op_b in combinations(op_keys, 2):
                    faults = {}
                    for op in (op_a, op_b):
                        svars = ctx.stub_mapping[op]
                        fv_list: list = []
                        for var in svars:
                            dom = ctx.domains.get(var)
                            if dom:
                                table = fault_tables.get(dom.semantic_type, [])
                                fv_list.extend(table)
                        if op.startswith("DLI") or any(
                            "PCB" in v.upper() for v in svars
                        ):
                            fv_list.extend(["GE", "GB", "II", "AI"])
                        if not fv_list:
                            fv_list = ["10", "23", "35"]
                        faults[op] = ctx.rng.choice(fv_list[:5])

                    stubs, defaults = _build_multi_fault_stubs(
                        ctx.stub_mapping, ctx.domains, faults, ctx.rng,
                    )
                    yield (base, stubs, defaults,
                           f"stubwalk-pair:{op_a}+{op_b}")

        self._ran = True


class GuidedMutationStrategy(Strategy):
    """Layer 5: Guided random walks mutating high-coverage test cases."""

    name = "guided_mutation"
    priority = 60

    def should_run(self, cov, round_num: int) -> bool:
        return len(cov.test_cases) > 0

    def generate_cases(self, ctx, cov, batch_size) -> Iterator[CaseT]:
        from .cobol_coverage import _build_fault_stubs

        if not cov.test_cases:
            return

        ranked = sorted(
            cov.test_cases,
            key=lambda tc: len(tc.get("paragraphs_hit", [])),
            reverse=True,
        )[:10]

        input_vars = [
            name for name, dom in ctx.domains.items()
            if dom.classification in ("input", "flag") and not dom.set_by_stub
        ]

        walks_done = 0
        max_walks = batch_size
        for tc in ranked:
            if walks_done >= max_walks:
                break

            base_state = dict(tc.get("input_state", {}))

            for _ in range(max_walks // len(ranked)):
                if walks_done >= max_walks:
                    break

                mutated = dict(base_state)
                n_mutations = ctx.rng.randint(1, 3)
                vars_to_mutate = ctx.rng.sample(
                    input_vars, min(n_mutations, len(input_vars)),
                )

                for var_name in vars_to_mutate:
                    dom = ctx.domains.get(var_name)
                    if not dom:
                        continue
                    if ctx.rng.random() < 0.7 and (dom.condition_literals or dom.valid_88_values):
                        strategy = "condition_literal" if dom.condition_literals else "88_value"
                    else:
                        strategy = "random_valid"
                    val = generate_value(dom, strategy, ctx.rng)
                    mutated[var_name] = format_value_for_cobol(dom, val)

                if ctx.rng.random() < 0.3 and ctx.stub_mapping:
                    op_key = ctx.rng.choice(list(ctx.stub_mapping.keys()))
                    stubs, defaults = _build_fault_stubs(
                        ctx.stub_mapping, ctx.domains,
                        target_op=op_key, rng=ctx.rng,
                    )
                else:
                    stubs, defaults = ctx.success_stubs, ctx.success_defaults

                yield mutated, stubs, defaults, "walk"
                walks_done += 1


class MonteCarloStrategy(Strategy):
    """Layer 6: Broad random exploration with mixed strategies."""

    name = "monte_carlo"
    priority = 70

    def generate_cases(self, ctx, cov, batch_size) -> Iterator[CaseT]:
        from .cobol_coverage import _build_fault_stubs, _build_input_state

        for iteration in range(batch_size):
            roll = ctx.rng.random()
            if roll < 0.4:
                strategy = "random_valid"
            elif roll < 0.6:
                strategy = "boundary"
            elif roll < 0.8:
                strategy = "adversarial"
            else:
                strategy = "semantic"

            input_state = _build_input_state(ctx.domains, strategy, ctx.rng)

            if ctx.rng.random() < 0.3 and ctx.stub_mapping:
                op_key = ctx.rng.choice(list(ctx.stub_mapping.keys()))
                stubs, defaults = _build_fault_stubs(
                    ctx.stub_mapping, ctx.domains,
                    target_op=op_key, rng=ctx.rng,
                )
            else:
                stubs, defaults = ctx.success_stubs, ctx.success_defaults

            yield input_state, stubs, defaults, "monte_carlo"

            if (iteration + 1) % 200 == 0:
                log.info("  monte_carlo iteration %d: %d paras, %d branches",
                         iteration + 1, len(cov.paragraphs_hit),
                         len(cov.branches_hit))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_multi_fault_stubs(
    stub_mapping: dict[str, list[str]],
    domains: dict[str, "VariableDomain"],
    faults: dict[str, object],
    rng: random.Random,
) -> tuple[dict[str, list], dict[str, list]]:
    """Build stubs where multiple operations return fault values.

    Args:
        faults: mapping of op_key -> fault_value for each faulted operation.
    """
    outcomes: dict[str, list] = {}
    defaults: dict[str, list] = {}

    for op_key, status_vars in stub_mapping.items():
        entries: list = []
        fault_value = faults.get(op_key)

        for var in status_vars:
            dom = domains.get(var)
            if fault_value is not None:
                entries.append((var, fault_value))
            else:
                # Success for non-faulted ops
                if dom and dom.semantic_type == "status_file":
                    entries.append((var, "00"))
                elif dom and dom.semantic_type == "status_sql":
                    entries.append((var, 0))
                elif "PCB" in var.upper() or op_key.startswith("DLI"):
                    entries.append((var, "  "))
                else:
                    entries.append((var, "00"))

        if entries:
            outcomes.setdefault(op_key, []).append(entries)
            defaults[op_key] = entries

    return outcomes, defaults


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


def _build_intent_prompt(
    program_id: str,
    comments: dict[str, list[str]],
    flow_summary: list[str],
    var_report: VariableReport,
    stub_mapping: dict[str, list[str]],
    domains: dict[str, VariableDomain],
) -> str:
    """Build a prompt asking the LLM to identify business scenarios."""
    flow_block = "\n".join(flow_summary) if flow_summary else "(empty program)"

    anno_lines = []
    for para_name, bullets in sorted(comments.items()):
        anno_lines.append(f"{para_name}: {'; '.join(bullets)}")
    anno_block = "\n".join(anno_lines[:50]) if anno_lines else "(no comments)"

    var_lines = []
    for name, dom in sorted(domains.items()):
        if dom.classification not in ("input", "status", "flag"):
            continue
        if dom.set_by_stub:
            continue
        extras = []
        if dom.condition_literals:
            extras.append(f"known_values={dom.condition_literals[:8]!r}")
        if dom.valid_88_values:
            extras.append(f"88_levels={dict(list(dom.valid_88_values.items())[:6])!r}")
        if dom.semantic_type != "generic":
            extras.append(f"type={dom.semantic_type}")
        extra_str = f" ({', '.join(extras)})" if extras else ""
        var_lines.append(f"  {name}: {dom.classification}{extra_str}")

    var_summary = "\n".join(var_lines[:60]) if var_lines else "  (none)"

    stub_lines = []
    for op_key, status_vars in sorted(stub_mapping.items()):
        status_info = []
        for sv in status_vars:
            dom = domains.get(sv)
            if dom and (dom.condition_literals or dom.valid_88_values):
                vals = [str(v) for v in dom.condition_literals[:4]]
                status_info.append(f"{sv} [{', '.join(vals)}]")
            else:
                status_info.append(sv)
        stub_lines.append(f"  {op_key} -> {'; '.join(status_info)}")
    stub_summary = "\n".join(stub_lines[:40]) if stub_lines else "  (none)"

    return f"""\
You are an expert COBOL business analyst. Analyze this program's structure
and identify its business purpose, then generate 10-15 distinct, realistic
business scenarios that would exercise different execution paths.

=== PROGRAM: {program_id} ===

=== FLOW ===
{flow_block}

=== PARAGRAPH ANNOTATIONS ===
{anno_block}

=== INPUT VARIABLES ===
{var_summary}

=== STUB OPERATIONS ===
{stub_summary}

=== INSTRUCTIONS ===
First, identify what business process this program implements (e.g.,
credit card authorization, account update, transaction posting).

Then generate scenarios representing real-world business situations such as:
- Happy path (normal successful operation)
- Customer/account not found
- Validation failures (invalid input, expired data)
- Authorization denied / over limit
- Duplicate transaction
- System errors (database unavailable, communication failure)
- Edge cases (zero amounts, boundary dates)

Each scenario should have concrete variable values that trigger the
corresponding business path through the program.

For stub_overrides, use operation keys from the stub operations above and set
status values: file "00"=success/"10"=EOF/"23"=not-found, DLI "  "=success/
"GE"=not-found, CICS 0=normal/12=not-found, SQL 0=success/100=not-found.

Respond with ONLY a JSON array:
[
  {{
    "input_values": {{"VARIABLE-NAME": "value", ...}},
    "stub_overrides": {{"OPERATION:KEY": "status", ...}},
    "target": "brief scenario description",
    "reasoning": "why these values trigger this business path"
  }}
]"""


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
            eligible = [s for s in strategies if s.name == "monte_carlo"]
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
        if strategy.name in ("llm_seed", "llm_gap", "intent_driven", "baseline"):
            return 500
        if strategy.name == "direct_paragraph":
            return min(self.default_batch_size * 25, 5000)
        if strategy.name == "monte_carlo":
            return min(self.default_batch_size * 5, 2000)
        return self.default_batch_size


class LLMSelector(StrategySelector):
    """Consults LLM periodically, falls back to HeuristicSelector."""

    def __init__(self, llm_provider, llm_model: str | None = None,
                 consult_interval: int = 5, default_batch_size: int = 200,
                 var_report: VariableReport | None = None):
        self.llm_provider = llm_provider
        self.llm_model = llm_model
        self.consult_interval = consult_interval
        self.var_report = var_report
        self._heuristic = HeuristicSelector(default_batch_size)
        self._last_llm_round = -1
        self._profiles_initialized = False
        self._semantic_profiles: dict = {}

    def select(self, strategies, cov, round_num):
        if (round_num > 0
                and (round_num - self._last_llm_round) >= self.consult_interval
                and cov.stale_rounds >= 2):
            decision = self._consult_llm(strategies, cov, round_num)
            if decision is not None:
                self._last_llm_round = round_num
                return decision

        return self._heuristic.select(strategies, cov, round_num)

    def _consult_llm(self, strategies, cov, round_num):
        from .llm_fuzzer import (
            SessionMemory,
            StrategyResult,
            get_strategy_decision,
            infer_variable_semantics,
        )

        memory = SessionMemory()
        for sname, syield in cov.strategy_yields.items():
            memory.strategy_history.append(StrategyResult(
                strategy=sname, iterations=syield.total_cases,
                new_paragraphs=syield.total_new_coverage,
                new_branches=0, new_edges=0, errors=0,
            ))

        if not self._profiles_initialized:
            self._profiles_initialized = True
            if self.var_report is not None and self.var_report.variables:
                try:
                    self._semantic_profiles = infer_variable_semantics(
                        self.llm_provider, self.var_report, model=self.llm_model,
                    )
                except Exception as e:
                    log.warning("LLM selector profile inference failed: %s", e)
                    self._semantic_profiles = {}
        if self._semantic_profiles:
            memory.semantic_profiles.update(self._semantic_profiles)

        var_report = self.var_report
        if var_report is None:
            var_report = type("VarReport", (), {"variables": {}})()

        frontier: set[str] = set()
        try:
            decision = get_strategy_decision(
                self.llm_provider, memory, cov.paragraphs_hit,
                cov.all_paragraphs, frontier, cov.total_branches,
                len(cov.branches_hit),
                var_report,
                model=self.llm_model,
            )
        except Exception as e:
            log.warning("LLM selector query failed: %s", e)
            return None

        if decision is None:
            return None

        name_map = {
            "random_exploration": "monte_carlo",
            "single_var_mutation": "guided_mutation",
            "literal_guided": "baseline",
            "directed_walk": "constraint_solver",
            "stub_outcome_variation": "fault_injection",
            "crossover": "guided_mutation",
            "error_avoidance_replay": "guided_mutation",
        }
        target_name = name_map.get(decision.strategy, "monte_carlo")

        for s in strategies:
            if s.name == target_name and s.should_run(cov, round_num):
                batch = max(25, min(500, decision.iterations))
                log.info("LLM selector chose %s (%s): %s",
                         s.name, decision.strategy, decision.reasoning[:60])
                return s, batch

        return None
