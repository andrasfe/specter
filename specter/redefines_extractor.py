"""Extract REDEFINES groups + USAGE BINARY layouts from COBOL source.

In COBOL, ``A REDEFINES B`` makes A and B two different views of the same
physical bytes. Combined with ``USAGE BINARY`` / ``COMP`` (number stored
as binary bytes rather than ASCII digits) this lets a program write an
integer to one field and read its individual bytes through another.
The CBTRN02C error path uses this trick:

    01 TWO-BYTES-BINARY     PIC 9(4) BINARY.
    01 TWO-BYTES-ALPHA REDEFINES TWO-BYTES-BINARY.
       05 TWO-BYTES-LEFT  PIC X.
       05 TWO-BYTES-RIGHT PIC X.

This module produces a layout map the Java runtime uses to back each
REDEFINES group with a ``byte[]`` and route reads/writes through
encode/decode helpers.

Output format::

    {
        "<canonical_group_id>": {
            "width": <bytes>,
            "members": {
                "<field_name>": {
                    "offset": <byte_offset>,
                    "length": <byte_length>,
                    "kind": "binary" | "alpha" | "numeric" | "group",
                    "signed": bool,
                    "digits": int,   # PIC 9(N) / S9(N) digit count, 0 for alpha
                },
                ...
            },
        },
        ...
    }

The canonical group_id is the original (non-REDEFINES) field name.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_DECL_RE = re.compile(
    r"^\s+(0[1-9]|[1-4][0-9]|66|77)\s+([A-Z0-9][A-Z0-9-]*)\s*(.*)$",
    re.IGNORECASE,
)
_PIC_RE = re.compile(
    r"\bPIC(?:TURE)?\s+(?:IS\s+)?([SsXx0-9+\-()V.,Aa9]+)",
    re.IGNORECASE,
)
_REDEFINES_RE = re.compile(
    r"\bREDEFINES\s+([A-Z][A-Z0-9-]*)",
    re.IGNORECASE,
)
_USAGE_RE = re.compile(
    r"\bUSAGE\s+(?:IS\s+)?([A-Z0-9-]+)\b"
    r"|\b(COMP-3|COMP-4|COMP-5|COMP|BINARY|PACKED-DECIMAL|DISPLAY)\b",
    re.IGNORECASE,
)


@dataclass
class _Decl:
    level: int
    name: str
    pic: str | None
    usage: str
    redefines: str | None
    is_signed: bool
    digits: int       # numeric digit count from PIC (0 for alpha)
    byte_length: int  # leaf storage size; 0 if a group (will be summed)
    offset: int = 0   # byte offset within the enclosing 01 (computed later)
    children: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# PIC parsing helpers (storage-aware)
# ---------------------------------------------------------------------------

def _count_digits_in_pic(pic: str) -> int:
    total = 0
    for m in re.finditer(r"9\((\d+)\)", pic):
        total += int(m.group(1))
    stripped = re.sub(r"9\(\d+\)", "", pic)
    total += stripped.count("9")
    return total


def _count_alpha_chars(pic: str) -> int:
    total = 0
    for m in re.finditer(r"[XA]\((\d+)\)", pic, re.IGNORECASE):
        total += int(m.group(1))
    stripped = re.sub(r"[XA]\(\d+\)", "", pic, flags=re.IGNORECASE)
    total += stripped.upper().count("X") + stripped.upper().count("A")
    return total


def _calc_storage(pic: str, usage: str) -> tuple[int, int]:
    """Return ``(digit_count, byte_storage_length)`` for a PIC + USAGE pair."""
    p = pic.upper()
    if "X" in p or "A" in p:
        chars = _count_alpha_chars(p)
        return (0, max(chars, 1))
    digits = _count_digits_in_pic(p)
    if usage in ("COMP-3", "PACKED-DECIMAL"):
        # Packed-decimal: ceil((digits + 1) / 2) bytes (sign nibble included)
        return (digits, (digits + 2) // 2)
    if usage in ("COMP", "COMP-4", "COMP-5", "BINARY"):
        if digits <= 4:
            return (digits, 2)
        if digits <= 9:
            return (digits, 4)
        return (digits, 8)
    # USAGE DISPLAY (default): one ASCII byte per digit, no separate sign.
    return (digits, max(digits, 1))


def _kind(decl: _Decl) -> str:
    if not decl.pic:
        return "group"
    p = decl.pic.upper()
    if "X" in p or "A" in p:
        return "alpha"
    if decl.usage in ("COMP", "COMP-4", "COMP-5", "BINARY"):
        return "binary"
    if decl.usage in ("COMP-3", "PACKED-DECIMAL"):
        return "packed"
    return "numeric"


# ---------------------------------------------------------------------------
# Source parsing
# ---------------------------------------------------------------------------

def _parse_decls(source_text: str) -> list[_Decl]:
    """Walk DATA DIVISION lines and return an ordered list of declarations."""
    decls: list[_Decl] = []
    in_data = False
    for raw in source_text.splitlines():
        if len(raw) > 6 and raw[6] in ("*", "/"):
            continue
        s = raw[:72] if len(raw) > 72 else raw
        upper = s.upper().strip()
        if not upper:
            continue
        if "DATA DIVISION" in upper:
            in_data = True
            continue
        if "PROCEDURE DIVISION" in upper:
            in_data = False
            continue
        if not in_data:
            continue
        m = _DECL_RE.match(s)
        if not m:
            continue
        try:
            level = int(m.group(1))
        except ValueError:
            continue
        name = m.group(2).upper()
        if name == "FILLER":
            # FILLER occupies storage but isn't accessible by name.
            # Track it for offset accounting.
            pass
        rest = m.group(3)
        pic = None
        m_pic = _PIC_RE.search(rest)
        if m_pic:
            pic = m_pic.group(1)
        usage = ""
        m_usage = _USAGE_RE.search(rest)
        if m_usage:
            usage = (m_usage.group(1) or m_usage.group(2) or "").upper()
        redefines = None
        m_red = _REDEFINES_RE.search(rest)
        if m_red:
            redefines = m_red.group(1).upper()
        is_signed = bool(pic and pic.upper().startswith("S"))
        digits, byte_length = (0, 0)
        if pic:
            digits, byte_length = _calc_storage(pic, usage)
        decls.append(_Decl(
            level=level, name=name, pic=pic, usage=usage,
            redefines=redefines, is_signed=is_signed,
            digits=digits, byte_length=byte_length,
        ))
    return decls


def _build_tree(decls: list[_Decl]) -> list[_Decl]:
    """Attach each declaration as a child of the closest preceding lower-level
    declaration. Returns the list of top-level (level 01 / 77) roots."""
    roots: list[_Decl] = []
    stack: list[_Decl] = []
    for d in decls:
        while stack and stack[-1].level >= d.level:
            stack.pop()
        if stack:
            stack[-1].children.append(d)
        else:
            roots.append(d)
        stack.append(d)
    for root in roots:
        _compute_offsets(root)
    return roots


def _compute_offsets(node: _Decl) -> int:
    """Compute each child's offset within ``node``. Returns ``node``'s
    effective byte length (sum of children for groups, declared length for
    leaves)."""
    if not node.children:
        return node.byte_length
    total = 0
    for child in node.children:
        # Skip REDEFINES children: they share a sibling's storage,
        # not consume new bytes.
        if child.redefines is not None:
            # For a child REDEFINES sibling, find sibling's offset and use it.
            sibling = next(
                (c for c in node.children if c.name == child.redefines),
                None,
            )
            if sibling is not None:
                child.offset = sibling.offset
            else:
                child.offset = 0
            child_len = _compute_offsets(child)
            if child.byte_length == 0:
                child.byte_length = child_len
            # NO offset advance.
            continue
        child.offset = total
        child_len = _compute_offsets(child)
        if child.byte_length == 0:
            child.byte_length = child_len
        total += child.byte_length
    if node.byte_length == 0:
        node.byte_length = total
    return node.byte_length


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def extract_redefines_groups(
    source_path: str | Path,
) -> dict[str, dict[str, Any]]:
    """Parse a COBOL source and return REDEFINES group layouts.

    Only includes 01/77-level REDEFINES today (the most common pattern).
    Sub-level REDEFINES is unhandled (TODO if the benchmark needs it).
    """
    p = Path(source_path)
    if not p.is_file():
        return {}
    try:
        text = p.read_text(errors="replace")
    except OSError:
        return {}

    decls = _parse_decls(text)
    if not decls:
        return {}
    roots = _build_tree(decls)

    # Index 01/77 roots by name for canonical lookup.
    top_by_name = {r.name: r for r in roots if r.level in (1, 77)}

    def canonical(name: str) -> str:
        seen: set[str] = set()
        cur = name
        while cur in top_by_name and top_by_name[cur].redefines:
            if cur in seen:
                return cur
            seen.add(cur)
            cur = top_by_name[cur].redefines
        return cur

    # Identify groups: every 01/77 that is REDEFINED by another 01/77 OR
    # that REDEFINES another field.
    redefined_targets: set[str] = set()
    for r in roots:
        if r.level in (1, 77) and r.redefines:
            redefined_targets.add(canonical(r.redefines))

    groups: dict[str, dict[str, Any]] = {}
    for r in roots:
        if r.level not in (1, 77):
            continue
        if r.redefines is None and r.name not in redefined_targets:
            # Plain top-level field with no REDEFINES involvement.
            continue
        cid = canonical(r.name)
        # Width = max byte_length over all roots in the group
        width = max(
            (other.byte_length for other in roots
             if other.level in (1, 77)
             and (other.name == cid or canonical(other.name) == cid)),
            default=0,
        )
        if width <= 0:
            continue
        if cid not in groups:
            groups[cid] = {"width": width, "members": {}}
        _add_members(r, groups[cid]["members"], base=0)

    return groups


def _add_members(
    node: _Decl, members: dict[str, dict[str, Any]], base: int,
) -> None:
    """Recursively add ``node`` and its descendants to ``members`` with
    absolute offsets within the REDEFINES group."""
    if node.name == "FILLER":
        # Skip — FILLER occupies storage but is not addressable by name.
        for child in node.children:
            _add_members(child, members, base + node.offset)
        return
    abs_offset = base + node.offset
    members[node.name] = {
        "offset": int(abs_offset),
        "length": int(node.byte_length),
        "kind": _kind(node),
        "signed": bool(node.is_signed),
        "digits": int(node.digits),
    }
    for child in node.children:
        _add_members(child, members, abs_offset)
