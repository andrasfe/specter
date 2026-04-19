"""Tests for the unified branch registry."""

from __future__ import annotations

from pathlib import Path

from specter.ast_parser import parse_ast
from specter.branch_registry import (
    BRANCH_TYPES,
    BranchEntry,
    BranchRegistry,
    _canon_condition,
    build_registry,
)
from specter.models import Paragraph, Program, Statement


# ---------------------------------------------------------------- entry
# shape + hashing

def test_content_hash_stable_across_same_inputs() -> None:
    a = BranchEntry(bid=1, paragraph="P", condition="X > 0", type="IF", ordinal=0)
    b = BranchEntry(bid=99, paragraph="P", condition="X > 0", type="IF", ordinal=0)
    # bid is not in the hash — same anchor → same hash
    assert a.content_hash == b.content_hash


def test_content_hash_distinguishes_ordinal() -> None:
    a = BranchEntry(bid=1, paragraph="P", condition="X > 0", type="IF", ordinal=0)
    b = BranchEntry(bid=2, paragraph="P", condition="X > 0", type="IF", ordinal=1)
    assert a.content_hash != b.content_hash


def test_content_hash_distinguishes_type() -> None:
    a = BranchEntry(bid=1, paragraph="P", condition="X > 0", type="IF", ordinal=0)
    b = BranchEntry(bid=1, paragraph="P", condition="X > 0", type="EVALUATE", ordinal=0)
    assert a.content_hash != b.content_hash


def test_canon_condition_normalization() -> None:
    assert _canon_condition("  X > 0  ") == "X > 0"
    assert _canon_condition("x > 0.") == "X > 0"
    assert _canon_condition("X\t>\n0") == "X > 0"
    assert _canon_condition("") == ""
    assert _canon_condition(None) == ""  # type: ignore[arg-type]


# ---------------------------------------------------------------- lookup

def test_registry_lookup_roundtrip() -> None:
    reg = BranchRegistry()
    reg.add(BranchEntry(bid=7, paragraph="MAIN", condition="A = B",
                        type="IF", ordinal=0))
    reg.add(BranchEntry(bid=8, paragraph="MAIN", condition="A = B",
                        type="IF", ordinal=1))
    hit = reg.lookup(paragraph="main", condition="a = b",
                     type="IF", ordinal=1)
    assert hit is not None
    assert hit.bid == 8
    miss = reg.lookup(paragraph="MAIN", condition="A = B",
                      type="IF", ordinal=99)
    assert miss is None


def test_registry_serialize_roundtrip() -> None:
    reg = BranchRegistry()
    reg.add(BranchEntry(bid=1, paragraph="P1", condition="C",
                        type="IF", ordinal=0, source_line=42,
                        attributes={"subject": "EIBAID"}))
    restored = BranchRegistry.from_dict(reg.to_dict())
    assert len(restored.entries) == 1
    e = restored.entries[0]
    assert e.bid == 1
    assert e.paragraph == "P1"
    assert e.condition == "C"
    assert e.type == "IF"
    assert e.source_line == 42
    assert e.attributes == {"subject": "EIBAID"}
    assert restored.by_hash[e.content_hash].bid == 1


def test_registry_as_branch_meta_matches_legacy_shape() -> None:
    reg = BranchRegistry()
    reg.add(BranchEntry(bid=3, paragraph="X", condition="A > 0",
                        type="IF", ordinal=0,
                        attributes={"subject": "W"}))
    meta = reg.as_branch_meta()
    assert meta == {3: {"paragraph": "X", "condition": "A > 0",
                        "type": "IF", "subject": "W"}}


# ---------------------------------------------------------------- walker

def _mk_stmt(type_: str, text: str = "", line: int = 1,
             attributes: dict | None = None,
             children: list[Statement] | None = None) -> Statement:
    return Statement(type=type_, text=text, line_start=line, line_end=line,
                     attributes=attributes or {}, children=children or [])


def _mk_prog(paragraphs: list[Paragraph]) -> Program:
    prog = Program(program_id="TEST", paragraphs=paragraphs)
    prog.paragraph_index = {p.name: p for p in paragraphs}
    return prog


def test_walker_emits_if() -> None:
    para = Paragraph(name="MAIN", line_start=1, line_end=5,
                     statements=[_mk_stmt("IF", "IF A = B", 2,
                                          {"condition": "A = B"})])
    reg = build_registry(_mk_prog([para]))
    assert len(reg.entries) == 1
    e = reg.entries[0]
    assert e.bid == 1 and e.type == "IF" and e.paragraph == "MAIN"
    assert e.condition == "A = B"


def test_walker_evaluate_when_groups() -> None:
    # EVALUATE with three WHEN arms:
    #   WHEN 'A' (no body, groups with next)
    #   WHEN 'B' + DISPLAY
    #   WHEN 'C' + DISPLAY
    # Expect 2 branches: group("A","B") + "C"
    when_a = _mk_stmt("WHEN", "WHEN 'A'", 3, {"value": "'A'"})
    when_b = _mk_stmt("WHEN", "WHEN 'B'", 4, {"value": "'B'"},
                      children=[_mk_stmt("DISPLAY", "", 4)])
    when_c = _mk_stmt("WHEN", "WHEN 'C'", 5, {"value": "'C'"},
                      children=[_mk_stmt("DISPLAY", "", 5)])
    eval_stmt = _mk_stmt("EVALUATE", "EVALUATE FOO", 2,
                         {"subject": "FOO"},
                         children=[when_a, when_b, when_c])
    reg = build_registry(_mk_prog([Paragraph(name="P", line_start=1,
                                             line_end=10,
                                             statements=[eval_stmt])]))
    # 2 OR-groups; ordinals 0 and 1
    assert [e.type for e in reg.entries] == ["EVALUATE", "EVALUATE"]
    assert reg.entries[0].condition == "'A' OR 'B'"
    assert reg.entries[1].condition == "'C'"
    assert [e.ordinal for e in reg.entries] == [0, 1]


def test_walker_evaluate_other_is_tagged_other() -> None:
    when_other = _mk_stmt("WHEN", "WHEN OTHER", 3, {"is_other": True},
                          children=[_mk_stmt("DISPLAY", "", 3)])
    eval_stmt = _mk_stmt("EVALUATE", "", 2, {},
                         children=[when_other])
    reg = build_registry(_mk_prog([Paragraph(name="P", line_start=1,
                                             line_end=10,
                                             statements=[eval_stmt])]))
    assert reg.entries[0].condition == "OTHER"


def test_walker_nested_if_produces_sequential_bids() -> None:
    inner = _mk_stmt("IF", "IF Y = 0", 3, {"condition": "Y = 0"})
    outer = _mk_stmt("IF", "IF X = 0", 2, {"condition": "X = 0"},
                    children=[inner])
    reg = build_registry(_mk_prog([Paragraph(name="P", line_start=1,
                                             line_end=10,
                                             statements=[outer])]))
    assert [e.bid for e in reg.entries] == [1, 2]
    assert [e.condition for e in reg.entries] == ["X = 0", "Y = 0"]
    # Ordinals are per-paragraph-per-type, so both IFs under P are
    # 0 and 1 respectively.
    assert [e.ordinal for e in reg.entries] == [0, 1]


def test_walker_perform_until_emits_branch() -> None:
    perf = _mk_stmt("PERFORM", "PERFORM UNTIL X = 0", 2,
                    {"target": "SUB", "condition": "X = 0"})
    reg = build_registry(_mk_prog([Paragraph(name="P", line_start=1,
                                             line_end=10,
                                             statements=[perf])]))
    assert len(reg.entries) == 1
    assert reg.entries[0].type == "PERFORM_UNTIL"
    assert reg.entries[0].condition == "X = 0"


def test_walker_perform_varying_multi_word_from_by_is_skipped() -> None:
    # `VARYING IDX FROM LENGTH OF X BY 1 UNTIL ...` does NOT match
    # code_generator's tight _VARYING_RE, so the registry must not emit
    # a PERFORM_VARYING entry either (keeps the bid sequence aligned).
    perf = _mk_stmt("PERFORM_INLINE", "PERFORM VARYING IDX FROM LENGTH", 2,
                   {"varying": "VARYING IDX FROM LENGTH OF X BY 1 UNTIL DONE"})
    reg = build_registry(_mk_prog([Paragraph(name="P", line_start=1,
                                             line_end=10,
                                             statements=[perf])]))
    assert len(reg.entries) == 0


# ---------------------------------------------------------------- end-to-end against code_generator

def test_registry_matches_code_generator_on_every_carddemo_ast() -> None:
    """Cross-check: for every AST in the carddemo test corpus, the
    registry's (bid, paragraph, condition, type) agrees with what the
    code generator emits into ``_BRANCH_META``.
    """
    import ast as _ast
    from specter.code_generator import generate_code
    from specter.variable_extractor import extract_variables

    base = Path("/home/andras/aws-mainframe-modernization-carddemo/app/cbl")
    if not base.exists():
        import pytest
        pytest.skip("carddemo corpus not available in this environment")

    asts = sorted(base.glob("*.ast"))
    assert asts, "corpus has no AST files"

    from specter.branch_registry import _canon_condition, _canon_paragraph

    for ast_file in asts:
        prog = parse_ast(ast_file)
        reg = build_registry(prog)
        rep = extract_variables(prog)
        cbl = ast_file.with_suffix("")
        code = generate_code(
            prog, rep, instrument=True,
            cobol_source=str(cbl) if cbl.exists() else None,
        )
        bm = None
        for line in code.split("\n"):
            if line.startswith("_BRANCH_META"):
                bm = _ast.literal_eval(line.split(" = ", 1)[1])
                break
        assert bm is not None, f"{ast_file.name}: no _BRANCH_META"
        assert len(reg.entries) == len(bm), (
            f"{ast_file.name}: registry={len(reg.entries)} cg={len(bm)}"
        )
        for e in reg.entries:
            row = bm.get(e.bid)
            assert row is not None, f"{ast_file.name}: bid={e.bid} missing"
            assert _canon_paragraph(row["paragraph"]) == e.paragraph
            assert _canon_condition(row["condition"]) == e.condition
            assert row["type"] == e.type
