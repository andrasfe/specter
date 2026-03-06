"""Dynamic analysis reporting from instrumented execution runs."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field


@dataclass
class AnalysisReport:
    """Aggregated dynamic analysis results across N iterations."""

    paragraph_hit_counts: dict[str, int] = field(default_factory=dict)
    dead_paragraphs: list[str] = field(default_factory=list)
    call_graph: dict[str, set[str]] = field(default_factory=dict)
    variable_write_counts: dict[str, int] = field(default_factory=dict)
    variable_read_counts: dict[str, int] = field(default_factory=dict)
    dead_writes: list[str] = field(default_factory=list)
    read_only_vars: list[str] = field(default_factory=list)
    state_diffs: dict[str, dict] = field(default_factory=dict)
    n_iterations: int = 0
    structurally_unreachable: list[str] = field(default_factory=list)
    reachable_uncovered: list[str] = field(default_factory=list)
    max_theoretical_coverage: float = 0.0
    branch_hits: int = 0
    total_branches: int = 0

    def summary(self) -> str:
        lines = []
        total_paras = len(self.paragraph_hit_counts) + len(self.dead_paragraphs)
        covered = len(self.paragraph_hit_counts)

        if self.structurally_unreachable:
            n_reachable = total_paras - len(self.structurally_unreachable)
            pct = (covered / n_reachable * 100) if n_reachable else 0
            lines.append(f"=== Dynamic Analysis ({self.n_iterations} iterations) ===")
            lines.append("")
            lines.append(
                f"Paragraph Coverage: {covered}/{n_reachable} reachable ({pct:.1f}%), "
                f"{len(self.structurally_unreachable)} structurally unreachable"
            )
        else:
            pct = (covered / total_paras * 100) if total_paras else 0
            lines.append(f"=== Dynamic Analysis ({self.n_iterations} iterations) ===")
            lines.append("")
            lines.append(f"Paragraph Coverage: {covered}/{total_paras} ({pct:.1f}%)")

        if self.total_branches > 0:
            br_pct = (self.branch_hits / self.total_branches * 100)
            lines.append(
                f"Branch Coverage: {self.branch_hits}/{self.total_branches} ({br_pct:.1f}%)"
            )

        if self.reachable_uncovered:
            lines.append(f"  Reachable uncovered: {', '.join(self.reachable_uncovered[:10])}")
            if len(self.reachable_uncovered) > 10:
                lines.append(f"  ... and {len(self.reachable_uncovered) - 10} more")
        if self.dead_paragraphs:
            lines.append(f"  Dead: {', '.join(self.dead_paragraphs[:10])}")
            if len(self.dead_paragraphs) > 10:
                lines.append(f"  ... and {len(self.dead_paragraphs) - 10} more")

        if self.call_graph:
            lines.append("")
            lines.append("Call Graph (top callers):")
            sorted_callers = sorted(self.call_graph.items(),
                                    key=lambda x: len(x[1]), reverse=True)
            for caller, callees in sorted_callers[:10]:
                lines.append(f"  {caller} -> {', '.join(sorted(callees))}")

        lines.append("")
        lines.append("Variable Activity:")
        if self.variable_write_counts:
            top_writes = sorted(self.variable_write_counts.items(),
                                key=lambda x: -x[1])[:5]
            lines.append(f"  Most written: {', '.join(f'{n} ({c})' for n, c in top_writes)}")
        if self.read_only_vars:
            lines.append(f"  Read-only: {', '.join(self.read_only_vars[:10])}")
        if self.dead_writes:
            lines.append(f"  Dead writes: {', '.join(self.dead_writes[:10])}")

        if self.state_diffs:
            lines.append("")
            lines.append("State Changes:")
            always = []
            sometimes = []
            never = []
            for var, info in sorted(self.state_diffs.items()):
                changed_in = info.get("changed_in", 0)
                if changed_in == self.n_iterations:
                    always.append(f"{var} ({changed_in}/{self.n_iterations})")
                elif changed_in > 0:
                    sometimes.append((changed_in, f"{var} ({changed_in}/{self.n_iterations})"))
                else:
                    never.append(var)
            if always:
                lines.append(f"  Always changed: {', '.join(always[:10])}")
            if sometimes:
                sometimes.sort(key=lambda x: -x[0])
                lines.append(f"  Sometimes: {', '.join(s for _, s in sometimes[:10])}")
            if never:
                lines.append(f"  Never: {', '.join(never[:10])}")

        return "\n".join(lines)


def build_analysis_report(
    iterations: list[dict],
    all_paragraphs: list[str],
) -> AnalysisReport:
    """Build an aggregated analysis report from per-iteration instrumentation data.

    Args:
        iterations: List of dicts, each with keys: trace, var_writes, var_reads, state_diffs.
        all_paragraphs: List of all paragraph names defined in the program.
    """
    report = AnalysisReport(n_iterations=len(iterations))

    para_hits: Counter[str] = Counter()
    var_writes: Counter[str] = Counter()
    var_reads: Counter[str] = Counter()
    call_graph: dict[str, set[str]] = {}
    change_counts: Counter[str] = Counter()
    common_finals: dict[str, Counter] = {}

    for it in iterations:
        trace = it.get("trace", [])
        writes = it.get("var_writes", [])
        reads = it.get("var_reads", [])
        diffs = it.get("state_diffs", {})

        # Paragraph hits
        for para_name in trace:
            para_hits[para_name] += 1

        # Build call graph from trace: each paragraph "calls" the next one
        for i in range(len(trace) - 1):
            caller = trace[i]
            callee = trace[i + 1]
            if caller != callee:
                call_graph.setdefault(caller, set()).add(callee)

        # Variable writes
        for var, _para in writes:
            var_writes[var] += 1

        # Variable reads
        for var, _para in reads:
            var_reads[var] += 1

        # State diffs
        for var, diff in diffs.items():
            change_counts[var] += 1
            if var not in common_finals:
                common_finals[var] = Counter()
            final_val = diff.get("to", "")
            common_finals[var][repr(final_val)] += 1

    report.paragraph_hit_counts = dict(para_hits)
    report.call_graph = call_graph
    report.variable_write_counts = dict(var_writes)
    report.variable_read_counts = dict(var_reads)

    # Dead paragraphs: defined but never hit
    hit_names = set(para_hits.keys())
    report.dead_paragraphs = sorted(p for p in all_paragraphs if p not in hit_names)

    # Dead writes: written but never read
    written_vars = set(var_writes.keys())
    read_vars = set(var_reads.keys())
    report.dead_writes = sorted(written_vars - read_vars)

    # Read-only vars: read but never written
    report.read_only_vars = sorted(read_vars - written_vars)

    # State diffs summary
    all_tracked_vars = set()
    for it in iterations:
        diffs = it.get("state_diffs", {})
        # Also track variables from the initial snapshot
        all_tracked_vars.update(diffs.keys())

    for var in sorted(all_tracked_vars):
        info: dict = {"changed_in": change_counts.get(var, 0)}
        if var in common_finals:
            top = common_finals[var].most_common(3)
            info["common_finals"] = [(val, cnt) for val, cnt in top]
        report.state_diffs[var] = info

    return report
