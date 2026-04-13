"""Hierarchical 3-level planner for stubborn uncovered branches.

When the coverage loop plateaus and no strategy can reach a specific
branch, this module runs a focused investigation that decomposes the
problem into subgoals:

  Level 1 — **Route Planner** (deterministic):  BFS shortest path from
  program entry to the target paragraph, with gating conditions at
  each step.

  Level 2 — **Gate Solver** (1–2 LLM calls):  Works backwards from the
  target branch condition through each gate to determine what variable
  values and stub outcomes are needed end-to-end.  Validated forward
  via a fast Python execution (~3 ms) with precise per-gate diagnosis
  on failure.

  Level 3 — **Tape Builder** (deterministic):  Warm-starts from the
  nearest-hit test case's stub log, patches specific entries per the
  Gate Solver's output, pads loop iterations if needed, and produces
  a concrete ``(input_state, stub_log)`` pair ready for
  ``run_test_case``.

Direct execution bypasses ``_execute_and_save`` — the tape builder
hands the stub log directly to the COBOL binary, avoiding all the
projection/replay/prefix-matching that loses data.

Entry point: ``run_branch_swarm()`` — signature-compatible with
``run_branch_agent()`` so ``cobol_coverage.py`` can swap it in.
"""

from __future__ import annotations

import inspect
import json
import logging
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SpecialistProposal:
    """Output from one specialist agent."""

    specialist: str  # condition_cracker | path_finder | stub_architect | history_miner
    input_state: dict = field(default_factory=dict)
    stub_outcomes: dict = field(default_factory=dict)
    stub_defaults: dict | None = None
    reasoning: str = ""
    confidence: float = 0.5
    target_paragraph: str | None = None
    raw_response: str = ""


@dataclass
class JudgeFeedback:
    """Structured execution feedback from the judge."""

    reached_paragraph: bool = False
    condition_value: str | None = None
    actual_var_values: dict[str, Any] = field(default_factory=dict)
    branches_hit: list[str] = field(default_factory=list)
    paragraphs_hit: list[str] = field(default_factory=list)
    error: str | None = None
    python_result: bool = False
    cobol_promoted: bool = False
    branch_hit: bool = False


@dataclass
class SwarmRound:
    """One round of the swarm: proposals + synthesis + execution."""

    round_num: int
    proposals: list[SpecialistProposal] = field(default_factory=list)
    synthesized_cases: list[dict] = field(default_factory=list)
    feedback: list[JudgeFeedback] = field(default_factory=list)
    branch_hit: bool = False


@dataclass
class SolutionPattern:
    """A pattern that solved a branch, for cross-branch reuse."""

    branch_key: str
    paragraph: str
    condition_category: str
    winning_specialist: str
    key_variables: dict[str, Any] = field(default_factory=dict)
    key_stubs: dict[str, Any] = field(default_factory=dict)


@dataclass
class BranchContext:
    """All pre-gathered context for investigating one branch."""

    bid: int
    direction: str
    branch_key: str
    paragraph: str
    condition_text: str
    backward_slice_code: str
    var_domain_info: dict[str, dict[str, Any]]
    nearest_hit: dict | None
    call_graph_path: list[str]
    gating_conditions: list[dict]
    stub_ops_in_slice: list[str]
    stub_mapping: dict[str, list[str]]
    fault_tables: dict[str, list]
    test_case_count: int
    solution_patterns: list[SolutionPattern]
    # 88-level child → (parent_name, activating_value) reverse map.
    parent_88_lookup: dict[str, tuple[str, Any]] = field(default_factory=dict)
    # Full ordered stub operation sequence from the backward slice,
    # preserving duplicates (e.g. OPEN then READ then REWRITE).
    stub_op_sequence: list[str] = field(default_factory=list)


# Backward-compatible journal (wraps SwarmRound list into AgentIteration list)

@dataclass
class SwarmJournal:
    """Full record of a swarm investigation for one branch."""

    branch_key: str
    paragraph: str = ""
    condition_text: str = ""
    max_rounds: int = 3
    rounds: list[SwarmRound] = field(default_factory=list)
    success: bool = False
    final_reasoning: str = ""

    @property
    def max_iterations(self) -> int:
        return self.max_rounds

    @property
    def iterations(self) -> list:
        """Flatten rounds into AgentIteration-compatible dicts."""
        from .branch_agent import AgentIteration
        out: list[AgentIteration] = []
        for rnd in self.rounds:
            for i, fb in enumerate(rnd.feedback):
                case = rnd.synthesized_cases[i] if i < len(rnd.synthesized_cases) else {}
                reasons = [p.reasoning for p in rnd.proposals if p.reasoning]
                out.append(AgentIteration(
                    iteration=rnd.round_num * 10 + i,
                    prompt_summary=f"swarm round {rnd.round_num + 1}, case {i + 1}",
                    proposed_input=case.get("input_state", {}),
                    proposed_stubs=case.get("stub_outcomes", {}),
                    reasoning="; ".join(reasons)[:300],
                    execution_result={
                        "reached_paragraph": fb.reached_paragraph,
                        "branches_hit": fb.branches_hit[:10],
                        "error": fb.error,
                    },
                    branch_hit=fb.branch_hit,
                ))
        return out


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_MAX_ROUNDS = 3
DEFAULT_MAX_BRANCHES = 3
DEFAULT_MAX_INVOCATIONS = 3
DEFAULT_STALE_TRIGGER = 3
_MAX_LOOP_PAD = 5  # max loop iterations to try when padding stubs

_FAULT_TABLES = {
    "status_file": ["00", "10", "23", "35", "39", "46", "47"],
    "status_sql": [0, 100, -803, -805, -904],
    "status_cics": [0, 12, 13, 16, 22, 27],
    "status_dli": ["  ", "GE", "II", "GB"],
    "status_mq": [0, 2033, 2035, 2085],
}


def swarm_enabled() -> bool:
    """Return False if the user has disabled the branch swarm."""
    raw = os.environ.get("SPECTER_BRANCH_SWARM", "1").strip().lower()
    return raw not in ("0", "false", "no", "off", "")


# ---------------------------------------------------------------------------
# Context gathering
# ---------------------------------------------------------------------------

def _gather_branch_context(
    bid: int,
    direction: str,
    ctx,
    cov,
) -> BranchContext:
    """Gather all context needed for investigating one branch."""
    from .backward_slicer import backward_slice, slice_variable_names

    branch_key = f"{bid}:{direction}"
    branch_meta = getattr(ctx, "branch_meta", {}) or {}
    meta = branch_meta.get(str(bid)) or branch_meta.get(bid) or {}
    paragraph = str(meta.get("paragraph", "")).upper()
    condition_text = str(meta.get("condition", ""))

    # --- backward slice ---
    module_source = ""
    try:
        module = getattr(ctx, "module", None)
        if module:
            src_path = getattr(module, "__file__", None) or getattr(
                inspect.getfile(type(module)), "__file__", None
            )
            if src_path:
                module_source = Path(src_path).read_text(errors="replace")
    except Exception:
        pass

    slice_code = ""
    if module_source:
        try:
            target_bid = bid if direction == "T" else -bid
            slice_code = backward_slice(module_source, target_bid)
        except Exception:
            pass

    # --- variable domains ---
    domains = getattr(ctx, "domains", {}) or {}
    stub_mapping = getattr(ctx, "stub_mapping", {}) or {}
    var_to_stub: dict[str, str] = {}
    for op_key, status_vars in stub_mapping.items():
        for v in status_vars:
            var_to_stub.setdefault(v.upper(), op_key)

    condition_vars = _extract_condition_vars(condition_text)
    # Also pull in slice variables for broader context.
    slice_vars: set[str] = set()
    if module_source:
        try:
            slice_vars = slice_variable_names(module_source, bid if direction == "T" else -bid)
        except Exception:
            pass

    all_vars = list(dict.fromkeys(condition_vars + sorted(slice_vars - set(condition_vars))))
    var_domain_info: dict[str, dict[str, Any]] = {}
    for v in all_vars[:20]:  # cap to avoid prompt bloat
        dom = domains.get(v)
        if dom is None:
            continue
        var_domain_info[v] = {
            "classification": getattr(dom, "classification", ""),
            "data_type": getattr(dom, "data_type", ""),
            "max_length": getattr(dom, "max_length", 0),
            "precision": getattr(dom, "precision", 0),
            "signed": getattr(dom, "signed", False),
            "condition_literals": list(getattr(dom, "condition_literals", []))[:8],
            "valid_88_values": dict(getattr(dom, "valid_88_values", {})),
            "stub_op": var_to_stub.get(v, ""),
        }

    # --- nearest hit ---
    from .branch_agent import _find_nearest_hit
    nearest_hit = _find_nearest_hit(cov.test_cases, bid, paragraph)

    # --- call graph path + gating conditions ---
    call_graph = getattr(ctx, "call_graph", None)
    call_graph_path: list[str] = []
    if call_graph and paragraph:
        try:
            path = call_graph.path_to(paragraph)
            call_graph_path = path or []
        except Exception:
            pass

    gating_conds = getattr(ctx, "gating_conds", None) or {}
    gating_here = gating_conds.get(paragraph, []) if paragraph else []
    gating_list: list[dict] = []
    for gc in gating_here[:8]:
        gating_list.append({
            "variable": getattr(gc, "variable", "") or (gc.get("variable", "") if isinstance(gc, dict) else ""),
            "values": getattr(gc, "values", []) or (gc.get("values", []) if isinstance(gc, dict) else []),
            "negated": getattr(gc, "negated", False) or (gc.get("negated", False) if isinstance(gc, dict) else False),
        })

    # --- 88-level parent lookup ---
    # Build a reverse map: 88-level child name → (parent, activating value).
    # This lets specialists know that e.g. APPL-AOK is activated by
    # setting APPL-RESULT = 0, rather than treating it as a regular variable.
    parent_88_lookup: dict[str, tuple[str, Any]] = {}
    for parent_name, parent_dom in domains.items():
        v88 = getattr(parent_dom, "valid_88_values", None) or {}
        for child_name, child_value in v88.items():
            parent_88_lookup.setdefault(
                child_name.upper(), (parent_name, child_value),
            )
    # Also check var_report for broader 88-level data.
    var_report = getattr(ctx, "var_report", None)
    if var_report:
        for parent_name, parent_info in getattr(var_report, "variables", {}).items():
            v88 = getattr(parent_info, "valid_88_values", None) or {}
            if isinstance(v88, dict):
                for child_name, child_value in v88.items():
                    parent_88_lookup.setdefault(
                        child_name.upper(), (parent_name, child_value),
                    )

    # --- stub operations in the slice ---
    # Deduplicated list for prompt summaries.
    stub_ops_in_slice: list[str] = []
    # Full ordered sequence preserving duplicates for sequencing context.
    stub_op_sequence: list[str] = []
    if slice_code:
        for m in re.finditer(r"_apply_stub_outcome\(state,\s*'([^']+)'\)", slice_code):
            stub_op_sequence.append(m.group(1))
            if m.group(1) not in stub_ops_in_slice:
                stub_ops_in_slice.append(m.group(1))

    # --- solution patterns from prior branches ---
    memory_state = getattr(ctx, "memory_state", None)
    patterns: list[SolutionPattern] = []
    if memory_state:
        raw = getattr(memory_state, "meta", {}).get("solution_patterns", [])
        for p in raw[:10]:
            if isinstance(p, dict):
                patterns.append(SolutionPattern(**{
                    k: p.get(k, "") for k in SolutionPattern.__dataclass_fields__
                }))

    total_attempts = sum(
        1 for tc in cov.test_cases
        if paragraph and paragraph in (tc.get("paragraphs_hit") or [])
    )

    return BranchContext(
        bid=bid,
        direction=direction,
        branch_key=branch_key,
        paragraph=paragraph,
        condition_text=condition_text,
        backward_slice_code=slice_code,
        var_domain_info=var_domain_info,
        nearest_hit=nearest_hit,
        call_graph_path=call_graph_path,
        gating_conditions=gating_list,
        stub_ops_in_slice=stub_ops_in_slice,
        stub_mapping=dict(stub_mapping),
        fault_tables=dict(_FAULT_TABLES),
        test_case_count=total_attempts,
        solution_patterns=patterns,
        parent_88_lookup=parent_88_lookup,
        stub_op_sequence=stub_op_sequence,
    )


# ---------------------------------------------------------------------------
# Level 1: Route Planner (deterministic)
# ---------------------------------------------------------------------------


def _plan_route(
    bctx: BranchContext,
    ctx,
) -> list[tuple[str, list[dict]]]:
    """Compute the ordered paragraph path from entry to target with gates.

    Returns a list of ``(paragraph_name, [gate_dicts])`` from the program
    entry to ``bctx.paragraph``.  Each gate dict has ``variable``,
    ``values``, ``negated``.  Returns an empty list when no static path
    exists (direct invocation only).
    """
    call_graph = getattr(ctx, "call_graph", None)
    gating_conds = getattr(ctx, "gating_conds", None) or {}

    if call_graph is None or not bctx.paragraph:
        return []

    try:
        path = call_graph.path_to(bctx.paragraph)
    except Exception:
        path = None
    if not path:
        return []

    route: list[tuple[str, list[dict]]] = []
    for para in path:
        gates: list[dict] = []
        for gc in gating_conds.get(para, []):
            gates.append({
                "variable": getattr(gc, "variable", "") or (
                    gc.get("variable", "") if isinstance(gc, dict) else ""
                ),
                "values": getattr(gc, "values", []) or (
                    gc.get("values", []) if isinstance(gc, dict) else []
                ),
                "negated": getattr(gc, "negated", False) or (
                    gc.get("negated", False) if isinstance(gc, dict) else False
                ),
            })
        route.append((para, gates))
    return route


# ---------------------------------------------------------------------------
# Level 2: Gate Solver (1–2 LLM calls, backward chaining)
# ---------------------------------------------------------------------------

def _build_gate_solver_prompt(
    bctx: BranchContext,
    route: list[tuple[str, list[dict]]],
    diagnosis: str | None = None,
) -> str:
    """Build the backward-chaining prompt for the Gate Solver.

    Lays out the full execution path from entry to target, shows each
    gate and what must be satisfied, and asks the LLM to work backwards
    from the target condition to determine all required values.
    """
    parts: list[str] = []
    parts.append(
        "You are solving a COBOL branch-coverage problem by backward chaining.\n\n"
        "The program executes from entry, passes through a sequence of\n"
        "paragraphs (each gated by conditions), and must reach a specific\n"
        "branch.  Work BACKWARDS from the target branch to determine what\n"
        "every variable and stub outcome must be.\n\n"
    )

    # --- Target branch ---
    parts.append(
        f"TARGET: Branch {bctx.branch_key} in paragraph {bctx.paragraph}\n"
    )
    if bctx.condition_text:
        parts.append(f"Condition: {bctx.condition_text}\n")
    direction_word = "TRUE" if bctx.direction == "T" else "FALSE"
    parts.append(f"Required direction: {direction_word}\n\n")

    # --- Backward slice ---
    if bctx.backward_slice_code:
        slice_lines = bctx.backward_slice_code.splitlines()
        if len(slice_lines) > 100:
            slice_lines = slice_lines[:100] + ["  # ... (truncated)"]
        parts.append(
            "Code path to this branch (Python simulator):\n```python\n"
            + "\n".join(slice_lines) + "\n```\n\n"
        )

    # --- Route from entry ---
    if route:
        parts.append("EXECUTION ROUTE (entry → target):\n")
        for i, (para, gates) in enumerate(route):
            parts.append(f"  Step {i + 1}: paragraph {para}\n")
            for g in gates:
                var = g.get("variable", "?")
                vals = g.get("values", [])
                neg = " (negated)" if g.get("negated") else ""
                parts.append(f"    GATE: {var} must be in {vals}{neg}\n")
        parts.append("\n")
    else:
        parts.append(
            "No static route from entry to the target paragraph.\n"
            "The paragraph is invoked directly.\n\n"
        )

    # --- Variable domains with 88-level resolution ---
    if bctx.var_domain_info:
        parts.append("VARIABLE DOMAINS:\n")
        for var, info in bctx.var_domain_info.items():
            bits = [f"  {var}:"]
            if info.get("data_type"):
                bits.append(f" type={info['data_type']}")
            if info.get("max_length"):
                bits.append(f" len={info['max_length']}")
            if info.get("condition_literals"):
                bits.append(f" known_values={info['condition_literals'][:6]}")
            if info.get("valid_88_values"):
                bits.append(f" 88-levels={info['valid_88_values']}")
            if info.get("stub_op"):
                bits.append(f" (SET BY STUB: {info['stub_op']})")
            parent_entry = bctx.parent_88_lookup.get(var)
            if parent_entry:
                bits.append(
                    f" ** 88-level flag: set parent {parent_entry[0]} = "
                    f"{parent_entry[1]!r} to activate **"
                )
            parts.append("".join(bits) + "\n")
        parts.append("\n")

    # Extra 88-level hints for condition variables not in var_domain_info.
    for var in _extract_condition_vars(bctx.condition_text):
        if var in bctx.var_domain_info:
            continue
        parent_entry = bctx.parent_88_lookup.get(var)
        if parent_entry:
            parts.append(
                f"  {var} is an 88-level flag. "
                f"Set {parent_entry[0]} = {parent_entry[1]!r} in input_state.\n"
            )

    # --- Stub operation sequence ---
    if bctx.stub_op_sequence:
        parts.append("\nSTUB OPERATION SEQUENCE (consumed in this order):\n")
        for i, op in enumerate(bctx.stub_op_sequence, 1):
            status_vars = bctx.stub_mapping.get(op, [])
            parts.append(f"  {i}. {op} → sets {status_vars}\n")
        parts.append(
            "Every stub before the target operation MUST return success "
            "(typically status '00') or the program will abort/branch away.\n"
            "Only the stub that sets the TARGET variable should return the "
            "specific value needed by the branch condition.\n\n"
        )

    # --- Nearest hit (warm-start context) ---
    if bctx.nearest_hit:
        inp = bctx.nearest_hit.get("input_state") or {}
        if len(inp) > 10:
            inp = dict(list(inp.items())[:10])
        branches = bctx.nearest_hit.get("branches_hit") or []
        parts.append(
            "NEAREST-HIT TEST CASE (reached the paragraph, missed the branch):\n"
            f"  input_state: {json.dumps(inp, default=str)}\n"
            f"  branches_hit: {branches[:8]}\n\n"
        )

    # --- Diagnosis from failed forward validation ---
    if diagnosis:
        parts.append(
            f"PREVIOUS ATTEMPT FAILED. Diagnosis:\n{diagnosis}\n"
            "Adjust your proposal based on this diagnosis.\n\n"
        )

    # --- Response format ---
    parts.append(
        "Work backwards: what does the branch need? → what sets that "
        "variable? → what must the stub return? → what must earlier "
        "stubs return so the program reaches that point?\n\n"
        "Return ONLY a JSON object:\n"
        "{\n"
        '  "input_state": {"VAR_NAME": "value", ...},\n'
        '  "stub_outcomes": {"OP_KEY": [[["VAR", "VALUE"]], ...], ...},\n'
        '  "reasoning": "backward chain explanation"\n'
        "}\n"
    )
    return "".join(parts)


def _parse_gate_solver_response(text: str | None) -> tuple[dict, dict, str]:
    """Parse the Gate Solver LLM response.

    Returns ``(input_state, stub_outcomes, reasoning)``.
    """
    if not text:
        return {}, {}, "empty response"

    cleaned = text.strip()
    cleaned = re.sub(r"^```\w*\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    obj: dict | None = None
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            obj = parsed
    except (json.JSONDecodeError, ValueError, TypeError):
        pass

    if obj is None:
        m = re.search(r"\{[\s\S]*\}", cleaned)
        if m:
            try:
                parsed = json.loads(m.group(0))
                if isinstance(parsed, dict):
                    obj = parsed
            except (json.JSONDecodeError, ValueError, TypeError):
                pass

    if obj is None:
        return {}, {}, f"could not parse: {cleaned[:200]}"

    return (
        obj.get("input_state") or {},
        obj.get("stub_outcomes") or {},
        str(obj.get("reasoning", ""))[:300] or "(no reasoning)",
    )


def _solve_gates(
    bctx: BranchContext,
    route: list[tuple[str, list[dict]]],
    llm_provider,
    llm_model: str | None,
    diagnosis: str | None = None,
) -> tuple[dict, dict, str]:
    """Call the Gate Solver LLM. Returns (input_state, stub_outcomes, reasoning)."""
    from .llm_coverage import _query_llm_sync

    prompt = _build_gate_solver_prompt(bctx, route, diagnosis)
    try:
        response, _ = _query_llm_sync(llm_provider, prompt, llm_model)
    except Exception as exc:
        log.warning("  Gate solver LLM call failed: %s", exc)
        return {}, {}, f"LLM call failed: {exc}"

    return _parse_gate_solver_response(response)


# ---------------------------------------------------------------------------
# Level 2.5: Python forward validation
# ---------------------------------------------------------------------------

def _validate_python(
    module,
    bctx: BranchContext,
    input_state: dict,
    stub_outcomes: dict,
) -> tuple[bool, str | None]:
    """Run Python forward validation. Returns (branch_hit, diagnosis_if_failed)."""
    if module is None or not bctx.paragraph:
        return False, "no module or paragraph for Python validation"

    from .monte_carlo import _run_paragraph_directly

    try:
        default_state_fn = getattr(module, "_default_state", None)
        state = default_state_fn() if default_state_fn else {}
        state.update(input_state)
        if stub_outcomes:
            state["_stub_outcomes"] = {
                k: [list(e) if isinstance(e, list) else e for e in v]
                for k, v in stub_outcomes.items()
            }
        state.setdefault("_stub_log", [])
        state.setdefault("_stub_defaults", {})

        post_state = _run_paragraph_directly(module, bctx.paragraph, state)
        if not post_state:
            return False, f"paragraph {bctx.paragraph} not found in Python module"

        target_int = bctx.bid if bctx.direction == "T" else -bctx.bid
        raw_branches = post_state.get("_branches", set())
        if target_int in raw_branches:
            return True, None

        # Build diagnosis: what did each condition variable actually hold?
        diag_parts: list[str] = []
        cond_vars = _extract_condition_vars(bctx.condition_text)
        for var in cond_vars[:8]:
            actual = post_state.get(var)
            expected_info = bctx.var_domain_info.get(var, {})
            stub_op = expected_info.get("stub_op", "")
            diag_parts.append(
                f"  {var} = {actual!r}"
                + (f" (set by stub {stub_op})" if stub_op else " (input)")
            )

        # Check which gate-step paragraphs were actually executed.
        trace = post_state.get("_trace", [])
        diag_parts.append(f"  paragraphs hit: {trace[:10]}")

        # Which branches fired nearby?
        nearby = sorted(
            b for b in raw_branches
            if abs(b) in range(bctx.bid - 3, bctx.bid + 4)
        )
        diag_parts.append(f"  nearby branches fired: {nearby}")

        return False, "\n".join(diag_parts)

    except Exception as exc:
        return False, f"Python execution error: {exc}"


# ---------------------------------------------------------------------------
# Level 3: Tape Builder (deterministic)
# ---------------------------------------------------------------------------

def _build_tape(
    bctx: BranchContext,
    ctx,
    input_state: dict,
    stub_outcomes: dict,
) -> tuple[dict, list[tuple[str, list]]]:
    """Build a concrete (input_state, stub_log) for run_test_case.

    Warm-starts from the nearest-hit's stub log if available, then
    patches specific entries per the Gate Solver's output.  Falls back
    to a fresh ``_python_pre_run`` if no warm-start is available.
    """
    from .cobol_coverage import _python_pre_run

    module = getattr(ctx, "module", None)
    if module is None:
        return input_state, []

    # Merge Gate Solver's input_state with nearest-hit for warm-start.
    merged_input = dict(input_state)

    # Run the full Python program from entry with the proposed
    # stub_outcomes to get the execution-ordered stub_log.
    stub_log = _python_pre_run(module, merged_input, stub_outcomes)

    # If the stub_log is very short but stub_outcomes has entries,
    # the program may have aborted early.  Try padding with success
    # stubs for operations the program didn't reach.
    if stub_outcomes and len(stub_log) < len(stub_outcomes):
        # Add missing operations with success status.
        logged_ops = {op for op, _ in stub_log}
        for op_key, entries in stub_outcomes.items():
            if op_key not in logged_ops and entries:
                stub_log.append((op_key, entries[0] if entries else []))

    return merged_input, stub_log


# ---------------------------------------------------------------------------
# Direct execution (bypasses _execute_and_save)
# ---------------------------------------------------------------------------

def _execute_directly(
    ctx,
    cov,
    report,
    tc_count: int,
    input_state: dict,
    stub_log: list[tuple[str, list]],
    bctx: BranchContext,
    stub_defaults: dict | None = None,
) -> tuple[JudgeFeedback, int]:
    """Execute via run_test_case and handle coverage bookkeeping."""
    feedback = JudgeFeedback()

    cobol_context = getattr(ctx, "context", None)
    if cobol_context is None:
        # Python-only mode fallback.
        feedback.error = "no COBOL execution context"
        return feedback, tc_count

    try:
        from .cobol_executor import run_test_case
        from .cobol_coverage import _save_test_case, _compute_tc_id

        exec_timeout = int(getattr(ctx, "execution_timeout", 120))
        result = run_test_case(
            cobol_context, input_state, stub_log,
            timeout=exec_timeout,
            stub_defaults=stub_defaults,
        )

        feedback.cobol_promoted = True
        feedback.error = result.error
        feedback.paragraphs_hit = list(result.paragraphs_hit or [])[:15]
        feedback.branches_hit = list(result.branches_hit or [])[:30]
        feedback.reached_paragraph = bctx.paragraph in (result.paragraphs_hit or [])
        feedback.branch_hit = bctx.branch_key in (result.branches_hit or set())

        if result.error:
            return feedback, tc_count

        # --- Coverage bookkeeping (mirrors _execute_and_save) ---
        result_paras = set(result.paragraphs_hit)
        all_paras = getattr(cov, "all_paragraphs", None) or set()
        if all_paras:
            result_ast_paras = result_paras & all_paras
        else:
            result_ast_paras = result_paras

        new_paras = result_ast_paras - cov.paragraphs_hit
        new_branches = result.branches_hit - cov.branches_hit

        if new_paras or new_branches:
            cov.paragraphs_hit.update(result_ast_paras)
            cov.branches_hit.update(result.branches_hit)

            tc_id = _compute_tc_id(input_state, stub_log)
            target = f"direct:{bctx.paragraph}|swarm:{bctx.branch_key}"
            store_path = getattr(ctx, "store_path", None)
            if store_path:
                _save_test_case(
                    store_path, tc_id, input_state, stub_log, result,
                    "branch_swarm", target,
                )
            tc_count += 1
            report.layer_stats["branch_swarm"] = report.layer_stats.get("branch_swarm", 0) + 1

            cov.test_cases.append({
                "id": tc_id,
                "input_state": {k: v for k, v in input_state.items() if not str(k).startswith("_")},
                "stub_outcomes": [[op, entries] for op, entries in stub_log],
                "paragraphs_hit": result.paragraphs_hit,
                "branches_hit": sorted(result.branches_hit),
                "layer": "branch_swarm",
                "target": target,
            })

            if new_paras:
                log.info(
                    "  [branch_swarm] +%d paras -> %d/%d: %s",
                    len(new_paras), len(cov.paragraphs_hit),
                    len(all_paras) if all_paras else "?",
                    sorted(new_paras)[:5],
                )
            if new_branches:
                total_branches = getattr(cov, "total_branches", 0) or 0
                log.info(
                    "  [branch_swarm] +%d branches -> %d/%d",
                    len(new_branches), len(cov.branches_hit), total_branches,
                )

        # Update memory state.
        memory_store = getattr(ctx, "memory_store", None)
        memory_state = getattr(ctx, "memory_state", None)
        if memory_store is not None and memory_state is not None:
            canonical = f"branch:{bctx.branch_key}"
            try:
                memory_store.upsert_target_status(
                    memory_state, canonical,
                    attempts_delta=1,
                    solved=feedback.branch_hit,
                    nearest_paragraph_hits=len(result.paragraphs_hit),
                    nearest_branch_hits=len(result.branches_hit),
                )
            except Exception:
                pass

    except Exception as exc:
        log.warning("  Swarm direct execution failed: %s", exc)
        feedback.error = str(exc)

    return feedback, tc_count


# ---------------------------------------------------------------------------
# Main investigation loop (3-level planner)
# ---------------------------------------------------------------------------

def investigate_branch_swarm(
    *,
    bid: int,
    direction: str,
    ctx,
    cov,
    report,
    tc_count: int,
    max_rounds: int = DEFAULT_MAX_ROUNDS,
    llm_provider=None,
    llm_model: str | None = None,
) -> tuple[SwarmJournal, int]:
    """Run the 3-level hierarchical planner for a single uncovered branch."""
    branch_key = f"{bid}:{direction}"

    journal = SwarmJournal(
        branch_key=branch_key,
        max_rounds=max_rounds,
    )

    if llm_provider is None:
        journal.final_reasoning = "no LLM provider configured"
        return journal, tc_count

    # Gather context once.
    bctx = _gather_branch_context(bid, direction, ctx, cov)
    journal.paragraph = bctx.paragraph
    journal.condition_text = bctx.condition_text

    # Level 1: Route Planner (deterministic).
    route = _plan_route(bctx, ctx)
    if route:
        log.info(
            "  Planner: route to %s: %s",
            bctx.paragraph,
            " → ".join(p for p, _ in route),
        )
    else:
        log.info("  Planner: no static route to %s (direct invocation)", bctx.paragraph)

    diagnosis: str | None = None

    for attempt in range(min(max_rounds, 2)):  # max 2 LLM calls
        log.info(
            "  Planner: %s attempt %d/%d%s",
            branch_key, attempt + 1, min(max_rounds, 2),
            " (retry with diagnosis)" if diagnosis else "",
        )

        # Level 2: Gate Solver (1 LLM call).
        input_state, stub_outcomes, reasoning = _solve_gates(
            bctx, route, llm_provider, llm_model, diagnosis,
        )

        if not input_state and not stub_outcomes:
            log.info("  Planner: empty gate solver proposal — %s", reasoning[:100])
            proposal = SpecialistProposal(
                specialist="gate_solver", reasoning=reasoning,
            )
            rnd = SwarmRound(
                round_num=attempt,
                proposals=[proposal],
                feedback=[JudgeFeedback(error="empty proposal")],
            )
            journal.rounds.append(rnd)
            break

        log.info(
            "  Planner: gate solver proposed input_keys=%s stub_keys=%s — %s",
            list(input_state.keys())[:6],
            list(stub_outcomes.keys())[:6],
            reasoning[:80],
        )

        # Level 2.5: Python forward validation.
        module = getattr(ctx, "module", None)
        py_ok, py_diagnosis = _validate_python(
            module, bctx, input_state, stub_outcomes,
        )

        if py_ok:
            log.info("  Planner: Python validation PASSED for %s", branch_key)
        else:
            log.info(
                "  Planner: Python validation failed — %s",
                (py_diagnosis or "unknown")[:150],
            )

        # Level 3: Tape Builder (deterministic).
        final_input, stub_log = _build_tape(bctx, ctx, input_state, stub_outcomes)

        log.info(
            "  Planner: tape built with %d stub entries",
            len(stub_log),
        )

        # Direct COBOL execution.
        feedback, tc_count = _execute_directly(
            ctx, cov, report, tc_count,
            final_input, stub_log, bctx,
        )

        proposal = SpecialistProposal(
            specialist="gate_solver",
            input_state=input_state,
            stub_outcomes=stub_outcomes,
            reasoning=reasoning,
            confidence=1.0 if feedback.branch_hit else 0.5,
        )
        rnd = SwarmRound(
            round_num=attempt,
            proposals=[proposal],
            synthesized_cases=[{
                "input_state": final_input,
                "stub_outcomes": stub_outcomes,
            }],
            feedback=[feedback],
            branch_hit=feedback.branch_hit,
        )
        journal.rounds.append(rnd)

        if feedback.branch_hit:
            journal.success = True
            journal.final_reasoning = f"Solved on attempt {attempt + 1}: {reasoning}"
            log.info("  Planner: SOLVED %s on attempt %d", branch_key, attempt + 1)
            _record_solution_pattern(
                ctx, bctx, [proposal],
                {"input_state": final_input, "stub_outcomes": stub_outcomes, "origin": "gate_solver"},
            )
            break

        # Use Python diagnosis for the retry.
        diagnosis = py_diagnosis
        log.info(
            "  Planner: %s not hit — %s",
            branch_key, reasoning[:100],
        )

    if not journal.success:
        journal.final_reasoning = (
            f"Exhausted {len(journal.rounds)} attempts. "
            f"Last reasoning: {reasoning if 'reasoning' in dir() else 'n/a'}"
        )

    return journal, tc_count


# ---------------------------------------------------------------------------
# Top-level entry point (matches run_branch_agent signature)
# ---------------------------------------------------------------------------

def run_branch_swarm(
    *,
    ctx,
    cov,
    report,
    tc_count: int,
    max_iterations: int = DEFAULT_MAX_ROUNDS,
    max_branches: int = DEFAULT_MAX_BRANCHES,
    llm_provider=None,
    llm_model: str | None = None,
    invocation_idx: int = 1,
) -> tuple[list[SwarmJournal], int, int]:
    """Run the hierarchical planner for the top-K stubborn branches.

    Signature-compatible with ``run_branch_agent()`` — returns
    ``(journals, n_solved, updated_tc_count)``.
    """
    if not swarm_enabled():
        return [], 0, tc_count
    if llm_provider is None:
        return [], 0, tc_count

    branch_meta = getattr(ctx, "branch_meta", None)
    if not branch_meta:
        return [], 0, tc_count

    from .branch_agent import _select_priority_branch_targets
    targets = _select_priority_branch_targets(ctx, cov, max_targets=max_branches)
    if not targets:
        log.info("Branch swarm #%d: no uncovered branches to investigate", invocation_idx)
        return [], 0, tc_count

    log.info(
        "Branch swarm #%d: investigating %d branches: %s",
        invocation_idx, len(targets), ", ".join(targets),
    )

    journals: list[SwarmJournal] = []
    n_solved = 0

    for target_key in targets:
        parts = target_key.split(":")
        if len(parts) < 3:
            continue
        try:
            bid = int(parts[1])
        except (ValueError, TypeError):
            continue
        direction = parts[2]

        journal, tc_count = investigate_branch_swarm(
            bid=bid,
            direction=direction,
            ctx=ctx,
            cov=cov,
            report=report,
            tc_count=tc_count,
            max_rounds=max_iterations,
            llm_provider=llm_provider,
            llm_model=llm_model,
        )
        journals.append(journal)
        if journal.success:
            n_solved += 1

    _persist_journals(ctx, journals)

    log.info(
        "Branch swarm #%d: %d/%d branches solved, %d attempts total",
        invocation_idx, n_solved, len(targets),
        sum(len(j.rounds) for j in journals),
    )

    return journals, n_solved, tc_count


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_COBOL_KEYWORDS = frozenset({
    "IF", "ELSE", "END-IF", "AND", "OR", "NOT", "IS", "EQUAL", "GREATER",
    "LESS", "THAN", "SPACES", "SPACE", "ZEROS", "ZERO", "ZEROES",
    "NUMERIC", "TRUE", "FALSE", "OF", "IN", "WHEN", "OTHER",
    "EVALUATE", "PERFORM", "UNTIL",
})
_VAR_RE = re.compile(r"\b([A-Z][A-Z0-9-]{1,})\b")
_QUOTED_RE = re.compile(r"'[^']*'|\"[^\"]*\"")


def _extract_condition_vars(text: str) -> list[str]:
    """Pull variable names from a condition string."""
    if not text:
        return []
    stripped = _QUOTED_RE.sub("", text)
    seen: set[str] = set()
    out: list[str] = []
    for m in _VAR_RE.finditer(stripped.upper()):
        name = m.group(1)
        if name in _COBOL_KEYWORDS or name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def _record_solution_pattern(
    ctx,
    bctx: BranchContext,
    proposals: list[SpecialistProposal],
    winning_case: dict,
) -> None:
    """Record a solution pattern for cross-branch reuse."""
    memory_state = getattr(ctx, "memory_state", None)
    if memory_state is None:
        return

    # Determine which specialist contributed the most to the win.
    winning_specialist = winning_case.get("origin", "merged")
    if winning_specialist == "history_mutation":
        winning_specialist = "history_miner"
    elif winning_specialist == "condition+stub":
        winning_specialist = "condition_cracker+stub_architect"

    pattern = SolutionPattern(
        branch_key=bctx.branch_key,
        paragraph=bctx.paragraph,
        condition_category="",  # will be filled by caller if needed
        winning_specialist=winning_specialist,
        key_variables=winning_case.get("input_state", {}),
        key_stubs=winning_case.get("stub_outcomes", {}),
    )

    meta = getattr(memory_state, "meta", None)
    if meta is None:
        memory_state.meta = {}
        meta = memory_state.meta
    patterns = meta.setdefault("solution_patterns", [])
    patterns.append(asdict(pattern))
    # Cap stored patterns.
    if len(patterns) > 50:
        meta["solution_patterns"] = patterns[-50:]

    try:
        memory_store = getattr(ctx, "memory_store", None)
        if memory_store:
            memory_store.save_state(memory_state)
    except Exception:
        pass


def _persist_journals(ctx, journals: list[SwarmJournal]) -> None:
    """Write swarm journals to the memory store."""
    memory_store = getattr(ctx, "memory_store", None)
    memory_state = getattr(ctx, "memory_state", None)
    if memory_store is None or memory_state is None:
        return

    for journal in journals:
        target_key = f"branch:{journal.branch_key}"
        try:
            status = memory_state.targets.get(target_key)
            if status is not None:
                total_iters = sum(len(r.feedback) for r in journal.rounds)
                status.agent_iterations_used = (
                    getattr(status, "agent_iterations_used", 0) or 0
                ) + total_iters
                status.agent_last_reasoning = journal.final_reasoning
                if journal.success:
                    status.solved = True
            memory_store.save_state(memory_state)
        except Exception as exc:
            log.debug("Failed to persist swarm journal for %s: %s", target_key, exc)
