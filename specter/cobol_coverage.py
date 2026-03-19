"""Agentic coverage-guided test generation engine.

Runs an execute-many loop with pluggable strategies to maximize paragraph and
branch coverage.  Supports both Python-only execution (from AST) and
GnuCOBOL-compiled programs.  A strategy selector picks the next strategy based
on coverage feedback.  All generated test cases are persisted to a JSONL test
store for downstream use.
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
from .coverage_strategies import (
    BaselineStrategy,
    BranchSolverStrategy,
    ConstraintSolverStrategy,
    DirectParagraphStrategy,
    FaultInjectionStrategy,
    GuidedMutationStrategy,
    HeuristicSelector,
    IntentDrivenStrategy,
    LLMGapStrategy,
    LLMSeedStrategy,
    LLMSelector,
    MonteCarloStrategy,
    Strategy,
    StrategyContext,
    StrategyYield,
    StubWalkStrategy,
)
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
    runtime_only_paragraphs: set[str] = field(default_factory=set)
    branches_hit: set[str] = field(default_factory=set)
    total_paragraphs: int = 0
    total_branches: int = 0
    test_cases: list[dict] = field(default_factory=list)
    all_paragraphs: set[str] = field(default_factory=set)
    strategy_yields: dict[str, StrategyYield] = field(default_factory=dict)
    stale_rounds: int = 0
    # Kept for strategies that check stub_mapping availability
    _stub_mapping: dict[str, list[str]] = field(default_factory=dict)


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
    runtime_trace_total: int = 0
    runtime_only_paragraphs: int = 0
    layer_stats: dict[str, int] = field(default_factory=dict)

    def summary(self) -> str:
        lines = [
            "=== COBOL Coverage Report ===",
            f"  Test cases:  {self.total_test_cases}",
            f"  Paragraphs:  {self.paragraphs_hit}/{self.paragraphs_total} "
            f"({self.paragraph_coverage:.1%})",
            f"  Runtime paragraph labels: {self.runtime_trace_total} "
            f"(runtime-only: {self.runtime_only_paragraphs})",
            f"  Branches:    {self.branches_hit}/{self.branches_total} "
            f"({self.branch_coverage:.1%})",
            f"  Time:        {self.elapsed_seconds:.1f}s",
        ]
        if self.layer_stats:
            lines.append("  Per strategy:")
            for name, count in sorted(self.layer_stats.items()):
                lines.append(f"    {name}: {count} test cases")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# LLM seed injector (one-shot strategy from pre-generated seeds)
# ---------------------------------------------------------------------------

class _LLMSeedInjector(Strategy):
    """Injects pre-generated LLM seeds as test cases.  Runs once."""

    name = "llm_seeds"
    priority = 5  # run first

    def __init__(self, seeds: list[dict], stub_mapping: dict[str, list[str]]):
        self._seeds = seeds
        self._stub_mapping = stub_mapping
        self._ran = False

    def should_run(self, cov, round_num: int) -> bool:
        return not self._ran

    def generate_cases(self, ctx, cov, batch_size):
        self._ran = True
        for seed_data in self._seeds:
            input_state = {}
            for var, val in seed_data.get("input_values", {}).items():
                dom = ctx.domains.get(var.upper())
                if dom:
                    input_state[var.upper()] = format_value_for_cobol(dom, val)
                else:
                    input_state[var.upper()] = str(val)

            # Build stubs from overrides
            stubs = dict(ctx.success_stubs)
            defaults = dict(ctx.success_defaults)
            for op_key, status_val in seed_data.get("stub_overrides", {}).items():
                matched = _match_stub_operation(op_key, self._stub_mapping)
                if matched:
                    svars = self._stub_mapping[matched]
                    entry = [(sv, status_val) for sv in svars]
                    stubs[matched] = [entry] * 50
                    defaults[matched] = entry

            target = seed_data.get("target", "llm_seed")[:50]
            yield input_state, stubs, defaults, f"seed:{target}"


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
    layer: str | int,
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


def _python_execute(
    module,
    input_state: dict,
    stub_outcomes: dict | None = None,
    stub_defaults: dict | None = None,
    paragraph: str | None = None,
) -> CobolTestResult:
    """Run the Python module and return a CobolTestResult-compatible object.

    If *paragraph* is given, invokes that paragraph directly instead of
    running from the program entry point.  This is much faster and can
    reach branches not reachable through the normal entry.
    """
    from .monte_carlo import _run_paragraph_directly

    default_state_fn = getattr(module, "_default_state", None)
    state = default_state_fn() if default_state_fn else {}
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
        if paragraph:
            rs = _run_paragraph_directly(module, paragraph, state)
            if not rs:
                return CobolTestResult(error="paragraph not found")
        else:
            rs = module.run(state)
    except Exception as exc:
        return CobolTestResult(error=f"{type(exc).__name__}: {exc}")

    # Convert integer branches to "py:<bid>:T"/"py:<bid>:F" string format.
    # The "py:" prefix prevents collision with COBOL branch IDs (@@B:)
    # since the two numbering schemes are independent.
    raw_branches = rs.get("_branches", set())
    branches_hit: set[str] = set()
    for b in raw_branches:
        if b > 0:
            branches_hit.add(f"py:{b}:T")
        elif b < 0:
            branches_hit.add(f"py:{abs(b)}:F")

    trace = rs.get("_trace", [])
    paragraphs_hit = list(dict.fromkeys(trace))
    display_output = rs.get("_display", [])

    return CobolTestResult(
        paragraphs_hit=paragraphs_hit,
        branches_hit=branches_hit,
        display_output=display_output,
    )


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


def _build_siblings_88(copybook_records) -> dict[str, set[str]]:
    """Build 88-level siblings map from copybook records."""
    siblings: dict[str, set[str]] = {}
    if not copybook_records:
        return siblings
    for rec in copybook_records:
        for fld in rec.fields:
            if fld.values_88:
                names = {n.upper() for n in fld.values_88.keys()}
                for name in names:
                    siblings[name] = names - {name}
    return siblings


def _expand_stub_mapping(
    stub_mapping: dict[str, list[str]],
    siblings_88: dict[str, set[str]],
) -> set[str]:
    """Expand stub mapping to include 88-level sibling vars.

    Returns the set of var names that were added (not in the original mapping).
    """
    added: set[str] = set()
    for op_key in list(stub_mapping.keys()):
        status_vars = stub_mapping[op_key]
        original = {v.upper() for v in status_vars}
        to_add: set[str] = set()
        for var in status_vars:
            to_add.update(siblings_88.get(var.upper(), set()))
        for var in sorted(to_add - original):
            status_vars.append(var)
            added.add(var.upper())
    return added


def _build_success_stubs(
    stub_mapping: dict[str, list[str]],
    domains: dict[str, VariableDomain],
    flag_88_added: set[str] | None = None,
    siblings_88: dict[str, set[str]] | None = None,
) -> tuple[dict[str, list], dict[str, list]]:
    """Build all-success stub outcomes and defaults.

    For READ operations: generates multiple success records followed by EOF
    ('10'), with default set to EOF so PERFORM UNTIL loops terminate.
    For other operations: single success entry with success default.

    88-level flags (identified by flag_88_added / siblings_88) are set to
    True for success indicators (original mapping vars) and False for their
    siblings (added vars).
    """
    flag_88_added = flag_88_added or set()
    siblings_88 = siblings_88 or {}
    outcomes: dict[str, list] = {}
    defaults: dict[str, list] = {}

    for op_key, status_vars in stub_mapping.items():
        is_read = op_key.startswith("READ:")

        # Identify the primary success flag among 88-level vars.
        # Heuristic: prefer vars with OK/SUCCESS in name, else first original.
        _88_originals = [v for v in status_vars
                         if v.upper() in siblings_88 and v.upper() not in flag_88_added]
        _success_flag = None
        for v in _88_originals:
            if any(kw in v.upper() for kw in ("OK", "SUCCESS", "FOUND")):
                _success_flag = v.upper()
                break
        if not _success_flag and _88_originals:
            _success_flag = _88_originals[0].upper()

        success_entries: list = []
        eof_entries: list = []
        for var in status_vars:
            dom = domains.get(var)
            var_upper = var.upper()
            is_88 = var_upper in siblings_88 or var_upper in flag_88_added
            # 88-level: only the primary success flag is True
            if is_88 and _success_flag:
                success_entries.append((var, var_upper == _success_flag))
                eof_entries.append((var, False))
            elif dom and dom.semantic_type == "status_file":
                success_entries.append((var, "00"))
                eof_entries.append((var, "10"))
            elif dom and dom.semantic_type == "status_sql":
                success_entries.append((var, 0))
                eof_entries.append((var, 100))
            elif dom and dom.semantic_type == "status_cics":
                success_entries.append((var, 0))
                eof_entries.append((var, 0))
            elif op_key.startswith("DLI") or "PCB" in var.upper():
                success_entries.append((var, "  "))
                eof_entries.append((var, "GB"))
            else:
                success_entries.append((var, "00"))
                eof_entries.append((var, "10"))

        if success_entries:
            if is_read:
                # 5 success reads then EOF — enough for loop body coverage
                outcome_list = [success_entries] * 5 + [eof_entries]
                outcomes[op_key] = outcome_list
                defaults[op_key] = eof_entries  # loop terminates on exhaustion
            else:
                outcomes.setdefault(op_key, []).append(success_entries)
                defaults[op_key] = success_entries

    return outcomes, defaults


def _build_fault_stubs(
    stub_mapping: dict[str, list[str]],
    domains: dict[str, VariableDomain],
    target_op: str | None = None,
    fault_value: str | int | None = None,
    rng: random.Random | None = None,
    flag_88_added: set[str] | None = None,
    siblings_88: dict[str, set[str]] | None = None,
) -> tuple[dict[str, list], dict[str, list]]:
    """Build stubs with one operation returning an error code.

    For 88-level flags, fault_value is interpreted as the flag name to
    activate (set to True) while all siblings are set to False.
    """
    if rng is None:
        rng = random.Random()
    flag_88_added = flag_88_added or set()
    siblings_88 = siblings_88 or {}

    outcomes: dict[str, list] = {}
    defaults: dict[str, list] = {}

    for op_key, status_vars in stub_mapping.items():
        entries: list = []
        is_target = (target_op is not None and op_key == target_op)

        # Check if this op has 88-level flags
        has_88 = any(v.upper() in siblings_88 or v.upper() in flag_88_added
                     for v in status_vars)

        # If targeting an op with 88-level flags and fault_value is a flag name,
        # set that flag True and all others False
        target_flag = None
        if is_target and has_88 and isinstance(fault_value, str):
            fv_upper = fault_value.upper()
            if fv_upper in siblings_88 or fv_upper in flag_88_added:
                target_flag = fv_upper

        for var in status_vars:
            dom = domains.get(var)
            var_upper = var.upper()
            is_88 = var_upper in siblings_88 or var_upper in flag_88_added

            if is_target and target_flag:
                # 88-level targeted fault: activate the target, clear others
                entries.append((var, var_upper == target_flag))
            elif is_target and is_88 and not target_flag:
                # 88-level var but fault_value is a status code (e.g. "GE")
                # Set original flags to False, added siblings to False
                entries.append((var, False))
            elif is_target and fault_value is not None:
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
                if var_upper in flag_88_added:
                    entries.append((var, False))
                elif var_upper in siblings_88:
                    entries.append((var, True))
                elif dom and dom.semantic_type == "status_file":
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
# Stub matching helper
# ---------------------------------------------------------------------------

def _match_stub_operation(
    llm_key: str,
    stub_mapping: dict[str, list[str]],
) -> str | None:
    """Match an LLM-provided operation key to a stub_mapping key.

    The LLM might say "READ:XREF" but stub_mapping has "READ:XREF-FILE".
    Uses fuzzy matching on the operation type and file/program name.
    """
    upper = llm_key.upper().strip()
    # Exact match
    if upper in stub_mapping:
        return upper
    # Try case-insensitive
    for key in stub_mapping:
        if key.upper() == upper:
            return key
    # Fuzzy: match operation prefix + substring of target
    if ":" in upper:
        op_type, target = upper.split(":", 1)
        for key in stub_mapping:
            if ":" in key:
                k_op, k_target = key.split(":", 1)
                if k_op.upper() == op_type and target in k_target.upper():
                    return key
            elif key.upper().startswith(op_type):
                return key
    else:
        # No colon — match if the key starts with the LLM key
        for key in stub_mapping:
            if key.upper().startswith(upper):
                return key
    return None


# ---------------------------------------------------------------------------
# Standalone execute-and-save
# ---------------------------------------------------------------------------

def _execute_and_save(
    ctx: StrategyContext,
    cov: CoverageState,
    input_state: dict,
    stub_outcomes: dict | None,
    stub_defaults: dict | None,
    strategy_name: str,
    target: str,
    report: CobolCoverageReport,
    tc_count: int,
) -> tuple[bool, int]:
    """Execute a test case and save if new coverage is found.

    Supports both COBOL (ctx.context is set) and Python-only (ctx.context is
    None) execution modes.  Returns (saved, updated_tc_count).
    """
    # Parse direct paragraph invocation from target string
    direct_para = None
    if target.startswith("direct:"):
        direct_para = target[7:].split("|", 1)[0]

    if ctx.context is not None:
        if direct_para:
            # Direct paragraph invocation: use Python for speed, COBOL can't
            # invoke individual paragraphs.  Python execution still gives
            # valid branch coverage from the generated module.
            result = _python_execute(
                ctx.module, input_state, stub_outcomes, stub_defaults,
                paragraph=direct_para,
            )
            stub_log = []
        else:
            # Full program: pre-run Python for stub ordering, then COBOL
            stub_log = _python_pre_run(ctx.module, input_state, stub_outcomes, stub_defaults)
            result = run_test_case(ctx.context, input_state, stub_log)
    else:
        # Python-only execution path
        result = _python_execute(
            ctx.module, input_state, stub_outcomes, stub_defaults,
            paragraph=direct_para,
        )
        stub_log = []

    if result.error:
        return False, tc_count

    # Normalize paragraph coverage to AST-known labels. Keep runtime-only labels
    # in a side channel for diagnostics/reporting.
    result_paras = set(result.paragraphs_hit)
    if cov.all_paragraphs:
        result_ast_paras = result_paras & cov.all_paragraphs
        result_runtime_only = result_paras - cov.all_paragraphs
    else:
        result_ast_paras = result_paras
        result_runtime_only = set()

    # Check for new coverage
    new_paras = result_ast_paras - cov.paragraphs_hit
    new_runtime_only = result_runtime_only - cov.runtime_only_paragraphs
    new_branches = result.branches_hit - cov.branches_hit

    # Always save first few test cases; after that, only if new coverage
    force_save = tc_count < 5
    if not new_paras and not new_branches and not new_runtime_only and not force_save:
        return False, tc_count

    # Update coverage
    cov.paragraphs_hit.update(result_ast_paras)
    cov.runtime_only_paragraphs.update(result_runtime_only)
    cov.branches_hit.update(result.branches_hit)

    # Save
    tc_id = _compute_tc_id(input_state, stub_log)
    _save_test_case(
        ctx.store_path, tc_id, input_state, stub_log, result,
        strategy_name, target,
    )
    tc_count += 1
    report.layer_stats[strategy_name] = report.layer_stats.get(strategy_name, 0) + 1

    # Keep in-memory test_cases in sync so mid-run strategies can use them
    cov.test_cases.append({
        "id": tc_id,
        "input_state": {k: v for k, v in input_state.items() if not str(k).startswith("_")},
        "stub_outcomes": [[op, entries] for op, entries in stub_log],
        "paragraphs_hit": result.paragraphs_hit,
        "branches_hit": sorted(result.branches_hit),
        "layer": strategy_name,
        "target": target,
    })

    if new_paras:
        log.info("  [%s] +%d paras -> %d/%d: %s",
                 strategy_name, len(new_paras), len(cov.paragraphs_hit),
                 cov.total_paragraphs, sorted(new_paras))
    if new_branches:
        log.info("  [%s] +%d branches -> %d/%d",
                 strategy_name, len(new_branches), len(cov.branches_hit),
                 cov.total_branches)
    if new_runtime_only:
        log.info("  [%s] +%d runtime-only paras (not in AST)",
                 strategy_name, len(new_runtime_only))
    return True, tc_count


# ---------------------------------------------------------------------------
# Agentic coverage loop
# ---------------------------------------------------------------------------

def run_cobol_coverage(
    ast_file: str | Path,
    cobol_source: str | Path,
    copybook_dirs: list[str | Path] | None = None,
    budget: int = 5000,
    timeout: int = 1800,
    store_path: str | Path | None = None,
    seed: int = 42,
    work_dir: str | Path | None = None,
    llm_provider=None,
    llm_model: str | None = None,
    max_rounds: int = 0,
    batch_size: int = 200,
    strict_branch_coverage: bool = False,
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
    code = generate_code(program, var_report, instrument=True,
                         copybook_records=copybook_records)
    tmpdir = Path(tempfile.mkdtemp(prefix="specter_cov_"))
    py_path = tmpdir / f"{program.program_id}.py"
    py_path.write_text(code)
    module = _load_module(py_path)

    # Injectable variables for the init dispatch
    _EIB_NAMES = {"EIBCALEN", "EIBAID", "EIBTRNID", "EIBTIME", "EIBDATE",
                  "EIBTASKN", "EIBTRMID", "EIBCPOSN", "EIBFN", "EIBRCODE",
                  "EIBDS", "EIBREQID", "EIBRSRCE", "EIBRESP", "EIBRESP2"}
    injectable = [
        name for name, dom in domains.items()
        if dom.classification in ("input", "status", "flag")
        and not dom.set_by_stub
        and name.upper() not in _EIB_NAMES
        and (dom.condition_literals or dom.valid_88_values)
    ]
    log.info("Injectable variables: %d", len(injectable))

    # Prepare COBOL context (instrument + compile)
    log.info("Instrumenting and compiling COBOL ...")
    try:
        # Don't pass injectable_vars — the init dispatch EVALUATE that Phase 10
        # generates often gets destroyed by Phase 12, and the destruction
        # cascades into neutralizing paragraphs and branches.  EIB fields are
        # already set via VALUE clauses in coverage mode.  Input values are
        # varied through the Python pre-run's stub_outcomes instead.
        context = prepare_context(
            cobol_source, copybook_dirs,
            enable_branch_tracing=True,
            work_dir=work_dir,
            injectable_vars=[],
            coverage_mode=True,
            allow_hardening_fallback=not strict_branch_coverage,
        )
    except RuntimeError as e:
        log.error("COBOL compilation failed: %s", e)
        if strict_branch_coverage:
            raise
        return CobolCoverageReport(elapsed_seconds=time.time() - start_time)

    if strict_branch_coverage and context.total_branches == 0:
        msg = (
            "Strict branch coverage requested, but no COBOL branch probes were "
            "generated (0/0)."
        )
        if context.hardened_mode:
            msg += (
                " Hardening fallback is active (SPECTER-HARDENED-ENTRY), which "
                "typically removes executable IF/EVALUATE constructs."
            )
        raise RuntimeError(msg)

    # Setup store
    if store_path is None:
        store_path = tmpdir / f"{program.program_id}_cobol_testset.jsonl"
    store_path = Path(store_path)

    # Load existing coverage
    existing_tcs, existing_paras, existing_branches = load_existing_coverage(store_path)

    # Expand stub mapping with 88-level siblings
    siblings_88 = _build_siblings_88(copybook_records)
    flag_88_added = _expand_stub_mapping(stub_mapping, siblings_88)
    if flag_88_added:
        log.info("Expanded stub mapping with %d 88-level siblings: %s",
                 len(flag_88_added), sorted(flag_88_added))

    # Build success stubs
    success_stubs, success_defaults = _build_success_stubs(
        stub_mapping, domains,
        flag_88_added=flag_88_added, siblings_88=siblings_88,
    )

    all_paras = {p.name for p in program.paragraphs}
    existing_ast_paras = existing_paras & all_paras
    existing_runtime_only = existing_paras - all_paras

    # Coverage state
    cov = CoverageState(
        paragraphs_hit=existing_ast_paras,
        runtime_only_paragraphs=existing_runtime_only,
        branches_hit=existing_branches,
        total_paragraphs=len(all_paras),
        total_branches=context.total_branches,
        test_cases=existing_tcs,
        all_paragraphs=all_paras,
        _stub_mapping=stub_mapping,
    )
    report = CobolCoverageReport(
        total_test_cases=len(existing_tcs),
        paragraphs_total=len(all_paras),
        runtime_trace_total=context.total_paragraphs,
        runtime_only_paragraphs=len(existing_runtime_only),
        branches_total=context.total_branches,
    )

    if existing_tcs:
        log.info("Loaded %d existing TCs: %d AST paras, %d runtime-only paras, %d branches covered",
                 len(existing_tcs), len(existing_ast_paras), len(existing_runtime_only),
                 len(existing_branches))

    tc_count = len(existing_tcs)

    # --- BUILD STRATEGY CONTEXT ---
    ctx = StrategyContext(
        module=module,
        context=context,
        domains=domains,
        stub_mapping=stub_mapping,
        call_graph=call_graph,
        gating_conds=gating_conds,
        var_report=var_report,
        program=program,
        all_paragraphs=all_paras,
        success_stubs=success_stubs,
        success_defaults=success_defaults,
        rng=rng,
        store_path=store_path,
        branch_meta=context.branch_meta,
        cobol_source_path=Path(cobol_source),
        llm_provider=llm_provider,
        llm_model=llm_model,
        siblings_88=siblings_88,
        flag_88_added=flag_88_added,
    )

    # --- REGISTER STRATEGIES ---
    strategies: list[Strategy] = [
        BaselineStrategy(),
        ConstraintSolverStrategy(),
        DirectParagraphStrategy(),
        BranchSolverStrategy(),
        FaultInjectionStrategy(),
        StubWalkStrategy(),
        GuidedMutationStrategy(),
        MonteCarloStrategy(),
    ]
    if llm_provider:
        strategies.extend([
            LLMSeedStrategy(llm_provider, llm_model),
            LLMGapStrategy(llm_provider, llm_model),
            IntentDrivenStrategy(llm_provider, llm_model),
        ])

    selector = (
        LLMSelector(llm_provider, llm_model,
                     default_batch_size=batch_size,
                     var_report=var_report)
        if llm_provider
        else HeuristicSelector(default_batch_size=batch_size)
    )

    return _run_agentic_loop(
        ctx, cov, report, strategies, selector,
        budget, timeout, start_time, tc_count,
        max_rounds=max_rounds,
    )


# ---------------------------------------------------------------------------
# Shared agentic loop
# ---------------------------------------------------------------------------

def _run_agentic_loop(
    ctx: StrategyContext,
    cov: CoverageState,
    report: CobolCoverageReport,
    strategies: list[Strategy],
    selector,
    budget: int,
    timeout: int | float,
    start_time: float,
    tc_count: int,
    max_rounds: int = 0,
) -> CobolCoverageReport:
    """Run the strategy-based agentic coverage loop.

    Shared between run_cobol_coverage() and run_coverage().
    """
    round_num = 0
    while tc_count < budget and (time.time() - start_time) < timeout:
        if max_rounds > 0 and round_num >= max_rounds:
            log.info("Max rounds (%d) reached", max_rounds)
            break
        strategy, batch_size = selector.select(strategies, cov, round_num)
        round_new = 0
        round_cov_before = len(cov.paragraphs_hit) + len(cov.branches_hit)

        log.info("Round %d: %s (batch=%d)", round_num, strategy.name, batch_size)

        cases_tried = 0
        for input_state, stubs, defaults, target in strategy.generate_cases(ctx, cov, batch_size):
            if tc_count >= budget or (time.time() - start_time) >= timeout:
                break

            saved, tc_count = _execute_and_save(
                ctx, cov, input_state, stubs, defaults,
                strategy.name, target, report, tc_count,
            )
            if saved:
                round_new += 1

            cases_tried += 1
            if round_new >= batch_size:
                break

        # Record yield for this strategy
        round_cov_after = len(cov.paragraphs_hit) + len(cov.branches_hit)
        new_coverage = round_cov_after - round_cov_before

        sy = cov.strategy_yields.setdefault(strategy.name, StrategyYield())
        sy.total_cases += cases_tried
        sy.total_new_coverage += new_coverage
        sy.rounds += 1
        if new_coverage > 0:
            sy.last_yield_round = round_num

        log.info("Round %d done: %s -> %d new TCs, +%d coverage (%d/%d paras, %d/%d branches)",
                 round_num, strategy.name, round_new, new_coverage,
                 len(cov.paragraphs_hit), cov.total_paragraphs,
                 len(cov.branches_hit), cov.total_branches)

        # Staleness detection
        if new_coverage == 0:
            cov.stale_rounds += 1
        else:
            cov.stale_rounds = 0

        # Early termination conditions
        full_para = (cov.total_paragraphs > 0
                     and len(cov.paragraphs_hit) >= cov.total_paragraphs)
        full_branch = (cov.total_branches > 0
                       and len(cov.branches_hit) >= cov.total_branches)
        if full_para and full_branch:
            log.info("Full coverage achieved!")
            break

        if cov.stale_rounds >= 10 and cov.total_paragraphs > 0:
            para_pct = len(cov.paragraphs_hit) / cov.total_paragraphs
            branch_pct = (len(cov.branches_hit) / cov.total_branches
                          if cov.total_branches > 0 else 1.0)
            if para_pct > 0.9 and branch_pct > 0.8:
                log.info("Plateau detected at %.1f%% para / %.1f%% branch, stopping",
                         para_pct * 100, branch_pct * 100)
                break
            # Extended patience when branch coverage is still low
            if cov.stale_rounds >= 30:
                log.info("Extended plateau at %.1f%% para / %.1f%% branch, stopping",
                         para_pct * 100, branch_pct * 100)
                break

        round_num += 1

    # --- FINALIZE ---
    elapsed = time.time() - start_time
    report.total_test_cases = tc_count
    report.paragraphs_hit = len(cov.paragraphs_hit)
    report.runtime_only_paragraphs = len(cov.runtime_only_paragraphs)
    # In COBOL mode, only count COBOL branches (not py:-prefixed Python ones).
    # In Python-only mode (ctx.context is None), all branches count.
    if ctx.context is not None:
        counted_branches = {b for b in cov.branches_hit if not b.startswith("py:")}
    else:
        counted_branches = cov.branches_hit
    report.branches_hit = len(counted_branches)
    report.elapsed_seconds = elapsed
    if cov.total_paragraphs > 0:
        report.paragraph_coverage = len(cov.paragraphs_hit) / cov.total_paragraphs
    if cov.total_branches > 0:
        report.branch_coverage = len(counted_branches) / cov.total_branches

    log.info("Coverage complete: %s", report.summary())
    return report


# ---------------------------------------------------------------------------
# Python-only coverage entry point
# ---------------------------------------------------------------------------

def run_coverage(
    ast_file: str | Path,
    *,
    copybook_dirs: list[str | Path] | None = None,
    cobol_source: str | Path | None = None,
    budget: int = 5000,
    timeout: int | float = 1800,
    store_path: str | Path | None = None,
    seed: int = 42,
    llm_provider=None,
    llm_model: str | None = None,
    max_rounds: int = 0,
    batch_size: int = 200,
) -> CobolCoverageReport:
    """Run coverage-guided test generation using Python execution only.

    No GnuCOBOL required — executes the generated Python module directly.
    If *cobol_source* is provided, LLM strategies can read the COBOL source
    to extract paragraph comments and generate business-scenario-aware inputs.
    """
    from .ast_parser import parse_ast
    from .code_generator import generate_code
    from .monte_carlo import _load_module

    start_time = time.time()
    rng = random.Random(seed)
    copybook_dirs = list(copybook_dirs or [])

    # --- PARSE + CODEGEN ---
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
    copybook_records = load_copybooks(copybook_dirs) if copybook_dirs else []
    domains = build_variable_domains(var_report, copybook_records, stub_mapping)
    log.info("Domain model: %d variables", len(domains))

    # Generate + load instrumented Python module
    import tempfile
    code = generate_code(program, var_report, instrument=True,
                         copybook_records=copybook_records)
    tmpdir = Path(tempfile.mkdtemp(prefix="specter_cov_"))
    py_path = tmpdir / f"{program.program_id}.py"
    py_path.write_text(code)
    module = _load_module(py_path)

    # Branch metadata (from generated module)
    raw_branch_meta = getattr(module, "_BRANCH_META", {})

    # Compute totals
    all_paras = {p.name for p in program.paragraphs}
    total_paragraphs = len(all_paras)
    total_branches = len(raw_branch_meta) * 2  # each branch: T + F

    # Setup store
    if store_path is None:
        store_path = tmpdir / f"{program.program_id}_testset.jsonl"
    store_path = Path(store_path)

    # Load existing coverage
    existing_tcs, existing_paras, existing_branches = load_existing_coverage(store_path)

    # Expand stub mapping with 88-level siblings
    siblings_88 = _build_siblings_88(copybook_records)
    flag_88_added = _expand_stub_mapping(stub_mapping, siblings_88)
    if flag_88_added:
        log.info("Expanded stub mapping with %d 88-level siblings: %s",
                 len(flag_88_added), sorted(flag_88_added))

    # Build success stubs
    success_stubs, success_defaults = _build_success_stubs(
        stub_mapping, domains,
        flag_88_added=flag_88_added, siblings_88=siblings_88,
    )

    existing_ast_paras = existing_paras & all_paras
    existing_runtime_only = existing_paras - all_paras

    # Coverage state
    cov = CoverageState(
        paragraphs_hit=existing_ast_paras,
        runtime_only_paragraphs=existing_runtime_only,
        branches_hit=existing_branches,
        total_paragraphs=total_paragraphs,
        total_branches=total_branches,
        test_cases=existing_tcs,
        all_paragraphs=all_paras,
        _stub_mapping=stub_mapping,
    )
    report = CobolCoverageReport(
        total_test_cases=len(existing_tcs),
        paragraphs_total=total_paragraphs,
        runtime_trace_total=total_paragraphs,
        runtime_only_paragraphs=len(existing_runtime_only),
        branches_total=total_branches,
    )

    if existing_tcs:
        log.info("Loaded %d existing TCs: %d AST paras, %d runtime-only paras, %d branches covered",
                 len(existing_tcs), len(existing_ast_paras), len(existing_runtime_only),
                 len(existing_branches))

    tc_count = len(existing_tcs)

    # --- UPFRONT ANALYSIS (static, no LLM) ---
    from .program_analysis import (
        generate_seeds_from_analysis,
        prepare_program_analysis,
    )

    cobol_source_path = Path(cobol_source) if cobol_source else None
    if cobol_source_path and not cobol_source_path.exists():
        log.warning("COBOL source not found: %s", cobol_source_path)
        cobol_source_path = None

    analysis = prepare_program_analysis(
        program, var_report, domains, call_graph, gating_conds,
        stub_mapping, cobol_source=cobol_source_path,
        branch_meta=raw_branch_meta,
    )

    # Save analysis JSON alongside the test store
    analysis_path = store_path.with_suffix(".analysis.json")
    analysis_path.write_text(analysis.to_json())
    log.info("Analysis saved: %s", analysis_path)

    # --- LLM SEED GENERATION (one-time, from analysis JSON) ---
    llm_seeds: list[dict] = []
    if llm_provider:
        seed_cache = store_path.with_name(store_path.stem + "_seeds.json")
        llm_seeds = generate_seeds_from_analysis(
            analysis, llm_provider, llm_model,
            cache_path=seed_cache,
        )
        log.info("LLM seeds: %d initial test states", len(llm_seeds))

    # --- BUILD STRATEGY CONTEXT ---
    ctx = StrategyContext(
        module=module,
        context=None,  # Python-only mode
        domains=domains,
        stub_mapping=stub_mapping,
        call_graph=call_graph,
        gating_conds=gating_conds,
        var_report=var_report,
        program=program,
        all_paragraphs=all_paras,
        success_stubs=success_stubs,
        success_defaults=success_defaults,
        rng=rng,
        store_path=store_path,
        branch_meta=raw_branch_meta,
        cobol_source_path=cobol_source_path,
        llm_provider=llm_provider,
        llm_model=llm_model,
        siblings_88=siblings_88,
        flag_88_added=flag_88_added,
    )

    # --- REGISTER STRATEGIES ---
    strategies: list[Strategy] = [
        BaselineStrategy(),
        ConstraintSolverStrategy(),
        DirectParagraphStrategy(),
        BranchSolverStrategy(),
        FaultInjectionStrategy(),
        StubWalkStrategy(),
        GuidedMutationStrategy(),
        MonteCarloStrategy(),
    ]

    # Inject LLM seeds as a one-shot strategy (no per-round LLM calls)
    if llm_seeds:
        strategies.insert(0, _LLMSeedInjector(llm_seeds, stub_mapping))

    # LLM selector for per-round strategy steering (optional)
    if llm_provider:
        strategies.extend([
            LLMGapStrategy(llm_provider, llm_model),
        ])

    selector = (
        LLMSelector(llm_provider, llm_model,
                     default_batch_size=batch_size,
                     var_report=var_report)
        if llm_provider
        else HeuristicSelector(default_batch_size=batch_size)
    )

    return _run_agentic_loop(
        ctx, cov, report, strategies, selector,
        budget, timeout, start_time, tc_count,
        max_rounds=max_rounds,
    )
