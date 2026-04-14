"""Reconstruct PROCEDURE DIVISION top-level statements from COBOL source.

The cobalt parser used to produce ``.ast`` files drops the unlabeled
statements between ``PROCEDURE DIVISION.`` and the first labeled
paragraph (the implicit main entry that PERFORMs the rest). This module
parses the source directly and produces a ``list[Statement]`` matching
the AST schema, so callers can populate ``program.entry_statements``
and let the existing code generators emit the correct main flow.

Scope: focused on the patterns actually seen in batch COBOL entry
sections — DISPLAY / MOVE / ADD / SUBTRACT / MULTIPLY / DIVIDE /
COMPUTE / SET / PERFORM (simple, THRU, UNTIL, VARYING, TIMES) /
IF (with optional ELSE / END-IF) / GOBACK / STOP RUN / EXIT / CONTINUE.
EVALUATE and other less-common verbs are captured as a generic
``UNKNOWN`` statement with the raw text so they survive round-trip.
"""

from __future__ import annotations

import re
from pathlib import Path

from .models import Statement

# Verbs that, when seen at the start of a sub-token stream, definitely
# begin a new statement. Used by IF/PERFORM-UNTIL condition parsers to
# decide where the condition ends.
_STMT_STARTERS = {
    "DISPLAY", "MOVE", "ADD", "SUBTRACT", "MULTIPLY", "DIVIDE",
    "COMPUTE", "SET", "PERFORM", "IF", "EVALUATE", "GOBACK",
    "STOP", "EXIT", "CONTINUE", "CALL", "EXEC", "READ", "WRITE",
    "OPEN", "CLOSE", "REWRITE", "DELETE", "START",
}

# Keywords that terminate a nested block at matching depth.
_BLOCK_END = {"END-IF", "END-PERFORM", "END-EVALUATE", "ELSE", "WHEN"}


# ---------------------------------------------------------------------------
# Source slicing
# ---------------------------------------------------------------------------

# Match a paragraph header: line containing only an identifier + period.
# Allow whitespace around. COBOL Area A starts at column 8 in fixed format,
# but we also accept indented forms used by some sources.
_PARA_HEADER_RE = re.compile(
    r"^\s{0,11}([A-Z0-9][A-Z0-9-]*)\s*\.\s*$",
    re.IGNORECASE,
)

# Words that *look* like a paragraph header (identifier + period) but are
# actually keywords closing nested constructs. These must NOT terminate the
# entry-section slice.
_HEADER_LIKE_KEYWORDS = {
    "END-IF", "END-PERFORM", "END-EVALUATE", "END-READ", "END-WRITE",
    "END-CALL", "END-START", "END-SEARCH", "END-STRING", "END-UNSTRING",
    "GOBACK", "EXIT", "CONTINUE", "STOP", "ELSE",
}

_PROC_DIVISION_RE = re.compile(
    r"^\s*PROCEDURE\s+DIVISION(\s+USING[^.]*)?\s*\.\s*$",
    re.IGNORECASE,
)


def _slice_entry_section(source_text: str) -> str | None:
    """Return the text between PROCEDURE DIVISION and the first labeled paragraph.

    Returns ``None`` if either marker is missing.
    """
    lines = source_text.splitlines()
    proc_idx: int | None = None
    for i, raw in enumerate(lines):
        # Skip COBOL comment lines (column 7 = '*' or '/').
        if len(raw) > 6 and raw[6] in ("*", "/"):
            continue
        # Trim Identification area (col 73+).
        line = raw[:72] if len(raw) > 72 else raw
        if _PROC_DIVISION_RE.match(line):
            proc_idx = i
            break
    if proc_idx is None:
        return None

    end_idx: int | None = None
    for j in range(proc_idx + 1, len(lines)):
        raw = lines[j]
        if len(raw) > 6 and raw[6] in ("*", "/"):
            continue
        line = raw[:72] if len(raw) > 72 else raw
        m = _PARA_HEADER_RE.match(line)
        if m:
            name = m.group(1).upper()
            if name in _HEADER_LIKE_KEYWORDS or name == "DIVISION":
                continue
            end_idx = j
            break
    if end_idx is None:
        return None

    body_lines = []
    for raw in lines[proc_idx + 1:end_idx]:
        if len(raw) > 6 and raw[6] in ("*", "/"):
            continue
        line = raw[:72] if len(raw) > 72 else raw
        body_lines.append(line)
    return "\n".join(body_lines).strip() or None


# ---------------------------------------------------------------------------
# Tokenisation
# ---------------------------------------------------------------------------

# Token regex: quoted strings, dotted identifiers, identifiers, operators,
# parens, comma. Period is special — we keep it separate as a statement
# terminator.
_TOKEN_RE = re.compile(
    r"""
    (?P<str>'(?:[^']|'')*'|"(?:[^"]|"")*")  # quoted literal
    | (?P<period>\.)                         # period (statement terminator)
    | (?P<paren>[()])                        # parens
    | (?P<op>>=|<=|<>|=|>|<)                 # comparators
    | (?P<word>[A-Za-z0-9][A-Za-z0-9_-]*)    # identifier or keyword
    | (?P<comma>,)
    """,
    re.VERBOSE,
)


def _tokenise(text: str) -> list[str]:
    out: list[str] = []
    for m in _TOKEN_RE.finditer(text):
        out.append(m.group(0))
    return out


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class _TokenStream:
    def __init__(self, tokens: list[str]) -> None:
        self.tokens = tokens
        self.pos = 0

    def peek(self, offset: int = 0) -> str | None:
        idx = self.pos + offset
        return self.tokens[idx] if 0 <= idx < len(self.tokens) else None

    def consume(self) -> str:
        t = self.tokens[self.pos]
        self.pos += 1
        return t

    def eof(self) -> bool:
        return self.pos >= len(self.tokens)

    def skip_period(self) -> None:
        while not self.eof() and self.peek() == ".":
            self.consume()


def _is_keyword_terminator(tok: str) -> bool:
    return tok.upper() in _BLOCK_END


def _stmt(type_: str, text: str, attributes: dict | None = None,
          children: list[Statement] | None = None) -> Statement:
    return Statement(
        type=type_,
        text=text,
        line_start=0,
        line_end=0,
        attributes=attributes or {},
        children=children or [],
    )


def _parse_simple(ts: _TokenStream, verb: str) -> Statement:
    """Read a simple statement: VERB <args> until period or block end."""
    parts = [ts.consume()]
    while not ts.eof():
        tok = ts.peek()
        if tok == ".":
            ts.consume()
            break
        if _is_keyword_terminator(tok):
            break
        if tok and tok.upper() in _STMT_STARTERS:
            # Sentence-form (no period): next verb begins a new sibling
            # statement at the same level.
            break
        parts.append(ts.consume())
    text = " ".join(parts)
    attrs: dict = {}
    if verb == "MOVE":
        # MOVE <source> TO <target> [<target>...]
        m = re.match(r"MOVE\s+(.+?)\s+TO\s+(.+)", text, re.IGNORECASE)
        if m:
            attrs["source"] = m.group(1).strip()
            attrs["targets"] = m.group(2).strip()
    elif verb == "ADD":
        attrs["raw_text"] = text
    elif verb == "DISPLAY":
        attrs["raw_text"] = text
    elif verb == "CALL":
        m = re.match(r"CALL\s+['\"]?([A-Z0-9_-]+)['\"]?", text, re.IGNORECASE)
        if m:
            attrs["target"] = m.group(1).upper()
    elif verb == "SET":
        attrs["raw_text"] = text
    return _stmt(verb, text, attrs)


def _parse_perform(ts: _TokenStream) -> Statement:
    """Parse PERFORM in any of its forms."""
    parts = [ts.consume()]  # PERFORM
    after = ts.peek()
    if after and after.upper() == "UNTIL":
        return _parse_perform_until(ts, parts)
    if after and after.upper() == "VARYING":
        return _parse_perform_varying(ts, parts)
    # Simple PERFORM <para> [THRU <para>] [TIMES n].
    target = None
    thru = None
    times = None
    while not ts.eof():
        tok = ts.peek()
        if tok == ".":
            ts.consume()
            break
        if _is_keyword_terminator(tok):
            break
        if tok and tok.upper() in _STMT_STARTERS:
            break
        u = tok.upper()
        if u == "THRU" or u == "THROUGH":
            ts.consume()
            parts.append(tok)
            if not ts.eof():
                thru = ts.consume()
                parts.append(thru)
            continue
        if u == "TIMES":
            ts.consume()
            parts.append(tok)
            continue
        if target is None and re.match(r"^[A-Z0-9][A-Z0-9-]*$", tok, re.IGNORECASE):
            target = tok
            parts.append(ts.consume())
            continue
        # Numeric (TIMES count) or other.
        parts.append(ts.consume())
        if u.isdigit():
            times = u
    text = " ".join(parts)
    attrs: dict = {}
    if target:
        attrs["target"] = target.upper()
    if thru:
        attrs["thru"] = thru.upper()
    if times:
        attrs["times"] = times
    return _stmt("PERFORM", text, attrs)


def _parse_perform_until(
    ts: _TokenStream, prefix_parts: list[str],
) -> Statement:
    """Parse PERFORM UNTIL <cond> ... END-PERFORM."""
    # Consume UNTIL.
    parts = list(prefix_parts) + [ts.consume()]
    cond_tokens: list[str] = []
    # Read tokens until a statement starter or a period.
    while not ts.eof():
        tok = ts.peek()
        if tok == ".":
            break
        if tok and tok.upper() in _STMT_STARTERS:
            break
        cond_tokens.append(ts.consume())
    parts.extend(cond_tokens)
    condition = " ".join(cond_tokens).strip()
    # Body: parse statements until END-PERFORM.
    children: list[Statement] = []
    while not ts.eof():
        tok = ts.peek()
        if tok and tok.upper() == "END-PERFORM":
            ts.consume()
            ts.skip_period()
            break
        s = _parse_one_statement(ts)
        if s is None:
            break
        children.append(s)
    text = " ".join(parts) + " ... END-PERFORM"
    return _stmt(
        "PERFORM_INLINE",
        text,
        attributes={"condition": "UNTIL " + condition},
        children=children,
    )


def _parse_perform_varying(
    ts: _TokenStream, prefix_parts: list[str],
) -> Statement:
    """Parse PERFORM VARYING ... END-PERFORM (rare in entry sections)."""
    parts = list(prefix_parts)
    vary_parts: list[str] = []
    # Consume up to the body (heuristic: tokens until first statement starter).
    while not ts.eof():
        tok = ts.peek()
        if tok == ".":
            break
        if tok and tok.upper() in _STMT_STARTERS and not (
            tok.upper() in {"VARYING", "FROM", "BY", "UNTIL"}
        ):
            break
        vary_parts.append(ts.consume())
    parts.extend(vary_parts)
    children: list[Statement] = []
    while not ts.eof():
        tok = ts.peek()
        if tok and tok.upper() == "END-PERFORM":
            ts.consume()
            ts.skip_period()
            break
        s = _parse_one_statement(ts)
        if s is None:
            break
        children.append(s)
    text = " ".join(parts) + " ... END-PERFORM"
    return _stmt(
        "PERFORM_INLINE",
        text,
        attributes={"varying": " ".join(vary_parts)},
        children=children,
    )


def _parse_if(ts: _TokenStream) -> Statement:
    """Parse IF <cond> ... [ELSE ...] [END-IF] [.]."""
    parts = [ts.consume()]  # IF
    cond_tokens: list[str] = []
    while not ts.eof():
        tok = ts.peek()
        if tok == ".":
            break
        if tok and tok.upper() in _STMT_STARTERS:
            break
        if tok and tok.upper() in _BLOCK_END:
            break
        cond_tokens.append(ts.consume())
    condition = " ".join(cond_tokens).strip()
    parts.extend(cond_tokens)

    then_stmts: list[Statement] = []
    else_stmts: list[Statement] = []
    in_else = False

    while not ts.eof():
        tok = ts.peek()
        if tok is None:
            break
        u = tok.upper()
        if u == "END-IF":
            ts.consume()
            ts.skip_period()
            break
        if u == "ELSE":
            ts.consume()
            in_else = True
            continue
        if tok == ".":
            ts.consume()
            # Period terminates the IF when no END-IF was used (sentence form).
            break
        s = _parse_one_statement(ts)
        if s is None:
            break
        if in_else:
            else_stmts.append(s)
        else:
            then_stmts.append(s)

    children = list(then_stmts)
    if else_stmts:
        children.append(_stmt("ELSE", "ELSE", children=else_stmts))
    return _stmt(
        "IF",
        " ".join(parts) + " ... END-IF",
        attributes={"condition": condition},
        children=children,
    )


def _parse_one_statement(ts: _TokenStream) -> Statement | None:
    """Parse the next statement, or return None at end / block boundary."""
    while not ts.eof() and ts.peek() == ".":
        ts.consume()
    if ts.eof():
        return None
    tok = ts.peek()
    if tok is None:
        return None
    u = tok.upper()
    if u in _BLOCK_END:
        return None
    if u == "DISPLAY":
        return _parse_simple(ts, "DISPLAY")
    if u == "PERFORM":
        return _parse_perform(ts)
    if u == "IF":
        return _parse_if(ts)
    if u in {"MOVE", "ADD", "SUBTRACT", "MULTIPLY", "DIVIDE",
             "COMPUTE", "SET", "CONTINUE", "EXIT"}:
        return _parse_simple(ts, u)
    if u in {"GOBACK", "STOP"}:
        # GOBACK or STOP RUN.
        parts = [ts.consume()]
        while not ts.eof():
            t2 = ts.peek()
            if t2 == ".":
                ts.consume()
                break
            if t2 and t2.upper() in _STMT_STARTERS:
                break
            parts.append(ts.consume())
        return _stmt("GOBACK", " ".join(parts))
    if u == "CALL":
        return _parse_simple(ts, "CALL")
    if u == "EVALUATE":
        # Treat EVALUATE conservatively as opaque text up to END-EVALUATE.
        parts = [ts.consume()]
        depth = 1
        while not ts.eof() and depth > 0:
            t2 = ts.consume()
            parts.append(t2)
            if t2.upper() == "EVALUATE":
                depth += 1
            elif t2.upper() == "END-EVALUATE":
                depth -= 1
        ts.skip_period()
        return _stmt("EVALUATE", " ".join(parts))
    # Unknown verb — capture as raw text up to next period / block end.
    parts = [ts.consume()]
    while not ts.eof():
        t2 = ts.peek()
        if t2 == "." or (t2 and t2.upper() in _BLOCK_END):
            if t2 == ".":
                ts.consume()
            break
        if t2 and t2.upper() in _STMT_STARTERS:
            break
        parts.append(ts.consume())
    return _stmt("UNKNOWN", " ".join(parts), attributes={"raw_text": " ".join(parts)})


def _parse_statements(ts: _TokenStream) -> list[Statement]:
    out: list[Statement] = []
    while not ts.eof():
        s = _parse_one_statement(ts)
        if s is None:
            # If we stopped on a block-end keyword inside a non-nested
            # context, just consume it and continue.
            tok = ts.peek()
            if tok and tok.upper() in _BLOCK_END:
                ts.consume()
                continue
            if tok == ".":
                ts.consume()
                continue
            break
        out.append(s)
    return out


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def extract_entry_statements(source_path: str | Path) -> list[Statement]:
    """Parse PROCEDURE DIVISION top-level statements from a COBOL source file.

    Returns an empty list when the file is missing, the PROCEDURE DIVISION
    can't be located, or the section is empty.
    """
    p = Path(source_path)
    if not p.is_file():
        return []
    try:
        text = p.read_text(errors="replace")
    except OSError:
        return []
    body = _slice_entry_section(text)
    if not body:
        return []
    tokens = _tokenise(body)
    if not tokens:
        return []
    stmts = _parse_statements(_TokenStream(tokens))
    return stmts
