"""Unified branch registry shared by the Python code generator and the
COBOL branch instrumenter.

Historically the Python code generator (:mod:`specter.code_generator`)
and the COBOL probe inserter (:func:`specter.cobol_mock._add_branch_tracing`)
each maintained their own monotonic branch counter. The two walkers see
different inputs (AST vs post-transform mock.cbl) and walk in different
orders, so the same ``branch_id`` meant different things on each side.
The swarm targets a branch using Python's id but measures success
against COBOL's id — hence phantom failures.

This module introduces a single registry as the source of truth:

1. :func:`build_registry` walks the AST once, assigns each branch a
   deterministic numeric id, and records a content hash plus a
   source anchor.
2. The Python code generator consumes the registry instead of its
   internal counter — each branch it emits gets its id by looking up
   the registry via the same content hash the registry walker used.
3. The COBOL branch instrumenter will do the same lookup as Phase 3
   of the unification rollout; unmatched COBOL-only branches get a
   reserved id in the 90000+ range so they do not collide with
   AST-derived ids.

The content hash is collision-proof across reasonable COBOL programs:
``sha1(paragraph || '\0' || normalized_condition || '\0' || type ||
'\0' || ordinal)``. The ``ordinal`` breaks ties when the same
condition text appears twice in a paragraph (e.g. two ``IF EOF`` guards
separated by other statements).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Iterator

from .models import Paragraph, Program, Statement


# Construct types recognized by the walker. Kept in sync with the
# branch-emitting sites in ``code_generator``.
BRANCH_TYPES: frozenset[str] = frozenset({
    "IF",
    "EVALUATE",           # one entry per WHEN arm, including WHEN OTHER
    "PERFORM_UNTIL",
    "PERFORM_VARYING",
    "SEARCH",
})


# Reserved range for COBOL-only branches with no AST anchor (e.g.
# branches in scaffolding injected by mock transformations, or inside
# an inlined copybook that the AST never saw). Phase 3 uses this.
COBOL_ONLY_BID_MIN: int = 90001


@dataclass
class BranchEntry:
    """Single branch record in the registry."""

    bid: int
    paragraph: str
    condition: str        # normalized (whitespace collapsed, uppercase)
    type: str             # one of BRANCH_TYPES
    ordinal: int          # 0-based index of this (paragraph, type) within walk order
    source_line: int = 0  # original-source line number (0 if unknown)
    # Optional extra detail (e.g. EVALUATE subject, PERFORM target).
    attributes: dict = field(default_factory=dict)

    @property
    def content_hash(self) -> str:
        """Stable hash — the key both walkers use to agree on the bid."""
        payload = (
            f"{self.paragraph}\x00"
            f"{self.condition}\x00"
            f"{self.type}\x00"
            f"{self.ordinal}"
        )
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()


@dataclass
class BranchRegistry:
    """All branches in a program, keyed by bid and by content hash."""

    entries: list[BranchEntry] = field(default_factory=list)
    by_bid: dict[int, BranchEntry] = field(default_factory=dict)
    by_hash: dict[str, BranchEntry] = field(default_factory=dict)

    def add(self, entry: BranchEntry) -> None:
        self.entries.append(entry)
        self.by_bid[entry.bid] = entry
        self.by_hash[entry.content_hash] = entry

    def lookup(
        self,
        *,
        paragraph: str,
        condition: str,
        type: str,
        ordinal: int,
    ) -> BranchEntry | None:
        """Find an entry by its four-tuple content key."""
        probe = BranchEntry(
            bid=0,
            paragraph=_canon_paragraph(paragraph),
            condition=_canon_condition(condition),
            type=type,
            ordinal=ordinal,
        )
        return self.by_hash.get(probe.content_hash)

    # --- Serialization -----------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "version": 1,
            "entries": [
                {
                    "bid": e.bid,
                    "paragraph": e.paragraph,
                    "condition": e.condition,
                    "type": e.type,
                    "ordinal": e.ordinal,
                    "source_line": e.source_line,
                    "content_hash": e.content_hash,
                    "attributes": dict(e.attributes),
                }
                for e in self.entries
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BranchRegistry":
        reg = cls()
        for e in data.get("entries", []):
            reg.add(BranchEntry(
                bid=int(e["bid"]),
                paragraph=str(e["paragraph"]),
                condition=str(e["condition"]),
                type=str(e["type"]),
                ordinal=int(e.get("ordinal", 0)),
                source_line=int(e.get("source_line", 0)),
                attributes=dict(e.get("attributes", {}) or {}),
            ))
        return reg

    # --- Legacy-shape helper ----------------------------------------------

    def as_branch_meta(self) -> dict[int, dict]:
        """Return the legacy ``_BRANCH_META`` dict that downstream code
        still consumes (condition / paragraph / type per bid).
        """
        meta: dict[int, dict] = {}
        for e in self.entries:
            row = {
                "condition": e.condition,
                "paragraph": e.paragraph,
                "type": e.type,
            }
            row.update(e.attributes)
            meta[e.bid] = row
        return meta


# ---------------------------------------------------------------------------
# Canonicalization
# ---------------------------------------------------------------------------

def _canon_paragraph(name: str) -> str:
    return (name or "").strip().upper()


_WS_RE = re.compile(r"\s+")


def _canon_condition(text: str) -> str:
    """Normalize a condition string so semantic equals compare equal."""
    if not text:
        return ""
    # Collapse whitespace, uppercase, strip trailing period.
    t = _WS_RE.sub(" ", text).strip().upper()
    if t.endswith("."):
        t = t[:-1].rstrip()
    return t


# ---------------------------------------------------------------------------
# AST walker
# ---------------------------------------------------------------------------

_VARYING_TEXT_RE = re.compile(
    r"\bVARYING\s+[A-Z0-9_-]+\s+FROM\s+\S+\s+BY\s+\S+\s+UNTIL\s+(.+)",
    re.IGNORECASE,
)


def build_registry(program: Program) -> BranchRegistry:
    """Walk ``program`` in code-generation order, emit a full registry.

    The walk order mirrors :func:`specter.code_generator.generate_code`
    so that the Nth branch emitted during code generation is the Nth
    entry in the registry. The registry also keys by a content hash so
    independent walks (e.g. the COBOL instrumenter) can align without
    relying on ordering.
    """
    reg = BranchRegistry()
    next_bid = 1
    # Ordinals are per (paragraph, type) so "the 3rd IF in PARA-X" has
    # a stable identity independent of unrelated edits elsewhere.
    ordinals: dict[tuple[str, str], int] = {}

    # Honor Program.entry_statements if present (statements before the
    # first named paragraph). Treat them as anchored to a synthetic
    # "<ENTRY>" paragraph for hashing purposes.
    entry_stmts = getattr(program, "entry_statements", None) or []
    if entry_stmts:
        for stmt in entry_stmts:
            for entry in _walk_statement(stmt, "<ENTRY>", ordinals, next_bid):
                reg.add(entry)
                next_bid = entry.bid + 1

    for paragraph in program.paragraphs:
        pname = _canon_paragraph(paragraph.name)
        for stmt in paragraph.statements:
            for entry in _walk_statement(stmt, pname, ordinals, next_bid):
                reg.add(entry)
                next_bid = entry.bid + 1

    return reg


def _walk_statement(
    stmt: Statement,
    paragraph: str,
    ordinals: dict[tuple[str, str], int],
    start_bid: int,
) -> Iterator[BranchEntry]:
    """Yield branch entries for a statement subtree, matching code_generator.

    Order: IF condition fires first, then children are walked recursively;
    EVALUATE emits one entry per WHEN arm before descending into arm bodies;
    PERFORM UNTIL / VARYING emit one entry, then the body; SEARCH emits one
    entry for the FOUND path.
    """
    bid = start_bid
    stype = stmt.type.upper() if stmt.type else ""
    text = stmt.text or ""

    # --- IF ---------------------------------------------------------------
    if stype == "IF":
        cond = stmt.attributes.get("condition", "") if stmt.attributes else ""
        if not cond:
            # Extract from text as a best-effort fallback. Keep raw; the
            # canonicalizer will normalize.
            m = re.match(r"\s*IF\s+(.+?)\s+THEN\b|\s*IF\s+(.+)", text,
                         re.IGNORECASE | re.DOTALL)
            cond = (m.group(1) or m.group(2) or "") if m else ""
        ord_key = (paragraph, "IF")
        ord_ = ordinals.get(ord_key, 0)
        ordinals[ord_key] = ord_ + 1
        yield BranchEntry(
            bid=bid,
            paragraph=paragraph,
            condition=_canon_condition(cond),
            type="IF",
            ordinal=ord_,
            source_line=stmt.line_start,
        )
        bid += 1
        # Descend into children (body + optional ELSE subtree)
        for child in stmt.children:
            for e in _walk_statement(child, paragraph, ordinals, bid):
                yield e
                bid = e.bid + 1
        return

    # --- EVALUATE ---------------------------------------------------------
    if stype == "EVALUATE":
        subject = (stmt.attributes or {}).get("subject", "")
        # Group consecutive WHEN siblings that share a body — code_generator
        # treats them as an OR group with one shared bid. We replicate that
        # grouping so registry ordinals match emitted branches 1:1.
        groups = _group_evaluate_whens(stmt)
        for group in groups:
            # Build the combined condition label the way _gen_evaluate does.
            first = group[0]
            is_other = (
                (first.attributes or {}).get("is_other") is True
                or (first.text or "").strip().upper().startswith("WHEN OTHER")
            )
            if is_other:
                cond_label = "OTHER"
            else:
                # Mirror ``_gen_evaluate``'s label: strip the WHEN (or
                # ``WHEN WHEN``) prefix from each arm's text and join
                # with " OR ". Keeping this identical to the code
                # generator's label keeps content hashes aligned.
                from .condition_parser import parse_when_value
                parts: list[str] = []
                for wc in group:
                    vt, _is_other = parse_when_value(wc.text or "")
                    parts.append(vt.strip())
                cond_label = " OR ".join(p for p in parts if p)

            ord_key = (paragraph, "EVALUATE")
            ord_ = ordinals.get(ord_key, 0)
            ordinals[ord_key] = ord_ + 1
            yield BranchEntry(
                bid=bid,
                paragraph=paragraph,
                condition=_canon_condition(cond_label),
                type="EVALUATE",
                ordinal=ord_,
                source_line=first.line_start,
                attributes={"subject": subject} if subject else {},
            )
            bid += 1
            # Descend into each WHEN's body children (non-WHEN siblings).
            for wc in group:
                for child in wc.children:
                    if child.type and child.type.upper() == "WHEN":
                        continue
                    for e in _walk_statement(child, paragraph, ordinals, bid):
                        yield e
                        bid = e.bid + 1
        return

    # --- PERFORM UNTIL / PERFORM VARYING (outline & inline) --------------
    if stype in ("PERFORM", "PERFORM_INLINE"):
        attrs = stmt.attributes or {}
        condition = attrs.get("condition", "") or ""
        varying = attrs.get("varying", "") or ""
        # Text-based VARYING fallback (outline PERFORM)
        if not varying and not condition:
            m_vary = _VARYING_TEXT_RE.search(text)
            if m_vary:
                condition = m_vary.group(1).strip().rstrip(".")
                variant = "PERFORM_VARYING"
            else:
                variant = None
        elif varying:
            # Mirror code_generator's VARYING regex exactly — it requires
            # single-token FROM and BY values. A PERFORM VARYING with
            # multi-word FROM/BY (e.g. `FROM LENGTH OF X`) doesn't match
            # and code_generator skips the branch entry. Use the same
            # gate here to keep the registry aligned.
            m_vary = re.match(
                r"\s*(?:VARYING\s+)?[A-Z0-9_-]+\s+FROM\s+\S+\s+BY\s+\S+\s+UNTIL\s+(.+)",
                varying, re.IGNORECASE,
            )
            if m_vary:
                condition = m_vary.group(1).strip().rstrip(".")
                variant = "PERFORM_VARYING"
            else:
                variant = None
                condition = ""
        else:
            variant = "PERFORM_UNTIL"

        if variant and condition:
            ord_key = (paragraph, variant)
            ord_ = ordinals.get(ord_key, 0)
            ordinals[ord_key] = ord_ + 1
            yield BranchEntry(
                bid=bid,
                paragraph=paragraph,
                condition=_canon_condition(condition),
                type=variant,
                ordinal=ord_,
                source_line=stmt.line_start,
            )
            bid += 1
        # Descend into the loop body (inline PERFORM children)
        for child in stmt.children:
            for e in _walk_statement(child, paragraph, ordinals, bid):
                yield e
                bid = e.bid + 1
        return

    # --- SEARCH -----------------------------------------------------------
    if stype == "SEARCH":
        table_name = (stmt.attributes or {}).get("target", "") or ""
        cond = f"SEARCH {table_name} FOUND".strip()
        ord_key = (paragraph, "SEARCH")
        ord_ = ordinals.get(ord_key, 0)
        ordinals[ord_key] = ord_ + 1
        yield BranchEntry(
            bid=bid,
            paragraph=paragraph,
            condition=_canon_condition(cond),
            type="SEARCH",
            ordinal=ord_,
            source_line=stmt.line_start,
        )
        bid += 1
        for child in stmt.children:
            for e in _walk_statement(child, paragraph, ordinals, bid):
                yield e
                bid = e.bid + 1
        return

    # --- Generic descent --------------------------------------------------
    # Non-branching statements: just descend so nested IF/EVALUATE surface.
    for child in stmt.children:
        for e in _walk_statement(child, paragraph, ordinals, bid):
            yield e
            bid = e.bid + 1


def _group_evaluate_whens(evaluate_stmt: Statement) -> list[list[Statement]]:
    """Group WHEN children the way ``_gen_evaluate`` does.

    Consecutive WHEN siblings with no body between them form one OR group
    and share a single branch id. A WHEN with body statements ends the
    current group; the next WHEN starts a new one.
    """
    groups: list[list[Statement]] = []
    current: list[Statement] = []
    for child in evaluate_stmt.children:
        ctype = (child.type or "").upper()
        if ctype != "WHEN":
            continue
        has_body = any(
            (c.type or "").upper() != "WHEN" for c in child.children
        )
        current.append(child)
        if has_body:
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    return groups
