"""Multi-specialist swarm for COBOL compilation fixes.

When a single-scribe fix is insufficient or gets rejected by the
challenger, this swarm runs 3 specialists in parallel (each with a
different focus), then picks the best proposal.

Specialists:
  - **Syntax Specialist**: column 72, Area A/B, periods, reserved words
  - **Semantic Specialist**: preserve business logic, don't comment out
    referenced code, don't insert GOBACK/EXIT to short-circuit
  - **Structure Specialist**: data definitions, PIC clauses, 88-level
    condition-names, record structures

Judge picks based on:
  - Rule-based quality gate (reject if mostly commenting out)
  - Does the fix address the specific error line?
  - Does it preserve surrounding context?

Entry point: ``propose_compile_fix_swarm()`` — signature-compatible
with a single-scribe LLM call, returns ``(fixes_dict, reasoning)``.
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
import re
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)


_SPECIALIST_TIMEOUT = 60  # seconds per specialist call
_MAX_WORKERS = 3


@dataclass
class CompileFixProposal:
    """One specialist's proposed fix."""

    specialist: str
    fixes: dict[int, str]  # line_number → new_content
    reasoning: str
    raw_response: str = ""


def _syntax_prompt(error_line: int, error_msg: str, context: str) -> str:
    """Syntax Specialist prompt: focus on COBOL syntax rules."""
    return (
        f"You are a COBOL syntax specialist. Fix a compilation error "
        f"focusing ONLY on syntax correctness (column boundaries, "
        f"section headers, periods, reserved words, literal formats).\n\n"
        f"Error at line {error_line}: {error_msg}\n\n"
        f"Code context:\n```cobol\n{context}\n```\n\n"
        f"Rules you enforce:\n"
        f"- Fixed-format COBOL: code in columns 8-72, Area A for headers\n"
        f"- Paragraph/section headers in Area A (col 8)\n"
        f"- Statements in Area B (col 12+)\n"
        f"- Periods end sentences (one per paragraph/IF/EVALUATE group)\n"
        f"- Reserved words: EXEC, SECTION, DIVISION cannot be identifiers\n"
        f"- Literals: quoted strings, numeric without quotes\n"
        f"- Line continuation: col 7 = '-' for continuation\n\n"
        f"Return ONLY JSON:\n"
        f'{{\n'
        f'  "{error_line}": "<corrected line>",\n'
        f'  "reasoning": "syntax rule applied"\n'
        f'}}\n'
        f"Do NOT comment out referenced code. Do NOT change business logic.\n"
    )


def _semantic_prompt(error_line: int, error_msg: str, context: str) -> str:
    """Semantic Specialist prompt: preserve business logic."""
    return (
        f"You are a COBOL semantics specialist. Fix a compilation error "
        f"while PRESERVING the program's business logic at all costs.\n\n"
        f"Error at line {error_line}: {error_msg}\n\n"
        f"Code context:\n```cobol\n{context}\n```\n\n"
        f"Your hard rules:\n"
        f"- NEVER comment out lines that are referenced elsewhere\n"
        f"- NEVER rename undefined symbols (they're referenced downstream)\n"
        f"- NEVER insert GOBACK/EXIT to short-circuit logic\n"
        f"- NEVER narrow PIC clauses to mask precision errors\n"
        f"- NEVER delete EVALUATE/WHEN clauses or IF branches\n"
        f"- Prefer adding missing definitions over removing references\n"
        f"- Prefer stubs (SELECT, FD, 01-level) over deletion\n\n"
        f"Return ONLY JSON:\n"
        f'{{\n'
        f'  "{error_line}": "<corrected line>",\n'
        f'  "reasoning": "what business logic is preserved"\n'
        f'}}\n'
    )


def _structure_prompt(error_line: int, error_msg: str, context: str) -> str:
    """Structure Specialist prompt: data definitions and 88-levels."""
    return (
        f"You are a COBOL data-structure specialist. Fix a compilation "
        f"error focusing on data definitions, PIC clauses, and "
        f"88-level condition-names.\n\n"
        f"Error at line {error_line}: {error_msg}\n\n"
        f"Code context:\n```cobol\n{context}\n```\n\n"
        f"Your expertise:\n"
        f"- 88-level condition-names cannot be MOVE targets; use "
        f"  `SET <FLAG> TO TRUE` / `SET <FLAG> TO FALSE` instead\n"
        f"- 88-level values: the VALUE clause defines activating values\n"
        f"- Group items cannot have PIC (only elementary items)\n"
        f"- Record structures: 01-level parent, 05-level children\n"
        f"- FILLER for unnamed fields\n"
        f"- REDEFINES must match parent size\n"
        f"- USAGE COMP/BINARY/DISPLAY affects storage\n"
        f"- Qualified names: `FIELD OF RECORD` or `FIELD IN RECORD`\n\n"
        f"For 'condition-name not allowed here': replace "
        f"`MOVE <src> TO <88-FLAG>` with `SET <88-FLAG> TO TRUE`.\n\n"
        f"Return ONLY JSON:\n"
        f'{{\n'
        f'  "{error_line}": "<corrected line>",\n'
        f'  "reasoning": "structural fix applied"\n'
        f'}}\n'
    )


def _parse_fix_response(text: str | None, specialist: str) -> CompileFixProposal:
    """Parse a specialist's fix response into a CompileFixProposal."""
    if not text:
        return CompileFixProposal(
            specialist=specialist, fixes={}, reasoning="empty response", raw_response="",
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
        return CompileFixProposal(
            specialist=specialist, fixes={},
            reasoning=f"could not parse: {cleaned[:150]}",
            raw_response=text[:500],
        )

    # Extract line-number → content pairs, separating metadata fields.
    fixes: dict[int, str] = {}
    reasoning = str(obj.get("reasoning", ""))[:300]
    for k, v in obj.items():
        if k == "reasoning":
            continue
        try:
            ln = int(k)
            fixes[ln] = str(v) if not str(v).endswith("\n") else str(v)
            if not fixes[ln].endswith("\n"):
                fixes[ln] = fixes[ln] + "\n"
        except (ValueError, TypeError):
            continue

    return CompileFixProposal(
        specialist=specialist, fixes=fixes,
        reasoning=reasoning or "(no reasoning)",
        raw_response=text[:500],
    )


def _score_proposal(proposal: CompileFixProposal, src_lines: list[str]) -> int:
    """Score a fix proposal. Higher is better.

    Scoring criteria (in priority order):
      - +10 if the fix address the specific error line
      - -50 if the fix is mostly commenting out (>50% of affected lines)
      - -20 if the fix adds GOBACK/EXIT (short-circuit)
      - +5 for structural keywords (SET, MOVE, PIC, 01-level)
      - 0 baseline
    """
    if not proposal.fixes:
        return -100  # empty proposal is useless

    score = 0
    commented_count = 0
    total_count = 0

    for ln, content in proposal.fixes.items():
        total_count += 1
        stripped = content.strip()
        if stripped.startswith(("*", "*>")) or stripped.startswith("      *"):
            commented_count += 1
        # Short-circuit patterns
        if re.search(r"\b(GOBACK|STOP\s+RUN|EXIT\s+PROGRAM)\b", content, re.IGNORECASE):
            # Only penalize if this wasn't a GOBACK originally
            idx = ln - 1
            if 0 <= idx < len(src_lines):
                orig = src_lines[idx]
                if not re.search(r"\b(GOBACK|STOP\s+RUN|EXIT\s+PROGRAM)\b", orig, re.IGNORECASE):
                    score -= 20
        # Structural keyword bonus
        if re.search(r"\b(SET.*TO\s+TRUE|SET.*TO\s+FALSE|01\s+[A-Z]|PIC\s+)", content, re.IGNORECASE):
            score += 5

    # Penalize commenting-out heavy fixes
    if total_count > 0 and commented_count / total_count > 0.5:
        score -= 100

    # Reward addressing the expected line (assumes caller passes one error)
    score += 10

    return score


def _judge_proposals(
    proposals: list[CompileFixProposal],
    src_lines: list[str],
) -> CompileFixProposal:
    """Pick the best proposal using the rule-based judge.

    Falls back to the proposal with the highest confidence if all are
    equally scored. Returns an empty proposal if all are unusable.
    """
    scored = [(p, _score_proposal(p, src_lines)) for p in proposals]
    scored.sort(key=lambda pair: pair[1], reverse=True)

    for p, s in scored:
        log.info(
            "  [compile-swarm] %s: score=%d fixes=%d reason=%s",
            p.specialist, s, len(p.fixes), p.reasoning[:80],
        )

    if not scored or scored[0][1] < -50:
        return CompileFixProposal(
            specialist="judge",
            fixes={},
            reasoning="all proposals rejected by judge",
        )
    return scored[0][0]


def propose_compile_fix_swarm(
    error_line: int,
    error_msg: str,
    context: str,
    src_lines: list[str],
    llm_provider,
    llm_model: str | None = None,
) -> tuple[dict[int, str], str]:
    """Run the compile-fix swarm and return the best proposal.

    Signature is compatible with a single-scribe call — returns
    ``(fixes_dict, reasoning)``. The judge picks among three parallel
    specialist proposals using a rule-based score.
    """
    if llm_provider is None:
        return {}, "no LLM provider"

    from .llm_coverage import _query_llm_sync

    def _run(name: str, prompt: str) -> CompileFixProposal:
        try:
            response, _ = _query_llm_sync(llm_provider, prompt, llm_model)
            return _parse_fix_response(response, name)
        except Exception as exc:
            log.warning("  [compile-swarm] %s failed: %s", name, exc)
            return CompileFixProposal(
                specialist=name, fixes={}, reasoning=f"LLM error: {exc}",
            )

    specialists = [
        ("syntax", _syntax_prompt(error_line, error_msg, context)),
        ("semantic", _semantic_prompt(error_line, error_msg, context)),
        ("structure", _structure_prompt(error_line, error_msg, context)),
    ]

    proposals: list[CompileFixProposal] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        futures = {pool.submit(_run, name, p): name for name, p in specialists}
        for future in concurrent.futures.as_completed(futures):
            name = futures[future]
            try:
                proposals.append(future.result(timeout=_SPECIALIST_TIMEOUT))
            except Exception as exc:
                log.warning("  [compile-swarm] %s timed out: %s", name, exc)
                proposals.append(CompileFixProposal(
                    specialist=name, fixes={}, reasoning=f"timeout: {exc}",
                ))

    winner = _judge_proposals(proposals, src_lines)
    return winner.fixes, f"[{winner.specialist}] {winner.reasoning}"


def swarm_enabled() -> bool:
    """Return False if the user has disabled the compile swarm."""
    import os
    raw = os.environ.get("SPECTER_COMPILE_SWARM", "1").strip().lower()
    return raw not in ("0", "false", "no", "off", "")
