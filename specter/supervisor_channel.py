"""Teacher/student IPC channel for long-running Specter jobs.

Specter (the student) appends a JSON event to ``escalations.jsonl`` when it
hits a dead end it can't resolve on its own — e.g. an LLM scribe proposal
rejected by the challenger past the revision cap, or a phase gate about to
raise. A teacher process (typically a Claude Code session tailing the file)
reads the event, investigates, and appends a reply to ``resolutions.jsonl``
carrying the same correlation ``id``. The student polls for that reply with a
bounded timeout; on timeout it falls back to its existing abandonment path so
headless runs never deadlock.

File layout::

    <run_dir>/
      escalations.jsonl   # student -> teacher, append-only
      resolutions.jsonl   # teacher -> student, append-only
      status.jsonl        # heartbeats, append-only

The channel is env-gated: ``SPECTER_SUPERVISOR=<run_dir>`` turns it on.
Unset -> all methods no-op, zero overhead on the hot path.

Resolution verdicts understood by callers:

- ``patch``      – apply inline ``{line: content}`` fix and continue
- ``skip``       – abandon this error, continue
- ``abort``      – raise so the run exits cleanly
- ``restart``    – teacher will edit source + relaunch; student should abort
- ``retry_with`` – continue with modified env/flags (future use)
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .persistence_utils import append_line_with_fsync

log = logging.getLogger(__name__)

SUPERVISOR_ENV = "SPECTER_SUPERVISOR"
ESCALATIONS_FILE = "escalations.jsonl"
RESOLUTIONS_FILE = "resolutions.jsonl"
STATUS_FILE = "status.jsonl"

_VALID_VERDICTS = {"patch", "skip", "abort", "restart", "retry_with"}


# ---------------------------------------------------------------- exceptions
#
# These inherit from BaseException rather than Exception so that defensive
# `except Exception:` / `except RuntimeError:` blocks elsewhere in the
# pipeline (e.g. the compile-retry fallback in cobol_coverage.py) do NOT
# swallow a teacher-issued abort or restart. Only an explicit handler for
# SupervisorAbort / SupervisorRestart / BaseException / bare `except:` will
# catch them — matching the convention used by KeyboardInterrupt and
# SystemExit for control-flow signals the application is not allowed to
# quietly recover from.


class SupervisorAbort(BaseException):
    """Teacher instructed the student to stop the run immediately.

    Callers should let this propagate out of the pipeline. If a layer
    genuinely needs to clean up before exit, it may catch this exception,
    perform cleanup, and then re-raise. It must not be converted to a
    RuntimeError or swallowed silently.
    """


class SupervisorRestart(BaseException):
    """Teacher requested a restart — intends to edit student source then rerun.

    Same propagation contract as SupervisorAbort: let it out of the
    pipeline. A wrapper script or outer driver can catch it to trigger the
    relaunch; the pipeline itself must not retry on its own.
    """


@dataclass
class Resolution:
    """Reply from the teacher for a single escalation.

    Optional fields let the teacher record durable knowledge alongside
    the immediate answer:

    - ``save_rule``: a pattern the student should apply on its own next
      time instead of escalating. Appended to ``teacher_rules.jsonl``.
    - ``finding``: a structural observation about the student itself
      (not a runtime fix). Appended to ``teacher_findings.jsonl`` for
      later human review. These are the "improve the student, not just
      the artifact" notes from the teacher/student design.
    """

    id: str
    verdict: str
    fix: dict[int, str] = field(default_factory=dict)
    notes: str = ""
    raw: dict[str, Any] = field(default_factory=dict)
    save_rule: dict[str, Any] | None = None
    finding: dict[str, Any] | None = None


# -------------------------------------------------------------- file names
RULES_FILE = "teacher_rules.jsonl"
FINDINGS_FILE = "teacher_findings.jsonl"


@dataclass
class TeacherRule:
    """A durable pattern the student applies to skip escalation.

    A rule matches a compile error when ALL of these hold:
    - ``phase`` matches (exact, after student-side normalization), OR
      the rule's phase is empty/"*".
    - Every token in ``msg_contains`` is a substring of the error message.
    - If ``source_context_contains`` is set, at least one line within ±4
      of the error appears to contain that token (case-insensitive).

    ``reason`` is free-form teacher-provided text used in logs.
    ``issued_by`` is informational.
    """

    kind: str  # currently only "skip_error_class"
    phase: str
    msg_contains: list[str] = field(default_factory=list)
    source_context_contains: str = ""
    reason: str = ""
    issued_by: str = "teacher"
    ts: float = 0.0

    def matches(
        self,
        *,
        phase: str,
        msg: str,
        source_window: list[str] | None = None,
    ) -> bool:
        if self.phase and self.phase != "*" and self.phase != phase:
            return False
        for token in self.msg_contains:
            if token and token not in msg:
                return False
        if self.source_context_contains:
            needle = self.source_context_contains.upper()
            found = False
            for line in source_window or []:
                if needle in line.upper():
                    found = True
                    break
            if not found:
                return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "phase": self.phase,
            "msg_contains": list(self.msg_contains),
            "source_context_contains": self.source_context_contains,
            "reason": self.reason,
            "issued_by": self.issued_by,
            "ts": self.ts,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TeacherRule | None":
        try:
            return cls(
                kind=str(data.get("kind", "skip_error_class")),
                phase=str(data.get("phase", "")),
                msg_contains=[str(x) for x in data.get("msg_contains", []) or []],
                source_context_contains=str(data.get("source_context_contains", "")),
                reason=str(data.get("reason", "")),
                issued_by=str(data.get("issued_by", "teacher")),
                ts=float(data.get("ts", 0.0) or 0.0),
            )
        except (TypeError, ValueError):
            return None


class TeacherRulesStore:
    """Append-only JSONL store of durable skip rules.

    Safe to instantiate with a missing file — reads yield an empty list,
    and ``append`` creates the file on demand. The store caches rules on
    load; callers that expect live concurrent updates from another
    process should call ``reload()`` before matching.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._rules: list[TeacherRule] = []
        self.reload()

    @property
    def rules(self) -> list[TeacherRule]:
        return list(self._rules)

    def reload(self) -> None:
        self._rules = []
        if not self.path.exists():
            return
        try:
            for raw in self.path.read_text(encoding="utf-8").splitlines():
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                rule = TeacherRule.from_dict(data)
                if rule is not None:
                    self._rules.append(rule)
        except OSError as exc:
            log.warning("supervisor: failed to read rules file: %s", exc)

    def append(self, rule: TeacherRule) -> None:
        try:
            append_line_with_fsync(
                self.path, json.dumps(rule.to_dict(), default=str) + "\n"
            )
            self._rules.append(rule)
        except Exception as exc:  # noqa: BLE001
            log.warning("supervisor: failed to persist rule: %s", exc)

    def match(
        self,
        *,
        phase: str,
        msg: str,
        source_window: list[str] | None = None,
    ) -> TeacherRule | None:
        """Return the first rule that matches, or None."""
        for rule in self._rules:
            if rule.matches(phase=phase, msg=msg, source_window=source_window):
                return rule
        return None


class TeacherFindingsStore:
    """Append-only JSONL store of structural teacher observations.

    Unlike rules, findings are never auto-applied; they are a "lint
    inbox" for the operator. Each entry carries a severity, title,
    optional suggested file pointers, and free-form notes.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def append(self, finding: dict[str, Any]) -> None:
        payload = dict(finding)
        payload.setdefault("ts", time.time())
        try:
            append_line_with_fsync(
                self.path, json.dumps(payload, default=str) + "\n"
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("supervisor: failed to persist finding: %s", exc)

    def read_all(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        out: list[dict[str, Any]] = []
        try:
            for raw in self.path.read_text(encoding="utf-8").splitlines():
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    out.append(json.loads(raw))
                except json.JSONDecodeError:
                    continue
        except OSError as exc:
            log.warning("supervisor: failed to read findings file: %s", exc)
        return out


class SupervisorChannel:
    """Append-only JSONL channel between Specter and a teacher agent.

    Safe to instantiate even when disabled: when ``run_dir`` is ``None`` (env
    var unset), ``escalate`` returns ``None`` immediately and ``heartbeat`` is
    a no-op. Callers can therefore construct one unconditionally and let the
    toggle live in the environment.
    """

    def __init__(
        self,
        run_dir: str | Path | None,
        *,
        poll_interval_sec: float = 1.0,
        default_timeout_sec: float = 900.0,
        pid: int | None = None,
    ):
        self.run_dir = Path(run_dir) if run_dir else None
        self.poll_interval_sec = poll_interval_sec
        self.default_timeout_sec = default_timeout_sec
        self.pid = pid if pid is not None else os.getpid()
        self._resolutions_offset = 0
        self.rules_store: TeacherRulesStore | None = None
        self.findings_store: TeacherFindingsStore | None = None

        if self.run_dir is not None:
            self.run_dir.mkdir(parents=True, exist_ok=True)
            # Remember where we already are in resolutions.jsonl so each
            # escalate() only scans new lines on subsequent waits. On first
            # construction the file may not exist yet — that's fine.
            rp = self.run_dir / RESOLUTIONS_FILE
            if rp.exists():
                self._resolutions_offset = rp.stat().st_size
            # Instantiate durable stores up-front so persistence is
            # best-effort and never blocks the hot path.
            self.rules_store = TeacherRulesStore(self.run_dir / RULES_FILE)
            self.findings_store = TeacherFindingsStore(
                self.run_dir / FINDINGS_FILE
            )

    @property
    def enabled(self) -> bool:
        return self.run_dir is not None

    @classmethod
    def from_env(cls, **kwargs: Any) -> "SupervisorChannel":
        """Build a channel from ``SPECTER_SUPERVISOR``; disabled if unset."""
        run_dir = os.environ.get(SUPERVISOR_ENV)
        return cls(run_dir or None, **kwargs)

    # ------------------------------------------------------------------ I/O

    def escalate(
        self,
        *,
        kind: str,
        summary: str,
        context: dict[str, Any] | None = None,
        artifacts: Iterable[str | Path] | None = None,
        student_hints: Iterable[str] | None = None,
        timeout_sec: float | None = None,
    ) -> Resolution | None:
        """Append an escalation event, block until matching resolution.

        Returns ``None`` when disabled, on timeout, or when the teacher's
        reply can't be parsed. Callers should treat ``None`` as "the teacher
        didn't answer — fall back to default behavior".
        """
        if not self.enabled:
            return None
        assert self.run_dir is not None  # for type checker

        event_id = str(uuid.uuid4())
        related = self._related_findings(kind, context or {})
        payload = {
            "id": event_id,
            "ts": time.time(),
            "pid": self.pid,
            "kind": kind,
            "summary": summary,
            "context": context or {},
            "artifacts": [str(p) for p in (artifacts or [])],
            "student_hints": list(student_hints or []),
            "related_findings": related,
        }
        line = json.dumps(payload, default=str) + "\n"
        escalations_path = self.run_dir / ESCALATIONS_FILE
        try:
            append_line_with_fsync(escalations_path, line)
        except Exception as exc:  # noqa: BLE001
            log.warning("supervisor: failed to append escalation: %s", exc)
            return None

        log.warning(
            "supervisor: escalated kind=%s id=%s summary=%s",
            kind, event_id[:8], summary[:120],
        )
        deadline = time.time() + (timeout_sec or self.default_timeout_sec)
        return self._wait_for_resolution(event_id, deadline)

    def heartbeat(self, data: dict[str, Any]) -> None:
        """Append a heartbeat snapshot. Best-effort, never raises."""
        if not self.enabled:
            return
        assert self.run_dir is not None
        payload = {"ts": time.time(), "pid": self.pid, **data}
        try:
            append_line_with_fsync(
                self.run_dir / STATUS_FILE,
                json.dumps(payload, default=str) + "\n",
            )
        except Exception as exc:  # noqa: BLE001
            log.debug("supervisor: heartbeat failed: %s", exc)

    # ------------------------------------------------------------ internals

    def _related_findings(
        self, kind: str, context: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Return prior findings / rules relevant to the current event.

        Keeps the list short (<=10) so the escalation payload stays
        readable. Matching is cheap: we look for findings whose title
        or notes mention the current error message or phase, and
        include a tiny summary of existing rules for this phase so the
        teacher can see "you already told me to skip this class N times."
        """
        if not self.findings_store and not self.rules_store:
            return []
        msg = str(context.get("error_msg", ""))
        phase = str(context.get("phase", ""))
        out: list[dict[str, Any]] = []

        if self.findings_store:
            for f in self.findings_store.read_all():
                blob = (str(f.get("title", "")) + " " +
                        str(f.get("notes", ""))).lower()
                if (msg and msg.lower() in blob) or (
                    phase and phase.lower() in blob
                ):
                    out.append({"kind": "finding", **f})
                if len(out) >= 8:
                    break

        if self.rules_store:
            matching = [
                r for r in self.rules_store.rules
                if (not r.phase or r.phase == "*" or r.phase == phase)
                and (not r.msg_contains or any(
                    tok and tok in msg for tok in r.msg_contains
                ))
            ]
            if matching:
                out.append({
                    "kind": "rules_summary",
                    "count": len(matching),
                    "reasons": [r.reason for r in matching[:5]],
                })
        return out

    def _persist_durable_fields(self, resolution: "Resolution") -> None:
        """Record any durable teacher knowledge carried by the resolution.

        ``save_rule`` becomes a TeacherRule and is appended to the rules
        store. ``finding`` is appended verbatim to the findings store
        (plus a timestamp). Either can be absent; both are best-effort
        and never raise.
        """
        if resolution.save_rule and self.rules_store is not None:
            rule_data = dict(resolution.save_rule)
            rule_data.setdefault("ts", time.time())
            rule_data.setdefault("issued_by", "teacher")
            # Allow a flat `msg_contains: "str"` shorthand in addition
            # to the canonical list form.
            mc = rule_data.get("msg_contains")
            if isinstance(mc, str):
                rule_data["msg_contains"] = [mc]
            rule = TeacherRule.from_dict(rule_data)
            if rule is not None:
                self.rules_store.append(rule)
                log.info(
                    "supervisor: persisted teacher rule kind=%s phase=%s "
                    "msg_contains=%s",
                    rule.kind, rule.phase, rule.msg_contains,
                )
        if resolution.finding and self.findings_store is not None:
            self.findings_store.append(resolution.finding)
            log.info(
                "supervisor: persisted teacher finding: %s",
                str(resolution.finding.get("title", ""))[:120],
            )

    def _wait_for_resolution(
        self, event_id: str, deadline: float
    ) -> Resolution | None:
        assert self.run_dir is not None
        path = self.run_dir / RESOLUTIONS_FILE
        while time.time() < deadline:
            if path.exists():
                try:
                    size = path.stat().st_size
                except OSError:
                    size = 0
                if size > self._resolutions_offset:
                    with open(path, "r", encoding="utf-8") as f:
                        f.seek(self._resolutions_offset)
                        # readline() (not iteration) keeps tell() usable
                        # so we can advance the cursor precisely even when
                        # a matching message is found mid-stream.
                        while True:
                            raw = f.readline()
                            if not raw:
                                break
                            pos = f.tell()
                            try:
                                msg = json.loads(raw)
                            except json.JSONDecodeError:
                                self._resolutions_offset = pos
                                continue
                            if msg.get("id") == event_id:
                                self._resolutions_offset = pos
                                parsed = _parse_resolution(msg)
                                if parsed is not None:
                                    self._persist_durable_fields(parsed)
                                    return parsed
                                # Unknown verdict: advance past and keep
                                # polling rather than deadlocking.
                            self._resolutions_offset = pos
            time.sleep(self.poll_interval_sec)

        log.warning(
            "supervisor: timeout waiting for resolution id=%s", event_id[:8],
        )
        return None


def _parse_resolution(msg: dict[str, Any]) -> Resolution | None:
    verdict = str(msg.get("verdict", "")).strip()
    if verdict not in _VALID_VERDICTS:
        log.warning(
            "supervisor: ignoring resolution with unknown verdict=%r", verdict,
        )
        return None
    # The fix dict arrives with string keys over JSON; coerce to int.
    raw_fix = msg.get("fix") or {}
    fix: dict[int, str] = {}
    if isinstance(raw_fix, dict):
        for k, v in raw_fix.items():
            try:
                fix[int(k)] = str(v)
            except (TypeError, ValueError):
                continue

    save_rule = msg.get("save_rule")
    if save_rule is not None and not isinstance(save_rule, dict):
        save_rule = None
    finding = msg.get("finding")
    if finding is not None and not isinstance(finding, dict):
        finding = None

    return Resolution(
        id=str(msg.get("id", "")),
        verdict=verdict,
        fix=fix,
        notes=str(msg.get("notes", "")),
        raw=msg,
        save_rule=save_rule,
        finding=finding,
    )
