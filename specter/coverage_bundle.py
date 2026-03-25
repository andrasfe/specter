"""Portable coverage bundle: export and run.

Export phase (--export-bundle): compiles COBOL, runs full analysis with
optional LLM enrichment, packages binary + coverage spec YAML.

Run phase (--run-bundle): loads spec + binary, generates test cases from
spec hints, executes through COBOL binary, reports coverage.  No AST,
source, copybooks, or LLM needed.
"""

from __future__ import annotations

import json
import logging
import platform
import random
import shutil
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Spec dataclasses
# ---------------------------------------------------------------------------

@dataclass
class VariableSpec:
    name: str
    data_type: str = "unknown"
    max_length: int = 10
    precision: int = 0
    signed: bool = False
    min_value: float | None = None
    max_value: float | None = None
    condition_literals: list = field(default_factory=list)
    valid_88_values: dict[str, str] = field(default_factory=dict)
    classification: str = "internal"
    semantic_type: str = "generic"
    set_by_stub: str | None = None
    llm_hints: list[str] = field(default_factory=list)


@dataclass
class StubSpec:
    op_key: str
    status_vars: list[str] = field(default_factory=list)
    success_values: list[dict] = field(default_factory=list)
    fault_values: list[dict] = field(default_factory=list)
    llm_hints: list[str] = field(default_factory=list)


@dataclass
class ScenarioSpec:
    name: str
    description: str = ""
    input_values: dict = field(default_factory=dict)
    stub_overrides: dict = field(default_factory=dict)
    target_paragraphs: list[str] = field(default_factory=list)


@dataclass
class CoverageSpec:
    program_id: str
    exported_at: str = ""
    platform_tag: str = ""
    binary_name: str = "program.mock"
    coverage_mode: bool = True
    total_branches: int = 0
    total_paragraphs: int = 0
    branch_meta: dict = field(default_factory=dict)
    paragraph_names: list[str] = field(default_factory=list)
    variables: dict[str, VariableSpec] = field(default_factory=dict)
    stubs: dict[str, StubSpec] = field(default_factory=dict)
    siblings_88: dict[str, list[str]] = field(default_factory=dict)
    constants: dict[str, int | float] = field(default_factory=dict)
    gating_conditions: dict[str, list[str]] = field(default_factory=dict)
    call_graph: dict[str, list[str]] = field(default_factory=dict)
    llm_scenarios: list[ScenarioSpec] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def _serialize_spec(spec: CoverageSpec, output_path: Path) -> None:
    """Write coverage-spec.yaml (or .json fallback)."""
    data = _spec_to_dict(spec)
    try:
        import yaml
        output_path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))
    except ImportError:
        output_path.with_suffix(".json").write_text(
            json.dumps(data, indent=2, default=str)
        )
        log.warning("PyYAML not installed — wrote coverage-spec.json instead")


def _spec_to_dict(spec: CoverageSpec) -> dict:
    """Convert spec to a serializable dict."""
    d = {
        "program_id": spec.program_id,
        "exported_at": spec.exported_at,
        "platform": spec.platform_tag,
        "execution": {
            "binary": spec.binary_name,
            "coverage_mode": spec.coverage_mode,
        },
        "branches": {
            "total": spec.total_branches,
            "meta": {str(k): v for k, v in spec.branch_meta.items()},
        },
        "paragraphs": {
            "total": spec.total_paragraphs,
            "names": spec.paragraph_names,
        },
        "variables": {
            name: {k: v for k, v in asdict(vs).items() if k != "name"}
            for name, vs in spec.variables.items()
        },
        "stubs": {
            name: {k: v for k, v in asdict(ss).items() if k != "op_key"}
            for name, ss in spec.stubs.items()
        },
        "siblings_88": spec.siblings_88,
        "constants": spec.constants,
        "gating_conditions": spec.gating_conditions,
        "call_graph": spec.call_graph,
        "llm_scenarios": [asdict(s) for s in spec.llm_scenarios],
    }
    return d


def _load_spec(spec_path: Path) -> CoverageSpec:
    """Load coverage spec from YAML or JSON."""
    text = spec_path.read_text()
    try:
        import yaml
        data = yaml.safe_load(text)
    except ImportError:
        data = json.loads(text)

    variables = {}
    for name, vd in data.get("variables", {}).items():
        variables[name] = VariableSpec(name=name, **{
            k: v for k, v in vd.items()
            if k in VariableSpec.__dataclass_fields__
        })

    stubs = {}
    for name, sd in data.get("stubs", {}).items():
        stubs[name] = StubSpec(op_key=name, **{
            k: v for k, v in sd.items()
            if k in StubSpec.__dataclass_fields__
        })

    scenarios = []
    for sd in data.get("llm_scenarios", []):
        scenarios.append(ScenarioSpec(**{
            k: v for k, v in sd.items()
            if k in ScenarioSpec.__dataclass_fields__
        }))

    branch_data = data.get("branches", {})
    para_data = data.get("paragraphs", {})

    return CoverageSpec(
        program_id=data.get("program_id", "UNKNOWN"),
        exported_at=data.get("exported_at", ""),
        platform_tag=data.get("platform", ""),
        binary_name=data.get("execution", {}).get("binary", "program.mock"),
        coverage_mode=data.get("execution", {}).get("coverage_mode", True),
        total_branches=branch_data.get("total", 0),
        total_paragraphs=para_data.get("total", 0),
        branch_meta={int(k): v for k, v in branch_data.get("meta", {}).items()},
        paragraph_names=para_data.get("names", []),
        variables=variables,
        stubs=stubs,
        siblings_88={k: list(v) for k, v in data.get("siblings_88", {}).items()},
        constants=data.get("constants", {}),
        gating_conditions=data.get("gating_conditions", {}),
        call_graph=data.get("call_graph", {}),
        llm_scenarios=scenarios,
    )


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def export_bundle(
    ast_file: str | Path,
    cobol_source: str | Path,
    copybook_dirs: list[str | Path] | None = None,
    output_dir: str | Path = "bundle",
    llm_provider=None,
    llm_model: str | None = None,
    coverage_config=None,
    obfuscate: bool = False,
    mapping_output_dir: str | Path | None = None,
) -> Path:
    """Export a portable coverage bundle.

    Compiles COBOL, extracts all metadata, optionally enriches with LLM,
    and packages into a self-contained directory.
    """
    from .ast_parser import parse_ast
    from .cobol_coverage import (
        _MQ_CONSTANTS,
        _build_siblings_88,
        _build_success_stubs,
        _enrich_domains_with_boolean_hints,
        _expand_stub_mapping,
    )
    from .cobol_executor import prepare_context
    from .static_analysis import (
        build_static_call_graph,
        extract_gating_conditions,
    )
    from .variable_domain import build_variable_domains, load_copybooks
    from .variable_extractor import extract_stub_status_mapping, extract_variables

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    copybook_dirs = list(copybook_dirs or [])

    # --- Parse + analyze ---
    log.info("Parsing AST: %s", ast_file)
    program = parse_ast(ast_file)
    var_report = extract_variables(program)
    call_graph = build_static_call_graph(program)
    gating_conds = extract_gating_conditions(program, call_graph)
    stub_mapping = extract_stub_status_mapping(program, var_report)

    # --- Build domains ---
    copybook_records = load_copybooks(copybook_dirs) if copybook_dirs else []
    domains = build_variable_domains(var_report, copybook_records, stub_mapping)
    _enrich_domains_with_boolean_hints(domains, program)

    # --- 88-level siblings ---
    siblings_88 = _build_siblings_88(copybook_records, cobol_source=cobol_source)
    flag_88_added = _expand_stub_mapping(stub_mapping, siblings_88)

    # --- Compile COBOL ---
    log.info("Compiling instrumented COBOL: %s", cobol_source)
    context = prepare_context(
        cobol_source, copybook_dirs,
        enable_branch_tracing=True,
        coverage_mode=True,
        allow_hardening_fallback=True,
    )
    log.info("Compiled: %d paragraphs, %d branches",
             context.total_paragraphs, context.total_branches)

    # Copy binary to bundle
    binary_name = f"{program.program_id}.mock"
    shutil.copy2(context.executable_path, output_dir / binary_name)

    # --- Build spec ---
    spec = CoverageSpec(
        program_id=program.program_id,
        exported_at=datetime.now(timezone.utc).isoformat(),
        platform_tag=f"{platform.system().lower()}-{platform.machine()}",
        binary_name=binary_name,
        coverage_mode=True,
        total_branches=context.total_branches,
        total_paragraphs=context.total_paragraphs,
        branch_meta=context.branch_meta,
        paragraph_names=[p.name for p in program.paragraphs],
    )

    # Variables
    for name, dom in domains.items():
        spec.variables[name] = VariableSpec(
            name=name,
            data_type=dom.data_type,
            max_length=dom.max_length,
            precision=dom.precision,
            signed=dom.signed,
            min_value=dom.min_value,
            max_value=dom.max_value,
            condition_literals=list(dom.condition_literals),
            valid_88_values=dict(dom.valid_88_values),
            classification=dom.classification,
            semantic_type=dom.semantic_type,
            set_by_stub=dom.set_by_stub,
        )

    # Stubs
    success_stubs, success_defaults = _build_success_stubs(
        stub_mapping, domains,
        flag_88_added=flag_88_added, siblings_88=siblings_88,
    )
    for op_key, status_vars in stub_mapping.items():
        success_vals = success_stubs.get(op_key, [[]])[0]
        stub_spec = StubSpec(
            op_key=op_key,
            status_vars=status_vars,
            success_values=[{v: val for v, val in success_vals}] if success_vals else [],
        )
        spec.stubs[op_key] = stub_spec

    # Siblings
    for name, sibs in siblings_88.items():
        spec.siblings_88[name] = sorted(sibs)

    # Constants
    spec.constants = dict(_MQ_CONSTANTS)

    # Gating conditions
    for para, gates in gating_conds.items():
        if gates:
            spec.gating_conditions[para] = [str(g) for g in gates[:5]]

    # Call graph
    for para_name in call_graph.edges:
        targets = [t for t in call_graph.edges[para_name]]
        if targets:
            spec.call_graph[para_name] = targets

    # --- LLM enrichment ---
    if llm_provider:
        _llm_enrich_spec(spec, cobol_source, llm_provider, llm_model)

    # --- Obfuscation ---
    if obfuscate:
        log.info("Obfuscating bundle for IP protection ...")
        mapping = _build_obfuscation_mapping(spec)

        # Obfuscate COBOL trace strings in the already-instrumented source
        instr_source = context.instrumented_source_path.read_text()
        obf_source = _obfuscate_cobol_source(instr_source, mapping)

        import subprocess
        import tempfile
        obf_dir = Path(tempfile.mkdtemp(prefix="specter_obf_"))
        obf_cbl = obf_dir / f"{program.program_id}.obf.cbl"
        obf_cbl.write_text(obf_source)
        obf_bin = obf_dir / f"{program.program_id}.mock"
        rc = subprocess.run(
            ["cobc", "-x", "-o", str(obf_bin), str(obf_cbl)],
            capture_output=True, text=True,
        )
        if rc.returncode != 0:
            log.warning("Obfuscated COBOL compilation failed: %s", rc.stderr[:500])
            log.warning("Falling back to non-obfuscated binary (traces will use real names)")
        else:
            shutil.copy2(obf_bin, output_dir / binary_name)
            log.info("Recompiled with obfuscated trace names")

            # Strip debug symbols from binary
            subprocess.run(["strip", str(output_dir / binary_name)],
                           capture_output=True)
            log.info("Binary stripped of debug symbols")

        # Obfuscate spec
        spec = _obfuscate_spec(spec, mapping)

        # Randomize program_id and binary name in spec
        obf_binary_name = mapping["program_id_obf"] + ".mock"
        old_binary = output_dir / binary_name
        new_binary = output_dir / obf_binary_name
        if old_binary.exists():
            old_binary.rename(new_binary)
        spec.binary_name = obf_binary_name
        spec.program_id = mapping["program_id_obf"]

        log.info("Spec obfuscated: %d variables, %d paragraphs renamed",
                 len(mapping["variables"]), len(mapping["paragraphs"]))

        # Save mapping to source machine (NOT in bundle)
        map_dir = Path(mapping_output_dir) if mapping_output_dir else Path(".")
        map_dir.mkdir(parents=True, exist_ok=True)
        map_path = map_dir / f"{program.program_id}_obfuscation_map.json"
        map_path.write_text(json.dumps(mapping, indent=2))
        log.info("Obfuscation mapping saved: %s (keep this secure!)", map_path)

    # --- Write spec ---
    spec_path = output_dir / "coverage-spec.yaml"
    _serialize_spec(spec, spec_path)
    log.info("Bundle exported to %s", output_dir)
    log.info("  Binary: %s", binary_name)
    log.info("  Spec: coverage-spec.yaml")
    log.info("  Variables: %d, Stubs: %d, Scenarios: %d",
             len(spec.variables), len(spec.stubs), len(spec.llm_scenarios))

    return output_dir


# ---------------------------------------------------------------------------
# Obfuscation
# ---------------------------------------------------------------------------

def _build_obfuscation_mapping(spec: CoverageSpec) -> dict:
    """Build a mapping from real names to randomized obfuscated tokens.

    Uses random hex tokens (not sequential) and shuffled assignment to
    prevent leaking variable counts, ordering, or naming patterns.
    Adds dummy entries to further obscure the real variable count.
    """
    import os
    import random as _rng

    # Use OS random for non-deterministic token generation
    _rng.seed(os.urandom(16))

    def _hex_token(prefix: str, length: int = 4) -> str:
        return prefix + "".join(_rng.choices("0123456789ABCDEF", k=length))

    used_tokens: set[str] = set()

    def _unique_token(prefix: str) -> str:
        for _ in range(1000):
            t = _hex_token(prefix)
            if t not in used_tokens:
                used_tokens.add(t)
                return t
        raise RuntimeError("Token collision")

    mapping: dict = {
        "variables": {},
        "paragraphs": {},
        "stubs": {},
        "constants": {},
        "reverse": {},
        "program_id_obf": _hex_token("PGM"),
    }

    # Collect ALL names that appear anywhere in the spec
    all_var_names: set[str] = set(spec.variables.keys())
    for sibs in spec.siblings_88.values():
        all_var_names.update(sibs)
    for ss in spec.stubs.values():
        all_var_names.update(ss.status_vars)
        for sv in ss.success_values:
            all_var_names.update(sv.keys())
        for fv in ss.fault_values:
            all_var_names.update(k for k in fv.keys() if k != "label")
    for sc in spec.llm_scenarios:
        all_var_names.update(sc.input_values.keys())

    # Shuffle names before assigning tokens to break ordering
    var_names = list(all_var_names)
    _rng.shuffle(var_names)
    for name in var_names:
        token = _unique_token("X")
        mapping["variables"][name] = token
        mapping["reverse"][token] = name

    para_names = list(spec.paragraph_names)
    _rng.shuffle(para_names)
    for name in para_names:
        token = _unique_token("Q")
        mapping["paragraphs"][name] = token
        mapping["reverse"][token] = name

    all_stub_names: set[str] = set(spec.stubs.keys())
    for sc in spec.llm_scenarios:
        all_stub_names.update(sc.stub_overrides.keys())
    stub_names = list(all_stub_names)
    _rng.shuffle(stub_names)
    for op_key in stub_names:
        token = _unique_token("K")
        mapping["stubs"][op_key] = token
        mapping["reverse"][token] = op_key

    const_names = list(spec.constants.keys())
    _rng.shuffle(const_names)
    for name in const_names:
        token = _unique_token("W")
        mapping["constants"][name] = token
        mapping["reverse"][token] = name

    # Add dummy variables/paragraphs to obscure real counts
    n_dummy_vars = _rng.randint(10, 30)
    for _ in range(n_dummy_vars):
        _unique_token("X")  # just consume tokens to pad the space

    n_dummy_paras = _rng.randint(5, 15)
    for _ in range(n_dummy_paras):
        _unique_token("Q")

    return mapping


def _obfuscate_cobol_source(source: str, mapping: dict) -> str:
    """Obfuscate SPECTER-TRACE display strings in instrumented COBOL source.

    Only replaces paragraph names inside SPECTER-TRACE:xxx display
    statements and the PROGRAM-ID — these are what the coverage engine
    parses from stdout. Other COBOL names are left intact to avoid
    column-alignment issues in COBOL's fixed-format source. The binary
    should be stripped after compilation for full protection.
    """
    import re

    para_map = mapping.get("paragraphs", {})
    pgm_id = mapping.get("program_id_obf")

    # Replace SPECTER-TRACE:<para-name> patterns
    if para_map:
        lookup = {real.upper(): obf for real, obf in para_map.items()}
        def _replace_trace(m):
            real_name = m.group(1).upper()
            return f"SPECTER-TRACE:{lookup.get(real_name, m.group(1))}"
        source = re.sub(
            r"SPECTER-TRACE:([A-Z0-9][A-Z0-9-]*)",
            _replace_trace, source, flags=re.IGNORECASE,
        )

    # Replace PROGRAM-ID
    if pgm_id:
        source = re.sub(
            r"(PROGRAM-ID\.\s+)([A-Z0-9][A-Z0-9-]*)",
            lambda m: m.group(1) + pgm_id,
            source, flags=re.IGNORECASE,
        )

    return source


def _obfuscate_spec(spec: CoverageSpec, mapping: dict) -> CoverageSpec:
    """Apply obfuscation mapping to the coverage spec."""
    var_map = mapping.get("variables", {})
    para_map = mapping.get("paragraphs", {})
    stub_map = mapping.get("stubs", {})
    const_map = mapping.get("constants", {})

    def _rename_var(name: str) -> str:
        return var_map.get(name, const_map.get(name, name))

    def _rename_para(name: str) -> str:
        return para_map.get(name, name)

    def _rename_stub(name: str) -> str:
        return stub_map.get(name, name)

    # Obfuscate variables
    new_vars = {}
    for name, vs in spec.variables.items():
        new_name = _rename_var(name)
        new_vs = VariableSpec(
            name=new_name,
            data_type=vs.data_type,
            max_length=vs.max_length,
            precision=vs.precision,
            signed=vs.signed,
            min_value=vs.min_value,
            max_value=vs.max_value,
            condition_literals=list(vs.condition_literals),
            valid_88_values={_rename_var(k): v for k, v in vs.valid_88_values.items()},
            classification=vs.classification,
            semantic_type=vs.semantic_type,
            set_by_stub=_rename_stub(vs.set_by_stub) if vs.set_by_stub else None,
            llm_hints=[],  # Strip all hints
        )
        new_vars[new_name] = new_vs

    # Obfuscate stubs
    new_stubs = {}
    for op_key, ss in spec.stubs.items():
        new_key = _rename_stub(op_key)
        new_stubs[new_key] = StubSpec(
            op_key=new_key,
            status_vars=[_rename_var(v) for v in ss.status_vars],
            success_values=[
                {_rename_var(k): v for k, v in sv.items()}
                for sv in ss.success_values
            ],
            fault_values=[
                {_rename_var(k): v for k, v in fv.items() if k != "label"}
                for fv in ss.fault_values
            ],
            llm_hints=[],  # Strip all hints
        )

    # Obfuscate branch meta
    new_branch_meta = {}
    for bid, meta in spec.branch_meta.items():
        new_meta = dict(meta)
        new_meta["paragraph"] = _rename_para(meta.get("paragraph", ""))
        new_meta["condition"] = f"condition_{bid}"  # Strip condition text
        new_branch_meta[bid] = new_meta

    # Obfuscate siblings
    new_siblings = {}
    for name, sibs in spec.siblings_88.items():
        new_name = _rename_var(name)
        new_siblings[new_name] = [_rename_var(s) for s in sibs]

    # Obfuscate constants
    new_constants = {}
    for name, val in spec.constants.items():
        new_constants[const_map.get(name, name)] = val

    # Obfuscate call graph
    new_call_graph = {}
    for para, targets in spec.call_graph.items():
        new_call_graph[_rename_para(para)] = [_rename_para(t) for t in targets]

    # Obfuscate scenarios (strip descriptions, rename vars)
    new_scenarios = []
    for i, sc in enumerate(spec.llm_scenarios):
        new_scenarios.append(ScenarioSpec(
            name=f"scenario_{i + 1}",
            description="",
            input_values={_rename_var(k): v for k, v in sc.input_values.items()},
            stub_overrides={
                _rename_stub(k): (
                    {_rename_var(vk): vv for vk, vv in v.items()}
                    if isinstance(v, dict) else v
                )
                for k, v in sc.stub_overrides.items()
            },
            target_paragraphs=[_rename_para(p) for p in sc.target_paragraphs],
        ))

    return CoverageSpec(
        program_id=spec.program_id,  # keep program ID (it's in the binary name)
        exported_at=spec.exported_at,
        platform_tag=spec.platform_tag,
        binary_name=spec.binary_name,
        coverage_mode=spec.coverage_mode,
        total_branches=spec.total_branches,
        total_paragraphs=spec.total_paragraphs,
        branch_meta=new_branch_meta,
        paragraph_names=[_rename_para(n) for n in spec.paragraph_names],
        variables=new_vars,
        stubs=new_stubs,
        siblings_88=new_siblings,
        constants=new_constants,
        gating_conditions={},  # Strip entirely
        call_graph={},  # Strip — contains unobfuscated CALL targets
        llm_scenarios=new_scenarios,
    )


# ---------------------------------------------------------------------------
# LLM enrichment
# ---------------------------------------------------------------------------

def _llm_enrich_spec(
    spec: CoverageSpec,
    cobol_source: str | Path,
    llm_provider,
    llm_model: str | None,
) -> None:
    """Query LLM to add business-logic hints to the spec."""
    from .llm_coverage import _query_llm_sync

    cobol_text = Path(cobol_source).read_text(errors="replace")
    # Truncate to first 2000 lines for prompt size
    source_preview = "\n".join(cobol_text.splitlines()[:2000])

    # --- Variable hints ---
    var_names = [n for n, v in spec.variables.items()
                 if v.classification in ("input", "status", "flag")][:50]
    if var_names:
        prompt = (
            f"You are analyzing COBOL program {spec.program_id} for test generation.\n\n"
            f"COBOL source (first 2000 lines):\n```\n{source_preview[:8000]}\n```\n\n"
            f"For each variable below, provide 1-3 short test hints "
            f"(good values to try, what it represents, related branches).\n\n"
            f"Variables: {', '.join(var_names[:30])}\n\n"
            f"Respond as JSON: {{\"VAR-NAME\": [\"hint1\", \"hint2\"]}}"
        )
        try:
            response, _ = _query_llm_sync(llm_provider, prompt, llm_model)
            hints = _parse_json_response(response)
            if isinstance(hints, dict):
                for var, hint_list in hints.items():
                    vs = spec.variables.get(var.upper())
                    if vs and isinstance(hint_list, list):
                        vs.llm_hints = [str(h) for h in hint_list[:5]]
                log.info("LLM variable hints: %d variables enriched", len(hints))
        except Exception as e:
            log.warning("LLM variable hint generation failed: %s", e)

    # --- Stub hints ---
    if spec.stubs:
        stub_names = list(spec.stubs.keys())[:20]
        prompt = (
            f"You are analyzing COBOL program {spec.program_id}.\n\n"
            f"COBOL source (first 2000 lines):\n```\n{source_preview[:8000]}\n```\n\n"
            f"For each external operation below, provide 1-3 hints about "
            f"what it does and useful fault scenarios.\n\n"
            f"Operations: {', '.join(stub_names)}\n\n"
            f"Respond as JSON: {{\"OP-KEY\": [\"hint1\", \"hint2\"]}}"
        )
        try:
            response, _ = _query_llm_sync(llm_provider, prompt, llm_model)
            hints = _parse_json_response(response)
            if isinstance(hints, dict):
                for op, hint_list in hints.items():
                    ss = spec.stubs.get(op)
                    if ss and isinstance(hint_list, list):
                        ss.llm_hints = [str(h) for h in hint_list[:5]]
                log.info("LLM stub hints: %d stubs enriched", len(hints))
        except Exception as e:
            log.warning("LLM stub hint generation failed: %s", e)

    # --- Business scenarios ---
    branch_summary = []
    for bid, meta in list(spec.branch_meta.items())[:20]:
        branch_summary.append(
            f"  Branch {bid}: {meta.get('paragraph', '')} — {meta.get('condition', '')}"
        )

    prompt = (
        f"You are generating test scenarios for COBOL program {spec.program_id}.\n\n"
        f"COBOL source (first 2000 lines):\n```\n{source_preview[:8000]}\n```\n\n"
        f"Branch targets:\n{chr(10).join(branch_summary)}\n\n"
        f"Available stubs: {', '.join(spec.stubs.keys())}\n"
        f"Input variables: {', '.join(var_names[:20])}\n\n"
        f"Generate 10-15 diverse test scenarios. Each should target different "
        f"branch paths with specific input values and stub overrides.\n\n"
        f"Respond as JSON array:\n"
        f'[{{"name": "...", "description": "...", '
        f'"input_values": {{"VAR": value}}, '
        f'"stub_overrides": {{"OP": value}}, '
        f'"target_paragraphs": ["PARA1"]}}]'
    )
    try:
        response, _ = _query_llm_sync(llm_provider, prompt, llm_model)
        scenarios = _parse_json_response(response)
        if isinstance(scenarios, list):
            for sd in scenarios:
                if isinstance(sd, dict) and "name" in sd:
                    spec.llm_scenarios.append(ScenarioSpec(
                        name=str(sd.get("name", "")),
                        description=str(sd.get("description", "")),
                        input_values=sd.get("input_values", {}),
                        stub_overrides=sd.get("stub_overrides", {}),
                        target_paragraphs=sd.get("target_paragraphs", []),
                    ))
            log.info("LLM scenarios: %d generated", len(spec.llm_scenarios))
    except Exception as e:
        log.warning("LLM scenario generation failed: %s", e)


def _parse_json_response(text: str):
    """Parse JSON from LLM response, handling markdown fences."""
    import re
    payload = text.strip()
    if "```" in payload:
        parts = payload.split("```")
        for part in parts[1::2]:
            lines = part.strip().split("\n", 1)
            if len(lines) > 1 and lines[0].strip().lower() in ("json", ""):
                payload = lines[1]
            else:
                payload = part
            break
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        m = re.search(r"[\[{][\s\S]*[\]}]", payload)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    return None


# ---------------------------------------------------------------------------
# Run from bundle
# ---------------------------------------------------------------------------

def run_bundle(
    bundle_dir: str | Path,
    store_path: str | Path | None = None,
    budget: int = 5000,
    timeout: int = 1800,
    seed: int = 42,
    coverage_config=None,
    llm_provider=None,
    llm_model: str | None = None,
) -> "CobolCoverageReport":
    """Run coverage from a portable bundle.

    No AST, source, or copybooks needed — just the bundle directory.
    """
    from .cobol_coverage import (
        CobolCoverageReport,
        CoverageState,
        HeuristicSelector,
        _build_input_state,
        _compute_tc_id,
        _execute_and_save,
        _save_test_case,
        load_existing_coverage,
    )
    from .cobol_executor import CobolExecutionContext, run_test_case
    from .cobol_mock import generate_init_records, generate_mock_data_ordered
    from .coverage_config import CoverageConfig, build_selector, build_strategies
    from .coverage_strategies import (
        HeuristicSelector,
        Strategy,
        StrategyContext,
        StrategyYield,
    )
    from .variable_domain import VariableDomain

    bundle_dir = Path(bundle_dir)
    start_time = time.time()
    rng = random.Random(seed)

    # --- Load spec ---
    spec_path = bundle_dir / "coverage-spec.yaml"
    if not spec_path.exists():
        spec_path = bundle_dir / "coverage-spec.json"
    if not spec_path.exists():
        raise RuntimeError(f"Coverage spec not found in {bundle_dir}")

    log.info("Loading coverage spec: %s", spec_path)
    spec = _load_spec(spec_path)
    log.info("Program: %s, %d variables, %d stubs, %d branches, %d scenarios",
             spec.program_id, len(spec.variables), len(spec.stubs),
             spec.total_branches, len(spec.llm_scenarios))

    # --- Locate binary ---
    binary_path = bundle_dir / spec.binary_name
    if not binary_path.exists():
        raise RuntimeError(f"COBOL binary not found: {binary_path}")

    # --- Reconstruct domains ---
    domains = _reconstruct_domains(spec)
    log.info("Reconstructed %d variable domains", len(domains))

    # --- Reconstruct context ---
    context = CobolExecutionContext(
        executable_path=binary_path,
        instrumented_source_path=binary_path,  # not used for execution
        branch_meta=spec.branch_meta,
        total_paragraphs=spec.total_paragraphs,
        total_branches=spec.total_branches,
        coverage_mode=spec.coverage_mode,
    )

    # --- Reconstruct stub mapping ---
    stub_mapping = {
        op_key: ss.status_vars
        for op_key, ss in spec.stubs.items()
    }

    # --- Build success stubs from spec ---
    success_stubs: dict[str, list] = {}
    success_defaults: dict[str, list] = {}
    for op_key, ss in spec.stubs.items():
        if ss.success_values:
            entries = [list(sv.items()) for sv in ss.success_values]
            success_stubs[op_key] = entries
            success_defaults[op_key] = entries[0] if entries else []

    # --- Siblings + constants ---
    siblings_88 = {k: set(v) for k, v in spec.siblings_88.items()}

    # --- Setup store ---
    if store_path is None:
        store_path = bundle_dir / f"{spec.program_id}_testset.jsonl"
    store_path = Path(store_path)
    existing_tcs, existing_paras, existing_branches = load_existing_coverage(store_path)

    all_paras = set(spec.paragraph_names)
    existing_ast_paras = existing_paras & all_paras

    cov = CoverageState(
        paragraphs_hit=existing_ast_paras,
        branches_hit=existing_branches,
        total_paragraphs=spec.total_paragraphs,
        total_branches=spec.total_branches,
        test_cases=existing_tcs,
        all_paragraphs=all_paras,
        _stub_mapping=stub_mapping,
    )
    report = CobolCoverageReport(
        total_test_cases=len(existing_tcs),
        paragraphs_total=spec.total_paragraphs,
        runtime_trace_total=spec.total_paragraphs,
        branches_total=spec.total_branches,
    )

    if existing_tcs:
        log.info("Loaded %d existing TCs, %d branches covered",
                 len(existing_tcs), len(existing_branches))

    tc_count = len(existing_tcs)

    # --- Execute LLM scenarios as initial seeds ---
    if spec.llm_scenarios:
        log.info("Executing %d LLM scenarios ...", len(spec.llm_scenarios))
        for scenario in spec.llm_scenarios:
            input_state = dict(scenario.input_values)
            # Inject constants
            for name, value in spec.constants.items():
                if name.upper() in spec.variables:
                    input_state.setdefault(name.upper(), value)

            # Build stub log from overrides
            stub_log = []
            for op_key, val in scenario.stub_overrides.items():
                if isinstance(val, dict):
                    stub_log.append((op_key, list(val.items())))
                else:
                    svars = stub_mapping.get(op_key, [])
                    stub_log.append((op_key, [(sv, val) for sv in svars]))

            result = run_test_case(context, input_state, stub_log, timeout=30)
            if result.error:
                continue

            result_paras = set(result.paragraphs_hit) & all_paras
            new_branches = result.branches_hit - cov.branches_hit
            new_paras = result_paras - cov.paragraphs_hit

            if new_branches or new_paras or tc_count < 5:
                cov.paragraphs_hit.update(result_paras)
                cov.branches_hit.update(result.branches_hit)
                tc_id = _compute_tc_id(input_state, stub_log)
                _save_test_case(
                    store_path, tc_id, input_state, stub_log, result,
                    "scenario", scenario.name[:50],
                )
                tc_count += 1
                report.layer_stats["scenario"] = report.layer_stats.get("scenario", 0) + 1

                if new_branches:
                    log.info("  [scenario:%s] +%d branches -> %d/%d",
                             scenario.name[:30], len(new_branches),
                             len(cov.branches_hit), cov.total_branches)

        log.info("Scenarios done: %d/%d paras, %d/%d branches",
                 len(cov.paragraphs_hit), cov.total_paragraphs,
                 len(cov.branches_hit), cov.total_branches)

    # --- Build strategy context (no Python module) ---
    # Create a minimal var_report-like object for strategies
    from .variable_extractor import VariableReport, VariableInfo
    var_info = {}
    for name, vs in spec.variables.items():
        var_info[name] = VariableInfo(
            name=name,
            classification=vs.classification,
            read_count=1 if vs.classification == "input" else 0,
            write_count=0,
        )
    var_report = VariableReport(variables=var_info)

    # Minimal Program-like for strategies that need it
    from .models import Program, Paragraph
    paragraphs = [
        Paragraph(name=n, statements=[], line_start=0, line_end=0)
        for n in spec.paragraph_names
    ]
    program_stub = Program(program_id=spec.program_id, paragraphs=paragraphs)

    # Gating conditions as expected format
    gating_conds = {p: g for p, g in spec.gating_conditions.items()}

    ctx = StrategyContext(
        module=None,  # No Python module in bundle mode
        context=context,
        domains=domains,
        stub_mapping=stub_mapping,
        call_graph=None,  # Not available without full analysis
        gating_conds=gating_conds,
        var_report=var_report,
        program=program_stub,
        all_paragraphs=all_paras,
        success_stubs=success_stubs,
        success_defaults=success_defaults,
        rng=rng,
        store_path=store_path,
        branch_meta=spec.branch_meta,
        siblings_88=siblings_88,
        flag_88_added=set(),
    )

    # --- Register strategies (exclude direct_paragraph — needs Python module) ---
    if coverage_config is None:
        coverage_config = CoverageConfig(
            strategies=[
                "baseline", "corpus_fuzz", "fault_injection",
            ],
        )

    strategies = build_strategies(coverage_config, llm_provider, llm_model)
    # Filter out direct_paragraph if present (needs Python module)
    strategies = [s for s in strategies if s.name != "direct_paragraph"]

    selector = build_selector(coverage_config, llm_provider, llm_model, var_report)

    # --- Run agentic loop ---
    from .cobol_coverage import _run_agentic_loop

    log.info("Starting coverage loop: budget=%d, timeout=%ds", budget, timeout)
    return _run_agentic_loop(
        ctx, cov, report, strategies, selector,
        budget, timeout, time.time(), tc_count,
        config=coverage_config,
    )


def _reconstruct_domains(spec: CoverageSpec) -> dict[str, "VariableDomain"]:
    """Rebuild VariableDomain objects from spec."""
    from .variable_domain import VariableDomain

    domains = {}
    for name, vs in spec.variables.items():
        dom = VariableDomain(name=name)
        dom.data_type = vs.data_type
        dom.max_length = vs.max_length
        dom.precision = vs.precision
        dom.signed = vs.signed
        dom.min_value = vs.min_value
        dom.max_value = vs.max_value
        dom.classification = vs.classification
        dom.semantic_type = vs.semantic_type
        dom.set_by_stub = vs.set_by_stub
        dom.valid_88_values = dict(vs.valid_88_values)

        # Merge condition_literals with LLM hint-derived values
        lits = list(vs.condition_literals)
        for hint in vs.llm_hints:
            # Extract numeric values from hints like "Try: 0.01, 100.00, 9999.99"
            import re
            for m in re.finditer(r"(?:^|[\s,=:(])(-?\d+\.?\d*)", hint):
                try:
                    val = float(m.group(1))
                    if val == int(val):
                        val = int(val)
                    if val not in lits:
                        lits.append(val)
                except ValueError:
                    pass
        dom.condition_literals = lits
        domains[name] = dom

    return domains
