"""Convert COBOL condition text into Java boolean expression strings.

Parallels condition_parser.py (which emits Python), but produces Java
expressions suitable for embedding in generated Java source code.

Handles comparisons, figurative constants, boolean flags, IS NUMERIC,
multi-value OR, logical AND/OR, DFHRESP codes, and EVALUATE/WHEN patterns.
"""

from __future__ import annotations

import re

from specter.condition_parser import (
    _tokenize,
    _FIGURATIVE as _PY_FIGURATIVE,
    _DFHRESP,
    _CICS_AID_KEYS,
    _CMP_WORDS,
    _is_value_token,
    _looks_like_bare_value,
    parse_when_value,
)

# ---------------------------------------------------------------------------
# Java figurative constants (double-quoted strings for Java)
# ---------------------------------------------------------------------------

_FIGURATIVE_JAVA: dict[str, str] = {
    "SPACES": '" "',
    "SPACE": '" "',
    "LOW-VALUES": '"\\u0000"',
    "LOW-VALUE": '"\\u0000"',
    "HIGH-VALUES": '"\\u00FF"',
    "HIGH-VALUE": '"\\u00FF"',
    "ZEROS": "0",
    "ZERO": "0",
    "ZEROES": "0",
}


def _java_numeric_literal(token: str) -> str:
    """Render a COBOL numeric token as a Java-safe numeric expression."""
    t = token.strip()
    if re.match(r"^[+-]?\d+$", t):
        digits = t.lstrip("+-").lstrip("0") or "0"
        if len(digits) <= 18:
            n = int(t)
            if -2147483648 <= n <= 2147483647:
                return str(n)
            if -9223372036854775808 <= n <= 9223372036854775807:
                return f"{n}L"
        return f'CobolRuntime.toNum("{t}")'

    if re.match(r"^[+-]?\d+\.\d*$", t):
        return f'CobolRuntime.toNum("{t}")'

    return t

# ---------------------------------------------------------------------------
# Value resolution (Java)
# ---------------------------------------------------------------------------


def _resolve_value_java(token: str) -> str:
    """Resolve a token to a Java expression string."""
    upper = token.upper()

    # Figurative constants
    if upper in _FIGURATIVE_JAVA:
        return _FIGURATIVE_JAVA[upper]

    # CICS AID key constants
    if upper in _CICS_AID_KEYS:
        return f'"{upper}"'

    # DFHRESP(...)
    m = re.match(r"DFHRESP\((\w+)\)", token, re.IGNORECASE)
    if m:
        code = m.group(1).upper()
        return _DFHRESP.get(code, f'"{code}"')

    # Quoted string -- convert single-quoted COBOL to double-quoted Java
    if token.startswith("'") and token.endswith("'"):
        inner = token[1:-1]
        return f'"{inner}"'

    # Numeric literal
    if re.match(r"^[+-]?\d+\.?\d*$", token):
        return _java_numeric_literal(token)

    # Variable reference
    return f'state.get("{token.upper()}")'


def _is_numeric_literal_java(resolved: str) -> bool:
    """Check if a resolved Java expression is a numeric literal."""
    try:
        float(resolved)
        return True
    except (ValueError, TypeError):
        return False


def _negate_op(op: str) -> str:
    """Return the negated comparison operator."""
    return {
        "==": "!=",
        "!=": "==",
        ">": "<=",
        "<": ">=",
        ">=": "<",
        "<=": ">",
    }.get(op, f"!{op}")


def _is_string_expr(resolved: str) -> bool:
    """Check whether a resolved value is a string expression (not numeric).

    Returns True for state.get(...), quoted strings, figurative string
    constants.  Returns False for numeric literals.
    """
    if _is_numeric_literal_java(resolved):
        return False
    return True


# ---------------------------------------------------------------------------
# Java equality / inequality helpers
# ---------------------------------------------------------------------------


def _java_eq(lhs: str, rhs: str) -> str:
    """Build a Java equality expression, using Objects.equals for strings.

    When one operand is a numeric literal, coerce the other side via
    ``CobolRuntime.toNum(...)`` so a COBOL ``IF X = 0`` matches whether
    ``X`` is stored in ``ProgramState`` as a String (``"0"``, ``"00"``,
    ``" "``) or a numeric (Integer/Long/BigDecimal). Mirrors how the
    Python codegen wraps both sides in ``_to_num`` for var-vs-literal
    numeric comparisons.
    """
    l_num = _is_numeric_literal_java(lhs)
    r_num = _is_numeric_literal_java(rhs)
    if l_num and r_num:
        return f"{lhs} == {rhs}"
    if l_num:
        return f"{lhs} == CobolRuntime.toNum({rhs})"
    if r_num:
        return f"CobolRuntime.toNum({lhs}) == {rhs}"
    return f'java.util.Objects.equals({lhs}, {rhs})'


def _java_neq(lhs: str, rhs: str) -> str:
    """Build a Java inequality expression. See :func:`_java_eq` for the
    var-vs-numeric-literal coercion rationale."""
    l_num = _is_numeric_literal_java(lhs)
    r_num = _is_numeric_literal_java(rhs)
    if l_num and r_num:
        return f"{lhs} != {rhs}"
    if l_num:
        return f"{lhs} != CobolRuntime.toNum({rhs})"
    if r_num:
        return f"CobolRuntime.toNum({lhs}) != {rhs}"
    return f'!java.util.Objects.equals({lhs}, {rhs})'


# ---------------------------------------------------------------------------
# Recursive descent parser -- Java output
# ---------------------------------------------------------------------------


class _JavaParser:
    """Recursive descent parser for COBOL conditions, emitting Java."""

    def __init__(self, tokens: list[str]):
        self.tokens = tokens
        self.pos = 0
        self._last_subject: str | None = None

    # -- Scanner helpers --------------------------------------------------

    def peek(self, offset: int = 0) -> str | None:
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

    def consume(self, *values: str) -> str | None:
        if self.match(*values):
            return self.advance()
        return None

    # -- Entry point ------------------------------------------------------

    def parse(self) -> str:
        return self._or_expr()

    # -- Grammar rules ----------------------------------------------------

    def _or_expr(self) -> str:
        left = self._and_expr()
        while self.match("OR"):
            next1 = self.peek(1)
            next2 = self.peek(2)
            # Implied-subject: OR NOT <op> val
            if (next1 and next1.upper() == "NOT"
                    and next2 and next2.upper() in (
                        "=", "EQUAL", "GREATER", "LESS", ">", "<", ">=", "<=")):
                if self._last_subject:
                    self.advance()  # skip OR
                    self.advance()  # skip NOT
                    op = self._parse_operator()
                    if op:
                        rhs_token = self._primary_token()
                        if rhs_token:
                            rhs = _resolve_value_java(rhs_token)
                            neg_op = _negate_op(op)
                            subj = self._last_subject
                            expr = self._build_cmp(subj, neg_op, rhs)
                            left = f"({left}) || ({expr})"
                            continue
            # Implied-subject: OR <op> val
            elif (next1 and next1.upper() in (
                    "=", "EQUAL", "GREATER", "LESS", ">", "<", ">=", "<=")):
                if self._last_subject:
                    self.advance()  # skip OR
                    op = self._parse_operator()
                    if op:
                        rhs_token = self._primary_token()
                        if rhs_token:
                            rhs = _resolve_value_java(rhs_token)
                            subj = self._last_subject
                            expr = self._build_cmp(subj, op, rhs)
                            left = f"({left}) || ({expr})"
                            continue
            self.advance()  # skip OR
            right = self._and_expr()
            left = f"({left}) || ({right})"
        return left

    def _and_expr(self) -> str:
        left = self._not_expr()
        while self.match("AND"):
            next1 = self.peek(1)
            next2 = self.peek(2)
            # Implied-subject: AND NOT <op> val
            if (next1 and next1.upper() == "NOT"
                    and next2 and next2.upper() in (
                        "=", "EQUAL", "GREATER", "LESS", ">", "<", ">=", "<=")):
                if self._last_subject:
                    self.advance()  # skip AND
                    self.advance()  # skip NOT
                    op = self._parse_operator()
                    if op:
                        rhs_token = self._primary_token()
                        if rhs_token:
                            rhs = _resolve_value_java(rhs_token)
                            neg_op = _negate_op(op)
                            subj = self._last_subject
                            expr = self._build_cmp(subj, neg_op, rhs)
                            left = f"({left}) && ({expr})"
                            continue
            # Implied-subject: AND <op> val
            elif (next1 and next1.upper() in (
                    "=", "EQUAL", "GREATER", "LESS", ">", "<", ">=", "<=")):
                if self._last_subject:
                    self.advance()  # skip AND
                    op = self._parse_operator()
                    if op:
                        rhs_token = self._primary_token()
                        if rhs_token:
                            rhs = _resolve_value_java(rhs_token)
                            subj = self._last_subject
                            expr = self._build_cmp(subj, op, rhs)
                            left = f"({left}) && ({expr})"
                            continue
            self.advance()  # skip AND
            right = self._not_expr()
            left = f"({left}) && ({right})"
        return left

    def _not_expr(self) -> str:
        if self.match("NOT"):
            next_t = self.peek(1)
            if next_t and next_t.upper() in (
                    "=", "EQUAL", "GREATER", "LESS", ">", "<", ">=", "<="):
                return self._comparison()
            self.advance()
            inner = self._not_expr()
            return f"!({inner})"
        return self._comparison()

    def _comparison(self) -> str:
        lhs_token = self._primary_token()
        if lhs_token is None:
            return "true"

        lhs = _resolve_value_java(lhs_token)
        self._last_subject = lhs

        # IS NUMERIC / IS NOT NUMERIC / IS <op>
        if self.match("IS"):
            self.advance()
            if self.match("NOT"):
                self.advance()
                if self.match("NUMERIC"):
                    self.advance()
                    return f"!CobolRuntime.isNumeric({lhs})"
                # IS NOT <op>
                op = self._parse_operator()
                if op is not None:
                    rhs_token = self._primary_token()
                    if rhs_token is None:
                        return f"!CobolRuntime.isTruthy({lhs})"
                    rhs = _resolve_value_java(rhs_token)
                    neg_op = _negate_op(op)
                    return self._build_cmp(lhs, neg_op, rhs)
                return f"!CobolRuntime.isTruthy({lhs})"
            if self.match("NUMERIC"):
                self.advance()
                return f"CobolRuntime.isNumeric({lhs})"
            # IS GREATER/LESS/EQUAL -- fall through
            if (self.peek() and self.peek().upper() in (
                    "GREATER", "LESS", "EQUAL", ">", "<", ">=", "<=", "=")):
                pass
            else:
                return f"CobolRuntime.isTruthy({lhs})"

        # Comparison operators. COBOL allows the IS keyword to be omitted,
        # so ``IO-STATUS NUMERIC`` / ``IO-STATUS NOT NUMERIC`` are both valid
        # and must be recognised here (the IS-prefixed form is handled above).
        negated = False
        if self.match("NOT"):
            negated = True
            self.advance()

        if self.match("NUMERIC"):
            self.advance()
            if negated:
                return f"!CobolRuntime.isNumeric({lhs})"
            return f"CobolRuntime.isNumeric({lhs})"

        op = self._parse_operator()
        if op is None:
            # Bare identifier -> truthiness check
            if negated:
                return f"!CobolRuntime.isTruthy({lhs})"
            return f"CobolRuntime.isTruthy({lhs})"

        rhs_token = self._primary_token()
        if rhs_token is None:
            if negated:
                return f"!CobolRuntime.isTruthy({lhs})"
            return f"CobolRuntime.isTruthy({lhs})"

        rhs = _resolve_value_java(rhs_token)

        # Multi-value: X = A OR B  or  X NOT EQUAL TO A AND B
        values = [rhs]
        while not self.at_end():
            if self.match("OR"):
                next_t = self.peek(1)
                if next_t and _looks_like_bare_value(next_t):
                    saved = self.pos
                    self.advance()  # skip OR
                    val_token = self.peek()
                    after_val = self.peek(1)
                    if (after_val and after_val.upper() in (
                            "=", ">", "<", ">=", "<=",
                            "NOT", "IS", "EQUAL", "GREATER", "LESS")):
                        self.pos = saved
                        break
                    if val_token:
                        self.advance()
                        values.append(_resolve_value_java(val_token))
                    else:
                        self.pos = saved
                        break
                else:
                    break
            elif self.match("AND") and negated:
                next_t = self.peek(1)
                if next_t and _looks_like_bare_value(next_t):
                    after_val = self.peek(2)
                    if (after_val and after_val.upper() in (
                            "=", ">", "<", ">=", "<=",
                            "NOT", "IS", "EQUAL")):
                        break
                    self.advance()  # skip AND
                    val_token = self.advance()
                    values.append(_resolve_value_java(val_token))
                else:
                    break
            else:
                break

        # Determine effective operator
        if negated:
            eff_op = _negate_op(op)
        else:
            eff_op = op

        # Numeric coercion for ordering comparisons
        if eff_op in ("<", ">", "<=", ">="):
            if all(_is_numeric_literal_java(v) for v in values):
                lhs = f"CobolRuntime.toNum({lhs})"
            elif len(values) == 1 and not _is_numeric_literal_java(values[0]):
                lhs = f"CobolRuntime.toNum({lhs})"
                values = [f"CobolRuntime.toNum({values[0]})"]

        if len(values) == 1:
            return self._build_cmp_raw(lhs, eff_op, values[0])
        else:
            # Multi-value
            vals_str = ", ".join(values)
            if negated:
                return f"!java.util.List.of({vals_str}).contains({lhs})"
            else:
                return f"java.util.List.of({vals_str}).contains({lhs})"

    # -- Operator parsing -------------------------------------------------

    def _parse_operator(self) -> str | None:
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
            if self.consume("OR"):
                self.consume("EQUAL")
                self.consume("TO")
                return ">="
            return ">"

        if upper == "LESS":
            self.advance()
            self.consume("THAN")
            if self.consume("OR"):
                self.consume("EQUAL")
                self.consume("TO")
                return "<="
            return "<"

        return None

    def _primary_token(self) -> str | None:
        if self.at_end():
            return None
        t = self.peek()
        if t and t.upper() in ("AND", "OR"):
            return None
        if t and t.upper() == "NOT":
            next_t = self.peek(1)
            if next_t and next_t.upper() in (
                    "=", "EQUAL", "GREATER", "LESS", ">", "<", ">=", "<="):
                return None
            return None
        if t and _is_value_token(t):
            self.advance()
            return t
        return None

    # -- Expression builders ----------------------------------------------

    def _build_cmp(self, lhs: str, op: str, rhs: str) -> str:
        """Build a comparison, applying numeric coercion for ordering ops."""
        if op in ("<", ">", "<=", ">="):
            if _is_numeric_literal_java(rhs):
                lhs = f"CobolRuntime.toNum({lhs})"
            else:
                lhs = f"CobolRuntime.toNum({lhs})"
                rhs = f"CobolRuntime.toNum({rhs})"
        return self._build_cmp_raw(lhs, op, rhs)

    @staticmethod
    def _build_cmp_raw(lhs: str, op: str, rhs: str) -> str:
        """Build a comparison expression using the appropriate Java idiom."""
        if op == "==":
            return _java_eq(lhs, rhs)
        if op == "!=":
            return _java_neq(lhs, rhs)
        # Ordering operators (<, >, <=, >=) pass through directly
        return f"{lhs} {op} {rhs}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def cobol_condition_to_java(
    condition_text: str,
    level_88_map: dict[str, tuple[str, object]] | None = None,
) -> str:
    """Convert a COBOL condition string to a Java boolean expression.

    When ``level_88_map`` is supplied, bare references to 88-level
    condition-names (e.g. ``IF APPL-AOK`` where ``88 APPL-AOK VALUE 0``
    is defined under ``APPL-RESULT``) are rewritten to their parent-value
    comparison: ``CobolRuntime.toNum(state.get("APPL-RESULT")) == 0`` for
    numeric parents, or ``state.get("APPL-RESULT").equals("…")`` for
    alphanumeric parents. Mirrors :func:`specter.code_generator._rewrite_88_level_conditions`.

    Examples::

        >>> cobol_condition_to_java("WS-STATUS = SPACES OR '00'")
        'java.util.List.of(" ", "00").contains(state.get("WS-STATUS"))'

        >>> cobol_condition_to_java("ERR-FLG-ON")
        'CobolRuntime.isTruthy(state.get("ERR-FLG-ON"))'

        >>> cobol_condition_to_java("APPL-AOK", {"APPL-AOK": ("APPL-RESULT", 0)})
        'CobolRuntime.toNum(state.get("APPL-RESULT")) == 0'
    """
    text = condition_text.strip()
    if not text:
        return "true"

    # Strip UNTIL prefix
    if text.upper().startswith("UNTIL "):
        text = text[6:].strip()

    # Strip OF qualifications: "FIELD OF RECORD" → "FIELD"
    import re
    text = re.sub(
        r"([A-Z][A-Z0-9-]*)\s+OF\s+[A-Z][A-Z0-9-]*",
        r"\1", text, flags=re.IGNORECASE,
    )

    tokens = _tokenize(text)
    if not tokens:
        return "true"

    parser = _JavaParser(tokens)
    java_cond = parser.parse()
    if level_88_map:
        java_cond = _rewrite_88_level_conditions_java(java_cond, level_88_map)
    return java_cond


# ---------------------------------------------------------------------------
# 88-level condition rewriting (Java)
# ---------------------------------------------------------------------------

# Match either the bare wrapped form ``CobolRuntime.isTruthy(state.get("VAR"))``
# emitted for bare identifiers, or a raw ``state.get("VAR")`` access. Group 1
# is the COBOL variable name in both cases.
_BARE_ISTRUTHY_RE = __import__("re").compile(
    r'CobolRuntime\.isTruthy\(state\.get\("([A-Z][A-Z0-9-]*)"\)\)'
)
_BARE_STATE_GET_RE = __import__("re").compile(
    r'state\.get\("([A-Z][A-Z0-9-]*)"\)'
)


def _rewrite_88_level_conditions_java(
    java_cond: str,
    level_88_map: dict[str, tuple[str, object]],
) -> str:
    """Replace bare 88-level references with parent-value comparisons.

    Handles two source patterns produced by the Java condition parser for
    bare identifiers:

    1. ``CobolRuntime.isTruthy(state.get("APPL-AOK"))`` — the wrap the
       parser uses when an identifier appears without a comparator.
    2. ``state.get("APPL-AOK")`` — left over by other code paths if the
       identifier was already partway through a comparison; only rewritten
       when not adjacent to a comparator (``=``/``!``/``>``/``<``/``.``).
    """
    if not level_88_map:
        return java_cond

    def _emit(parent: str, value: object) -> str:
        if isinstance(value, bool):
            return f'CobolRuntime.isTruthy(state.get("{parent}")) == {str(value).lower()}'
        if isinstance(value, (int, float)):
            return f'CobolRuntime.toNum(state.get("{parent}")) == {value!r}'
        # String/alpha value — escape any embedded double quote.
        s = str(value).replace("\\", "\\\\").replace('"', '\\"')
        return f'java.util.Objects.equals(state.get("{parent}"), "{s}")'

    def _replace_truthy(match):
        child = match.group(1)
        entry = level_88_map.get(child)
        if entry is None:
            return match.group(0)
        parent, value = entry
        return _emit(parent, value)

    out = _BARE_ISTRUTHY_RE.sub(_replace_truthy, java_cond)

    def _replace_bare_get(match):
        child = match.group(1)
        entry = level_88_map.get(child)
        if entry is None:
            return match.group(0)
        # Skip if already adjacent to a comparator/method (already in a
        # comparison or member access — leave the parser's translation alone).
        end = match.end()
        rest = out[end:end + 8].lstrip()
        if rest and rest[0] in ("=", "!", ">", "<", ".", ","):
            return match.group(0)
        parent, value = entry
        return _emit(parent, value)

    out = _BARE_STATE_GET_RE.sub(_replace_bare_get, out)
    return out


def resolve_when_value_java(
    value_text: str,
    is_evaluate_true: bool,
    level_88_map: dict[str, tuple[str, object]] | None = None,
) -> str:
    """Resolve a WHEN value to a Java expression.

    If the EVALUATE subject is TRUE, the WHEN value is a full condition
    and 88-level rewriting is applied via ``level_88_map``. Otherwise the
    value is a literal compared against the subject and the map is unused.
    """
    if is_evaluate_true:
        return cobol_condition_to_java(value_text, level_88_map)
    return _resolve_value_java(value_text)
