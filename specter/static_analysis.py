"""Static reachability analysis of the COBOL AST call graph."""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass, field
from functools import cached_property

from .models import Program, Statement
from .variable_extractor import _CMP_RE, _clean_var_name, _KEYWORDS


@dataclass
class GatingCondition:
    """A condition that gates entry to a paragraph."""

    variable: str
    values: list
    negated: bool  # True if PERFORM is in ELSE branch


@dataclass
class PathConstraints:
    """Constraints along a path from entry to a target paragraph."""

    target: str
    path: list[str]
    constraints: list[GatingCondition]


@dataclass
class StaticCallGraph:
    """Static call graph built from PERFORM/GO_TO edges in the AST."""

    edges: dict[str, set[str]] = field(default_factory=dict)
    reverse_edges: dict[str, set[str]] = field(default_factory=dict)
    entry: str = ""
    all_paragraphs: set[str] = field(default_factory=set)

    @cached_property
    def reachable(self) -> frozenset[str]:
        """BFS from entry to find all reachable paragraphs."""
        if not self.entry:
            return frozenset()
        visited: set[str] = set()
        queue = deque([self.entry])
        visited.add(self.entry)
        while queue:
            node = queue.popleft()
            for callee in self.edges.get(node, set()):
                if callee not in visited and callee in self.all_paragraphs:
                    visited.add(callee)
                    queue.append(callee)
        return frozenset(visited)

    @cached_property
    def unreachable(self) -> frozenset[str]:
        """Paragraphs not reachable from entry."""
        return frozenset(self.all_paragraphs - self.reachable)

    def path_to(self, target: str) -> list[str] | None:
        """BFS shortest path from entry to target. Returns None if unreachable."""
        if not self.entry or target not in self.all_paragraphs:
            return None
        if target == self.entry:
            return [self.entry]
        visited: set[str] = {self.entry}
        queue: deque[list[str]] = deque([[self.entry]])
        while queue:
            path = queue.popleft()
            node = path[-1]
            for callee in self.edges.get(node, set()):
                if callee not in visited and callee in self.all_paragraphs:
                    new_path = path + [callee]
                    if callee == target:
                        return new_path
                    visited.add(callee)
                    queue.append(new_path)
        return None

    def frontier(self, covered: set[str]) -> set[str]:
        """Reachable paragraphs not yet covered."""
        return set(self.reachable) - covered


def build_static_call_graph(program: Program) -> StaticCallGraph:
    """Walk every statement to build a static call graph from PERFORM/GO_TO edges."""
    graph = StaticCallGraph()
    graph.all_paragraphs = {p.name for p in program.paragraphs}
    if program.paragraphs:
        graph.entry = program.paragraphs[0].name

    para_order = [p.name for p in program.paragraphs]
    para_index = {name: idx for idx, name in enumerate(para_order)}

    def _collect(para_name: str, stmt: Statement):
        target = stmt.attributes.get("target", "")
        if target and stmt.type in (
            "PERFORM", "PERFORM_THRU", "GO_TO",
        ):
            graph.edges.setdefault(para_name, set()).add(target)
            graph.reverse_edges.setdefault(target, set()).add(para_name)

            # For PERFORM_THRU, add edges to all paragraphs in the range
            if stmt.type == "PERFORM_THRU":
                thru = stmt.attributes.get("thru", "")
                if thru and thru != target:
                    start_idx = para_index.get(target)
                    end_idx = para_index.get(thru)
                    if (start_idx is not None and end_idx is not None
                            and end_idx > start_idx):
                        for idx in range(start_idx, end_idx + 1):
                            p = para_order[idx]
                            graph.edges.setdefault(para_name, set()).add(p)
                            graph.reverse_edges.setdefault(p, set()).add(para_name)

        for child in stmt.children:
            _collect(para_name, child)

    for para in program.paragraphs:
        for stmt in para.statements:
            _collect(para.name, stmt)

    return graph


def _parse_condition_variables(condition: str) -> list[tuple[str, list, bool]]:
    """Extract (variable, values, is_negated) triples from a condition string.

    Returns a list of tuples: (variable_name, [literal_values], negated).
    For bare flag conditions like "SCHEDULE-FILE-ERROR", returns
    (variable_name, [True], False) since the flag must be truthy.
    """
    if not condition:
        return []
    text = condition.strip()
    results = []

    parts = _CMP_RE.split(text)
    ops = _CMP_RE.findall(text)

    # Handle bare flag conditions (no comparison operator)
    # e.g. "SCHEDULE-FILE-ERROR" or "NOT SCHEDULE-FILE-ERROR"
    if not ops:
        tokens = re.findall(r"[A-Z][A-Z0-9-]*", text, re.IGNORECASE)
        negated = False
        var_name = None
        for tok in tokens:
            upper = tok.upper()
            if upper == "NOT":
                negated = True
            elif upper not in _KEYWORDS and upper not in ("AND", "OR") and len(tok) >= 2:
                var_name = _clean_var_name(upper)
                break
        if var_name:
            results.append((var_name, [True], negated))
        return results

    for idx, op in enumerate(ops):
        lhs_raw = parts[idx].strip() if idx < len(parts) else ""
        rhs_raw = parts[idx + 1].strip() if idx + 1 < len(parts) else ""
        if not lhs_raw or not rhs_raw:
            continue

        # Check if this comparison is negated
        # NOT can be in the operator (NOT =, NOT EQUAL) or before it in the LHS
        op_upper = op.upper().strip()
        lhs_upper = lhs_raw.upper()
        negated = "NOT" in op_upper or lhs_upper.rstrip().endswith("NOT")

        # Extract variable from LHS
        lhs_tokens = re.findall(
            r"[A-Z][A-Z0-9-]*(?:\([^)]*\))?|'[^']*'|-?\d+\.?\d*",
            lhs_raw, re.IGNORECASE,
        )
        var_name = None
        for tok in reversed(lhs_tokens):
            tok_upper = tok.upper()
            if (tok_upper not in _KEYWORDS
                    and tok_upper not in ("AND", "OR", "NOT")
                    and not tok.startswith("'")
                    and not re.match(r"^-?\d+\.?\d*$", tok)):
                var_name = _clean_var_name(tok_upper)
                break
        if not var_name or len(var_name) < 2:
            continue

        # Extract literals from RHS
        rhs_tokens = re.findall(
            r"'[^']*'|-?\d+\.?\d*|[A-Z][A-Z0-9-]*(?:\([^)]*\))?",
            rhs_raw, re.IGNORECASE,
        )
        literals: list = []
        for tok in rhs_tokens:
            tok_upper = tok.upper()
            if tok_upper in ("AND", "OR", "NOT", "IS", "NUMERIC"):
                continue
            if tok.startswith("'") and tok.endswith("'"):
                literals.append(tok[1:-1])
            elif re.match(r"^-?\d+$", tok):
                literals.append(int(tok))
            elif re.match(r"^-?\d+\.\d+$", tok):
                literals.append(float(tok))

        if literals:
            results.append((var_name, literals, negated))

    return results


def extract_gating_conditions(
    program: Program,
    call_graph: StaticCallGraph,
) -> dict[str, list[GatingCondition]]:
    """Walk statement trees with a condition stack to find gating conditions.

    Returns a mapping from paragraph name to the list of GatingConditions
    that must be satisfied to reach that paragraph.
    """
    gating: dict[str, list[GatingCondition]] = {}

    def _walk(stmt: Statement, condition_stack: list[GatingCondition]):
        if stmt.type == "IF":
            condition_text = stmt.attributes.get("condition", "")
            parsed = _parse_condition_variables(condition_text)

            # Build positive conditions for the then-branch
            then_conditions = []
            for var, vals, neg in parsed:
                then_conditions.append(GatingCondition(
                    variable=var, values=vals, negated=neg,
                ))

            # Build negated conditions for the else-branch
            else_conditions = []
            for var, vals, neg in parsed:
                else_conditions.append(GatingCondition(
                    variable=var, values=vals, negated=not neg,
                ))

            # Process then-branch children (non-ELSE children)
            # Process else-branch children (ELSE children)
            for child in stmt.children:
                if child.type == "ELSE":
                    new_stack = condition_stack + else_conditions
                    for sub in child.children:
                        _walk(sub, new_stack)
                else:
                    new_stack = condition_stack + then_conditions
                    _walk(child, new_stack)
            return

        # Record gating conditions for PERFORM targets
        if stmt.type in ("PERFORM", "PERFORM_THRU", "GO_TO"):
            target = stmt.attributes.get("target", "")
            if target and condition_stack:
                gating.setdefault(target, []).extend(condition_stack)

        for child in stmt.children:
            _walk(child, condition_stack)

    for para in program.paragraphs:
        for stmt in para.statements:
            _walk(stmt, [])

    # Second pass: detect GO_TO guards.
    # When an IF's then-branch contains a GO_TO (early exit), all subsequent
    # PERFORMs in the same paragraph are implicitly gated by NOT(condition).
    for para in program.paragraphs:
        guard_stack: list[GatingCondition] = []
        for stmt in para.statements:
            if stmt.type == "IF":
                condition_text = stmt.attributes.get("condition", "")
                # Check if the then-branch contains a GO_TO (exit guard)
                has_goto = _subtree_has_goto(stmt)
                if has_goto and condition_text:
                    parsed = _parse_condition_variables(condition_text)
                    for var, vals, neg in parsed:
                        # Subsequent code only runs if condition is NOT met
                        guard_stack.append(GatingCondition(
                            variable=var, values=vals, negated=not neg,
                        ))
            elif stmt.type in ("PERFORM", "PERFORM_THRU") and guard_stack:
                target = stmt.attributes.get("target", "")
                if target:
                    gating.setdefault(target, []).extend(guard_stack)

    return gating


def _subtree_has_goto(stmt: Statement) -> bool:
    """Check if an IF statement's then-branch contains a GO_TO."""
    for child in stmt.children:
        if child.type == "ELSE":
            continue
        if child.type == "GO_TO":
            return True
        if _subtree_has_goto(child):
            return True
    return False


@dataclass
class SequentialGate:
    """A paragraph with 3+ sequential operation→IF checks (a 'gate gauntlet')."""

    paragraph: str
    gate_count: int
    status_variables: list[str]
    success_values: dict[str, list]  # variable → [success values]


def extract_sequential_gates(program: Program) -> list[SequentialGate]:
    """Detect paragraphs with 3+ sequential operation→IF patterns.

    These are initialization gauntlets where each operation (OPEN, CALL, EXEC)
    is immediately followed by a status check.  All checks must pass for
    execution to continue past the gauntlet.
    """
    gates: list[SequentialGate] = []
    op_types = {"OPEN", "CLOSE", "READ", "WRITE", "REWRITE", "DELETE",
                "CALL", "EXEC_SQL", "EXEC_CICS", "START"}

    for para in program.paragraphs:
        gate_count = 0
        status_vars: list[str] = []
        success_vals: dict[str, list] = {}

        stmts = para.statements
        for idx, stmt in enumerate(stmts):
            if stmt.type in op_types:
                # Look ahead: is the next statement an IF checking a status var?
                if idx + 1 < len(stmts) and stmts[idx + 1].type == "IF":
                    cond = stmts[idx + 1].attributes.get("condition", "")
                    parsed = _parse_condition_variables(cond)
                    for var, vals, neg in parsed:
                        upper = var.upper()
                        if ("STATUS" in upper or upper.startswith("FS-")
                                or "RETURN-CODE" in upper or upper.endswith("-RC")
                                or "SQLCODE" in upper or "EIBRESP" in upper):
                            gate_count += 1
                            status_vars.append(var)
                            if not neg and vals:
                                success_vals[var] = vals
                            elif neg and vals:
                                # NOT = X means success is X (the negated path
                                # is the error path, so non-negated values are
                                # actually what must NOT be true for error)
                                # Store the values that trigger the error branch
                                pass

        if gate_count >= 3:
            gates.append(SequentialGate(
                paragraph=para.name,
                gate_count=gate_count,
                status_variables=status_vars,
                success_values=success_vals,
            ))

    return gates


def augment_gating_with_sequential_gates(
    gating_conditions: dict[str, list[GatingCondition]],
    sequential_gates: list[SequentialGate],
    call_graph: StaticCallGraph,
) -> dict[str, list[GatingCondition]]:
    """Propagate sequential gate constraints to all paragraphs called from gate paragraphs.

    Any paragraph reachable from a gate paragraph inherits the gate's
    success-value constraints, since those must all pass for the gate
    paragraph to complete and execution to continue.
    """
    for gate in sequential_gates:
        # Build gating conditions from the gate's success values
        gate_conds: list[GatingCondition] = []
        for var, vals in gate.success_values.items():
            gate_conds.append(GatingCondition(
                variable=var, values=vals, negated=False,
            ))

        if not gate_conds:
            continue

        # Propagate to all paragraphs directly called from this gate paragraph
        callees = call_graph.edges.get(gate.paragraph, set())
        for callee in callees:
            gating_conditions.setdefault(callee, []).extend(gate_conds)

    return gating_conditions


def compute_path_constraints(
    target: str,
    call_graph: StaticCallGraph,
    gating_conditions: dict[str, list[GatingCondition]],
) -> PathConstraints | None:
    """Compute the constraints along the shortest path to a target paragraph."""
    path = call_graph.path_to(target)
    if path is None:
        return None

    constraints: list[GatingCondition] = []
    for node in path:
        if node in gating_conditions:
            constraints.extend(gating_conditions[node])

    return PathConstraints(target=target, path=path, constraints=constraints)


# ---------------------------------------------------------------------------
# Equality constraint extraction
# ---------------------------------------------------------------------------

@dataclass
class EqualityConstraint:
    """Two variables that must be equal for execution to proceed."""

    var_a: str
    var_b: str
    paragraph: str


def extract_equality_constraints(program: Program) -> list[EqualityConstraint]:
    """Find IF conditions comparing two variables for (in)equality.

    These represent business logic gates like:
      IF BILLING-DATE-CURR-RTCTDB NOT EQUAL BUCKET-LAST-CUTOFF
    where both sides are variable references (not literals).
    """
    constraints: list[EqualityConstraint] = []
    _eq_re = re.compile(
        r"([A-Z][A-Z0-9-]+)\s+(?:NOT\s+)?(?:EQUAL(?:\s+TO)?|=)\s+([A-Z][A-Z0-9-]+)",
        re.IGNORECASE,
    )
    _skip_vals = frozenset({
        "SPACES", "SPACE", "ZEROS", "ZERO", "ZEROES",
        "HIGH-VALUES", "HIGH-VALUE", "LOW-VALUES", "LOW-VALUE",
        "TRUE", "FALSE", "NUMERIC", "NULL", "NULLS",
    })

    def _walk(stmts: list[Statement], para_name: str):
        for stmt in stmts:
            if stmt.type == "IF" and stmt.text:
                for m in _eq_re.finditer(stmt.text):
                    a, b = m.group(1).upper(), m.group(2).upper()
                    if a in _skip_vals or b in _skip_vals:
                        continue
                    if a in _KEYWORDS or b in _KEYWORDS:
                        continue
                    # Both must look like variable names
                    if re.match(r"^\d", a) or re.match(r"^\d", b):
                        continue
                    constraints.append(EqualityConstraint(
                        var_a=a, var_b=b, paragraph=para_name,
                    ))
            if stmt.children:
                _walk(stmt.children, para_name)

    for para in program.paragraphs:
        _walk(para.statements, para.name)

    return constraints
