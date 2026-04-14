"""Extract PIC lengths for COBOL variables from copybooks + inline source.

COBOL variables have fixed-width storage declared by their PIC clause.
``MOVE 'NVGFYGWWQC' TO END-OF-FILE`` truncates to PIC X(1) → ``'N'``.
The Java runtime stores values in a ``HashMap<String,Object>`` with no
truncation, so test cases that inject long strings into short fields
yield divergent control flow vs the COBOL ground truth.

This module produces a ``dict[var_name -> {"length": int, "kind": str}]``
which the Java generator emits as a static ``PIC_INFO`` map and the
integration-test harness uses to truncate input-state values before
seeding them into ``ProgramState``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .copybook_parser import CopybookField, CopybookRecord


# ---------------------------------------------------------------------------
# Copybook records → PIC info
# ---------------------------------------------------------------------------

def _field_to_entry(f: CopybookField) -> dict[str, Any] | None:
    """Convert a CopybookField to a PIC entry, or None for unsupported types."""
    if f.is_filler or f.pic_type == "group":
        return None
    return {
        "length": int(f.length),
        "kind": f.pic_type,        # alpha / numeric / packed / comp
        "precision": int(f.precision),
    }


def pic_info_from_copybooks(
    records: list[CopybookRecord],
) -> dict[str, dict[str, Any]]:
    """Build the PIC info map from parsed copybook records."""
    out: dict[str, dict[str, Any]] = {}
    for rec in records:
        for f in rec.fields:
            entry = _field_to_entry(f)
            if entry is None:
                continue
            name = (f.name or "").upper()
            if not name:
                continue
            out.setdefault(name, entry)
    return out


# ---------------------------------------------------------------------------
# Inline source extraction (DATA DIVISION variables not in a copybook)
# ---------------------------------------------------------------------------

# Match a level-numbered field declaration with an optional PIC clause.
# Captures: (level, name, rest-of-line). Skip 88-level (those are condition
# names, not storage-bearing).
_FIELD_RE = re.compile(
    # Leading whitespace + level + name + optional rest. Rest is optional
    # because a group item can be declared as ``01 NAME.`` with no PIC.
    r"^\s+(0[1-9]|[1-4][0-9]|66|77)\s+([A-Z0-9][A-Z0-9-]*)\s*(.*)$",
    re.IGNORECASE,
)
_PIC_RE = re.compile(
    r"\bPIC(?:TURE)?\s+(?:IS\s+)?([SsXx0-9+\-()V.,Aa9]+)",
    re.IGNORECASE,
)
_USAGE_RE = re.compile(
    r"\bUSAGE\s+(?:IS\s+)?([A-Z0-9-]+)\b|\b(COMP-3|COMP-4|COMP-5|COMP|BINARY|PACKED-DECIMAL|DISPLAY)\b",
    re.IGNORECASE,
)
_VALUE_RE = re.compile(
    r"\bVALUE\s+(?:IS\s+)?(?:'([^']*)'|\"([^\"]*)\"|([+-]?\d+(?:\.\d+)?)"
    r"|(SPACES?|ZEROS?|ZEROES|LOW-VALUES?|HIGH-VALUES?))",
    re.IGNORECASE,
)


def _parse_value_literal(match) -> object | None:
    """Decode a VALUE clause match into a Python literal."""
    if match is None:
        return None
    s_quoted, d_quoted, num, fig = match.group(1), match.group(2), match.group(3), match.group(4)
    if s_quoted is not None:
        return s_quoted
    if d_quoted is not None:
        return d_quoted
    if num is not None:
        if "." in num:
            try:
                return float(num)
            except ValueError:
                return num
        try:
            return int(num)
        except ValueError:
            return num
    if fig is not None:
        u = fig.upper()
        if u in ("SPACES", "SPACE"):
            return " "
        if u in ("ZEROS", "ZERO", "ZEROES"):
            return 0
        if u in ("LOW-VALUES", "LOW-VALUE"):
            return ""
        if u in ("HIGH-VALUES", "HIGH-VALUE"):
            return "\u00ff"
    return None


def _parse_pic_clause(pic: str, usage: str) -> tuple[str, int, int]:
    """Reuse the same logic as copybook_parser._parse_pic.

    Returns ``(kind, length, precision)``.
    """
    from .copybook_parser import _parse_pic
    return _parse_pic(pic, usage)


def pic_info_from_source(
    cobol_source: str | Path,
) -> dict[str, dict[str, Any]]:
    """Scan a COBOL source file for inline DATA DIVISION field definitions.

    Returns a mapping ``var_name -> {"length", "kind", "precision"}``.
    Variables defined in copybooks are picked up by
    :func:`pic_info_from_copybooks`; this catches the rest (WORKING-STORAGE
    variables declared inline, e.g. ``05 END-OF-FILE PIC X(1) VALUE 'N'``).
    """
    p = Path(cobol_source)
    if not p.is_file():
        return {}
    try:
        text = p.read_text(errors="replace")
    except OSError:
        return {}

    out: dict[str, dict[str, Any]] = {}
    in_data_division = False
    for raw in text.splitlines():
        if len(raw) > 6 and raw[6] in ("*", "/"):
            continue
        stripped = raw[:72].rstrip() if len(raw) > 72 else raw.rstrip()
        upper = stripped.upper().strip()
        if not upper:
            continue
        if "DATA DIVISION" in upper:
            in_data_division = True
            continue
        if "PROCEDURE DIVISION" in upper:
            in_data_division = False
            continue
        if not in_data_division:
            continue

        m = _FIELD_RE.match(stripped)
        if not m:
            continue
        name = m.group(2).upper()
        if name in {"FILLER"} or name.startswith("FILLER-"):
            continue
        rest = m.group(3)
        m_pic = _PIC_RE.search(rest)
        if not m_pic:
            # Group item without PIC — skip.
            continue
        usage_match = _USAGE_RE.search(rest)
        usage = ""
        if usage_match:
            usage = (usage_match.group(1) or usage_match.group(2) or "").upper()
        kind, length, precision = _parse_pic_clause(m_pic.group(1), usage)
        entry: dict[str, Any] = {
            "length": int(length),
            "kind": kind,
            "precision": int(precision),
        }
        v_match = _VALUE_RE.search(rest)
        if v_match is not None:
            v = _parse_value_literal(v_match)
            if v is not None:
                entry["value"] = v
        out.setdefault(name, entry)
    return out


def build_pic_info(
    copybook_records: list[CopybookRecord] | None,
    cobol_source: str | Path | None,
) -> dict[str, dict[str, Any]]:
    """Combine copybook + inline-source PIC info.

    Copybook entries take precedence (encountered first via setdefault).
    """
    out = pic_info_from_copybooks(copybook_records or [])
    if cobol_source:
        for k, v in pic_info_from_source(cobol_source).items():
            out.setdefault(k, v)
    return out


# ---------------------------------------------------------------------------
# Truncation helper (Python-side, for tests)
# ---------------------------------------------------------------------------

_EIB_NAMES = {"EIBCALEN", "EIBAID", "EIBTRNID", "EIBTIME", "EIBDATE",
              "EIBTASKN", "EIBTRMID", "EIBCPOSN", "EIBFN", "EIBRCODE",
              "EIBDS", "EIBREQID", "EIBRSRCE", "EIBRESP", "EIBRESP2"}


def group_layouts_from_source(
    cobol_source: str | Path,
) -> dict[str, list[dict[str, Any]]]:
    """Extract GROUP-item layouts from inline COBOL source.

    A COBOL group item (a level-01..49 with no PIC clause) has a string
    representation that is the concatenation of its sub-fields' values
    (right-padded according to each child's PIC width). E.g.::

        01 IO-STATUS-04.
            05 IO-STATUS-0401  PIC 9    VALUE 0.
            05 IO-STATUS-0403  PIC 999  VALUE 0.

    yields ``{"IO-STATUS-04": [{"name": "IO-STATUS-0401", "length": 1,
    "kind": "numeric"}, {"name": "IO-STATUS-0403", "length": 3,
    "kind": "numeric"}]}``. The Java runtime uses this map to compose
    parent values on read and split written values across children, so
    reference-modifier MOVEs and DISPLAY of the parent reflect the
    children's actual state.
    """
    p = Path(cobol_source)
    if not p.is_file():
        return {}
    try:
        text = p.read_text(errors="replace")
    except OSError:
        return {}

    layouts: dict[str, list[dict[str, Any]]] = {}
    in_data_division = False
    # Stack of (level, name) for the currently-open parent groups so that
    # 05-level children get attributed to the most recent 01..04 group.
    stack: list[tuple[int, str]] = []

    for raw in text.splitlines():
        if len(raw) > 6 and raw[6] in ("*", "/"):
            continue
        stripped = raw[:72].rstrip() if len(raw) > 72 else raw.rstrip()
        upper = stripped.upper().strip()
        if not upper:
            continue
        if "DATA DIVISION" in upper:
            in_data_division = True
            continue
        if "PROCEDURE DIVISION" in upper:
            in_data_division = False
            continue
        if not in_data_division:
            continue

        m = _FIELD_RE.match(stripped)
        if not m:
            continue
        try:
            level = int(m.group(1))
        except ValueError:
            continue
        name = m.group(2).upper()
        if name == "FILLER" or name.startswith("FILLER-"):
            # Pop scope back to >= level
            while stack and stack[-1][0] >= level:
                stack.pop()
            continue
        rest = m.group(3)

        # Pop deeper levels that this declaration closes off.
        while stack and stack[-1][0] >= level:
            stack.pop()

        m_pic = _PIC_RE.search(rest)
        if not m_pic:
            # Group item — register an entry, push as parent.
            layouts.setdefault(name, [])
            stack.append((level, name))
            continue

        # Leaf field — append to the current parent group's layout
        # (if any).
        usage_match = _USAGE_RE.search(rest)
        usage = ""
        if usage_match:
            usage = (usage_match.group(1) or usage_match.group(2) or "").upper()
        kind, length, _precision = _parse_pic_clause(m_pic.group(1), usage)
        if stack:
            parent_name = stack[-1][1]
            layouts[parent_name].append({
                "name": name,
                "length": int(length),
                "kind": kind,
            })

    # Drop empty groups (parent declarations with no children captured).
    return {k: v for k, v in layouts.items() if v}


def injectable_var_names(
    program,
    var_report,
    copybook_records: list[CopybookRecord] | None,
    cobol_source: str | Path | None,
) -> set[str]:
    """Return the set of variables COBOL will accept from the INIT records.

    Mirrors :func:`specter.cobol_coverage._is_safe_to_inject` so the Java
    integration test can filter ``input_state`` to the same set — without
    that filter, Java seeds variables (e.g. ``END-OF-FILE``) that COBOL
    silently leaves at their source ``VALUE`` clause, causing the two
    runtimes to diverge from the loop entry onward.
    """
    from .variable_domain import build_variable_domains

    domains = build_variable_domains(
        var_report, copybook_records or [], {},
        cobol_source=str(cobol_source) if cobol_source else None,
    )

    safe: set[str] = set()
    for name, dom in domains.items():
        upper = name.upper()
        if upper == "FILLER" or upper.startswith("FILLER-"):
            continue
        if upper in _EIB_NAMES:
            continue
        if dom.set_by_stub:
            continue
        if getattr(dom, "classification", None) == "internal-no-inject":
            continue
        if not dom.condition_literals and not dom.valid_88_values:
            continue
        if dom.valid_88_values and not dom.condition_literals:
            all_null = all(
                v == "" or v == 0 or (isinstance(v, str) and not v.strip())
                for v in dom.valid_88_values.values()
            )
            if all_null:
                continue
        safe.add(upper)
    return safe


def truncate_for_pic(value: Any, entry: dict[str, Any] | None) -> Any:
    """Apply COBOL PIC truncation to a value.

    - alpha / unknown: truncate string to ``length`` characters; left-pad
      shorter values with spaces (COBOL right-pads PIC X — we mimic by
      preserving the input length when shorter, only truncating when
      longer; full COBOL behaviour would right-pad with spaces).
    - numeric / packed / comp: keep as-is for now (precision-aware
      conversion is left to the runtime's ``toNum``).
    """
    if entry is None or value is None:
        return value
    length = entry.get("length", 0) or 0
    kind = (entry.get("kind") or "alpha").lower()
    if kind in ("alpha",):
        s = str(value)
        if length > 0 and len(s) > length:
            return s[:length]
        return s
    return value
