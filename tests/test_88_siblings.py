"""Tests for 88-level sibling handling and EVALUATE :F branch probes.

These tests protect structural branch coverage fixes from regression:
1. EVALUATE :F probes — negative branch IDs for non-taken WHEN arms
2. 88-level mutual exclusivity — SET X TO TRUE clears sibling flags
3. 88-level extraction from COBOL source — inline 88-level scanning
4. Stub mapping expansion — only expand pure-88 ops, not mixed ops
5. Fault stub generation — 88-level targeted faults use True/False
"""

import re
import tempfile
from pathlib import Path

import pytest

from specter.code_generator import generate_code, _CodeBuilder
from specter.models import Program, Paragraph, Statement
from specter.variable_extractor import extract_variables


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_stmt(type, text, children=None, **attrs):
    return Statement(
        type=type, text=text, attributes=attrs,
        children=children or [], line_start=1, line_end=1,
    )


def _make_program(paragraphs):
    return Program(program_id="TEST", paragraphs=paragraphs)


def _compile_and_run(code, initial_state=None):
    ns = {}
    exec(compile(code, "test.py", "exec"), ns)
    return ns["run"](initial_state or {})


# ---------------------------------------------------------------------------
# EVALUATE :F probes
# ---------------------------------------------------------------------------

class TestEvaluateFProbes:
    """EVALUATE codegen must emit negative branch IDs for non-taken WHEN arms."""

    def _build_evaluate_program(self):
        when1 = _make_stmt("WHEN", "WHEN 1", [
            _make_stmt("DISPLAY", 'DISPLAY "ONE"'),
        ])
        when2 = _make_stmt("WHEN", "WHEN 2", [
            _make_stmt("DISPLAY", 'DISPLAY "TWO"'),
        ])
        when_other = _make_stmt("WHEN", "WHEN OTHER", [
            _make_stmt("DISPLAY", 'DISPLAY "OTHER"'),
        ])
        eval_stmt = _make_stmt("EVALUATE", "EVALUATE WS-CODE",
                               [when1, when2, when_other], subject="WS-CODE")
        para = Paragraph(name="TEST-PARA", statements=[eval_stmt],
                         line_start=1, line_end=10)
        return _make_program([para])

    def test_eval_taken_variable_emitted(self):
        prog = self._build_evaluate_program()
        code = generate_code(prog, instrument=True)
        assert "_eval_taken_" in code, "EVALUATE must emit _eval_taken_ tracking variable"

    def test_negative_branch_loop_emitted(self):
        prog = self._build_evaluate_program()
        code = generate_code(prog, instrument=True)
        assert "for _bid in" in code, "EVALUATE must emit negative branch probe loop"

    def test_f_probes_fire_for_non_taken_arms(self):
        prog = self._build_evaluate_program()
        code = generate_code(prog, instrument=True)
        result = _compile_and_run(code, {"WS-CODE": 1})
        branches = result["_branches"]
        # bid 1 should be T (taken), bids 2,3 should be F (not taken)
        pos = {b for b in branches if b > 0}
        neg = {b for b in branches if b < 0}
        assert len(pos) >= 1, "At least one positive branch"
        assert len(neg) >= 2, "At least two negative (F) branch probes"

    def test_all_arms_get_coverage(self):
        """Running with each WHEN value covers all T and F directions."""
        prog = self._build_evaluate_program()
        code = generate_code(prog, instrument=True)
        all_branches = set()
        for val in [1, 2, 99]:
            result = _compile_and_run(code, {"WS-CODE": val})
            all_branches.update(result["_branches"])
        meta_count = len([b for b in all_branches if b > 0 or b < 0])
        # 3 WHEN arms × 2 directions = 6 total coverable
        assert meta_count >= 6, f"Expected 6+ branch probes, got {meta_count}"


# ---------------------------------------------------------------------------
# 88-level sibling clearing in SET
# ---------------------------------------------------------------------------

class TestSiblingClearing:
    """SET X TO TRUE must clear 88-level siblings."""

    def _build_set_program(self, siblings_source="copybook"):
        set_stmt = _make_stmt("SET", "SET CARD-NFOUND-XREF TO TRUE")
        para = Paragraph(name="TEST-PARA", statements=[set_stmt],
                         line_start=1, line_end=2)
        prog = _make_program([para])
        return prog

    def test_sibling_cleared_with_copybook(self):
        from specter.copybook_parser import CopybookRecord, CopybookField
        field = CopybookField(
            level=5, name="XREF-STATUS", pic="X", pic_type="alpha",
            length=1, precision=0, occurs=1, is_filler=False,
            values_88={"CARD-FOUND-XREF": "Y", "CARD-NFOUND-XREF": "N"},
        )
        rec = CopybookRecord(name="TEST", fields=[field], copybook_file="t.cpy")
        prog = self._build_set_program()
        code = generate_code(prog, instrument=True, copybook_records=[rec])
        assert "state['CARD-FOUND-XREF'] = False" in code, \
            "SET CARD-NFOUND-XREF TO TRUE must clear sibling CARD-FOUND-XREF"

    def test_sibling_cleared_with_heuristic(self):
        """FOUND/NFOUND naming heuristic must infer siblings."""
        set1 = _make_stmt("SET", "SET CARD-FOUND-XREF TO TRUE")
        set2 = _make_stmt("SET", "SET CARD-NFOUND-XREF TO TRUE")
        para = Paragraph(name="P", statements=[set1, set2],
                         line_start=1, line_end=3)
        prog = _make_program([para])
        code = generate_code(prog, instrument=True)
        # SET CARD-FOUND-XREF TO TRUE should clear CARD-NFOUND-XREF
        assert "state['CARD-NFOUND-XREF'] = False" in code
        # SET CARD-NFOUND-XREF TO TRUE should clear CARD-FOUND-XREF
        assert "state['CARD-FOUND-XREF'] = False" in code

    def test_sibling_cleared_with_cobol_source(self):
        """88-levels defined inline in COBOL source must be extracted."""
        cobol = """\
       WORKING-STORAGE SECTION.
       05  DIBSTAT          PIC XX.
           88 STATUS-OK              VALUE '  '.
           88 SEGMENT-NOT-FOUND      VALUE 'GE'.
           88 PSB-SCHED-MORE         VALUE 'TC'.
       05  OTHER-VAR        PIC X.
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".cbl", delete=False) as f:
            f.write(cobol)
            cbl_path = f.name

        set_stmt = _make_stmt("SET", "SET STATUS-OK TO TRUE")
        para = Paragraph(name="P", statements=[set_stmt],
                         line_start=1, line_end=2)
        prog = _make_program([para])
        code = generate_code(prog, instrument=True, cobol_source=cbl_path)
        Path(cbl_path).unlink()

        assert "state['SEGMENT-NOT-FOUND'] = False" in code, \
            "SET STATUS-OK TO TRUE must clear sibling SEGMENT-NOT-FOUND"
        assert "state['PSB-SCHED-MORE'] = False" in code, \
            "SET STATUS-OK TO TRUE must clear sibling PSB-SCHED-MORE"


# ---------------------------------------------------------------------------
# 88-level extraction from COBOL source
# ---------------------------------------------------------------------------

class TestExtract88FromSource:
    """_extract_88_siblings_from_source must parse inline 88-levels."""

    def test_basic_extraction(self):
        from specter.cobol_coverage import _extract_88_siblings_from_source

        cobol = """\
       01  WS-STATUS-AREA.
           05  DIBSTAT          PIC XX.
               88 STATUS-OK              VALUE '  '.
               88 SEGMENT-NOT-FOUND      VALUE 'GE'.
               88 END-OF-DB              VALUE 'GB'.
           05  OTHER-VAR        PIC X.
               88 FLAG-A                 VALUE 'Y'.
               88 FLAG-B                 VALUE 'N'.
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".cbl", delete=False) as f:
            f.write(cobol)
            path = f.name

        siblings = _extract_88_siblings_from_source(path)
        Path(path).unlink()

        assert "STATUS-OK" in siblings
        assert "SEGMENT-NOT-FOUND" in siblings["STATUS-OK"]
        assert "END-OF-DB" in siblings["STATUS-OK"]
        assert "STATUS-OK" in siblings["SEGMENT-NOT-FOUND"]
        assert "FLAG-A" in siblings
        assert "FLAG-B" in siblings["FLAG-A"]
        # Different parent groups must not be mixed
        assert "FLAG-A" not in siblings.get("STATUS-OK", set())

    def test_single_88_no_siblings(self):
        from specter.cobol_coverage import _extract_88_siblings_from_source

        cobol = """\
       05  SINGLE-FLAG     PIC X.
           88 ONLY-ONE      VALUE 'Y'.
       05  NEXT-VAR        PIC X.
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".cbl", delete=False) as f:
            f.write(cobol)
            path = f.name

        siblings = _extract_88_siblings_from_source(path)
        Path(path).unlink()

        # A single 88-level has no siblings
        assert "ONLY-ONE" not in siblings

    def test_nonexistent_file(self):
        from specter.cobol_coverage import _extract_88_siblings_from_source
        result = _extract_88_siblings_from_source("/nonexistent/file.cbl")
        assert result == {}

    def test_real_copaua0c_source(self):
        """Validate extraction against the actual COPAUA0C COBOL source."""
        from specter.cobol_coverage import _extract_88_siblings_from_source

        cbl_path = Path("examples/COPAUA0C.cbl.ast")
        # The .ast file is JSON, not COBOL — look for the .cbl source
        cbl_source = Path(
            "/home/andras/aws-mainframe-modernization-carddemo/"
            "app/app-authorization-ims-db2-mq/cbl/COPAUA0C.cbl"
        )
        if not cbl_source.exists():
            pytest.skip("COPAUA0C.cbl source not available")

        siblings = _extract_88_siblings_from_source(cbl_source)

        # DIBSTAT 88-levels must be found
        assert "STATUS-OK" in siblings, "STATUS-OK not found in COBOL source"
        assert "SEGMENT-NOT-FOUND" in siblings["STATUS-OK"], \
            "SEGMENT-NOT-FOUND must be a sibling of STATUS-OK"
        assert "PSB-SCHEDULED-MORE-THAN-ONCE" in siblings["STATUS-OK"], \
            "PSB-SCHEDULED-MORE-THAN-ONCE must be a sibling of STATUS-OK"


# ---------------------------------------------------------------------------
# Stub mapping expansion
# ---------------------------------------------------------------------------

class TestStubMappingExpansion:
    """_expand_stub_mapping must only expand pure-88 ops."""

    def test_expand_pure_88_op(self):
        from specter.cobol_coverage import _expand_stub_mapping

        stub_mapping = {"DLI": ["STATUS-OK", "PSB-SCHED"]}
        siblings = {
            "STATUS-OK": {"SEGMENT-NOT-FOUND", "PSB-SCHED"},
            "PSB-SCHED": {"STATUS-OK", "SEGMENT-NOT-FOUND"},
            "SEGMENT-NOT-FOUND": {"STATUS-OK", "PSB-SCHED"},
        }
        added = _expand_stub_mapping(stub_mapping, siblings)
        assert "SEGMENT-NOT-FOUND" in added
        assert "SEGMENT-NOT-FOUND" in stub_mapping["DLI"]

    def test_no_expand_mixed_op(self):
        """Ops mixing 88-level flags with non-88 status vars must NOT expand."""
        from specter.cobol_coverage import _expand_stub_mapping

        stub_mapping = {"CICS": ["EIBRESP", "WS-RESP-CD", "ERR-CRITICAL"]}
        siblings = {
            "ERR-CRITICAL": {"ERR-INFO", "ERR-WARNING"},
            "ERR-INFO": {"ERR-CRITICAL", "ERR-WARNING"},
            "ERR-WARNING": {"ERR-CRITICAL", "ERR-INFO"},
        }
        added = _expand_stub_mapping(stub_mapping, siblings)
        assert len(added) == 0, "Mixed ops must not be expanded"
        assert "ERR-INFO" not in stub_mapping["CICS"]


# ---------------------------------------------------------------------------
# Fault stub generation for 88-level flags
# ---------------------------------------------------------------------------

class TestFaultStubs88:
    """_build_fault_stubs must generate targeted 88-level fault entries."""

    def test_targeted_88_fault(self):
        from specter.cobol_coverage import _build_fault_stubs
        import random

        stub_mapping = {
            "DLI": ["STATUS-OK", "PSB-SCHED", "SEGMENT-NOT-FOUND"],
        }
        siblings = {
            "STATUS-OK": {"PSB-SCHED", "SEGMENT-NOT-FOUND"},
            "PSB-SCHED": {"STATUS-OK", "SEGMENT-NOT-FOUND"},
            "SEGMENT-NOT-FOUND": {"STATUS-OK", "PSB-SCHED"},
        }
        flag_added = {"SEGMENT-NOT-FOUND"}

        stubs, defaults = _build_fault_stubs(
            stub_mapping, {},
            target_op="DLI", fault_value="SEGMENT-NOT-FOUND",
            rng=random.Random(42),
            flag_88_added=flag_added, siblings_88=siblings,
        )

        dli_entry = stubs["DLI"][0]
        vals = {var: val for var, val in dli_entry}
        assert vals["SEGMENT-NOT-FOUND"] is True, \
            "Targeted 88-level fault must set SEGMENT-NOT-FOUND = True"
        assert vals["STATUS-OK"] is False, \
            "Targeted 88-level fault must clear STATUS-OK"
        assert vals["PSB-SCHED"] is False, \
            "Targeted 88-level fault must clear PSB-SCHED"

    def test_success_stubs_primary_flag(self):
        """Success stubs must set only the primary success flag to True."""
        from specter.cobol_coverage import _build_success_stubs

        stub_mapping = {
            "DLI": ["STATUS-OK", "PSB-SCHED", "SEGMENT-NOT-FOUND"],
        }
        siblings = {
            "STATUS-OK": {"PSB-SCHED", "SEGMENT-NOT-FOUND"},
            "PSB-SCHED": {"STATUS-OK", "SEGMENT-NOT-FOUND"},
            "SEGMENT-NOT-FOUND": {"STATUS-OK", "PSB-SCHED"},
        }
        flag_added = {"SEGMENT-NOT-FOUND"}

        stubs, defaults = _build_success_stubs(
            stub_mapping, {},
            flag_88_added=flag_added, siblings_88=siblings,
        )

        dli_entry = stubs["DLI"][0]
        vals = {var: val for var, val in dli_entry}
        assert vals["STATUS-OK"] is True, \
            "STATUS-OK (contains 'OK') must be the primary success flag"
        assert vals["PSB-SCHED"] is False
        assert vals["SEGMENT-NOT-FOUND"] is False
