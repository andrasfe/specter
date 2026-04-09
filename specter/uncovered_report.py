"""Post-run diagnostic report for branches the coverage loop could not hit.

When the agentic loop finishes, any branch that remains uncovered is a
piece of evidence: what condition was on the branch, which strategies
tried to hit it, which paragraph contains it, what the nearest-miss
test case looked like, and — when the pattern is recognisable — what
the most likely next step is. The raw data for all of that lives in
``CoverageState`` and ``StrategyContext`` at the moment the loop exits,
but it is not exposed anywhere that a human can dig into later.

This module walks the end-of-run state and writes two sibling files
next to the test store (or wherever the CLI asks):

  * ``<stem>.uncovered.json`` — structured report for tooling and future
    automation. Each entry documents one uncovered branch direction.
  * ``<stem>.uncovered.md`` — human-readable companion that leads with
    the paragraphs that have the most uncovered branches and groups by
    condition category so a reviewer can spot patterns at a glance.

The report is intentionally derivable — nothing here gates the main
loop, nothing here writes into the coverage state. If this module
crashes, the loop still finishes and the test store is still valid.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class AttemptSummary:
    """How a given strategy tried to hit an uncovered branch.

    Attempts are reconstructed from the saved test-case list in the
    coverage state. Each test case records its originating strategy
    and a target string; we match by paragraph (the strongest signal
    we have) and by explicit bid-in-target when the strategy formats
    its target that way (e.g. ``concolic:42``, ``chain-if:10:T``).
    """

    strategy: str
    count: int = 0
    direct_bid_match: int = 0   # target string mentioned the bid explicitly
    paragraph_match: int = 0    # test case just happened to reach the paragraph


@dataclass
class NearestHit:
    """A saved test case that came closest to hitting the target branch.

    "Closest" here is a coarse measure: the test case that reached the
    uncovered branch's *paragraph* and saved the most overall branches
    in that paragraph. It is not guaranteed to be arithmetically
    nearest, but it gives a reviewer a concrete starting state to
    perturb by hand.
    """

    test_case_id: str | None
    strategy: str
    target: str
    input_state: dict
    stub_outcomes: dict | None
    paragraphs_hit: list[str] = field(default_factory=list)
    branches_hit_in_same_paragraph: list[str] = field(default_factory=list)


@dataclass
class UncoveredBranchDetail:
    """One uncovered branch direction — all we know about it."""

    # --- identity ---
    branch_id: int
    direction: str             # 'T' or 'F'
    branch_key: str            # e.g. "42:T"
    paragraph: str

    # --- condition text & location ---
    source_file: str
    source_line: int
    condition_text: str
    condition_category: str    # see _classify_condition() below

    # --- semantic dependencies ---
    condition_vars: list[str] = field(default_factory=list)
    var_classifications: dict[str, str] = field(default_factory=dict)
    var_literals: dict[str, list] = field(default_factory=dict)
    var_88_values: dict[str, dict[str, Any]] = field(default_factory=dict)
    stub_return_vars: dict[str, str] = field(default_factory=dict)  # var -> op_key

    # --- reachability analysis ---
    gating_paragraphs: list[str] = field(default_factory=list)
    gating_conditions: list[str] = field(default_factory=list)

    # --- attempts ---
    total_attempts: int = 0
    attempts_by_strategy: list[AttemptSummary] = field(default_factory=list)
    nearest_hit: NearestHit | None = None

    # --- next steps ---
    hints: list[str] = field(default_factory=list)

    # --- parent lookup for 88-level children ---
    # Maps an 88-level child name (e.g. "APPL-AOK") to its parent
    # variable and activating value ("APPL-RESULT", 0). Used by
    # _generate_hints when the condition variable IS the child, so
    # the hint can point the reviewer at the parent to set.
    parent_88_lookup: dict[str, tuple[str, Any]] = field(default_factory=dict)


@dataclass
class UncoveredReport:
    """The full report — header metadata + one entry per uncovered branch."""

    program_id: str
    total_branches: int
    covered_branches: int
    uncovered_branches: int
    total_test_cases: int
    elapsed_seconds: float
    generated_at: str
    branches: list[UncoveredBranchDetail] = field(default_factory=list)
    summary_by_category: dict[str, int] = field(default_factory=dict)
    summary_by_paragraph: dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Condition extraction from COBOL source
# ---------------------------------------------------------------------------

_PROBE_RE = re.compile(r"@@B:(\d+):(T|F|W\d+)")
_PARA_RE = re.compile(r"^\s{7}([A-Z0-9][A-Z0-9_-]*)\s*\.\s*$")
_IF_RE = re.compile(r"\b(IF|WHEN|PERFORM\s+UNTIL|EVALUATE)\b", re.IGNORECASE)


def _extract_branch_conditions(mock_source_path: Path) -> dict[str, dict[str, Any]]:
    """Scan an instrumented mock .cbl file and recover condition text per bid.

    Returns a dict keyed by the branch id (as a string) with fields:

        paragraph         — the enclosing paragraph name
        line              — 1-based line number of the probe
        condition_text    — the nearest preceding IF/WHEN/PERFORM UNTIL line
        condition_type    — the COBOL keyword that introduced the condition

    The extractor walks the source top to bottom, tracks the current
    paragraph, and when it finds a ``DISPLAY '@@B:<bid>:<dir>'`` probe
    it looks backward for the closest COBOL condition-bearing verb.
    The walk is deliberately line-based — it is cheap, handles the
    vast majority of probe placements (IF / inline IF / EVALUATE /
    WHEN / PERFORM UNTIL), and gracefully degrades to an empty
    condition_text when the source is exotic enough to confuse it.
    """
    if not mock_source_path.exists():
        return {}

    try:
        lines = mock_source_path.read_text(errors="replace").splitlines()
    except Exception as exc:  # noqa: BLE001
        log.debug("Could not read mock source %s: %s", mock_source_path, exc)
        return {}

    result: dict[str, dict[str, Any]] = {}
    current_para = ""

    for idx, line in enumerate(lines):
        # Ignore fixed-format comments.
        if len(line) > 6 and line[6] in ("*", "/"):
            continue

        m_para = _PARA_RE.match(line)
        if m_para:
            current_para = m_para.group(1).upper()
            continue

        m_probe = _PROBE_RE.search(line)
        if not m_probe:
            continue

        bid = m_probe.group(1)
        direction = m_probe.group(2)
        # We may see both :T and :F probes for the same bid — the first
        # one we hit gives us the condition text.
        if bid in result:
            continue

        # Walk backward up to 10 lines to find the controlling IF/WHEN.
        condition_text = ""
        condition_type = "unknown"
        for j in range(idx - 1, max(-1, idx - 12), -1):
            prev = lines[j]
            if len(prev) > 6 and prev[6] in ("*", "/"):
                continue
            stripped = prev[6:72] if len(prev) > 7 else prev
            stripped = stripped.strip()
            if not stripped:
                continue
            m_if = _IF_RE.search(stripped)
            if m_if:
                condition_text = stripped
                condition_type = m_if.group(1).upper().replace("  ", " ")
                break

        result[bid] = {
            "paragraph": current_para,
            "line": idx + 1,
            "condition_text": condition_text,
            "condition_type": condition_type,
            "direction_seen": direction,
        }

    return result


# ---------------------------------------------------------------------------
# Condition classification
# ---------------------------------------------------------------------------

# Order matters: more specific patterns first.
_CLASSIFIERS: list[tuple[str, re.Pattern]] = [
    ("evaluate_when", re.compile(r"^WHEN\b", re.IGNORECASE)),
    ("loop_until", re.compile(r"PERFORM\s+UNTIL\b", re.IGNORECASE)),
    ("evaluate_head", re.compile(r"^EVALUATE\b", re.IGNORECASE)),
    ("file_status_eq", re.compile(
        r"\b[A-Z][A-Z0-9-]*-?STATUS\b\s*(?:=|EQUAL(?:\s+TO)?)\s*['\"]\d\d['\"]",
        re.IGNORECASE,
    )),
    ("status_flag_88", re.compile(
        r"^\s*IF\s+[A-Z][A-Z0-9-]*\s*(?:\.|$)",
        re.IGNORECASE,
    )),
    ("compound_and_or", re.compile(
        r"\b(AND|OR)\b",
        re.IGNORECASE,
    )),
    ("numeric_cmp", re.compile(
        r"[<>]=?|\bGREATER\b|\bLESS\b",
        re.IGNORECASE,
    )),
    ("not_numeric", re.compile(r"\bNOT\s+NUMERIC\b", re.IGNORECASE)),
    ("string_eq", re.compile(
        r"=\s*['\"][^'\"]*['\"]",
    )),
]


def _classify_condition(text: str) -> str:
    """Map a condition string to a short category label.

    Categories are intentionally coarse — they drive hint generation
    and summary grouping in the Markdown companion report, not a
    formal typology of COBOL conditions.
    """
    if not text:
        return "unknown"
    for label, pattern in _CLASSIFIERS:
        if pattern.search(text):
            return label
    return "other"


# ---------------------------------------------------------------------------
# Variable extraction from condition text
# ---------------------------------------------------------------------------

_COBOL_KEYWORDS = frozenset({
    "IF", "ELSE", "END-IF", "EVALUATE", "WHEN", "OTHER", "END-EVALUATE",
    "PERFORM", "UNTIL", "VARYING", "FROM", "BY", "TO", "TIMES",
    "AND", "OR", "NOT", "IS", "EQUAL", "GREATER", "LESS", "THAN",
    "SPACES", "SPACE", "ZEROS", "ZERO", "ZEROES", "HIGH-VALUES",
    "HIGH-VALUE", "LOW-VALUES", "LOW-VALUE", "QUOTES", "QUOTE",
    "NULL", "NULLS", "NUMERIC", "ALPHABETIC", "TRUE", "FALSE",
    "OF", "IN", "THRU", "THROUGH", "DISPLAY", "CONTINUE", "EXIT",
})

_VAR_RE = re.compile(r"\b([A-Z][A-Z0-9-]*)\b")


def _extract_condition_vars(text: str) -> list[str]:
    """Pull identifier-shaped tokens out of a condition string.

    Filters COBOL keywords and very short names (< 2 chars) so the
    output is a reasonable set of variable name candidates. Does not
    attempt to resolve qualified names (``FIELD OF RECORD``) — the
    first token of each qualifier is kept, which is enough for the
    reporter's downstream lookups.
    """
    if not text:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for match in _VAR_RE.finditer(text):
        name = match.group(1).upper()
        if name in _COBOL_KEYWORDS:
            continue
        if len(name) < 2:
            continue
        if name.isdigit():
            continue
        if name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


# ---------------------------------------------------------------------------
# Attempt reconstruction from the test-case list
# ---------------------------------------------------------------------------

_BID_IN_TARGET_RE = re.compile(r"(?:chain-if:|:|^)(\d+):([TFW]\d?)")


def _count_attempts(
    test_cases: list[dict],
    bid: int,
    direction: str,
    paragraph: str,
) -> tuple[int, list[AttemptSummary], NearestHit | None]:
    """Reconstruct best-effort attempts for a single uncovered branch.

    The coverage loop does not record "this test case targeted branch
    X" explicitly, so we infer:

      * **Direct bid match**: the target string (e.g.
        ``"direct:1000-GET|chain-if:10:T"`` or ``"concolic:42"``)
        mentions the exact bid — that's a strong signal the strategy
        meant to hit this branch.
      * **Paragraph match**: the test case's ``paragraphs_hit`` list
        contains the uncovered branch's paragraph — the test case
        reached the code but did not flip the branch. Weaker but
        still useful, especially for counting denominator.

    Also picks a ``NearestHit``: the paragraph-matching test case with
    the largest overlap between its branches_hit and the other
    covered branches in the same paragraph. A reviewer can start from
    that state and perturb by hand.
    """
    total = 0
    per_strategy: dict[str, AttemptSummary] = {}
    nearest: NearestHit | None = None
    nearest_score = -1

    target_suffix = f"{bid}:{direction}"

    for tc in test_cases:
        strategy = tc.get("layer") or tc.get("strategy") or "unknown"
        target = tc.get("target") or ""
        paras = tc.get("paragraphs_hit") or tc.get("paragraphs_covered") or []
        branches_hit = tc.get("branches_hit") or tc.get("branches_covered") or []

        direct_hit = False
        if target_suffix in target:
            direct_hit = True
        else:
            for m in _BID_IN_TARGET_RE.finditer(target):
                if int(m.group(1)) == bid:
                    direct_hit = True
                    break

        para_hit = paragraph and paragraph in paras

        if not direct_hit and not para_hit:
            continue

        summary = per_strategy.setdefault(strategy, AttemptSummary(strategy=strategy))
        summary.count += 1
        if direct_hit:
            summary.direct_bid_match += 1
        if para_hit:
            summary.paragraph_match += 1
        total += 1

        if para_hit:
            # Score the test case for "nearest hit": prefer the one
            # that covered the most branches overall, with a bonus
            # for branches whose bid is numerically near the target
            # (a coarse proxy for "in the same paragraph" that we can
            # compute without a full branch→paragraph map here).
            close_hits = sum(
                1 for b in branches_hit
                if isinstance(b, str) and _same_paragraph_bid(b, bid, paragraph)
            )
            total_hits = len(branches_hit)
            score = close_hits * 100 + total_hits
            if score > nearest_score:
                nearest_score = score
                nearest = NearestHit(
                    test_case_id=tc.get("id"),
                    strategy=strategy,
                    target=target,
                    input_state=tc.get("input_state") or {},
                    stub_outcomes=tc.get("stub_outcomes") or None,
                    paragraphs_hit=list(paras),
                    branches_hit_in_same_paragraph=[
                        b for b in branches_hit
                        if isinstance(b, str) and _same_paragraph_bid(b, bid, paragraph)
                    ],
                )

    attempts_by_strategy = sorted(
        per_strategy.values(), key=lambda s: (-s.count, s.strategy),
    )
    return total, attempts_by_strategy, nearest


def _same_paragraph_bid(branch_key: str, target_bid: int, target_para: str) -> bool:
    """Return True if ``branch_key`` refers to a branch in the same paragraph
    as the target branch. Used by the nearest-hit scorer."""
    # Best effort — without the full branch_meta we can only compare by
    # numeric proximity. This is a placeholder filter that keeps the
    # list short; the JSON report will only include branches we can
    # confidently tie to the paragraph via branch_meta downstream.
    try:
        bid = int(branch_key.split(":", 1)[0])
    except (ValueError, IndexError):
        return False
    return abs(bid - target_bid) <= 10


# ---------------------------------------------------------------------------
# Hint generation
# ---------------------------------------------------------------------------

def _generate_hints(detail: UncoveredBranchDetail) -> list[str]:
    """Produce human-readable next-step suggestions for an uncovered branch.

    These are *hints*, not instructions — they point the reviewer at
    the specific lever (a fault table entry, a missing stub, an
    inline 88-level value that should have been harvested, a
    compound condition that concolic could solve) that is likely to
    unlock the branch. False positives are fine; an over-eager hint
    is cheap to ignore. A missing hint is more costly because it
    leaves the reviewer with nothing to try.
    """
    hints: list[str] = []
    cat = detail.condition_category
    cond = detail.condition_text or ""

    # ---- file-status gates ----
    if cat == "file_status_eq":
        m = re.search(
            r"\b([A-Z][A-Z0-9-]*-?STATUS)\b\s*(?:=|EQUAL(?:\s+TO)?)\s*['\"](\d\d)['\"]",
            cond, re.IGNORECASE,
        )
        if m:
            status_var = m.group(1)
            wanted = m.group(2)
            hints.append(
                f"Needs file-status '{wanted}' on {status_var}. Verify "
                f"FaultInjectionStrategy emits a `fault:<OP>:{status_var}={wanted}` "
                f"case for an op key whose stub_mapping includes {status_var}."
            )

    # ---- 88-level gates (conditional expression = single variable) ----
    if cat == "status_flag_88" and detail.condition_vars:
        var = detail.condition_vars[0]
        v88 = detail.var_88_values.get(var) or {}
        if v88:
            activators = ", ".join(
                f"{k}={_fmt_value(v)}" for k, v in list(v88.items())[:4]
            )
            hints.append(
                f"{var} carries 88-level children. Try injecting one of "
                f"their activating values: {activators}."
            )
        else:
            # The condition variable is itself an 88-level *child* (e.g.
            # "IF APPL-AOK" where APPL-AOK is 88 VALUE 0 under
            # APPL-RESULT). Walk the parent→child map in detail.parent_88
            # which the caller populates from the full domain table.
            parent_hint = detail.parent_88_lookup.get(var) if hasattr(detail, "parent_88_lookup") else None
            if parent_hint:
                parent_name, activating_value = parent_hint
                hints.append(
                    f"{var} is an 88-level flag child of {parent_name}. "
                    f"Set {parent_name}={_fmt_value(activating_value)} in "
                    f"input_state to activate it. Requires {parent_name} "
                    f"to be in the injectable_vars filter (T2-C) and to "
                    f"not be overwritten by program logic before the "
                    f"target branch runs."
                )
            else:
                hints.append(
                    f"{var} looks like a bare 88-level flag but no parent "
                    f"was found. Either the variable is a plain boolean "
                    f"(add condition_literals={True, False} to its domain) "
                    f"or the parser missed an inline 88-level definition "
                    f"(check _extract_88_values_from_source)."
                )

    # ---- compound AND/OR ----
    if cat == "compound_and_or":
        hints.append(
            "Compound AND/OR condition. Candidate for concolic escalation "
            "(SPECTER_CONCOLIC=1 + plateau trigger) — the Z3 solver can "
            "search the joint assignment space in a single call. If "
            "concolic has already run and not solved it, the condition "
            "likely depends on variables that are driven by stub outcomes "
            "rather than input_state."
        )

    # ---- arithmetic comparisons ----
    if cat == "numeric_cmp":
        hints.append(
            "Numeric comparison. Check that the variable's domain has "
            "boundary values in condition_literals (the value itself, "
            "value-1, value+1). If not, the IF harvester in "
            "variable_extractor._harvest_condition_literals may be "
            "missing this comparison operator."
        )

    # ---- EVALUATE WHEN literal ----
    if cat == "evaluate_when":
        hints.append(
            "EVALUATE WHEN arm. Expected to be handled by "
            "_harvest_evaluate_when_literals (Tier 1-B). If the subject "
            "variable is internal and its WHEN literals are not reaching "
            "the runtime, check the injectable_vars filter and the "
            "runtime INIT record format."
        )

    # ---- NOT NUMERIC ----
    if cat == "not_numeric":
        hints.append(
            "NOT NUMERIC guard. Inject a non-numeric value (e.g. 'X') into "
            "the variable via the test store and verify the runtime "
            "PICTURE is alpha-compatible."
        )

    # ---- stub-driven variables ----
    stub_vars = [v for v, src in detail.stub_return_vars.items() if src]
    if stub_vars:
        hints.append(
            "Condition depends on stub-return variable(s): "
            + ", ".join(f"{v}→{detail.stub_return_vars[v]}" for v in stub_vars)
            + ". Verify the corresponding op key has the target value in "
              "its fault_values list (FaultInjectionStrategy)."
        )

    # ---- no attempts at all ----
    if detail.total_attempts == 0:
        hints.append(
            "No strategy ever touched this branch's paragraph. Verify "
            "the paragraph is reachable from the entry via PERFORM/GO TO "
            "(static_analysis.build_static_call_graph) — if not, the "
            "branch may be structurally unreachable from the current "
            "gating conditions."
        )

    return hints


def _fmt_value(v: Any) -> str:
    """Compact, reviewer-friendly rendering of a value for hint text."""
    if isinstance(v, str):
        return f"'{v}'"
    return str(v)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def generate_uncovered_report(
    *,
    ctx,
    cov,
    report,
    program_id: str,
    mock_source_path: Path | None = None,
    out_path_stem: Path,
    format: str = "both",
) -> UncoveredReport:
    """Build and write the uncovered-branch diagnostic report.

    The two output files are written next to ``out_path_stem``:

        <stem>.uncovered.json
        <stem>.uncovered.md

    Parameters
    ----------
    ctx:
        The active ``StrategyContext`` at the end of the coverage
        loop. Read for ``branch_meta``, ``domains``, ``stub_mapping``,
        ``gating_conds``, and ``var_report``.
    cov:
        The active ``CoverageState``. Read for ``branches_hit``,
        ``paragraphs_hit``, and ``test_cases``.
    report:
        The ``CobolCoverageReport`` being finalised — its totals drive
        the header metadata.
    program_id:
        Program identifier for the report header.
    mock_source_path:
        Optional path to the instrumented mock ``.cbl`` file. When
        provided, we scan it to recover condition text and source
        line numbers per branch id. When None, the report is still
        generated but condition_text is empty for each entry.
    out_path_stem:
        Base path for the output files. ``.uncovered.json`` and
        ``.uncovered.md`` are appended.
    format:
        ``"json"``, ``"markdown"``, or ``"both"`` (default).

    Returns
    -------
    UncoveredReport
        The in-memory report so the caller can inspect or log it.
        Always returns — on any internal failure, the caller gets an
        empty report and the failure is logged, so this helper never
        aborts the main coverage loop.
    """
    try:
        return _generate_uncovered_report_impl(
            ctx=ctx,
            cov=cov,
            report=report,
            program_id=program_id,
            mock_source_path=mock_source_path,
            out_path_stem=out_path_stem,
            format=format,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("Uncovered report generation failed: %s", exc)
        return UncoveredReport(
            program_id=program_id,
            total_branches=0,
            covered_branches=0,
            uncovered_branches=0,
            total_test_cases=0,
            elapsed_seconds=0.0,
            generated_at="",
        )


def _generate_uncovered_report_impl(
    *,
    ctx,
    cov,
    report,
    program_id: str,
    mock_source_path: Path | None,
    out_path_stem: Path,
    format: str,
) -> UncoveredReport:
    import datetime

    branch_meta = getattr(ctx, "branch_meta", None) or {}
    domains = getattr(ctx, "domains", None) or {}
    stub_mapping = getattr(ctx, "stub_mapping", None) or {}
    gating_conds = getattr(ctx, "gating_conds", None) or {}
    test_cases = cov.test_cases or []

    # --- enrich branch_meta with condition text from the mock source ---
    source_info: dict[str, dict[str, Any]] = {}
    if mock_source_path:
        source_info = _extract_branch_conditions(mock_source_path)

    # Build reverse lookup: var_name -> stub op_key (for stub-driven vars).
    var_to_stub_op: dict[str, str] = {}
    for op_key, status_vars in stub_mapping.items():
        for v in status_vars:
            var_to_stub_op.setdefault(v.upper(), op_key)

    # Build reverse lookup: 88-level child name -> (parent_name, activating_value).
    # This is what turns "IF APPL-AOK" into an actionable hint pointing
    # at "set APPL-RESULT = 0".
    parent_88_global: dict[str, tuple[str, Any]] = {}
    for parent_name, dom in domains.items():
        v88 = getattr(dom, "valid_88_values", None) or {}
        for child_name, child_value in v88.items():
            # First writer wins — 88-level child names are supposed to
            # be unique across a program so collisions are rare.
            parent_88_global.setdefault(
                child_name.upper(), (parent_name, child_value),
            )

    # --- walk every branch in branch_meta and select uncovered ones ---
    uncovered: list[UncoveredBranchDetail] = []

    for bid_key, meta in branch_meta.items():
        try:
            bid = int(bid_key)
        except (TypeError, ValueError):
            continue

        for direction in ("T", "F"):
            branch_key = f"{bid}:{direction}"
            if branch_key in cov.branches_hit:
                continue

            sinfo = source_info.get(str(bid)) or {}
            paragraph = (
                sinfo.get("paragraph")
                or meta.get("paragraph")
                or ""
            ).upper()
            cond_text = sinfo.get("condition_text") or meta.get("condition") or ""
            source_line = sinfo.get("line") or meta.get("line") or 0

            category = _classify_condition(cond_text)
            cond_vars = _extract_condition_vars(cond_text)

            var_classifications: dict[str, str] = {}
            var_literals: dict[str, list] = {}
            var_88_values: dict[str, dict[str, Any]] = {}
            stub_return_vars: dict[str, str] = {}
            for v in cond_vars:
                dom = domains.get(v)
                if dom is None:
                    continue
                var_classifications[v] = getattr(dom, "classification", "") or ""
                lits = list(getattr(dom, "condition_literals", []) or [])
                if lits:
                    var_literals[v] = lits[:8]
                v88 = dict(getattr(dom, "valid_88_values", {}) or {})
                if v88:
                    var_88_values[v] = v88
                if v in var_to_stub_op:
                    stub_return_vars[v] = var_to_stub_op[v]

            # --- reachability: take the gating conditions on this paragraph ---
            gating_here = gating_conds.get(paragraph, []) if paragraph else []
            gating_paragraphs: list[str] = []
            gating_conditions_text: list[str] = []
            for gc in gating_here[:6]:
                # GatingCondition may be a dataclass or dict — probe both.
                gcp = getattr(gc, "paragraph", None) or (
                    gc.get("paragraph") if isinstance(gc, dict) else None
                )
                gct = getattr(gc, "condition", None) or (
                    gc.get("condition") if isinstance(gc, dict) else None
                )
                if gcp:
                    gating_paragraphs.append(str(gcp))
                if gct:
                    gating_conditions_text.append(str(gct))

            # --- attempts from the test-case list ---
            total, attempts, nearest = _count_attempts(
                test_cases, bid, direction, paragraph,
            )

            # Restrict the parent-88 lookup to just the variables
            # this branch's condition mentions, so the hint generator
            # doesn't have to iterate the whole table.
            detail_parent_88: dict[str, tuple[str, Any]] = {
                v: parent_88_global[v]
                for v in cond_vars
                if v in parent_88_global
            }

            detail = UncoveredBranchDetail(
                branch_id=bid,
                direction=direction,
                branch_key=branch_key,
                paragraph=paragraph,
                source_file=str(mock_source_path) if mock_source_path else "",
                source_line=int(source_line) if source_line else 0,
                condition_text=cond_text,
                condition_category=category,
                condition_vars=cond_vars,
                var_classifications=var_classifications,
                var_literals=var_literals,
                var_88_values=var_88_values,
                stub_return_vars=stub_return_vars,
                gating_paragraphs=gating_paragraphs,
                gating_conditions=gating_conditions_text,
                total_attempts=total,
                attempts_by_strategy=attempts,
                nearest_hit=nearest,
                parent_88_lookup=detail_parent_88,
            )
            detail.hints = _generate_hints(detail)
            uncovered.append(detail)

    # --- header / summary ---
    summary_by_category: dict[str, int] = {}
    summary_by_paragraph: dict[str, int] = {}
    for d in uncovered:
        summary_by_category[d.condition_category] = summary_by_category.get(
            d.condition_category, 0,
        ) + 1
        summary_by_paragraph[d.paragraph] = summary_by_paragraph.get(
            d.paragraph, 0,
        ) + 1

    uncovered_report = UncoveredReport(
        program_id=program_id,
        total_branches=int(getattr(report, "branches_total", 0) or cov.total_branches or 0),
        covered_branches=int(getattr(report, "branches_hit", 0) or 0),
        uncovered_branches=len(uncovered),
        total_test_cases=int(getattr(report, "total_test_cases", 0) or len(test_cases)),
        elapsed_seconds=float(getattr(report, "elapsed_seconds", 0.0) or 0.0),
        generated_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        branches=uncovered,
        summary_by_category=summary_by_category,
        summary_by_paragraph=summary_by_paragraph,
    )

    # --- write files ---
    out_path_stem = Path(out_path_stem)
    out_path_stem.parent.mkdir(parents=True, exist_ok=True)

    if format in ("json", "both"):
        json_path = out_path_stem.with_suffix(out_path_stem.suffix + ".uncovered.json")
        # Re-derive a stem that strips any trailing extension so the file lands
        # as e.g. "tests.uncovered.json" instead of "tests.jsonl.uncovered.json".
        json_path = out_path_stem.with_name(out_path_stem.stem + ".uncovered.json")
        try:
            json_path.write_text(
                json.dumps(_to_jsonable(uncovered_report), indent=2, sort_keys=False),
            )
            log.info("Uncovered-branch report (JSON): %s", json_path)
        except Exception as exc:  # noqa: BLE001
            log.warning("Failed to write JSON uncovered report: %s", exc)

    if format in ("markdown", "both"):
        md_path = out_path_stem.with_name(out_path_stem.stem + ".uncovered.md")
        try:
            md_path.write_text(_render_markdown(uncovered_report))
            log.info("Uncovered-branch report (Markdown): %s", md_path)
        except Exception as exc:  # noqa: BLE001
            log.warning("Failed to write Markdown uncovered report: %s", exc)

    return uncovered_report


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

def _to_jsonable(obj: Any) -> Any:
    """Convert dataclasses + sets into JSON-serialisable primitives."""
    if hasattr(obj, "__dataclass_fields__"):
        return {k: _to_jsonable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {str(k): _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [_to_jsonable(x) for x in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return str(obj)


def _render_markdown(report: UncoveredReport) -> str:
    """Render the report as a human-readable Markdown document.

    Layout:
        1. Header with program id, coverage totals, timestamps.
        2. Category summary (counts by condition_category).
        3. Paragraph summary (top 10 paragraphs with most uncovered).
        4. Per-branch detail sections, grouped by paragraph and sorted
           by branch id for stable diffs.
    """
    lines: list[str] = []
    lines.append(f"# Uncovered branch report — {report.program_id}")
    lines.append("")
    lines.append(f"- Generated: {report.generated_at}")
    lines.append(f"- Coverage: {report.covered_branches}/{report.total_branches} branches "
                 f"({_pct(report.covered_branches, report.total_branches)})")
    lines.append(f"- Uncovered: **{report.uncovered_branches}**")
    lines.append(f"- Test cases: {report.total_test_cases}")
    lines.append(f"- Elapsed: {report.elapsed_seconds:.1f}s")
    lines.append("")

    if report.summary_by_category:
        lines.append("## Uncovered by category")
        lines.append("")
        lines.append("| Category | Count |")
        lines.append("|---|---|")
        for cat, count in sorted(
            report.summary_by_category.items(), key=lambda kv: -kv[1],
        ):
            lines.append(f"| `{cat}` | {count} |")
        lines.append("")

    if report.summary_by_paragraph:
        top_paras = sorted(
            report.summary_by_paragraph.items(), key=lambda kv: -kv[1],
        )[:15]
        lines.append("## Top paragraphs with uncovered branches")
        lines.append("")
        lines.append("| Paragraph | Count |")
        lines.append("|---|---|")
        for para, count in top_paras:
            lines.append(f"| `{para or '(unknown)'}` | {count} |")
        lines.append("")

    # Group details by paragraph, ordered by descending uncovered count.
    by_para: dict[str, list[UncoveredBranchDetail]] = {}
    for d in report.branches:
        by_para.setdefault(d.paragraph, []).append(d)
    for p in by_para:
        by_para[p].sort(key=lambda d: (d.branch_id, d.direction))

    ordered_paras = sorted(
        by_para.keys(),
        key=lambda p: (-len(by_para[p]), p),
    )

    lines.append("## Detail")
    lines.append("")
    for para in ordered_paras:
        entries = by_para[para]
        lines.append(f"### `{para or '(unknown)'}` — {len(entries)} uncovered")
        lines.append("")
        for d in entries:
            lines.append(f"#### Branch {d.branch_key} (`{d.condition_category}`)")
            lines.append("")
            if d.condition_text:
                lines.append(f"- **Condition**: `{d.condition_text}`")
            if d.source_line:
                lines.append(f"- **Source line**: {d.source_line}")
            if d.condition_vars:
                vars_bits = []
                for v in d.condition_vars:
                    cls = d.var_classifications.get(v, "")
                    note = f" *({cls})*" if cls else ""
                    if v in d.stub_return_vars:
                        note += f" ← `{d.stub_return_vars[v]}`"
                    vars_bits.append(f"`{v}`{note}")
                lines.append(f"- **Variables**: {', '.join(vars_bits)}")
            if d.var_literals:
                lit_bits = []
                for v, lits in d.var_literals.items():
                    lit_bits.append(f"`{v}` ∈ {{{', '.join(_fmt_value(x) for x in lits[:6])}}}")
                lines.append(f"- **Known literals**: {'; '.join(lit_bits)}")
            if d.var_88_values:
                lines.append(f"- **88-level values**:")
                for v, vm in d.var_88_values.items():
                    for name, val in list(vm.items())[:6]:
                        lines.append(f"    - `{v}` → `{name}` = {_fmt_value(val)}")
            if d.gating_conditions:
                lines.append(f"- **Gating conditions**:")
                for gc in d.gating_conditions[:4]:
                    lines.append(f"    - `{gc}`")
            lines.append(f"- **Attempts**: {d.total_attempts}")
            if d.attempts_by_strategy:
                attempt_bits = [
                    f"{s.strategy}={s.count}"
                    + (f" (direct:{s.direct_bid_match})" if s.direct_bid_match else "")
                    for s in d.attempts_by_strategy[:6]
                ]
                lines.append(f"    - {', '.join(attempt_bits)}")
            if d.nearest_hit:
                nh = d.nearest_hit
                preview_keys = list((nh.input_state or {}).keys())[:6]
                preview = {k: nh.input_state[k] for k in preview_keys}
                lines.append(f"- **Nearest hit**: `{nh.strategy}` (`{nh.target}`)")
                if preview:
                    lines.append(f"    - Input: `{preview}`")
                # stub_outcomes arrives as a dict in the in-memory runtime
                # format but as a list of [op_key, outcome] pairs when it
                # comes from a reloaded test store — handle both shapes.
                stub_preview = _stub_op_preview(nh.stub_outcomes)
                if stub_preview:
                    lines.append(f"    - Stub ops: `{stub_preview}`")
            if d.hints:
                lines.append("- **Hints**:")
                for h in d.hints:
                    lines.append(f"    - {h}")
            lines.append("")
    return "\n".join(lines) + "\n"


def _pct(num: int, denom: int) -> str:
    if not denom:
        return "n/a"
    return f"{100.0 * num / denom:.1f}%"


def _stub_op_preview(stub_outcomes: Any, limit: int = 4) -> list[str]:
    """Extract a short list of op-key names from a stub_outcomes value.

    ``stub_outcomes`` is a ``dict[str, list]`` in the live runtime
    (where the Strategy context builds it from scratch) but becomes a
    ``list[[op_key, outcome], ...]`` after it round-trips through the
    JSONL test store, because JSON has no tuple type and
    ``test_store.TestCase`` serialises the runtime dict to a list of
    pairs. The markdown renderer must tolerate both shapes; any
    other shape is silently ignored.
    """
    if not stub_outcomes:
        return []
    if isinstance(stub_outcomes, dict):
        return list(stub_outcomes.keys())[:limit]
    if isinstance(stub_outcomes, (list, tuple)):
        out: list[str] = []
        for entry in stub_outcomes:
            if isinstance(entry, (list, tuple)) and entry:
                out.append(str(entry[0]))
            if len(out) >= limit:
                break
        return out
    return []
