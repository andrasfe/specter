"""COBOL ground-truth snapshot capture for the unified pipeline.

For every test case in a JSONL test store, replay the test case through the
already-compiled instrumented COBOL binary and persist the observed
execution as a JSON snapshot keyed by the test case ID. The same snapshot
is consumed at Java integration-test time by ``EquivalenceAssert`` to prove
the generated Java behaves identically to the original COBOL.

Snapshot fields (per test case):

- ``id`` — test case ID (matches tests.jsonl)
- ``abended`` — True iff COBOL exited non-zero or reported an error
- ``displays`` — non-trace DISPLAY output lines (in order)
- ``paragraphs_covered`` — paragraph trace in execution order
- ``branches`` — sorted list of ``"<id>:<dir>"`` strings (COBOL @@B: probes;
  retained for reporting only — IDs are not cross-tool comparable)
- ``stub_log_keys`` — ordered list of op_keys consumed (call_chain projection)
- ``final_state`` — final values of all observed variables, normalised

Normalisation rules (also implemented in Java by ``EquivalenceAssert``):

- Strings: trim trailing spaces (COBOL pads PIC X with spaces).
- Numerics: when both sides parse as numbers, compare numerically.
- Empty / null / single-space → empty string.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from .cobol_executor import CobolExecutionContext, CobolTestResult, run_test_case

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

_NUMERIC_RE = re.compile(r"^[+-]?\d+(\.\d+)?$")


def normalize_value(v: Any) -> str:
    """Canonicalise a COBOL/Java value for cross-tool equality.

    - ``None``, ``""``, or a single space → ``""``.
    - Numeric strings (incl. leading zeros) → canonical numeric form
      (e.g. ``"00042"`` → ``"42"``, ``"0.50"`` → ``"0.5"``).
    - Everything else: trimmed of trailing spaces (COBOL PIC X padding).
    """
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int,)):
        return str(int(v))
    if isinstance(v, float):
        # Drop trailing zeros + redundant decimal point.
        s = repr(v)
        if "." in s:
            s = s.rstrip("0").rstrip(".")
        return s or "0"
    s = str(v)
    s = s.rstrip(" ")
    if s == "":
        return ""
    if _NUMERIC_RE.match(s):
        # Strip leading zeros while keeping single 0 / sign / decimal.
        sign = ""
        if s[0] in "+-":
            sign, s = s[0], s[1:]
            if sign == "+":
                sign = ""
        if "." in s:
            int_part, dec_part = s.split(".", 1)
            int_part = int_part.lstrip("0") or "0"
            dec_part = dec_part.rstrip("0")
            return sign + int_part + (("." + dec_part) if dec_part else "")
        return sign + (s.lstrip("0") or "0")
    return s


def values_equivalent(a: Any, b: Any) -> bool:
    """True when ``a`` and ``b`` are equivalent under :func:`normalize_value`."""
    return normalize_value(a) == normalize_value(b)


# ---------------------------------------------------------------------------
# Snapshot dataclass
# ---------------------------------------------------------------------------

@dataclass
class CobolSnapshot:
    """COBOL ground truth captured for one test case."""

    id: str
    abended: bool = False
    displays: list[str] = field(default_factory=list)
    paragraphs_covered: list[str] = field(default_factory=list)
    branches: list[str] = field(default_factory=list)
    stub_log_keys: list[str] = field(default_factory=list)
    final_state: dict[str, str] = field(default_factory=dict)
    return_code: int = 0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if d.get("error") is None:
            d.pop("error", None)
        return d

    @classmethod
    def from_result(
        cls,
        tc_id: str,
        result: CobolTestResult,
        track_vars: Iterable[str] | None = None,
    ) -> "CobolSnapshot":
        """Build a snapshot from a CobolTestResult.

        ``track_vars`` restricts which variables get captured into
        ``final_state``. When ``None``, every variable observed in the
        last ``variable_snapshots`` entry is captured.
        """
        # Final paragraph snapshot is the closest thing we have to "final state".
        final_state: dict[str, str] = {}
        if result.variable_snapshots:
            # variable_snapshots is dict[paragraph_name, dict[var, value]]
            # — take the last entry (insertion order = execution order).
            last_snapshot = list(result.variable_snapshots.values())[-1]
            tracked = (
                {v.upper() for v in track_vars} if track_vars else None
            )
            for var, val in last_snapshot.items():
                if tracked and var.upper() not in tracked:
                    continue
                final_state[var] = normalize_value(val)
        # call_chain is list[(call_type, target)] — project to op_keys.
        stub_keys: list[str] = []
        for call_type, target in result.call_chain or []:
            if not target:
                continue
            up = call_type.upper()
            if up.startswith("CALL"):
                stub_keys.append(f"CALL:{target}")
            elif up == "OPEN":
                stub_keys.append(f"OPEN:{target}")
            elif up == "READ":
                stub_keys.append(f"READ:{target}")
            elif up == "WRITE":
                stub_keys.append(f"WRITE:{target}")
            elif up == "CLOSE":
                stub_keys.append(f"CLOSE:{target}")
            elif up.startswith("EXEC"):
                stub_keys.append(target.upper() if target else up)
            else:
                stub_keys.append(f"{up}:{target}")
        # IBM/mainframe convention: rc=0 OK, rc=4 warning (not an abend),
        # rc>=8 hard error. GnuCOBOL emits rc=4 for runtime warnings (e.g.
        # numeric overflow, file-status warnings) even when the program
        # completes all close paragraphs cleanly; Java's `state.abended`
        # flag only flips on explicit ABEND paths, so matching COBOL's rc
        # threshold keeps the two aligned.
        abended = (result.return_code >= 8) or bool(result.error)
        return cls(
            id=tc_id,
            abended=abended,
            displays=list(result.display_output or []),
            paragraphs_covered=list(result.paragraphs_hit or []),
            branches=sorted(result.branches_hit or []),
            stub_log_keys=stub_keys,
            final_state=final_state,
            return_code=int(result.return_code),
            error=result.error,
        )


# ---------------------------------------------------------------------------
# Capture loop
# ---------------------------------------------------------------------------

def normalize_stub_outcomes(raw: Any) -> dict[str, list]:
    """Normalise either JSONL stub_outcomes shape into a dict-of-FIFO.

    The test_store.jsonl file is bimodal:

    - ``TestStore.append`` (test_store.py) writes a dict
      ``{op_key: [entry, entry, ...]}`` where each entry is a list of
      ``[var, val]`` pairs.
    - ``cobol_coverage._save_test_case`` writes a list of
      ``[op_key, entry]`` pairs in execution order.

    Both round-trip into a dict-of-FIFO (entries appended in order of
    appearance) which is what every downstream consumer (snapshot capture,
    Java IT loader, WireMock writer, seed_sql builder) expects.

    ``None`` and empty inputs return ``{}``.
    """
    if not raw:
        return {}
    if isinstance(raw, dict):
        # Already dict-of-FIFO; defensively wrap None queues as [].
        out: dict[str, list] = {}
        for k, v in raw.items():
            out[str(k)] = list(v) if v else []
        return out
    if isinstance(raw, list):
        out = {}
        for pair in raw:
            if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                continue
            op_key = str(pair[0])
            entry = pair[1]
            out.setdefault(op_key, []).append(entry)
        return out
    return {}


def _stub_outcomes_to_log(
    stub_outcomes: Mapping[str, list],
) -> list[tuple[str, list]]:
    """Flatten the stored ``stub_outcomes`` dict into an ordered stub_log.

    The test_store.jsonl format keeps per-op_key FIFO queues but doesn't
    preserve cross-key execution order. ``run_test_case`` already reorders
    OPEN/CLOSE entries internally so a best-effort flatten is sufficient
    for the snapshot phase.
    """
    flat: list[tuple[str, list]] = []
    for op_key, queue in stub_outcomes.items():
        for entry in queue or []:
            flat.append((op_key, entry))
    return flat


def _python_pre_run_stub_log(
    module: Any,
    input_state: dict,
    stub_outcomes: Mapping[str, list] | None,
    stub_defaults: Mapping[str, list] | None,
    pic_info: Mapping[str, dict] | None = None,
) -> list[tuple[str, list]]:
    """Use the generated Python module to derive an execution-ordered stub_log.

    Mirrors :func:`specter.cobol_coverage._python_pre_run`. Lazily imported
    to avoid pulling in coverage machinery when callers don't need it.

    When ``pic_info`` is supplied, each input_state value is PIC-truncated
    before the pre-run so the Python module sees the same field widths the
    COBOL binary would see (otherwise injected garbage like
    ``END-OF-FILE='NVGFYGWWQC'`` causes the Python pre-run to skip the
    main loop body, producing a stub_log with no READ entries and
    desynchronising the subsequent COBOL replay).
    """
    from .cobol_coverage import _python_pre_run  # local import
    truncated = dict(input_state)
    if pic_info:
        from .pic_extractor import truncate_for_pic
        truncated = {
            k: truncate_for_pic(v, pic_info.get(k.upper()))
            for k, v in input_state.items()
        }
    return _python_pre_run(
        module,
        truncated,
        dict(stub_outcomes or {}),
        dict(stub_defaults or {}),
    )


def iter_test_cases(test_store_path: str | Path) -> Iterable[dict]:
    """Yield each test case dict from a JSONL store, skipping progress records."""
    with open(test_store_path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "id" in obj and not obj.get("_type"):
                yield obj


def capture_snapshots(
    test_store_path: str | Path,
    context: CobolExecutionContext,
    output_dir: str | Path,
    *,
    python_module: Any | None = None,
    track_vars: Iterable[str] | None = None,
    timeout: int = 30,
    progress_every: int = 25,
    pic_info: Mapping[str, dict] | None = None,
    injectable_vars: Iterable[str] | None = None,
) -> list[Path]:
    """Replay every test case through the compiled COBOL and write snapshots.

    Args:
        test_store_path: Path to the JSONL test store produced by
            :func:`specter.cobol_coverage.run_cobol_coverage`.
        context: Already-compiled COBOL execution context. Reuse the one
            from the coverage phase to avoid recompiling.
        output_dir: Directory to write ``<tc_id>.json`` snapshot files.
        python_module: Optional generated Python module. When provided, used
            to derive an execution-ordered stub_log via the same pre-run
            mechanism the coverage loop uses. When ``None``, the snapshot
            phase falls back to a flat dict-iteration order which is correct
            in most cases (run_test_case reorders OPEN/CLOSE internally).
        track_vars: Restrict which final-state variables are captured.
            Default (``None``): capture every variable in the last paragraph
            snapshot.
        timeout: Per-test-case execution timeout (seconds).
        progress_every: Log a progress line every N test cases.

    Returns:
        List of paths to the snapshot files written, in test case order.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    inj_set: set[str] | None = (
        {v.upper() for v in injectable_vars} if injectable_vars else None
    )

    written: list[Path] = []
    n_total = 0
    n_ok = 0
    n_err = 0
    seen_ids: set[str] = set()  # dedup: cobol_coverage's test_store accumulates

    for tc in iter_test_cases(test_store_path):
        tc_id_check = str(tc.get("id", ""))
        if tc_id_check in seen_ids:
            continue
        seen_ids.add(tc_id_check)
        n_total += 1
        tc_id = str(tc["id"])
        input_state = tc.get("input_state") or {}
        stub_outcomes = normalize_stub_outcomes(tc.get("stub_outcomes"))
        stub_defaults = tc.get("stub_defaults") or {}
        if isinstance(stub_defaults, list):
            stub_defaults = normalize_stub_outcomes(stub_defaults)

        # Filter input_state to the injectable set (mirrors what COBOL's
        # SPECTER-READ-INIT-VARS dispatcher accepts) and apply PIC
        # truncation to the surviving values. Without these two steps the
        # COBOL binary's runtime state diverges from Java's right after
        # the initial INIT records are consumed.
        if inj_set is not None:
            filtered = {k: v for k, v in input_state.items() if k.upper() in inj_set}
        else:
            filtered = dict(input_state)
        if pic_info:
            from .pic_extractor import truncate_for_pic
            cobol_input_state = {
                k: truncate_for_pic(v, pic_info.get(k.upper()))
                for k, v in filtered.items()
            }
        else:
            cobol_input_state = dict(filtered)

        if python_module is not None:
            # Use the SAME (filtered + truncated) input the COBOL binary
            # gets, so the Python pre-run's stub_log matches COBOL's
            # actual operation sequence.
            stub_log = _python_pre_run_stub_log(
                python_module, cobol_input_state,
                stub_outcomes, stub_defaults,
                pic_info=None,  # already truncated above
            )
        else:
            stub_log = _stub_outcomes_to_log(stub_outcomes)

        try:
            result = run_test_case(
                context,
                cobol_input_state,
                stub_log,
                timeout=timeout,
                stub_defaults=dict(stub_defaults) if stub_defaults else None,
            )
        except Exception as exc:
            log.warning("snapshot capture failed for %s: %s", tc_id, exc)
            result = CobolTestResult(error=str(exc), return_code=-1)
            n_err += 1
        else:
            if result.error:
                n_err += 1
            else:
                n_ok += 1

        snapshot = CobolSnapshot.from_result(
            tc_id, result, track_vars=track_vars,
        )
        path = out / f"{tc_id}.json"
        path.write_text(
            json.dumps(snapshot.to_dict(), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        written.append(path)

        if n_total % progress_every == 0:
            log.info(
                "captured %d/%d snapshots (%d ok, %d errors)",
                n_total, n_total, n_ok, n_err,
            )

    log.info(
        "snapshot capture complete: %d total, %d ok, %d errors",
        n_total, n_ok, n_err,
    )
    return written
