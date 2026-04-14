"""WireMock stub-mapping generator for synchronous CALL outcomes.

Translates per-test-case ``stub_outcomes["CALL:<PROGNAME>"]`` entries into
WireMock stub mapping JSON files. Each mapping makes WireMock respond to
``POST /<progname-lowercase>`` with the JSON-serialised output variable
assignments from the corresponding stub outcome.

Multi-outcome chains (a program calls ``CALL 'FOO'`` twice in one test
case) use WireMock's scenario state so the responses are returned in
order, isolated per test case.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping


_MQ_CALL_RE = re.compile(r"^CALL:MQ", re.IGNORECASE)


def is_routable_call_key(op_key: str) -> bool:
    """Return True if the op_key is a non-MQ ``CALL:<PROG>`` we should mock."""
    if not op_key.startswith("CALL:"):
        return False
    return _MQ_CALL_RE.match(op_key) is None


def _outcome_pairs_to_json_body(pairs: list) -> dict[str, Any]:
    """Convert a stub-outcome entry (``[[var, val], ...]``) to a JSON body dict."""
    body: dict[str, Any] = {}
    if not pairs:
        return body
    for pair in pairs:
        if not isinstance(pair, (list, tuple)) or len(pair) < 2:
            continue
        var = str(pair[0])
        val = pair[1]
        body[var] = val
    return body


def render_mapping(
    progname: str,
    outcome_pairs: list,
    *,
    scenario_name: str | None = None,
    required_state: str | None = None,
    new_state: str | None = None,
    priority: int = 5,
) -> dict[str, Any]:
    """Build a single WireMock stub-mapping document.

    Args:
        progname: COBOL program name (e.g. ``"CUSTAPI"``). Mapped to URL
            path ``/<progname-lowercase>``.
        outcome_pairs: One stub-outcome entry — a list of ``(var, val)``
            pairs to serialise as the JSON response body.
        scenario_name: Optional WireMock scenario for chaining responses
            (only meaningful for multi-outcome chains).
        required_state: The scenario state required for this mapping to
            match. ``None`` means initial state (``"Started"``).
        new_state: The scenario state to transition to after this mapping
            matches. ``None`` means no transition.
        priority: WireMock priority (lower = higher precedence). Defaults
            to ``5``; tests can override.

    Returns:
        A dict suitable for ``json.dumps`` and dropping into
        ``wiremock/mappings/`` as a single mapping file.
    """
    mapping: dict[str, Any] = {
        "request": {
            "method": "POST",
            "urlPattern": "/" + progname.lower(),
        },
        "response": {
            "status": 200,
            "headers": {"Content-Type": "application/json"},
            "jsonBody": _outcome_pairs_to_json_body(outcome_pairs),
        },
        "priority": priority,
    }
    if scenario_name:
        mapping["scenarioName"] = scenario_name
        mapping["requiredScenarioState"] = required_state or "Started"
        if new_state:
            mapping["newScenarioState"] = new_state
    return mapping


def write_mappings(
    test_case_id: str,
    stub_outcomes: Mapping[str, list],
    out_dir: str | Path,
) -> list[Path]:
    """Write all WireMock mappings for one test case under ``out_dir/<tc_id>/``.

    Iterates non-MQ ``CALL:*`` keys in ``stub_outcomes``. For each key with
    multiple FIFO entries, chains them via per-test-case scenario state so
    responses fire in order. Returns the list of files written (sorted).
    """
    out_dir = Path(out_dir)
    files: list[Path] = []

    tc_dir = out_dir / test_case_id
    has_routable = any(is_routable_call_key(k) for k in stub_outcomes)
    if not has_routable:
        return files

    tc_dir.mkdir(parents=True, exist_ok=True)

    for op_key, queue in stub_outcomes.items():
        if not is_routable_call_key(op_key):
            continue
        progname = op_key.split(":", 1)[1]
        entries = list(queue) if queue else []
        if not entries:
            continue

        scenario = f"{test_case_id}_{progname}" if len(entries) > 1 else None
        for seq, entry in enumerate(entries):
            req_state: str | None
            new_state: str | None
            if scenario is None:
                req_state = None
                new_state = None
            elif seq == 0:
                req_state = "Started"
                new_state = f"step_{seq + 1}"
            else:
                req_state = f"step_{seq}"
                new_state = (
                    f"step_{seq + 1}"
                    if seq + 1 < len(entries)
                    else None
                )
            mapping = render_mapping(
                progname,
                entry,
                scenario_name=scenario,
                required_state=req_state,
                new_state=new_state,
            )
            fname = f"{seq:03d}_{progname.lower()}.json"
            fpath = tc_dir / fname
            fpath.write_text(json.dumps(mapping, indent=2), encoding="utf-8")
            files.append(fpath)

    return sorted(files)
