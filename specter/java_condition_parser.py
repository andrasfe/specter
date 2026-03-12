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
    """Build a Java equality expression, using Objects.equals for strings."""
    if _is_numeric_literal_java(lhs) and _is_numeric_literal_java(rhs):
        return f"{lhs} == {rhs}"
    return f'java.util.Objects.equals({lhs}, {rhs})'


def _java_neq(lhs: str, rhs: str) -> str:
    """Build a Java inequality expression."""
    if _is_numeric_literal_java(lhs) and _is_numeric_literal_java(rhs):
        return f"{lhs} != {rhs}"
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
                        return f"!({lhs})"
                    rhs = _resolve_value_java(rhs_token)
                    neg_op = _negate_op(op)
                    return self._build_cmp(lhs, neg_op, rhs)
                return f"!({lhs})"
            if self.match("NUMERIC"):
                self.advance()
                return f"CobolRuntime.isNumeric({lhs})"
            # IS GREATER/LESS/EQUAL -- fall through
            if (self.peek() and self.peek().upper() in (
                    "GREATER", "LESS", "EQUAL", ">", "<", ">=", "<=", "=")):
                pass
            else:
                return lhs

        # Comparison operators
        negated = False
        if self.match("NOT"):
            negated = True
            self.advance()

        op = self._parse_operator()
        if op is None:
            # Bare identifier -> truthiness check
            if negated:
                return f"!CobolRuntime.isTruthy({lhs})"
            return f"CobolRuntime.isTruthy({lhs})"

        rhs_token = self._primary_token()
        if rhs_token is None:
            return lhs

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


def cobol_condition_to_java(condition_text: str) -> str:
    """Convert a COBOL condition string to a Java boolean expression.

    Examples::

        >>> cobol_condition_to_java("WS-STATUS = SPACES OR '00'")
        'java.util.List.of(" ", "00").contains(state.get("WS-STATUS"))'

        >>> cobol_condition_to_java("ERR-FLG-ON")
        'CobolRuntime.isTruthy(state.get("ERR-FLG-ON"))'
    """
    text = condition_text.strip()
    if not text:
        return "true"

    # Strip UNTIL prefix
    if text.upper().startswith("UNTIL "):
        text = text[6:].strip()

    tokens = _tokenize(text)
    if not tokens:
        return "true"

    parser = _JavaParser(tokens)
    return parser.parse()


def resolve_when_value_java(value_text: str, is_evaluate_true: bool) -> str:
    """Resolve a WHEN value to a Java expression.

    If the EVALUATE subject is TRUE, the WHEN value is a full condition.
    Otherwise it is a simple value to compare against the subject.
    """
    if is_evaluate_true:
        return cobol_condition_to_java(value_text)
    return _resolve_value_java(value_text)
