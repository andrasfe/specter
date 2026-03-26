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
) -> dict[int, list[str]]:
    """Query LLM to fix compilation errors.

    Args:
        errors: List of (lineno, error_message).
        src_lines: Full source as list of lines.
        session_fixes: Prior fixes in this session (for context).

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
        # Extract window around the batch
        min_line = max(0, batch[0][0] - 11)
        max_line = min(len(src_lines), batch[-1][0] + 10)
        window = src_lines[min_line:max_line]

        error_desc = "\n".join(
            f"Line {ln}: {msg}" for ln, msg in batch
        )

        prior_context = ""
        if session_fixes:
            prior_context = (
                "\n\nPrior fixes applied in this session:\n"
                + "\n".join(f"- {f}" for f in session_fixes[-10:])
            )

        # Number the lines for the LLM
        numbered = "\n".join(
            f"{min_line + i + 1:5d}: {line.rstrip()}"
            for i, line in enumerate(window)
        )

        prompt = (
            "You are fixing GnuCOBOL compilation errors in an instrumented COBOL source.\n"
            "The original code compiles on IBM mainframes but GnuCOBOL (-std=ibm) is stricter.\n\n"
            f"Errors:\n{error_desc}\n\n"
            f"Context (lines {min_line+1}-{max_line}):\n"
            f"```cobol\n{numbered}\n```\n"
            f"{prior_context}\n\n"
            "Fix the COBOL so it compiles with GnuCOBOL while preserving the original semantics.\n"
            "Common fixes: remove separator comments inside VALUE clauses, fix premature periods,\n"
            "uncomment continuation lines, fix P.I.C. → PIC, remove duplicate definitions.\n\n"
            "Output ONLY the corrected lines with their line numbers, same format as above.\n"
            "Do not add explanations. Only output lines that changed."
        )

        try:
            response, _ = _query_llm_sync(llm_provider, prompt, llm_model)
            parsed = _parse_llm_fix_response(response, min_line, max_line)
            if parsed:
                for lineno, fixed_line in parsed.items():
                    fixes[lineno] = fixed_line
                log.info("LLM fix: %d lines corrected for errors at %s",
                         len(parsed), [ln for ln, _ in batch])
        except Exception as e:
            log.warning("LLM fix query failed: %s", e)

    return fixes


def _parse_llm_fix_response(
    response: str, min_line: int, max_line: int,
) -> dict[int, str]:
    """Parse LLM response into {lineno: fixed_line} dict."""
    fixes: dict[int, str] = {}
    for line in response.splitlines():
        line = line.strip()
        if not line:
            continue
        # Match: "  1234: fixed content" or "1234: fixed content"
        m = re.match(r"(\d+)\s*:\s?(.*)", line)
        if m:
            lineno = int(m.group(1))
            content = m.group(2)
            if min_line < lineno <= max_line:
                # Ensure proper COBOL formatting (pad to at least 7 chars)
                if not content.startswith(" " * 6):
                    content = " " * 6 + " " + content.lstrip()
                fixes[lineno] = content + "\n"
    return fixes
