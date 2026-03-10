"""Convert COBOL condition text into Python expression strings.

Handles comparisons, figurative constants, boolean flags, IS NUMERIC,
multi-value OR, logical AND/OR, DFHRESP codes, and EVALUATE/WHEN patterns.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Figurative constants
# ---------------------------------------------------------------------------

_FIGURATIVE = {
    "SPACES": "' '",
    "SPACE": "' '",
    "LOW-VALUES": "''",
    "LOW-VALUE": "''",
    "HIGH-VALUES": "'\\xff'",
    "HIGH-VALUE": "'\\xff'",
    "ZEROS": "0",
    "ZERO": "0",
    "ZEROES": "0",
}

# DFHRESP codes
_DFHRESP = {
    "NORMAL": "0",
    "ERROR": "1",
    "TERMIDERR": "11",
    "FILENOTFOUND": "12",
    "NOTFND": "13",
    "DUPREC": "14",
    "DUPKEY": "15",
    "INVREQ": "16",
    "IOERR": "17",
    "NOSPACE": "18",
    "NOTOPEN": "19",
    "ENDFILE": "20",
    "ILLOGIC": "21",
    "LENGERR": "22",
    "QZERO": "23",
    "SIGNAL": "24",
    "QBUSY": "25",
    "ITEMERR": "26",
    "PGMIDERR": "27",
    "TRANSIDERR": "28",
    "ENDDATA": "29",
    "INVTSREQ": "30",
    "EXPIRED": "31",
    "MAPFAIL": "36",
    "ENQBUSY": "55",
    "DISABLED": "84",
    "NOTAUTH": "70",
}

# CICS AID key constants — resolve as string literals
_CICS_AID_KEYS = frozenset({
    "DFHENTER", "DFHCLEAR",
    "DFHPF1", "DFHPF2", "DFHPF3", "DFHPF4", "DFHPF5", "DFHPF6",
    "DFHPF7", "DFHPF8", "DFHPF9", "DFHPF10", "DFHPF11", "DFHPF12",
    "DFHPF13", "DFHPF14", "DFHPF15", "DFHPF16", "DFHPF17", "DFHPF18",
    "DFHPF19", "DFHPF20", "DFHPF21", "DFHPF22", "DFHPF23", "DFHPF24",
    "DFHPA1", "DFHPA2", "DFHPA3",
})

# Comparison operator words
_CMP_WORDS = frozenset({
    "=", ">", "<", ">=", "<=",
    "EQUAL", "GREATER", "LESS", "THAN", "TO",
})

# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

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


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text)


# ---------------------------------------------------------------------------
# Value resolution
# ---------------------------------------------------------------------------

def _resolve_value(token: str) -> str:
    """Resolve a token to a Python expression string."""
    upper = token.upper()

    # Figurative constants
    if upper in _FIGURATIVE:
        return _FIGURATIVE[upper]

    # CICS AID key constants
    if upper in _CICS_AID_KEYS:
        return f"'{upper}'"

    # DFHRESP(...)
    m = re.match(r"DFHRESP\((\w+)\)", token, re.IGNORECASE)
    if m:
        code = m.group(1).upper()
        return _DFHRESP.get(code, f"'{code}'")

    # Quoted string
    if token.startswith("'") and token.endswith("'"):
        return token

    # Numeric literal — strip leading sign/zeros to avoid Python syntax errors
    if re.match(r"^[+-]?\d+\.?\d*$", token):
        return str(int(token)) if "." not in token else str(float(token))

    # Variable reference (with optional subscript)
    return f"state['{token.upper()}']"


def _is_value_token(token: str) -> bool:
    """Check if a token looks like a value (not a logical keyword or operator)."""
    upper = token.upper()
    if upper in ("AND", "OR", "NOT", "IS", "NUMERIC", "EQUAL", "THAN", "TO",
                 "GREATER", "LESS", "OF"):
        return False
    if upper in _CMP_WORDS:
        return False
    return True


def _is_numeric_literal(resolved: str) -> bool:
    """Check if a resolved Python expression is a numeric literal."""
    try:
        float(resolved)
        return True
    except (ValueError, TypeError):
        return False


def _looks_like_bare_value(token: str) -> bool:
    """Check if a token is a simple value (literal, figurative constant, or variable)."""
    upper = token.upper()
    if upper in _FIGURATIVE:
        return True
    if token.startswith("'"):
        return True
    if re.match(r"^-?\d+\.?\d*$", token):
        return True
    if re.match(r"DFHRESP\(", token, re.IGNORECASE):
        return True
    # Variable names
    if re.match(r"^[A-Za-z][A-Za-z0-9_-]*(\([^)]*\))?$", token):
        return True
    return False


# ---------------------------------------------------------------------------
# Recursive descent parser
# ---------------------------------------------------------------------------

class _Parser:
    """Recursive descent parser for COBOL conditions."""

    def __init__(self, tokens: list[str]):
        self.tokens = tokens
        self.pos = 0
        self._last_subject: str | None = None  # Track subject for implied-subject continuations

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

    def parse(self) -> str:
        result = self._or_expr()
        return result

    def _or_expr(self) -> str:
        left = self._and_expr()
        while self.match("OR"):
            # Check for implied-subject continuation: OR NOT = val / OR = val
            next1 = self.peek(1)
            next2 = self.peek(2)
            if next1 and next1.upper() == "NOT" and next2 and next2.upper() in ("=", "EQUAL", "GREATER", "LESS", ">", "<", ">=", "<="):
                if self._last_subject:
                    self.advance()  # skip OR
                    self.advance()  # skip NOT
                    op = self._parse_operator()
                    if op:
                        rhs_token = self._primary_token()
                        if rhs_token:
                            rhs = _resolve_value(rhs_token)
                            py_op = _negate_op(op)
                            subj = self._last_subject
                            if py_op in ("<", ">", "<=", ">="):
                                subj = f"_to_num({subj})"
                                rhs = f"_to_num({rhs})"
                            left = f"({left}) or ({subj} {py_op} {rhs})"
                            continue
            elif next1 and next1.upper() in ("=", "EQUAL", "GREATER", "LESS", ">", "<", ">=", "<="):
                if self._last_subject:
                    self.advance()  # skip OR
                    op = self._parse_operator()
                    if op:
                        rhs_token = self._primary_token()
                        if rhs_token:
                            rhs = _resolve_value(rhs_token)
                            subj = self._last_subject
                            if op in ("<", ">", "<=", ">="):
                                subj = f"_to_num({subj})"
                                rhs = f"_to_num({rhs})"
                            left = f"({left}) or ({subj} {op} {rhs})"
                            continue
            self.advance()
            right = self._and_expr()
            left = f"({left}) or ({right})"
        return left

    def _and_expr(self) -> str:
        left = self._not_expr()
        while self.match("AND"):
            # Check for implied-subject continuation: AND NOT = val / AND = val
            # In COBOL, "X NOT = A AND NOT = B" means X != A AND X != B
            next1 = self.peek(1)
            next2 = self.peek(2)
            if next1 and next1.upper() == "NOT" and next2 and next2.upper() in ("=", "EQUAL", "GREATER", "LESS", ">", "<", ">=", "<="):
                if self._last_subject:
                    self.advance()  # skip AND
                    self.advance()  # skip NOT
                    op = self._parse_operator()
                    if op:
                        rhs_token = self._primary_token()
                        if rhs_token:
                            rhs = _resolve_value(rhs_token)
                            py_op = _negate_op(op)
                            subj = self._last_subject
                            if py_op in ("<", ">", "<=", ">="):
                                subj = f"_to_num({subj})"
                                rhs = f"_to_num({rhs})"
                            left = f"({left}) and ({subj} {py_op} {rhs})"
                            continue
            elif next1 and next1.upper() in ("=", "EQUAL", "GREATER", "LESS", ">", "<", ">=", "<="):
                if self._last_subject:
                    self.advance()  # skip AND
                    op = self._parse_operator()
                    if op:
                        rhs_token = self._primary_token()
                        if rhs_token:
                            rhs = _resolve_value(rhs_token)
                            subj = self._last_subject
                            if op in ("<", ">", "<=", ">="):
                                subj = f"_to_num({subj})"
                                rhs = f"_to_num({rhs})"
                            left = f"({left}) and ({subj} {op} {rhs})"
                            continue
            self.advance()
            right = self._not_expr()
            left = f"({left}) and ({right})"
        return left

    def _not_expr(self) -> str:
        if self.match("NOT"):
            # Peek: is this "NOT =" or "NOT EQUAL"? If so, it's a comparison
            next_t = self.peek(1)
            if next_t and next_t.upper() in ("=", "EQUAL", "GREATER", "LESS", ">", "<", ">=", "<="):
                return self._comparison()
            self.advance()
            inner = self._not_expr()
            return f"not ({inner})"
        return self._comparison()

    def _comparison(self) -> str:
        # Parse left-hand side
        lhs_token = self._primary_token()
        if lhs_token is None:
            return "True"

        lhs = _resolve_value(lhs_token)
        # Save subject for implied-subject continuations (AND NOT = val)
        self._last_subject = lhs

        # Check for IS NUMERIC / IS NOT NUMERIC / IS GREATER/LESS/EQUAL
        if self.match("IS"):
            self.advance()
            if self.match("NOT"):
                self.advance()
                if self.match("NUMERIC"):
                    self.advance()
                    return f"not _is_numeric({lhs})"
                # IS NOT <operator> — fall through to operator parsing with negation
                negated = True
                op = self._parse_operator()
                if op is not None:
                    # Continue to rhs parsing below
                    rhs_token = self._primary_token()
                    if rhs_token is None:
                        return f"not ({lhs})"
                    rhs = _resolve_value(rhs_token)
                    py_op = _negate_op(op)
                    if py_op in ("<", ">", "<=", ">="):
                        lhs = f"_to_num({lhs})"
                        rhs = f"_to_num({rhs})"
                    return f"{lhs} {py_op} {rhs}"
                return f"not ({lhs})"
            if self.match("NUMERIC"):
                self.advance()
                return f"_is_numeric({lhs})"
            # IS GREATER/LESS/EQUAL — fall through to operator parsing
            if self.peek() and self.peek().upper() in ("GREATER", "LESS", "EQUAL", ">", "<", ">=", "<=", "="):
                pass  # fall through to operator parsing below
            else:
                return lhs

        # Check for comparison operators
        negated = False
        if self.match("NOT"):
            negated = True
            self.advance()

        op = self._parse_operator()
        if op is None:
            # Bare identifier = boolean flag
            if negated:
                return f"not ({lhs})"
            return lhs

        # Parse right-hand side value
        rhs_token = self._primary_token()
        if rhs_token is None:
            return lhs

        rhs = _resolve_value(rhs_token)

        # Check for multi-value: "X = A OR B" or "X NOT EQUAL TO A AND B"
        values = [rhs]
        while not self.at_end():
            if self.match("OR"):
                # Peek: is the thing after OR a simple value (multi-value)
                # or does it look like a full condition (logical OR)?
                next_t = self.peek(1)
                if next_t and _looks_like_bare_value(next_t):
                    # Check if the token AFTER the value starts a new comparison
                    # If next_t is followed by an operator, it's a full condition
                    saved = self.pos
                    self.advance()  # skip OR
                    val_token = self.peek()
                    after_val = self.peek(1)
                    if after_val and after_val.upper() in ("=", ">", "<", ">=", "<=",
                                                            "NOT", "IS", "EQUAL",
                                                            "GREATER", "LESS"):
                        # This is a logical OR, not multi-value
                        self.pos = saved
                        break
                    if val_token:
                        self.advance()  # consume value
                        values.append(_resolve_value(val_token))
                    else:
                        self.pos = saved
                        break
                else:
                    break
            elif self.match("AND") and negated:
                # "NOT EQUAL TO A AND B" means "not in (A, B)"
                next_t = self.peek(1)
                if next_t and _looks_like_bare_value(next_t):
                    after_val = self.peek(2)
                    if after_val and after_val.upper() in ("=", ">", "<", ">=", "<=",
                                                            "NOT", "IS", "EQUAL"):
                        break
                    self.advance()  # skip AND
                    val_token = self.advance()
                    values.append(_resolve_value(val_token))
                else:
                    break
            else:
                break

        # Build expression
        if negated:
            py_op = _negate_op(op)
        else:
            py_op = op

        # For ordering comparisons, coerce both sides to avoid
        # TypeError (str vs int) at runtime.
        if py_op in ("<", ">", "<=", ">="):
            if all(_is_numeric_literal(v) for v in values):
                lhs = f"_to_num({lhs})"
            elif len(values) == 1 and not _is_numeric_literal(values[0]):
                # Variable-to-variable comparison: wrap both
                lhs = f"_to_num({lhs})"
                values = [f"_to_num({values[0]})"]

        if len(values) == 1:
            return f"{lhs} {py_op} {values[0]}"
        else:
            vals_str = ", ".join(values)
            if negated:
                return f"{lhs} not in ({vals_str})"
            else:
                return f"{lhs} in ({vals_str})"

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
            return ">"

        if upper == "LESS":
            self.advance()
            self.consume("THAN")
            return "<"

        return None

    def _primary_token(self) -> str | None:
        if self.at_end():
            return None
        t = self.peek()
        if t and t.upper() in ("AND", "OR"):
            return None
        if t and t.upper() in ("NOT",):
            # Peek further: NOT followed by operator means this is a negated comparison
            next_t = self.peek(1)
            if next_t and next_t.upper() in ("=", "EQUAL", "GREATER", "LESS", ">", "<", ">=", "<="):
                return None
            # "NOT X" at primary level means boolean negation—handled upstream
            return None
        if t and _is_value_token(t):
            self.advance()
            return t
        return None


def _negate_op(op: str) -> str:
    return {
        "==": "!=",
        "!=": "==",
        ">": "<=",
        "<": ">=",
        ">=": "<",
        "<=": ">",
    }.get(op, f"not {op}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def cobol_condition_to_python(condition_text: str) -> str:
    """Convert a COBOL condition string to a Python expression.

    Examples::

        >>> cobol_condition_to_python("WS-STATUS = SPACES OR '00'")
        "state['WS-STATUS'] in (' ', '00')"

        >>> cobol_condition_to_python("ERR-FLG-ON")
        "state['ERR-FLG-ON']"
    """
    text = condition_text.strip()
    if not text:
        return "True"

    # Strip UNTIL prefix
    if text.upper().startswith("UNTIL "):
        text = text[6:].strip()

    tokens = _tokenize(text)
    if not tokens:
        return "True"

    parser = _Parser(tokens)
    return parser.parse()


def parse_when_value(text: str) -> tuple[str, bool]:
    """Parse a WHEN node's text field.

    Returns (value_expr, is_other) where value_expr is a Python expression
    and is_other is True for WHEN OTHER.
    """
    stripped = text.strip()

    # "WHEN OTHER"
    if re.match(r"WHEN\s+OTHER", stripped, re.IGNORECASE):
        return "", True

    # "WHEN WHEN value" — double WHEN from AST format
    m = re.match(r"WHEN\s+WHEN\s+(.+)", stripped, re.IGNORECASE)
    if m:
        value_text = m.group(1).strip()
        # The value might be a condition (for EVALUATE TRUE) or a literal
        return value_text, False

    # "WHEN value"
    m = re.match(r"WHEN\s+(.+)", stripped, re.IGNORECASE)
    if m:
        value_text = m.group(1).strip()
        return value_text, False

    return stripped, False


def resolve_when_value(value_text: str, is_evaluate_true: bool) -> str:
    """Resolve a WHEN value to a Python expression.

    If the EVALUATE subject is TRUE, the WHEN value is a full condition.
    Otherwise it's a simple value to compare against the subject.
    """
    if is_evaluate_true:
        return cobol_condition_to_python(value_text)
    return _resolve_value(value_text)
