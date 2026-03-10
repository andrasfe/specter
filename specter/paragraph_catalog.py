"""Generate a per-paragraph catalog from a test store + generated module.

Produces a Markdown file with one entry per paragraph containing:
- Paragraph name (H2 heading with anchor)
- Next paragraph(s) as clickable links
- Example input state
- State changes (before/after)
- External operations with return values
"""

from __future__ import annotations

import inspect
import re
from collections import defaultdict
from pathlib import Path

from .monte_carlo import _load_module, _run_paragraph_directly
from .test_store import TestStore, TestCase, _build_run_state


def generate_paragraph_catalog(
    module_path: str | Path,
    store_path: str | Path,
    program=None,
) -> str:
    """Generate Markdown paragraph catalog.

    Args:
        module_path: Path to the generated Python module.
        store_path: Path to the JSONL test store.
        program: Optional parsed Program for richer call graph.

    Returns:
        Markdown string.
    """
    module = _load_module(module_path)
    test_cases, _progress = TestStore.load(store_path)

    if not test_cases:
        return "# No test cases found\n"

    para_order = getattr(module, "_PARAGRAPH_ORDER", [])

    # Step A: pick best TC per paragraph
    best_tc = _build_para_index(test_cases)

    # Step B: extract successors
    successors = _extract_successors(module, program)

    # Step C: extract stub keys per paragraph
    para_stubs = {}
    for pname in para_order:
        para_stubs[pname] = _extract_para_stubs(module, pname)

    # Step D: selective replay (deduplicated by TC id)
    replay_results = _replay_all(module, best_tc)

    # Step E+F+G: render
    all_paras: set[str] = set()
    for tc in test_cases:
        all_paras.update(tc.paragraphs_covered)

    # Use para_order for output ordering; append any covered but unlisted paras
    ordered = list(para_order)
    extra = sorted(all_paras - set(para_order))
    ordered.extend(extra)

    entries = []
    for pname in ordered:
        tc = best_tc.get(pname)
        replay = replay_results.get(id(tc)) if tc else None
        entries.append(_render_paragraph(
            pname, tc, replay, successors, para_stubs, ordered,
        ))

    # Header
    program_name = ""
    if para_order:
        # Try to get program name from module
        run_fn = getattr(module, "run", None)
        if run_fn:
            program_name = getattr(module, "_PROGRAM_ID", "")
    header_name = f" \u2014 {program_name}" if program_name else ""

    header = [
        f"# Paragraph Catalog{header_name}",
        "",
        f"{len(ordered)} paragraphs, {len(test_cases)} test cases",
        "",
    ]

    return "\n".join(header) + "\n---\n\n" + "\n\n---\n\n".join(entries) + "\n"


def _build_para_index(test_cases: list[TestCase]) -> dict[str, TestCase]:
    """Pick the TC with the most branches_covered for each paragraph."""
    best: dict[str, TestCase] = {}
    best_score: dict[str, int] = {}
    for tc in test_cases:
        score = len(tc.branches_covered)
        for pname in tc.paragraphs_covered:
            if pname not in best or score > best_score[pname]:
                best[pname] = tc
                best_score[pname] = score
    return best


def _extract_successors(module, program=None) -> dict[str, list[str]]:
    """Extract paragraph call successors from source + optional call graph."""
    successors: dict[str, set[str]] = defaultdict(set)

    # From generated source: scan for para_XXX(state) calls
    call_re = re.compile(r"(para_[A-Z0-9_]+)\(state\)")
    para_order = getattr(module, "_PARAGRAPH_ORDER", [])
    # Build func name -> COBOL name mapping
    func_to_cobol = {}
    for pname in para_order:
        fname = "para_" + pname.replace("-", "_").replace(".", "_")
        func_to_cobol[fname] = pname

    for pname in para_order:
        fname = "para_" + pname.replace("-", "_").replace(".", "_")
        fn = getattr(module, fname, None)
        if fn is None:
            continue
        try:
            source = inspect.getsource(fn)
        except (OSError, TypeError):
            continue
        for match in call_re.findall(source):
            if match != fname:  # skip self-calls in source
                callee = func_to_cobol.get(match, match.replace("para_", "").replace("_", "-"))
                successors[pname].add(callee)

    # From static call graph if available
    if program is not None:
        try:
            from .static_analysis import build_static_call_graph
            cg = build_static_call_graph(program)
            for caller, callees in cg.edges.items():
                for callee in callees:
                    if callee != caller:
                        successors[caller].add(callee)
        except Exception:
            pass

    # Convert to sorted lists
    return {k: sorted(v) for k, v in successors.items()}


def _extract_para_stubs(module, para_name: str) -> list[str]:
    """Extract stub operation keys consumed by a paragraph."""
    fname = "para_" + para_name.replace("-", "_").replace(".", "_")
    fn = getattr(module, fname, None)
    if fn is None:
        return []
    try:
        source = inspect.getsource(fn)
    except (OSError, TypeError):
        return []

    keys: list[str] = []
    # _apply_stub_outcome(state, 'KEY')
    for m in re.finditer(r"_apply_stub_outcome\(state,\s*'([^']+)'\)", source):
        keys.append(m.group(1))
    # _dummy_call('NAME', state)
    for m in re.finditer(r"_dummy_call\('([^']+)',\s*state\)", source):
        keys.append(f"CALL:{m.group(1)}")
    # _dummy_exec('KIND', ...)
    for m in re.finditer(r"_dummy_exec\('([^']+)'", source):
        keys.append(m.group(1))
    return keys


def _replay_all(
    module,
    best_tc: dict[str, TestCase],
) -> dict[int, dict]:
    """Replay unique TCs and collect state diffs.

    Returns dict keyed by id(tc) -> replay result dict.
    """
    # Deduplicate: group paras by TC id to replay each TC only once
    tc_by_obj_id: dict[int, TestCase] = {}
    tc_paras: dict[int, list[str]] = defaultdict(list)
    for pname, tc in best_tc.items():
        obj_id = id(tc)
        tc_by_obj_id[obj_id] = tc
        tc_paras[obj_id].append(pname)

    results: dict[int, dict] = {}
    for obj_id, tc in tc_by_obj_id.items():
        try:
            state = _build_run_state(module, tc)
            initial = dict(state)

            if tc.target.startswith("direct:"):
                rest = tc.target[len("direct:"):]
                para_name = rest.split("|", 1)[0]
                rs = _run_paragraph_directly(module, para_name, state)
            else:
                rs = module.run(state)

            trace = rs.get("_trace", [])
            var_writes = rs.get("_var_writes", [])

            results[obj_id] = {
                "trace": trace,
                "var_writes": var_writes,
                "initial_state": initial,
                "final_state": dict(rs),
            }
        except Exception:
            results[obj_id] = {
                "trace": [],
                "var_writes": [],
                "initial_state": {},
                "final_state": {},
            }

    return results


def _para_anchor(name: str) -> str:
    """Convert paragraph name to Markdown anchor."""
    return re.sub(r"[^a-z0-9 -]", "-", name.lower()).replace(" ", "-")


def _render_paragraph(
    pname: str,
    tc: TestCase | None,
    replay: dict | None,
    successors: dict[str, list[str]],
    para_stubs: dict[str, list[str]],
    all_paras: list[str],
) -> str:
    """Render a single paragraph entry."""
    lines = [f"## {pname}"]

    # Calls
    succs = successors.get(pname, [])
    if succs:
        para_set = set(all_paras)
        links = []
        for s in succs:
            if s in para_set:
                links.append(f"[{s}](#{_para_anchor(s)})")
            else:
                links.append(s)
        lines.append("")
        lines.append(f"**Calls:** {', '.join(links)}")

    if tc is None:
        lines.append("")
        lines.append("*(No test case covers this paragraph)*")
        return "\n".join(lines)

    # Example Input (non-default, non-empty, non-internal)
    interesting = {
        k: v for k, v in tc.input_state.items()
        if not k.startswith("_") and v not in ("", None)
    }
    if interesting:
        lines.append("")
        lines.append("### Example Input")
        lines.append("| Variable | Value |")
        lines.append("|----------|-------|")
        shown = 0
        for var in sorted(interesting):
            if shown >= 15:
                break
            val = interesting[var]
            lines.append(f"| {var} | `{_escape_md(val)}` |")
            shown += 1

    # State Changes
    if replay:
        diffs = _compute_state_diffs(
            pname,
            replay.get("var_writes", []),
            replay.get("initial_state", {}),
            replay.get("final_state", {}),
        )
        if diffs:
            lines.append("")
            lines.append("### State Changes")
            lines.append("| Variable | Before | After |")
            lines.append("|----------|--------|-------|")
            for var, before, after in diffs[:15]:
                lines.append(
                    f"| {var} | `{_escape_md(before)}` | `{_escape_md(after)}` |"
                )

    # External Operations
    stub_keys = para_stubs.get(pname, [])
    if stub_keys and tc.stub_outcomes:
        stub_rows = _attribute_stubs_for_para(
            pname, stub_keys, tc, replay,
        )
        if stub_rows:
            lines.append("")
            lines.append("### External Operations")
            lines.append("| Operation | Returns |")
            lines.append("|-----------|---------|")
            for op_key, returns_str in stub_rows:
                lines.append(f"| {op_key} | {returns_str} |")

    return "\n".join(lines)


def _compute_state_diffs(
    para_name: str,
    var_writes: list,
    initial_state: dict,
    final_state: dict,
) -> list[tuple[str, object, object]]:
    """Compute state diffs for a paragraph."""
    # If var_writes has paragraph info, filter to this paragraph
    written_vars: set[str] = set()
    if var_writes:
        for entry in var_writes:
            if isinstance(entry, (list, tuple)) and len(entry) >= 2:
                var, para = entry[0], entry[1] if len(entry) > 1 else ""
                if not para or para == para_name:
                    written_vars.add(var)

    # If no var_writes info, diff all non-internal keys
    if not written_vars:
        for k in final_state:
            if not k.startswith("_") and k in initial_state:
                if initial_state[k] != final_state.get(k):
                    written_vars.add(k)

    diffs = []
    for var in sorted(written_vars):
        before = initial_state.get(var, "")
        after = final_state.get(var, "")
        if before != after:
            diffs.append((var, before, after))

    return diffs


def _attribute_stubs_for_para(
    para_name: str,
    stub_keys: list[str],
    tc: TestCase,
    replay: dict | None,
) -> list[tuple[str, str]]:
    """Attribute stub outcomes to this paragraph."""
    rows = []
    for key in stub_keys:
        queue = tc.stub_outcomes.get(key, [])
        if not queue:
            # Try defaults
            default = tc.stub_defaults.get(key, [])
            if isinstance(default, list) and default:
                pairs_str = _format_stub_entry(default)
                if pairs_str:
                    rows.append((key, pairs_str))
            continue
        # Use first entry as representative
        entry = queue[0]
        pairs_str = _format_stub_entry(entry)
        if pairs_str:
            rows.append((key, pairs_str))
    return rows


def _format_stub_entry(entry) -> str:
    """Format a stub outcome entry as var=val pairs."""
    if isinstance(entry, list):
        parts = []
        for pair in entry:
            if isinstance(pair, (list, tuple)) and len(pair) == 2:
                var, val = pair
                parts.append(f"{var}=`{_escape_md(val)}`")
        return ", ".join(parts) if parts else ""
    return str(entry)


def _escape_md(val) -> str:
    """Escape value for Markdown table cell."""
    s = str(val)
    return s.replace("|", "\\|").replace("\n", " ")
