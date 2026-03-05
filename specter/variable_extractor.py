"""Walk a Program AST and extract all variable names with classification."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .models import Program, Statement

# Variable name pattern (COBOL style with hyphens)
_VAR_RE = re.compile(r"\b([A-Z][A-Z0-9-]*(?:\([^)]*\))?)\b")

# Tokens that are COBOL keywords, not variables
_KEYWORDS = frozenset({
    "MOVE", "TO", "FROM", "IF", "ELSE", "END-IF", "PERFORM", "THRU",
    "UNTIL", "VARYING", "EVALUATE", "WHEN", "OTHER", "END-EVALUATE",
    "END-PERFORM", "COMPUTE", "ADD", "SUBTRACT", "MULTIPLY", "DIVIDE",
    "GIVING", "REMAINDER", "SET", "TRUE", "FALSE", "DISPLAY", "ACCEPT",
    "CALL", "USING", "RETURNING", "GOBACK", "STOP", "RUN", "EXIT",
    "CONTINUE", "OPEN", "CLOSE", "READ", "WRITE", "REWRITE", "INTO",
    "INPUT", "OUTPUT", "EXTEND", "I-O", "INITIALIZE", "STRING",
    "DELIMITED", "BY", "SIZE", "INTO", "POINTER", "OVERFLOW",
    "END-STRING", "UNSTRING", "INSPECT", "TALLYING", "REPLACING",
    "ALL", "LEADING", "FIRST", "INITIAL", "SEARCH", "AT", "END",
    "GO", "ALTER", "PROCEED", "SORT", "ASCENDING", "DESCENDING",
    "KEY", "NOT", "AND", "OR", "IS", "NUMERIC", "ALPHABETIC",
    "EQUAL", "GREATER", "LESS", "THAN", "SPACES", "SPACE",
    "ZEROS", "ZERO", "ZEROES", "LOW-VALUES", "LOW-VALUE",
    "HIGH-VALUES", "HIGH-VALUE", "QUOTES", "QUOTE", "NULL", "NULLS",
    "EXEC", "SQL", "CICS", "DLI", "END-EXEC", "RETURN",
    "LENGTH", "OF", "FUNCTION", "ENTRY", "UPON",
    "NOHANDLE", "ABSTIME", "FORMATTIME", "MMDDYY", "DATESEP",
    "ASKTIME", "SEND", "RECEIVE", "MAP", "MAPSET", "CURSOR",
    "ERASE", "FREEKB", "MAPONLY", "DATAONLY", "MAPFAIL",
    "RESP", "HANDLE", "CONDITION", "ABEND", "XCTL", "LINK",
    "PROGRAM", "COMMAREA", "TRANSID", "STARTBR", "READNEXT",
    "READPREV", "RESETBR", "ENDBR", "DELETE", "UNLOCK",
    "RIDFLD", "KEYLENGTH", "GENERIC", "GTEQ", "EQUAL",
    "UPDATE", "DATASET", "FILE", "QUEUE", "ITEM", "NUMITEMS",
    "INSERT", "INTO", "VALUES", "SELECT", "WHERE", "FROM",
    "SET", "CURRENT", "DATE", "DAY", "TIME",
    "DFHENTER", "DFHPF1", "DFHPF2", "DFHPF3", "DFHPF4",
    "DFHPF5", "DFHPF6", "DFHPF7", "DFHPF8", "DFHPF9",
    "DFHPF10", "DFHPF11", "DFHPF12", "DFHCLEAR",
})

# Known status code variables
_STATUS_VARS = frozenset({
    "SQLCODE", "SQLSTATE", "EIBRESP", "EIBRESP2", "EIBAID",
    "EIBCALEN", "EIBFN", "EIBRCODE", "EIBTRNID",
})


@dataclass
class VariableInfo:
    """Information about a discovered variable."""

    name: str
    read_count: int = 0
    write_count: int = 0
    first_access: str = ""  # "read" or "write"
    classification: str = ""  # "input", "internal", "status", "flag"
    condition_literals: list = field(default_factory=list)


@dataclass
class VariableReport:
    """All variables discovered in a program."""

    variables: dict[str, VariableInfo] = field(default_factory=dict)

    @property
    def input_vars(self) -> list[str]:
        return [n for n, v in self.variables.items() if v.classification == "input"]

    @property
    def internal_vars(self) -> list[str]:
        return [n for n, v in self.variables.items() if v.classification == "internal"]

    @property
    def status_vars(self) -> list[str]:
        return [n for n, v in self.variables.items() if v.classification == "status"]

    @property
    def flag_vars(self) -> list[str]:
        return [n for n, v in self.variables.items() if v.classification == "flag"]

    @property
    def all_names(self) -> list[str]:
        return sorted(self.variables.keys())


def _clean_var_name(name: str) -> str:
    """Strip subscripts from variable name."""
    paren = name.find("(")
    if paren >= 0:
        return name[:paren]
    return name


def _record_read(report: VariableReport, name: str):
    name = _clean_var_name(name.upper())
    if name in _KEYWORDS or len(name) < 2:
        return
    if name not in report.variables:
        report.variables[name] = VariableInfo(name=name, first_access="read")
    report.variables[name].read_count += 1


def _record_write(report: VariableReport, name: str):
    name = _clean_var_name(name.upper())
    if name in _KEYWORDS or len(name) < 2:
        return
    if name not in report.variables:
        report.variables[name] = VariableInfo(name=name, first_access="write")
    report.variables[name].write_count += 1


def _extract_names_from_text(text: str) -> list[str]:
    """Extract potential variable names from COBOL text."""
    # Remove quoted strings first
    cleaned = re.sub(r"'[^']*'", "", text)
    names = _VAR_RE.findall(cleaned)
    return [n for n in names if _clean_var_name(n.upper()) not in _KEYWORDS and len(n) >= 2]


def _extract_from_condition(report: VariableReport, condition: str):
    """Extract variables referenced in a condition string."""
    if not condition:
        return
    text = condition
    if text.upper().startswith("UNTIL "):
        text = text[6:]
    for name in _extract_names_from_text(text):
        _record_read(report, name)


# Figurative constant mapping for literal harvesting
_FIGURATIVE_LITERALS: dict[str, str | int] = {
    "SPACES": " ", "SPACE": " ",
    "ZEROS": 0, "ZERO": 0, "ZEROES": 0,
    "LOW-VALUES": "", "LOW-VALUE": "",
    "HIGH-VALUES": "\xff", "HIGH-VALUE": "\xff",
}

# Pattern for comparison operators in COBOL conditions
_CMP_RE = re.compile(
    r"\bNOT\s+EQUAL(?:\s+TO)?\b|\bEQUAL(?:\s+TO)?\b"
    r"|\bNOT\s+=\b|\bGREATER(?:\s+THAN)?\b|\bLESS(?:\s+THAN)?\b"
    r"|[><=]+|=",
    re.IGNORECASE,
)


def _harvest_condition_literals(
    report: VariableReport, condition: str,
):
    """Extract (variable, literal) pairs from a COBOL condition string."""
    if not condition:
        return
    text = condition.strip()
    if text.upper().startswith("UNTIL "):
        text = text[6:].strip()

    # Split on logical AND/OR at the top level, but only when they separate
    # full comparisons (not multi-value lists).  We process each comparison
    # individually.
    #
    # Strategy: split by comparison operators to get LHS / RHS pairs, then
    # parse the RHS for literal values.

    # Split into segments around comparison operators
    parts = _CMP_RE.split(text)
    ops = _CMP_RE.findall(text)

    for idx, op in enumerate(ops):
        lhs_raw = parts[idx].strip() if idx < len(parts) else ""
        rhs_raw = parts[idx + 1].strip() if idx + 1 < len(parts) else ""

        if not lhs_raw or not rhs_raw:
            continue

        # Extract the variable name from LHS (last token, since earlier tokens
        # may be leftover logical connectors)
        lhs_tokens = re.findall(r"[A-Z][A-Z0-9-]*(?:\([^)]*\))?|'[^']*'|-?\d+\.?\d*", lhs_raw, re.IGNORECASE)
        if not lhs_tokens:
            continue

        # The variable is the last identifier-looking token on the LHS
        var_name = None
        for tok in reversed(lhs_tokens):
            tok_upper = tok.upper()
            if (tok_upper not in _KEYWORDS
                    and tok_upper not in ("AND", "OR", "NOT")
                    and tok_upper not in _FIGURATIVE_LITERALS
                    and not tok.startswith("'")
                    and not re.match(r"^-?\d+\.?\d*$", tok)):
                var_name = _clean_var_name(tok_upper)
                break

        if not var_name or len(var_name) < 2:
            continue

        # Parse RHS for literal values.  RHS may contain multi-value lists
        # like "'00' OR '04' OR '05'" or "'00' AND '04'" (for NOT EQUAL).
        # Split on OR/AND that separate bare literals.
        rhs_tokens = re.findall(r"'[^']*'|-?\d+\.?\d*|[A-Z][A-Z0-9-]*(?:\([^)]*\))?", rhs_raw, re.IGNORECASE)

        literals: list[str | int | float] = []
        for tok in rhs_tokens:
            tok_upper = tok.upper()
            if tok_upper in ("AND", "OR", "NOT", "IS", "NUMERIC"):
                continue
            if tok_upper in _FIGURATIVE_LITERALS:
                literals.append(_FIGURATIVE_LITERALS[tok_upper])
            elif tok.startswith("'") and tok.endswith("'"):
                literals.append(tok[1:-1])  # strip quotes
            elif re.match(r"^-?\d+$", tok):
                literals.append(int(tok))
            elif re.match(r"^-?\d+\.\d+$", tok):
                literals.append(float(tok))
            # else: it's a variable reference — skip

        if not literals:
            continue

        # For ordering comparisons (> < >= <=), also add boundary values
        op_upper = op.upper().strip()
        is_ordering = any(c in op_upper for c in (">", "<", "GREATER", "LESS"))

        # Ensure variable exists in report
        if var_name not in report.variables:
            report.variables[var_name] = VariableInfo(name=var_name, first_access="read")

        info = report.variables[var_name]
        existing = set(info.condition_literals)
        for lit in literals:
            if lit not in existing:
                info.condition_literals.append(lit)
                existing.add(lit)
            # For ordering comparisons with numeric literals, add boundary
            if is_ordering and isinstance(lit, int):
                for boundary in (lit - 1, lit, lit + 1):
                    if boundary not in existing:
                        info.condition_literals.append(boundary)
                        existing.add(boundary)


def _walk_statement(report: VariableReport, stmt: Statement):
    """Process a single statement for variable extraction."""
    attrs = stmt.attributes
    stype = stmt.type

    if stype == "MOVE":
        source = attrs.get("source", "")
        targets = attrs.get("targets", "")
        if source:
            for name in _extract_names_from_text(source):
                if not (source.startswith("'") or re.match(r"^-?\d+\.?\d*$", source.strip())):
                    _record_read(report, name)
        if targets:
            for t in re.split(r"\s+", targets):
                t = t.strip()
                if t and t.upper() not in _KEYWORDS:
                    _record_write(report, t)

    elif stype == "COMPUTE":
        target = attrs.get("target", "")
        expr = attrs.get("expression", "")
        if target:
            _record_write(report, target)
        if expr:
            for name in _extract_names_from_text(expr):
                _record_read(report, name)
        # Fallback: parse from text if attributes are empty
        if not target and not expr:
            m = re.search(r"COMPUTE\s+([A-Z][A-Z0-9-]*)\s*=\s*(.+)",
                          stmt.text, re.IGNORECASE)
            if m:
                _record_write(report, m.group(1))
                for name in _extract_names_from_text(m.group(2)):
                    _record_read(report, name)

    elif stype == "ADD":
        m = re.search(r"ADD\s+(.+?)\s+TO\s+(.+)", stmt.text, re.IGNORECASE)
        if m:
            for name in _extract_names_from_text(m.group(1)):
                _record_read(report, name)
            for name in _extract_names_from_text(m.group(2)):
                _record_read(report, name)
                _record_write(report, name)

    elif stype == "SUBTRACT":
        m = re.search(r"SUBTRACT\s+(.+?)\s+FROM\s+(.+)", stmt.text, re.IGNORECASE)
        if m:
            for name in _extract_names_from_text(m.group(1)):
                _record_read(report, name)
            for name in _extract_names_from_text(m.group(2)):
                _record_read(report, name)
                _record_write(report, name)

    elif stype == "SET":
        m = re.search(r"SET\s+([A-Z][A-Z0-9-]*)\s+TO\s+", stmt.text, re.IGNORECASE)
        if m:
            _record_write(report, m.group(1))

    elif stype == "IF":
        cond = attrs.get("condition", "")
        _extract_from_condition(report, cond)
        _harvest_condition_literals(report, cond)

    elif stype == "EVALUATE":
        subject = attrs.get("subject", "")
        if subject and subject.upper() != "TRUE":
            _record_read(report, subject)

    elif stype == "WHEN":
        # WHEN values may contain variable references
        for name in _extract_names_from_text(stmt.text):
            _record_read(report, name)
        # Harvest literals from WHEN conditions too
        _harvest_condition_literals(report, stmt.text)

    elif stype in ("PERFORM_THRU", "PERFORM_INLINE"):
        cond = attrs.get("condition", "")
        if cond:
            _extract_from_condition(report, cond)

    elif stype == "PERFORM":
        cond = attrs.get("condition", "")
        if cond:
            _extract_from_condition(report, cond)

    elif stype == "DISPLAY":
        for name in _extract_names_from_text(stmt.text):
            _record_read(report, name)

    elif stype == "INITIALIZE":
        for name in _extract_names_from_text(stmt.text):
            _record_write(report, name)

    elif stype == "STRING":
        for name in _extract_names_from_text(stmt.text):
            _record_read(report, name)

    elif stype in ("EXEC_SQL", "EXEC_CICS", "EXEC_DLI", "EXEC_OTHER"):
        raw = attrs.get("raw_text", "")
        # Host variables in SQL are prefixed with :
        for m in re.finditer(r":([A-Z][A-Z0-9-]*)", raw, re.IGNORECASE):
            _record_read(report, m.group(1))

    # Recurse into children
    for child in stmt.children:
        _walk_statement(report, child)


def _classify_variables(report: VariableReport):
    """Classify each variable based on access patterns."""
    for name, info in report.variables.items():
        upper = name.upper()

        # Status codes from external calls
        if upper in _STATUS_VARS or upper.endswith("-STATUS"):
            info.classification = "status"
            continue

        # PCB status fields (STATUS-CODE-PCBn, *-PCB-STATUS, etc.)
        if "PCB-STATUS" in upper or upper.startswith("STATUS-CODE-"):
            info.classification = "status"
            continue

        # File status variables (FILE-STATUS-*, FS-*)
        if upper.startswith("FILE-STATUS-") or (
            upper.startswith("FS-") and len(upper) > 3
        ):
            info.classification = "status"
            continue

        # Boolean flags (88-level patterns)
        if (upper.endswith("-ON") or upper.endswith("-OFF") or
                upper.endswith("-ERROR") or upper.endswith("-ERRORS") or
                upper.startswith("END-") or upper.startswith("NO-MORE-") or
                upper.endswith("-SUCCESS") or upper.endswith("-FAILED") or
                "FLG" in upper or "FLAG" in upper or
                upper.startswith("DEBUG-") or upper.startswith("QUALIFIED-")):
            info.classification = "flag"
            continue

        # Read before written, or only read → input
        if info.first_access == "read" or info.write_count == 0:
            info.classification = "input"
            continue

        # Written before read → internal
        info.classification = "internal"


def extract_variables(program: Program) -> VariableReport:
    """Extract and classify all variables from a Program AST."""
    report = VariableReport()

    for para in program.paragraphs:
        for stmt in para.statements:
            _walk_statement(report, stmt)

    _classify_variables(report)
    return report


def extract_stub_status_mapping(
    program: Program,
    var_report: VariableReport,
) -> dict[str, list[str]]:
    """Map external operation keys to the status variables they affect.

    Walks paragraphs linearly: after each EXEC_SQL/EXEC_CICS/READ/WRITE,
    looks at the next IF statement to see which status variable it checks.

    Returns e.g. {"SQL": ["SQLCODE"], "READ:MY-FILE": ["MY-FILE-STATUS"]}.
    """
    mapping: dict[str, list[str]] = {}

    # Collect all known status variable names
    status_vars = {
        name for name, info in var_report.variables.items()
        if info.classification == "status"
    }

    for para in program.paragraphs:
        stmts = para.statements
        for i, stmt in enumerate(stmts):
            op_key = None
            if stmt.type == "EXEC_SQL":
                op_key = "SQL"
            elif stmt.type == "EXEC_CICS":
                op_key = "CICS"
            elif stmt.type == "EXEC_DLI":
                op_key = "DLI"
            elif stmt.type == "CALL":
                target = stmt.attributes.get("target", "")
                if target:
                    op_key = f"CALL:{target}"
            elif stmt.type == "READ":
                m = re.search(r"READ\s+([A-Z][A-Z0-9-]*)", stmt.text, re.IGNORECASE)
                fname = m.group(1).upper() if m else "UNKNOWN"
                op_key = f"READ:{fname}"
            elif stmt.type == "WRITE":
                m = re.search(r"WRITE\s+([A-Z][A-Z0-9-]*)", stmt.text, re.IGNORECASE)
                recname = m.group(1).upper() if m else "UNKNOWN"
                op_key = f"WRITE:{recname}"
            elif (stmt.type == "START"
                  or (stmt.type == "UNKNOWN"
                      and stmt.text.strip().upper().startswith("START "))):
                m = re.search(r"START\s+([A-Z][A-Z0-9-]*)", stmt.text, re.IGNORECASE)
                if m:
                    op_key = f"START:{m.group(1).upper()}"
            elif stmt.type == "OPEN":
                # Extract file names from OPEN text (may have multiple)
                m = re.findall(
                    r"(?:INPUT|OUTPUT|I-O|EXTEND)\s+([A-Z][A-Z0-9-]*(?:\s+[A-Z][A-Z0-9-]*)*)",
                    stmt.text, re.IGNORECASE,
                )
                # Use the LAST file name as the op_key (most specific)
                fnames = []
                for group in m:
                    fnames.extend(group.upper().split())
                if fnames:
                    # Check if next IF references a status var for one of these files
                    op_key = f"OPEN:{fnames[-1]}"
            elif stmt.type == "CLOSE":
                m = re.search(r"CLOSE\s+([A-Z][A-Z0-9-]*)", stmt.text, re.IGNORECASE)
                if m:
                    op_key = f"CLOSE:{m.group(1).upper()}"

            if op_key is None:
                continue

            # Look at the next few statements for an IF checking a status var
            is_call = stmt.type == "CALL"
            for j in range(i + 1, min(i + 4, len(stmts))):
                next_stmt = stmts[j]
                if next_stmt.type == "IF":
                    cond = next_stmt.attributes.get("condition", "")
                    if cond:
                        found = _find_status_vars_in_condition(cond, status_vars)
                        # For CALL stmts, also check any variable in condition
                        # (e.g. RETURN-CODE, PL10-O-RETURN-CODE)
                        if not found and is_call:
                            found = _find_return_vars_in_condition(cond)
                        if found:
                            mapping.setdefault(op_key, []).extend(
                                v for v in found if v not in mapping.get(op_key, [])
                            )
                    break

    # Apply fallback defaults for common operations
    if "SQL" not in mapping:
        for sv in status_vars:
            if "SQLCODE" in sv:
                mapping.setdefault("SQL", []).append(sv)
                break
    if "CICS" not in mapping:
        for sv in status_vars:
            if "EIBRESP" in sv and "EIBRESP2" not in sv:
                mapping.setdefault("CICS", []).append(sv)
                break

    # For READ/WRITE keys without explicit mapping, look for *-STATUS vars
    for key in list(mapping.keys()):
        pass  # already mapped

    # Add generic file status fallbacks for unmapped READ/WRITE
    for para in program.paragraphs:
        for stmt in para.statements:
            if stmt.type == "READ":
                m = re.search(r"READ\s+([A-Z][A-Z0-9-]*)", stmt.text, re.IGNORECASE)
                if m:
                    fname = m.group(1).upper()
                    key = f"READ:{fname}"
                    if key not in mapping:
                        # Look for <fname>-STATUS or any *STATUS* var
                        candidate = f"{fname}-STATUS"
                        if candidate in status_vars:
                            mapping[key] = [candidate]
                        else:
                            for sv in status_vars:
                                if "STATUS" in sv and sv not in (
                                    "SQLCODE", "SQLSTATE",
                                ) and "EIB" not in sv:
                                    mapping[key] = [sv]
                                    break
            elif stmt.type == "WRITE":
                m = re.search(r"WRITE\s+([A-Z][A-Z0-9-]*)", stmt.text, re.IGNORECASE)
                if m:
                    recname = m.group(1).upper()
                    key = f"WRITE:{recname}"
                    if key not in mapping:
                        candidate = f"{recname}-STATUS"
                        if candidate in status_vars:
                            mapping[key] = [candidate]

    return mapping


def _find_return_vars_in_condition(condition: str) -> list[str]:
    """Find return-code-like variable names in a condition after a CALL.

    Looks for variables containing RETURN-CODE, -RC, or similar patterns.
    Falls back to the first non-keyword variable in the condition.
    """
    tokens = re.findall(r"[A-Z][A-Z0-9-]*", condition, re.IGNORECASE)
    found = []
    fallback = None
    for tok in tokens:
        upper = tok.upper()
        if upper in _KEYWORDS or upper in ("AND", "OR", "NOT", "IS"):
            continue
        if len(upper) < 2:
            continue
        if "RETURN-CODE" in upper or upper.endswith("-RC"):
            if upper not in found:
                found.append(upper)
        elif fallback is None:
            fallback = upper
    if found:
        return found
    if fallback:
        return [fallback]
    return []


def _find_status_vars_in_condition(
    condition: str, status_vars: set[str],
) -> list[str]:
    """Find status variable names referenced in a condition string.

    Checks both the explicit status_vars set and common status-like patterns.
    """
    found = []
    tokens = re.findall(r"[A-Z][A-Z0-9-]*", condition, re.IGNORECASE)
    for tok in tokens:
        upper = tok.upper()
        if upper in found:
            continue
        if upper in status_vars:
            found.append(upper)
        elif (upper.startswith("STATUS-CODE-")
              or upper.endswith("-STATUS")
              or "PCB-STATUS" in upper
              or upper.startswith("FILE-STATUS-")
              or (upper.startswith("FS-") and len(upper) > 3)):
            found.append(upper)
    return found
