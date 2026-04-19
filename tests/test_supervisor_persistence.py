"""Tests for durable teacher knowledge: rules, findings, related_findings."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from specter.persistence_utils import append_line_with_fsync
from specter.supervisor_channel import (
    FACTS_FILE,
    FINDINGS_FILE,
    RESOLUTIONS_FILE,
    RULES_FILE,
    SupervisorChannel,
    TeacherFact,
    TeacherFactsStore,
    TeacherFindingsStore,
    TeacherRule,
    TeacherRulesStore,
)


# ------------------------------ TeacherRule.matches -------------------------


def test_rule_matches_by_message_token() -> None:
    r = TeacherRule(
        kind="skip_error_class",
        phase="copy_resolution",
        msg_contains=["'EXEC' is a reserved word"],
    )
    assert r.matches(
        phase="copy_resolution",
        msg="'EXEC' is a reserved word, but isn't supported",
    )
    assert not r.matches(
        phase="copy_resolution",
        msg="'WS-FOO' is not defined",
    )


def test_rule_respects_phase_filter() -> None:
    r = TeacherRule(
        kind="skip_error_class",
        phase="copy_resolution",
        msg_contains=["EXEC"],
    )
    # Different phase -> no match even if msg matches.
    assert not r.matches(phase="exec_replacement", msg="'EXEC' is reserved")


def test_rule_wildcard_phase() -> None:
    r = TeacherRule(kind="skip_error_class", phase="*", msg_contains=["FOO"])
    assert r.matches(phase="anything", msg="BAR FOO BAZ")


def test_rule_requires_source_context_when_set() -> None:
    r = TeacherRule(
        kind="skip_error_class",
        phase="copy_resolution",
        msg_contains=["unexpected"],
        source_context_contains="EXEC CICS",
    )
    # Window lacks the required context token.
    assert not r.matches(
        phase="copy_resolution",
        msg="syntax error, unexpected PROGRAM",
        source_window=["           MOVE 1 TO WS-FOO\n"],
    )
    # Window contains it.
    assert r.matches(
        phase="copy_resolution",
        msg="syntax error, unexpected PROGRAM",
        source_window=["           EXEC CICS\n", "               XCTL ..."],
    )


# ------------------------------ Rules store round-trip ---------------------


def test_rules_store_append_reload(tmp_path: Path) -> None:
    path = tmp_path / "rules.jsonl"
    store = TeacherRulesStore(path)
    assert store.rules == []

    store.append(TeacherRule(
        kind="skip_error_class",
        phase="copy_resolution",
        msg_contains=["'EXEC'"],
        reason="Phase 3 handles",
    ))
    assert len(store.rules) == 1

    # Fresh store loads from disk.
    store2 = TeacherRulesStore(path)
    assert len(store2.rules) == 1
    assert store2.rules[0].reason == "Phase 3 handles"


def test_rules_store_match_returns_first(tmp_path: Path) -> None:
    store = TeacherRulesStore(tmp_path / "rules.jsonl")
    store.append(TeacherRule(
        kind="skip_error_class",
        phase="copy_resolution",
        msg_contains=["EXEC"],
        reason="first",
    ))
    store.append(TeacherRule(
        kind="skip_error_class",
        phase="copy_resolution",
        msg_contains=["EXEC"],
        reason="second",
    ))
    hit = store.match(phase="copy_resolution", msg="'EXEC' is reserved")
    assert hit is not None
    assert hit.reason == "first"


def test_rules_store_ignores_malformed_lines(tmp_path: Path) -> None:
    path = tmp_path / "rules.jsonl"
    path.write_text("not json\n" + json.dumps({
        "kind": "skip_error_class",
        "phase": "copy_resolution",
        "msg_contains": ["FOO"],
        "reason": "works",
    }) + "\n")
    store = TeacherRulesStore(path)
    assert len(store.rules) == 1


# ------------------------------ Findings store -----------------------------


def test_findings_store_append_read(tmp_path: Path) -> None:
    store = TeacherFindingsStore(tmp_path / "findings.jsonl")
    store.append({
        "severity": "high",
        "title": "Phase-0 baseline tracker misses EXEC CICS errors",
        "suggested_files": ["specter/incremental_mock.py"],
        "notes": "See demo run 2026-04-18.",
    })
    all_ = store.read_all()
    assert len(all_) == 1
    assert all_[0]["title"].startswith("Phase-0")
    assert "ts" in all_[0]  # auto-stamped


# ---------------- End-to-end: save_rule + finding via channel --------------


def test_escalate_roundtrip_persists_rule_and_finding(tmp_path: Path) -> None:
    c = SupervisorChannel(tmp_path, poll_interval_sec=0.05)

    # Teacher that writes a skip reply WITH save_rule + finding.
    def teacher() -> None:
        esc_path = tmp_path / "escalations.jsonl"
        for _ in range(100):
            if esc_path.exists() and esc_path.stat().st_size > 0:
                evt = json.loads(esc_path.read_text().splitlines()[0])
                reply = {
                    "id": evt["id"],
                    "verdict": "skip",
                    "notes": "baseline-tracker bug; Phase 3 handles",
                    "save_rule": {
                        "kind": "skip_error_class",
                        "phase": "copy_resolution",
                        "msg_contains": ["'EXEC' is a reserved word"],
                        "source_context_contains": "EXEC CICS",
                        "reason": "Phase 3 (_replace_exec_blocks) handles",
                    },
                    "finding": {
                        "severity": "high",
                        "title": "Baseline tracker misses CICS verbs",
                        "suggested_files": [
                            "specter/incremental_mock.py:_compile_and_fix",
                        ],
                        "notes": "20 escalations all same class in demo run.",
                    },
                }
                append_line_with_fsync(
                    tmp_path / RESOLUTIONS_FILE, json.dumps(reply) + "\n",
                )
                return
            time.sleep(0.02)

    t = threading.Thread(target=teacher)
    t.start()
    try:
        res = c.escalate(
            kind="compile_fix_exhausted",
            summary="first time",
            context={"phase": "copy_resolution",
                     "error_msg": "'EXEC' is a reserved word"},
            timeout_sec=5,
        )
    finally:
        t.join(timeout=5)

    assert res is not None
    assert res.verdict == "skip"
    assert res.save_rule is not None
    assert res.finding is not None

    # Rule was persisted and reloadable.
    rules = TeacherRulesStore(tmp_path / RULES_FILE).rules
    assert len(rules) == 1
    assert rules[0].msg_contains == ["'EXEC' is a reserved word"]

    # Finding was persisted.
    findings = TeacherFindingsStore(tmp_path / FINDINGS_FILE).read_all()
    assert len(findings) == 1
    assert "CICS verbs" in findings[0]["title"]


def test_second_escalation_includes_related_findings(tmp_path: Path) -> None:
    """After a finding has been saved, a subsequent escalation for the same
    class should carry it in related_findings so the teacher sees context.
    """
    c = SupervisorChannel(tmp_path, poll_interval_sec=0.05)
    # Seed a finding directly.
    assert c.findings_store is not None
    c.findings_store.append({
        "severity": "high",
        "title": "Baseline tracker misses EXEC CICS errors",
        "notes": "see run A",
    })
    # And a rule so the rules_summary path also fires.
    assert c.rules_store is not None
    c.rules_store.append(TeacherRule(
        kind="skip_error_class",
        phase="copy_resolution",
        msg_contains=["'EXEC' is a reserved word"],
        reason="Phase 3 handles",
    ))

    # Teacher that replies with a minimal skip (no new save_rule).
    def teacher() -> None:
        esc_path = tmp_path / "escalations.jsonl"
        for _ in range(100):
            if esc_path.exists() and esc_path.stat().st_size > 0:
                evt = json.loads(esc_path.read_text().splitlines()[-1])
                append_line_with_fsync(
                    tmp_path / RESOLUTIONS_FILE,
                    json.dumps({"id": evt["id"], "verdict": "skip"}) + "\n",
                )
                return
            time.sleep(0.02)

    t = threading.Thread(target=teacher)
    t.start()
    try:
        c.escalate(
            kind="compile_fix_exhausted",
            summary="second time",
            context={"phase": "copy_resolution",
                     "error_msg": "'EXEC' is a reserved word"},
            timeout_sec=5,
        )
    finally:
        t.join(timeout=5)

    # The escalation line written to disk should carry related_findings.
    lines = (tmp_path / "escalations.jsonl").read_text().splitlines()
    evt = json.loads(lines[0])
    assert "related_findings" in evt
    kinds = {r.get("kind") for r in evt["related_findings"]}
    assert "finding" in kinds or "rules_summary" in kinds


def test_shorthand_msg_contains_string_is_accepted(tmp_path: Path) -> None:
    """save_rule with msg_contains as a string (not list) is normalized."""
    c = SupervisorChannel(tmp_path, poll_interval_sec=0.05)

    def teacher() -> None:
        esc_path = tmp_path / "escalations.jsonl"
        for _ in range(100):
            if esc_path.exists() and esc_path.stat().st_size > 0:
                evt = json.loads(esc_path.read_text().splitlines()[0])
                append_line_with_fsync(
                    tmp_path / RESOLUTIONS_FILE,
                    json.dumps({
                        "id": evt["id"],
                        "verdict": "skip",
                        "save_rule": {
                            "kind": "skip_error_class",
                            "phase": "copy_resolution",
                            "msg_contains": "quick-shorthand",  # not a list
                            "reason": "ok",
                        },
                    }) + "\n",
                )
                return
            time.sleep(0.02)

    t = threading.Thread(target=teacher)
    t.start()
    try:
        c.escalate(kind="x", summary="x", timeout_sec=5)
    finally:
        t.join(timeout=5)

    rules = TeacherRulesStore(tmp_path / RULES_FILE).rules
    assert len(rules) == 1
    assert rules[0].msg_contains == ["quick-shorthand"]


# ------------------------------ TeacherFact --------------------------------


def test_fact_round_trip(tmp_path: Path) -> None:
    store = TeacherFactsStore(tmp_path / FACTS_FILE)
    store.append(TeacherFact(
        kind="variable_format",
        target="DATEIN",
        scope="variable",
        content="DDMMYY string",
        examples=["150425", "010101"],
        reason="copybook comment",
    ))
    reloaded = TeacherFactsStore(tmp_path / FACTS_FILE)
    assert len(reloaded.facts) == 1
    f = reloaded.facts[0]
    assert f.target == "DATEIN"
    assert f.content == "DDMMYY string"
    assert f.examples == ["150425", "010101"]


def test_fact_match_scope_and_global(tmp_path: Path) -> None:
    store = TeacherFactsStore(tmp_path / FACTS_FILE)
    store.append(TeacherFact(
        kind="variable_format", target="DATEIN", scope="variable",
        content="DDMMYY",
    ))
    store.append(TeacherFact(
        kind="stub_outcome", target="CICS-READ", scope="stub_op",
        content="SPACES is success",
    ))
    store.append(TeacherFact(
        kind="note", target="", scope="global",
        content="All money fields are signed PIC S9(9)V99 COMP-3",
    ))

    var_hits = store.match(scope="variable", target="DATEIN")
    assert len(var_hits) == 2  # matched variable + global
    assert any(f.scope == "global" for f in var_hits)

    other_var_hits = store.match(scope="variable", target="SOMETHING-ELSE")
    # Only the global fact — the variable-scoped one is for DATEIN.
    assert [f.scope for f in other_var_hits] == ["global"]

    stub_hits = store.match(scope="stub_op", target="CICS-READ")
    assert any(f.target == "CICS-READ" for f in stub_hits)


def test_escalate_persists_save_fact(tmp_path: Path) -> None:
    c = SupervisorChannel(tmp_path, poll_interval_sec=0.05)

    def teacher() -> None:
        esc_path = tmp_path / "escalations.jsonl"
        for _ in range(100):
            if esc_path.exists() and esc_path.stat().st_size > 0:
                evt = json.loads(esc_path.read_text().splitlines()[0])
                reply = {
                    "id": evt["id"],
                    "verdict": "skip",
                    "notes": "date format is program-specific",
                    # Both list and single-dict shapes are accepted.
                    "save_fact": [
                        {
                            "kind": "variable_format",
                            "target": "DATEIN",
                            "scope": "variable",
                            "content": "DDMMYY string",
                            "examples": ["150425"],
                        },
                        {
                            "kind": "note",
                            "scope": "global",
                            "content": "money fields are PIC S9(9)V99 COMP-3",
                        },
                    ],
                }
                append_line_with_fsync(
                    tmp_path / RESOLUTIONS_FILE, json.dumps(reply) + "\n",
                )
                return
            time.sleep(0.02)

    t = threading.Thread(target=teacher)
    t.start()
    try:
        res = c.escalate(kind="end_of_cycle_review", summary="x", timeout_sec=5)
    finally:
        t.join(timeout=5)

    assert res is not None
    assert len(res.save_fact) == 2

    # Both facts persisted — reload from disk.
    facts = TeacherFactsStore(tmp_path / FACTS_FILE).facts
    assert len(facts) == 2
    targets = {f.target for f in facts}
    assert "DATEIN" in targets


def test_save_fact_accepts_single_dict_shorthand(tmp_path: Path) -> None:
    c = SupervisorChannel(tmp_path, poll_interval_sec=0.05)

    def teacher() -> None:
        esc_path = tmp_path / "escalations.jsonl"
        for _ in range(100):
            if esc_path.exists() and esc_path.stat().st_size > 0:
                evt = json.loads(esc_path.read_text().splitlines()[0])
                append_line_with_fsync(
                    tmp_path / RESOLUTIONS_FILE,
                    json.dumps({
                        "id": evt["id"],
                        "verdict": "skip",
                        # Single dict (not a list) should be accepted.
                        "save_fact": {
                            "kind": "variable_values",
                            "target": "WS-DLG-ACT",
                            "scope": "variable",
                            "content": "One of U, D, I",
                        },
                    }) + "\n",
                )
                return
            time.sleep(0.02)

    t = threading.Thread(target=teacher)
    t.start()
    try:
        res = c.escalate(kind="end_of_cycle_review", summary="x", timeout_sec=5)
    finally:
        t.join(timeout=5)

    assert res is not None and len(res.save_fact) == 1
    facts = TeacherFactsStore(tmp_path / FACTS_FILE).facts
    assert len(facts) == 1
    assert facts[0].target == "WS-DLG-ACT"


# ------------------------------ JIT integration ----------------------------


def test_jit_prompt_includes_teacher_facts(tmp_path: Path) -> None:
    """The JIT prompt for a variable should surface matching facts."""
    from specter.jit_value_inference import _build_inference_prompt
    from specter.variable_domain import VariableDomain

    store = TeacherFactsStore(tmp_path / FACTS_FILE)
    store.append(TeacherFact(
        kind="variable_format", target="DATEIN", scope="variable",
        content="DDMMYY string", examples=["150425"],
    ))
    facts = store.match(scope="variable", target="DATEIN")

    domain = VariableDomain(
        name="DATEIN", data_type="alpha", max_length=6,
        classification="input",
    )
    prompt = _build_inference_prompt(
        "DATEIN", domain,
        target_paragraph="PROCESS-ENTER-KEY",
        teacher_facts=facts,
    )
    assert "Teacher-curated domain facts" in prompt
    assert "DDMMYY string" in prompt
    assert "150425" in prompt


def test_jit_facts_digest_changes_with_fact(tmp_path: Path) -> None:
    """Adding a fact must change the cache key so stale profiles drop."""
    from specter.jit_value_inference import _facts_digest

    class _F:
        def __init__(self, kind: str, content: str, examples: list[str]) -> None:
            self.kind = kind
            self.content = content
            self.examples = examples

    d_empty = _facts_digest([])
    d_one = _facts_digest([_F("variable_format", "DDMMYY", ["150425"])])
    d_other = _facts_digest([_F("variable_format", "YYYYMMDD", [])])
    assert d_empty == ""
    assert d_one != ""
    assert d_one != d_other
