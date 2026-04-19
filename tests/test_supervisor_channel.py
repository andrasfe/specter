"""Tests for the teacher/student supervisor channel."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import pytest

from specter.persistence_utils import append_line_with_fsync
from specter.supervisor_channel import (
    ESCALATE_ENV,
    RESOLUTIONS_FILE,
    STATUS_FILE,
    SupervisorChannel,
    SUPERVISOR_ENV,
)


def test_disabled_when_no_run_dir() -> None:
    c = SupervisorChannel(None)
    assert c.enabled is False
    # Calling escalate on a disabled channel is a no-op that returns None.
    assert c.escalate(kind="x", summary="x") is None
    # heartbeat is also a no-op.
    c.heartbeat({"phase": "x"})


def test_from_env_respects_toggle(monkeypatch: pytest.MonkeyPatch,
                                  tmp_path: Path) -> None:
    # Neither var set → disabled.
    monkeypatch.delenv(SUPERVISOR_ENV, raising=False)
    monkeypatch.delenv(ESCALATE_ENV, raising=False)
    assert SupervisorChannel.from_env().enabled is False

    # Only SPECTER_SUPERVISOR set → still disabled. Escalation is an
    # explicit opt-in; configuring the channel dir alone is not enough.
    monkeypatch.setenv(SUPERVISOR_ENV, str(tmp_path))
    assert SupervisorChannel.from_env().enabled is False

    # Only SPECTER_ESCALATE set → still disabled (no channel dir).
    monkeypatch.delenv(SUPERVISOR_ENV, raising=False)
    monkeypatch.setenv(ESCALATE_ENV, "1")
    assert SupervisorChannel.from_env().enabled is False

    # Both set → enabled.
    monkeypatch.setenv(SUPERVISOR_ENV, str(tmp_path))
    monkeypatch.setenv(ESCALATE_ENV, "1")
    c = SupervisorChannel.from_env()
    assert c.enabled is True
    assert c.run_dir == tmp_path

    # Truthy variations all work.
    for value in ("true", "yes", "on", "TRUE"):
        monkeypatch.setenv(ESCALATE_ENV, value)
        assert SupervisorChannel.from_env().enabled is True

    # Explicit 0 / false / empty disables.
    for value in ("0", "false", "no", ""):
        monkeypatch.setenv(ESCALATE_ENV, value)
        assert SupervisorChannel.from_env().enabled is False


def test_escalate_writes_event_and_waits(tmp_path: Path) -> None:
    c = SupervisorChannel(tmp_path, poll_interval_sec=0.05)

    # Teacher simulator: waits for the escalation, reads its id, replies.
    def teacher() -> None:
        esc_path = tmp_path / "escalations.jsonl"
        deadline = time.time() + 5
        while time.time() < deadline:
            if esc_path.exists() and esc_path.stat().st_size > 0:
                evt = json.loads(esc_path.read_text().splitlines()[0])
                reply = {
                    "id": evt["id"],
                    "verdict": "patch",
                    "fix": {"42": "           MOVE 1 TO WS-FOO"},
                    "notes": "test patch",
                }
                append_line_with_fsync(
                    tmp_path / RESOLUTIONS_FILE, json.dumps(reply) + "\n",
                )
                return
            time.sleep(0.05)

    t = threading.Thread(target=teacher)
    t.start()
    try:
        res = c.escalate(
            kind="compile_fix_exhausted",
            summary="phase=copy_resolution line=42",
            context={"foo": "bar"},
            timeout_sec=5,
        )
    finally:
        t.join(timeout=5)

    assert res is not None
    assert res.verdict == "patch"
    assert res.fix == {42: "           MOVE 1 TO WS-FOO"}
    assert res.notes == "test patch"


def test_escalate_times_out(tmp_path: Path) -> None:
    c = SupervisorChannel(tmp_path, poll_interval_sec=0.05)
    res = c.escalate(
        kind="compile_fix_exhausted",
        summary="no teacher around",
        timeout_sec=0.25,
    )
    assert res is None
    # The escalation was still written — teachers that log in later can read
    # the history even if the student moved on.
    assert (tmp_path / "escalations.jsonl").read_text().strip() != ""


def test_ignores_unknown_verdict(tmp_path: Path) -> None:
    c = SupervisorChannel(tmp_path, poll_interval_sec=0.05)

    def teacher() -> None:
        esc_path = tmp_path / "escalations.jsonl"
        for _ in range(100):
            if esc_path.exists() and esc_path.stat().st_size > 0:
                evt = json.loads(esc_path.read_text().splitlines()[0])
                # Bogus verdict — should be ignored so the student keeps
                # polling until timeout, then falls back.
                append_line_with_fsync(
                    tmp_path / RESOLUTIONS_FILE,
                    json.dumps({"id": evt["id"], "verdict": "nonsense"}) + "\n",
                )
                return
            time.sleep(0.02)

    t = threading.Thread(target=teacher)
    t.start()
    try:
        res = c.escalate(kind="x", summary="x", timeout_sec=0.5)
    finally:
        t.join(timeout=5)
    assert res is None


def test_heartbeat_appends(tmp_path: Path) -> None:
    c = SupervisorChannel(tmp_path)
    c.heartbeat({"phase": "compile", "round": 3})
    c.heartbeat({"phase": "compile", "round": 4})
    lines = (tmp_path / STATUS_FILE).read_text().splitlines()
    assert len(lines) == 2
    payloads = [json.loads(ln) for ln in lines]
    assert payloads[0]["phase"] == "compile"
    assert payloads[1]["round"] == 4
    assert "ts" in payloads[0]
    assert payloads[0]["pid"] == os.getpid()
