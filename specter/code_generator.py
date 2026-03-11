"""Generate executable Python source code from a COBOL Program AST."""

from __future__ import annotations

import re
from textwrap import indent

from .condition_parser import (
    cobol_condition_to_python,
    parse_when_value,
    resolve_when_value,
)
from .models import Program, Statement
from .variable_extractor import VariableReport, extract_variables

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FIGURATIVE_SOURCES = {
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


def _strip_cobol_comments(text: str) -> str:
    """Strip COBOL inline comments (*> ...) from text.

    In merged AST text, *> segments mark old/commented-out code interleaved
    with the active code.  The active code is: everything before the first *>
    plus relevant segments after *> markers.

    Strategy: keep first part + concatenate text from each *> segment that
    contains COBOL keywords (TO, FROM, BY, GIVING, INTO, UNTIL) or looks
    like code, stripping the leading comment prose from each segment.
    """
    if "*>" not in text:
        return text.strip()

    parts = text.split("*>")
    first = parts[0].strip()

    # From each subsequent segment, try to extract real code after comment prose.
    # Comment prose typically doesn't contain COBOL keywords at word boundaries.
    _KW = re.compile(
        r"\b(TO|FROM|BY|GIVING|INTO|UNTIL|REMAINDER|ROUNDED|THRU|REPLACING)\b",
        re.IGNORECASE,
    )
    code_parts = [first]
    for seg in parts[1:]:
        seg = seg.strip()
        # If segment contains a COBOL keyword, keep from the first keyword onward
        m = _KW.search(seg)
        if m:
            code_parts.append(seg[m.start():])
        elif ". " in seg:
            # Old code ending with period, then new code starts
            after_period = seg.split(". ", 1)[1].strip()
            if after_period and re.match(r"[A-Z0-9]", after_period):
                code_parts.append(after_period)
        elif re.match(r"[A-Z][A-Z0-9-]*\s*[(/+*=-]", seg, re.IGNORECASE):
            # Looks like a COBOL expression (variable followed by operator/paren)
            code_parts.append(seg)
        # else: pure comment prose, discard

    combined = " ".join(code_parts)
    return " ".join(combined.split()).strip()


def _strip_comments_arithmetic(text: str) -> str:
    """Strip *> comments from a COBOL arithmetic expression using syntax awareness.

    In merged AST text, *> starts an inline comment that runs to end-of-line.
    Since line boundaries are lost, we infer them by recognizing that valid
    continuation of an arithmetic expression must start with an operator,
    opening paren, or be preceded by an operator.
    """
    if "*>" not in text:
        return text.strip()
    parts = text.split("*>")
    # First part is always code
    result = parts[0].strip()
    for seg in parts[1:]:
        seg = seg.strip()
        if not seg:
            continue
        # Scan for the first token that could be a valid arithmetic continuation:
        # an operator (+, -, *, /), opening paren, or a variable/number that
        # follows the pattern of a COBOL arithmetic token
        # Strategy: find the first arithmetic operator at word boundary
        m = re.search(r'(?:^|\s)([+\-*/])\s+([A-Z0-9])', seg, re.IGNORECASE)
        if m:
            # Found an operator — keep from there
            result += " " + seg[m.start():].strip()
            continue
        # Check if segment starts with operator
        if seg and seg[0] in '+-*/(':
            result += " " + seg
            continue
        # Check if segment starts with a paren-close (continuation of grouped expr)
        if seg and seg[0] == ')':
            result += " " + seg
            continue
        # If result ends with an operator, look for a variable/number after period or space
        if result and result.rstrip()[-1:] in '+-*/':
            # Pattern: *> OLD-CODE. NEW-CODE or *> OLD-CODE NEW-CODE
            # Look for a COBOL variable after a period-space separator
            m2 = re.search(r'\.\s+([A-Z][A-Z0-9-]*(?:\s*\([^)]*\))?)', seg, re.IGNORECASE)
            if m2:
                result += " " + m2.group(1)
                continue
            # Look for last COBOL variable/number in the segment (likely the replacement)
            tokens = re.findall(r'[A-Z][A-Z0-9-]*(?:\s*\([^)]*\))?', seg, re.IGNORECASE)
            if tokens:
                result += " " + tokens[-1]
                continue
    return " ".join(result.split()).strip()


def _tokenize_cobol_vars(text: str) -> list[str]:
    """Tokenize a string of COBOL variable references, respecting subscripts.

    'VAR1 VAR2(1) VAR3 (I J)' → ['VAR1', 'VAR2(1)', 'VAR3 (I J)']
    Also strips *> comments and trailing periods.
    """
    text = _strip_cobol_comments(text).rstrip(".")
    tokens = []
    # Match: identifier optionally followed by (possibly space-separated) subscript in parens
    for m in re.finditer(
        r"[A-Z0-9][A-Z0-9-]*(?:\s*\([^)]*\))?",
        text, re.IGNORECASE,
    ):
        tokens.append(m.group(0).strip())
    return tokens


def _var_name(token: str) -> str:
    """Extract the base variable name from a token, stripping subscripts."""
    return re.sub(r"\s*\(.*\)", "", token).upper().strip("'\".,;:")


def _sanitize_name(name: str) -> str:
    """Convert a COBOL paragraph name to a valid Python function name."""
    cleaned = re.sub(r"[^A-Z0-9_]", "_", name.upper().replace("-", "_").replace(".", "_"))
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return "para_" + cleaned


def _sq(name: str) -> str:
    """Escape a variable name for safe use inside single-quoted Python strings."""
    return name.replace("'", "\\'")


def _vk(name: str) -> str:
    """Clean a name for use as a state dict key (strip stray quotes/punctuation)."""
    return name.upper().strip("'\".,;:")


def _oneline(text: str, limit: int = 60) -> str:
    """Collapse text to a single line, truncated for use in generated comments."""
    return " ".join(text.split())[:limit]


def _resolve_source(source: str) -> str:
    """Resolve a MOVE source to a Python expression."""
    s = source.strip()

    # Strip leading ALL (MOVE ALL 'X' etc.)
    s = re.sub(r"^ALL\s+", "", s, flags=re.IGNORECASE).strip()

    # Figurative constant
    upper = s.upper()
    if upper in _FIGURATIVE_SOURCES:
        return str(_FIGURATIVE_SOURCES[upper])

    # Quoted string literal
    if s.startswith("'") and s.endswith("'"):
        return s

    # Numeric literal — strip leading zeros
    if re.match(r"^-?\d+\.?\d*$", s):
        return str(int(s)) if "." not in s else str(float(s))

    # LENGTH OF variable
    m = re.match(r"LENGTH\s+OF\s+(.+)", s, re.IGNORECASE)
    if m:
        varname = _vk(m.group(1).strip())
        return f"len(str(state.get('{varname}', '')))"

    # Variable with subscript like FOO(1:2)
    m = re.match(r"([A-Z][A-Z0-9-]*)\((\d+):(\d+)\)", s, re.IGNORECASE)
    if m:
        varname = _vk(m.group(1))
        start = int(m.group(2)) - 1  # COBOL is 1-based
        length = int(m.group(3))
        return f"str(state.get('{varname}', ''))[{start}:{start + length}]"

    # Variable reference
    varname = _vk(s)
    return f"state.get('{varname}', '')"


# ---------------------------------------------------------------------------
# Code builder
# ---------------------------------------------------------------------------

class _CodeBuilder:
    """Builds Python source lines with indentation tracking."""

    def __init__(self):
        self.lines: list[str] = []
        self._indent = 0
        self._loop_counter = 0
        self._branch_counter = 0
        self.branch_meta: dict[int, dict] = {}
        self.current_para: str = ""

    def next_branch_id(self) -> int:
        """Return a unique branch ID for instrumentation."""
        self._branch_counter += 1
        return self._branch_counter

    def next_loop_var(self) -> str:
        """Return a unique loop counter variable name."""
        self._loop_counter += 1
        return f"_lc{self._loop_counter}"

    def line(self, text: str):
        self.lines.append("    " * self._indent + text)

    def blank(self):
        self.lines.append("")

    def indent(self):
        self._indent += 1

    def dedent(self):
        self._indent = max(0, self._indent - 1)

    def build(self) -> str:
        return "\n".join(self.lines) + "\n"


# ---------------------------------------------------------------------------
# Statement generators
# ---------------------------------------------------------------------------

def _gen_move(cb: _CodeBuilder, stmt: Statement):
    source = stmt.attributes.get("source", "")
    targets = stmt.attributes.get("targets", "")

    if not source or not targets:
        # Fallback: parse from text
        m = re.search(r"MOVE\s+(.+?)\s+TO\s+(.+)", stmt.text, re.IGNORECASE)
        if m:
            source = m.group(1).strip()
            targets = m.group(2).strip()
        else:
            cb.line(f"pass  # MOVE: {_oneline(stmt.text)}")
            return

    # Detect MOVE ALL 'x' — strip ALL prefix from source if present
    is_move_all = bool(re.search(r"MOVE\s+ALL\s+", stmt.text, re.IGNORECASE))
    if is_move_all:
        source = re.sub(r"^ALL\s+", "", source, flags=re.IGNORECASE).strip()

    resolved = _resolve_source(source)
    for target_tok in _tokenize_cobol_vars(_strip_cobol_comments(targets)):
        target_tok = target_tok.strip().rstrip(".")
        if target_tok:
            tname = _var_name(target_tok)
            # Handle subscript targets
            m = re.match(r"([A-Z][A-Z0-9-]*)\((\d+):(\d+)\)", tname)
            if m:
                varname = m.group(1)
                start = int(m.group(2)) - 1
                length = int(m.group(3))
                cb.line(f"_v = str(state.get('{varname}', ''))")
                cb.line(f"state['{varname}'] = _v[:{start}] + str({resolved})[:{length}] + _v[{start + length}:]")
            elif is_move_all:
                # MOVE ALL 'x' fills target with repeated character
                # Use length of current value (stripped/raw) or default 10
                cb.line(f"_fill = str({resolved})")
                cb.line(f"_cur = str(state.get('{tname}', ''))")
                cb.line(f"_flen = max(len(_cur), 10)")
                cb.line(f"state['{tname}'] = (_fill * _flen)[:_flen]")
            else:
                cb.line(f"state['{tname}'] = {resolved}")


def _gen_compute(cb: _CodeBuilder, stmt: Statement):
    target = stmt.attributes.get("target", "")
    expression = stmt.attributes.get("expression", "")

    if not target or not expression:
        # Fallback: parse from text — support subscripted targets like VAR(1) or VAR (1 2)
        # Also support EQUAL as synonym for = in COMPUTE, and digit-prefixed var names
        _compute_re = re.compile(
            r"COMPUTE\s+([A-Z0-9][A-Z0-9-]*(?:\s*\([^)]*\))?)\s*(?:ROUNDED\s*)?(?:=|EQUAL)\s*(.+)",
            re.IGNORECASE,
        )
        m = _compute_re.search(stmt.text)
        if m:
            raw_target = m.group(1).strip()
            target = re.sub(r"\s*\(.*\)", "", raw_target).upper()
            expression = m.group(2).strip().rstrip(".")
        else:
            cb.line(f"pass  # COMPUTE: {_oneline(stmt.text)}")
            return
    # Strip COBOL inline comments (*> ... to end)
    # Try multiple strategies and pick the first that compiles
    if "*>" in expression:
        candidates = []

        # Strategy 1: _strip_cobol_comments (understands old-code. new-code)
        s1 = _strip_cobol_comments(expression)
        s1 = " ".join(s1.split()).strip().rstrip(".")
        while s1 and s1[-1] in "+-*/":
            s1 = s1[:-1].strip()
        if s1:
            candidates.append(s1)

        # Strategy 2: simple truncation (strip everything after *>)
        s2 = re.sub(r"\*>.*", "", expression)
        s2 = " ".join(s2.split()).strip().rstrip(".")
        while s2 and s2[-1] in "+-*/":
            s2 = s2[:-1].strip()
        if s2 and s2 not in candidates:
            candidates.append(s2)

        # Strategy 3: arithmetic-aware recovery
        s3 = _strip_comments_arithmetic(expression)
        s3 = " ".join(s3.split()).strip().rstrip(".")
        while s3 and s3[-1] in "+-*/":
            s3 = s3[:-1].strip()
        if s3 and s3 not in candidates:
            candidates.append(s3)

        # Strategy 4: for *> OLD-CODE NEW-CODE, strip *> markers then try
        # taking the last N tokens that form a valid expression (new code
        # typically mirrors old code structure)
        bare = re.sub(r"\*>[^*]*?(?=[A-Z0-9(])", "", expression, flags=re.IGNORECASE)
        bare = " ".join(bare.split()).strip().rstrip(".")
        if bare:
            # Try the full bare expression
            if bare not in candidates:
                candidates.append(bare)
            # Try taking the second half (old code replaced by new code)
            tokens = re.findall(r"[A-Z][A-Z0-9-]*(?:\s*\([^)]*\))?|[+\-*/()]|\d+\.?\d*", bare, re.IGNORECASE)
            for split_idx in range(1, len(tokens)):
                half = " ".join(tokens[split_idx:])
                if half and half not in candidates:
                    candidates.append(half)

        # Pick the first candidate that produces a valid Python expression
        expression = ""
        for cand in candidates:
            # Balance parens before testing
            open_c = cand.count("(") - cand.count(")")
            test_expr = cand + ")" * open_c if open_c > 0 else cand
            # Quick variable substitution for compile test
            test_py = re.sub(r"[A-Z_][A-Z0-9_-]*(?:\s*\([^)]*\))?", "0", test_expr, flags=re.IGNORECASE)
            test_py = test_py.replace(")(", ")*(")  # fix adjacent parens
            try:
                compile(test_py, "<test>", "eval")
                expression = cand
                break
            except SyntaxError:
                continue

    if not expression:
        cb.line(f"pass  # COMPUTE: empty expression after comment strip")
        return

    # Balance parentheses — add missing closing parens
    open_count = expression.count("(") - expression.count(")")
    if open_count > 0:
        expression += ")" * open_count

    # Preprocess: resolve complex COBOL constructs to Python snippets,
    # stash them as placeholders so replace_var won't mangle them.
    expr = expression
    _placeholders: dict[str, str] = {}
    _ph_counter = 0

    def _ph(py_code: str) -> str:
        nonlocal _ph_counter
        key = f"__PH{_ph_counter}__"
        _ph_counter += 1
        _placeholders[key] = py_code
        return key

    # LENGTH OF <var>
    expr = re.sub(
        r"LENGTH\s+OF\s+([A-Z][A-Z0-9-]*)",
        lambda m: _ph(f"len(str(state.get('{_vk(m.group(1))}', '')))"),
        expr, flags=re.IGNORECASE,
    )

    # FUNCTION <name>(<balanced-parens>) — handles nested parens properly
    def _extract_function_call(text: str, start: int) -> tuple[str, str, int] | None:
        """Find FUNCTION name(...) starting at `start`. Returns (name, inner, end)."""
        m = re.match(r"FUNCTION\s+([\w-]+)\s*\(", text[start:], re.IGNORECASE)
        if not m:
            return None
        name = m.group(1)
        paren_start = start + m.end() - 1  # index of '('
        depth = 0
        for i in range(paren_start, len(text)):
            if text[i] == "(":
                depth += 1
            elif text[i] == ")":
                depth -= 1
                if depth == 0:
                    inner = text[paren_start + 1:i]
                    return name, inner, i + 1
        return None

    def _resolve_function(text: str) -> str:
        """Resolve all FUNCTION calls in text, innermost first."""
        while True:
            # Find the last FUNCTION keyword (innermost call)
            positions = [m.start() for m in re.finditer(r"FUNCTION\s+", text, re.IGNORECASE)]
            if not positions:
                break
            resolved_any = False
            for pos in reversed(positions):
                result = _extract_function_call(text, pos)
                if not result:
                    continue
                fname, inner, end = result
                upper_fname = fname.upper()
                if "INTEGER-OF-DATE" in upper_fname:
                    inner_var = re.search(r"([A-Z][A-Z0-9-]*)", inner, re.IGNORECASE)
                    varname = inner_var.group(1).upper() if inner_var else "0"
                    replacement = _ph(f"_to_num(state.get('{varname}', 0))")
                elif "DATE-OF-INTEGER" in upper_fname:
                    replacement = _ph(_resolve_function(inner))
                elif "NUMVAL" in upper_fname:
                    cleaned = re.sub(r"\s+OF\s+\S+", "", inner, flags=re.IGNORECASE).strip()
                    varname = _vk(cleaned)
                    replacement = _ph(f"_to_num(state.get('{varname}', 0))")
                else:
                    replacement = _ph("0")
                text = text[:pos] + replacement + text[end:]
                resolved_any = True
                break  # restart after replacement
            if not resolved_any:
                break
        return text

    expr = _resolve_function(expr)

    # Strip remaining bare FUNCTION keyword
    expr = re.sub(r"\bFUNCTION\b\s*", "", expr, flags=re.IGNORECASE)

    # VAR OF QUALIFIER → use the first identifier
    expr = re.sub(
        r"([A-Z][A-Z0-9-]*)\s+OF\s+[A-Z][A-Z0-9-]*",
        r"\1", expr, flags=re.IGNORECASE,
    )

    # Convert remaining variable references to Python
    def replace_var(m):
        name = m.group(1)  # base identifier (without subscript)
        upper = name.upper()
        if re.match(r"^__PH\d+__$", name):
            return name
        if re.match(r"^-?\d+\.?\d*$", name):
            return str(int(name)) if "." not in name else str(float(name))
        if upper in _FIGURATIVE_SOURCES:
            return str(_FIGURATIVE_SOURCES[upper])
        return f"_to_num(state.get('{upper}', 0))"

    py_expr = re.sub(r"([A-Z_][A-Z0-9_-]*)(?:\s*\([^)]*\))?", replace_var, expr, flags=re.IGNORECASE)

    # Restore placeholders
    for key, val in _placeholders.items():
        py_expr = py_expr.replace(key, val)

    # Validate the generated Python expression compiles
    try:
        compile(py_expr, "<compute>", "eval")
    except SyntaxError:
        cb.line(f"pass  # COMPUTE: unrecoverable expression after comment strip")
        return

    # COBOL truncates by default; use int() when expression has division
    has_div = "/" in py_expr
    rounded = "ROUNDED" in stmt.text.upper()
    if has_div and not rounded:
        cb.line(f"state['{_vk(target)}'] = int({py_expr})")
    elif has_div and rounded:
        cb.line(f"state['{_vk(target)}'] = round({py_expr})")
    else:
        cb.line(f"state['{_vk(target)}'] = {py_expr}")


def _gen_add(cb: _CodeBuilder, stmt: Statement):
    text = _strip_cobol_comments(stmt.text)
    m_giving = re.search(r"ADD\s+(.+?)\s+GIVING\s+(.+)", text, re.IGNORECASE)
    m_to = re.search(r"ADD\s+(.+?)\s+TO\s+(.+)", text, re.IGNORECASE)
    if m_giving:
        addends_str = m_giving.group(1).strip()
        target_str = re.sub(r"\s+ROUNDED\b.*", "", m_giving.group(2).strip().rstrip("."), flags=re.IGNORECASE)
        tname = _var_name(target_str)
        parts = []
        for tok in _tokenize_cobol_vars(addends_str):
            if re.match(r"^[+-]?\d+\.?\d*$", tok):
                parts.append(tok)
            elif tok.upper() not in ("TO", "GIVING", "ROUNDED"):
                vname = _var_name(tok)
                parts.append(f"_to_num(state.get('{vname}', 0))")
        if parts:
            cb.line(f"state['{tname}'] = " + " + ".join(parts))
        else:
            cb.line(f"pass  # ADD: {_oneline(stmt.text)}")
    elif m_to:
        addends_str = m_to.group(1).strip()
        targets_str = m_to.group(2).strip().rstrip(".")

        # Build sum of all addends
        add_parts = []
        for tok in _tokenize_cobol_vars(addends_str):
            if re.match(r"^[+-]?\d+\.?\d*$", tok):
                add_parts.append(tok)
            elif tok.upper() not in ("TO", "GIVING", "ROUNDED"):
                add_parts.append(f"_to_num(state.get('{_var_name(tok)}', 0))")
        val = " + ".join(add_parts) if add_parts else "0"

        for tok in _tokenize_cobol_vars(targets_str):
            tname = _var_name(tok)
            if tname and tname not in ("TO", "GIVING", "ROUNDED"):
                cb.line(f"state['{tname}'] = _to_num(state.get('{tname}', 0)) + {val}")
    else:
        cb.line(f"pass  # ADD: {_oneline(stmt.text)}")


def _gen_subtract(cb: _CodeBuilder, stmt: Statement):
    text = _strip_cobol_comments(stmt.text)
    m_giving = re.search(
        r"SUBTRACT\s+(.+?)\s+FROM\s+(.+?)\s+GIVING\s+(.+)",
        text, re.IGNORECASE,
    )
    m = re.search(r"SUBTRACT\s+(.+?)\s+FROM\s+(.+)", text, re.IGNORECASE)
    if m_giving:
        subtrahend = m_giving.group(1).strip()
        minuend = m_giving.group(2).strip().rstrip(".")
        target_str = re.sub(r"\s+ROUNDED\b.*", "", m_giving.group(3).strip().rstrip("."), flags=re.IGNORECASE)
        tname = _var_name(target_str)
        def _sv(v):
            v = v.strip()
            if re.match(r"^[+-]?\d+\.?\d*$", v):
                return v
            return f"_to_num(state.get('{_var_name(v)}', 0))"
        cb.line(f"state['{tname}'] = {_sv(minuend)} - {_sv(subtrahend)}")
    elif m:
        subtrahend = m.group(1).strip()
        targets_str = m.group(2).strip().rstrip(".")

        if re.match(r"^-?\d+\.?\d*$", subtrahend):
            val = str(int(subtrahend)) if "." not in subtrahend else str(float(subtrahend))
        else:
            val = f"_to_num(state.get('{_var_name(subtrahend)}', 0))"

        for tok in _tokenize_cobol_vars(targets_str):
            tname = _var_name(tok)
            if tname and tname not in ("FROM", "GIVING", "ROUNDED"):
                cb.line(f"state['{tname}'] = _to_num(state.get('{tname}', 0)) - {val}")
    else:
        cb.line(f"pass  # SUBTRACT: {_oneline(stmt.text)}")


def _strip_comments_condition(text: str) -> str:
    """Strip *> comments from a COBOL condition expression.

    In merged AST text, *> introduces inline comments that may contain old
    condition code. We strip the comment text and keep what follows if it
    looks like a valid condition continuation (starts with paren or variable
    followed by a COBOL comparison keyword).
    """
    if "*>" not in text:
        return text.strip()

    parts = text.split("*>")
    result = parts[0].strip()

    # Pattern for condition continuation: AND/OR followed by condition,
    # or a parenthesized condition group
    _COND_CONT = re.compile(
        r"\b(AND|OR)\s+(?:NOT\s+)?(?:\()?[A-Z][A-Z0-9-]",
        re.IGNORECASE,
    )
    # Pattern for start of condition: VAR comparison or (VAR comparison
    _COND_START = re.compile(
        r"(?:\()?\s*[A-Z][A-Z0-9-]*(?:\s*\([^)]*\))?\s+(?:EQUAL|NOT|LESS|GREATER|IN)\b",
        re.IGNORECASE,
    )

    def _append(result: str, new_text: str) -> str:
        """Append new_text to result, avoiding AND AND or OR OR duplication."""
        new_text = new_text.strip()
        result_stripped = result.rstrip()
        # If result ends with AND/OR and new_text starts with same, skip the dupe
        for kw in ("AND", "OR"):
            if result_stripped.upper().endswith(kw) and re.match(rf"^{kw}\b", new_text, re.IGNORECASE):
                new_text = new_text[len(kw):].strip()
                break
        # If result ends with AND but new_text starts with OR (or vice versa),
        # the AND was from the old code — replace it with the new connector
        if result_stripped.upper().endswith("AND") and re.match(r"^OR\b", new_text, re.IGNORECASE):
            result = result_stripped[:-3].rstrip()
        elif result_stripped.upper().endswith("OR") and re.match(r"^AND\b", new_text, re.IGNORECASE):
            result = result_stripped[:-2].rstrip()
        return result + " " + new_text

    for seg in parts[1:]:
        seg = seg.strip()
        if not seg:
            continue

        # Look for AND/OR continuation — most reliable indicator of new code
        m = _COND_CONT.search(seg)
        if m:
            result = _append(result, seg[m.start():])
            continue

        # Look for period-separated new code: *> old-code. new-code
        if ". " in seg:
            after = seg.split(". ", 1)[1].strip()
            if after and _COND_START.match(after):
                result = _append(result, after)
                continue

        # Look for a parenthesized condition start
        m = re.search(r"(\([A-Z][A-Z0-9-]*(?:\s*\([^)]*\))?\s+(?:EQUAL|NOT|LESS|GREATER))", seg, re.IGNORECASE)
        if m:
            result = _append(result, seg[m.start():])
            continue

        # Look for condition start: VAR EQUAL/NOT/LESS...
        m = _COND_START.search(seg)
        if m:
            result = _append(result, seg[m.start():])
            continue

    return " ".join(result.split()).strip()


def _gen_if(cb: _CodeBuilder, stmt: Statement):
    condition = stmt.attributes.get("condition", "")
    # Strip *> comments from conditions (AST may contain inline comments)
    if "*>" in condition:
        condition = _strip_comments_condition(condition)
    bid = cb.next_branch_id()
    cb.branch_meta[bid] = {
        "condition": condition,
        "paragraph": cb.current_para,
        "type": "IF",
    }
    if not condition:
        cb.line(f"if True:  # IF: {_oneline(stmt.text)}")
    else:
        py_cond = cobol_condition_to_python(condition)
        cb.line(f"if {py_cond}:")
    cb.indent()
    cb.line(f"state.get('_branches', set()).add({bid})")

    # Split children into before-ELSE and ELSE
    else_node = None
    then_children = []
    for child in stmt.children:
        if child.type == "ELSE":
            else_node = child
        else:
            then_children.append(child)

    if not then_children:
        cb.line("pass")
    else:
        for child in then_children:
            _gen_statement(cb, child)
    cb.dedent()

    if else_node:
        cb.line("else:")
        cb.indent()
        cb.line(f"state.get('_branches', set()).add(-{bid})")
        if not else_node.children:
            cb.line("pass")
        else:
            for child in else_node.children:
                _gen_statement(cb, child)
        cb.dedent()
    else:
        # No ELSE in AST — still instrument the fall-through path
        cb.line("else:")
        cb.indent()
        cb.line(f"state.get('_branches', set()).add(-{bid})")
        cb.dedent()


def _gen_evaluate(cb: _CodeBuilder, stmt: Statement):
    subject = stmt.attributes.get("subject", "TRUE")
    is_true = subject.upper() == "TRUE"

    if not is_true:
        subj_expr = f"state.get('{_vk(subject)}', '')"
        cb.line(f"_eval_subject = {subj_expr}")
        # Check if WHEN values are numeric — if so, coerce subject to number
        _has_numeric_when = False
        for child in stmt.children:
            if child.type == "WHEN":
                vt, io = parse_when_value(child.text)
                if not io and re.match(r"^[+-]?\d+\.?\d*$", vt.strip()):
                    _has_numeric_when = True
                    break
        if _has_numeric_when:
            cb.line(f"_eval_subject = _to_num(_eval_subject)")

    first_when = True
    for child in stmt.children:
        if child.type != "WHEN":
            _gen_statement(cb, child)
            continue

        value_text, is_other = parse_when_value(child.text)

        if is_other:
            cb.line("else:")
        else:
            resolved = resolve_when_value(value_text, is_true)
            if is_true:
                keyword = "if" if first_when else "elif"
                cb.line(f"{keyword} {resolved}:")
            else:
                keyword = "if" if first_when else "elif"
                cb.line(f"{keyword} _eval_subject == {resolved}:")
            first_when = False

        cb.indent()
        bid = cb.next_branch_id()
        cb.branch_meta[bid] = {
            "condition": value_text if not is_other else "OTHER",
            "paragraph": cb.current_para,
            "type": "EVALUATE",
            "subject": subject,
        }
        cb.line(f"state.get('_branches', set()).add({bid})")
        when_body = [c for c in child.children if c.type != "WHEN"]
        if not when_body:
            cb.line("pass")
        else:
            for c in when_body:
                _gen_statement(cb, c)
        cb.dedent()


def _gen_perform(cb: _CodeBuilder, stmt: Statement):
    target = stmt.attributes.get("target", "")
    if not target:
        cb.line(f"pass  # PERFORM: {_oneline(stmt.text)}")
        return
    func_name = _sanitize_name(target)
    times_str = stmt.attributes.get("times", "")
    if times_str:
        # Extract numeric count: "3 TIMES" → 3, or variable name
        m = re.match(r"(\d+)\s+TIMES?", times_str, re.IGNORECASE)
        if m:
            count = int(m.group(1))
            cb.line(f"for _ in range({count}):")
            cb.indent()
            cb.line(f"{func_name}(state)")
            cb.dedent()
            return
        # Variable TIMES: "WS-COUNT TIMES"
        mv = re.match(r"([A-Z][A-Z0-9-]*)\s+TIMES?", times_str, re.IGNORECASE)
        if mv:
            vname = mv.group(1).upper()
            cb.line(f"for _ in range(int(_to_num(state.get('{vname}', 0)))):")
            cb.indent()
            cb.line(f"{func_name}(state)")
            cb.dedent()
            return
    # Check for VARYING in text when not in attributes
    m_vary = re.search(
        r"VARYING\s+([A-Z][A-Z0-9-]*)\s+FROM\s+(\S+)\s+BY\s+(\S+)\s+UNTIL\s+(.+)",
        stmt.text, re.IGNORECASE,
    )
    if m_vary:
        loop_var = m_vary.group(1).upper()
        from_val = _resolve_source(m_vary.group(2).strip())
        by_val = _resolve_source(m_vary.group(3).strip())
        until_cond = m_vary.group(4).strip().rstrip(".")
        py_until = cobol_condition_to_python(until_cond)
        bid = cb.next_branch_id()
        cb.branch_meta[bid] = {
            "condition": until_cond,
            "paragraph": cb.current_para,
            "type": "PERFORM_VARYING",
        }
        lv = cb.next_loop_var()
        cb.line(f"state['{loop_var}'] = _to_num({from_val})")
        cb.line(f"{lv} = 0")
        cb.line(f"while not ({py_until}):")
        cb.indent()
        cb.line(f"state.get('_branches', set()).add({bid})")
        cb.line(f"{func_name}(state)")
        cb.line(f"state['{loop_var}'] = _to_num(state.get('{loop_var}', 0)) + _to_num({by_val})")
        cb.line(f"{lv} += 1")
        cb.line(f"if {lv} >= 100:")
        cb.indent()
        cb.line("break")
        cb.dedent()
        cb.dedent()
        cb.line(f"if {lv} == 0:")
        cb.indent()
        cb.line(f"state.get('_branches', set()).add(-{bid})")
        cb.dedent()
        return

    cb.line(f"{func_name}(state)")


_PARAGRAPH_ORDER: list[str] = []


def _get_thru_range(target: str, thru: str) -> list[str]:
    """Get the list of paragraph names from target through thru (inclusive)."""
    if not _PARAGRAPH_ORDER:
        return [target]
    try:
        start = _PARAGRAPH_ORDER.index(target)
    except ValueError:
        return [target]
    try:
        end = _PARAGRAPH_ORDER.index(thru)
    except ValueError:
        return [target]
    if end < start:
        return [target]
    return _PARAGRAPH_ORDER[start:end + 1]


def _gen_perform_thru(cb: _CodeBuilder, stmt: Statement):
    target = stmt.attributes.get("target", "")
    thru = stmt.attributes.get("thru", "")
    condition = stmt.attributes.get("condition", "")
    # ProLeap sometimes gives wrong thru value; prefer parsing from text
    m_thru = re.search(r"THRU\s+([A-Z][A-Z0-9-]*)", stmt.text, re.IGNORECASE)
    if m_thru:
        thru = m_thru.group(1).upper()

    if not target:
        cb.line(f"pass  # PERFORM_THRU: {_oneline(stmt.text)}")
        return

    # Determine all paragraphs in the THRU range
    if thru and thru != target:
        range_paras = _get_thru_range(target, thru)
    else:
        range_paras = [target]

    if condition:
        py_cond = cobol_condition_to_python(condition)
        bid = cb.next_branch_id()
        cb.branch_meta[bid] = {
            "condition": condition,
            "paragraph": cb.current_para,
            "type": "PERFORM_UNTIL",
        }
        lv = cb.next_loop_var()
        cb.line(f"{lv} = 0")
        cb.line(f"while not ({py_cond}):")
        cb.indent()
        cb.line(f"state.get('_branches', set()).add({bid})")
        for para_name in range_paras:
            cb.line(f"{_sanitize_name(para_name)}(state)")
        cb.line(f"{lv} += 1")
        cb.line(f"if {lv} >= 100:")
        cb.indent()
        cb.line("break")
        cb.dedent()
        cb.dedent()
        # Branch for "condition was true from start" (loop not entered)
        cb.line(f"if {lv} == 0:")
        cb.indent()
        cb.line(f"state.get('_branches', set()).add(-{bid})")
        cb.dedent()
    else:
        for para_name in range_paras:
            cb.line(f"{_sanitize_name(para_name)}(state)")


def _gen_perform_inline(cb: _CodeBuilder, stmt: Statement):
    condition = stmt.attributes.get("condition", "")
    varying = stmt.attributes.get("varying", "")
    lv = cb.next_loop_var()
    vary_increment = None  # (loop_var, by_val) if VARYING parsed
    loop_bid = None  # branch ID for loop condition

    if condition:
        py_cond = cobol_condition_to_python(condition)
        loop_bid = cb.next_branch_id()
        cb.branch_meta[loop_bid] = {
            "condition": condition,
            "paragraph": cb.current_para,
            "type": "PERFORM_UNTIL",
        }
        cb.line(f"{lv} = 0")
        cb.line(f"while not ({py_cond}):")
    elif varying:
        # Parse VARYING <var> FROM <start> BY <step> UNTIL <cond>
        m_vary = re.match(
            r"VARYING\s+([A-Z][A-Z0-9-]*)\s+FROM\s+(\S+)\s+BY\s+(\S+)\s+UNTIL\s+(.+)",
            varying, re.IGNORECASE,
        )
        if m_vary:
            loop_var = m_vary.group(1).upper()
            from_val = _resolve_source(m_vary.group(2).strip())
            by_val = _resolve_source(m_vary.group(3).strip())
            until_cond = m_vary.group(4).strip()
            py_until = cobol_condition_to_python(until_cond)
            loop_bid = cb.next_branch_id()
            cb.branch_meta[loop_bid] = {
                "condition": until_cond,
                "paragraph": cb.current_para,
                "type": "PERFORM_VARYING",
            }
            cb.line(f"state['{loop_var}'] = _to_num({from_val})")
            cb.line(f"{lv} = 0")
            cb.line(f"while not ({py_until}):")
            vary_increment = (loop_var, by_val)
        else:
            cb.line(f"{lv} = 0")
            cb.line(f"while True:  # VARYING: {varying[:50]}")
    else:
        cb.line(f"{lv} = 0")
        cb.line(f"while True:  # PERFORM_INLINE")

    cb.indent()
    if loop_bid is not None:
        cb.line(f"state.get('_branches', set()).add({loop_bid})")
    if not stmt.children:
        cb.line("pass")
    else:
        for child in stmt.children:
            _gen_statement(cb, child)
    if vary_increment:
        loop_var, by_val = vary_increment
        cb.line(f"state['{loop_var}'] = _to_num(state.get('{loop_var}', 0)) + _to_num({by_val})")
    cb.line(f"{lv} += 1")
    cb.line(f"if {lv} >= 100:")
    cb.indent()
    cb.line("break")
    cb.dedent()
    cb.dedent()
    if loop_bid is not None:
        cb.line(f"if {lv} == 0:")
        cb.indent()
        cb.line(f"state.get('_branches', set()).add(-{loop_bid})")
        cb.dedent()


def _gen_set(cb: _CodeBuilder, stmt: Statement):
    _VN = r"[A-Z0-9][A-Z0-9-]*"
    m = re.search(rf"SET\s+({_VN})\s+TO\s+TRUE", stmt.text, re.IGNORECASE)
    if m:
        varname = m.group(1).upper()
        cb.line(f"state['{varname}'] = True")
        return
    m = re.search(rf"SET\s+({_VN})\s+TO\s+FALSE", stmt.text, re.IGNORECASE)
    if m:
        varname = m.group(1).upper()
        cb.line(f"state['{varname}'] = False")
        return
    m = re.search(rf"SET\s+({_VN})\s+UP\s+BY\s+(.+)", stmt.text, re.IGNORECASE)
    if m:
        varname = m.group(1).upper()
        value = m.group(2).strip().rstrip(".")
        cb.line(f"state['{varname}'] = _to_num(state.get('{varname}', 0)) + {_resolve_source(value)}")
        return
    m = re.search(rf"SET\s+({_VN})\s+DOWN\s+BY\s+(.+)", stmt.text, re.IGNORECASE)
    if m:
        varname = m.group(1).upper()
        value = m.group(2).strip().rstrip(".")
        cb.line(f"state['{varname}'] = _to_num(state.get('{varname}', 0)) - {_resolve_source(value)}")
        return
    m = re.search(rf"SET\s+({_VN})\s+TO\s+(.+)", stmt.text, re.IGNORECASE)
    if m:
        varname = m.group(1).upper()
        value = m.group(2).strip().rstrip(".")
        cb.line(f"state['{varname}'] = {_resolve_source(value)}")
        return
    cb.line(f"pass  # SET: {_oneline(stmt.text)}")


def _gen_display(cb: _CodeBuilder, stmt: Statement):
    # Parse DISPLAY text to extract parts
    text = stmt.text.strip()
    m = re.match(r"DISPLAY\s+(.*)", text, re.IGNORECASE)
    if not m:
        cb.line(f"state['_display'].append('{_sq(_oneline(text))}')")
        return

    content = m.group(1).rstrip(".")
    parts = []
    pos = 0
    while pos < len(content):
        if content[pos] == "'":
            end = content.index("'", pos + 1) if "'" in content[pos + 1:] else len(content)
            parts.append(content[pos:end + 1])
            pos = end + 1
        elif content[pos] in (" ", "\t"):
            pos += 1
        else:
            end = pos
            while end < len(content) and content[end] not in (" ", "\t", "'"):
                end += 1
            token = content[pos:end]
            if _vk(token) not in ("UPON", "CONSOLE", "SYSIN", "SYSOUT"):
                parts.append(f"str(state.get('{_vk(token)}', ''))")
            pos = end

    if parts:
        expr = " + ".join(parts)
        cb.line(f"state['_display'].append({expr})")
    else:
        cb.line(f"state['_display'].append('')")


def _gen_call(cb: _CodeBuilder, stmt: Statement):
    target = stmt.attributes.get("target", "UNKNOWN")
    cb.line(f"_dummy_call('{_sq(target)}', state)")


def _gen_exec(cb: _CodeBuilder, stmt: Statement, kind: str):
    raw = stmt.attributes.get("raw_text", "")
    # Escape for string
    escaped = raw.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")
    if len(escaped) > 200:
        escaped = escaped[:200] + "..."
    cb.line(f"_dummy_exec('{kind}', '{escaped}', state)")


def _gen_initialize(cb: _CodeBuilder, stmt: Statement):
    text = _strip_cobol_comments(stmt.text)
    m = re.search(r"INITIALIZE\s+(.+)", text, re.IGNORECASE)
    if m:
        targets = m.group(1).strip().rstrip(".")
        for tok in _tokenize_cobol_vars(targets):
            tname = _var_name(tok)
            if tname and tname not in ("REPLACING", "ALPHANUMERIC",
                                       "NUMERIC", "BY", "ALL"):
                cb.line(f"state['{tname}'] = 0 if isinstance(state.get('{tname}', ''), (int, float)) else ''")
    else:
        cb.line(f"pass  # INITIALIZE: {_oneline(stmt.text)}")


def _gen_string_stmt(cb: _CodeBuilder, stmt: Statement):
    # Best-effort: extract INTO target and concatenate parts
    m = re.search(r"INTO\s+([A-Z][A-Z0-9-]*)", stmt.text, re.IGNORECASE)
    if m:
        target = m.group(1).upper()
        # Extract parts before DELIMITED
        parts_text = re.split(r"\bINTO\b", stmt.text, flags=re.IGNORECASE)[0]
        parts_text = re.sub(r"^STRING\s+", "", parts_text, flags=re.IGNORECASE)

        # Split on DELIMITED BY SIZE
        segments = re.split(r"\s+DELIMITED\s+BY\s+SIZE\s*", parts_text, flags=re.IGNORECASE)
        py_parts = []
        for seg in segments:
            seg = seg.strip()
            if not seg:
                continue
            # Each segment could be a quoted string or variable
            for token in re.findall(r"'[^']*'|[A-Z][A-Z0-9-]*", seg, re.IGNORECASE):
                if token.startswith("'"):
                    py_parts.append(token)
                else:
                    py_parts.append(f"str(state.get('{_vk(token)}', ''))")

        if py_parts:
            expr = " + ".join(py_parts)
            cb.line(f"state['{target}'] = {expr}")
        else:
            cb.line(f"pass  # STRING: {_oneline(stmt.text)}")
    else:
        cb.line(f"pass  # STRING: {_oneline(stmt.text)}")


def _gen_accept(cb: _CodeBuilder, stmt: Statement):
    m = re.search(r"ACCEPT\s+([A-Z][A-Z0-9-]*)", stmt.text, re.IGNORECASE)
    if m:
        varname = m.group(1).upper()
        cb.line(f"# ACCEPT {varname} — uses preset state value")
    else:
        cb.line(f"# ACCEPT: {_oneline(stmt.text)}")


def _gen_read(cb: _CodeBuilder, stmt: Statement):
    # Extract file name and set status
    m = re.search(r"READ\s+([A-Z][A-Z0-9-]*)", stmt.text, re.IGNORECASE)
    if m:
        fname = m.group(1).upper()
        cb.line(f"state['_reads'].append('{fname}')")
        cb.line(f"_apply_stub_outcome(state, 'READ:{fname}')")
    else:
        cb.line(f"state['_reads'].append('UNKNOWN')")
        cb.line(f"_apply_stub_outcome(state, 'READ:UNKNOWN')")


def _gen_write(cb: _CodeBuilder, stmt: Statement):
    m = re.search(r"WRITE\s+([A-Z][A-Z0-9-]*)", stmt.text, re.IGNORECASE)
    if m:
        recname = m.group(1).upper()
        cb.line(f"state['_writes'].append('{recname}')")
        cb.line(f"_apply_stub_outcome(state, 'WRITE:{recname}')")
    else:
        cb.line(f"state['_writes'].append('UNKNOWN')")
        cb.line(f"_apply_stub_outcome(state, 'WRITE:UNKNOWN')")


def _gen_rewrite(cb: _CodeBuilder, stmt: Statement):
    m = re.search(r"REWRITE\s+([A-Z][A-Z0-9-]*)", stmt.text, re.IGNORECASE)
    if m:
        recname = m.group(1).upper()
        cb.line(f"state['_writes'].append('{recname}')")
        cb.line(f"_apply_stub_outcome(state, 'REWRITE:{recname}')")
    else:
        cb.line(f"state['_writes'].append('UNKNOWN')")


def _gen_open(cb: _CodeBuilder, stmt: Statement):
    m = re.search(r"OPEN\s+(?:INPUT|OUTPUT|I-O|EXTEND)\s+(.+)", stmt.text, re.IGNORECASE)
    if m:
        files_str = m.group(1).strip().rstrip(".")
        for tok in re.split(r"\s+", files_str):
            tok = _vk(tok.strip())
            if tok and tok not in ("INPUT", "OUTPUT", "I-O", "EXTEND"):
                cb.line(f"_apply_stub_outcome(state, 'OPEN:{tok}')")
    cb.line(f"pass  # {_oneline(stmt.text, 70)}")


def _gen_close(cb: _CodeBuilder, stmt: Statement):
    m = re.search(r"CLOSE\s+(.+)", stmt.text, re.IGNORECASE)
    if m:
        files_str = m.group(1).strip().rstrip(".")
        for tok in re.split(r"\s+", files_str):
            tok = _vk(tok.strip())
            if tok:
                cb.line(f"_apply_stub_outcome(state, 'CLOSE:{tok}')")
    cb.line(f"pass  # {_oneline(stmt.text, 70)}")


def _gen_search(cb: _CodeBuilder, stmt: Statement):
    """Generate code for COBOL SEARCH statement.

    SEARCH <table> [VARYING <index>] AT END <stmts> WHEN <cond> <stmts>

    Since we don't have table data, the search result is controlled by a
    stub outcome flag.  If found (default 70%), execute WHEN branch and set
    the index variable; otherwise execute AT END branch.
    """
    text = stmt.text.strip()

    # Extract table name
    m_table = re.match(r"SEARCH\s+([A-Z][A-Z0-9-]*)", text, re.IGNORECASE)
    if not m_table:
        cb.line(f"pass  # SEARCH (unparsed): {_oneline(text)}")
        return
    table_name = m_table.group(1).upper()

    # Extract VARYING index
    m_vary = re.search(r"VARYING\s+([A-Z][A-Z0-9-]*)", text, re.IGNORECASE)
    index_var = m_vary.group(1).upper() if m_vary else None

    # Split into AT END and WHEN sections
    at_end_body = ""
    when_body = ""
    at_end_pos = re.search(r"\bAT\s+END\b", text, re.IGNORECASE)
    when_pos = re.search(r"\bWHEN\b", text, re.IGNORECASE)

    if at_end_pos and when_pos:
        at_end_body = text[at_end_pos.end():when_pos.start()].strip()
        when_body = text[when_pos.end():].strip()
    elif when_pos:
        when_body = text[when_pos.end():].strip()
    elif at_end_pos:
        at_end_body = text[at_end_pos.end():].strip()

    # Generate branching code with branch instrumentation
    bid = cb.next_branch_id()
    cb.branch_meta[bid] = {
        "condition": f"SEARCH {table_name} FOUND",
        "paragraph": cb.current_para,
        "type": "SEARCH",
    }
    stub_key = f"SEARCH:{table_name}"
    cb.line(f"_sl = state.get('_stub_outcomes', {{}}).get('{stub_key}', [])")
    cb.line(f"_search_found = _sl.pop(0) if _sl else True")
    cb.line("if _search_found:")
    cb.indent()
    cb.line(f"state.get('_branches', set()).add({bid})")
    # WHEN branch: set index and execute extracted statements
    if index_var:
        cb.line(f"state['{index_var}'] = 1")
    _gen_search_body(cb, when_body)
    cb.dedent()
    cb.line("else:")
    cb.indent()
    cb.line(f"state.get('_branches', set()).add(-{bid})")
    if at_end_body:
        _gen_search_body(cb, at_end_body)
    else:
        cb.line("pass")
    cb.dedent()


def _gen_search_body(cb: _CodeBuilder, body: str):
    """Generate Python code for extracted SEARCH body text (AT END / WHEN)."""
    if not body:
        cb.line("pass")
        return

    generated = False

    # Extract and generate MOVE statements
    for m in re.finditer(
        r"MOVE\s+(.+?)\s+TO\s+([A-Z][A-Z0-9-]*(?:\s*\([^)]*\))?)",
        body, re.IGNORECASE,
    ):
        source = m.group(1).strip()
        target = m.group(2).strip().rstrip(".")
        resolved = _resolve_source(source)
        tname = _vk(target)
        # Strip subscript for state key but keep for context
        clean = re.sub(r"\s*\([^)]*\)", "", tname)
        cb.line(f"state['{clean}'] = {resolved}")
        generated = True

    # Extract GO TO
    m_goto = re.search(r"GO\s+TO\s+([A-Z][A-Z0-9-]*)", body, re.IGNORECASE)
    if m_goto:
        func_name = _sanitize_name(m_goto.group(1))
        cb.line(f"{func_name}(state)")
        cb.line("return")
        generated = True

    # Extract PERFORM [THRU]
    for m in re.finditer(
        r"PERFORM\s+([A-Z][A-Z0-9-]*)(?:\s+THRU\s+([A-Z][A-Z0-9-]*))?",
        body, re.IGNORECASE,
    ):
        target = m.group(1).upper()
        thru = m.group(2).upper() if m.group(2) else None
        if thru and thru != target:
            range_paras = _get_thru_range(target, thru)
        else:
            range_paras = [target]
        for para_name in range_paras:
            cb.line(f"{_sanitize_name(para_name)}(state)")
        generated = True

    # Extract DISPLAY
    for m in re.finditer(r"DISPLAY\s+'([^']*)'", body, re.IGNORECASE):
        cb.line(f"state['_display'].append('{m.group(1)}')")
        generated = True

    # Extract ADD ... TO ...
    for m in re.finditer(
        r"ADD\s+(\S+)\s+TO\s+([A-Z][A-Z0-9-]*)", body, re.IGNORECASE,
    ):
        val = m.group(1).strip()
        target = m.group(2).strip().upper()
        resolved = _resolve_source(val)
        cb.line(f"state['{target}'] = _to_num(state.get('{target}', 0)) + _to_num({resolved})")
        generated = True

    # Extract COMPUTE
    for m in re.finditer(
        r"COMPUTE\s+([A-Z][A-Z0-9-]*)\s*=\s*([^.]+)",
        body, re.IGNORECASE,
    ):
        target = _vk(m.group(1))
        expr = m.group(2).strip()
        # Simple variable-only expression
        py_expr = re.sub(
            r"([A-Z][A-Z0-9-]+)",
            lambda mv: f"_to_num(state.get('{_vk(mv.group(1))}', 0))",
            expr,
        )
        cb.line(f"state['{target}'] = {py_expr}")
        generated = True

    if not generated:
        cb.line("pass")


def _gen_unstring(cb: _CodeBuilder, stmt: Statement):
    """Generate code for COBOL UNSTRING statement.

    Supports: UNSTRING src DELIMITED BY delim INTO t1 t2 ... [END-UNSTRING]
    """
    text = " ".join(stmt.text.split())

    # Extract source
    m_src = re.match(r"UNSTRING\s+([A-Z][A-Z0-9-]*(?:\s*\([^)]*\))?)", text, re.IGNORECASE)
    if not m_src:
        cb.line(f"pass  # UNSTRING (unparsed): {_oneline(text)}")
        return

    src_raw = m_src.group(1).strip()
    src_var = re.sub(r"\s*\(.*\)", "", src_raw).upper()

    # Extract delimiter
    m_delim = re.search(r"DELIMITED\s+BY\s+(\S+)", text, re.IGNORECASE)
    if m_delim:
        delim_token = m_delim.group(1).strip()
        if _vk(delim_token) == "SPACES" or _vk(delim_token) == "SPACE":
            py_delim = "None"  # Python split() with None splits on whitespace
        elif delim_token.startswith("'") and delim_token.endswith("'"):
            py_delim = delim_token
        else:
            py_delim = f"str(state.get('{_vk(delim_token)}', ' '))"
    else:
        py_delim = "None"

    # Extract INTO targets
    m_into = re.search(r"\bINTO\s+(.+?)(?:\s+END-UNSTRING|\s*$)", text, re.IGNORECASE)
    if not m_into:
        cb.line(f"pass  # UNSTRING (no INTO): {_oneline(text)}")
        return

    targets_str = m_into.group(1).strip()
    # Split target names (filter out keywords)
    targets = []
    for tok in re.findall(r"[A-Z][A-Z0-9-]*(?:\s*\([^)]*\))?", targets_str, re.IGNORECASE):
        clean = re.sub(r"\s*\(.*\)", "", tok).upper()
        if clean not in ("END-UNSTRING", "DELIMITER", "COUNT", "IN", "ALL", "OR"):
            targets.append(clean)

    if not targets:
        cb.line(f"pass  # UNSTRING (no targets): {_oneline(text)}")
        return

    cb.line(f"_us_src = str(state.get('{src_var}', ''))")
    if py_delim == "None":
        cb.line(f"_us_parts = _us_src.split()")
    else:
        cb.line(f"_us_parts = _us_src.split({py_delim})")
    for i, tgt in enumerate(targets):
        cb.line(f"state['{tgt}'] = _us_parts[{i}].strip() if {i} < len(_us_parts) else ''")


def _gen_inspect(cb: _CodeBuilder, stmt: Statement):
    """Generate code for COBOL INSPECT statement.

    Supports: INSPECT var TALLYING counter FOR LEADING SPACES/ZEROES
    """
    text = stmt.text.strip()

    # INSPECT var TALLYING counter FOR LEADING SPACES/ZEROES
    m = re.search(
        r"INSPECT\s+([A-Z][A-Z0-9-]*(?:\s*\([^)]*\))?)\s+TALLYING\s+([A-Z][A-Z0-9-]*)\s+FOR\s+LEADING\s+(\S+)",
        text, re.IGNORECASE,
    )
    if m:
        src_var = _vk(re.sub(r"\s*\(.*\)", "", m.group(1).strip()))
        counter = _vk(m.group(2).strip())
        what = m.group(3).strip().upper().rstrip(".")
        if what in ("SPACES", "SPACE"):
            char = " "
        elif what in ("ZEROS", "ZEROES", "ZERO"):
            char = "0"
        else:
            char = what.strip("'")
        cb.line(f"_ins_v = str(state.get('{src_var}', ''))")
        cb.line(f"_ins_c = 0")
        cb.line(f"for _ch in _ins_v:")
        cb.indent()
        cb.line(f"if _ch == '{char}':")
        cb.indent()
        cb.line(f"_ins_c += 1")
        cb.dedent()
        cb.line(f"else:")
        cb.indent()
        cb.line(f"break")
        cb.dedent()
        cb.dedent()
        cb.line(f"state['{counter}'] = _to_num(state.get('{counter}', 0)) + _ins_c")
        return

    # INSPECT var REPLACING LEADING/ALL/FIRST
    m = re.search(
        r"INSPECT\s+([A-Z][A-Z0-9-]*(?:\s*\([^)]*\))?)\s+REPLACING\s+(.+)",
        text, re.IGNORECASE,
    )
    if m:
        src_var = re.sub(r"\s*\(.*\)", "", m.group(1).strip()).upper()
        # Best-effort: just emit a comment — REPLACING is complex
        cb.line(f"pass  # INSPECT REPLACING: {_oneline(text)}")
        return

    cb.line(f"pass  # INSPECT: {_oneline(text)}")


def _gen_goto(cb: _CodeBuilder, stmt: Statement):
    target = stmt.attributes.get("target", "")
    if target:
        func_name = _sanitize_name(target)
        cb.line(f"{func_name}(state)")
        cb.line(f"return")
    else:
        cb.line(f"pass  # GO TO: {_oneline(stmt.text)}")


def _gen_statement(cb: _CodeBuilder, stmt: Statement):
    """Generate Python code for a single statement."""
    stype = stmt.type

    if stype == "MOVE":
        _gen_move(cb, stmt)
    elif stype == "COMPUTE":
        _gen_compute(cb, stmt)
    elif stype == "ADD":
        _gen_add(cb, stmt)
    elif stype == "SUBTRACT":
        _gen_subtract(cb, stmt)
    elif stype == "IF":
        _gen_if(cb, stmt)
    elif stype == "ELSE":
        # Handled inside IF
        pass
    elif stype == "EVALUATE":
        _gen_evaluate(cb, stmt)
    elif stype == "WHEN":
        # Handled inside EVALUATE
        pass
    elif stype == "PERFORM":
        _gen_perform(cb, stmt)
    elif stype == "PERFORM_THRU":
        _gen_perform_thru(cb, stmt)
    elif stype == "PERFORM_INLINE":
        _gen_perform_inline(cb, stmt)
    elif stype == "SET":
        _gen_set(cb, stmt)
    elif stype == "DISPLAY":
        _gen_display(cb, stmt)
    elif stype == "CALL":
        _gen_call(cb, stmt)
    elif stype == "EXEC_SQL":
        _gen_exec(cb, stmt, "SQL")
    elif stype == "EXEC_CICS":
        _gen_exec(cb, stmt, "CICS")
    elif stype == "EXEC_DLI":
        _gen_exec(cb, stmt, "DLI")
    elif stype == "EXEC_OTHER":
        _gen_exec(cb, stmt, "OTHER")
    elif stype == "GOBACK":
        cb.line("raise _GobackSignal()")
    elif stype == "STOP_RUN":
        cb.line("raise _GobackSignal()")
    elif stype == "EXIT":
        cb.line("pass  # EXIT")
    elif stype in ("CONTINUE", "CONTINUE_STMT"):
        cb.line("pass  # CONTINUE")
    elif stype == "INITIALIZE":
        _gen_initialize(cb, stmt)
    elif stype == "OPEN":
        _gen_open(cb, stmt)
    elif stype == "CLOSE":
        _gen_close(cb, stmt)
    elif stype == "READ":
        _gen_read(cb, stmt)
    elif stype == "WRITE":
        _gen_write(cb, stmt)
    elif stype == "REWRITE":
        _gen_rewrite(cb, stmt)
    elif stype == "ACCEPT":
        _gen_accept(cb, stmt)
    elif stype == "STRING":
        _gen_string_stmt(cb, stmt)
    elif stype == "UNSTRING":
        _gen_unstring(cb, stmt)
    elif stype == "INSPECT":
        _gen_inspect(cb, stmt)
    elif stype == "SEARCH":
        _gen_search(cb, stmt)
    elif stype == "SORT":
        cb.line(f"pass  # SORT: {_oneline(stmt.text)}")
    elif stype == "GO_TO":
        _gen_goto(cb, stmt)
    elif stype == "ALTER":
        cb.line(f"pass  # ALTER: {_oneline(stmt.text)}")
    elif stype == "MULTIPLY":
        _text = _strip_cobol_comments(stmt.text)
        m_giving = re.search(
            r"MULTIPLY\s+(\S+)\s+BY\s+(\S+)\s+GIVING\s+(.+)",
            _text, re.IGNORECASE,
        )
        m = re.search(r"MULTIPLY\s+(.+?)\s+BY\s+(.+)", _text, re.IGNORECASE)
        if m_giving:
            f1 = m_giving.group(1).strip().rstrip(".")
            f2 = m_giving.group(2).strip().rstrip(".")
            target_str = re.sub(r"\s+ROUNDED\b.*", "", m_giving.group(3).strip().rstrip("."), flags=re.IGNORECASE)
            tname = _var_name(target_str)
            def _mv(v):
                v = v.strip()
                if re.match(r"^[+-]?\d+\.?\d*$", v):
                    return v
                return f"_to_num(state.get('{_var_name(v)}', 0))"
            cb.line(f"state['{tname}'] = {_mv(f1)} * {_mv(f2)}")
        elif m:
            factor = m.group(1).strip()
            targets_str = m.group(2).strip().rstrip(".")
            if re.match(r"^-?\d+\.?\d*$", factor):
                val = str(int(factor)) if "." not in factor else str(float(factor))
            else:
                val = f"_to_num(state.get('{_var_name(factor)}', 0))"
            for tok in _tokenize_cobol_vars(targets_str):
                tname = _var_name(tok)
                if tname and tname not in ("GIVING", "ROUNDED"):
                    cb.line(f"state['{tname}'] = _to_num(state.get('{tname}', 0)) * {val}")
        else:
            cb.line(f"pass  # MULTIPLY: {_oneline(stmt.text)}")
    elif stype == "DIVIDE":
        m_by = re.search(
            r"DIVIDE\s+(.+?)\s+BY\s+(.+?)\s+GIVING\s+(\S+)"
            r"(?:\s+REMAINDER\s+(\S+))?",
            stmt.text, re.IGNORECASE,
        )
        m_into_giving = re.search(
            r"DIVIDE\s+(.+?)\s+INTO\s+(\S+)\s+GIVING\s+(\S+)"
            r"(?:\s+REMAINDER\s+(\S+))?",
            stmt.text, re.IGNORECASE,
        )
        m_into = re.search(r"DIVIDE\s+(.+?)\s+INTO\s+(.+)", stmt.text, re.IGNORECASE)
        if m_by:
            def _div_val(v):
                v = v.strip().rstrip(".")
                v = re.sub(r"\s+ROUNDED$", "", v, flags=re.IGNORECASE)
                if re.match(r"^[+-]?\d+\.?\d*$", v):
                    return v
                vn = _vk(re.sub(r"\s*\(.*", "", v))
                return f"_to_num(state.get('{vn}', 0))"
            dividend = _div_val(m_by.group(1))
            divisor = _div_val(m_by.group(2))
            tname = _vk(re.sub(r"\s*\(.*", "", m_by.group(3).strip().rstrip(".")))
            tname = re.sub(r"\s+ROUNDED$", "", tname, flags=re.IGNORECASE)
            cb.line(f"state['{tname}'] = _to_num({dividend}) // ({divisor} or 1)")
            if m_by.group(4):
                rname = _vk(re.sub(r"\s*\(.*", "", m_by.group(4).strip().rstrip(".")))
                cb.line(f"state['{rname}'] = _to_num({dividend}) % ({divisor} or 1)")
        elif m_into_giving:
            # DIVIDE x INTO y GIVING z [REMAINDER r]
            # z = y / x, r = y % x, y unchanged
            def _div_val2(v):
                v = v.strip().rstrip(".")
                v = re.sub(r"\s+ROUNDED$", "", v, flags=re.IGNORECASE)
                if re.match(r"^[+-]?\d+\.?\d*$", v):
                    return v
                vn = _vk(re.sub(r"\s*\(.*", "", v))
                return f"_to_num(state.get('{vn}', 0))"
            divisor = _div_val2(m_into_giving.group(1))
            dividend = _div_val2(m_into_giving.group(2))
            tname = _vk(re.sub(r"\s*\(.*", "", m_into_giving.group(3).strip().rstrip(".")))
            tname = re.sub(r"\s+ROUNDED$", "", tname, flags=re.IGNORECASE)
            cb.line(f"state['{tname}'] = _to_num({dividend}) // ({divisor} or 1)")
            if m_into_giving.group(4):
                rname = _vk(re.sub(r"\s*\(.*", "", m_into_giving.group(4).strip().rstrip(".")))
                cb.line(f"state['{rname}'] = _to_num({dividend}) % ({divisor} or 1)")
        elif m_into:
            divisor = m_into.group(1).strip()
            targets_str = m_into.group(2).strip().rstrip(".")
            if re.match(r"^-?\d+\.?\d*$", divisor):
                val = str(int(divisor)) if "." not in divisor else str(float(divisor))
            else:
                val = f"_to_num(state.get('{_var_name(divisor)}', 0))"
            for tok in _tokenize_cobol_vars(targets_str):
                tname = _var_name(tok)
                if tname and tname not in ("GIVING", "REMAINDER", "ROUNDED"):
                    cb.line(f"state['{tname}'] = _to_num(state.get('{tname}', 0)) // ({val} or 1)")
        else:
            cb.line(f"pass  # DIVIDE: {_oneline(stmt.text)}")
    elif stype == "START":
        m = re.search(r"START\s+([A-Z][A-Z0-9-]*)", stmt.text, re.IGNORECASE)
        if m:
            fname = m.group(1).upper()
            cb.line(f"_apply_stub_outcome(state, 'START:{fname}')")
        cb.line(f"pass  # {_oneline(stmt.text, 70)}")
    elif stype == "DELETE":
        m = re.search(r"DELETE\s+([A-Z][A-Z0-9-]*)", stmt.text, re.IGNORECASE)
        if m:
            fname = m.group(1).upper()
            cb.line(f"_apply_stub_outcome(state, 'DELETE:{fname}')")
        cb.line(f"pass  # {_oneline(stmt.text, 70)}")
    else:
        # Check for UNKNOWN statements that are actually START/DELETE
        text_upper = stmt.text.strip().upper()
        if text_upper.startswith("START "):
            m = re.search(r"START\s+([A-Z][A-Z0-9-]*)", stmt.text, re.IGNORECASE)
            if m:
                fname = m.group(1).upper()
                cb.line(f"_apply_stub_outcome(state, 'START:{fname}')")
        elif text_upper.startswith("DELETE "):
            m = re.search(r"DELETE\s+([A-Z][A-Z0-9-]*)", stmt.text, re.IGNORECASE)
            if m:
                fname = m.group(1).upper()
                cb.line(f"_apply_stub_outcome(state, 'DELETE:{fname}')")
        cb.line(f"pass  # {stype}: {_oneline(stmt.text)}")


# ---------------------------------------------------------------------------
# Top-level code generation
# ---------------------------------------------------------------------------

def generate_code(
    program: Program,
    var_report: VariableReport | None = None,
    instrument: bool = False,
) -> str:
    """Generate a standalone Python module from a COBOL Program AST.

    Args:
        program: Parsed COBOL program AST.
        var_report: Optional variable report (extracted if not given).
        instrument: If True, emit instrumented state tracking code.

    Returns the complete Python source code as a string.
    """
    if var_report is None:
        var_report = extract_variables(program)

    global _PARAGRAPH_ORDER
    _PARAGRAPH_ORDER = [p.name for p in program.paragraphs]

    cb = _CodeBuilder()

    # Module docstring
    cb.line(f'"""Generated Python from COBOL program {program.program_id}.')
    cb.line("")
    cb.line("Auto-generated by Specter. Do not edit.")
    cb.line('"""')
    cb.blank()

    # Runtime helpers
    cb.line("# --- Runtime helpers ---")
    cb.blank()
    cb.line("_CALL_DEPTH_LIMIT = 500")
    cb.blank()
    cb.blank()
    cb.line("class _GobackSignal(Exception):")
    cb.indent()
    cb.line('"""Signal for GOBACK/STOP RUN."""')
    cb.line("pass")
    cb.dedent()
    cb.blank()
    cb.blank()

    cb.line("def _is_numeric(v):")
    cb.indent()
    cb.line('"""Check if a value is numeric."""')
    cb.line("try:")
    cb.indent()
    cb.line("float(str(v))")
    cb.line("return True")
    cb.dedent()
    cb.line("except (ValueError, TypeError):")
    cb.indent()
    cb.line("return False")
    cb.dedent()
    cb.dedent()
    cb.blank()
    cb.blank()

    cb.line("def _to_num(v):")
    cb.indent()
    cb.line('"""Coerce a value to a number for arithmetic."""')
    cb.line("if isinstance(v, (int, float)):")
    cb.indent()
    cb.line("return v")
    cb.dedent()
    cb.line("try:")
    cb.indent()
    cb.line("return int(v)")
    cb.dedent()
    cb.line("except (ValueError, TypeError):")
    cb.indent()
    cb.line("try:")
    cb.indent()
    cb.line("return float(v)")
    cb.dedent()
    cb.line("except (ValueError, TypeError):")
    cb.indent()
    cb.line("return 0")
    cb.dedent()
    cb.dedent()
    cb.dedent()
    cb.blank()
    cb.blank()

    cb.line("def _apply_stub_outcome(state, key):")
    cb.indent()
    cb.line('"""Apply a queued stub outcome (set status variables after external op)."""')
    cb.line("_applied = None")
    cb.line("_ol = state.get('_stub_outcomes', {}).get(key, [])")
    cb.line("if _ol:")
    cb.indent()
    cb.line("_entry = _ol.pop(0)")
    cb.line("_applied = _entry")
    cb.line("if isinstance(_entry, list):")
    cb.indent()
    cb.line("for _var, _val in _entry:")
    cb.indent()
    cb.line("state[_var] = _val")
    cb.dedent()
    cb.dedent()
    cb.line("else:")
    cb.indent()
    cb.line("_var, _val = _entry")
    cb.line("state[_var] = _val")
    cb.dedent()
    cb.dedent()
    cb.line("else:")
    cb.indent()
    cb.line("# Apply default when stub outcomes exhausted")
    cb.line("_dm = state.get('_stub_defaults', {}).get(key)")
    cb.line("if _dm:")
    cb.indent()
    cb.line("_applied = list(_dm)")
    cb.line("for _var, _val in _dm:")
    cb.indent()
    cb.line("state[_var] = _val")
    cb.dedent()
    cb.dedent()
    cb.dedent()
    cb.line("_log = state.get('_stub_log')")
    cb.line("if _log is not None:")
    cb.indent()
    cb.line("_log.append((key, _applied))")
    cb.dedent()
    cb.dedent()
    cb.blank()
    cb.blank()

    cb.line("def _dummy_call(name, state, *args):")
    cb.indent()
    cb.line('"""Stub for external CALL."""')
    cb.line("state['_calls'].append({'name': name, 'args': list(args)})")
    cb.line("_apply_stub_outcome(state, 'CALL:' + name)")
    cb.dedent()
    cb.blank()
    cb.blank()

    cb.line("def _dummy_exec(kind, raw_text, state):")
    cb.indent()
    cb.line('"""Stub for EXEC SQL/CICS/DLI."""')
    cb.line("state['_execs'].append({'kind': kind, 'text': raw_text})")
    cb.line("_apply_stub_outcome(state, kind)")
    cb.dedent()
    cb.blank()
    cb.blank()

    # Safe dict that returns '' for missing keys (COBOL default)
    cb.line("class _SafeDict(dict):")
    cb.indent()
    cb.line("def __getitem__(self, key):")
    cb.indent()
    cb.line("try:")
    cb.indent()
    cb.line("return super().__getitem__(key)")
    cb.dedent()
    cb.line("except KeyError:")
    cb.indent()
    cb.line("return ''")
    cb.dedent()
    cb.dedent()
    cb.dedent()
    cb.blank()
    cb.blank()

    if instrument:
        cb.line("class _InstrumentedState(_SafeDict):")
        cb.indent()
        cb.line('"""Dict subclass that records variable reads/writes and paragraph trace."""')
        cb.blank()
        cb.line("def __init__(self, *args, **kwargs):")
        cb.indent()
        cb.line("super().__init__(*args, **kwargs)")
        cb.line("self._current_para = ''")
        cb.line("self._call_stack = []")
        cb.line("super().__setitem__('_trace', [])")
        cb.line("super().__setitem__('_var_writes', [])")
        cb.line("super().__setitem__('_var_reads', [])")
        cb.line("super().__setitem__('_call_events', [])")
        cb.dedent()
        cb.blank()
        cb.line("def _enter_para(self, name):")
        cb.indent()
        cb.line("if len(self['_trace']) > 50000:")
        cb.indent()
        cb.line("raise _GobackSignal()")
        cb.dedent()
        cb.line("caller = self._call_stack[-1] if self._call_stack else None")
        cb.line("self._call_stack.append(name)")
        cb.line("self._current_para = name")
        cb.line("super().__getitem__('_trace').append(name)")
        cb.line("super().__getitem__('_call_events').append(('enter', name, len(self._call_stack), caller))")
        cb.dedent()
        cb.blank()
        cb.line("def _exit_para(self, name):")
        cb.indent()
        cb.line("if self._call_stack and self._call_stack[-1] == name:")
        cb.indent()
        cb.line("self._call_stack.pop()")
        cb.dedent()
        cb.line("self._current_para = self._call_stack[-1] if self._call_stack else ''")
        cb.line("super().__getitem__('_call_events').append(('exit', name, len(self._call_stack) + 1, None))")
        cb.dedent()
        cb.blank()
        cb.line("def __setitem__(self, key, value):")
        cb.indent()
        cb.line("if not key.startswith('_'):")
        cb.indent()
        cb.line("super().__getitem__('_var_writes').append((key, self._current_para))")
        cb.dedent()
        cb.line("super().__setitem__(key, value)")
        cb.dedent()
        cb.blank()
        cb.line("def get(self, key, default=None):")
        cb.indent()
        cb.line("if not key.startswith('_'):")
        cb.indent()
        cb.line("super().__getitem__('_var_reads').append((key, self._current_para))")
        cb.dedent()
        cb.line("return super().get(key, default)")
        cb.dedent()
        cb.blank()
        cb.line("def __getitem__(self, key):")
        cb.indent()
        cb.line("if not key.startswith('_'):")
        cb.indent()
        cb.line("dict.__getitem__(self, '_var_reads').append((key, self._current_para))")
        cb.dedent()
        cb.line("return super().__getitem__(key)")
        cb.dedent()
        cb.blank()
        cb.line("def setdefault(self, key, default=None):")
        cb.indent()
        cb.line("if key not in self:")
        cb.indent()
        cb.line("self[key] = default")
        cb.dedent()
        cb.line("return super().__getitem__(key)")
        cb.dedent()
        cb.dedent()
        cb.blank()
        cb.blank()

    # Default state
    cb.line("def _default_state():")
    cb.indent()
    cb.line('"""Return default state dict with all discovered variables."""')
    cb.line("return {")
    cb.indent()
    for name in sorted(var_report.variables.keys()):
        info = var_report.variables[name]
        if info.classification == "flag":
            default = "False"
        elif info.classification == "status":
            if "SQLCODE" in name.upper():
                default = "0"
            else:
                default = "' '"
        elif any(kw in name.upper() for kw in (
            "CNT", "COUNT", "AMT", "AMOUNT", "FREQ", "DAYS",
            "TIME", "9C", "CODE", "LEN",
        )):
            default = "0"
        else:
            default = "''"
        cb.line(f"'{_sq(name)}': {default},")
    cb.dedent()
    cb.line("}")
    cb.dedent()
    cb.blank()
    cb.blank()

    # Collect all PERFORM targets to detect missing paragraphs
    defined_paras = {p.name for p in program.paragraphs}
    referenced_paras: set[str] = set()

    def _collect_targets(stmt):
        target = stmt.attributes.get("target", "")
        if target:
            referenced_paras.add(target)
        for child in stmt.children:
            _collect_targets(child)

    for para in program.paragraphs:
        for stmt in para.statements:
            _collect_targets(stmt)

    # Generate stubs for referenced but undefined paragraphs
    missing = referenced_paras - defined_paras
    for name in sorted(missing):
        func_name = _sanitize_name(name)
        cb.line(f"def {func_name}(state):")
        cb.indent()
        cb.line(f'"""Stub for missing paragraph {name}."""')
        cb.line("pass")
        cb.dedent()
        cb.blank()
        cb.blank()

    # One function per paragraph
    for para in program.paragraphs:
        cb.current_para = para.name
        func_name = _sanitize_name(para.name)
        cb.line(f"def {func_name}(state):")
        cb.indent()
        cb.line(f'"""Paragraph {para.name} (lines {para.line_start}-{para.line_end})."""')

        # Call-depth guard to prevent unbounded recursion
        cb.line("_d = state.get('_call_depth', 0) + 1")
        cb.line("state['_call_depth'] = _d")
        cb.line("if _d > _CALL_DEPTH_LIMIT:")
        cb.indent()
        cb.line("state['_call_depth'] = _d - 1")
        cb.line("return")
        cb.dedent()
        cb.line("try:")
        cb.indent()

        if instrument:
            cb.line(f"state._enter_para('{_sq(para.name)}')")

        if not para.statements:
            if not instrument:
                cb.line("pass")
        else:
            for stmt in para.statements:
                _gen_statement(cb, stmt)

        cb.dedent()
        cb.line("finally:")
        cb.indent()
        if instrument:
            cb.line(f"state._exit_para('{_sq(para.name)}')")
        cb.line("state['_call_depth'] = state.get('_call_depth', 1) - 1")
        cb.dedent()
        cb.dedent()
        cb.blank()
        cb.blank()

    # Branch metadata for concolic engine (maps branch ID -> condition info)
    cb.line(f"_BRANCH_META = {repr(cb.branch_meta)}")
    cb.blank()
    cb.blank()

    # Entry point — find first paragraph
    cb.line("def run(initial_state=None):")
    cb.indent()
    cb.line('"""Execute the program with optional initial state overrides."""')
    if instrument:
        cb.line("state = _InstrumentedState({**_default_state(), **(initial_state or {})})")
    else:
        cb.line("state = _SafeDict({**_default_state(), **(initial_state or {})})")
    cb.line("state.setdefault('_display', [])")
    cb.line("state.setdefault('_calls', [])")
    cb.line("state.setdefault('_execs', [])")
    cb.line("state.setdefault('_reads', [])")
    cb.line("state.setdefault('_writes', [])")
    cb.line("state.setdefault('_abended', False)")
    cb.line("state.setdefault('_branches', set())")
    cb.line("state.setdefault('_stub_log', [])")
    if instrument:
        cb.line("dict.__setitem__(state, '_initial_snapshot', {k: v for k, v in state.items() if not k.startswith('_')})")
    if program.paragraphs:
        # If the program has an entry_statements list (from the unnamed
        # PROCEDURE DIVISION driver section), generate those as the entry
        # point.  Otherwise fall through all paragraphs sequentially
        # (standard COBOL fall-through semantics).
        entry_stmts = getattr(program, "entry_statements", None)
        cb.line("try:")
        cb.indent()
        if entry_stmts:
            for stmt in entry_stmts:
                _gen_statement(cb, stmt)
        else:
            for para in program.paragraphs:
                func_name = _sanitize_name(para.name)
                cb.line(f"{func_name}(state)")
        cb.dedent()
        cb.line("except _GobackSignal:")
        cb.indent()
        cb.line("pass")
        cb.dedent()
        cb.line("except ZeroDivisionError:")
        cb.indent()
        cb.line("state['_abended'] = True")
        cb.dedent()
    if instrument:
        cb.line("_snap = dict.__getitem__(state, '_initial_snapshot')")
        cb.line("state['_state_diffs'] = {")
        cb.indent()
        cb.line("k: {'from': _snap[k], 'to': dict.__getitem__(state, k)}")
        cb.dedent()
        cb.line("    for k in _snap")
        cb.line("    if _snap[k] != dict.get(state, k)")
        cb.line("}")
    cb.line("return state")
    cb.dedent()
    cb.blank()
    cb.blank()

    cb.line("if __name__ == '__main__':")
    cb.indent()
    cb.line("result = run()")
    cb.line("for line in result.get('_display', []):")
    cb.indent()
    cb.line("print(line)")
    cb.dedent()
    cb.dedent()
    cb.blank()

    return cb.build()
