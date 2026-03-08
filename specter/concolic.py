"""Concolic coverage engine — uses Z3 to solve for inputs that flip uncovered branches.

This module is entirely optional.  It is imported lazily only when
``--concolic`` is passed on the CLI and Z3 is installed
(``pip install z3-solver``).

The public entry point is :func:`solve_for_uncovered_branches`.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy Z3 import — callers must guard with try/except
# ---------------------------------------------------------------------------

def _import_z3():
    """Import z3 lazily.  Raises ImportError when z3-solver is absent."""
    import z3
    return z3


# ---------------------------------------------------------------------------
# Shared constants (mirrored from condition_parser to avoid coupling)
# ---------------------------------------------------------------------------

_FIGURATIVE = {
    "SPACES": " ",
    "SPACE": " ",
    "LOW-VALUES": "",
    "LOW-VALUE": "",
    "HIGH-VALUES": "\xff",
    "HIGH-VALUE": "\xff",
    "ZEROS": 0,
    "ZERO": 0,
    "ZEROES": 0,
}

_DFHRESP = {
    "NORMAL": 0,
    "ERROR": 1,
    "TERMIDERR": 11,
    "FILENOTFOUND": 12,
    "NOTFND": 13,
    "DUPREC": 14,
    "DUPKEY": 15,
    "INVREQ": 16,
    "IOERR": 17,
    "NOSPACE": 18,
    "NOTOPEN": 19,
    "ENDFILE": 20,
    "ILLOGIC": 21,
    "LENGERR": 22,
    "QZERO": 23,
    "SIGNAL": 24,
    "QBUSY": 25,
    "ITEMERR": 26,
    "PGMIDERR": 27,
    "TRANSIDERR": 28,
    "ENDDATA": 29,
    "INVTSREQ": 30,
    "EXPIRED": 31,
    "MAPFAIL": 36,
    "ENQBUSY": 55,
    "DISABLED": 84,
    "NOTAUTH": 70,
}

# Reuse the tokenizer pattern from condition_parser
_TOKEN_RE = re.compile(
    r"""
      '(?:[^']*)'               # quoted string
    | DFHRESP\(\w+\)            # DFHRESP(code)
    | [A-Za-z0-9_-]+\([^)]*\)   # function/subscript like FOO(1:2)
    | [><=]+                     # operators
    | [A-Za-z0-9_-]+             # identifiers/numbers
    """,
    re.VERBOSE | re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_CONCOLIC_TIMEOUT_MS = 500
_CONCOLIC_MAX_BRANCHES = 50
_CONCOLIC_COOLDOWN = 1000  # iterations before retrying a failed branch


@dataclass
class ConcolicSolution:
    """A Z3-derived input assignment that should flip a particular branch."""
    branch_id: int
    assignments: dict[str, object] = field(default_factory=dict)
    stub_outcomes: dict[str, list] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Z3 condition translator — parallel to condition_parser._Parser
# ---------------------------------------------------------------------------

class _Z3Parser:
    """Recursive descent parser producing Z3 expressions from COBOL conditions."""

    def __init__(self, tokens: list[str], var_env: dict, z3):
        self.tokens = tokens
        self.pos = 0
        self.var_env = var_env
        self.z3 = z3

    def peek(self, offset: int = 0):
        idx = self.pos + offset
        if idx < len(self.tokens):
            return self.tokens[idx]
        return None

    def advance(self) -> str:
        t = self.tokens[self.pos]
        self.pos += 1
        return t

    def at_end(self) -> bool:
        return self.pos >= len(self.tokens)

    def match(self, *values: str) -> bool:
        t = self.peek()
        if t and t.upper() in [v.upper() for v in values]:
            return True
        return False

    def consume(self, *values: str):
        if self.match(*values):
            return self.advance()
        return None

    def parse(self):
        result = self._or_expr()
        return result

    def _or_expr(self):
        left = self._and_expr()
        while self.match("OR"):
            self.advance()
            right = self._and_expr()
            left = self.z3.Or(left, right)
        return left

    def _and_expr(self):
        left = self._not_expr()
        while self.match("AND"):
            self.advance()
            right = self._not_expr()
            left = self.z3.And(left, right)
        return left

    def _not_expr(self):
        if self.match("NOT"):
            next_t = self.peek(1)
            if next_t and next_t.upper() in ("=", "EQUAL", "GREATER", "LESS", ">", "<", ">=", "<="):
                return self._comparison()
            self.advance()
            inner = self._not_expr()
            return self.z3.Not(inner)
        return self._comparison()

    def _comparison(self):
        lhs_token = self._primary_token()
        if lhs_token is None:
            return self.z3.BoolVal(True)

        lhs = self._resolve_z3(lhs_token)

        # IS NUMERIC / IS NOT NUMERIC
        if self.match("IS"):
            self.advance()
            if self.match("NOT"):
                self.advance()
                if self.match("NUMERIC"):
                    self.advance()
                    return self.z3.BoolVal(True)  # approximation
                negated = True
                op = self._parse_operator()
                if op is not None:
                    rhs_token = self._primary_token()
                    if rhs_token is None:
                        return self.z3.BoolVal(True)
                    rhs = self._resolve_z3(rhs_token)
                    lhs, rhs = self._coerce_pair(lhs, rhs)
                    return self._apply_negated_op(op, lhs, rhs)
                return self.z3.BoolVal(True)
            if self.match("NUMERIC"):
                self.advance()
                return self.z3.BoolVal(True)  # approximation
            if self.peek() and self.peek().upper() in ("GREATER", "LESS", "EQUAL", ">", "<", ">=", "<=", "="):
                pass  # fall through to operator parsing
            else:
                return self._to_bool(lhs)

        negated = False
        if self.match("NOT"):
            negated = True
            self.advance()

        op = self._parse_operator()
        if op is None:
            result = self._to_bool(lhs)
            if negated:
                return self.z3.Not(result)
            return result

        rhs_token = self._primary_token()
        if rhs_token is None:
            return self._to_bool(lhs)

        rhs = self._resolve_z3(rhs_token)

        # Multi-value: X = A OR B OR C
        values = [rhs]
        while not self.at_end():
            if self.match("OR"):
                next_t = self.peek(1)
                if next_t and self._looks_like_value(next_t):
                    after = self.peek(2)
                    if after and after.upper() in ("=", ">", "<", ">=", "<=", "NOT", "IS", "EQUAL", "GREATER", "LESS"):
                        break
                    self.advance()  # skip OR
                    val_token = self.peek()
                    if val_token:
                        self.advance()
                        values.append(self._resolve_z3(val_token))
                    else:
                        break
                else:
                    break
            elif self.match("AND") and negated:
                next_t = self.peek(1)
                if next_t and self._looks_like_value(next_t):
                    after = self.peek(2)
                    if after and after.upper() in ("=", ">", "<", ">=", "<=", "NOT", "IS", "EQUAL"):
                        break
                    self.advance()  # skip AND
                    val_token = self.advance()
                    values.append(self._resolve_z3(val_token))
                else:
                    break
            else:
                break

        # Build Z3 expression
        if len(values) == 1:
            lhs, rhs = self._coerce_pair(lhs, values[0])
            if negated:
                return self._apply_negated_op(op, lhs, rhs)
            return self._apply_op(op, lhs, rhs)
        else:
            # Multi-value: OR / NOT IN
            coerced_vals = [self._coerce_pair(lhs, v)[1] for v in values]
            lhs_c = self._coerce_pair(lhs, values[0])[0]
            alternatives = [lhs_c == v for v in coerced_vals]
            if negated:
                return self.z3.And(*[self.z3.Not(a) for a in alternatives])
            return self.z3.Or(*alternatives)

    def _parse_operator(self):
        t = self.peek()
        if t is None:
            return None
        upper = t.upper()
        if upper == "=":
            self.advance()
            return "=="
        if upper in (">", "<", ">=", "<="):
            self.advance()
            return upper
        if upper == "EQUAL":
            self.advance()
            self.consume("TO")
            return "=="
        if upper == "GREATER":
            self.advance()
            self.consume("THAN")
            return ">"
        if upper == "LESS":
            self.advance()
            self.consume("THAN")
            return "<"
        return None

    def _primary_token(self):
        if self.at_end():
            return None
        t = self.peek()
        if t and t.upper() in ("AND", "OR"):
            return None
        if t and t.upper() == "NOT":
            next_t = self.peek(1)
            if next_t and next_t.upper() in ("=", "EQUAL", "GREATER", "LESS", ">", "<", ">=", "<="):
                return None
            return None
        if t and self._is_value_token(t):
            self.advance()
            return t
        return None

    def _is_value_token(self, token: str) -> bool:
        upper = token.upper()
        if upper in ("AND", "OR", "NOT", "IS", "NUMERIC", "EQUAL", "THAN", "TO",
                     "GREATER", "LESS", "OF"):
            return False
        if upper in ("=", ">", "<", ">=", "<="):
            return False
        return True

    def _looks_like_value(self, token: str) -> bool:
        upper = token.upper()
        if upper in _FIGURATIVE:
            return True
        if token.startswith("'"):
            return True
        if re.match(r"^-?\d+\.?\d*$", token):
            return True
        if re.match(r"DFHRESP\(", token, re.IGNORECASE):
            return True
        if re.match(r"^[A-Za-z][A-Za-z0-9_-]*(\([^)]*\))?$", token):
            return True
        return False

    # ---- Z3 value resolution ----

    def _resolve_z3(self, token: str):
        """Resolve a COBOL token to a Z3 expression."""
        z3 = self.z3
        upper = token.upper()

        # Figurative constants
        if upper in _FIGURATIVE:
            val = _FIGURATIVE[upper]
            if isinstance(val, int):
                return z3.IntVal(val)
            return z3.StringVal(val)

        # DFHRESP(...)
        m = re.match(r"DFHRESP\((\w+)\)", token, re.IGNORECASE)
        if m:
            code = m.group(1).upper()
            return z3.IntVal(_DFHRESP.get(code, 0))

        # Quoted string
        if token.startswith("'") and token.endswith("'"):
            return z3.StringVal(token[1:-1])

        # Numeric literal
        if re.match(r"^[+-]?\d+\.?\d*$", token):
            if "." in token:
                # Approximate as int for Z3 (Z3 Int is simpler)
                return z3.IntVal(int(float(token)))
            return z3.IntVal(int(token))

        # Variable reference
        var_name = upper
        # Strip subscript
        paren = var_name.find("(")
        if paren >= 0:
            var_name = var_name[:paren]

        if var_name in self.var_env:
            return self.var_env[var_name]

        # Unknown variable — return a fresh unconstrained Int
        v = z3.Int(var_name)
        self.var_env[var_name] = v
        return v

    def _to_bool(self, expr):
        """Convert a Z3 expression to Bool if needed."""
        z3 = self.z3
        if z3.is_bool(expr):
            return expr
        if z3.is_int(expr):
            return expr != z3.IntVal(0)
        if z3.is_string(expr):
            return expr != z3.StringVal("")
        return z3.BoolVal(True)

    def _coerce_pair(self, a, b):
        """Coerce a pair of Z3 expressions to compatible types."""
        z3 = self.z3
        a_int = z3.is_int(a)
        b_int = z3.is_int(b)
        a_str = z3.is_string(a)
        b_str = z3.is_string(b)

        if a_int and b_str:
            # Try to interpret b as int if it's a StringVal constant
            try:
                val = int(str(b).strip('"'))
                return a, z3.IntVal(val)
            except (ValueError, TypeError):
                pass
            # Convert a to string
            return z3.IntToStr(a) if hasattr(z3, 'IntToStr') else a, b
        if a_str and b_int:
            try:
                val = int(str(a).strip('"'))
                return z3.IntVal(val), b
            except (ValueError, TypeError):
                pass
            return a, z3.IntToStr(b) if hasattr(z3, 'IntToStr') else b
        return a, b

    def _apply_op(self, op: str, lhs, rhs):
        if op == "==":
            return lhs == rhs
        if op == ">":
            return lhs > rhs
        if op == "<":
            return lhs < rhs
        if op == ">=":
            return lhs >= rhs
        if op == "<=":
            return lhs <= rhs
        return lhs == rhs

    def _apply_negated_op(self, op: str, lhs, rhs):
        neg = {"==": "!=", ">": "<=", "<": ">=", ">=": "<", "<=": ">"}
        nop = neg.get(op, "!=")
        if nop == "!=":
            return lhs != rhs
        if nop == "<=":
            return lhs <= rhs
        if nop == ">=":
            return lhs >= rhs
        if nop == "<":
            return lhs < rhs
        if nop == ">":
            return lhs > rhs
        return lhs != rhs


# ---------------------------------------------------------------------------
# Public API: condition translator
# ---------------------------------------------------------------------------

def cobol_condition_to_z3(condition_text: str, var_env: dict):
    """Convert a COBOL condition string to a Z3 BoolRef.

    *var_env* maps variable names (uppercase) to Z3 variables.
    New variables encountered in the condition are added to *var_env*.

    Raises ``ImportError`` if z3-solver is not installed.
    """
    z3 = _import_z3()
    text = condition_text.strip()
    if not text:
        return z3.BoolVal(True)

    if text.upper().startswith("UNTIL "):
        text = text[6:].strip()

    tokens = _TOKEN_RE.findall(text)
    if not tokens:
        return z3.BoolVal(True)

    parser = _Z3Parser(tokens, var_env, z3)
    return parser.parse()


# ---------------------------------------------------------------------------
# Variable environment builder
# ---------------------------------------------------------------------------

def build_var_env(var_report, observed_state: dict | None = None,
                  stub_mapping: dict | None = None):
    """Create Z3 variables for each known COBOL variable.

    - ``input``/``status``/``flag`` → free Z3 variable (solvable)
    - ``internal`` → Z3 constant from *observed_state* (fixed)
    - Variables that appear in *stub_mapping* values are always free
      (they are set by stub outcomes and thus controllable)

    Type inference:
    - If all condition_literals are numeric → ``z3.Int``
    - Name contains AMT/CNT/CODE/NUM/AMOUNT/COUNT → ``z3.Int``
    - Classification is ``flag`` → ``z3.Int`` (0/1)
    - Otherwise → ``z3.String``
    """
    z3 = _import_z3()
    env: dict[str, object] = {}
    observed = observed_state or {}

    # Collect all variables controlled by stubs — these are always solvable
    stub_controlled: set[str] = set()
    if stub_mapping:
        for status_vars in stub_mapping.values():
            for sv in status_vars:
                stub_controlled.add(sv.upper())
        log.debug("Concolic: %d stub-controlled vars: %s",
                  len(stub_controlled), sorted(stub_controlled)[:10])

    n_free = 0
    n_fixed = 0
    for name, info in var_report.variables.items():
        upper = name.upper()
        is_numeric = _infer_numeric(upper, info)

        # Stub-controlled vars are free even if classified as internal
        is_free = (info.classification != "internal"
                   or upper in stub_controlled)

        if is_free:
            # Free variable — solver can assign
            n_free += 1
            if is_numeric:
                env[upper] = z3.Int(upper)
            else:
                env[upper] = z3.String(upper)
        else:
            # Fixed to observed value
            n_fixed += 1
            val = observed.get(name, observed.get(upper, ""))
            if is_numeric:
                try:
                    env[upper] = z3.IntVal(int(val) if val != "" else 0)
                except (ValueError, TypeError):
                    env[upper] = z3.IntVal(0)
            else:
                env[upper] = z3.StringVal(str(val))

    log.debug("Concolic var env: %d free, %d fixed, %d total",
              n_free, n_fixed, len(env))
    return env


def _infer_numeric(upper_name: str, info) -> bool:
    """Heuristic: is this variable numeric?"""
    literals = info.condition_literals if hasattr(info, "condition_literals") else []
    if literals:
        all_num = all(_is_numeric_str(str(v)) for v in literals)
        if all_num:
            return True

    # Naming heuristics
    for tag in ("AMT", "CNT", "CODE", "NUM", "AMOUNT", "COUNT",
                "SQLCODE", "EIBRESP", "RETURN-CODE", "-RC"):
        if tag in upper_name:
            return True

    if info.classification == "flag":
        return True

    return False


def _is_numeric_str(s: str) -> bool:
    try:
        float(s)
        return True
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# Solver
# ---------------------------------------------------------------------------

def solve_for_branch(
    branch_id: int,
    branch_meta: dict,
    var_env: dict,
    negate: bool = True,
    timeout_ms: int = _CONCOLIC_TIMEOUT_MS,
    stub_mapping: dict | None = None,
) -> ConcolicSolution | None:
    """Attempt to find inputs that cover *branch_id*.

    If *negate* is True, the condition is negated (to cover the else-branch).
    When *stub_mapping* is provided, solved status variables are also
    returned as ``stub_outcomes`` on the solution.
    Returns a :class:`ConcolicSolution` or ``None`` on unsat/timeout.
    """
    z3 = _import_z3()

    abs_id = abs(branch_id)
    meta = branch_meta.get(abs_id)
    if not meta:
        return None

    condition = meta.get("condition", "")
    if not condition or condition == "OTHER":
        return None

    # For EVALUATE branches, build the condition from subject + WHEN value
    if meta.get("type") == "EVALUATE":
        subject = meta.get("subject", "TRUE")
        if subject.upper() == "TRUE":
            # WHEN value IS a full condition
            pass  # condition is already the WHEN condition
        else:
            # EVALUATE subject WHEN value → subject = value
            condition = f"{subject} = {condition}"

    # Build a fresh var_env copy so solver constraints don't leak
    local_env = dict(var_env)

    try:
        z3_expr = cobol_condition_to_z3(condition, local_env)
    except Exception:
        return None

    if negate:
        z3_expr = z3.Not(z3_expr)

    solver = z3.Solver()
    solver.set("timeout", timeout_ms)
    solver.add(z3_expr)

    # Add reasonable bounds for numeric variables
    for name, var in local_env.items():
        if z3.is_int(var) and not z3.is_int_value(var):
            solver.add(var >= -999999999)
            solver.add(var <= 999999999)

    result = solver.check()
    if result != z3.sat:
        log.debug("Concolic: branch %d unsat/timeout: %s",
                  branch_id, condition[:40])
        return None

    log.debug("Concolic: branch %d sat (negate=%s): %s",
              branch_id, negate, condition[:40])
    model = solver.model()
    assignments: dict[str, object] = {}
    for name, var in local_env.items():
        if z3.is_int(var) and not z3.is_int_value(var):
            val = model.eval(var, model_completion=True)
            try:
                assignments[name] = val.as_long()
            except (AttributeError, Exception):
                pass
        elif z3.is_string(var) and not z3.is_string_value(var):
            val = model.eval(var, model_completion=True)
            try:
                assignments[name] = val.as_string()
            except (AttributeError, Exception):
                pass

    if not assignments:
        return None

    # Split assignments into regular inputs vs stub-controlled variables
    stub_outcomes: dict[str, list] = {}
    if stub_mapping:
        # Build reverse map: var_name -> [op_keys]
        var_to_ops: dict[str, list[str]] = {}
        # Also build op_key -> all status vars (for filling success defaults)
        op_all_vars: dict[str, list[str]] = {}
        for op_key, status_vars in stub_mapping.items():
            op_all_vars[op_key] = [sv.upper() for sv in status_vars]
            for sv in status_vars:
                var_to_ops.setdefault(sv.upper(), []).append(op_key)

        # Collect which op_keys need the solved value
        solved_ops: dict[str, list[tuple[str, object]]] = {}
        for var_name in list(assignments):
            if var_name in var_to_ops:
                val = assignments.pop(var_name)
                for op_key in var_to_ops[var_name]:
                    solved_ops.setdefault(op_key, []).append((var_name, val))

        # For each op_key, build stub outcomes:
        # - Ops that need a specific solved value get a few success entries
        #   first (so earlier invocations pass), then the target value
        # - All other ops get success defaults
        for op_key, all_vars in op_all_vars.items():
            if op_key in solved_ops:
                target_pairs = solved_ops[op_key]
                # Build success entry for this op (all vars at success values)
                success_entry = _stub_success_entry(op_key, all_vars)
                # First N invocations succeed, then target value repeats
                entries = [success_entry] * 5
                target_entry = list(target_pairs)
                entries.extend([target_entry] * 20)
                stub_outcomes[op_key] = entries
            else:
                # Not targeted — fill with success defaults so program
                # survives to the branch point
                success_entry = _stub_success_entry(op_key, all_vars)
                stub_outcomes[op_key] = [success_entry] * 25

    return ConcolicSolution(
        branch_id=branch_id,
        assignments=assignments,
        stub_outcomes=stub_outcomes,
    )


def _stub_success_entry(op_key: str, var_names: list[str]) -> list[tuple[str, object]]:
    """Build a success stub outcome entry for an operation."""
    entry = []
    for var in var_names:
        upper = var.upper()
        if "SQLCODE" in upper or "SQLSTATE" in upper:
            entry.append((var, 0))
        elif "EIBRESP" in upper:
            entry.append((var, 0))
        elif "STATUS" in upper or upper.startswith("FS-"):
            entry.append((var, "00"))
        elif "RETURN-CODE" in upper or upper.endswith("-RC"):
            entry.append((var, 0))
        else:
            entry.append((var, 0))
    return entry


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def solve_for_uncovered_branches(
    branch_meta: dict,
    covered_branches: set[int],
    var_report,
    observed_states: list[dict],
    max_attempts: int = _CONCOLIC_MAX_BRANCHES,
    timeout_ms: int = _CONCOLIC_TIMEOUT_MS,
    stub_mapping: dict | None = None,
    corpus_entries: list | None = None,
) -> list[ConcolicSolution]:
    """Find input assignments for uncovered branches using Z3.

    Prioritizes branches where only one direction is covered (the other
    direction is solvable by negation).

    When *stub_mapping* is provided, status variables controlled by stubs
    (SQL, CICS, file I/O) are treated as free variables and solved
    assignments are returned as ``stub_outcomes`` on each solution.

    When *corpus_entries* is provided (list of _CorpusEntry with coverage
    and input_state), the solver picks the observed state from the entry
    that best reaches each target branch's paragraph, giving internal
    variables realistic runtime values.

    Works with already-generated code that may lack ``_BRANCH_META`` —
    callers should use ``getattr(module, '_BRANCH_META', {})``.
    """
    if not branch_meta:
        return []

    try:
        z3 = _import_z3()
    except ImportError:
        return []

    # Index corpus entries by which paragraphs they reach
    _para_to_states: dict[str, list[dict]] = {}
    if corpus_entries:
        for entry in corpus_entries:
            for para in entry.coverage:
                _para_to_states.setdefault(para, []).append(entry.input_state)
        log.debug("Concolic: indexed %d corpus entries covering %d paras",
                  len(corpus_entries), len(_para_to_states))

    # Default observed state for var env
    default_observed = observed_states[-1] if observed_states else {}

    # Find half-covered branches (one direction covered, other not)
    candidates: list[tuple[int, bool]] = []  # (abs_branch_id, negate)
    n_half = 0
    n_uncovered = 0
    for abs_id in sorted(branch_meta.keys()):
        pos_covered = abs_id in covered_branches
        neg_covered = -abs_id in covered_branches

        if pos_covered and not neg_covered:
            candidates.append((abs_id, True))
            n_half += 1
        elif neg_covered and not pos_covered:
            candidates.append((abs_id, False))
            n_half += 1
        elif not pos_covered and not neg_covered:
            candidates.append((abs_id, False))
            candidates.append((abs_id, True))
            n_uncovered += 1

    all_branch_ids = set()
    for bid in branch_meta:
        all_branch_ids.add(bid)
        all_branch_ids.add(-bid)
    total_covered = len(covered_branches & all_branch_ids)
    log.debug("Concolic: %d/%d covered, %d half, %d uncovered, %d candidates",
              total_covered, len(all_branch_ids),
              n_half, n_uncovered, len(candidates))

    solutions: list[ConcolicSolution] = []
    n_sat = 0
    n_unsat = 0
    for abs_id, negate in candidates[:max_attempts]:
        target_id = -abs_id if negate else abs_id
        if target_id in covered_branches:
            continue

        # Pick the best observed state for this branch's paragraph
        target_para = branch_meta.get(abs_id, {}).get("paragraph", "")
        if target_para and target_para in _para_to_states:
            # Use state from a run that actually reached this paragraph
            observed_for_branch = _para_to_states[target_para][-1]
        else:
            observed_for_branch = default_observed

        # Build var env with paragraph-specific observed values
        var_env = build_var_env(
            var_report, observed_for_branch, stub_mapping=stub_mapping,
        )

        sol = solve_for_branch(
            target_id, branch_meta, var_env,
            negate=negate, timeout_ms=timeout_ms,
            stub_mapping=stub_mapping,
        )
        if sol is not None:
            n_sat += 1
            n_stub_keys = len(sol.stub_outcomes)
            n_input_keys = len(sol.assignments)
            log.debug("Concolic: branch %d solved (%d inputs, %d stubs) %s",
                      target_id, n_input_keys, n_stub_keys, target_para)
            solutions.append(sol)
        else:
            n_unsat += 1

    log.debug("Concolic: %d sat, %d unsat", n_sat, n_unsat)
    return solutions
