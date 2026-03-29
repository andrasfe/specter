"""Cache for LLM-assisted COBOL compilation fixes.

Stores fixes keyed by normalized error patterns so the same structural
error doesn't require an LLM call twice. The cache is a JSON file that
persists across runs.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

# COBOL keywords to preserve during normalization (not replaced with <NAME>)
_COBOL_KEYWORDS = {
    "ACCEPT", "ADD", "ALL", "AND", "BINARY", "BLANK", "BY", "CALL",
    "CLOSE", "COMP", "COMPUTE", "CONTINUE", "COPY", "DATA", "DELETE",
    "DISPLAY", "DIVIDE", "DIVISION", "ELSE", "END", "EVALUATE", "EXEC",
    "EXIT", "FD", "FILE", "FILLER", "FROM", "GIVING", "GO", "GOBACK",
    "IF", "IN", "INITIALIZE", "INPUT", "INSPECT", "INTO", "IS", "KEY",
    "MOVE", "MULTIPLY", "NOT", "NUMERIC", "OCCURS", "OF", "OPEN", "OR",
    "ORGANIZATION", "OUTPUT", "PERFORM", "PIC", "PICTURE", "PROCEDURE",
    "READ", "RECORD", "REDEFINES", "REPLACING", "RETURN", "REWRITE",
    "SECTION", "SELECT", "SEQUENTIAL", "SET", "SIGN", "SPACES", "STATUS",
    "STOP", "STRING", "SUBTRACT", "SYNC", "THRU", "TO", "UNTIL", "USAGE",
    "VALUE", "VARYING", "WHEN", "WITH", "WRITE", "ZEROS", "ZEROES",
}


@dataclass
class FixEntry:
    """A cached compilation fix."""
    error_type: str
    context_pattern: str
    context_hash: str
    original_lines: list[str]
    fixed_lines: list[str]
    source: str = "llm"  # "llm" or "rule"
    llm_model: str = ""
    timestamp: str = ""
    verified: bool = False  # True once error disappeared on recompile


@dataclass
class InvestigationResult:
    """Result from a multi-turn LLM investigation of a compilation error."""
    fixes: dict[int, str]
    diagnosis: str = ""
    suggested_next_target: int | None = None
    exhausted: bool = False


@dataclass
class EscalationState:
    """Tracks escalation through increasingly aggressive fix strategies.

    Levels:
      0 — normal (cache + single-error LLM + rules)
      1 — investigate: multi-turn LLM investigation (10 turns)
      2 — deep: wider context investigation
      3 — revert-and-retry: revert to best snapshot, try different error
    """
    level: int = 0
    stall_count: int = 0
    best_error_count: int = 999999
    best_source: str = ""
    investigated_sigs: set = field(default_factory=set)
    failed_fix_hashes: set = field(default_factory=set)
    pass_number: int = 0

    def update(self, error_count: int, current_source: str):
        """Update escalation state after a compilation attempt."""
        self.pass_number += 1
        if error_count < self.best_error_count:
            self.best_error_count = error_count
            self.best_source = current_source
            self.stall_count = 0
            self.level = 0
        else:
            self.stall_count += 1
            if self.stall_count >= 2 and self.level < 1:
                self.level = 1
            if self.stall_count >= 4 and self.level < 2:
                self.level = 2
            if self.stall_count >= 6 and self.level < 3:
                self.level = 3


class CobolFixCache:
    """Persistent cache for COBOL compilation fixes."""

    def __init__(self, cache_path: Path | str):
        self._path = Path(cache_path)
        self._fixes: list[FixEntry] = []
        self._load()

    def _load(self):
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text())
            for entry in data.get("fixes", []):
                self._fixes.append(FixEntry(**{
                    k: v for k, v in entry.items()
                    if k in FixEntry.__dataclass_fields__
                }))
            log.info("Loaded %d cached COBOL fixes from %s",
                     len(self._fixes), self._path)
        except (json.JSONDecodeError, TypeError, KeyError) as e:
            log.warning("Failed to load fix cache: %s", e)

    def save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": 1,
            "fixes": [asdict(f) for f in self._fixes],
        }
        self._path.write_text(json.dumps(data, indent=2, default=str))

    def lookup(self, error_type: str, context_lines: list[str]) -> list[str] | None:
        """Find a cached fix matching this error pattern.

        Returns the fixed lines or None if no match.
        """
        pattern = normalize_context(context_lines)
        h = _hash_pattern(error_type, pattern)
        for fix in self._fixes:
            if fix.context_hash == h:
                return fix.fixed_lines
        return None

    def record(
        self,
        error_type: str,
        context_lines: list[str],
        fixed_lines: list[str],
        source: str = "llm",
        model: str = "",
        verified: bool = False,
    ):
        """Record a fix and persist immediately.

        Fixes are saved as pending (verified=False) until the error
        disappears on recompile, then promoted via promote().
        Pending fixes are still usable on cache load — they survive
        crashes so LLM work is never lost.
        """
        pattern = normalize_context(context_lines)
        h = _hash_pattern(error_type, pattern)
        # Don't duplicate
        for fix in self._fixes:
            if fix.context_hash == h:
                fix.fixed_lines = fixed_lines
                if verified:
                    fix.verified = True
                self.save()
                return
        self._fixes.append(FixEntry(
            error_type=error_type,
            context_pattern=pattern,
            context_hash=h,
            original_lines=list(context_lines),
            fixed_lines=list(fixed_lines),
            source=source,
            llm_model=model,
            timestamp=datetime.now(timezone.utc).isoformat(),
            verified=verified,
        ))
        self.save()

    def promote(self, error_type: str, context_lines: list[str]):
        """Mark a pending fix as verified (error disappeared on recompile)."""
        pattern = normalize_context(context_lines)
        h = _hash_pattern(error_type, pattern)
        for fix in self._fixes:
            if fix.context_hash == h and not fix.verified:
                fix.verified = True
                self.save()
                return

    def __len__(self):
        return len(self._fixes)


def normalize_context(lines: list[str]) -> str:
    """Normalize COBOL lines for pattern matching.

    Replaces variable names and numbers with placeholders while
    preserving COBOL structure and keywords.
    """
    result = []
    for line in lines:
        # Work on the code area (cols 7-72)
        if len(line) > 7:
            content = line[7:72] if len(line) > 72 else line[7:]
        else:
            content = line
        content = content.rstrip()

        # Skip comment lines — just mark them
        if len(line) > 6 and line[6] in ("*", "/"):
            result.append("*COMMENT")
            continue

        # Replace PIC clauses
        content = re.sub(
            r"\bPIC(?:TURE)?\s+[SX9()\sVBCOMP.-]+",
            "<PIC>", content, flags=re.IGNORECASE,
        )
        # Replace numeric literals
        content = re.sub(r"\b\d+\b", "<NUM>", content)
        # Replace identifiers (but not COBOL keywords)
        def _replace_id(m):
            word = m.group(0)
            if word.upper() in _COBOL_KEYWORDS:
                return word
            return "<NAME>"
        content = re.sub(r"\b[A-Z][A-Z0-9-]+\b", _replace_id, content)
        result.append(content.strip())

    return "\n".join(result)


def _hash_pattern(error_type: str, pattern: str) -> str:
    """Hash the normalized pattern for cache lookup."""
    payload = f"{error_type}||{pattern}"
    return hashlib.sha256(payload.encode()).hexdigest()[:12]


def parse_compilation_errors(
    stderr: str, source_name: str,
) -> list[tuple[int, str]]:
    """Parse error line numbers and messages from cobc stderr.

    Returns list of (lineno, error_message) tuples.
    """
    errors: list[tuple[int, str]] = []
    seen_lines: set[int] = set()
    for line in stderr.splitlines():
        if "error:" not in line.lower():
            continue
        if source_name not in line:
            continue
        m = re.search(rf"{re.escape(source_name)}:(\d+):\s*error:\s*(.*)", line)
        if m:
            lineno = int(m.group(1))
            msg = m.group(2).strip()
            if lineno not in seen_lines:
                errors.append((lineno, msg))
                seen_lines.add(lineno)
    return errors


def llm_fix_errors(
    llm_provider,
    llm_model: str | None,
    errors: list[tuple[int, str]],
    src_lines: list[str],
    session_fixes: list[str],
    source_name: str = "",
) -> dict[int, list[str]]:
    """Query LLM to fix compilation errors.

    Args:
        errors: List of (lineno, error_message).
        src_lines: Full source as list of lines.
        session_fixes: Prior fixes in this session (for context).
        source_name: Filename for context in the prompt.

    Returns dict mapping error_lineno → fixed_lines (replacement for the window).
    """
    from .llm_coverage import _query_llm_sync

    # Group errors by proximity (batch nearby errors together)
    batches: list[list[tuple[int, str]]] = []
    current_batch: list[tuple[int, str]] = []
    for lineno, msg in sorted(errors):
        if current_batch and lineno - current_batch[-1][0] > 20:
            batches.append(current_batch)
            current_batch = []
        current_batch.append((lineno, msg))
    if current_batch:
        batches.append(current_batch)

    fixes: dict[int, list[str]] = {}

    for batch in batches[:10]:  # max 10 LLM calls per pass
        # Extract window around the batch — 50 lines context minimum
        min_line = max(0, batch[0][0] - 51)
        max_line = min(len(src_lines), batch[-1][0] + 20)
        window = src_lines[min_line:max_line]

        error_desc = "\n".join(
            f"Line {ln}: {msg}" for ln, msg in batch
        )

        # Detect if the error region is DATA DIVISION or PROCEDURE DIVISION
        division = "DATA DIVISION"
        for i in range(min(min_line, len(src_lines))):
            ln_text = src_lines[i][6:72] if len(src_lines[i]) > 6 else src_lines[i]
            if "PROCEDURE DIVISION" in ln_text.upper():
                division = "PROCEDURE DIVISION"
                break

        prior_context = ""
        if session_fixes:
            prior_context = (
                "\n\nPrior fixes applied in this session:\n"
                + "\n".join(f"- {f}" for f in session_fixes[-10:])
            )

        file_context = ""
        if source_name:
            file_context = f"File: {source_name}\n"

        # Number the lines for the LLM
        numbered = "\n".join(
            f"{min_line + i + 1:5d}: {line.rstrip()}"
            for i, line in enumerate(window)
        )

        prompt = (
            "You are fixing GnuCOBOL compilation errors in an instrumented COBOL source.\n"
            "The original code compiles on IBM mainframes but GnuCOBOL (-std=ibm) is stricter.\n\n"
            f"{file_context}"
            f"Section: {division} ({'data definitions / copybook content' if division == 'DATA DIVISION' else 'executable statements'})\n\n"
            f"Errors:\n{error_desc}\n\n"
            f"Context (lines {min_line+1}-{max_line}):\n"
            f"```cobol\n{numbered}\n```\n"
            f"{prior_context}\n\n"
            "Fix the COBOL so it compiles with GnuCOBOL while preserving the original semantics.\n"
            "Common fixes: VALUES ARE → VALUE, remove separator comments inside VALUE clauses,\n"
            "fix premature periods, uncomment continuation lines, P.I.C. → PIC,\n"
            "remove duplicate definitions, fix level-number hierarchy issues.\n\n"
            "Output ONLY the corrected lines as a flat JSON object mapping line number to fixed content.\n"
            "Example: {\"5417\": \"       10  EXT-K1-WS  PIC 99.\", \"5418\": \"       10  EXT-K2-WS  PIC 99.\"}\n"
            "Do NOT wrap in outer keys like 'changed_lines'. Do NOT add explanations.\n"
            "Only include lines that changed. Preserve COBOL column formatting (cols 7-72)."
        )

        try:
            response, _ = _query_llm_sync(llm_provider, prompt, llm_model)
            parsed = _parse_llm_fix_response(response, min_line, max_line)
            if parsed:
                for lineno, fixed_line in parsed.items():
                    fixes[lineno] = fixed_line
                log.info("LLM fix: %d lines corrected for errors at %s",
                         len(parsed), [ln for ln, _ in batch])
            else:
                # Log first 200 chars of response so we can debug why parsing failed
                snippet = response[:200].replace("\n", "\\n") if response else "(empty)"
                log.info("LLM response not parsed (lines %d-%d): %s",
                          min_line + 1, max_line, snippet)
        except Exception as e:
            log.warning("LLM fix query failed: %s", e)

    return fixes


def _format_numbered(src_lines: list[str], start: int, end: int) -> str:
    """Format source lines with line numbers for LLM context."""
    return "\n".join(
        f"{start + i + 1:5d}: {line.rstrip()}"
        for i, line in enumerate(src_lines[start:end])
    )


def llm_investigate_cascade(
    llm_provider,
    llm_model: str | None,
    first_error_line: int,
    error_msg: str,
    all_errors: list[tuple[int, str]],
    src_lines: list[str],
    source_name: str = "",
    max_turns: int = 10,
    prior_attempts: list[str] | None = None,
) -> InvestigationResult:
    """Multi-turn LLM investigation of cascade root cause.

    The LLM can request specific chunks of the source file to
    investigate where the parser lost context. Up to max_turns
    rounds of conversation.

    Returns an InvestigationResult with fixes, diagnosis, and optional
    redirect to a different error line.
    """
    from .llm_coverage import _query_llm_sync, Message

    _empty = InvestigationResult(fixes={})

    total_lines = len(src_lines)
    idx = first_error_line - 1
    # When few errors remain, expand initial window dramatically —
    # the root cause may be hundreds of lines before the error
    n_errors = len(all_errors)
    lookback = 1000 if n_errors <= 20 else (500 if n_errors <= 100 else 200)
    min_line = max(0, idx - lookback)
    max_line = min(total_lines, idx + 5)
    initial_window = _format_numbered(src_lines, min_line, max_line)

    # Show first 30 error locations as clues
    error_locs = ", ".join(str(ln) for ln, _ in all_errors[:30])

    file_ctx = f"File: {source_name} ({total_lines} lines total)\n" if source_name else ""

    prior_ctx = ""
    if prior_attempts:
        prior_ctx = (
            "\n\nIMPORTANT — The following fix approaches were already tried "
            "and DID NOT resolve the error. Do NOT repeat them:\n"
            + "\n".join(f"- {a}" for a in prior_attempts[-10:])
            + "\n"
        )

    system_msg = Message(
        role="system",
        content=(
            "You are investigating a GnuCOBOL compilation cascade failure in a "
            "large instrumented COBOL source file. You can request chunks of the "
            "file to investigate. Respond with ONLY JSON, no explanations."
            + prior_ctx
        ),
    )

    user_msg = Message(
        role="user",
        content=(
            f"{file_ctx}"
            f"The compiler reports {len(all_errors)} errors. "
            f"The first error on a valid data definition is at line {first_error_line}:\n"
            f"  {error_msg}\n\n"
            "All errors from this line onward are CASCADE SYMPTOMS — the lines "
            "themselves are valid COBOL. The root cause is a malformed line "
            "somewhere ABOVE that broke the parser's DATA DIVISION context.\n\n"
            "Common root causes:\n"
            "- A VALUE clause missing a terminal period\n"
            "- A commented-out line that broke a multi-line VALUE or record structure\n"
            "- IBM-only syntax like VALUES ARE (should be VALUE)\n"
            "- A separator comment inside a VALUE clause\n\n"
            f"First error and 100 lines before it:\n"
            f"```cobol\n{initial_window}\n```\n\n"
            f"Other error locations: {error_locs}\n\n"
            "You have THREE options:\n\n"
            "OPTION A — You found the root cause. Return:\n"
            "{\"fix\": {\"12345\": \"       fixed content line\"}}\n\n"
            "OPTION B — You need to see more of the file. Return:\n"
            "{\"need_context\": {\"start\": 3720, \"end\": 3770, \"reason\": \"checking first error area\"}}\n\n"
            "OPTION C — You believe this error line is NOT the real problem and "
            "want to redirect investigation. Return:\n"
            "{\"give_up\": {\"reason\": \"explanation\", \"suggested_line\": 5432}}\n\n"
            "Respond with ONLY the JSON."
        ),
    )

    messages = [system_msg, user_msg]
    parse_retries = 0
    max_parse_retries = 2

    for turn in range(max_turns):
        try:
            response, _ = _query_llm_sync(llm_provider, messages, llm_model)
        except Exception as e:
            log.warning("LLM cascade investigation failed on turn %d: %s", turn + 1, e)
            return _empty

        # Strip markdown code blocks
        cleaned = re.sub(r"```\w*\n?", "", response).strip()

        # Try to parse JSON
        parsed = None
        try:
            parsed = json.loads(cleaned)
        except (json.JSONDecodeError, ValueError):
            # Try to find JSON in the response
            m = re.search(r"\{[^{}]*\{[^{}]*\}[^{}]*\}", cleaned) or re.search(r"\{[^{}]+\}", cleaned)
            if m:
                try:
                    parsed = json.loads(m.group())
                except (json.JSONDecodeError, ValueError):
                    pass

        if parsed is None:
            # JSON parse failure — send corrective message instead of aborting
            parse_retries += 1
            if parse_retries > max_parse_retries:
                log.warning("  Turn %d: JSON parse failed %d times, giving up",
                            turn + 1, parse_retries)
                return InvestigationResult(fixes={}, exhausted=True)

            log.info("  Turn %d: JSON parse failed, sending correction (retry %d/%d)",
                     turn + 1, parse_retries, max_parse_retries)
            messages.append(Message(role="assistant", content=response))
            messages.append(Message(
                role="user",
                content=(
                    "Your response was not valid JSON. Please respond with ONLY "
                    "a JSON object in one of these formats:\n"
                    '{\"fix\": {\"LINE\": \"content\"}}\n'
                    '{\"need_context\": {\"start\": N, \"end\": M, \"reason\": \"...\"}}\n'
                    '{\"give_up\": {\"reason\": \"...\", \"suggested_line\": N}}\n'
                    "No markdown, no explanation — just the JSON."
                ),
            ))
            continue

        # OPTION C: LLM gives up on this error, suggests different target
        if "give_up" in parsed:
            give_up_data = parsed["give_up"]
            reason = give_up_data.get("reason", "unknown")
            suggested = give_up_data.get("suggested_line")
            if isinstance(suggested, (int, float)):
                suggested = int(suggested)
            else:
                suggested = None
            log.info("  Turn %d: LLM gave up on line %d: %s (suggested: %s)",
                     turn + 1, first_error_line, reason, suggested)
            return InvestigationResult(
                fixes={},
                diagnosis=reason,
                suggested_next_target=suggested,
                exhausted=True,
            )

        # OPTION A: LLM found a fix
        if "fix" in parsed:
            fix_data = parsed["fix"]
            if isinstance(fix_data, dict):
                result = _parse_llm_fix_response(
                    json.dumps(fix_data), 0, total_lines,
                )
                if result:
                    log.info("  Turn %d: LLM found root cause — %d lines fixed",
                             turn + 1, len(result))
                    return InvestigationResult(fixes=result)

        # OPTION B: LLM needs more context
        if "need_context" in parsed:
            req = parsed["need_context"]
            req_start = max(0, int(req.get("start", 1)) - 1)
            req_end = min(total_lines, int(req.get("end", req_start + 50)))
            reason = req.get("reason", "")

            # Cap chunk size — generous when few errors remain
            max_chunk = 1000 if n_errors <= 20 else (500 if n_errors <= 100 else 200)
            if req_end - req_start > max_chunk:
                req_end = req_start + max_chunk

            chunk = _format_numbered(src_lines, req_start, req_end)

            log.info("  Turn %d: LLM requested lines %d-%d (%s)",
                     turn + 1, req_start + 1, req_end, reason)

            messages.append(Message(role="assistant", content=response))
            messages.append(Message(
                role="user",
                content=f"Lines {req_start + 1}-{req_end}:\n```cobol\n{chunk}\n```",
            ))
            continue

        # Unrecognized — try parsing as a flat fix dict
        result = _parse_llm_fix_response(json.dumps(parsed), 0, total_lines)
        if result:
            log.info("  Turn %d: LLM returned fix (flat format) — %d lines",
                     turn + 1, len(result))
            return InvestigationResult(fixes=result)

        log.warning("  Turn %d: unrecognized LLM response format", turn + 1)
        return _empty

    log.warning("  LLM cascade investigation exhausted %d turns", max_turns)
    return InvestigationResult(fixes={}, exhausted=True)


def _parse_llm_fix_response(
    response: str, min_line: int, max_line: int,
) -> dict[int, str]:
    """Parse LLM response into {lineno: fixed_line} dict.

    Handles multiple formats:
    - Plain text: "12345: fixed content"
    - JSON: {"12345": "12345: fixed content"} or {"12345": "fixed content"}
    - Markdown code blocks: ```cobol ... ```
    """
    fixes: dict[int, str] = {}

    # Strip markdown code blocks if present
    cleaned = re.sub(r"```\w*\n?", "", response)

    # Try JSON parse first (GPT models often return JSON)
    if cleaned.strip().startswith("{"):
        try:
            data = json.loads(cleaned)
            # Unwrap nested structures like {"changed_lines": {...}}
            # or {"fixes": {...}} — find the inner dict with line numbers
            if len(data) == 1:
                inner = next(iter(data.values()))
                if isinstance(inner, dict):
                    data = inner
            for key, value in data.items():
                m_key = re.match(r"(\d+)", str(key))
                if not m_key:
                    continue
                lineno = int(m_key.group(1))
                if not (min_line < lineno <= max_line):
                    continue
                content = str(value)
                m_val = re.match(r"\s*\d+\s*:\s?(.*)", content)
                if m_val:
                    content = m_val.group(1)
                if not content.startswith(" " * 6):
                    content = " " * 6 + " " + content.lstrip()
                fixes[lineno] = content + "\n"
            if fixes:
                return fixes
        except (json.JSONDecodeError, TypeError, ValueError):
            pass  # Fall through to line-by-line parsing

    # Line-by-line parsing
    for line in cleaned.splitlines():
        line = line.strip()
        if not line:
            continue
        # Match: "  1234: fixed content" or "1234: fixed content"
        m = re.match(r"(\d+)\s*:\s?(.*)", line)
        if m:
            lineno = int(m.group(1))
            content = m.group(2)
            if min_line < lineno <= max_line:
                if not content.startswith(" " * 6):
                    content = " " * 6 + " " + content.lstrip()
                fixes[lineno] = content + "\n"
    return fixes
