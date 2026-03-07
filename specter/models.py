"""Internal representation of a COBOL AST."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Statement:
    """A single COBOL statement node."""

    type: str
    text: str
    line_start: int
    line_end: int
    attributes: dict
    children: list[Statement] = field(default_factory=list)

    def walk(self):
        """Pre-order traversal yielding self then all descendants."""
        yield self
        for child in self.children:
            yield from child.walk()


@dataclass
class Paragraph:
    """A named COBOL paragraph containing statements."""

    name: str
    line_start: int
    line_end: int
    statements: list[Statement] = field(default_factory=list)


@dataclass
class Program:
    """Top-level program extracted from a COBOL AST JSON file."""

    program_id: str
    paragraphs: list[Paragraph] = field(default_factory=list)
    paragraph_index: dict[str, Paragraph] = field(default_factory=dict)
    entry_statements: list[Statement] | None = None
