"""Multi-agent swarm for stubborn uncovered branches.

Replaces the single-agent sequential loop in ``branch_agent.py`` with
four specialist agents that run in parallel, feeding proposals to a
judge that synthesizes, executes, and provides structured feedback.

Specialists (run concurrently per round):

  1. **Condition Cracker** — reads backward slice, condition text,
     variable domains, PIC clauses.  Proposes ``input_state`` values
     to satisfy the branch condition.
  2. **Path Finder** — reads call graph, gating conditions, path
     constraints.  Proposes how to *reach* the target paragraph.
  3. **Stub Architect** — reads stub mapping, fault tables, operation
     keys.  Proposes ``stub_outcomes`` and ``stub_defaults``.
  4. **History Miner** — reads test corpus, prior attempts, nearest-hit
     test cases.  Proposes targeted mutations of near-miss cases.

Judge (sequential per round):

  Receives all four proposals, synthesizes 1–3 test cases, runs Python
  first (~3 ms), promotes to COBOL only if Python shows promise, and
  builds structured feedback for the next round.

Entry point: ``run_branch_swarm()`` — signature-compatible with
``run_branch_agent()`` so ``cobol_coverage.py`` can swap it in.
"""

from __future__ import annotations

import concurrent.futures
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
_SPECIALIST_TIMEOUT = 60  # seconds per specialist LLM call

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
# Specialist prompt builders
# ---------------------------------------------------------------------------

_JSON_RESPONSE_FORMAT = (
    "Return ONLY a JSON object:\n"
    "{\n"
    '  "input_state": {"VAR_NAME": "value", ...},\n'
    '  "stub_outcomes": {"OP_KEY": [[["VAR", "VALUE"]], ...], ...},\n'
    '  "reasoning": "one-sentence explanation",\n'
    '  "confidence": 0.7\n'
    "}\n"
)


def _build_condition_cracker_prompt(
    bctx: BranchContext,
    prior_feedback: list[JudgeFeedback] | None = None,
) -> str:
    """Specialist 1: what values satisfy the branch condition?"""
    parts: list[str] = []
    parts.append(
        "You are a COBOL condition analyst. Your job is to determine what "
        "variable values would make a specific branch condition evaluate to "
        f"{'TRUE' if bctx.direction == 'T' else 'FALSE'}.\n\n"
        f"Branch {bctx.branch_key} in paragraph {bctx.paragraph}.\n"
    )
    if bctx.condition_text:
        parts.append(f"Condition: {bctx.condition_text}\n\n")

    if bctx.backward_slice_code:
        slice_lines = bctx.backward_slice_code.splitlines()
        if len(slice_lines) > 80:
            slice_lines = slice_lines[:80] + ["  # ... (truncated)"]
        parts.append(
            "Code path to this branch (Python simulator):\n```python\n"
            + "\n".join(slice_lines) + "\n```\n\n"
        )

    if bctx.var_domain_info:
        parts.append("Variables and their domains:\n")
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
                bits.append(f" (set by stub: {info['stub_op']})")
            # Surface 88-level parent relationship.
            parent_entry = bctx.parent_88_lookup.get(var)
            if parent_entry:
                parent_name, activating_value = parent_entry
                bits.append(
                    f" ** 88-level flag — set parent {parent_name} = "
                    f"{activating_value!r} to activate **"
                )
            parts.append("".join(bits) + "\n")
        parts.append("\n")

    # Show 88-level relationships for condition variables even when
    # they are not in var_domain_info (the child might not have its
    # own domain entry but the parent→child mapping still exists).
    cond_88: list[str] = []
    for var in _extract_condition_vars(bctx.condition_text):
        if var in bctx.var_domain_info:
            continue  # already shown above
        parent_entry = bctx.parent_88_lookup.get(var)
        if parent_entry:
            parent_name, activating_value = parent_entry
            cond_88.append(
                f"  {var} is an 88-level flag. "
                f"Set {parent_name} = {activating_value!r} in input_state "
                f"to activate it.\n"
            )
    if cond_88:
        parts.append("88-level flag relationships:\n")
        parts.extend(cond_88)
        parts.append("\n")

    if prior_feedback:
        parts.append("Previous round results:\n")
        for fb in prior_feedback[-2:]:
            parts.append(
                f"  reached_paragraph={fb.reached_paragraph}, "
                f"branch_hit={fb.branch_hit}, "
                f"vars={json.dumps(fb.actual_var_values, default=str)[:200]}\n"
            )
        parts.append("Try something fundamentally different.\n\n")

    parts.append(
        "Focus ONLY on the condition variables. What concrete values would "
        f"make the condition go {'TRUE' if bctx.direction == 'T' else 'FALSE'}?\n\n"
    )
    parts.append(_JSON_RESPONSE_FORMAT)
    return "".join(parts)


def _build_path_finder_prompt(
    bctx: BranchContext,
    prior_feedback: list[JudgeFeedback] | None = None,
) -> str:
    """Specialist 2: how to reach the target paragraph?"""
    parts: list[str] = []
    parts.append(
        "You are a COBOL reachability analyst. Your job is to determine what "
        "input values are needed to REACH a specific paragraph via the "
        "program's PERFORM/GO TO call chain.\n\n"
        f"Target paragraph: {bctx.paragraph}\n"
        f"Target branch: {bctx.branch_key}\n\n"
    )

    if bctx.call_graph_path:
        parts.append(f"Call graph path from entry: {' → '.join(bctx.call_graph_path)}\n\n")
    else:
        parts.append(
            "No call graph path found from the program entry to this paragraph. "
            "It may require direct paragraph invocation or specific gating "
            "conditions to reach.\n\n"
        )

    if bctx.gating_conditions:
        parts.append("Gating conditions along the path:\n")
        for gc in bctx.gating_conditions:
            neg = " (negated)" if gc.get("negated") else ""
            parts.append(
                f"  {gc.get('variable', '?')} must be in {gc.get('values', [])}%s\n" % neg
            )
        parts.append("\n")

    if bctx.var_domain_info:
        # Only show gating vars for this specialist.
        gating_var_names = {gc.get("variable", "").upper() for gc in bctx.gating_conditions}
        gating_domains = {k: v for k, v in bctx.var_domain_info.items() if k in gating_var_names}
        if gating_domains:
            parts.append("Gating variable domains:\n")
            for var, info in gating_domains.items():
                parts.append(
                    f"  {var}: type={info.get('data_type', '?')}, "
                    f"known_values={info.get('condition_literals', [])[:6]}\n"
                )
            parts.append("\n")

    if prior_feedback:
        parts.append("Previous round results:\n")
        for fb in prior_feedback[-2:]:
            parts.append(
                f"  reached_paragraph={fb.reached_paragraph}, "
                f"paragraphs_hit={fb.paragraphs_hit[:8]}\n"
            )
        parts.append("Try a different approach to reach the paragraph.\n\n")

    parts.append(
        "Propose input_state values that would navigate the program's control "
        "flow to reach the target paragraph. Focus on gating variables.\n\n"
    )
    parts.append(_JSON_RESPONSE_FORMAT)
    return "".join(parts)


def _build_stub_architect_prompt(
    bctx: BranchContext,
    prior_feedback: list[JudgeFeedback] | None = None,
) -> str:
    """Specialist 3: what stub I/O outcomes set up the right state?"""
    parts: list[str] = []
    parts.append(
        "You are a COBOL I/O stub specialist. Your job is to determine what "
        "mock I/O outcomes (file reads, SQL queries, CICS calls) would set up "
        "the right program state to reach a specific branch.\n\n"
        f"Target branch: {bctx.branch_key} in paragraph {bctx.paragraph}\n"
    )
    if bctx.condition_text:
        parts.append(f"Condition: {bctx.condition_text}\n\n")

    if bctx.stub_ops_in_slice:
        parts.append(
            "Stub operations in the code path to this branch:\n"
            f"  {', '.join(bctx.stub_ops_in_slice)}\n\n"
        )

    # Show the full ordered sequence — the program consumes stubs in
    # this exact order, so ALL preceding operations must succeed before
    # the target operation fires.
    if bctx.stub_op_sequence and len(bctx.stub_op_sequence) > 1:
        parts.append(
            "IMPORTANT — these operations fire in this order (each must have "
            "a stub_outcomes entry so the program does not abort early):\n"
        )
        for i, op in enumerate(bctx.stub_op_sequence, 1):
            parts.append(f"  {i}. {op}\n")
        parts.append(
            "Provide stub_outcomes for ALL operations in this sequence, "
            "not just the one that sets the target variable. Earlier "
            "operations typically need status '00' (success) so the "
            "program continues to the operation that matters.\n\n"
        )

    # Show stub mapping for relevant ops.
    relevant_stubs: dict[str, list[str]] = {}
    for op in bctx.stub_ops_in_slice:
        if op in bctx.stub_mapping:
            relevant_stubs[op] = bctx.stub_mapping[op]
    if relevant_stubs:
        parts.append("Stub operation → status variables:\n")
        for op, vars_ in relevant_stubs.items():
            parts.append(f"  {op} → {vars_}\n")
        parts.append("\n")

    # Show domain info for stub-returned variables.
    stub_vars = {v for vs in relevant_stubs.values() for v in vs}
    for var in sorted(stub_vars):
        info = bctx.var_domain_info.get(var.upper())
        if info:
            lits = info.get("condition_literals", [])[:6]
            v88 = info.get("valid_88_values", {})
            parent_entry = bctx.parent_88_lookup.get(var.upper())
            line = f"  {var}: known_values={lits}, 88-levels={v88}"
            if parent_entry:
                line += f" (88-flag of {parent_entry[0]}, activate with {parent_entry[1]!r})"
            parts.append(line + "\n")
    if stub_vars:
        parts.append("\n")

    parts.append("Known fault code tables:\n")
    for stype, codes in bctx.fault_tables.items():
        parts.append(f"  {stype}: {codes}\n")
    parts.append("\n")

    parts.append(
        "stub_outcomes format: {\"OP_KEY\": [[[\"VAR\", \"VALUE\"], ...], ...]}.\n"
        "Each entry in the list is consumed in order by the program. "
        "If the program reads the same operation multiple times, provide "
        "multiple entries.\n\n"
    )

    if prior_feedback:
        parts.append("Previous round results:\n")
        for fb in prior_feedback[-2:]:
            parts.append(
                f"  reached_paragraph={fb.reached_paragraph}, "
                f"branch_hit={fb.branch_hit}, error={fb.error}\n"
            )
        parts.append("Adjust stub outcomes based on what happened.\n\n")

    parts.append(_JSON_RESPONSE_FORMAT)
    return "".join(parts)


def _build_history_miner_prompt(
    bctx: BranchContext,
    prior_feedback: list[JudgeFeedback] | None = None,
) -> str:
    """Specialist 4: what mutations of near-miss cases would work?"""
    parts: list[str] = []
    parts.append(
        "You are a test-case mutation specialist. Your job is to take "
        "existing near-miss test cases and propose small, targeted changes "
        "that would flip a specific branch.\n\n"
        f"Target branch: {bctx.branch_key} in paragraph {bctx.paragraph}\n"
    )
    if bctx.condition_text:
        parts.append(f"Condition: {bctx.condition_text}\n\n")

    if bctx.nearest_hit:
        inp = bctx.nearest_hit.get("input_state") or {}
        if len(inp) > 12:
            inp = dict(list(inp.items())[:12])
        stubs = bctx.nearest_hit.get("stub_outcomes")
        stub_keys = []
        if isinstance(stubs, dict):
            stub_keys = list(stubs.keys())[:8]
        elif isinstance(stubs, list):
            stub_keys = [e[0] for e in stubs[:8] if isinstance(e, (list, tuple)) and e]
        branches = bctx.nearest_hit.get("branches_hit") or []
        parts.append(
            "Nearest-hit test case (reached the paragraph but missed the branch):\n"
            f"  input_state: {json.dumps(inp, default=str)}\n"
            f"  stub_outcomes keys: {stub_keys}\n"
            f"  branches_hit: {branches[:8]}\n\n"
        )
    else:
        parts.append(
            "No test case has reached this paragraph yet. "
            "Propose a fresh test case based on the condition.\n\n"
        )

    if bctx.solution_patterns:
        parts.append("Patterns that solved similar branches:\n")
        for pat in bctx.solution_patterns[:3]:
            parts.append(
                f"  {pat.branch_key} ({pat.condition_category}): "
                f"winning_specialist={pat.winning_specialist}, "
                f"key_vars={json.dumps(pat.key_variables, default=str)[:150]}\n"
            )
        parts.append("\n")

    if prior_feedback:
        parts.append("Previous round results:\n")
        for fb in prior_feedback[-2:]:
            parts.append(
                f"  reached_paragraph={fb.reached_paragraph}, "
                f"branch_hit={fb.branch_hit}, "
                f"vars={json.dumps(fb.actual_var_values, default=str)[:200]}\n"
            )
        parts.append("Mutate differently based on what actually happened.\n\n")

    parts.append(
        "Propose a SMALL mutation of the nearest-hit case. Change only "
        "the variables that directly affect the branch condition. "
        "Small changes to working cases beat large random proposals.\n\n"
    )
    parts.append(_JSON_RESPONSE_FORMAT)
    return "".join(parts)


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

def _parse_specialist_response(
    text: str | None,
    specialist_name: str,
) -> SpecialistProposal:
    """Parse a specialist LLM response into a SpecialistProposal."""
    if not text:
        return SpecialistProposal(
            specialist=specialist_name,
            reasoning="empty response",
            confidence=0.0,
            raw_response="",
        )

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
        return SpecialistProposal(
            specialist=specialist_name,
            reasoning=f"could not parse: {cleaned[:150]}",
            confidence=0.0,
            raw_response=text[:500],
        )

    return SpecialistProposal(
        specialist=specialist_name,
        input_state=obj.get("input_state") or {},
        stub_outcomes=obj.get("stub_outcomes") or {},
        stub_defaults=obj.get("stub_defaults"),
        reasoning=str(obj.get("reasoning", ""))[:300],
        confidence=float(obj.get("confidence", 0.5) or 0.5),
        target_paragraph=obj.get("target_paragraph"),
        raw_response=text[:500],
    )


# ---------------------------------------------------------------------------
# Specialist runners
# ---------------------------------------------------------------------------

def _run_specialist(
    name: str,
    prompt_fn,
    bctx: BranchContext,
    prior_feedback: list[JudgeFeedback] | None,
    llm_provider,
    llm_model: str | None,
) -> SpecialistProposal:
    """Run a single specialist: build prompt, call LLM, parse response."""
    from .llm_coverage import _query_llm_sync

    prompt = prompt_fn(bctx, prior_feedback)
    try:
        response, _ = _query_llm_sync(llm_provider, prompt, llm_model)
    except Exception as exc:
        log.warning("  Specialist %s LLM call failed: %s", name, exc)
        return SpecialistProposal(
            specialist=name,
            reasoning=f"LLM call failed: {exc}",
            confidence=0.0,
        )

    return _parse_specialist_response(response, name)


def _run_specialists_parallel(
    bctx: BranchContext,
    prior_feedback: list[JudgeFeedback] | None,
    llm_provider,
    llm_model: str | None,
) -> list[SpecialistProposal]:
    """Run all 4 specialists concurrently."""
    specialists = [
        ("condition_cracker", _build_condition_cracker_prompt),
        ("path_finder", _build_path_finder_prompt),
        ("stub_architect", _build_stub_architect_prompt),
        ("history_miner", _build_history_miner_prompt),
    ]

    proposals: list[SpecialistProposal] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = {
            pool.submit(
                _run_specialist, name, prompt_fn, bctx,
                prior_feedback, llm_provider, llm_model,
            ): name
            for name, prompt_fn in specialists
        }
        for future in concurrent.futures.as_completed(futures):
            name = futures[future]
            try:
                proposal = future.result(timeout=_SPECIALIST_TIMEOUT)
                proposals.append(proposal)
            except Exception as exc:
                log.warning("  Specialist %s failed: %s", name, exc)
                proposals.append(SpecialistProposal(
                    specialist=name,
                    reasoning=f"failed: {exc}",
                    confidence=0.0,
                ))
    return proposals


# ---------------------------------------------------------------------------
# Judge: synthesis + execution
# ---------------------------------------------------------------------------

def _synthesize_test_cases(
    proposals: list[SpecialistProposal],
    bctx: BranchContext,
    llm_provider=None,
    llm_model: str | None = None,
) -> list[dict]:
    """Merge specialist proposals into 1–3 concrete test cases.

    If an LLM is available, ask the judge to synthesize.  Otherwise,
    use a deterministic merge: condition_cracker's input_state for
    condition vars, path_finder's for gating vars, stub_architect's
    stubs, history_miner's mutations as a fallback.
    """
    # Deterministic merge (always available, used as fallback).
    merged_input: dict = {}
    merged_stubs: dict = {}
    merged_defaults: dict | None = None

    # Priority order: path_finder (reach first), condition_cracker
    # (satisfy condition), history_miner (near-miss mutations).
    for p in sorted(proposals, key=lambda p: {
        "path_finder": 0,
        "condition_cracker": 1,
        "stub_architect": 2,
        "history_miner": 3,
    }.get(p.specialist, 4)):
        if p.input_state:
            merged_input.update(p.input_state)
        if p.stub_outcomes:
            merged_stubs.update(p.stub_outcomes)
        if p.stub_defaults is not None:
            merged_defaults = p.stub_defaults

    cases: list[dict] = []

    # Case 1: Full merge of all proposals.
    if merged_input or merged_stubs:
        cases.append({
            "input_state": dict(merged_input),
            "stub_outcomes": dict(merged_stubs),
            "stub_defaults": merged_defaults,
            "origin": "merged",
        })

    # Case 2: Condition cracker + stub architect only (skip path/history).
    cc = next((p for p in proposals if p.specialist == "condition_cracker" and p.input_state), None)
    sa = next((p for p in proposals if p.specialist == "stub_architect" and p.stub_outcomes), None)
    if cc and sa:
        case2_input = dict(cc.input_state)
        case2_stubs = dict(sa.stub_outcomes)
        # Only add if different from case 1.
        if case2_input != merged_input or case2_stubs != merged_stubs:
            cases.append({
                "input_state": case2_input,
                "stub_outcomes": case2_stubs,
                "stub_defaults": sa.stub_defaults,
                "origin": "condition+stub",
            })

    # Case 3: History miner's mutation (if it has a distinct proposal).
    hm = next((p for p in proposals if p.specialist == "history_miner" and p.input_state), None)
    if hm:
        case3_input = dict(hm.input_state)
        case3_stubs = dict(hm.stub_outcomes) if hm.stub_outcomes else dict(merged_stubs)
        if case3_input != merged_input:
            cases.append({
                "input_state": case3_input,
                "stub_outcomes": case3_stubs,
                "stub_defaults": hm.stub_defaults or merged_defaults,
                "origin": "history_mutation",
            })

    if not cases:
        # Fallback: empty case (will fail, but gives feedback).
        cases.append({
            "input_state": {},
            "stub_outcomes": {},
            "stub_defaults": None,
            "origin": "empty_fallback",
        })

    return cases[:3]


def _execute_and_evaluate(
    case: dict,
    bctx: BranchContext,
    ctx,
    cov,
    report,
    tc_count: int,
) -> tuple[JudgeFeedback, int]:
    """Execute a synthesized test case: Python first, COBOL if promising."""
    from .cobol_coverage import _python_execute, _execute_and_save

    input_state = case.get("input_state") or {}
    stub_outcomes = case.get("stub_outcomes") or {}
    stub_defaults = case.get("stub_defaults")

    feedback = JudgeFeedback()

    # --- Python-first execution ---
    module = getattr(ctx, "module", None)
    if module:
        try:
            py_result = _python_execute(
                module, input_state, stub_outcomes, stub_defaults,
                paragraph=bctx.paragraph or None,
            )
            feedback.python_result = py_result.error is None
            feedback.paragraphs_hit = list(py_result.paragraphs_hit or [])[:10]
            feedback.branches_hit = list(py_result.branches_hit or [])[:20]
            feedback.reached_paragraph = bctx.paragraph in (py_result.paragraphs_hit or [])
            feedback.error = py_result.error

            # Check if the Python simulation hit the target branch.
            py_branch_t = f"py:{bctx.bid}:T" if bctx.direction == "T" else f"py:{bctx.bid}:F"
            py_hit = py_branch_t in (py_result.branches_hit or set())

            # Extract actual variable values from the result for feedback.
            # The Python executor returns state after execution.
            for var in list(bctx.var_domain_info.keys())[:8]:
                val = input_state.get(var)
                if val is not None:
                    feedback.actual_var_values[var] = val
        except Exception as exc:
            feedback.error = f"Python execution failed: {exc}"

    # --- COBOL execution (always attempt via _execute_and_save for real coverage) ---
    try:
        target = f"direct:{bctx.paragraph}|swarm:{bctx.branch_key}" if bctx.paragraph else f"swarm:{bctx.branch_key}"
        saved, tc_count = _execute_and_save(
            ctx, cov, input_state, stub_outcomes, stub_defaults,
            "branch_swarm", target, report, tc_count,
        )
        feedback.cobol_promoted = True
        feedback.branch_hit = bctx.branch_key in cov.branches_hit
        if feedback.branch_hit:
            feedback.reached_paragraph = True
    except Exception as exc:
        log.warning("  Swarm execution failed: %s", exc)
        feedback.error = str(exc)

    return feedback, tc_count


# ---------------------------------------------------------------------------
# Main investigation loop
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
    """Run the multi-agent swarm for a single uncovered branch."""
    branch_key = f"{bid}:{direction}"

    journal = SwarmJournal(
        branch_key=branch_key,
        max_rounds=max_rounds,
    )

    if llm_provider is None:
        journal.final_reasoning = "no LLM provider configured"
        return journal, tc_count

    # Gather context once (expensive).
    bctx = _gather_branch_context(bid, direction, ctx, cov)
    journal.paragraph = bctx.paragraph
    journal.condition_text = bctx.condition_text

    prior_feedback: list[JudgeFeedback] | None = None

    for round_num in range(max_rounds):
        log.info(
            "  Swarm: investigating %s round %d/%d",
            branch_key, round_num + 1, max_rounds,
        )

        # Run all 4 specialists in parallel.
        proposals = _run_specialists_parallel(
            bctx, prior_feedback, llm_provider, llm_model,
        )

        # Log specialist results.
        for p in proposals:
            log.info(
                "    %s: confidence=%.1f input_keys=%s stub_keys=%s",
                p.specialist, p.confidence,
                list(p.input_state.keys())[:5],
                list(p.stub_outcomes.keys())[:5],
            )

        # Synthesize 1-3 test cases.
        cases = _synthesize_test_cases(proposals, bctx, llm_provider, llm_model)

        # Execute each synthesized case.
        round_feedback: list[JudgeFeedback] = []
        round_hit = False
        for case in cases:
            fb, tc_count = _execute_and_evaluate(
                case, bctx, ctx, cov, report, tc_count,
            )
            round_feedback.append(fb)
            if fb.branch_hit:
                round_hit = True
                # Record which specialist contributed the winning input.
                _record_solution_pattern(ctx, bctx, proposals, case)

        rnd = SwarmRound(
            round_num=round_num,
            proposals=proposals,
            synthesized_cases=cases,
            feedback=round_feedback,
            branch_hit=round_hit,
        )
        journal.rounds.append(rnd)

        if round_hit:
            winning_reasons = [p.reasoning for p in proposals if p.input_state or p.stub_outcomes]
            journal.success = True
            journal.final_reasoning = (
                f"Solved on round {round_num + 1}: "
                + "; ".join(winning_reasons[:2])
            )
            log.info("  Swarm: SOLVED %s on round %d", branch_key, round_num + 1)
            break

        # Feed results back for next round.
        prior_feedback = round_feedback
        log.info(
            "  Swarm: %s not hit on round %d — %s",
            branch_key, round_num + 1,
            "; ".join(
                f"{p.specialist}:{p.reasoning[:50]}" for p in proposals if p.reasoning
            )[:200],
        )

    if not journal.success:
        all_reasons = []
        for rnd in journal.rounds:
            for p in rnd.proposals:
                if p.reasoning:
                    all_reasons.append(f"{p.specialist}: {p.reasoning[:80]}")
        journal.final_reasoning = (
            f"Exhausted {max_rounds} rounds. "
            f"Approaches: {'; '.join(all_reasons[:4])}"
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
    """Run the multi-agent swarm for the top-K stubborn branches.

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
        "Branch swarm #%d: %d/%d branches solved, %d rounds total",
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
