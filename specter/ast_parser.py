"""Parse a JSON AST file into a Program dataclass."""

from __future__ import annotations

import json
from pathlib import Path

from .models import Paragraph, Program, Statement


def _parse_statement(raw: dict) -> Statement:
    children = [_parse_statement(c) for c in raw.get("children", [])]
    return Statement(
        type=raw["type"],
        text=raw.get("text", ""),
        line_start=raw.get("line_start", 0),
        line_end=raw.get("line_end", 0),
        attributes=raw.get("attributes", {}),
        children=children,
    )


def _parse_paragraph(raw: dict) -> Paragraph:
    stmts = [_parse_statement(s) for s in raw.get("statements", [])]
    return Paragraph(
        name=raw["name"],
        line_start=raw.get("line_start", 0),
        line_end=raw.get("line_end", 0),
        statements=stmts,
    )


def parse_ast(
    source: str | Path | dict,
    cobol_source: str | Path | None = None,
) -> Program:
    """Parse a JSON AST into a Program.

    *source* can be a file path (str or Path), or an already-loaded dict.

    *cobol_source*: optional path to the original ``.cbl`` source. When the
    AST JSON has no ``entry_statements`` (the cobalt parser drops the
    unlabeled PROCEDURE DIVISION top-level statements that drive the main
    flow in batch programs), this fills the gap by parsing the source
    text directly via :mod:`specter.entry_extractor`.
    """
    if isinstance(source, dict):
        data = source
    else:
        with open(source) as f:
            data = json.load(f)

    paragraphs = [_parse_paragraph(p) for p in data.get("paragraphs", [])]
    index = {p.name: p for p in paragraphs}

    # Parse optional unnamed PROCEDURE DIVISION driver statements
    entry_stmts = None
    if "entry_statements" in data:
        entry_stmts = [_parse_statement(s) for s in data["entry_statements"]]
    elif cobol_source is not None:
        try:
            from .entry_extractor import extract_entry_statements
            inferred = extract_entry_statements(cobol_source)
            if inferred:
                entry_stmts = inferred
        except Exception:
            entry_stmts = None

    return Program(
        program_id=data.get("program_id", "UNKNOWN"),
        paragraphs=paragraphs,
        paragraph_index=index,
        entry_statements=entry_stmts,
    )
