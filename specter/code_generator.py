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


def _sanitize_name(name: str) -> str:
    """Convert a COBOL paragraph name to a valid Python function name."""
    return "para_" + name.upper().replace("-", "_").replace(".", "_")


def _resolve_source(source: str) -> str:
    """Resolve a MOVE source to a Python expression."""
    s = source.strip()

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
        varname = m.group(1).strip().upper()
        return f"len(str(state.get('{varname}', '')))"

    # Variable with subscript like FOO(1:2)
    m = re.match(r"([A-Z][A-Z0-9-]*)\((\d+):(\d+)\)", s, re.IGNORECASE)
    if m:
        varname = m.group(1).upper()
        start = int(m.group(2)) - 1  # COBOL is 1-based
        length = int(m.group(3))
        return f"str(state.get('{varname}', ''))[{start}:{start + length}]"

    # Variable reference
    varname = s.upper()
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
            cb.line(f"pass  # MOVE: {stmt.text[:60]}")
            return

    resolved = _resolve_source(source)
    for target in re.split(r"\s+", targets):
        target = target.strip().rstrip(".")
        if target:
            tname = target.upper()
            # Handle subscript targets
            m = re.match(r"([A-Z][A-Z0-9-]*)\((\d+):(\d+)\)", tname)
            if m:
                varname = m.group(1)
                start = int(m.group(2)) - 1
                length = int(m.group(3))
                cb.line(f"_v = str(state.get('{varname}', ''))")
                cb.line(f"state['{varname}'] = _v[:{start}] + str({resolved})[:{length}] + _v[{start + length}:]")
            else:
                cb.line(f"state['{tname}'] = {resolved}")


def _gen_compute(cb: _CodeBuilder, stmt: Statement):
    target = stmt.attributes.get("target", "")
    expression = stmt.attributes.get("expression", "")

    if not target or not expression:
        # Fallback: parse from text
        m = re.search(r"COMPUTE\s+([A-Z][A-Z0-9-]*)\s*=\s*(.+)",
                      stmt.text, re.IGNORECASE)
        if m:
            target = m.group(1).strip().upper()
            expression = m.group(2).strip().rstrip(".")
        else:
            cb.line(f"pass  # COMPUTE: {stmt.text[:60]}")
            return

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
        lambda m: _ph(f"len(str(state.get('{m.group(1).upper()}', '')))"),
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
                    varname = cleaned.upper()
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

    cb.line(f"state['{target.upper()}'] = {py_expr}")


def _gen_add(cb: _CodeBuilder, stmt: Statement):
    m = re.search(r"ADD\s+(.+?)\s+TO\s+(.+)", stmt.text, re.IGNORECASE)
    if m:
        addend = m.group(1).strip()
        targets_str = m.group(2).strip().rstrip(".")

        if re.match(r"^-?\d+\.?\d*$", addend):
            val = addend
        else:
            val = f"_to_num(state.get('{addend.upper()}', 0))"

        for target in re.split(r"\s+", targets_str):
            target = target.strip()
            if target and target.upper() not in ("GIVING", "ROUNDED"):
                tname = target.upper()
                cb.line(f"state['{tname}'] = _to_num(state.get('{tname}', 0)) + {val}")
    else:
        cb.line(f"pass  # ADD: {stmt.text[:60]}")


def _gen_subtract(cb: _CodeBuilder, stmt: Statement):
    m = re.search(r"SUBTRACT\s+(.+?)\s+FROM\s+(.+)", stmt.text, re.IGNORECASE)
    if m:
        subtrahend = m.group(1).strip()
        targets_str = m.group(2).strip().rstrip(".")

        if re.match(r"^-?\d+\.?\d*$", subtrahend):
            val = str(int(subtrahend)) if "." not in subtrahend else str(float(subtrahend))
        else:
            val = f"_to_num(state.get('{subtrahend.upper()}', 0))"

        for target in re.split(r"\s+", targets_str):
            target = target.strip()
            if target and target.upper() not in ("GIVING", "ROUNDED"):
                tname = target.upper()
                cb.line(f"state['{tname}'] = _to_num(state.get('{tname}', 0)) - {val}")
    else:
        cb.line(f"pass  # SUBTRACT: {stmt.text[:60]}")


def _gen_if(cb: _CodeBuilder, stmt: Statement):
    condition = stmt.attributes.get("condition", "")
    bid = cb.next_branch_id()
    if not condition:
        cb.line(f"if True:  # IF: {stmt.text[:60]}")
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


def _gen_evaluate(cb: _CodeBuilder, stmt: Statement):
    subject = stmt.attributes.get("subject", "TRUE")
    is_true = subject.upper() == "TRUE"

    if not is_true:
        subj_expr = f"state.get('{subject.upper()}', '')"
        cb.line(f"_eval_subject = {subj_expr}")

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
        cb.line(f"pass  # PERFORM: {stmt.text[:60]}")
        return
    func_name = _sanitize_name(target)
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

    if not target:
        cb.line(f"pass  # PERFORM_THRU: {stmt.text[:60]}")
        return

    # Determine all paragraphs in the THRU range
    if thru and thru != target:
        range_paras = _get_thru_range(target, thru)
    else:
        range_paras = [target]

    if condition:
        py_cond = cobol_condition_to_python(condition)
        lv = cb.next_loop_var()
        cb.line(f"{lv} = 0")
        cb.line(f"while not ({py_cond}):")
        cb.indent()
        for para_name in range_paras:
            cb.line(f"{_sanitize_name(para_name)}(state)")
        cb.line(f"{lv} += 1")
        cb.line(f"if {lv} >= 100:")
        cb.indent()
        cb.line("break")
        cb.dedent()
        cb.dedent()
    else:
        for para_name in range_paras:
            cb.line(f"{_sanitize_name(para_name)}(state)")


def _gen_perform_inline(cb: _CodeBuilder, stmt: Statement):
    condition = stmt.attributes.get("condition", "")
    varying = stmt.attributes.get("varying", "")
    lv = cb.next_loop_var()
    vary_increment = None  # (loop_var, by_val) if VARYING parsed

    if condition:
        py_cond = cobol_condition_to_python(condition)
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
    cb.line(f"pass  # SET: {stmt.text[:60]}")


def _gen_display(cb: _CodeBuilder, stmt: Statement):
    # Parse DISPLAY text to extract parts
    text = stmt.text.strip()
    m = re.match(r"DISPLAY\s+(.*)", text, re.IGNORECASE)
    if not m:
        cb.line(f"state['_display'].append('{text}')")
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
            if token.upper() not in ("UPON", "CONSOLE", "SYSIN", "SYSOUT"):
                parts.append(f"str(state.get('{token.upper()}', ''))")
            pos = end

    if parts:
        expr = " + ".join(parts)
        cb.line(f"state['_display'].append({expr})")
    else:
        cb.line(f"state['_display'].append('')")


def _gen_call(cb: _CodeBuilder, stmt: Statement):
    target = stmt.attributes.get("target", "UNKNOWN")
    cb.line(f"_dummy_call('{target}', state)")


def _gen_exec(cb: _CodeBuilder, stmt: Statement, kind: str):
    raw = stmt.attributes.get("raw_text", "")
    # Escape for string
    escaped = raw.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")
    if len(escaped) > 200:
        escaped = escaped[:200] + "..."
    cb.line(f"_dummy_exec('{kind}', '{escaped}', state)")


def _gen_initialize(cb: _CodeBuilder, stmt: Statement):
    m = re.search(r"INITIALIZE\s+(.+)", stmt.text, re.IGNORECASE)
    if m:
        targets = m.group(1).strip().rstrip(".")
        for target in re.split(r"\s+", targets):
            target = target.strip()
            if target and target.upper() not in ("REPLACING", "ALPHANUMERIC",
                                                   "NUMERIC", "BY", "ALL"):
                tname = target.upper()
                cb.line(f"state['{tname}'] = ''")
    else:
        cb.line(f"pass  # INITIALIZE: {stmt.text[:60]}")


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
                    py_parts.append(f"str(state.get('{token.upper()}', ''))")

        if py_parts:
            expr = " + ".join(py_parts)
            cb.line(f"state['{target}'] = {expr}")
        else:
            cb.line(f"pass  # STRING: {stmt.text[:60]}")
    else:
        cb.line(f"pass  # STRING: {stmt.text[:60]}")


def _gen_accept(cb: _CodeBuilder, stmt: Statement):
    m = re.search(r"ACCEPT\s+([A-Z][A-Z0-9-]*)", stmt.text, re.IGNORECASE)
    if m:
        varname = m.group(1).upper()
        cb.line(f"# ACCEPT {varname} — uses preset state value")
    else:
        cb.line(f"# ACCEPT: {stmt.text[:60]}")


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
    m = re.search(r"OPEN\s+(?:INPUT|OUTPUT|I-O|EXTEND)\s+([A-Z][A-Z0-9-]*)", stmt.text, re.IGNORECASE)
    if m:
        fname = m.group(1).upper()
        cb.line(f"_apply_stub_outcome(state, 'OPEN:{fname}')")
    cb.line(f"pass  # {stmt.text[:70]}")


def _gen_close(cb: _CodeBuilder, stmt: Statement):
    m = re.search(r"CLOSE\s+([A-Z][A-Z0-9-]*)", stmt.text, re.IGNORECASE)
    if m:
        fname = m.group(1).upper()
        cb.line(f"_apply_stub_outcome(state, 'CLOSE:{fname}')")
    cb.line(f"pass  # {stmt.text[:70]}")


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
        cb.line(f"pass  # SEARCH (unparsed): {text[:60]}")
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

    # Generate branching code
    stub_key = f"SEARCH:{table_name}"
    cb.line(f"_sl = state.get('_stub_outcomes', {{}}).get('{stub_key}', [])")
    cb.line(f"_search_found = _sl.pop(0) if _sl else True")
    cb.line("if _search_found:")
    cb.indent()
    # WHEN branch: set index and execute extracted statements
    if index_var:
        cb.line(f"state['{index_var}'] = 1")
    _gen_search_body(cb, when_body)
    cb.dedent()
    if at_end_body:
        cb.line("else:")
        cb.indent()
        _gen_search_body(cb, at_end_body)
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
        tname = target.upper()
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
        func_name = _sanitize_name(m.group(1))
        cb.line(f"{func_name}(state)")
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
        target = m.group(1).upper()
        expr = m.group(2).strip()
        # Simple variable-only expression
        py_expr = re.sub(
            r"([A-Z][A-Z0-9-]+)",
            lambda mv: f"_to_num(state.get('{mv.group(1).upper()}', 0))",
            expr,
        )
        cb.line(f"state['{target}'] = {py_expr}")
        generated = True

    if not generated:
        cb.line("pass")


def _gen_goto(cb: _CodeBuilder, stmt: Statement):
    target = stmt.attributes.get("target", "")
    if target:
        func_name = _sanitize_name(target)
        cb.line(f"{func_name}(state)")
        cb.line(f"return")
    else:
        cb.line(f"pass  # GO TO: {stmt.text[:60]}")


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
        cb.line(f"pass  # UNSTRING: {stmt.text[:60]}")
    elif stype == "INSPECT":
        cb.line(f"pass  # INSPECT: {stmt.text[:60]}")
    elif stype == "SEARCH":
        _gen_search(cb, stmt)
    elif stype == "SORT":
        cb.line(f"pass  # SORT: {stmt.text[:60]}")
    elif stype == "GO_TO":
        _gen_goto(cb, stmt)
    elif stype == "ALTER":
        cb.line(f"pass  # ALTER: {stmt.text[:60]}")
    elif stype == "MULTIPLY":
        m = re.search(r"MULTIPLY\s+(.+?)\s+BY\s+(.+)", stmt.text, re.IGNORECASE)
        if m:
            factor = m.group(1).strip()
            targets_str = m.group(2).strip().rstrip(".")
            if re.match(r"^-?\d+\.?\d*$", factor):
                val = str(int(factor)) if "." not in factor else str(float(factor))
            else:
                val = f"_to_num(state.get('{factor.upper()}', 0))"
            for target in re.split(r"\s+", targets_str):
                target = target.strip()
                if target and target.upper() not in ("GIVING", "ROUNDED"):
                    tname = target.upper()
                    cb.line(f"state['{tname}'] = _to_num(state.get('{tname}', 0)) * {val}")
        else:
            cb.line(f"pass  # MULTIPLY: {stmt.text[:60]}")
    elif stype == "DIVIDE":
        m = re.search(r"DIVIDE\s+(.+?)\s+INTO\s+(.+)", stmt.text, re.IGNORECASE)
        if m:
            divisor = m.group(1).strip()
            targets_str = m.group(2).strip().rstrip(".")
            if re.match(r"^-?\d+\.?\d*$", divisor):
                val = str(int(divisor)) if "." not in divisor else str(float(divisor))
            else:
                val = f"_to_num(state.get('{divisor.upper()}', 0))"
            for target in re.split(r"\s+", targets_str):
                target = target.strip()
                if target and target.upper() not in ("GIVING", "REMAINDER", "ROUNDED"):
                    tname = target.upper()
                    cb.line(f"state['{tname}'] = _to_num(state.get('{tname}', 0)) // ({val} or 1)")
        else:
            cb.line(f"pass  # DIVIDE: {stmt.text[:60]}")
    elif stype == "START":
        m = re.search(r"START\s+([A-Z][A-Z0-9-]*)", stmt.text, re.IGNORECASE)
        if m:
            fname = m.group(1).upper()
            cb.line(f"_apply_stub_outcome(state, 'START:{fname}')")
        cb.line(f"pass  # {stmt.text[:70]}")
    elif stype == "DELETE":
        m = re.search(r"DELETE\s+([A-Z][A-Z0-9-]*)", stmt.text, re.IGNORECASE)
        if m:
            fname = m.group(1).upper()
            cb.line(f"_apply_stub_outcome(state, 'DELETE:{fname}')")
        cb.line(f"pass  # {stmt.text[:70]}")
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
        cb.line(f"pass  # {stype}: {stmt.text[:60]}")


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
    cb.line("_CALL_DEPTH_LIMIT = 200")
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
    cb.line("_ol = state.get('_stub_outcomes', {}).get(key, [])")
    cb.line("if _ol:")
    cb.indent()
    cb.line("_entry = _ol.pop(0)")
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
    cb.line("elif key.startswith('READ:') or key.startswith('START:'):")
    cb.indent()
    cb.line("# Default to EOF when stub outcomes exhausted — prevents infinite loops")
    cb.line("_dm = state.get('_stub_defaults', {}).get(key)")
    cb.line("if _dm:")
    cb.indent()
    cb.line("for _var, _val in _dm:")
    cb.indent()
    cb.line("state[_var] = _val")
    cb.dedent()
    cb.dedent()
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
        cb.line("super().__setitem__('_trace', [])")
        cb.line("super().__setitem__('_var_writes', [])")
        cb.line("super().__setitem__('_var_reads', [])")
        cb.dedent()
        cb.blank()
        cb.line("def _enter_para(self, name):")
        cb.indent()
        cb.line("if len(self['_trace']) > 50000:")
        cb.indent()
        cb.line("raise _GobackSignal()")
        cb.dedent()
        cb.line("self._current_para = name")
        cb.line("super().__getitem__('_trace').append(name)")
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
        cb.line(f"'{name}': {default},")
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
            cb.line(f"state._enter_para('{para.name}')")

        if not para.statements:
            if not instrument:
                cb.line("pass")
        else:
            for stmt in para.statements:
                _gen_statement(cb, stmt)

        cb.dedent()
        cb.line("finally:")
        cb.indent()
        cb.line("state['_call_depth'] = state.get('_call_depth', 1) - 1")
        cb.dedent()
        cb.dedent()
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
    if instrument:
        cb.line("dict.__setitem__(state, '_initial_snapshot', {k: v for k, v in state.items() if not k.startswith('_')})")
    if program.paragraphs:
        entry_func = _sanitize_name(program.paragraphs[0].name)
        cb.line("try:")
        cb.indent()
        cb.line(f"{entry_func}(state)")
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
