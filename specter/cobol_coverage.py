"""Agentic coverage-guided test generation engine for real COBOL programs.

Runs a compile-once / execute-many loop with layered strategies to maximize
paragraph and branch coverage on GnuCOBOL-compiled programs.  All generated
test cases are persisted to a JSONL test store for downstream use.
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import time
from dataclasses import dataclass, field
from pathlib import Path

from .cobol_executor import (
    CobolExecutionContext,
    CobolTestResult,
    prepare_context,
    run_test_case,
)
from .cobol_mock import generate_mock_data_ordered
from .models import Program
from .static_analysis import (
    StaticCallGraph,
    build_static_call_graph,
    compute_path_constraints,
    extract_gating_conditions,
    extract_sequential_gates,
    augment_gating_with_sequential_gates,
)
from .variable_domain import (
    VariableDomain,
    build_variable_domains,
    format_value_for_cobol,
    generate_value,
    load_copybooks,
    _FILE_STATUS_CODES,
    _SQL_STATUS_CODES,
    _CICS_STATUS_CODES,
    _DLI_STATUS_CODES,
)
from .variable_extractor import VariableReport, extract_stub_status_mapping, extract_variables

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class CoverageState:
    """Tracks cumulative coverage across all test cases."""

    paragraphs_hit: set[str] = field(default_factory=set)
    branches_hit: set[str] = field(default_factory=set)
    total_paragraphs: int = 0
    total_branches: int = 0
    test_cases: list[dict] = field(default_factory=list)


@dataclass
class CobolCoverageReport:
    """Summary of a coverage generation run."""

    total_test_cases: int = 0
    paragraph_coverage: float = 0.0
    branch_coverage: float = 0.0
    paragraphs_hit: int = 0
    paragraphs_total: int = 0
    branches_hit: int = 0
    branches_total: int = 0
    elapsed_seconds: float = 0.0
    layer_stats: dict[int, int] = field(default_factory=dict)

    def summary(self) -> str:
        lines = [
            "=== COBOL Coverage Report ===",
            f"  Test cases:  {self.total_test_cases}",
            f"  Paragraphs:  {self.paragraphs_hit}/{self.paragraphs_total} "
            f"({self.paragraph_coverage:.1%})",
            f"  Branches:    {self.branches_hit}/{self.branches_total} "
            f"({self.branch_coverage:.1%})",
            f"  Time:        {self.elapsed_seconds:.1f}s",
        ]
        if self.layer_stats:
            lines.append("  Per layer:")
            for layer, count in sorted(self.layer_stats.items()):
                lines.append(f"    Layer {layer}: {count} test cases")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Test case store (JSONL)
# ---------------------------------------------------------------------------

def _compute_tc_id(input_state: dict, stub_log: list) -> str:
    payload = json.dumps(
        {"input_state": input_state, "stub_log": stub_log},
        sort_keys=True, default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _save_test_case(
    store_path: Path,
    tc_id: str,
    input_state: dict,
    stub_log: list,
    result: CobolTestResult,
    layer: int,
    target: str,
) -> None:
    """Append a test case to the JSONL store."""
    record = {
        "id": tc_id,
        "input_state": {k: v for k, v in input_state.items() if not str(k).startswith("_")},
        "stub_outcomes": [[op, entries] for op, entries in stub_log],
        "paragraphs_hit": result.paragraphs_hit,
        "branches_hit": sorted(result.branches_hit),
        "display_output": result.display_output,
        "layer": layer,
        "target": target,
    }
    store_path.parent.mkdir(parents=True, exist_ok=True)
    with open(store_path, "a") as f:
        f.write(json.dumps(record, default=str) + "\n")


def load_existing_coverage(store_path: Path) -> tuple[list[dict], set[str], set[str]]:
    """Load existing test cases and compute baseline coverage."""
    if not store_path.exists():
        return [], set(), set()

    test_cases = []
    paras: set[str] = set()
    branches: set[str] = set()
    seen_ids: set[str] = set()

    for line in store_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "id" not in d or d.get("_type"):
            continue
        tc_id = d["id"]
        if tc_id in seen_ids:
            continue
        seen_ids.add(tc_id)
        test_cases.append(d)
        paras.update(d.get("paragraphs_hit", []))
        branches.update(d.get("branches_hit", []))

    return test_cases, paras, branches


# ---------------------------------------------------------------------------
# Python pre-run (for stub_log ordering)
# ---------------------------------------------------------------------------

def _python_pre_run(
    module,
    input_state: dict,
    stub_outcomes: dict | None = None,
    stub_defaults: dict | None = None,
) -> list[tuple[str, list]]:
    """Run the Python module to get execution-ordered stub_log.

    Returns stub_log: list of (op_key, entry) tuples.
    """
    state = {}
    default_state_fn = getattr(module, "_default_state", None)
    if default_state_fn:
        state = default_state_fn()
    state.update(input_state)

    if stub_outcomes:
        state["_stub_outcomes"] = {
            k: [list(e) if isinstance(e, list) else e for e in v]
            for k, v in stub_outcomes.items()
        }
    if stub_defaults:
        state["_stub_defaults"] = dict(stub_defaults)
    state["_stub_log"] = []

    try:
        result = module.run(state)
    except Exception:
        result = state

    return result.get("_stub_log", state.get("_stub_log", []))


# ---------------------------------------------------------------------------
# Value builders
# ---------------------------------------------------------------------------

def _build_input_state(
    domains: dict[str, VariableDomain],
    strategy: str,
    rng: random.Random,
    overrides: dict | None = None,
) -> dict[str, object]:
    """Build an input state dict using the domain model."""
    state: dict[str, object] = {}
    for name, dom in domains.items():
        if dom.classification not in ("input", "status", "flag"):
            continue
        if dom.set_by_stub:
            continue  # stub-controlled, not input
        val = generate_value(dom, strategy, rng)
        state[name] = format_value_for_cobol(dom, val)

    # CICS-aware defaults: ensure key EIB fields enable deeper execution
    upper_names = {n.upper(): n for n in state}
    if "EIBCALEN" in upper_names:
        # Set EIBCALEN > 0 to simulate returning transaction (not first entry)
        # This is critical for CICS programs to get past initialization logic
        state[upper_names["EIBCALEN"]] = str(rng.choice([20, 50, 100, 200]))
    if "EIBAID" in upper_names:
        # Common AID keys: ENTER, PF3 (return), PF7/PF8 (scroll)
        aids = ["ENTER", "DFHENTER", "DFHPF3", "DFHPF7", "DFHPF8", "DFHCLEAR"]
        state[upper_names["EIBAID"]] = rng.choice(aids)

    if overrides:
        state.update(overrides)
    return state


def _build_success_stubs(
    stub_mapping: dict[str, list[str]],
    domains: dict[str, VariableDomain],
) -> tuple[dict[str, list], dict[str, list]]:
    """Build all-success stub outcomes and defaults."""
    outcomes: dict[str, list] = {}
    defaults: dict[str, list] = {}

    for op_key, status_vars in stub_mapping.items():
        entries: list = []
        for var in status_vars:
            dom = domains.get(var)
            if dom and dom.semantic_type == "status_file":
                entries.append((var, "00"))
            elif dom and dom.semantic_type == "status_sql":
                entries.append((var, 0))
            elif dom and dom.semantic_type == "status_cics":
                entries.append((var, 0))
            elif op_key.startswith("DLI") or "PCB" in var.upper():
                entries.append((var, "  "))  # DLI success = spaces
            else:
                entries.append((var, "00"))

        if entries:
            outcomes.setdefault(op_key, []).append(entries)
            defaults[op_key] = entries

    return outcomes, defaults


def _build_fault_stubs(
    stub_mapping: dict[str, list[str]],
    domains: dict[str, VariableDomain],
    target_op: str | None = None,
    fault_value: str | int | None = None,
    rng: random.Random | None = None,
) -> tuple[dict[str, list], dict[str, list]]:
    """Build stubs with one operation returning an error code."""
    if rng is None:
        rng = random.Random()

    outcomes: dict[str, list] = {}
    defaults: dict[str, list] = {}

    for op_key, status_vars in stub_mapping.items():
        entries: list = []
        is_target = (target_op is not None and op_key == target_op)

        for var in status_vars:
            dom = domains.get(var)
            if is_target and fault_value is not None:
                entries.append((var, fault_value))
            elif is_target:
                # Pick a non-success value
                if dom and dom.semantic_type == "status_file":
                    entries.append((var, rng.choice(["10", "23", "35"])))
                elif dom and dom.semantic_type == "status_sql":
                    entries.append((var, rng.choice([100, -803, -805])))
                elif "PCB" in var.upper() or op_key.startswith("DLI"):
                    entries.append((var, rng.choice(["GE", "GB", "II"])))
                else:
                    entries.append((var, "10"))
            else:
                # Success for non-target ops
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


# ---------------------------------------------------------------------------
# Agentic coverage loop
# ---------------------------------------------------------------------------

def run_cobol_coverage(
    ast_file: str | Path,
    cobol_source: str | Path,
    copybook_dirs: list[str | Path] | None = None,
    budget: int = 5000,
    timeout: int = 600,
    store_path: str | Path | None = None,
    seed: int = 42,
    work_dir: str | Path | None = None,
) -> CobolCoverageReport:
    """Run coverage-guided test generation against real COBOL.

    Args:
        ast_file: Path to JSON AST file.
        cobol_source: Path to COBOL source (.cbl).
        copybook_dirs: Directories containing copybooks.
        budget: Maximum test cases to generate.
        timeout: Maximum seconds.
        store_path: Path for JSONL test store output.
        seed: Random seed for determinism.
        work_dir: Directory for build artifacts.

    Returns:
        CobolCoverageReport with coverage statistics.
    """
    from .ast_parser import parse_ast
    from .code_generator import generate_code
    from .monte_carlo import _load_module

    start_time = time.time()
    rng = random.Random(seed)
    copybook_dirs = list(copybook_dirs or [])

    # --- INITIALIZE ---
    log.info("Parsing AST: %s", ast_file)
    program = parse_ast(ast_file)
    var_report = extract_variables(program)
    call_graph = build_static_call_graph(program)
    gating_conds = extract_gating_conditions(program, call_graph)
    stub_mapping = extract_stub_status_mapping(program, var_report)
    seq_gates = extract_sequential_gates(program)
    if seq_gates:
        gating_conds = augment_gating_with_sequential_gates(
            gating_conds, seq_gates, call_graph,
        )

    # Build domain model
    log.info("Building variable domain model ...")
    copybook_records = load_copybooks(copybook_dirs) if copybook_dirs else []
    domains = build_variable_domains(var_report, copybook_records, stub_mapping)
    log.info("Domain model: %d variables (%d from copybooks)",
             len(domains), sum(1 for d in domains.values() if d.data_type != "unknown"))

    # Generate Python module for pre-runs
    log.info("Generating Python module for pre-runs ...")
    import tempfile
    code = generate_code(program, var_report, instrument=True)
    tmpdir = Path(tempfile.mkdtemp(prefix="specter_cov_"))
    py_path = tmpdir / f"{program.program_id}.py"
    py_path.write_text(code)
    module = _load_module(py_path)

    # Collect injectable variables: input/status/flag vars not set by stubs.
    # Limit to variables that appear in condition_literals or are key EIB fields,
    # to avoid overwhelming the init record mechanism.
    _ALWAYS_INJECT = {"EIBCALEN", "EIBAID", "EIBTRNID"}
    injectable = [
        name for name, dom in domains.items()
        if dom.classification in ("input", "status", "flag")
        and not dom.set_by_stub
        and (dom.condition_literals or dom.valid_88_values
             or name.upper() in _ALWAYS_INJECT
             or dom.semantic_type in ("status_file", "status_sql", "status_cics", "flag_bool"))
    ]
    log.info("Injectable variables: %d", len(injectable))

    # Prepare COBOL context (instrument + compile)
    log.info("Instrumenting and compiling COBOL ...")
    try:
        context = prepare_context(
            cobol_source, copybook_dirs,
            enable_branch_tracing=True,
            work_dir=work_dir,
            injectable_vars=injectable,
        )
    except RuntimeError as e:
        log.error("COBOL compilation failed: %s", e)
        return CobolCoverageReport(elapsed_seconds=time.time() - start_time)

    # Setup store
    if store_path is None:
        store_path = tmpdir / f"{program.program_id}_cobol_testset.jsonl"
    store_path = Path(store_path)

    # Load existing coverage
    existing_tcs, existing_paras, existing_branches = load_existing_coverage(store_path)

    # Coverage state
    cov = CoverageState(
        paragraphs_hit=existing_paras,
        branches_hit=existing_branches,
        total_paragraphs=context.total_paragraphs,
        total_branches=context.total_branches,
        test_cases=existing_tcs,
    )
    report = CobolCoverageReport(
        total_test_cases=len(existing_tcs),
        paragraphs_total=context.total_paragraphs,
        branches_total=context.total_branches,
    )

    if existing_tcs:
        log.info("Loaded %d existing TCs: %d paras, %d branches covered",
                 len(existing_tcs), len(existing_paras), len(existing_branches))

    all_paras = {p.name for p in program.paragraphs}
    tc_count = len(existing_tcs)

    def _time_ok() -> bool:
        return (time.time() - start_time) < timeout

    def _budget_ok() -> bool:
        return tc_count < budget

    def _execute_and_save(
        input_state: dict,
        stub_outcomes: dict | None,
        stub_defaults: dict | None,
        layer: int,
        target: str,
    ) -> bool:
        """Run Python pre-run → COBOL execution → save if new coverage."""
        nonlocal tc_count

        if not _time_ok() or not _budget_ok():
            return False

        # Python pre-run for stub_log ordering
        stub_log = _python_pre_run(module, input_state, stub_outcomes, stub_defaults)

        # COBOL execution
        result = run_test_case(context, input_state, stub_log)
        if result.error:
            return False

        # Check for new coverage
        new_paras = set(result.paragraphs_hit) - cov.paragraphs_hit
        new_branches = result.branches_hit - cov.branches_hit

        # Always save first few test cases; after that, only if new coverage
        force_save = tc_count < 5
        if not new_paras and not new_branches and not force_save:
            return False

        # Update coverage
        cov.paragraphs_hit.update(result.paragraphs_hit)
        cov.branches_hit.update(result.branches_hit)

        # Save
        tc_id = _compute_tc_id(input_state, stub_log)
        _save_test_case(store_path, tc_id, input_state, stub_log, result, layer, target)
        tc_count += 1
        report.layer_stats[layer] = report.layer_stats.get(layer, 0) + 1

        if new_paras:
            log.info("  L%d +%d paras → %d/%d: %s",
                     layer, len(new_paras), len(cov.paragraphs_hit),
                     cov.total_paragraphs, sorted(new_paras))
        if new_branches:
            log.info("  L%d +%d branches → %d/%d",
                     layer, len(new_branches), len(cov.branches_hit),
                     cov.total_branches)
        return True

    # --- LAYER 1: All-Success Baseline ---
    log.info("Layer 1: All-Success Baseline")
    success_stubs, success_defaults = _build_success_stubs(stub_mapping, domains)

    strategies = ["condition_literal", "semantic", "random_valid", "88_value", "boundary"]
    for strat in strategies:
        if not _time_ok() or not _budget_ok():
            break
        input_state = _build_input_state(domains, strat, rng)
        _execute_and_save(input_state, success_stubs, success_defaults, layer=1, target="baseline")

    # Also try with condition_literal values for each variable individually
    for name, dom in domains.items():
        if not _time_ok() or not _budget_ok():
            break
        if dom.condition_literals and dom.classification == "input":
            for lit in dom.condition_literals[:3]:
                base = _build_input_state(domains, "semantic", rng)
                base[name] = format_value_for_cobol(dom, lit)
                _execute_and_save(base, success_stubs, success_defaults, layer=1, target=f"lit:{name}")

    log.info("Layer 1 done: %d paras, %d branches",
             len(cov.paragraphs_hit), len(cov.branches_hit))

    # --- LAYER 2: Path-Constraint Satisfaction ---
    if _time_ok() and _budget_ok():
        log.info("Layer 2: Path-Constraint Satisfaction")
        uncovered = all_paras - cov.paragraphs_hit
        for target_para in sorted(uncovered):
            if not _time_ok() or not _budget_ok():
                break

            constraints = compute_path_constraints(target_para, call_graph, gating_conds)
            if constraints is None:
                continue

            # Try to satisfy constraints
            for variation in range(6):
                if not _time_ok() or not _budget_ok():
                    break

                base = _build_input_state(domains, "semantic", rng)

                # Apply gating constraints
                for gc in constraints.constraints:
                    dom = domains.get(gc.variable)
                    if dom and gc.values:
                        if gc.negated:
                            # Need a value NOT in the constraint set
                            val = generate_value(dom, "random_valid", rng)
                            attempts = 0
                            while val in gc.values and attempts < 10:
                                val = generate_value(dom, "random_valid", rng)
                                attempts += 1
                        else:
                            if variation < len(gc.values):
                                val = gc.values[variation]
                            else:
                                val = rng.choice(gc.values)
                        base[gc.variable] = format_value_for_cobol(dom, val)

                _execute_and_save(base, success_stubs, success_defaults,
                                  layer=2, target=target_para)

        log.info("Layer 2 done: %d paras, %d branches",
                 len(cov.paragraphs_hit), len(cov.branches_hit))

    # --- LAYER 3: Branch Solving ---
    if _time_ok() and _budget_ok():
        log.info("Layer 3: Branch Solving")
        _run_branch_solving(
            context, module, domains, stub_mapping,
            success_stubs, success_defaults,
            cov, store_path, report, rng,
            _time_ok, _budget_ok, _execute_and_save,
        )
        log.info("Layer 3 done: %d paras, %d branches",
                 len(cov.paragraphs_hit), len(cov.branches_hit))

    # --- LAYER 4: Stub Fault Injection ---
    if _time_ok() and _budget_ok():
        log.info("Layer 4: Stub Fault Injection")
        _run_fault_injection(
            module, domains, stub_mapping, cov,
            store_path, report, rng,
            _time_ok, _budget_ok, _execute_and_save,
        )
        log.info("Layer 4 done: %d paras, %d branches",
                 len(cov.paragraphs_hit), len(cov.branches_hit))

    # --- LAYER 5: Guided Random Walks ---
    if _time_ok() and _budget_ok():
        log.info("Layer 5: Guided Random Walks")
        _run_random_walks(
            module, domains, stub_mapping, cov,
            store_path, report, rng,
            _time_ok, _budget_ok, _execute_and_save,
            max_walks=200,
        )
        log.info("Layer 5 done: %d paras, %d branches",
                 len(cov.paragraphs_hit), len(cov.branches_hit))

    # --- LAYER 6: Monte Carlo Exploration ---
    if _time_ok() and _budget_ok():
        log.info("Layer 6: Monte Carlo Exploration")
        _run_monte_carlo(
            module, domains, stub_mapping, cov,
            store_path, report, rng,
            _time_ok, _budget_ok, _execute_and_save,
            max_iterations=min(budget - tc_count, 2000),
        )
        log.info("Layer 6 done: %d paras, %d branches",
                 len(cov.paragraphs_hit), len(cov.branches_hit))

    # --- FINALIZE ---
    elapsed = time.time() - start_time
    report.total_test_cases = tc_count
    report.paragraphs_hit = len(cov.paragraphs_hit)
    report.branches_hit = len(cov.branches_hit)
    report.elapsed_seconds = elapsed
    if cov.total_paragraphs > 0:
        report.paragraph_coverage = len(cov.paragraphs_hit) / cov.total_paragraphs
    if cov.total_branches > 0:
        report.branch_coverage = len(cov.branches_hit) / cov.total_branches

    log.info("Coverage complete: %s", report.summary())
    return report


# ---------------------------------------------------------------------------
# Layer 3: Branch Solving
# ---------------------------------------------------------------------------

def _run_branch_solving(
    context, module, domains, stub_mapping,
    success_stubs, success_defaults,
    cov, store_path, report, rng,
    time_ok, budget_ok, execute_and_save,
):
    """For each uncovered branch, try to craft inputs that reach it."""
    branch_meta = context.branch_meta
    if not branch_meta:
        return

    from .static_analysis import _parse_condition_variables

    for bid, meta in branch_meta.items():
        if not time_ok() or not budget_ok():
            break

        # Check which directions are uncovered
        for direction in ("T", "F"):
            branch_key = f"{bid}:{direction}"
            if branch_key in cov.branches_hit:
                continue

            condition = meta.get("condition", "")
            if not condition:
                continue

            # Parse condition variables
            try:
                parsed = _parse_condition_variables(condition)
            except Exception:
                continue

            for attempt in range(3):
                if not time_ok() or not budget_ok():
                    break

                base = _build_input_state(domains, "semantic", rng)

                for var_name, values, negated in parsed:
                    dom = domains.get(var_name)
                    if not dom:
                        continue

                    want_true = (direction == "T")
                    want_match = want_true != negated  # XOR

                    if want_match and values:
                        # Pick a matching value
                        val = values[attempt % len(values)] if values else generate_value(dom, "random_valid", rng)
                    else:
                        # Pick a non-matching value
                        val = generate_value(dom, "boundary" if attempt == 0 else "random_valid", rng)
                        retry = 0
                        while val in values and retry < 10:
                            val = generate_value(dom, "random_valid", rng)
                            retry += 1

                    base[var_name] = format_value_for_cobol(dom, val)

                execute_and_save(base, success_stubs, success_defaults,
                                 layer=3, target=f"branch:{bid}:{direction}")


# ---------------------------------------------------------------------------
# Layer 4: Stub Fault Injection
# ---------------------------------------------------------------------------

def _run_fault_injection(
    module, domains, stub_mapping, cov,
    store_path, report, rng,
    time_ok, budget_ok, execute_and_save,
):
    """Inject error codes for each stub operation."""
    fault_tables = {
        "status_file": ["10", "23", "35", "39", "46", "47"],
        "status_sql": [0, 100, -803, -805, -904],
        "status_cics": [0, 12, 13, 16, 22, 27],
    }

    for op_key, status_vars in stub_mapping.items():
        if not time_ok() or not budget_ok():
            break

        # Determine fault values to try
        fault_values: list = []
        for var in status_vars:
            dom = domains.get(var)
            if dom:
                table = fault_tables.get(dom.semantic_type, [])
                fault_values.extend(table)

        # DLI operations
        if op_key.startswith("DLI") or any("PCB" in v.upper() for v in status_vars):
            fault_values.extend(["GE", "GB", "II", "AI"])

        if not fault_values:
            fault_values = ["10", "23", "35"]

        for fv in fault_values[:5]:
            if not time_ok() or not budget_ok():
                break

            base = _build_input_state(domains, "semantic", rng)
            fault_stubs, fault_defaults = _build_fault_stubs(
                stub_mapping, domains, target_op=op_key, fault_value=fv, rng=rng,
            )
            execute_and_save(base, fault_stubs, fault_defaults,
                             layer=4, target=f"fault:{op_key}={fv}")


# ---------------------------------------------------------------------------
# Layer 5: Guided Random Walks
# ---------------------------------------------------------------------------

def _run_random_walks(
    module, domains, stub_mapping, cov,
    store_path, report, rng,
    time_ok, budget_ok, execute_and_save,
    max_walks: int = 200,
):
    """Mutate high-coverage test cases to explore nearby coverage."""
    if not cov.test_cases:
        return

    # Sort by coverage (most paragraphs first)
    ranked = sorted(
        cov.test_cases,
        key=lambda tc: len(tc.get("paragraphs_hit", [])),
        reverse=True,
    )[:10]  # Top 10 as mutation bases

    input_vars = [
        name for name, dom in domains.items()
        if dom.classification in ("input", "flag") and not dom.set_by_stub
    ]

    success_stubs, success_defaults = _build_success_stubs(stub_mapping, domains)

    walks_done = 0
    for tc in ranked:
        if not time_ok() or not budget_ok() or walks_done >= max_walks:
            break

        base_state = dict(tc.get("input_state", {}))

        for _ in range(max_walks // len(ranked)):
            if not time_ok() or not budget_ok() or walks_done >= max_walks:
                break

            # Mutate 1-3 variables
            mutated = dict(base_state)
            n_mutations = rng.randint(1, 3)
            vars_to_mutate = rng.sample(input_vars, min(n_mutations, len(input_vars)))

            for var_name in vars_to_mutate:
                dom = domains.get(var_name)
                if not dom:
                    continue
                # 70% condition_literal/88_value, 30% random
                if rng.random() < 0.7 and (dom.condition_literals or dom.valid_88_values):
                    strategy = "condition_literal" if dom.condition_literals else "88_value"
                else:
                    strategy = "random_valid"
                val = generate_value(dom, strategy, rng)
                mutated[var_name] = format_value_for_cobol(dom, val)

            # Occasionally mutate stubs too
            if rng.random() < 0.3 and stub_mapping:
                op_key = rng.choice(list(stub_mapping.keys()))
                stubs, defaults = _build_fault_stubs(stub_mapping, domains, target_op=op_key, rng=rng)
            else:
                stubs, defaults = success_stubs, success_defaults

            execute_and_save(mutated, stubs, defaults,
                             layer=5, target="walk")
            walks_done += 1


# ---------------------------------------------------------------------------
# Layer 6: Monte Carlo Exploration
# ---------------------------------------------------------------------------

def _run_monte_carlo(
    module, domains, stub_mapping, cov,
    store_path, report, rng,
    time_ok, budget_ok, execute_and_save,
    max_iterations: int = 2000,
):
    """Broad random search with mixed strategies."""
    success_stubs, success_defaults = _build_success_stubs(stub_mapping, domains)

    for iteration in range(max_iterations):
        if not time_ok() or not budget_ok():
            break

        # Pick strategy mix
        roll = rng.random()
        if roll < 0.4:
            strategy = "random_valid"
        elif roll < 0.6:
            strategy = "boundary"
        elif roll < 0.8:
            strategy = "adversarial"
        else:
            strategy = "semantic"

        input_state = _build_input_state(domains, strategy, rng)

        # Mix stubs: mostly success, sometimes faults
        if rng.random() < 0.3 and stub_mapping:
            op_key = rng.choice(list(stub_mapping.keys()))
            stubs, defaults = _build_fault_stubs(stub_mapping, domains, target_op=op_key, rng=rng)
        else:
            stubs, defaults = success_stubs, success_defaults

        execute_and_save(input_state, stubs, defaults,
                         layer=6, target="monte_carlo")

        # Periodic progress logging
        if (iteration + 1) % 200 == 0:
            log.info("  L6 iteration %d: %d paras, %d branches",
                     iteration + 1, len(cov.paragraphs_hit), len(cov.branches_hit))
