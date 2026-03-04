"""Monte Carlo analysis of generated Python code.

Runs multiple iterations with randomized input parameters to explore
execution paths, branch coverage, and external call patterns.
"""

from __future__ import annotations

import importlib.util
import random
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class IterationResult:
    """Result of a single Monte Carlo iteration."""

    iteration: int
    initial_state: dict
    final_state: dict
    display_output: list[str]
    calls_made: list[dict]
    execs_made: list[dict]
    reads: list[str]
    writes: list[str]
    abended: bool
    error: str | None = None


@dataclass
class MonteCarloReport:
    """Aggregated results from Monte Carlo analysis."""

    n_iterations: int
    n_successful: int = 0
    n_errors: int = 0
    n_abended: int = 0
    call_frequency: dict[str, int] = field(default_factory=dict)
    exec_frequency: dict[str, int] = field(default_factory=dict)
    display_patterns: dict[str, int] = field(default_factory=dict)
    variable_distributions: dict[str, Counter] = field(default_factory=dict)
    error_messages: list[str] = field(default_factory=list)
    iterations: list[IterationResult] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"Monte Carlo Analysis: {self.n_iterations} iterations",
            f"  Successful: {self.n_successful}",
            f"  Errors: {self.n_errors}",
            f"  Abended: {self.n_abended}",
            "",
            "External Calls:",
        ]
        for name, count in sorted(self.call_frequency.items(),
                                   key=lambda x: -x[1]):
            lines.append(f"  {name}: {count}")

        lines.append("")
        lines.append("Exec Blocks:")
        for kind, count in sorted(self.exec_frequency.items(),
                                   key=lambda x: -x[1]):
            lines.append(f"  {kind}: {count}")

        lines.append("")
        lines.append("Display Patterns (top 20):")
        sorted_displays = sorted(self.display_patterns.items(),
                                  key=lambda x: -x[1])[:20]
        for msg, count in sorted_displays:
            truncated = msg[:80] if len(msg) > 80 else msg
            lines.append(f"  [{count}x] {truncated}")

        if self.error_messages:
            lines.append("")
            lines.append("Errors (unique):")
            for msg in sorted(set(self.error_messages))[:10]:
                lines.append(f"  {msg[:100]}")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Input parameter generation
# ---------------------------------------------------------------------------

# Known status code values for different categories
_STATUS_VALUES = {
    "file": [" ", "00", "10", "21", "30", "35", "41", "42", "43", "44", "46", "47", "48", "49"],
    "ims": [" ", "  ", "II", "GE", "GB", "AI"],
    "sql": [0, 100, -803, -805, -811, -904, -911, -913],
    "cics": [0, 1, 12, 13, 16, 22, 26, 27, 70, 84],
}


def _generate_random_state(var_report, rng: random.Random) -> dict:
    """Generate a randomized initial state based on variable classification."""
    state = {}

    for name, info in var_report.variables.items():
        upper = name.upper()

        if info.classification == "status":
            if "SQLCODE" in upper or "SQLSTATE" in upper:
                state[name] = rng.choice(_STATUS_VALUES["sql"])
            elif "PCB" in upper and "STATUS" in upper:
                state[name] = rng.choice(_STATUS_VALUES["ims"])
            elif "EIBRESP" in upper:
                state[name] = rng.choice(_STATUS_VALUES["cics"])
            elif "EIBAID" in upper:
                state[name] = rng.choice(["DFHENTER", "DFHPF3", "DFHPF7", "DFHPF8", "DFHCLEAR"])
            elif "STATUS" in upper:
                state[name] = rng.choice(_STATUS_VALUES["file"])
            else:
                state[name] = rng.choice([" ", "00", "10"])

        elif info.classification == "flag":
            state[name] = rng.choice([True, False])

        elif info.classification == "input":
            # Heuristic: check name patterns
            if "DATE" in upper or "YYDDD" in upper:
                state[name] = f"{rng.randint(20, 25):02d}{rng.randint(1, 12):02d}{rng.randint(1, 28):02d}"
            elif "TIME" in upper:
                state[name] = f"{rng.randint(0, 23):02d}{rng.randint(0, 59):02d}{rng.randint(0, 59):02d}"
            elif "KEY" in upper or "NUM" in upper or "ID" in upper:
                state[name] = str(rng.randint(10000, 99999))
            elif "CNT" in upper or "COUNT" in upper or "FREQ" in upper:
                state[name] = rng.randint(0, 100)
            elif "AMT" in upper or "AMOUNT" in upper:
                state[name] = rng.randint(0, 10000)
            elif "DAYS" in upper:
                state[name] = rng.randint(1, 30)
            elif "FLAG" in upper or "FLG" in upper:
                state[name] = rng.choice(["Y", "N"])
            else:
                state[name] = rng.choice(["", " ", "TEST", "A", "12345"])

    return state


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def _load_module(module_path: str | Path):
    """Dynamically import a generated Python module."""
    path = Path(module_path)
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = module
    spec.loader.exec_module(module)
    return module


def run_monte_carlo(
    generated_module_path: str | Path,
    n_iterations: int = 1000,
    seed: int = 42,
    var_report=None,
) -> MonteCarloReport:
    """Run Monte Carlo analysis on a generated Python module.

    Args:
        generated_module_path: Path to the generated .py file.
        n_iterations: Number of random iterations.
        seed: Random seed for reproducibility.
        var_report: Optional VariableReport for input generation.

    Returns:
        MonteCarloReport with aggregated results.
    """
    module = _load_module(generated_module_path)
    rng = random.Random(seed)
    report = MonteCarloReport(n_iterations=n_iterations)

    for i in range(n_iterations):
        if var_report is not None:
            initial = _generate_random_state(var_report, rng)
        else:
            initial = {}

        try:
            result_state = module.run(initial)

            display = result_state.get("_display", [])
            calls = result_state.get("_calls", [])
            execs = result_state.get("_execs", [])
            reads = result_state.get("_reads", [])
            writes = result_state.get("_writes", [])
            abended = result_state.get("_abended", False)

            iteration = IterationResult(
                iteration=i,
                initial_state=initial,
                final_state={k: v for k, v in result_state.items()
                             if not k.startswith("_")},
                display_output=display,
                calls_made=calls,
                execs_made=execs,
                reads=reads,
                writes=writes,
                abended=abended,
            )
            report.iterations.append(iteration)
            report.n_successful += 1

            if abended:
                report.n_abended += 1

            # Aggregate calls
            for call in calls:
                name = call.get("name", "UNKNOWN")
                report.call_frequency[name] = report.call_frequency.get(name, 0) + 1

            # Aggregate execs
            for ex in execs:
                kind = ex.get("kind", "UNKNOWN")
                report.exec_frequency[kind] = report.exec_frequency.get(kind, 0) + 1

            # Aggregate display messages
            for msg in display:
                key = str(msg)[:100]
                report.display_patterns[key] = report.display_patterns.get(key, 0) + 1

        except Exception as e:
            report.n_errors += 1
            report.error_messages.append(f"Iteration {i}: {type(e).__name__}: {e}")
            report.iterations.append(IterationResult(
                iteration=i,
                initial_state=initial,
                final_state={},
                display_output=[],
                calls_made=[],
                execs_made=[],
                reads=[],
                writes=[],
                abended=False,
                error=str(e),
            ))

    return report
