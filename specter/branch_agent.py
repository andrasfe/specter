"""Inner agent loop for stubborn uncovered branches.

When the coverage loop plateaus and no strategy can reach a specific
branch, this module runs a focused, multi-turn LLM investigation:

  1. Gather context — backward slice, condition text, variable domains,
     what's already been tried.
  2. Ask the LLM to propose an input_state + stub_outcomes that would
     flip the target branch.
  3. Execute the proposal through the normal test-case path.
  4. If the branch wasn't hit, feed the execution result back to the
     LLM and ask it to try a different approach.
  5. Repeat up to ``max_iterations`` times.
  6. Journal every attempt (proposal, reasoning, execution trace) so
     the next run or a human reviewer can pick up where this left off.

The agent is invoked from ``_run_agentic_loop`` in ``cobol_coverage.py``
when ``stale_rounds`` crosses a configurable threshold. It targets the
top-K highest-priority uncovered branches (selected by
``_select_priority_branch_targets``) and runs the inner loop for each.
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
class AgentIteration:
    """One turn of the inner agent loop."""

    iteration: int
    prompt_summary: str = ""
    llm_response_raw: str = ""
    proposed_input: dict = field(default_factory=dict)
    proposed_stubs: dict = field(default_factory=dict)
    reasoning: str = ""
    execution_result: dict = field(default_factory=dict)
    branch_hit: bool = False


@dataclass
class BranchAgentJournal:
    """Full record of an inner agent investigation for one branch."""

    branch_key: str
    paragraph: str = ""
    condition_text: str = ""
    max_iterations: int = 3
    iterations: list[AgentIteration] = field(default_factory=list)
    success: bool = False
    final_reasoning: str = ""


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Default maximum number of LLM turns per branch investigation.
DEFAULT_MAX_ITERATIONS = 3

# Default number of branches to investigate per agent invocation.
DEFAULT_MAX_BRANCHES_PER_INVOCATION = 3

# Maximum total agent invocations per coverage run.
DEFAULT_MAX_INVOCATIONS = 3

# Stale-round threshold before the agent kicks in.
DEFAULT_STALE_TRIGGER = 3


def agent_enabled() -> bool:
    """Return False if the user has disabled the branch agent."""
    raw = os.environ.get("SPECTER_BRANCH_AGENT", "1").strip().lower()
    return raw not in ("0", "false", "no", "off", "")


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

def _build_agent_prompt(
    *,
    bid: int,
    direction: str,
    paragraph: str,
    condition_text: str,
    backward_slice_code: str,
    var_domains: dict[str, dict[str, Any]],
    nearest_hit: dict | None,
    prior_iterations: list[AgentIteration],
    total_attempts: int,
) -> str:
    """Build the LLM prompt for one iteration of the agent loop.

    The prompt is grounded in actual code (the backward slice), names
    the exact branch and condition, includes what was already tried,
    and requests structured JSON output.
    """
    parts: list[str] = []

    parts.append(
        f"You are debugging a COBOL program's branch coverage.\n"
        f"Branch {bid}:{direction} in paragraph {paragraph} has never been covered"
        f" in {total_attempts} test cases.\n"
    )

    if condition_text:
        parts.append(f"The condition on this branch is:\n  {condition_text}\n")

    if backward_slice_code:
        # Truncate the slice to ~120 lines to stay within context limits.
        slice_lines = backward_slice_code.splitlines()
        if len(slice_lines) > 120:
            slice_lines = slice_lines[:120]
            slice_lines.append("  # ... (truncated)")
        parts.append(
            "Here is the minimal code path leading to this branch "
            "(generated Python simulator):\n"
            "```python\n"
            + "\n".join(slice_lines) + "\n"
            "```\n"
        )

    if var_domains:
        parts.append("Variables in the condition and their domains:\n")
        for var_name, info in var_domains.items():
            bits = [f"  {var_name}:"]
            if info.get("classification"):
                bits.append(f" classification={info['classification']}")
            if info.get("data_type"):
                bits.append(f" type={info['data_type']}")
            if info.get("max_length"):
                bits.append(f" len={info['max_length']}")
            if info.get("condition_literals"):
                bits.append(f" literals={info['condition_literals'][:6]}")
            if info.get("valid_88_values"):
                bits.append(f" 88-values={info['valid_88_values']}")
            if info.get("stub_op"):
                bits.append(f" set-by-stub={info['stub_op']}")
            parts.append("".join(bits) + "\n")
        parts.append("")

    if nearest_hit:
        parts.append("The nearest test case that reached this paragraph:\n")
        # Truncate to relevant vars only.
        inp = nearest_hit.get("input_state") or {}
        if len(inp) > 15:
            inp = dict(list(inp.items())[:15])
        parts.append(f"  input_state: {json.dumps(inp, default=str)}\n")
        stubs = nearest_hit.get("stub_outcomes")
        if stubs:
            if isinstance(stubs, dict):
                stub_preview = list(stubs.keys())[:6]
            elif isinstance(stubs, list):
                stub_preview = [e[0] for e in stubs[:6] if isinstance(e, (list, tuple)) and e]
            else:
                stub_preview = []
            parts.append(f"  stub_outcomes keys: {stub_preview}\n")
        branches = nearest_hit.get("branches_hit") or []
        if branches:
            parts.append(f"  branches_hit: {branches[:10]}\n")
        parts.append("")

    if prior_iterations:
        parts.append("Previous agent attempts on this branch:\n")
        for it in prior_iterations:
            parts.append(
                f"  Attempt {it.iteration + 1}:\n"
                f"    proposed input: {json.dumps(it.proposed_input, default=str)[:300]}\n"
                f"    proposed stubs: {json.dumps(it.proposed_stubs, default=str)[:300]}\n"
                f"    result: {json.dumps(it.execution_result, default=str)[:300]}\n"
                f"    reasoning: {it.reasoning}\n"
                f"    branch hit: {it.branch_hit}\n"
            )
        parts.append(
            "The above attempts did NOT flip the target branch. "
            "You MUST try something fundamentally different.\n"
        )

    parts.append(
        f"\nPropose a test case that would flip branch {bid}:{direction}.\n"
        "Return ONLY a JSON object:\n"
        "{\n"
        '  "input_state": {"VAR_NAME": "value", ...},\n'
        '  "stub_outcomes": {"OP_KEY": [[["VAR", "VALUE"]], ...], ...},\n'
        '  "reasoning": "one-sentence explanation of why this should work"\n'
        "}\n\n"
        "Focus on the variables that directly control the branch condition.\n"
        "If the branch depends on a stub-returned value, set stub_outcomes "
        "for that operation key. If it depends on a sequence of operations "
        "(e.g. OPEN then READ), provide stub_outcomes for all of them "
        "in the order the program consumes them.\n"
    )

    return "".join(parts)


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

def parse_agent_response(text: str | None) -> tuple[dict, dict, str]:
    """Parse the LLM's proposed test case from its response.

    Returns (input_state, stub_outcomes, reasoning).
    On any parse failure, returns empty dicts and a reason string.
    """
    if not text:
        return {}, {}, "empty response"

    cleaned = text.strip()
    # Strip markdown fences.
    cleaned = re.sub(r"^```\w*\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    # Try strict JSON parse first.
    try:
        obj = json.loads(cleaned)
        if isinstance(obj, dict):
            return (
                obj.get("input_state") or {},
                obj.get("stub_outcomes") or {},
                str(obj.get("reasoning", "")).strip() or "(no reasoning)",
            )
    except (json.JSONDecodeError, ValueError, TypeError):
        pass

    # Try to find a JSON object in the response (LLMs sometimes add prose).
    m = re.search(r"\{[\s\S]*\}", cleaned)
    if m:
        try:
            obj = json.loads(m.group(0))
            if isinstance(obj, dict):
                return (
                    obj.get("input_state") or {},
                    obj.get("stub_outcomes") or {},
                    str(obj.get("reasoning", "")).strip() or "(no reasoning)",
                )
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

    return {}, {}, f"could not parse response: {cleaned[:200]}"


# ---------------------------------------------------------------------------
# Main investigation loop
# ---------------------------------------------------------------------------

def investigate_branch(
    *,
    bid: int,
    direction: str,
    ctx,
    cov,
    report,
    tc_count: int,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    llm_provider=None,
    llm_model: str | None = None,
) -> tuple[BranchAgentJournal, int]:
    """Run the inner agent loop for a single uncovered branch.

    Returns (journal, updated_tc_count).
    """
    from .llm_coverage import _query_llm_sync
    from .backward_slicer import backward_slice

    branch_key = f"{bid}:{direction}"
    branch_meta = getattr(ctx, "branch_meta", {}) or {}
    meta = branch_meta.get(str(bid)) or branch_meta.get(bid) or {}
    paragraph = str(meta.get("paragraph", "")).upper()
    condition_text = str(meta.get("condition", ""))

    journal = BranchAgentJournal(
        branch_key=branch_key,
        paragraph=paragraph,
        condition_text=condition_text,
        max_iterations=max_iterations,
    )

    if llm_provider is None:
        journal.final_reasoning = "no LLM provider configured"
        return journal, tc_count

    # Gather context once (expensive operations).
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

    # Build variable domain info for the prompt.
    domains = getattr(ctx, "domains", {}) or {}
    stub_mapping = getattr(ctx, "stub_mapping", {}) or {}
    var_to_stub: dict[str, str] = {}
    for op_key, status_vars in stub_mapping.items():
        for v in status_vars:
            var_to_stub.setdefault(v.upper(), op_key)

    condition_vars = _extract_condition_vars(condition_text)
    var_domain_info: dict[str, dict[str, Any]] = {}
    for v in condition_vars:
        dom = domains.get(v)
        if dom is None:
            continue
        var_domain_info[v] = {
            "classification": getattr(dom, "classification", ""),
            "data_type": getattr(dom, "data_type", ""),
            "max_length": getattr(dom, "max_length", 0),
            "condition_literals": list(getattr(dom, "condition_literals", []))[:8],
            "valid_88_values": dict(getattr(dom, "valid_88_values", {})),
            "stub_op": var_to_stub.get(v, ""),
        }

    # Find nearest hit.
    nearest_hit = _find_nearest_hit(cov.test_cases, bid, paragraph)

    # Count total prior attempts from all strategies.
    total_attempts = sum(
        1 for tc in cov.test_cases
        if paragraph and paragraph in (tc.get("paragraphs_hit") or [])
    )

    prior_iterations: list[AgentIteration] = []

    for iteration_num in range(max_iterations):
        log.info(
            "  Branch agent: investigating %s iteration %d/%d",
            branch_key, iteration_num + 1, max_iterations,
        )

        prompt = _build_agent_prompt(
            bid=bid,
            direction=direction,
            paragraph=paragraph,
            condition_text=condition_text,
            backward_slice_code=slice_code,
            var_domains=var_domain_info,
            nearest_hit=nearest_hit,
            prior_iterations=prior_iterations,
            total_attempts=total_attempts,
        )

        # Call the LLM.
        try:
            response, _ = _query_llm_sync(llm_provider, prompt, llm_model)
        except Exception as exc:
            log.warning("  Branch agent LLM call failed: %s", exc)
            iteration = AgentIteration(
                iteration=iteration_num,
                prompt_summary=prompt[:200],
                reasoning=f"LLM call failed: {exc}",
            )
            prior_iterations.append(iteration)
            journal.iterations.append(iteration)
            continue

        # Parse the response.
        proposed_input, proposed_stubs, reasoning = parse_agent_response(response)

        if not proposed_input and not proposed_stubs:
            log.info("  Branch agent: empty proposal — %s", reasoning[:100])
            iteration = AgentIteration(
                iteration=iteration_num,
                prompt_summary=prompt[:200],
                llm_response_raw=response[:500] if response else "",
                reasoning=reasoning,
            )
            prior_iterations.append(iteration)
            journal.iterations.append(iteration)
            continue

        # Execute the proposed test case.
        try:
            from .cobol_coverage import _execute_and_save
            saved, tc_count = _execute_and_save(
                ctx, cov, proposed_input, proposed_stubs, None,
                "branch_agent", f"agent:{branch_key}", report, tc_count,
            )
        except Exception as exc:
            log.warning("  Branch agent execution failed: %s", exc)
            iteration = AgentIteration(
                iteration=iteration_num,
                prompt_summary=prompt[:200],
                llm_response_raw=response[:500] if response else "",
                proposed_input=proposed_input,
                proposed_stubs=proposed_stubs,
                reasoning=reasoning,
                execution_result={"error": str(exc)},
            )
            prior_iterations.append(iteration)
            journal.iterations.append(iteration)
            continue

        # Check if the target branch was hit.
        hit = branch_key in cov.branches_hit

        # Build an execution summary for the journal.
        # The most recent test case in cov.test_cases is the one we just ran
        # (if it was saved).
        exec_result: dict[str, Any] = {"saved": saved, "branch_hit": hit}
        if cov.test_cases:
            last_tc = cov.test_cases[-1]
            exec_result["rc"] = last_tc.get("return_code", "?")
            exec_result["paragraphs_hit"] = last_tc.get("paragraphs_hit", [])[:10]
            exec_result["branches_hit"] = [
                b for b in (last_tc.get("branches_hit") or [])
                if isinstance(b, str) and b.split(":")[0] == str(bid)
            ][:5]

        iteration = AgentIteration(
            iteration=iteration_num,
            prompt_summary=prompt[:200],
            llm_response_raw=response[:500] if response else "",
            proposed_input=proposed_input,
            proposed_stubs=proposed_stubs,
            reasoning=reasoning,
            execution_result=exec_result,
            branch_hit=hit,
        )
        prior_iterations.append(iteration)
        journal.iterations.append(iteration)

        if hit:
            log.info(
                "  Branch agent: SOLVED %s on iteration %d — %s",
                branch_key, iteration_num + 1, reasoning[:100],
            )
            journal.success = True
            journal.final_reasoning = f"Solved on iteration {iteration_num + 1}: {reasoning}"
            break

        log.info(
            "  Branch agent: %s not hit — %s",
            branch_key, reasoning[:100],
        )

    if not journal.success:
        reasons = [it.reasoning for it in journal.iterations if it.reasoning]
        journal.final_reasoning = (
            f"Exhausted {max_iterations} iterations. "
            f"Approaches tried: {'; '.join(reasons[:3])}"
        )

    return journal, tc_count


# ---------------------------------------------------------------------------
# Top-level entry point (called from coverage loop)
# ---------------------------------------------------------------------------

def run_branch_agent(
    *,
    ctx,
    cov,
    report,
    tc_count: int,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    max_branches: int = DEFAULT_MAX_BRANCHES_PER_INVOCATION,
    llm_provider=None,
    llm_model: str | None = None,
    invocation_idx: int = 1,
) -> tuple[list[BranchAgentJournal], int, int]:
    """Run the inner agent loop for the top-K stubborn branches.

    Returns (journals, n_solved, updated_tc_count).
    """
    if not agent_enabled():
        return [], 0, tc_count

    if llm_provider is None:
        return [], 0, tc_count

    branch_meta = getattr(ctx, "branch_meta", None)
    if not branch_meta:
        return [], 0, tc_count

    # Pick the top-K uncovered branches.
    targets = _select_priority_branch_targets(ctx, cov, max_targets=max_branches)
    if not targets:
        log.info("Branch agent #%d: no uncovered branches to investigate", invocation_idx)
        return [], 0, tc_count

    log.info(
        "Branch agent #%d: investigating %d branches: %s",
        invocation_idx, len(targets),
        ", ".join(targets),
    )

    journals: list[BranchAgentJournal] = []
    n_solved = 0

    for target_key in targets:
        # Parse "branch:42:T" → bid=42, direction="T"
        parts = target_key.split(":")
        if len(parts) < 3:
            continue
        try:
            bid = int(parts[1])
        except (ValueError, TypeError):
            continue
        direction = parts[2]

        journal, tc_count = investigate_branch(
            bid=bid,
            direction=direction,
            ctx=ctx,
            cov=cov,
            report=report,
            tc_count=tc_count,
            max_iterations=max_iterations,
            llm_provider=llm_provider,
            llm_model=llm_model,
        )
        journals.append(journal)
        if journal.success:
            n_solved += 1

    # Persist journals to memory store.
    _persist_journals(ctx, journals)

    log.info(
        "Branch agent #%d: %d/%d branches solved, %d iterations total",
        invocation_idx,
        n_solved,
        len(targets),
        sum(len(j.iterations) for j in journals),
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


def _extract_condition_vars(text: str) -> list[str]:
    """Pull variable names from a condition string."""
    if not text:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for m in _VAR_RE.finditer(text.upper()):
        name = m.group(1)
        if name in _COBOL_KEYWORDS or name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def _find_nearest_hit(
    test_cases: list[dict],
    bid: int,
    paragraph: str,
) -> dict | None:
    """Find the test case that came closest to the target branch."""
    if not test_cases or not paragraph:
        return None
    best: dict | None = None
    best_score = -1
    for tc in test_cases:
        paras = tc.get("paragraphs_hit") or []
        if paragraph not in paras:
            continue
        branches = tc.get("branches_hit") or []
        score = sum(
            1 for b in branches
            if isinstance(b, str) and b.split(":")[0] == str(bid)
        )
        total = len(branches)
        combined = score * 100 + total
        if combined > best_score:
            best_score = combined
            best = tc
    return best


def _select_priority_branch_targets(
    ctx,
    cov,
    max_targets: int = DEFAULT_MAX_BRANCHES_PER_INVOCATION,
) -> list[str]:
    """Select the top-K highest-priority uncovered branches.

    Extends ``_select_priority_branch_target`` (which returns 1) to
    return multiple targets for the branch agent to investigate in
    parallel within a single invocation.
    """
    branch_meta = getattr(ctx, "branch_meta", None) or {}
    memory_state = getattr(ctx, "memory_state", None)
    target_status = getattr(memory_state, "targets", {}) if memory_state is not None else {}

    scored: list[tuple[int, int, int, str]] = []
    for raw_bid in branch_meta:
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
            # Deprioritize branches that the agent already investigated
            # (so it moves on to fresh targets rather than re-visiting).
            agent_used = int(getattr(status, "agent_iterations_used", 0) or 0) if status else 0
            scored.append((solved, agent_used, attempts, -nearest, tkey))

    if not scored:
        return []
    scored.sort()
    return [s[-1] for s in scored[:max_targets]]


def _persist_journals(ctx, journals: list[BranchAgentJournal]) -> None:
    """Write agent journals to the memory store for cross-run persistence."""
    memory_store = getattr(ctx, "memory_store", None)
    memory_state = getattr(ctx, "memory_state", None)
    if memory_store is None or memory_state is None:
        return

    for journal in journals:
        target_key = f"branch:{journal.branch_key}"
        try:
            # Upsert target status with agent fields.
            status = memory_state.targets.get(target_key)
            if status is not None:
                status.agent_iterations_used = (
                    getattr(status, "agent_iterations_used", 0) or 0
                ) + len(journal.iterations)
                status.agent_last_reasoning = journal.final_reasoning
                if journal.success:
                    status.solved = True
            memory_store.save_state(memory_state)
        except Exception as exc:
            log.debug("Failed to persist agent journal for %s: %s", target_key, exc)
