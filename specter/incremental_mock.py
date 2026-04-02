"""Incremental COBOL mock generation with compile-after-each-step.

Replaces the monolithic instrument_cobol() + agent_compile() flow with an
incremental approach: apply transformations in small phases, compile after
each phase, fix errors immediately using LLM + prior resolutions, and
record every resolution for learning.

Key advantages over the old approach:
1. Never more than a handful of errors at a time -- easy for LLM to fix
2. Resolution log accumulates knowledge -- later phases benefit from earlier fixes
3. No cascading failures -- each step is verified before the next
4. Resolution log is reusable -- re-runs apply cached fixes instantly
5. Branch probes are done last, after everything else compiles
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

# Fixed-format COBOL column constants (mirrored from cobol_mock)
_SEQ = "      "        # Cols 1-6: sequence area
_A = "       "         # Cols 1-7: area A start (col 8)
_B = "           "     # Cols 1-11: area B start (col 12)
_CMT = "      *"       # Comment line prefix (col 7 = *)

# Compilation flags shared across all syntax checks and final compilation
_COBC_COMMON_FLAGS = [
    "-std=ibm",
    "-Wno-dialect",
    "-frelax-syntax-checks",
    "-frelax-level-hierarchy",
]

_COBOL_FIX_KNOWLEDGE = """\
COBOL FIXED-FORMAT RULES:
- Cols 1-6: sequence numbers (ignored). Col 7: indicator (* = comment, - = continuation, space = code). Cols 8-72: code. Cols 73-80: ignored.
- ALL code must fit within columns 8-72. If a statement extends past col 72, the compiler silently truncates it → "unexpected identifier". Fix by splitting the line.
- 01-level items start in Area A (col 8). 05/10/etc items start in Area B (col 12+).
- Every data definition and statement MUST end with a period.

ERROR PATTERNS AND FIXES:
- 'X is not defined': X is used but has no definition. If X is used as 'FIELD OF RECORD', you need:
    01 RECORD.
       05 FIELD PIC X(20).
  Add ALL fields used with 'OF RECORD', not just one. Put in WORKING-STORAGE before PROCEDURE DIVISION.
- 'X is not a file name': X is used in a file operation (OPEN/READ/WRITE/CLOSE) but has no SELECT clause. Two things are needed:
    1. In FILE-CONTROL paragraph, add: SELECT X ASSIGN TO 'X'.
    2. In FILE SECTION (before WORKING-STORAGE), add: FD X. / 01 X-RECORD PIC X(256).
  If a FILE STATUS variable (like FILE-STATUS-X or WS-FS-X) is referenced in the program, also define it in WORKING-STORAGE: 01 FILE-STATUS-X PIC XX VALUE '00'.
- 'syntax error, unexpected ASSIGN': Usually a malformed SELECT statement. The correct syntax is:
    SELECT file-name ASSIGN TO 'literal'.
  Check that the file name comes directly after SELECT (no stray keywords). If SELECT OPTIONAL was used, it must be: SELECT OPTIONAL file-name ASSIGN TO 'literal'.
- 'X is ambiguous; needs qualification': X is defined in multiple records. Use 'X OF RECORD-NAME' to qualify, or comment out the duplicate 01-level definition.
- 'duplicate definition': two definitions for same name. Comment out one with * in col 7.
- 'PICTURE clause required': a group item (01/05) has no PIC and no subordinate items. Add PIC X(256) or add child 05 items.
- 'unexpected Identifier, expecting SECTION or .': the PREVIOUS line is missing its terminal period, or content extends past col 72.
- 'syntax error, unexpected .': a period is in the wrong place (e.g., inside an IF block). Remove it or add END-IF before it.
- 'unexpected ELSE/END-IF': mismatched IF/ELSE/END-IF. The IF block structure is broken.
- 'invalid target for TALLYING/INSPECT': the target variable needs to be defined as numeric (PIC 9).
- VALUES ARE → VALUE (GnuCOBOL doesn't accept VALUES ARE).
- 'continuation character expected': the previous line was split past col 72 but the next line doesn't have '-' in col 7. Two fixes:
  (a) If the line is too long: split it so the first part ends before col 72, and start the remainder on a new line at col 12 (Area B). No continuation needed for statements split at a space boundary.
  (b) If a string literal is split across lines: col 7 of the continuation line MUST be '-' and the string resumes with a quote in Area B: `      -    'rest of string'`
- 'could not find a match for PICTURE': the PIC clause format is wrong. Common PIC types:
  * PIC X(n) — alphanumeric, n chars
  * PIC 9(n) — unsigned integer
  * PIC S9(n) — signed integer
  * PIC S9(n)V9(m) — signed decimal, m decimal places
  * PIC S9(n)V9(m) COMP-3 — packed decimal (common for amounts)
  * PIC 99 — 2-digit number (status codes)
- 'PERFORM/VARYING identifier expected': a PERFORM VARYING loop uses an undefined variable. Add the loop counter as 01 var PIC 9(4).
- 'is not a numeric value': a VALUE clause uses a non-numeric literal for a numeric PIC. Use VALUE 0 (not VALUE SPACES) for PIC 9 fields.
- 'group item X cannot have PICTURE clause': a group item (has subordinate 05/10 items) cannot also have a PIC clause. Remove the PIC clause from the group item line. This is valid in IBM COBOL but rejected by GnuCOBOL.

CRITICAL RULES:
- NEVER comment out lines that other code references — this creates cascading "not defined" errors.
- ALL lines must fit within cols 8-72. Count carefully! Col 1 is position 1. If content would go past col 72, split the line.
- When adding stub definitions, use the correct PIC clause based on how the variable is used:
  * Compared to SPACES or moved from string → PIC X(n)
  * Tested with NUMERIC or used in COMPUTE → PIC 9(n) or PIC S9(n)V99 COMP-3
  * Used as status code (STATUS, CD, IND) → PIC XX or PIC 99
  * Used as date (DT, DATE) → PIC X(10)
  * Used as amount (AMT, RATE, BAL) → PIC S9(13)V99 COMP-3
  * Used as counter/index → PIC 9(4) or PIC S9(4) COMP
- When splitting long lines: put the continuation on the next line starting at col 12 (Area B). Do NOT use continuation character (-) unless splitting a string literal.
"""

_COBC_SYNTAX_TIMEOUT = 90
_COBC_COMPILE_TIMEOUT = 120


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Resolution:
    """A single error resolution recorded during incremental instrumentation."""

    phase: str
    batch: int
    transformation: str
    error: str
    fix: str
    fix_lines: dict[str, str]  # line_number (str) -> fixed content
    verified: bool
    timestamp: str = ""

    def summary(self) -> str:
        """One-line human-readable summary for LLM context."""
        return (
            f"Phase {self.phase} batch {self.batch}: "
            f"{self.error!r} -> {self.fix}"
        )


@dataclass
class PhaseResult:
    """Outcome of a single instrumentation phase."""

    phase: str
    errors_before: int
    errors_after: int
    resolutions: list[Resolution] = field(default_factory=list)
    skipped: bool = False


# ---------------------------------------------------------------------------
# Compilation helpers
# ---------------------------------------------------------------------------

def _cobc_syntax_check(
    source_path: Path,
    copybook_dirs: list[Path] | None = None,
    timeout: int = _COBC_SYNTAX_TIMEOUT,
) -> tuple[int, str]:
    """Run cobc syntax-only check.

    Returns (return_code, stderr_text).
    """
    cmd = ["cobc", "-fsyntax-only"] + _COBC_COMMON_FLAGS + [str(source_path)]
    if copybook_dirs:
        for d in copybook_dirs:
            cmd.extend(["-I", str(d)])
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
        )
        return result.returncode, (result.stderr or "") + "\n" + (result.stdout or "")
    except subprocess.TimeoutExpired:
        return -1, "Syntax check timed out"
    except FileNotFoundError:
        return -1, "cobc not found on PATH"


def _cobc_compile(
    source_path: Path,
    output_path: Path,
    copybook_dirs: list[Path] | None = None,
    timeout: int = _COBC_COMPILE_TIMEOUT,
) -> tuple[int, str]:
    """Run cobc full compilation.

    Returns (return_code, stderr_text).
    """
    cmd = [
        "cobc", "-x",
    ] + _COBC_COMMON_FLAGS + [
        "-fmax-errors=10000",
        "-o", str(output_path),
        str(source_path),
    ]
    if copybook_dirs:
        for d in copybook_dirs:
            cmd.extend(["-I", str(d)])
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
        )
        return result.returncode, (result.stderr or "") + "\n" + (result.stdout or "")
    except subprocess.TimeoutExpired:
        return -1, "Compilation timed out"
    except FileNotFoundError:
        return -1, "cobc not found on PATH"


def _parse_errors(stderr: str, source_name: str) -> list[tuple[int, str]]:
    """Parse error lines from cobc output.

    Returns list of (lineno, error_message) tuples, deduplicated by line.
    """
    errors: list[tuple[int, str]] = []
    seen: set[int] = set()
    for line in stderr.splitlines():
        if "error:" not in line.lower():
            continue
        m = re.search(rf"{re.escape(source_name)}:(\d+):\s*error:\s*(.*)", line)
        if m:
            lineno = int(m.group(1))
            msg = m.group(2).strip()
            if lineno not in seen:
                errors.append((lineno, msg))
                seen.add(lineno)
    return errors


# ---------------------------------------------------------------------------
# Resolution log persistence
# ---------------------------------------------------------------------------

def _load_resolutions(path: Path) -> list[Resolution]:
    """Load resolution log from JSON file."""
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        resolutions = []
        for entry in data.get("resolutions", []):
            # Ensure fix_lines keys are strings
            fix_lines = {str(k): v for k, v in entry.get("fix_lines", {}).items()}
            resolutions.append(Resolution(
                phase=entry.get("phase", ""),
                batch=entry.get("batch", 0),
                transformation=entry.get("transformation", ""),
                error=entry.get("error", ""),
                fix=entry.get("fix", ""),
                fix_lines=fix_lines,
                verified=entry.get("verified", False),
                timestamp=entry.get("timestamp", ""),
            ))
        log.info("Loaded %d prior resolutions from %s", len(resolutions), path)
        return resolutions
    except (json.JSONDecodeError, TypeError, KeyError) as exc:
        log.warning("Failed to load resolution log: %s", exc)
        return []


def _save_resolutions(resolutions: list[Resolution], path: Path) -> None:
    """Save resolution log to JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "version": 1,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "resolutions": [asdict(r) for r in resolutions],
    }
    path.write_text(json.dumps(data, indent=2, default=str))


def _audit_fix(
    audit_path: Path,
    phase: str,
    batch: int,
    attempt: int,
    fixes: dict[int, str],
    old_lines: list[str],
    error_desc: str,
    result: str,
) -> None:
    """Append a human-readable entry to the fix audit log.

    Each entry shows: the phase, what error triggered the fix, and for
    every changed line the BEFORE and AFTER content.  This lets the user
    verify the LLM isn't commenting out valid code.
    """
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    lines_out: list[str] = []
    lines_out.append(f"{'='*72}")
    lines_out.append(f"[{ts}] Phase: {phase}  Batch: {batch}  Attempt: {attempt}")
    lines_out.append(f"Error: {error_desc}")
    lines_out.append(f"Result: {result}")
    lines_out.append(f"Lines changed: {len(fixes)}")
    lines_out.append("")

    n_commented_out = 0
    n_stub_added = 0
    n_modified = 0

    for ln in sorted(fixes.keys()):
        idx = ln - 1
        old = old_lines[idx].rstrip() if 0 <= idx < len(old_lines) else "(new line)"
        new = fixes[ln].rstrip() if fixes[ln] else "(deleted)"

        was_comment = isinstance(old, str) and len(old) > 6 and old[6:7] == "*"
        is_comment = isinstance(new, str) and len(new) > 6 and new[6:7] == "*"

        tag = ""
        if is_comment and not was_comment:
            tag = " [COMMENTED OUT]"
            n_commented_out += 1
        elif not is_comment and old == "(new line)":
            tag = " [ADDED]"
            n_stub_added += 1
        elif old != new:
            tag = " [MODIFIED]"
            n_modified += 1

        lines_out.append(f"  Line {ln}{tag}:")
        lines_out.append(f"    OLD: {old}")
        lines_out.append(f"    NEW: {new}")

    lines_out.append("")
    lines_out.append(f"  Summary: {n_commented_out} commented out, "
                     f"{n_stub_added} added, {n_modified} modified")
    if n_commented_out > n_stub_added + n_modified:
        lines_out.append(f"  ⚠️  WARNING: More lines commented out than added/modified!")
    lines_out.append("")

    with open(audit_path, "a") as f:
        f.write("\n".join(lines_out) + "\n")


# ---------------------------------------------------------------------------
# Phase checkpoint for resume
# ---------------------------------------------------------------------------

def _load_checkpoint(output_dir: Path) -> dict:
    """Load phase checkpoint. Returns {} if none exists."""
    path = output_dir / "phase_checkpoint.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
        mock_path = output_dir / data.get("mock_cbl_name", "")
        if mock_path.exists():
            import hashlib
            actual_hash = hashlib.sha256(mock_path.read_bytes()).hexdigest()
            if actual_hash != data.get("mock_cbl_hash", ""):
                log.warning("Checkpoint hash mismatch — starting fresh")
                return {}
        log.info("Resuming from phase %d (%s)",
                 data.get("last_completed_phase_number", -1),
                 data.get("last_completed_phase", "unknown"))
        return data
    except (json.JSONDecodeError, TypeError, KeyError) as exc:
        log.warning("Failed to load checkpoint: %s", exc)
        return {}


def _save_checkpoint(output_dir: Path, phase_name: str, phase_number: int,
                     mock_path: Path) -> None:
    """Save phase checkpoint after successful completion."""
    import hashlib
    path = output_dir / "phase_checkpoint.json"
    data = {
        "last_completed_phase": phase_name,
        "last_completed_phase_number": phase_number,
        "mock_cbl_name": mock_path.name,
        "mock_cbl_hash": hashlib.sha256(mock_path.read_bytes()).hexdigest(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(data, indent=2))


# ---------------------------------------------------------------------------
# LLM-driven error fixing
# ---------------------------------------------------------------------------

def _build_fix_prompt(
    errors: list[tuple[int, str]],
    src_lines: list[str],
    source_name: str,
    phase: str,
    resolutions: list[Resolution],
) -> str:
    """Build an LLM prompt for fixing compilation errors.

    Includes all prior resolutions so the LLM learns from previous fixes.
    """
    # Build resolution summary — include RELEVANT resolutions (matching error
    # types) plus most recent ones. Cap at 30 to avoid context overload.
    resolution_text = ""
    if resolutions:
        current_error_types = {msg.split(",")[0].strip() for _, msg in errors}
        # Prioritize: resolutions matching current error types
        relevant = [r for r in resolutions if any(
            et in r.error for et in current_error_types
        )]
        # Add recent resolutions for general context
        recent = resolutions[-15:]
        # Combine, deduplicate, cap at 30
        seen: set[str] = set()
        selected: list[Resolution] = []
        for r in relevant + recent:
            key = f"{r.error}:{r.fix}"
            if key not in seen:
                seen.add(key)
                selected.append(r)
            if len(selected) >= 30:
                break
        summaries = [r.summary() for r in selected]
        resolution_text = (
            "Prior resolutions from this run (apply these proactively):\n"
            + "\n".join(f"- {s}" for s in summaries)
            + "\n\n"
        )

    # Group errors and extract context
    error_lines = sorted(set(e[0] for e in errors))
    first_line = error_lines[0] if error_lines else 1
    last_line = error_lines[-1] if error_lines else len(src_lines)
    ctx_start = max(0, first_line - 101)
    ctx_end = min(len(src_lines), last_line + 20)

    numbered_context = "\n".join(
        f"{ctx_start + i + 1:5d}: {line.rstrip()}"
        for i, line in enumerate(src_lines[ctx_start:ctx_end])
    )

    error_desc = "\n".join(
        f"  Line {ln}: {msg}" for ln, msg in errors
    )

    prompt = (
        "You are fixing GnuCOBOL compilation errors in a COBOL program "
        "being incrementally instrumented for mock execution.\n\n"
        f"Current phase: {phase}\n"
        f"File: {source_name} ({len(src_lines)} lines total)\n"
        f"Total errors: {len(errors)}\n\n"
        f"{resolution_text}"
        f"Current errors to fix:\n{error_desc}\n\n"
        f"Source context (lines {ctx_start + 1}-{ctx_end}):\n"
        f"```cobol\n{numbered_context}\n```\n\n"
        f"{_COBOL_FIX_KNOWLEDGE}\n"
        "Output ONLY the corrected lines as a flat JSON object mapping "
        "line number to fixed content.\n"
        'Example: {"5417": "       10  EXT-K1-WS  PIC 99.", '
        '"5418": "       10  EXT-K2-WS  PIC 99."}\n'
        "Do NOT wrap in outer keys. Do NOT add explanations.\n"
        "Only include lines that changed. Preserve COBOL column formatting "
        "(cols 7-72)."
    )
    return prompt


def _apply_preventive_fixes(
    src_lines: list[str],
    resolutions: list[Resolution],
) -> list[str]:
    """Apply verified fix_lines from prior resolutions to prevent known errors.

    This lets re-runs skip LLM calls for previously resolved issues.
    """
    lines = list(src_lines)
    applied = 0
    for res in resolutions:
        if not res.verified or not res.fix_lines:
            continue
        for ln_str, content in res.fix_lines.items():
            try:
                idx = int(ln_str) - 1
            except (ValueError, TypeError):
                continue
            if 0 <= idx < len(lines):
                lines[idx] = content if content.endswith("\n") else content + "\n"
                applied += 1
    if applied:
        log.debug("Applied %d preventive fix lines from prior resolutions", applied)
    return lines


_MAX_CONTEXT_LINES = 1000  # max lines sent to LLM per error (was 500)


def _cluster_errors(
    errors: list[tuple[int, str]],
    gap: int = 10,
) -> list[list[tuple[int, str]]]:
    """Group errors within `gap` lines of each other into clusters.

    When 20 errors are all in lines 14620-14630, they're one root cause.
    Treating them as one cluster prevents the LLM from trying each line
    separately with the same doomed fix.
    """
    if not errors:
        return []
    sorted_errs = sorted(errors, key=lambda e: e[0])
    clusters: list[list[tuple[int, str]]] = [[sorted_errs[0]]]
    for err in sorted_errs[1:]:
        if err[0] - clusters[-1][-1][0] <= gap:
            clusters[-1].append(err)
        else:
            clusters.append([err])
    return clusters


def _group_errors_by_type(
    errors: list[tuple[int, str]],
) -> dict[str, list[tuple[int, str]]]:
    """Group errors by their type signature for batch fixing.

    E.g., all "'X' is not defined" errors go into one group so the LLM
    can add all stub definitions at once rather than one at a time.
    """
    groups: dict[str, list[tuple[int, str]]] = {}
    for ln, msg in errors:
        # Normalize: "'FNPLN' is not defined" → "is not defined"
        # Keep the general pattern, drop the specific variable name
        if "is not defined" in msg:
            key = "is not defined"
        elif "not a file name" in msg:
            key = "not a file name"
        elif "syntax error" in msg:
            key = "syntax error"
        elif "PICTURE clause" in msg.upper():
            key = "PICTURE clause"
        elif "duplicate" in msg.lower():
            key = "duplicate"
        else:
            key = msg.split(",")[0].strip()[:40]
        groups.setdefault(key, []).append((ln, msg))
    return groups


def _fix_group_item_pic(
    errors: list[tuple[int, str]],
    src_lines: list[str],
) -> tuple[list[str], int]:
    """Fix 'group item X cannot have PICTURE clause' errors.

    GnuCOBOL rejects PIC clauses on group items (items with children).
    IBM COBOL is more lenient. Fix: remove the PIC clause from the
    identified group item.
    """
    # Collect group item names from errors
    group_items: dict[str, int] = {}  # name → error line
    for ln, msg in errors:
        m = re.match(r"group item '([A-Z0-9_-]+)' cannot have PICTURE",
                     msg, re.IGNORECASE)
        if m:
            group_items[m.group(1).upper()] = ln

    if not group_items:
        return src_lines, 0

    fixed = 0
    result = list(src_lines)
    for i, line in enumerate(result):
        if len(line) > 6 and line[6:7] == "*":
            continue
        upper = line.upper()
        for name in group_items:
            if name in upper and "PIC" in upper:
                # Remove PIC clause from this line
                new_line = re.sub(
                    r"\s+PIC(?:TURE)?\s+\S+",
                    "",
                    line.rstrip("\n"),
                    flags=re.IGNORECASE,
                )
                # Ensure it still ends with period if it did before
                if line.rstrip().endswith(".") and not new_line.rstrip().endswith("."):
                    new_line = new_line.rstrip() + "."
                result[i] = new_line + "\n"
                fixed += 1
                break

    return result, fixed


def _find_working_storage_range(src_lines: list[str]) -> tuple[int, int] | None:
    """Find the WORKING-STORAGE SECTION line range.

    Returns (start_idx, end_idx) or None if not found.  Used to give the LLM
    a second context chunk so it can add stub definitions in the right place.
    """
    ws_start = None
    ws_end = None
    for i, line in enumerate(src_lines):
        upper = line.upper().strip()
        if upper.startswith("*"):
            continue
        if "WORKING-STORAGE SECTION" in upper:
            ws_start = i
        elif ws_start is not None and any(
            kw in upper for kw in (
                "PROCEDURE DIVISION",
                "LINKAGE SECTION",
                "LOCAL-STORAGE SECTION",
                "REPORT SECTION",
                "SCREEN SECTION",
                "FILE SECTION",
            )
        ):
            ws_end = i
            break
    if ws_start is not None:
        if ws_end is None:
            ws_end = min(ws_start + 500, len(src_lines))
        return ws_start, ws_end
    return None


def _fix_long_lines(src_lines: list[str]) -> tuple[list[str], int]:
    """Fix lines where COBOL content extends past column 72.

    In fixed-format COBOL, cols 73-80 are ignored (sequence area).
    If a statement's period or identifier spills past col 72, the
    compiler sees a truncated line → "unexpected identifier" errors.

    Fix: wrap long lines by splitting before col 72 and continuing
    on the next line (area B indent).
    """
    result: list[str] = []
    fixed = 0
    for line in src_lines:
        # Only fix non-comment lines
        if len(line) > 7 and line[6:7] == "*":
            result.append(line)
            continue

        # Check if meaningful content extends past col 72
        content = line.rstrip("\n\r")
        if len(content) <= 72:
            result.append(line)
            continue

        # Content past col 72 — need to wrap
        # Find a safe split point before col 72 (at a space)
        active = content[:72]
        overflow = content[72:].lstrip()

        # Don't fix if overflow is just sequence numbers (digits/spaces)
        if not overflow or overflow.replace(" ", "").isdigit():
            result.append(line)
            continue

        # Find last space in the active area to split at
        split_at = active.rfind(" ", 12, 72)
        if split_at < 12:
            # No good split point — use col 72 boundary
            split_at = 72

        first_part = content[:split_at].rstrip()
        remainder = content[split_at:].strip()

        # If remainder has the overflow too, include it
        if len(content) > 72:
            remainder = content[split_at:].strip()

        result.append(first_part + "\n")
        # Continuation line in area B
        result.append(f"{_B}{remainder}\n")
        fixed += 1

    return result, fixed


def _generate_record_stubs(
    errors: list[tuple[int, str]],
    src_lines: list[str],
) -> list[str]:
    """Generate deterministic stub definitions for 'not defined' errors.

    Analyzes usage patterns in the source to build proper record structures
    instead of flat PIC X(256) stubs that the LLM keeps trying.

    Returns COBOL lines to insert into WORKING-STORAGE.
    """
    # Collect all undefined variable names
    undefined: set[str] = set()
    _error_qualified: dict[str, set[str]] = {}  # parent→{fields} from errors
    for _, msg in errors:
        # Match both simple ('X') and qualified ('X IN Y') names
        m = re.match(
            r"'([A-Z0-9_-]+(?:\s+(?:IN|OF)\s+[A-Z0-9_-]+)?)'\s+is not defined",
            msg, re.IGNORECASE,
        )
        if m:
            name = m.group(1).upper()
            # Parse qualified names: "FIELD IN RECORD" → track both
            qm = re.match(r"([A-Z0-9_-]+)\s+(?:IN|OF)\s+([A-Z0-9_-]+)", name)
            if qm:
                field, parent = qm.group(1), qm.group(2)
                undefined.add(field)
                undefined.add(parent)
                # Pre-populate parent→field mapping from the error itself
                _error_qualified.setdefault(parent, set()).add(field)
            else:
                undefined.add(name)

    if not undefined:
        return []

    source_text = "".join(src_lines)
    source_upper = source_text.upper()

    # Group fields by parent record (via OF/IN qualifier)
    # Pattern: FIELD-NAME OF RECORD-NAME
    of_re = re.compile(
        r"\b([A-Z0-9_-]+)\s+(?:OF|IN)\s+([A-Z0-9_-]+)\b",
        re.IGNORECASE,
    )
    parent_fields: dict[str, set[str]] = {}  # parent → {fields}
    standalone: set[str] = set()  # not used with OF

    for match in of_re.finditer(source_upper):
        field = match.group(1)
        parent = match.group(2)
        if field in undefined or parent in undefined:
            parent_fields.setdefault(parent, set()).add(field)

    # Merge qualified names from error messages themselves
    for parent, fields in _error_qualified.items():
        parent_fields.setdefault(parent, set()).update(fields)

    # Check which variables are ALREADY defined in the source
    # (prevents "ambiguous" errors from duplicate definitions)
    already_defined: set[str] = set()
    def_re = re.compile(
        r"^\s{6}\s+\d{2}\s+([A-Z0-9_-]+)\b",
        re.IGNORECASE,
    )
    for src_line in src_lines:
        if len(src_line) > 6 and src_line[6:7] == "*":
            continue  # skip comments
        dm = def_re.match(src_line)
        if dm:
            already_defined.add(dm.group(1).upper())

    # Remove already-defined variables from undefined set
    actually_undefined = undefined - already_defined
    if not actually_undefined:
        return []

    # Remove already-defined fields from parent groups
    for parent in list(parent_fields.keys()):
        parent_fields[parent] = {
            f for f in parent_fields[parent] if f in actually_undefined
        }

    # Variables not in any OF relationship
    standalone: set[str] = set()
    for var in actually_undefined:
        is_child = any(var in fields for fields in parent_fields.values())
        is_parent = var in parent_fields
        if not is_child and not is_parent:
            standalone.add(var)

    # Infer PIC clause from usage context
    def _infer_pic(var_name: str) -> str:
        # Check for NUMERIC test → alphanumeric
        if re.search(rf"\b{re.escape(var_name)}\b\s+(NOT\s+)?NUMERIC",
                      source_upper):
            return "PIC X(20)"
        # Check for MOVE from known numeric
        m = re.search(rf"MOVE\s+\d+\s+TO\s+{re.escape(var_name)}\b",
                       source_upper)
        if m:
            return "PIC 9(10)"
        # Check subscript usage like VAR(5:11) → alphanumeric with length
        m = re.search(rf"\b{re.escape(var_name)}\s*\(\s*(\d+)\s*:\s*(\d+)\s*\)",
                       source_upper)
        if m:
            total = int(m.group(1)) + int(m.group(2))
            return f"PIC X({total})"
        # Check for comparison with spaces/string
        if re.search(rf"\b{re.escape(var_name)}\b\s+(NOT\s+)?(=|EQUAL)\s+SPACES",
                      source_upper):
            return "PIC X(20)"
        # Check for comparison with numeric literal
        if re.search(rf"\b{re.escape(var_name)}\b\s+(NOT\s+)?(=|EQUAL)\s+\d",
                      source_upper):
            return "PIC 9(10)"
        # Check name patterns
        upper = var_name.upper()
        if any(kw in upper for kw in ("STATUS", "CD", "CODE", "IND", "FLAG")):
            return "PIC X(02)"
        if any(kw in upper for kw in ("AMT", "RATE", "BAL", "AMOUNT")):
            return "PIC S9(13)V99 COMP-3"
        if any(kw in upper for kw in ("DT", "DATE")):
            return "PIC X(10)"
        if any(kw in upper for kw in ("NO", "NBR", "NUM", "ID", "ACCT")):
            return "PIC X(20)"
        return "PIC X(256)"

    stubs: list[str] = []
    stubs.append(f"{_CMT} SPECTER: Auto-generated stubs for undefined variables\n")

    # Generate parent records with children
    for parent, fields in sorted(parent_fields.items()):
        if parent in actually_undefined:
            stubs.append(f"{_A}01  {parent}.\n")
            for field in sorted(fields):
                pic = _infer_pic(field)
                stubs.append(f"{_B}05  {field} {pic}.\n")
            # Ensure parent has at least one child
            if not fields:
                stubs.append(f"{_B}05  FILLER PIC X.\n")
            log.debug("  Stub: 01 %s with %d fields", parent, len(fields))
        elif any(f in actually_undefined for f in fields):
            # Parent exists but some fields are undefined — add just the fields
            for field in sorted(fields):
                if field in actually_undefined:
                    pic = _infer_pic(field)
                    stubs.append(f"{_A}01  {field} {pic}.\n")
                    log.debug("  Stub: 01 %s (orphan field of %s)", field, parent)

    # Generate standalone stubs
    for var in sorted(standalone):
        pic = _infer_pic(var)
        stubs.append(f"{_A}01  {var} {pic}.\n")
        log.debug("  Stub: 01 %s %s (standalone)", var, pic)

    if len(stubs) <= 1:  # only the comment
        return []

    log.info("  Pre-fix: generated %d stub lines for %d undefined vars "
             "(%d already defined, skipped)",
             len(stubs) - 1, len(actually_undefined),
             len(undefined - actually_undefined))

    return stubs


def _generate_file_stubs(
    errors: list[tuple[int, str]],
    src_lines: list[str],
) -> tuple[list[str], list[str]]:
    """Generate deterministic SELECT + FD stubs for 'not a file name' errors.

    Returns (select_lines, fd_lines) to insert into FILE-CONTROL and
    FILE SECTION respectively.
    """
    from .cobol_mock import _A, _B

    missing_files: set[str] = set()
    for _, msg in errors:
        m = re.match(
            r"'([A-Z0-9_-]+)'\s+is not a file name",
            msg, re.IGNORECASE,
        )
        if m:
            missing_files.add(m.group(1).upper())

    if not missing_files:
        return [], []

    source_upper = "".join(src_lines).upper()

    # Check which files already have SELECT clauses
    already_selected: set[str] = set()
    for line in src_lines:
        if len(line) > 6 and line[6] in ("*", "/"):
            continue
        upper = line.upper().strip()
        sm = re.match(r"SELECT\s+(?:OPTIONAL\s+)?([A-Z0-9_-]+)", upper)
        if sm:
            already_selected.add(sm.group(1))

    actually_missing = missing_files - already_selected
    if not actually_missing:
        return [], []

    select_lines: list[str] = []
    fd_lines: list[str] = []

    for fname in sorted(actually_missing):
        select_lines.append(
            f"{_B}SELECT {fname} ASSIGN TO '{fname}'.\n"
        )
        fd_lines.append(f"{_A}FD {fname}.\n")
        fd_lines.append(f"{_A}01 {fname}-RECORD PIC X(256).\n")
        log.debug("  File stub: SELECT + FD for %s", fname)

    log.info("  Pre-fix: generated file stubs for %d missing files: %s",
             len(actually_missing), ", ".join(sorted(actually_missing)))

    return select_lines, fd_lines


def _find_file_control_end(src_lines: list[str]) -> int | None:
    """Find the line index just after the last SELECT in FILE-CONTROL.

    Returns the insertion point for new SELECT clauses, or None if
    FILE-CONTROL is not found.
    """
    in_fc = False
    last_select_end = None
    fc_start = None
    for i, line in enumerate(src_lines):
        upper = line.upper().strip()
        if upper.startswith("*"):
            continue
        if re.match(r"\s*FILE-CONTROL\.", upper):
            in_fc = True
            fc_start = i
            continue
        if in_fc:
            # Stop at next section/division
            if any(kw in upper for kw in (
                "DATA DIVISION", "WORKING-STORAGE SECTION",
                "FILE SECTION", "PROCEDURE DIVISION",
                "I-O-CONTROL.", "LINKAGE SECTION",
            )):
                break
            # Track end of SELECT blocks
            if upper.endswith(".") and last_select_end is None:
                last_select_end = i + 1
            if upper.endswith("."):
                last_select_end = i + 1
    return last_select_end if last_select_end else (fc_start + 1 if fc_start is not None else None)


def _find_file_section_end(src_lines: list[str]) -> int | None:
    """Find the end of FILE SECTION (before WORKING-STORAGE or next section).

    Returns insertion point for new FD entries, or None.
    """
    in_fs = False
    for i, line in enumerate(src_lines):
        upper = line.upper().strip()
        if upper.startswith("*"):
            continue
        if "FILE SECTION" in upper:
            in_fs = True
            continue
        if in_fs and any(kw in upper for kw in (
            "WORKING-STORAGE SECTION", "LINKAGE SECTION",
            "LOCAL-STORAGE SECTION", "PROCEDURE DIVISION",
        )):
            return i
    return None


def _assert_clean(
    source_path: Path,
    phase_name: str,
    copybook_dirs: list[Path] | None = None,
    resolutions: list[Resolution] | None = None,
    resolution_log_path: Path | None = None,
    output_dir: Path | None = None,
    checkpoint_name: str | None = None,
    checkpoint_phase_number: int | None = None,
) -> None:
    """Raise RuntimeError if compilation errors remain after a phase.

    Saves resolutions AND re-saves the checkpoint with the current
    mock.cbl hash before raising, so restart resumes from here
    instead of starting from scratch.
    """
    remaining = _count_current_errors(source_path, copybook_dirs)
    if remaining > 0:
        if resolutions and resolution_log_path:
            _save_resolutions(resolutions, resolution_log_path)
        # Re-save checkpoint with updated hash so restart doesn't
        # invalidate it due to mock.cbl changes from compile_and_fix
        if output_dir and checkpoint_name is not None and checkpoint_phase_number is not None:
            _save_checkpoint(output_dir, checkpoint_name,
                             checkpoint_phase_number, source_path)
        raise RuntimeError(
            f"{phase_name} stalled with {remaining} errors. "
            f"Fix manually or delete phase_checkpoint.json to retry. "
            f"Mock source: {source_path}"
        )


def _count_current_errors(
    source_path: Path,
    copybook_dirs: list[Path] | None = None,
) -> int:
    """Quick error count for gating decisions between phases."""
    rc, stderr = _cobc_syntax_check(source_path, copybook_dirs)
    if rc == 0:
        return 0
    return len(_parse_errors(stderr, source_path.name))


def _compile_and_fix(
    source_path: Path,
    phase: str,
    batch: int,
    resolutions: list[Resolution],
    copybook_dirs: list[Path] | None = None,
    llm_provider=None,
    llm_model: str | None = None,
    max_fix_attempts: int = 200,
    baseline_errors: set[str] | None = None,
    audit_path: Path | None = None,
    checkpoint_dir: Path | None = None,
    checkpoint_name: str | None = None,
    checkpoint_number: int | None = None,
) -> list[Resolution]:
    """Compile, fix errors sequentially until 0 errors or no progress.

    Runs in a simple loop: compile → pick error → fix → compile → repeat.
    Stops when errors reach 0 or stalled (dynamic limit: 10 rounds for
    1 error, 3 rounds for 20+ errors).

    Key capabilities:
    1. **Batch similar errors**: When 5+ errors share the same type, the
       LLM sees ALL of them and can add all stubs at once.
    2. **Two-chunk context**: For "not defined" errors, the LLM also sees
       WORKING-STORAGE so it knows where to add definitions.
    3. **Failed attempt memory**: The LLM sees what was tried and failed.
    4. **Error clustering**: Adjacent errors treated as one root cause.
    5. **Relaxed verification**: Accept if total error count drops.

    Returns new resolutions added during this cycle.
    """
    from .llm_coverage import _query_llm_sync, Message
    from .cobol_fix_cache import _parse_llm_fix_response

    def _save_progress():
        """Save checkpoint with current mock hash — safe to Ctrl-C after."""
        if checkpoint_dir and checkpoint_name is not None and checkpoint_number is not None:
            _save_checkpoint(checkpoint_dir, checkpoint_name,
                             checkpoint_number, source_path)

    new_resolutions: list[Resolution] = []
    source_name = source_path.name

    # --- Pre-fix: fix lines extending past column 72 ---
    # In fixed-format COBOL, cols 73-80 are ignored. If a period or
    # identifier spills past col 72, the compiler sees truncated code.
    src_text = source_path.read_text(errors="replace")
    fixed_lines, n_long = _fix_long_lines(src_text.splitlines(keepends=True))
    if n_long > 0:
        source_path.write_text("".join(fixed_lines))
        log.info("  Pre-fix: wrapped %d lines that extended past column 72",
                 n_long)

    # --- Pre-fix: fix "group item cannot have PICTURE clause" errors ---
    # GnuCOBOL rejects PIC on group items; IBM COBOL allows it.
    rc_grp, stderr_grp = _cobc_syntax_check(source_path, copybook_dirs)
    if rc_grp != 0:
        grp_errors = _parse_errors(stderr_grp, source_name)
        grp_pic = [(ln, msg) for ln, msg in grp_errors
                   if "cannot have PICTURE" in msg]
        if grp_pic:
            src_grp = source_path.read_text(errors="replace").splitlines(keepends=True)
            src_grp, n_grp = _fix_group_item_pic(grp_pic, src_grp)
            if n_grp > 0:
                source_path.write_text("".join(src_grp))
                log.info("  Pre-fix: removed PIC from %d group items", n_grp)

    # --- Pre-fix: deterministic stub generation for "not defined" errors ---
    # Insert stubs ONE AT A TIME, verifying each. This way we keep stubs
    # that work and skip ones that don't, instead of all-or-nothing.
    rc_pre, stderr_pre = _cobc_syntax_check(source_path, copybook_dirs)
    if rc_pre != 0:
        pre_errors = _parse_errors(stderr_pre, source_name)
        not_defined = [(ln, msg) for ln, msg in pre_errors
                       if "is not defined" in msg]
        if not_defined:
            src = source_path.read_text(errors="replace").splitlines(keepends=True)
            stubs = _generate_record_stubs(not_defined, src)
            if stubs:
                ws_range = _find_working_storage_range(src)
                if ws_range:
                    _, ws_end = ws_range
                    # Split stubs into individual definitions (each 01-level
                    # with its children)
                    stub_groups: list[list[str]] = []
                    current_group: list[str] = []
                    for s_line in stubs:
                        stripped = s_line.strip()
                        if stripped.startswith("*"):
                            continue  # skip comment header
                        if re.match(r"^\s*01\s+", s_line):
                            if current_group:
                                stub_groups.append(current_group)
                            current_group = [s_line]
                        elif current_group:
                            current_group.append(s_line)
                    if current_group:
                        stub_groups.append(current_group)

                    stubs_kept = 0
                    stubs_rejected = 0
                    for group in stub_groups:
                        group_name = group[0].strip().split()[1] if len(group[0].strip().split()) > 1 else "?"
                        # Count "not defined" before
                        src_text = source_path.read_text(errors="replace")
                        src_lines_now = src_text.splitlines(keepends=True)
                        ws_range_now = _find_working_storage_range(src_lines_now)
                        if not ws_range_now:
                            break
                        insert_at = ws_range_now[1]

                        # Insert this group
                        for gi, g_line in enumerate(group):
                            src_lines_now.insert(insert_at + gi, g_line)
                        source_path.write_text("".join(src_lines_now))

                        rc_after, stderr_after = _cobc_syntax_check(
                            source_path, copybook_dirs)
                        errs_after = _parse_errors(stderr_after, source_name) if rc_after != 0 else []
                        nd_after = sum(1 for _, m in errs_after if "is not defined" in m)
                        nd_before = sum(1 for _, m in _parse_errors(stderr_pre, source_name)
                                        if "is not defined" in m) if stubs_kept == 0 else nd_after

                        # Recount from current baseline
                        rc_before, stderr_before = _cobc_syntax_check(
                            source_path, copybook_dirs) if stubs_kept > 0 else (rc_pre, stderr_pre)

                        # Keep if it didn't make things worse
                        if len(errs_after) <= len(pre_errors) + stubs_kept + 3:
                            stubs_kept += 1
                            # Update pre_errors baseline for next iteration
                            stderr_pre = stderr_after
                            pre_errors = errs_after
                            log.info("  Pre-fix: kept stub %s (%d lines, "
                                     "errors now %d)",
                                     group_name, len(group), len(errs_after))
                        else:
                            # Revert this group
                            reverted = src_lines_now[:insert_at] + src_lines_now[insert_at + len(group):]
                            source_path.write_text("".join(reverted))
                            stubs_rejected += 1
                            log.info("  Pre-fix: rejected stub %s "
                                     "(%d → %d errors)",
                                     group_name, len(pre_errors), len(errs_after))

                    if stubs_kept > 0 or stubs_rejected > 0:
                        log.info("  Pre-fix: %d stubs kept, %d rejected",
                                 stubs_kept, stubs_rejected)

    # --- Pre-fix: deterministic file stubs for "not a file name" errors ---
    # When a file name is used in OPEN/READ/WRITE/CLOSE but has no SELECT,
    # generate SELECT + FD stubs in FILE-CONTROL and FILE SECTION.
    rc_file, stderr_file = _cobc_syntax_check(source_path, copybook_dirs)
    if rc_file != 0:
        file_errors = _parse_errors(stderr_file, source_name)
        not_a_file = [(ln, msg) for ln, msg in file_errors
                      if "not a file name" in msg]
        if not_a_file:
            src = source_path.read_text(errors="replace").splitlines(keepends=True)
            select_stubs, fd_stubs = _generate_file_stubs(not_a_file, src)
            if select_stubs or fd_stubs:
                modified = False
                # Insert SELECT stubs into FILE-CONTROL
                if select_stubs:
                    fc_end = _find_file_control_end(src)
                    if fc_end is not None:
                        for j, sl in enumerate(select_stubs):
                            src.insert(fc_end + j, sl)
                        modified = True

                # Insert FD stubs into FILE SECTION
                if fd_stubs:
                    fs_end = _find_file_section_end(src)
                    if fs_end is not None:
                        for j, fl in enumerate(fd_stubs):
                            src.insert(fs_end + j, fl)
                        modified = True

                if modified:
                    source_path.write_text("".join(src))
                    rc_verify, stderr_verify = _cobc_syntax_check(
                        source_path, copybook_dirs)
                    errs_verify = (
                        _parse_errors(stderr_verify, source_name)
                        if rc_verify != 0 else []
                    )
                    nf_before = len(not_a_file)
                    nf_after = sum(
                        1 for _, m in errs_verify if "not a file name" in m
                    )
                    if nf_after < nf_before:
                        log.info("  Pre-fix: file stubs resolved %d/%d "
                                 "'not a file name' errors",
                                 nf_before - nf_after, nf_before)
                    else:
                        # Revert — didn't help
                        src_orig = source_path.read_text(errors="replace")
                        # Re-read without our stubs
                        rc_orig, _ = _cobc_syntax_check(
                            source_path, copybook_dirs)
                        log.info("  Pre-fix: file stubs didn't help, keeping "
                                 "(no worse: %d errors)", len(errs_verify))

    failed_error_lines: set[int] = set()
    # Fingerprints of fixes already tried — reject exact duplicates
    tried_fix_fingerprints: set[str] = set()
    # Revert counter per error line — survives resets. After 3 reverts
    # for the same line, it's permanently skipped.
    revert_count: dict[int, int] = {}
    _MAX_REVERTS_PER_LINE = 3

    # Memory of failed attempts: (line, error_msg, fix_summary, reason)
    failed_attempts: list[tuple[int, str, str, str]] = []
    # Memory of successful fixes for context
    successful_fixes: list[str] = []

    # Stall detection: stop only when error count has not decreased for
    # stall_limit consecutive *resets*.  A reset happens when all errors
    # have been attempted and we clear failed_error_lines to try again.
    # Individual failed attempts within a round do NOT count toward stall.
    # The limit scales with error count — try much harder when close to 0.
    rounds_without_progress = 0
    best_error_count = 999999
    attempt = 0

    while attempt < max_fix_attempts:
        attempt += 1
        rc, stderr = _cobc_syntax_check(source_path, copybook_dirs)
        if rc == 0:
            log.info("  Phase %s batch %d: compiles clean", phase, batch)
            return new_resolutions

        errors = _parse_errors(stderr, source_name)
        if not errors:
            log.warning("  Phase %s batch %d: compilation failed (unparseable)", phase, batch)
            return new_resolutions

        # Filter out baseline errors
        if baseline_errors:
            new_errors = [(ln, msg) for ln, msg in errors if msg not in baseline_errors]
            if not new_errors:
                log.info("  Phase %s batch %d: %d errors (all baseline)", phase, batch, len(errors))
                return new_resolutions
        else:
            new_errors = errors

        n_errors = len(new_errors)

        # Permanently skip lines reverted too many times — BUT only if
        # there are other errors to work on. If it's the last error(s),
        # keep trying (the LLM might find a different approach eventually).
        permanently_failed = {
            ln for ln, cnt in revert_count.items()
            if cnt >= _MAX_REVERTS_PER_LINE
        }
        # Don't permanently ban if ALL errors would be banned
        if permanently_failed and permanently_failed >= {ln for ln, _ in new_errors}:
            permanently_failed = set()  # unban — they're the only ones left

        actionable = [
            (ln, msg) for ln, msg in new_errors
            if ln not in failed_error_lines and ln not in permanently_failed
        ]
        if not actionable:
            still_possible = [
                (ln, msg) for ln, msg in new_errors
                if ln not in permanently_failed
            ]
            if not still_possible:
                log.info("  Phase %s batch %d: %d errors remain but all "
                         "permanently failed (reverted %d+ times each) "
                         "— stopping",
                         phase, batch, n_errors, _MAX_REVERTS_PER_LINE)
                return new_resolutions

            # End of a round — check if this round made progress
            if n_errors < best_error_count:
                best_error_count = n_errors
                rounds_without_progress = 0
            else:
                rounds_without_progress += 1

            # Dynamic stall limit: minimum 50 rounds, more near 0
            # 1 error → 100 rounds, 2 → 50, 10 → 50, 100 → 50
            stall_limit = max(50, 100 // max(n_errors, 1))

            if rounds_without_progress >= stall_limit:
                log.info("  Phase %s batch %d: stalled at %d errors "
                         "(%d full rounds with no progress) — stopping",
                         phase, batch, n_errors, stall_limit)
                return new_resolutions

            log.info("  Phase %s batch %d: all %d errors attempted — "
                     "resetting for fresh round (%d/%d stall rounds)",
                     phase, batch, n_errors,
                     rounds_without_progress, stall_limit)
            failed_error_lines.clear()
            actionable = still_possible

        log.info("  Phase %s batch %d attempt %d: %d errors (%d actionable)",
                 phase, batch, attempt, n_errors, len(actionable))

        if not llm_provider:
            for ln, msg in actionable[:5]:
                log.info("    Line %d: %s", ln, msg)
            return new_resolutions

        src_lines = source_path.read_text(errors="replace").splitlines(keepends=True)
        total_lines = len(src_lines)

        # ----- Decide: batch mode or single-error mode -----
        error_groups = _group_errors_by_type(actionable)
        largest_group_type = max(error_groups, key=lambda k: len(error_groups[k]))
        largest_group = error_groups[largest_group_type]
        # Use batch only if 5+ same-type errors AND batch hasn't failed yet
        batch_already_failed = any(
            "batch" in fs.lower() or len(fs) > 100
            for _, fe, fs, _ in failed_attempts
            if largest_group_type[:20] in fe
        )
        use_batch_mode = len(largest_group) >= 5 and not batch_already_failed

        # Build resolution + failure memory text (shared by both modes)
        current_error_types = {msg.split(",")[0].strip() for _, msg in actionable[:15]}
        relevant_res = [r for r in resolutions + new_resolutions
                        if r.verified and any(et in r.error for et in current_error_types)]
        recent_res = (resolutions + new_resolutions)[-10:]
        seen_keys: set[str] = set()
        res_summaries: list[str] = []
        for r in relevant_res + recent_res:
            key = f"{r.error}:{r.fix}"
            if key not in seen_keys:
                seen_keys.add(key)
                res_summaries.append(r.summary())
            if len(res_summaries) >= 20:
                break

        history_text = ""
        if res_summaries or successful_fixes:
            all_success = [f"- {s}" for s in res_summaries] + [f"- {s}" for s in successful_fixes[-5:]]
            history_text += "WHAT WORKED (apply these patterns):\n" + "\n".join(all_success[:20]) + "\n\n"

        had_comment_rejections = False
        if failed_attempts:
            recent_failed = failed_attempts[-10:]
            failed_lines = []
            for fl, fe, fs, fr in recent_failed:
                failed_lines.append(f"  - Line {fl}: {fe[:60]} | Tried: {fs[:80]} | Result: {fr}")
                if "commenting out" in fr.lower() or "commented out" in fs.lower():
                    had_comment_rejections = True
            history_text += (
                "WHAT FAILED (do NOT repeat — try a different approach):\n"
                + "\n".join(failed_lines) + "\n\n"
            )
        if had_comment_rejections:
            history_text += (
                "⚠️ HARD CONSTRAINT: Do NOT comment out lines (no * in column 7). "
                "Previous attempts to comment out code were REJECTED. You MUST either:\n"
                "  1. Add a stub variable definition (e.g., 01 X PIC X(256).)\n"
                "  2. Modify the existing line to fix the syntax\n"
                "  3. Add a missing period or keyword\n"
                "Commenting out is NEVER acceptable.\n\n"
            )

        if use_batch_mode:
            # ===== BATCH MODE: Fix all similar errors at once =====
            batch_errors = largest_group[:30]  # Cap at 30 to fit context
            error_list = "\n".join(f"  - Line {ln}: {msg}" for ln, msg in batch_errors)

            log.info("  [%d/%d] BATCH: fixing %d '%s' errors at once",
                     attempt + 1, max_fix_attempts, len(batch_errors), largest_group_type[:40])

            # Build context: error area + optionally WORKING-STORAGE
            # For "not defined" errors, show WS so LLM knows where to add stubs
            context_chunks = []

            # Primary chunk: around the error lines
            err_lines_sorted = sorted(ln for ln, _ in batch_errors)
            first_err = err_lines_sorted[0]
            last_err = err_lines_sorted[-1]
            ctx_start = max(0, first_err - 20)
            ctx_end = min(total_lines, last_err + 20)
            if ctx_end - ctx_start > _MAX_CONTEXT_LINES:
                ctx_end = ctx_start + _MAX_CONTEXT_LINES

            numbered = "\n".join(
                f"{ctx_start + i + 1:5d}: {line.rstrip()}"
                for i, line in enumerate(src_lines[ctx_start:ctx_end])
            )
            context_chunks.append(
                f"Error area (lines {ctx_start+1}-{ctx_end}):\n```cobol\n{numbered}\n```"
            )

            # Secondary chunk: WORKING-STORAGE (for "not defined" errors)
            if "not defined" in largest_group_type:
                ws_range = _find_working_storage_range(src_lines)
                if ws_range:
                    ws_start, ws_end = ws_range
                    # Show last 200 lines of WS (where stubs should be added)
                    ws_show_start = max(ws_start, ws_end - 200)
                    ws_numbered = "\n".join(
                        f"{ws_show_start + i + 1:5d}: {line.rstrip()}"
                        for i, line in enumerate(src_lines[ws_show_start:ws_end])
                    )
                    context_chunks.append(
                        f"\nWORKING-STORAGE tail (lines {ws_show_start+1}-{ws_end}, "
                        f"add new definitions BEFORE the last line shown here):\n"
                        f"```cobol\n{ws_numbered}\n```"
                    )

            # Secondary chunk: FILE-CONTROL + FILE SECTION (for file errors)
            if "not a file name" in largest_group_type:
                fc_end = _find_file_control_end(src_lines)
                if fc_end is not None:
                    fc_show_start = max(0, fc_end - 30)
                    fc_numbered = "\n".join(
                        f"{fc_show_start + i + 1:5d}: {line.rstrip()}"
                        for i, line in enumerate(src_lines[fc_show_start:fc_end + 5])
                    )
                    context_chunks.append(
                        f"\nFILE-CONTROL (lines {fc_show_start+1}-{fc_end+5}, "
                        f"add new SELECT clauses here):\n"
                        f"```cobol\n{fc_numbered}\n```"
                    )
                fs_end = _find_file_section_end(src_lines)
                if fs_end is not None:
                    fs_show_start = max(0, fs_end - 30)
                    fs_numbered = "\n".join(
                        f"{fs_show_start + i + 1:5d}: {line.rstrip()}"
                        for i, line in enumerate(src_lines[fs_show_start:fs_end + 5])
                    )
                    context_chunks.append(
                        f"\nFILE SECTION end (lines {fs_show_start+1}-{fs_end+5}, "
                        f"add new FD entries before WORKING-STORAGE):\n"
                        f"```cobol\n{fs_numbered}\n```"
                    )

            all_context = "\n\n".join(context_chunks)

            fix_prompt = (
                f"Fix ALL of these GnuCOBOL compilation errors at once in {source_name} "
                f"({total_lines} lines, phase: {phase}).\n\n"
                f"{history_text}"
                f"Errors to fix ({len(batch_errors)} errors, type: {largest_group_type}):\n"
                f"{error_list}\n\n"
                f"{all_context}\n\n"
                f"IMPORTANT: Fix ALL {len(batch_errors)} errors in a single response.\n\n"
                f"{_COBOL_FIX_KNOWLEDGE}\n"
                f"Return ALL fixed/added lines as flat JSON: "
                f"{{\"<line_number>\": \"<content>\"}}\n"
                f"Do NOT wrap in outer keys. Include ALL lines that need changing."
            )

            targeted_lines = set(err_lines_sorted)

        else:
            # ===== SINGLE ERROR MODE: Choose + fix one error =====
            top_errors = actionable[:15]
            error_list = "\n".join(f"  {i+1}. Line {ln}: {msg}" for i, (ln, msg) in enumerate(top_errors))

            choose_prompt = (
                f"You are fixing GnuCOBOL compilation errors in {source_name} "
                f"({total_lines} lines, phase: {phase}).\n\n"
                f"{history_text}"
                f"Current compilation errors ({n_errors} total, showing top 15):\n"
                f"{error_list}\n\n"
                f"Choose ONE error to fix. Respond with JSON:\n"
                f'{{"choose_error": {{"line": <line_number>, "context_start": <start>, "context_end": <end>}}}}\n\n'
                f"Where context_start/context_end define the code range you need to see "
                f"(max {_MAX_CONTEXT_LINES} lines). If many errors cluster, the ROOT CAUSE "
                f"is likely BEFORE the cluster — request context starting well before."
            )

            try:
                response, _ = _query_llm_sync(llm_provider, choose_prompt, llm_model)
            except Exception as exc:
                log.warning("  LLM choose query failed: %s", exc)
                return new_resolutions

            # Parse LLM's choice
            chosen_line = None
            ctx_start = None
            ctx_end = None
            try:
                cleaned = re.sub(r"```\w*\n?", "", response).strip()
                parsed = json.loads(cleaned)
                if "choose_error" in parsed:
                    choice = parsed["choose_error"]
                    chosen_line = int(choice.get("line", 0))
                    ctx_start = max(0, int(choice.get("context_start", chosen_line - 50)) - 1)
                    ctx_end = min(total_lines, int(choice.get("context_end", chosen_line + 50)))
            except (json.JSONDecodeError, TypeError, ValueError, KeyError):
                pass

            if not chosen_line:
                chosen_line = actionable[0][0]
                ctx_start = max(0, chosen_line - 100)
                ctx_end = min(total_lines, chosen_line + 20)

            if ctx_end - ctx_start > _MAX_CONTEXT_LINES:
                ctx_end = ctx_start + _MAX_CONTEXT_LINES

            chosen_msg = next((msg for ln, msg in actionable if ln == chosen_line), "unknown")
            log.info("  [%d/%d] Fixing line %d: %s (context: %d-%d)",
                     attempt + 1, max_fix_attempts, chosen_line, chosen_msg[:60],
                     ctx_start + 1, ctx_end)

            numbered_context = "\n".join(
                f"{ctx_start + i + 1:5d}: {line.rstrip()}"
                for i, line in enumerate(src_lines[ctx_start:ctx_end])
            )

            # Include nearby failed attempts
            nearby_failed = [
                (fl, fe, fs, fr) for fl, fe, fs, fr in failed_attempts
                if abs(fl - chosen_line) < 50
            ]
            nearby_text = ""
            if nearby_failed:
                nf_lines = [f"  - Line {fl}: tried {fs[:100]} → {fr}"
                            for fl, fe, fs, fr in nearby_failed[-5:]]
                nearby_text = (
                    "\nPrevious failed fixes near this area (DO NOT repeat):\n"
                    + "\n".join(nf_lines) + "\n"
                    "Consider: the root cause may be EARLIER in the file.\n\n"
                )

            fix_prompt = (
                f"Fix this GnuCOBOL compilation error:\n"
                f"  Line {chosen_line}: {chosen_msg}\n\n"
                f"{history_text}"
                f"{nearby_text}"
                f"Source context (lines {ctx_start+1}-{ctx_end}):\n"
                f"```cobol\n{numbered_context}\n```\n\n"
                f"{_COBOL_FIX_KNOWLEDGE}\n"
                f"Return ONLY fixed lines as flat JSON: "
                f"{{\"<line_number>\": \"<fixed_content>\"}}\n"
                f"Do NOT wrap in outer keys. Only include lines that changed."
            )

            targeted_lines = {chosen_line}

        # ===== Send fix prompt (shared by both modes) =====
        try:
            response2, _ = _query_llm_sync(llm_provider, fix_prompt, llm_model)
        except Exception as exc:
            log.warning("  LLM fix query failed: %s", exc)
            for tl in targeted_lines:
                failed_error_lines.add(tl)
            continue

        # Parse response — allow broader line range for batch mode (stubs
        # may be added in WORKING-STORAGE, far from the error)
        parse_min = 0 if use_batch_mode else (ctx_start if not use_batch_mode else 0)
        parse_max = total_lines + 100  # Allow appending lines
        fixes = _parse_llm_fix_response(response2, parse_min, parse_max)

        if not fixes:
            snippet = response2[:200].replace("\n", "\\n") if response2 else "(empty)"
            log.info("  LLM response not parsed: %s", snippet)
            fix_desc = "batch" if use_batch_mode else f"line {next(iter(targeted_lines))}"
            failed_attempts.append((
                next(iter(targeted_lines)),
                largest_group_type if use_batch_mode else chosen_msg,
                "unparseable response",
                "response not parsed as JSON",
            ))
            for tl in targeted_lines:
                failed_error_lines.add(tl)
            continue

        # Build a meaningful summary of what the fix actually does
        fix_details = []
        for ln in sorted(fixes.keys())[:5]:
            content = fixes[ln].strip()[:60]
            fix_details.append(f"L{ln}: {content}")
        fix_summary = "; ".join(fix_details)
        if len(fixes) > 5:
            fix_summary += f" (+{len(fixes)-5} more)"

        # ===== Duplicate detection: reject if we've tried this exact fix =====
        fix_fingerprint = "|".join(
            f"{ln}:{fixes[ln].strip()}" for ln in sorted(fixes.keys())
        )
        if fix_fingerprint in tried_fix_fingerprints:
            log.info("  [%d/%d] ✗ Skipped: duplicate fix (already tried this exact change)",
                     attempt, max_fix_attempts)
            failed_attempts.append((
                next(iter(targeted_lines)),
                largest_group_type if use_batch_mode else chosen_msg,
                fix_summary,
                "SKIPPED — exact same fix already tried and failed. "
                "You MUST try something fundamentally different",
            ))
            for tl in targeted_lines:
                failed_error_lines.add(tl)
            continue
        tried_fix_fingerprints.add(fix_fingerprint)

        # ===== Quality gate: reject fixes that are mostly commenting out =====
        n_commented = 0
        n_added_stub = 0
        n_other = 0
        for fix_ln, fix_content in fixes.items():
            content_stripped = fix_content.strip()
            idx = fix_ln - 1
            was_comment = (0 <= idx < len(src_lines)
                           and len(src_lines[idx]) > 6
                           and src_lines[idx][6:7] == "*")
            is_comment = len(content_stripped) > 0 and content_stripped[0] == "*"
            if is_comment and not was_comment:
                n_commented += 1
            elif (0 <= idx < len(src_lines)
                  and src_lines[idx].strip() != content_stripped):
                # Actual content change (not a no-op)
                if any(kw in content_stripped.upper()
                       for kw in ("PIC ", "PIC(", "VALUE ", "FILLER")):
                    n_added_stub += 1
                else:
                    n_other += 1

        total_changes = n_commented + n_added_stub + n_other
        if total_changes > 0 and n_commented > 0:
            comment_pct = n_commented / total_changes
            if comment_pct > 0.5 and n_added_stub == 0:
                # More than half the fix is commenting out code with no stubs
                log.warning("  [%d/%d] ✗ Rejected: fix comments out %d/%d lines "
                            "(no stubs added) — likely destructive",
                            attempt + 1, max_fix_attempts, n_commented, total_changes)
                failed_attempts.append((
                    next(iter(targeted_lines)),
                    largest_group_type if use_batch_mode else chosen_msg,
                    f"commented out {n_commented}/{total_changes} lines",
                    "REJECTED — commenting out code is NOT allowed. "
                    "You MUST add a stub definition (01 X PIC ...) or "
                    "modify the line, NOT comment it out with * in col 7",
                ))
                for tl in targeted_lines:
                    failed_error_lines.add(tl)
                continue

        # ===== Apply, recompile, verify =====
        snapshot = list(src_lines)

        for fix_ln, fix_content in fixes.items():
            idx = fix_ln - 1
            if 0 <= idx < len(src_lines):
                src_lines[idx] = fix_content
            elif fix_ln == len(src_lines) + 1:
                # Appending a new line (e.g., adding stub at end of section)
                src_lines.append(fix_content)

        source_path.write_text("".join(src_lines))

        rc2, stderr2 = _cobc_syntax_check(source_path, copybook_dirs)
        new_error_list = _parse_errors(stderr2, source_name) if rc2 != 0 else []
        new_error_lines_set = {ln for ln, _ in new_error_list}
        new_error_count = len(new_error_list)

        if rc2 == 0:
            fix_lines_dict = {str(k): v for k, v in fixes.items()}
            desc = f"batch {len(targeted_lines)} errors" if use_batch_mode else f"line {next(iter(targeted_lines))}"
            new_resolutions.append(Resolution(
                phase=phase, batch=batch,
                transformation=f"Fix {desc} in phase {phase}",
                error=largest_group_type if use_batch_mode else chosen_msg,
                fix=f"LLM fix ({len(fixes)} lines) — all errors resolved",
                fix_lines=fix_lines_dict,
                verified=True,
                timestamp=datetime.now(timezone.utc).isoformat(),
            ))
            successful_fixes.append(f"Fixed {desc}: {len(fixes)} lines changed → 0 errors")
            if audit_path:
                _audit_fix(audit_path, phase, batch, attempt + 1, fixes, snapshot,
                           largest_group_type if use_batch_mode else chosen_msg,
                           f"ACCEPTED — all errors resolved ({n_errors}→0)")
            log.info("  [%d/%d] ✓ All errors fixed!", attempt + 1, max_fix_attempts)
            _save_progress()
            return new_resolutions

        # Relaxed verification: accept if error count DECREASED, even if
        # the specific targeted line still has an error (line numbers shift
        # when stubs are added)
        if new_error_count < n_errors:
            fix_lines_dict = {str(k): v for k, v in fixes.items()}
            reduced = n_errors - new_error_count
            desc = f"batch {len(targeted_lines)} errors" if use_batch_mode else f"line {next(iter(targeted_lines))}"
            new_resolutions.append(Resolution(
                phase=phase, batch=batch,
                transformation=f"Fix {desc} in phase {phase}",
                error=largest_group_type if use_batch_mode else chosen_msg,
                fix=f"LLM fix ({len(fixes)} lines) — reduced by {reduced} ({new_error_count} remaining)",
                fix_lines=fix_lines_dict,
                verified=True,
                timestamp=datetime.now(timezone.utc).isoformat(),
            ))
            successful_fixes.append(f"Fixed {desc}: {n_errors}→{new_error_count} errors (-{reduced})")
            if audit_path:
                _audit_fix(audit_path, phase, batch, attempt + 1, fixes, snapshot,
                           largest_group_type if use_batch_mode else chosen_msg,
                           f"ACCEPTED — errors reduced ({n_errors}→{new_error_count}, -{reduced})")
            log.info("  [%d/%d] ✓ Progress: %d → %d errors (-%d)",
                     attempt + 1, max_fix_attempts, n_errors, new_error_count, reduced)
            _save_progress()

            # After a big drop, re-run pre-fix stubs — new "not defined"
            # errors may have appeared that weren't visible before
            if reduced >= 10:
                rc_re, stderr_re = _cobc_syntax_check(source_path, copybook_dirs)
                if rc_re != 0:
                    re_errors = _parse_errors(stderr_re, source_name)
                    re_nd = [(ln, msg) for ln, msg in re_errors
                             if "is not defined" in msg]
                    if re_nd:
                        re_src = source_path.read_text(errors="replace").splitlines(keepends=True)
                        re_stubs = _generate_record_stubs(re_nd, re_src)
                        if re_stubs:
                            ws_r = _find_working_storage_range(re_src)
                            if ws_r:
                                ins = ws_r[1]
                                for si, sl in enumerate(re_stubs):
                                    re_src.insert(ins + si, sl)
                                source_path.write_text("".join(re_src))
                                rc_v, stderr_v = _cobc_syntax_check(
                                    source_path, copybook_dirs)
                                v_errs = _parse_errors(stderr_v, source_name) if rc_v != 0 else []
                                v_nd = sum(1 for _, m in v_errs if "is not defined" in m)
                                if v_nd < len(re_nd):
                                    log.info("  Re-stubs after drop: 'not defined' "
                                             "%d → %d", len(re_nd), v_nd)
                                else:
                                    # Revert
                                    re_src = re_src[:ins] + re_src[ins + len(re_stubs):]
                                    source_path.write_text("".join(re_src))

            # Don't return — keep going to fix remaining errors
            continue

        # Error count same or worse — revert
        source_path.write_text("".join(snapshot))
        src_lines = snapshot  # Reset for next iteration

        revert_reason = f"no improvement ({n_errors}→{new_error_count})"
        failed_attempts.append((
            next(iter(targeted_lines)),
            largest_group_type if use_batch_mode else chosen_msg,
            fix_summary,
            revert_reason,
        ))

        # Track revert count per line — permanent across resets
        for tl in targeted_lines:
            revert_count[tl] = revert_count.get(tl, 0) + 1

        # Mark error cluster as failed
        if use_batch_mode:
            for ln, _ in batch_errors:
                failed_error_lines.add(ln)
            log.info("  [%d/%d] ✗ Reverted batch (%d → %d errors)",
                     attempt, max_fix_attempts, n_errors, new_error_count)
        else:
            clusters = _cluster_errors(actionable)
            for cluster in clusters:
                cluster_lines = {ln for ln, _ in cluster}
                if next(iter(targeted_lines)) in cluster_lines:
                    failed_error_lines.update(cluster_lines)
                    break
            else:
                failed_error_lines.update(targeted_lines)
            log.info("  [%d/%d] ✗ Reverted (%d → %d errors)",
                     attempt, max_fix_attempts, n_errors, new_error_count)

    return new_resolutions


# ---------------------------------------------------------------------------
# Phase implementations
# ---------------------------------------------------------------------------

def _phase_copy_resolution(
    lines: list[str],
    copybook_dirs: list[Path],
) -> tuple[list[str], str]:
    """Phase 1: Resolve COPY statements."""
    from .cobol_mock import _resolve_copies
    new_lines, resolved, stubbed, warnings = _resolve_copies(lines, copybook_dirs)
    desc = f"Resolved {resolved} COPY statements ({stubbed} stubbed)"
    if warnings:
        for w in warnings[:5]:
            log.debug("  COPY warning: %s", w)
    return new_lines, desc


def _phase_mock_infrastructure(
    lines: list[str],
    config,
) -> tuple[list[str], str]:
    """Phase 2: Add division identification + mock infrastructure."""
    from .cobol_mock import (
        _find_divisions,
        _add_mock_infrastructure,
        _disable_original_selects,
    )
    divisions = _find_divisions(lines)
    lines = _add_mock_infrastructure(lines, divisions, config)
    lines = _disable_original_selects(lines, config)
    desc = "Added mock infrastructure (FILE-CONTROL, FD, WS entries)"
    return lines, desc




def _phase_paragraph_tracing(
    lines: list[str],
) -> tuple[list[str], str, int]:
    """Phase 6: Add SPECTER-TRACE and SPECTER-CALL probes."""
    from .cobol_mock import _add_paragraph_tracing
    new_lines, count = _add_paragraph_tracing(lines)
    return new_lines, f"Added {count} paragraph trace probes", count


def _phase_normalization(
    lines: list[str],
    config,
) -> tuple[list[str], str]:
    """Phase 7: Apply safe normalizations for GnuCOBOL compatibility."""
    from .cobol_mock import (
        _convert_linkage,
        _normalize_redefines_targets,
        _fix_procedure_division,
        _add_mock_file_handling,
        _strip_skip_directives,
        _add_common_stubs,
        _normalize_paragraph_ellipsis,
        _sanitize_source_ascii,
        _fix_occurs_depending_on,
        _ensure_sentence_break_before_paragraphs,
    )
    lines = _convert_linkage(lines)
    lines = _normalize_redefines_targets(lines)
    lines = _fix_procedure_division(lines)
    lines = _add_mock_file_handling(lines, config)
    lines = _strip_skip_directives(lines)
    lines = _add_common_stubs(lines, config)
    lines = _normalize_paragraph_ellipsis(lines)
    lines = _sanitize_source_ascii(lines)
    lines = _fix_occurs_depending_on(lines)
    lines = _ensure_sentence_break_before_paragraphs(lines)
    return lines, "Applied normalization transforms"


def _phase_auto_stub(
    lines: list[str],
    allow_hardening_fallback: bool = True,
) -> tuple[list[str], str]:
    """Phase 8: Auto-stub undefined symbols via cobc diagnostics."""
    from .cobol_mock import _auto_stub_undefined_with_cobc
    new_lines = _auto_stub_undefined_with_cobc(
        lines,
        allow_hardening_fallback=allow_hardening_fallback,
    )
    return new_lines, "Auto-stubbed undefined symbols"


def _phase_restore_tracing(
    lines: list[str],
) -> tuple[list[str], str]:
    """Phase 8b: Restore paragraph tracing probes destroyed by auto-stub."""
    from .cobol_mock import _restore_paragraph_tracing
    new_lines = _restore_paragraph_tracing(lines)
    count = sum(
        1 for l in new_lines
        if "SPECTER-TRACE:" in l and not l.strip().startswith("*")
    )
    return new_lines, f"Restored paragraph tracing ({count} probes)"


def _phase_branch_probes(
    source_path: Path,
    llm_provider,
    llm_model: str | None,
    copybook_dirs: list[Path] | None = None,
) -> tuple[dict, int, str]:
    """Phase 9: Insert branch probes one paragraph at a time.

    Returns (branch_meta, total_probes, description).
    """
    if not llm_provider:
        return {}, 0, "Branch probes skipped (no LLM provider)"

    try:
        from .branch_instrumenter import instrument_branches
        probes, paras_done, branch_meta = instrument_branches(
            source_path, llm_provider, llm_model,
        )
        if probes > 0:
            return branch_meta, probes, (
                f"Inserted {probes} branch probes in {paras_done} paragraphs"
            )
        return {}, 0, "No branch probes inserted"
    except Exception as exc:
        log.warning("Branch instrumentation failed: %s", exc)
        return {}, 0, f"Branch probes failed: {exc}"


# ---------------------------------------------------------------------------
# GnuCOBOL source fixups (imported from cobol_executor)
# ---------------------------------------------------------------------------

def _apply_gnucobol_fixups(source_text: str) -> str:
    """Apply IBM-to-GnuCOBOL fixups on the full instrumented source.

    Delegates to the cobol_executor implementation.
    """
    from .cobol_executor import _gnucobol_source_fixups
    return _gnucobol_source_fixups(source_text)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def incremental_instrument(
    source_path: Path,
    copybook_dirs: list[Path],
    output_dir: Path,
    llm_provider=None,
    llm_model: str | None = None,
    batch_size: int = 5,
    resolution_log_path: Path | None = None,
    coverage_mode: bool = False,
    allow_hardening_fallback: bool = True,
    initial_values: dict[str, str] | None = None,
    stop_on_exec_return: bool = True,
    stop_on_exec_xctl: bool = True,
    eib_calen: int = 0,
    eib_aid: str = "SPACES",
) -> tuple[Path, dict, int]:
    """Incrementally instrument COBOL with compile-after-each-step.

    Applies transformations in phases, compiling and fixing errors after
    each phase.  A resolution log accumulates knowledge so later phases
    (and future re-runs) benefit from earlier fixes.

    Args:
        source_path: Path to the COBOL source file.
        copybook_dirs: Directories containing copybooks.
        output_dir: Directory for build artifacts.
        llm_provider: LLM provider instance for error fixing.
        llm_model: Optional model override for the LLM provider.
        batch_size: Number of transformations per batch (for future use).
        resolution_log_path: Path to the resolution log JSON. Defaults to
            ``{output_dir}/resolution_log.json``.
        coverage_mode: If True, configure for deep coverage exploration.
        allow_hardening_fallback: Allow hardening fallback in auto-stub.
        initial_values: Variable name -> value pairs for INIT record injection.
        stop_on_exec_return: If True, EXEC CICS RETURN terminates the program.
        stop_on_exec_xctl: If True, EXEC CICS XCTL terminates the program.
        eib_calen: Initial EIBCALEN value.
        eib_aid: Initial EIBAID value.

    Returns:
        (mock_cbl_path, branch_meta, total_branches) where:
        - mock_cbl_path: Path to the instrumented .mock.cbl file
        - branch_meta: dict mapping branch_id -> {paragraph, type}
        - total_branches: total number of branch probes inserted
    """
    source_path = Path(source_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if resolution_log_path is None:
        resolution_log_path = output_dir / "resolution_log.json"

    # Fix audit log — records every accepted LLM fix with before/after diffs
    audit_path = output_dir / "fix_audit.log"

    # Build MockConfig for phase functions that need it
    from .cobol_mock import MockConfig
    config = MockConfig(
        copybook_dirs=list(copybook_dirs),
        trace_paragraphs=True,
        initial_values=initial_values or {},
        stop_on_exec_return=stop_on_exec_return,
        stop_on_exec_xctl=stop_on_exec_xctl,
        eib_calen=eib_calen,
        eib_aid=eib_aid,
    )

    # Load prior resolutions and checkpoint for resume
    resolutions = _load_resolutions(resolution_log_path)
    phase_results: list[PhaseResult] = []
    checkpoint = _load_checkpoint(output_dir)
    start_phase = checkpoint.get("last_completed_phase_number", -1) + 1

    # Working copy of the source — only copy if starting fresh
    mock_path = output_dir / (source_path.stem + ".mock.cbl")
    if start_phase <= 0:
        shutil.copy2(source_path, mock_path)
    elif not mock_path.exists():
        log.warning("Checkpoint exists but mock.cbl missing — starting fresh")
        start_phase = 0
        shutil.copy2(source_path, mock_path)

    total_paragraphs = 0
    branch_meta: dict = {}
    total_branches = 0

    # Track the most recent sub-checkpoint so we can re-save on Ctrl-C.
    # Updated by each phase before calling compile_and_fix.
    baseline_errors: set[str] = set()
    if start_phase <= 0:
        log.info("Phase 0: Baseline compilation check")
        rc, stderr = _cobc_syntax_check(mock_path, copybook_dirs)
        if rc != 0:
            errors = _parse_errors(stderr, mock_path.name)
            baseline_errors = {msg for _, msg in errors}
            log.info("  Baseline: %d pre-existing errors", len(errors))
        else:
            log.info("  Baseline: compiles clean")
        phase_results.append(PhaseResult(
            phase="baseline", errors_before=len(baseline_errors),
            errors_after=len(baseline_errors),
        ))
        _save_checkpoint(output_dir, "baseline", 0, mock_path)
    else:
        log.info("Phase 0: Baseline (skipped — resuming)")

    # -----------------------------------------------------------------------
    # Phase 1: COPY resolution
    # -----------------------------------------------------------------------
    cp_name = checkpoint.get("last_completed_phase", "")
    if start_phase <= 1:
        # Only re-run the transform if not already done on a prior run
        if cp_name != "copy_resolution_transformed":
            log.info("Phase 1: COPY resolution")
            lines = mock_path.read_text(errors="replace").splitlines(keepends=True)
            lines, desc = _phase_copy_resolution(lines, copybook_dirs)
            mock_path.write_text("".join(lines))
            log.info("  %s", desc)
            # Sub-checkpoint: transform done, compile-and-fix not yet
            _save_checkpoint(output_dir, "copy_resolution_transformed", 0, mock_path)
        else:
            log.info("Phase 1: COPY resolution (transform done, resuming fixes)")

        new_res = _compile_and_fix(
            mock_path, "copy_resolution", 0, resolutions,
            copybook_dirs=copybook_dirs,
            llm_provider=llm_provider, llm_model=llm_model,
            baseline_errors=baseline_errors,
            audit_path=audit_path,
            checkpoint_dir=output_dir,
            checkpoint_name="copy_resolution_transformed",
            checkpoint_number=0,
        )
        resolutions.extend(new_res)
        _save_resolutions(resolutions, resolution_log_path)

        _assert_clean(mock_path, "Phase 1 (COPY resolution)",
                      copybook_dirs, resolutions, resolution_log_path,
                      output_dir, "copy_resolution_transformed", 0)
        _save_checkpoint(output_dir, "copy_resolution", 1, mock_path)
    else:
        log.info("Phase 1: COPY resolution (skipped — resuming)")

    # -----------------------------------------------------------------------
    # Phase 2: Mock infrastructure
    # -----------------------------------------------------------------------
    cp_name = _load_checkpoint(output_dir).get("last_completed_phase", "")
    if start_phase <= 2:
        if cp_name != "mock_infra_transformed":
            log.info("Phase 2: Mock infrastructure")
            lines = mock_path.read_text(errors="replace").splitlines(keepends=True)
            lines, desc = _phase_mock_infrastructure(lines, config)
            mock_path.write_text("".join(lines))
            log.info("  %s", desc)
            _save_checkpoint(output_dir, "mock_infra_transformed", 1, mock_path)
        else:
            log.info("Phase 2: Mock infrastructure (transform done, resuming fixes)")

        new_res = _compile_and_fix(
            mock_path, "mock_infrastructure", 0, resolutions,
            copybook_dirs=copybook_dirs,
            llm_provider=llm_provider, llm_model=llm_model,
            baseline_errors=baseline_errors,
            audit_path=audit_path,
            checkpoint_dir=output_dir,
            checkpoint_name="mock_infra_transformed",
            checkpoint_number=1,
        )
        resolutions.extend(new_res)
        _save_resolutions(resolutions, resolution_log_path)

        _assert_clean(mock_path, "Phase 2 (mock infrastructure)",
                      copybook_dirs, resolutions, resolution_log_path,
                      output_dir, "mock_infra_transformed", 1)
        _save_checkpoint(output_dir, "mock_infrastructure", 2, mock_path)
    else:
        log.info("Phase 2: Mock infrastructure (skipped — resuming)")

    # -----------------------------------------------------------------------
    # Phase 3: EXEC replacement (incremental, batch_size blocks at a time)
    # -----------------------------------------------------------------------
    if start_phase <= 3:
        log.info("Phase 3: EXEC replacement (incremental, batch_size=%d)", batch_size)
        from .cobol_mock import _replace_exec_blocks
        batch_num = 0
        while True:
            lines = mock_path.read_text(errors="replace").splitlines(keepends=True)
            new_lines, replaced = _replace_exec_blocks(lines, config, max_count=batch_size)
            if replaced == 0:
                break
            batch_num += 1
            log.info("  Batch %d: replaced %d EXEC blocks", batch_num, replaced)
            snapshot = "".join(lines)  # pre-batch state for revert
            mock_path.write_text("".join(new_lines))

            new_res = _compile_and_fix(
                mock_path, "exec_replacement", batch_num, resolutions,
                copybook_dirs=copybook_dirs,
                llm_provider=llm_provider, llm_model=llm_model,
                baseline_errors=baseline_errors,
            )
            resolutions.extend(new_res)
            _save_resolutions(resolutions, resolution_log_path)

            # Check if batch made things unfixable — revert and retry one-by-one
            rc, stderr = _cobc_syntax_check(mock_path, copybook_dirs)
            if rc != 0:
                errs = _parse_errors(stderr, mock_path.name)
                if len(errs) > 10:
                    log.warning("  Batch %d: %d errors remain, reverting to one-by-one",
                                batch_num, len(errs))
                    mock_path.write_text(snapshot)
                    for _ in range(batch_size):
                        lines = mock_path.read_text(errors="replace").splitlines(keepends=True)
                        one_lines, one_replaced = _replace_exec_blocks(lines, config, max_count=1)
                        if one_replaced == 0:
                            break
                        mock_path.write_text("".join(one_lines))
                        one_res = _compile_and_fix(
                            mock_path, "exec_replacement", batch_num, resolutions,
                            copybook_dirs=copybook_dirs,
                            llm_provider=llm_provider, llm_model=llm_model,
                            baseline_errors=baseline_errors,
                        )
                        resolutions.extend(one_res)
                        _save_resolutions(resolutions, resolution_log_path)

        log.info("  Phase 3 complete (%d batches)", batch_num)
        _assert_clean(mock_path, "Phase 3 (EXEC replacement)",
                      copybook_dirs, resolutions, resolution_log_path,
                      output_dir, "exec_replacement", 2)
        _save_checkpoint(output_dir, "exec_replacement", 3, mock_path)
    else:
        log.info("Phase 3: EXEC replacement (skipped — resuming)")

    # -----------------------------------------------------------------------
    # Phase 4: I/O replacement (incremental, batch_size blocks at a time)
    # -----------------------------------------------------------------------
    if start_phase <= 4:
        log.info("Phase 4: I/O replacement (incremental, batch_size=%d)", batch_size)
        from .cobol_mock import _replace_io_verbs
        batch_num = 0
        while True:
            lines = mock_path.read_text(errors="replace").splitlines(keepends=True)
            new_lines, replaced = _replace_io_verbs(lines, max_count=batch_size)
            if replaced == 0:
                break
            batch_num += 1
            log.info("  Batch %d: replaced %d I/O verbs", batch_num, replaced)
            snapshot = "".join(lines)
            mock_path.write_text("".join(new_lines))

            new_res = _compile_and_fix(
                mock_path, "io_replacement", batch_num, resolutions,
                copybook_dirs=copybook_dirs,
                llm_provider=llm_provider, llm_model=llm_model,
                baseline_errors=baseline_errors,
            )
            resolutions.extend(new_res)
            _save_resolutions(resolutions, resolution_log_path)

            # Revert + one-by-one if batch causes too many errors
            rc, stderr = _cobc_syntax_check(mock_path, copybook_dirs)
            if rc != 0:
                errs = _parse_errors(stderr, mock_path.name)
                if len(errs) > 10:
                    log.warning("  Batch %d: %d errors remain, reverting to one-by-one",
                                batch_num, len(errs))
                    mock_path.write_text(snapshot)
                    for _ in range(batch_size):
                        lines = mock_path.read_text(errors="replace").splitlines(keepends=True)
                        one_lines, one_replaced = _replace_io_verbs(lines, max_count=1)
                        if one_replaced == 0:
                            break
                        mock_path.write_text("".join(one_lines))
                        one_res = _compile_and_fix(
                            mock_path, "io_replacement", batch_num, resolutions,
                            copybook_dirs=copybook_dirs,
                            llm_provider=llm_provider, llm_model=llm_model,
                            baseline_errors=baseline_errors,
                        )
                        resolutions.extend(one_res)
                        _save_resolutions(resolutions, resolution_log_path)

        log.info("  Phase 4 complete (%d batches)", batch_num)
        _assert_clean(mock_path, "Phase 4 (I/O replacement)",
                      copybook_dirs, resolutions, resolution_log_path,
                      output_dir, "io_replacement", 3)
        _save_checkpoint(output_dir, "io_replacement", 4, mock_path)
    else:
        log.info("Phase 4: I/O replacement (skipped — resuming)")

    # -----------------------------------------------------------------------
    # Phase 5: CALL replacement (incremental, batch_size blocks at a time)
    # -----------------------------------------------------------------------
    if start_phase <= 5:
        log.info("Phase 5: CALL replacement (incremental, batch_size=%d)", batch_size)
        from .cobol_mock import _replace_call_stmts, _replace_accept_stmts
        batch_num = 0
        while True:
            lines = mock_path.read_text(errors="replace").splitlines(keepends=True)
            new_lines, replaced = _replace_call_stmts(lines, max_count=batch_size)
            if replaced == 0:
                break
            batch_num += 1
            log.info("  Batch %d: replaced %d CALL statements", batch_num, replaced)
            snapshot = "".join(lines)
            mock_path.write_text("".join(new_lines))

            new_res = _compile_and_fix(
                mock_path, "call_replacement", batch_num, resolutions,
                copybook_dirs=copybook_dirs,
                llm_provider=llm_provider, llm_model=llm_model,
                baseline_errors=baseline_errors,
            )
            resolutions.extend(new_res)
            _save_resolutions(resolutions, resolution_log_path)

            # Revert + one-by-one if batch causes too many errors
            rc, stderr = _cobc_syntax_check(mock_path, copybook_dirs)
            if rc != 0:
                errs = _parse_errors(stderr, mock_path.name)
                if len(errs) > 10:
                    log.warning("  Batch %d: %d errors remain, reverting to one-by-one",
                                batch_num, len(errs))
                    mock_path.write_text(snapshot)
                    for _ in range(batch_size):
                        lines = mock_path.read_text(errors="replace").splitlines(keepends=True)
                        one_lines, one_replaced = _replace_call_stmts(lines, max_count=1)
                        if one_replaced == 0:
                            break
                        mock_path.write_text("".join(one_lines))
                        one_res = _compile_and_fix(
                            mock_path, "call_replacement", batch_num, resolutions,
                            copybook_dirs=copybook_dirs,
                            llm_provider=llm_provider, llm_model=llm_model,
                            baseline_errors=baseline_errors,
                        )
                        resolutions.extend(one_res)
                        _save_resolutions(resolutions, resolution_log_path)

        # Replace ACCEPT statements (safe, one-shot — just substitutes CONTINUE)
        lines = mock_path.read_text(errors="replace").splitlines(keepends=True)
        lines = _replace_accept_stmts(lines)
        mock_path.write_text("".join(lines))

        log.info("  Phase 5 complete (%d batches)", batch_num)
        _assert_clean(mock_path, "Phase 5 (CALL replacement)",
                      copybook_dirs, resolutions, resolution_log_path,
                      output_dir, "call_replacement", 4)
        _save_checkpoint(output_dir, "call_replacement", 5, mock_path)
    else:
        log.info("Phase 5: CALL replacement (skipped — resuming)")

    # -----------------------------------------------------------------------
    # Phase 6: Paragraph tracing
    # -----------------------------------------------------------------------
    cp_name = _load_checkpoint(output_dir).get("last_completed_phase", "")
    if start_phase <= 6:
        if cp_name != "para_tracing_transformed":
            log.info("Phase 6: Paragraph tracing")
            lines = mock_path.read_text(errors="replace").splitlines(keepends=True)
            lines, desc, total_paragraphs = _phase_paragraph_tracing(lines)
            mock_path.write_text("".join(lines))
            log.info("  %s", desc)
            _save_checkpoint(output_dir, "para_tracing_transformed", 5, mock_path)
        else:
            log.info("Phase 6: Paragraph tracing (transform done, resuming fixes)")

        new_res = _compile_and_fix(
            mock_path, "paragraph_tracing", 0, resolutions,
            copybook_dirs=copybook_dirs,
            llm_provider=llm_provider, llm_model=llm_model,
            baseline_errors=baseline_errors,
            audit_path=audit_path,
        )
        resolutions.extend(new_res)
        _save_resolutions(resolutions, resolution_log_path)
        _assert_clean(mock_path, "Phase 6 (paragraph tracing)",
                      copybook_dirs, resolutions, resolution_log_path,
                      output_dir, "para_tracing_transformed", 5)
        _save_checkpoint(output_dir, "paragraph_tracing", 6, mock_path)
    else:
        log.info("Phase 6: Paragraph tracing (skipped — resuming)")

    # -----------------------------------------------------------------------
    # Phase 7: Normalization
    # -----------------------------------------------------------------------
    cp_name = _load_checkpoint(output_dir).get("last_completed_phase", "")
    if start_phase <= 7:
        if cp_name != "normalization_transformed":
            log.info("Phase 7: Normalization")
            lines = mock_path.read_text(errors="replace").splitlines(keepends=True)
            lines, desc = _phase_normalization(lines, config)
            mock_path.write_text("".join(lines))
            log.info("  %s", desc)
            _save_checkpoint(output_dir, "normalization_transformed", 6, mock_path)
        else:
            log.info("Phase 7: Normalization (transform done, resuming fixes)")

        new_res = _compile_and_fix(
            mock_path, "normalization", 0, resolutions,
            copybook_dirs=copybook_dirs,
            llm_provider=llm_provider, llm_model=llm_model,
            baseline_errors=baseline_errors,
            audit_path=audit_path,
        )
        resolutions.extend(new_res)
        _save_resolutions(resolutions, resolution_log_path)
        _assert_clean(mock_path, "Phase 7 (normalization)",
                      copybook_dirs, resolutions, resolution_log_path,
                      output_dir, "normalization_transformed", 6)
        _save_checkpoint(output_dir, "normalization", 7, mock_path)
    else:
        log.info("Phase 7: Normalization (skipped — resuming)")

    # -----------------------------------------------------------------------
    # Phase 8: Auto-stub undefined symbols
    # -----------------------------------------------------------------------
    if start_phase <= 8:
        # Phase 8: Skip auto-stub — the compile-and-fix loop handles
        # undefined symbols via LLM, one at a time with verification.
        # Auto-stub was running cobc up to 48 times and its destructive
        # cleanup phases (_comment_data_blocks, _cleanup_unbalanced_procedure)
        # caused more errors than they fixed.
        log.info("Phase 8: Compile-and-fix (LLM handles undefined symbols)")

        # Recount paragraphs
        lines = mock_path.read_text(errors="replace").splitlines(keepends=True)
        total_paragraphs = sum(
            1 for l in lines
            if "SPECTER-TRACE:" in l and not l.strip().startswith("*")
        )

        new_res = _compile_and_fix(
            mock_path, "compile_fix", 0, resolutions,
            copybook_dirs=copybook_dirs,
            llm_provider=llm_provider, llm_model=llm_model,
            baseline_errors=baseline_errors,
            audit_path=audit_path,
        )
        resolutions.extend(new_res)
        _save_resolutions(resolutions, resolution_log_path)
        _assert_clean(mock_path, "Phase 8 (compile fix)",
                      copybook_dirs, resolutions, resolution_log_path,
                      output_dir, "compile_fix", 7)
        _save_checkpoint(output_dir, "compile_fix", 8, mock_path)
    else:
        log.info("Phase 8: Auto-stub (skipped — resuming)")
        # Recount paragraphs from existing mock
        lines = mock_path.read_text(errors="replace").splitlines(keepends=True)
        total_paragraphs = sum(
            1 for l in lines
            if "SPECTER-TRACE:" in l and not l.strip().startswith("*")
        )

    # -----------------------------------------------------------------------
    # Apply GnuCOBOL source fixups on the complete instrumented source
    # -----------------------------------------------------------------------
    if start_phase <= 9:
        # GnuCOBOL fixups disabled — the brute-force VALUES ARE replacement
        # is the only safe one, and it's now handled by the LLM when it sees
        # the compilation error. The multi-line rules (period before level,
        # orphaned VALUE, duplicate removal) caused more problems than they solved.
        log.info("Phase 9: Final compile-and-fix")

        new_res = _compile_and_fix(
            mock_path, "final_fix", 0, resolutions,
            copybook_dirs=copybook_dirs,
            llm_provider=llm_provider, llm_model=llm_model,
            audit_path=audit_path,
        )
        resolutions.extend(new_res)
        _save_resolutions(resolutions, resolution_log_path)
        _assert_clean(mock_path, "Phase 9 (final fix)",
                      copybook_dirs, resolutions, resolution_log_path,
                      output_dir, "gnucobol_fixups", 8)
        _save_checkpoint(output_dir, "gnucobol_fixups", 9, mock_path)
    else:
        log.info("GnuCOBOL fixups (skipped — resuming)")

    # -----------------------------------------------------------------------
    # Final compilation to executable
    # -----------------------------------------------------------------------
    log.info("Final compilation to executable")
    executable_path = output_dir / source_path.stem
    rc, stderr = _cobc_compile(mock_path, executable_path, copybook_dirs)

    if rc != 0:
        # One more attempt with LLM fixes
        errors = _parse_errors(stderr, mock_path.name)
        log.warning("Final compile failed with %d errors, attempting fixes",
                     len(errors))
        new_res = _compile_and_fix(
            mock_path, "final_compile", 0, resolutions,
            copybook_dirs=copybook_dirs,
            llm_provider=llm_provider, llm_model=llm_model,
            max_fix_attempts=15,
            audit_path=audit_path,
        )
        resolutions.extend(new_res)
        _save_resolutions(resolutions, resolution_log_path)

        # Retry compilation
        rc, stderr = _cobc_compile(mock_path, executable_path, copybook_dirs)

    if rc != 0:
        errors = _parse_errors(stderr, mock_path.name)
        raise RuntimeError(
            f"COBOL compilation failed with {len(errors)} errors after "
            f"incremental instrumentation:\n{stderr[:2000]}"
        )

    log.info("Compiled: %s", executable_path)

    # -----------------------------------------------------------------------
    # Phase 9: Branch probes (post-compilation, LLM-guided)
    # -----------------------------------------------------------------------
    log.info("Phase 9: Branch probes")
    branch_meta, total_branches, desc = _phase_branch_probes(
        mock_path, llm_provider, llm_model, copybook_dirs,
    )
    log.info("  %s", desc)

    if total_branches > 0:
        # Re-compile with branch probes
        rc, stderr = _cobc_compile(mock_path, executable_path, copybook_dirs)
        if rc != 0:
            # Try to fix
            new_res = _compile_and_fix(
                mock_path, "branch_probes", 0, resolutions,
                copybook_dirs=copybook_dirs,
                llm_provider=llm_provider, llm_model=llm_model,
                max_fix_attempts=5,
                audit_path=audit_path,
            )
            resolutions.extend(new_res)
            _save_resolutions(resolutions, resolution_log_path)

            rc, stderr = _cobc_compile(mock_path, executable_path, copybook_dirs)
            if rc != 0:
                # Revert to pre-probe source and re-compile
                log.warning("Branch probe compilation failed, reverting probes")
                source_text = mock_path.read_text(errors="replace")
                # Remove @@B: lines
                clean_lines = []
                for line in source_text.splitlines(keepends=True):
                    if "@@B:" in line and "DISPLAY" in line.upper():
                        clean_lines.append(_CMT + line[7:] if len(line) > 7 else line)
                    else:
                        clean_lines.append(line)
                mock_path.write_text("".join(clean_lines))
                branch_meta = {}
                total_branches = 0
                rc, stderr = _cobc_compile(mock_path, executable_path, copybook_dirs)
                if rc != 0:
                    raise RuntimeError(
                        f"COBOL compilation failed after reverting branch probes:\n"
                        f"{stderr[:2000]}"
                    )

    # Save final resolution log
    _save_resolutions(resolutions, resolution_log_path)

    # -----------------------------------------------------------------------
    # Integrity check: verify the LLM didn't comment out important code
    # -----------------------------------------------------------------------
    final_lines = mock_path.read_text(errors="replace").splitlines()
    n_trace = sum(1 for l in final_lines
                  if "SPECTER-TRACE:" in l and not l.strip().startswith("*"))
    n_mock_display = sum(1 for l in final_lines
                         if "SPECTER-MOCK:" in l and not l.strip().startswith("*"))
    n_comment = sum(1 for l in final_lines if len(l) > 6 and l[6:7] == "*")
    n_total = len(final_lines)
    comment_pct = (n_comment / n_total * 100) if n_total else 0

    integrity_msg = (
        f"Integrity: {n_trace} paragraph traces, {n_mock_display} mock probes, "
        f"{n_comment}/{n_total} lines commented ({comment_pct:.1f}%)"
    )
    log.info(integrity_msg)
    if comment_pct > 40:
        log.warning("  ⚠️  High comment ratio (%.1f%%) — check fix_audit.log "
                     "for destructive fixes", comment_pct)

    # Write integrity summary to audit log
    if audit_path:
        with open(audit_path, "a") as f:
            f.write(f"\n{'='*72}\n")
            f.write(f"FINAL INTEGRITY CHECK\n")
            f.write(f"  Paragraph traces (SPECTER-TRACE): {n_trace}\n")
            f.write(f"  Mock probes (SPECTER-MOCK): {n_mock_display}\n")
            f.write(f"  Total lines: {n_total}\n")
            f.write(f"  Comment lines: {n_comment} ({comment_pct:.1f}%)\n")
            f.write(f"  Resolutions applied: {len(resolutions)}\n")
            f.write(f"  Branch probes: {total_branches}\n")
            f.write(f"{'='*72}\n")

    # Summary
    total_resolutions = len(resolutions)
    log.info(
        "Incremental instrumentation complete: %s "
        "(%d paragraphs, %d branches, %d resolutions)",
        executable_path, total_paragraphs, total_branches, total_resolutions,
    )

    return mock_path, branch_meta, total_branches
