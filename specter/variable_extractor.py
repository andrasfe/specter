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
        _extract_from_condition(report, attrs.get("condition", ""))

    elif stype == "EVALUATE":
        subject = attrs.get("subject", "")
        if subject and subject.upper() != "TRUE":
            _record_read(report, subject)

    elif stype == "WHEN":
        # WHEN values may contain variable references
        for name in _extract_names_from_text(stmt.text):
            _record_read(report, name)

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

        # PCB status fields
        if "PCB-STATUS" in upper:
            info.classification = "status"
            continue

        # Boolean flags (88-level patterns)
        if (upper.endswith("-ON") or upper.endswith("-OFF") or
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
