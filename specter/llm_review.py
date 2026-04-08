"""Scribe / challenger validation for LLM-proposed source modifications.

The compile-and-fix loops in ``incremental_mock.py``, ``cobol_fix_cache.py``
and ``agent_compile.py`` ask an LLM (the *scribe*) to propose source-level
fixes for COBOL compilation errors. The scribe sometimes proposes fixes that
make the error message disappear without actually solving the underlying
problem — commenting out an active line, renaming a referenced variable,
narrowing a PIC clause, or inserting an early ``GOBACK``. These "destructive"
fixes ship out a stack-trace at first sight but quietly corrupt the program's
behaviour and often cascade into worse failures downstream.

This module wraps each scribe proposal with a *challenger* call. The
challenger is a separate LLM invocation that sees only the original window,
the proposed window, and the error being addressed, and returns a structured
verdict: ``accept`` if the fix is non-destructive, ``reject`` (with a one-line
reason) otherwise. Callers feed the rejection reason back into the scribe and
re-prompt, up to a small revision cap, before giving up on that error.

The rule-based "comment out > 50% with no stub" gate in
``incremental_mock.py`` stays as a cheap pre-filter — the challenger only sees
fixes the rule-based gate has already accepted, so we never burn an LLM call
on an obvious anti-pattern.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Iterable

log = logging.getLogger(__name__)


@dataclass
class ReviewVerdict:
    """Structured outcome from a single challenger review."""

    verdict: str             # 'accept' | 'reject' | 'unknown'
    reason: str              # one-line explanation, fed back into the scribe
    severity: str = "high"   # 'high' (block + revise) or 'low' (block + abandon)

    @property
    def accepted(self) -> bool:
        return self.verdict == "accept"


# ---------------------------------------------------------------------------
# Kill switch
# ---------------------------------------------------------------------------

def review_enabled() -> bool:
    """Return False if the user has disabled the challenger via env var.

    SPECTER_LLM_REVIEW=0 (or "false"/"no"/"off") bypasses the challenger
    everywhere. This is the global kill switch — useful when running offline
    or measuring the cost of the review path against a baseline.
    """
    raw = os.environ.get("SPECTER_LLM_REVIEW", "1").strip().lower()
    return raw not in ("0", "false", "no", "off", "")


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

# The rubric the challenger evaluates the fix against. Kept short and concrete
# so the model can return a deterministic verdict instead of monologuing.
_REVIEW_RUBRIC = """\
You are reviewing a proposed COBOL source-code fix for a GnuCOBOL compilation
error. Your only job is to decide whether the proposed fix is DESTRUCTIVE
(it makes the error message disappear without solving the real problem and
silently corrupts program behaviour) or NON-DESTRUCTIVE (a legitimate fix).

REJECT the fix when any of these are true:
- It comments out (column-7 '*') an active line that other code references.
- It renames an undefined symbol so the "not defined" error disappears,
  instead of adding the missing definition.
- It deletes or replaces a meaningful business statement (MOVE, COMPUTE,
  IF/EVALUATE, PERFORM, READ, WRITE, CALL, EXEC) without an obvious typo
  fix justification.
- It inserts GOBACK / STOP RUN / EXIT mid-paragraph to short-circuit code
  the model could not fix.
- It widens or narrows a PIC clause that already had a defined size, in a
  way that loses precision or alters semantics.
- It changes a literal value (string, numeric, or figurative constant) on
  an active line, masking the real problem.
- It removes or shortens a paragraph or section header.
- It introduces a duplicate paragraph or data definition that shadows an
  existing one.

ACCEPT the fix when it does any of these:
- Adds a missing variable definition (e.g. 01 X PIC X(...)).
- Adds a missing paragraph stub (NAME. EXIT. / NAME. CONTINUE.).
- Adds a missing terminating period or scope-end (END-IF, END-EVALUATE,
  END-READ, END-PERFORM).
- Closes a missing parenthesis or quote.
- Wraps a single line that exceeded column 72 across two valid continuations.
- Removes a single trailing garbage character that does not belong to any
  identifier.
- Inserts a SELECT / FD / FILE STATUS clause that the program references
  but does not declare.
- Fixes a typo in a verb keyword (DISPALY -> DISPLAY) or operator.
- Adds whitespace, a blank line, or column alignment without changing
  any tokens.

You MUST respond with a single JSON object on one line, no markdown:
{"verdict": "accept" | "reject", "reason": "<one short sentence>", "severity": "high" | "low"}

Use "severity":"high" for outright destructive fixes (revise and try again).
Use "severity":"low" for borderline fixes that are safer to abandon than to
keep looping on (the scribe gets one final chance).
"""


def _format_window(
    src_lines: list[str],
    line_numbers: Iterable[int],
    radius: int = 8,
) -> str:
    """Render an annotated window around the given lines for the prompt.

    Returns a string of the form::

        00120: ...some line of context...
        00121: ...some line of context...
        00122: <-- proposed change ->  PIC X(2) VALUE 'A'.
        00123: ...some line of context...

    so the challenger can see what the surrounding code looked like.
    """
    if not src_lines:
        return "(empty source)"
    targets = sorted(set(int(n) for n in line_numbers if int(n) > 0))
    if not targets:
        return "(no target lines)"

    # Build a set of line indexes (0-based) we want to render.
    visible: set[int] = set()
    for ln in targets:
        idx = ln - 1
        for i in range(max(0, idx - radius), min(len(src_lines), idx + radius + 1)):
            visible.add(i)

    out: list[str] = []
    last = -2
    for i in sorted(visible):
        if i > last + 1 and out:
            out.append("...")
        marker = "  " if (i + 1) not in targets else "*>"
        text = src_lines[i].rstrip("\n")
        out.append(f"{marker} {i + 1:5d}: {text}")
        last = i
    return "\n".join(out)


def _format_proposed(
    fixes: dict[int, str],
    radius: int = 0,
) -> str:
    """Render the proposed fix as a numbered list of new line contents."""
    if not fixes:
        return "(no fixes proposed)"
    out: list[str] = []
    for ln in sorted(fixes.keys()):
        text = fixes[ln].rstrip("\n")
        out.append(f"   {ln:5d}: {text}")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

_VERDICT_RE = re.compile(
    r'"verdict"\s*:\s*"(accept|reject|unknown)"',
    re.IGNORECASE,
)
_REASON_RE = re.compile(r'"reason"\s*:\s*"([^"]*)"')
_SEVERITY_RE = re.compile(r'"severity"\s*:\s*"(high|low)"', re.IGNORECASE)


def parse_review_response(text: str | None) -> ReviewVerdict:
    """Parse the JSON verdict the challenger returns.

    Tolerates markdown fences, leading prose, and trailing garbage so the
    same parser can handle small drift in different models. On any parse
    failure, returns ``ReviewVerdict('unknown', ...)`` which the caller
    treats as a non-blocking pass-through (we never want a parse error in
    the reviewer to *block* a fix the scribe proposed).
    """
    if not text:
        return ReviewVerdict("unknown", "empty review response", severity="low")

    cleaned = text.strip()
    cleaned = re.sub(r"^```\w*\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    # First, try a strict JSON parse.
    try:
        obj = json.loads(cleaned)
        if isinstance(obj, dict) and "verdict" in obj:
            verdict = str(obj.get("verdict", "")).strip().lower()
            reason = str(obj.get("reason", "")).strip() or "(no reason given)"
            severity = str(obj.get("severity", "high")).strip().lower()
            if verdict not in ("accept", "reject", "unknown"):
                verdict = "unknown"
            if severity not in ("high", "low"):
                severity = "high"
            return ReviewVerdict(verdict=verdict, reason=reason, severity=severity)
    except (json.JSONDecodeError, ValueError, TypeError):
        pass

    # Fall back to per-field regex extraction so we still get a usable
    # verdict from a slightly noisy response.
    m_v = _VERDICT_RE.search(cleaned)
    if not m_v:
        return ReviewVerdict("unknown", "could not parse verdict", severity="low")
    verdict = m_v.group(1).lower()
    m_r = _REASON_RE.search(cleaned)
    reason = m_r.group(1).strip() if m_r else "(no reason given)"
    m_s = _SEVERITY_RE.search(cleaned)
    severity = m_s.group(1).lower() if m_s else "high"
    return ReviewVerdict(verdict=verdict, reason=reason, severity=severity)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def review_fix(
    *,
    llm_provider,
    llm_model: str | None,
    error_summary: str,
    src_lines: list[str],
    fixes: dict[int, str],
    fix_kind: str = "compile_fix",
    audit_label: str | None = None,
) -> ReviewVerdict:
    """Run the challenger on a single proposed fix.

    Parameters
    ----------
    llm_provider, llm_model:
        Same provider/model the scribe uses. The challenger does not need a
        stronger model than the scribe to be useful — most destructive fixes
        are caught by re-reading the rubric, not by deeper reasoning.
    error_summary:
        One-line description of the compilation error this fix is targeting.
    src_lines:
        The full source-line list (post-load, pre-fix). Used to render the
        original window so the challenger can compare before/after.
    fixes:
        Mapping of ``line_number -> new_content`` exactly as the scribe
        returned it. The line numbers are 1-based and refer to ``src_lines``.
    fix_kind:
        Tag for logging — distinguishes a compile fix from a cascade
        investigation fix from a probe insertion.
    audit_label:
        Free-form label written into the log line so a human reading the
        run log can match scribe / challenger pairs.

    Returns
    -------
    ReviewVerdict
        ``accepted`` is True iff the fix passed the challenger. On any
        unrecoverable error (LLM exception, malformed response, kill
        switch active) the verdict is ``unknown`` and the caller MUST
        treat it as a pass-through (do not block the fix).
    """
    if not review_enabled():
        return ReviewVerdict(
            "unknown", "challenger disabled by SPECTER_LLM_REVIEW=0",
            severity="low",
        )
    if llm_provider is None:
        return ReviewVerdict(
            "unknown", "no LLM provider configured", severity="low",
        )
    if not fixes:
        return ReviewVerdict(
            "unknown", "empty fix dict", severity="low",
        )

    # Build the prompt — small and structured so the parser is robust.
    target_lines = list(fixes.keys())
    original_window = _format_window(src_lines, target_lines, radius=8)
    proposed_block = _format_proposed(fixes)

    prompt = (
        f"{_REVIEW_RUBRIC}\n"
        f"Error being addressed:\n  {error_summary}\n\n"
        f"Original source window (lines marked with *> are about to change):\n"
        f"```cobol\n{original_window}\n```\n\n"
        f"Proposed fix (only the lines that will change):\n"
        f"```cobol\n{proposed_block}\n```\n\n"
        f"Return only the JSON verdict object."
    )

    try:
        from .llm_coverage import _query_llm_sync
        response, _meta = _query_llm_sync(llm_provider, prompt, llm_model)
    except Exception as exc:  # noqa: BLE001 - reviewer must never crash the loop
        log.warning("  Reviewer LLM call failed: %s", exc)
        return ReviewVerdict(
            "unknown", f"reviewer call failed: {exc}", severity="low",
        )

    verdict = parse_review_response(response)
    if audit_label:
        log.info(
            "  [reviewer:%s] %s — %s (%s)",
            fix_kind, audit_label, verdict.verdict, verdict.reason,
        )
    return verdict
