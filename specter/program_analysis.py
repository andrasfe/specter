"""Upfront static analysis of COBOL programs for coverage synthesis.

Builds a structured JSON per paragraph — comments, parameters, types,
ranges, stub operations, branch conditions — without any LLM calls.
This JSON is then used by the coverage engine and optionally by an LLM
to generate initial seeds.

The COBOL source is processed paragraph by paragraph to handle large files.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .llm_test_states import extract_paragraph_comments
from .models import Program
from .static_analysis import StaticCallGraph
from .variable_domain import VariableDomain
from .variable_extractor import VariableReport

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ParaAnalysis:
    """Per-paragraph analysis result."""

    name: str
    comments: list[str] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)
    stub_ops: list[str] = field(default_factory=list)
    gating_conditions: list[str] = field(default_factory=list)
    condition_vars: dict[str, list] = field(default_factory=dict)
    branch_count: int = 0


@dataclass
class StubOpAnalysis:
    """Per-stub-operation analysis."""

    op_key: str
    status_vars: list[str] = field(default_factory=list)
    known_values: list = field(default_factory=list)


@dataclass
class InputVarAnalysis:
    """Per-input-variable analysis."""

    name: str
    classification: str = "input"
    data_type: str = "unknown"
    pic: str = ""
    max_length: int = 0
    min_value: float | None = None
    max_value: float | None = None
    condition_literals: list = field(default_factory=list)
    valid_88_values: dict[str, str] = field(default_factory=dict)
    semantic_type: str = "generic"


@dataclass
class ProgramAnalysis:
    """Complete program analysis — the structured JSON."""

    program_id: str = ""
    paragraphs: dict[str, ParaAnalysis] = field(default_factory=dict)
    stub_operations: dict[str, StubOpAnalysis] = field(default_factory=dict)
    input_variables: dict[str, InputVarAnalysis] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)

    @classmethod
    def from_dict(cls, d: dict) -> ProgramAnalysis:
        pa = cls(program_id=d.get("program_id", ""))
        for name, pdata in d.get("paragraphs", {}).items():
            pa.paragraphs[name] = ParaAnalysis(**pdata)
        for key, sdata in d.get("stub_operations", {}).items():
            pa.stub_operations[key] = StubOpAnalysis(**sdata)
        for name, vdata in d.get("input_variables", {}).items():
            pa.input_variables[name] = InputVarAnalysis(**vdata)
        return pa

    @classmethod
    def load(cls, path: str | Path) -> ProgramAnalysis:
        return cls.from_dict(json.loads(Path(path).read_text()))


# ---------------------------------------------------------------------------
# Build analysis from AST + COBOL source + domain model
# ---------------------------------------------------------------------------

def prepare_program_analysis(
    program: Program,
    var_report: VariableReport,
    domains: dict[str, VariableDomain],
    call_graph: StaticCallGraph,
    gating_conds: dict[str, list],
    stub_mapping: dict[str, list[str]],
    cobol_source: str | Path | None = None,
    branch_meta: dict | None = None,
) -> ProgramAnalysis:
    """Build structured analysis from program artifacts.

    All static — no LLM calls.  Processes paragraphs individually so
    large COBOL sources are handled without loading everything at once.
    """
    analysis = ProgramAnalysis(program_id=program.program_id)

    # --- Extract paragraph comments from COBOL source ---
    comments: dict[str, list[str]] = {}
    if cobol_source:
        source_path = Path(cobol_source)
        if source_path.exists():
            source_lines = source_path.read_text(errors="replace").splitlines()
            comments = extract_paragraph_comments(program, source_lines)
            log.info("Extracted comments for %d paragraphs", len(comments))

    # --- Build reverse stub lookup: paragraph → op_keys ---
    para_stubs: dict[str, list[str]] = {}
    for para in program.paragraphs:
        for stmt in _walk_statements(para.statements):
            for op_key in stub_mapping:
                op_type = op_key.split(":")[0] if ":" in op_key else op_key
                if (stmt.type in ("EXEC_SQL", "EXEC_CICS", "EXEC_DLI", "CALL",
                                  "READ", "WRITE", "REWRITE", "OPEN", "CLOSE",
                                  "START", "DELETE")
                        or op_type.upper() in (stmt.type or "").upper()):
                    para_stubs.setdefault(para.name, [])
                    if op_key not in para_stubs[para.name]:
                        para_stubs[para.name].append(op_key)

    # --- Condition vars per paragraph from branch_meta ---
    para_cond_vars: dict[str, dict[str, list]] = {}
    if branch_meta:
        from .static_analysis import _parse_condition_variables
        for bid, meta in branch_meta.items():
            para_name = meta.get("paragraph", "")
            if not para_name:
                continue
            cond = meta.get("condition", "")
            if not cond:
                continue
            if para_name not in para_cond_vars:
                para_cond_vars[para_name] = {}
            try:
                parsed = _parse_condition_variables(cond)
                for var, vals, _ in parsed:
                    if var not in para_cond_vars[para_name]:
                        para_cond_vars[para_name][var] = []
                    for v in vals:
                        if v not in para_cond_vars[para_name][var]:
                            para_cond_vars[para_name][var].append(v)
            except Exception:
                pass

    # --- Branch count per paragraph ---
    para_branch_count: dict[str, int] = {}
    if branch_meta:
        for _bid, meta in branch_meta.items():
            p = meta.get("paragraph", "")
            if p:
                para_branch_count[p] = para_branch_count.get(p, 0) + 2  # T + F

    # --- Build per-paragraph analysis ---
    for para in program.paragraphs:
        pa = ParaAnalysis(name=para.name)
        pa.comments = comments.get(para.name, [])
        pa.calls = sorted(call_graph.edges.get(para.name, set()))
        pa.stub_ops = para_stubs.get(para.name, [])
        pa.branch_count = para_branch_count.get(para.name, 0)

        # Gating conditions
        gc_list = gating_conds.get(para.name, [])
        for gc in gc_list:
            if hasattr(gc, "text"):
                pa.gating_conditions.append(gc.text)
            elif hasattr(gc, "variable") and hasattr(gc, "values"):
                neg = "NOT " if getattr(gc, "negated", False) else ""
                pa.gating_conditions.append(
                    f"{gc.variable} {neg}= {gc.values}"
                )

        # Condition variables
        pa.condition_vars = para_cond_vars.get(para.name, {})

        analysis.paragraphs[para.name] = pa

    # --- Stub operations ---
    for op_key, status_vars in stub_mapping.items():
        soa = StubOpAnalysis(op_key=op_key, status_vars=list(status_vars))
        for var in status_vars:
            dom = domains.get(var)
            if dom:
                for lit in (dom.condition_literals or []):
                    if lit not in soa.known_values:
                        soa.known_values.append(lit)
                for v88 in (dom.valid_88_values or {}).values():
                    if v88 not in soa.known_values:
                        soa.known_values.append(v88)
        analysis.stub_operations[op_key] = soa

    # --- Input variables ---
    for name, dom in domains.items():
        if dom.classification not in ("input", "status", "flag"):
            continue
        if dom.set_by_stub:
            continue
        iva = InputVarAnalysis(
            name=name,
            classification=dom.classification,
            data_type=dom.data_type,
            max_length=dom.max_length,
            min_value=dom.min_value,
            max_value=dom.max_value,
            condition_literals=list(dom.condition_literals or []),
            valid_88_values=dict(dom.valid_88_values or {}),
            semantic_type=dom.semantic_type,
        )
        if hasattr(dom, "pic") and dom.pic:
            iva.pic = dom.pic
        analysis.input_variables[name] = iva

    log.info(
        "Program analysis: %d paragraphs, %d stubs, %d input vars",
        len(analysis.paragraphs),
        len(analysis.stub_operations),
        len(analysis.input_variables),
    )

    return analysis


def _walk_statements(stmts):
    """Recursively yield all statements."""
    for s in (stmts or []):
        yield s
        if s.children:
            yield from _walk_statements(s.children)


def _parse_yaml_seeds(text: str) -> list[dict]:
    """Parse YAML-ish seed output from LLM.

    Handles the simple list-of-dicts structure LLMs produce.  Falls back
    to JSON parsing if the response looks like JSON.  No yaml package needed.
    """
    import re

    text = text.strip()

    # Strip markdown fences
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()

    # Try JSON first (LLMs sometimes ignore YAML instruction)
    if text.startswith("[") or text.startswith("{"):
        try:
            from .llm_test_states import parse_test_states
            states = parse_test_states(text)
            return [
                {
                    "input_values": s.input_values,
                    "stub_overrides": s.stub_overrides,
                    "target": s.target_description,
                    "reasoning": s.reasoning,
                }
                for s in states
            ]
        except Exception:
            pass

    # Parse YAML-like structure:
    # - target: ...
    #   reasoning: ...
    #   input_values:
    #     VAR: val
    #   stub_overrides:
    #     OP: val
    seeds: list[dict] = []
    current: dict | None = None
    current_section: str | None = None  # "input_values" or "stub_overrides"

    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # New item: "- target: ..." or "- reasoning: ..."
        m = re.match(r'^-\s+(\w+):\s*(.*)', line)
        if m:
            if current is not None:
                seeds.append(current)
            current = {"input_values": {}, "stub_overrides": {}, "target": "", "reasoning": ""}
            current_section = None
            key, val = m.group(1), m.group(2).strip().strip('"').strip("'")
            if key in current:
                current[key] = val
            continue

        if current is None:
            continue

        # Top-level key within item: "  reasoning: ..." or "  input_values:"
        m2 = re.match(r'^\s{1,4}(\w+):\s*(.*)', line)
        if m2:
            key, val = m2.group(1), m2.group(2).strip().strip('"').strip("'")
            if key in ("input_values", "stub_overrides"):
                current_section = key
                continue
            if key in ("target", "reasoning"):
                current[key] = val
                current_section = None
                continue

        # Sub-key within section: "    VAR-NAME: value"
        m3 = re.match(r'^\s{4,8}([A-Z0-9][\w-]*):\s*(.*)', line)
        if m3 and current_section:
            var, val = m3.group(1), m3.group(2).strip().strip('"').strip("'")
            current[current_section][var] = val
            continue

    if current is not None:
        seeds.append(current)

    # Filter out empty seeds
    return [s for s in seeds if s.get("input_values") or s.get("stub_overrides")]


# ---------------------------------------------------------------------------
# LLM seed generation from analysis (one call per paragraph batch)
# ---------------------------------------------------------------------------

def generate_seeds_from_analysis(
    analysis: ProgramAnalysis,
    llm_provider,
    llm_model: str | None = None,
    batch_size: int = 10,
    seeds_per_batch: int = 8,
    cache_path: str | Path | None = None,
    use_cache: bool = True,
) -> list[dict]:
    """Query LLM to generate initial seed test states from the analysis JSON.

    Sends paragraphs in batches to handle large programs.  Each batch
    includes the paragraph's comments, condition variables, stub operations,
    and gating conditions — enough context for the LLM to generate
    realistic inputs without seeing the full COBOL source.

    Returns list of {input_values, stub_overrides, target, reasoning} dicts.
    """
    from .llm_coverage import LLMUnrecoverableAuthError, _query_llm_sync

    # Check cache
    if cache_path and use_cache:
        cache_path = Path(cache_path)
        if cache_path.exists():
            try:
                cached = json.loads(cache_path.read_text())
                if cached:
                    log.info("Loaded %d seeds from cache: %s", len(cached), cache_path)
                    return cached
            except (json.JSONDecodeError, KeyError):
                pass

    all_seeds: list[dict] = []

    # Sort paragraphs by branch count (most complex first)
    sorted_paras = sorted(
        analysis.paragraphs.values(),
        key=lambda p: p.branch_count,
        reverse=True,
    )

    # Build variable summary once
    var_lines = []
    for name, iva in sorted(analysis.input_variables.items()):
        extras = []
        if iva.condition_literals:
            extras.append(f"values={iva.condition_literals[:6]}")
        if iva.valid_88_values:
            extras.append(f"88={iva.valid_88_values}")
        if iva.semantic_type != "generic":
            extras.append(f"type={iva.semantic_type}")
        extra = f" ({', '.join(extras)})" if extras else ""
        var_lines.append(f"  {name}: {iva.classification} {iva.data_type}{extra}")
    var_summary = "\n".join(var_lines[:60]) or "  (none)"

    # Build stub summary once
    stub_lines = []
    for op_key, soa in sorted(analysis.stub_operations.items()):
        vals = soa.known_values[:6] if soa.known_values else ["00"]
        stub_lines.append(f"  {op_key} → {soa.status_vars} [{', '.join(str(v) for v in vals)}]")
    stub_summary = "\n".join(stub_lines) or "  (none)"

    # Process in batches
    total_batches = (len(sorted_paras) + batch_size - 1) // batch_size
    for batch_start in range(0, len(sorted_paras), batch_size):
        batch = sorted_paras[batch_start:batch_start + batch_size]
        batch_num = batch_start // batch_size + 1
        log.info("Seed generation: batch %d/%d (paragraphs %d-%d, %d seeds so far)",
                 batch_num, total_batches,
                 batch_start, batch_start + len(batch), len(all_seeds))

        para_block = []
        for pa in batch:
            lines = [f"\n### {pa.name} ({pa.branch_count} branches)"]
            if pa.comments:
                lines.append(f"  Comments: {'; '.join(pa.comments[:3])}")
            if pa.calls:
                lines.append(f"  Calls: {', '.join(pa.calls[:5])}")
            if pa.stub_ops:
                lines.append(f"  Stubs: {', '.join(pa.stub_ops)}")
            if pa.gating_conditions:
                lines.append(f"  Gates: {'; '.join(pa.gating_conditions[:3])}")
            if pa.condition_vars:
                cv_parts = []
                for var, vals in list(pa.condition_vars.items())[:5]:
                    cv_parts.append(f"{var}={vals[:4]}")
                lines.append(f"  Conditions: {'; '.join(cv_parts)}")
            para_block.append("\n".join(lines))

        prompt = f"""\
You are a COBOL test engineer. Generate {seeds_per_batch} test scenarios for program {analysis.program_id}.

=== PARAGRAPHS (this batch) ===
{"".join(para_block)}

=== INPUT VARIABLES ===
{var_summary}

=== STUB OPERATIONS ===
{stub_summary}

Generate realistic business scenarios. Each should target specific paragraphs
and set variables to trigger different branch paths. For stub_overrides, use
operation keys from above with appropriate status values.

Respond in YAML format (easier to parse than JSON):
- target: brief scenario description
  reasoning: why these values trigger this path
  input_values:
    VARIABLE-NAME: value
  stub_overrides:
    OPERATION-KEY: status"""

        try:
            response_text, _tokens = _query_llm_sync(
                llm_provider, prompt, llm_model,
            )
            seeds_batch = _parse_yaml_seeds(response_text)
            all_seeds.extend(seeds_batch)
            log.info(
                "LLM seeds batch %d-%d: %d states (total: %d seeds)",
                batch_start, batch_start + len(batch), len(seeds_batch),
                len(all_seeds),
            )
        except Exception as e:
            if isinstance(e, LLMUnrecoverableAuthError):
                raise
            log.warning("LLM seed generation failed for batch %d: %s", batch_start, e)

    # Cache results
    if cache_path and use_cache and all_seeds:
        cache_p = Path(cache_path)
        cache_p.parent.mkdir(parents=True, exist_ok=True)
        cache_p.write_text(json.dumps(all_seeds, indent=2, default=str))
        log.info("Cached %d seeds to %s", len(all_seeds), cache_p)

    return all_seeds
