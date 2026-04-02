"""Post-compilation branch probe insertion.

After a COBOL mock compiles successfully, this module prefers a
deterministic syntax-safe branch tracer to insert @@B: probes for IF and
EVALUATE statements. If that full-file pass does not compile, it falls
back to an insertion-only LLM workflow that validates each paragraph with
`cobc` and reverts unsafe edits.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)

_AREA_B = "           "
_MAX_INSERTION_ATTEMPTS = 3

# Regex to match a paragraph label in PROCEDURE DIVISION.
# COBOL paragraph labels start in Area A (col 8-11) and end with a period.
_PARA_RE = re.compile(
    r"^(\s{7}[A-Z0-9][A-Z0-9_-]*)\s*\.\s*$",
    re.IGNORECASE,
)

# Timeout for syntax check compilation (seconds).
_SYNTAX_CHECK_TIMEOUT = 90


def instrument_branches(
    mock_cbl_path: Path,
    llm_provider,
    llm_model: str | None = None,
) -> tuple[int, int, dict]:
    """Insert @@B: branch probes into a compiled COBOL mock.

    First attempts deterministic full-file branch tracing. If that syntax
    checks cleanly, the instrumented source is written immediately. Only if
    the deterministic pass fails does it fall back to paragraph-by-paragraph
    insertion-only LLM instrumentation.

    Args:
        mock_cbl_path: Path to the instrumented .mock.cbl file.
        llm_provider: An LLM provider instance.
        llm_model: Optional model override.

    Returns:
        (probes_inserted, paragraphs_instrumented, branch_meta)
        branch_meta maps branch_id (str) to {paragraph, type}.
    """
    source_text = mock_cbl_path.read_text(errors="replace")
    lines = _remove_existing_branch_instrumentation(
        source_text.splitlines(keepends=True)
    )

    deterministic = _try_deterministic_branch_instrumentation(lines, mock_cbl_path)
    if deterministic is not None:
        instrumented_lines, total_probes, total_instrumented, branch_meta = deterministic
        mock_cbl_path.write_text("".join(instrumented_lines))
        log.info(
            "Branch instrumentation complete via deterministic tracer: %d probes in %d paragraphs",
            total_probes,
            total_instrumented,
        )
        return total_probes, total_instrumented, branch_meta

    if not llm_provider:
        log.info("Branch instrumentation skipped: deterministic tracer failed and no LLM provider is available")
        return 0, 0, {}

    from .llm_coverage import Message, _query_llm_sync

    # Find PROCEDURE DIVISION start
    proc_start = _find_procedure_division(lines)
    if proc_start is None:
        log.warning("No PROCEDURE DIVISION found in %s", mock_cbl_path)
        return 0, 0, {}

    # Find all paragraphs and their line ranges
    paragraphs = _find_paragraphs(lines, proc_start)
    if not paragraphs:
        log.info("No paragraphs found for branch instrumentation")
        return 0, 0, {}

    log.info("Branch instrumenter: found %d paragraphs in PROCEDURE DIVISION",
             len(paragraphs))

    branch_id = 0
    total_probes = 0
    total_instrumented = 0
    branch_meta: dict[str, dict] = {}

    for para_name, start_line, end_line in paragraphs:
        # Extract paragraph code
        para_lines = lines[start_line:end_line]
        para_text = "".join(para_lines)

        # Check if paragraph has IF or EVALUATE
        upper_text = para_text.upper()
        has_branch = False
        for ln in para_lines:
            content = ln[6:72].strip().upper() if len(ln) > 6 else ln.strip().upper()
            if ln[6:7] in ("*", "/") if len(ln) > 6 else False:
                continue  # skip comments
            if re.search(r'\bIF\s', content) and not content.startswith("END-IF"):
                has_branch = True
                break
            if re.search(r'\bEVALUATE\s', content):
                has_branch = True
                break

        if not has_branch:
            continue

        numbered_para = _format_numbered_paragraph(para_lines, start_line)
        messages = [
            Message(
                role="system",
                content=(
                    "You instrument COBOL paragraphs by INSERTING new lines only. "
                    "You must preserve all original COBOL lines exactly. "
                    "Always respond with valid JSON only."
                ),
            ),
            Message(
                role="user",
                content=_build_insertion_prompt(
                    para_name=para_name,
                    start_line=start_line + 1,
                    end_line=end_line,
                    branch_id=branch_id,
                    numbered_para=numbered_para,
                ),
            ),
        ]

        accepted = False
        for attempt in range(1, _MAX_INSERTION_ATTEMPTS + 1):
            try:
                response, _ = _query_llm_sync(llm_provider, messages, llm_model)
            except Exception as e:
                log.warning("  LLM failed for paragraph %s: %s", para_name, e)
                break

            insertions = _parse_insertion_plan(
                response,
                min_line=start_line + 1,
                max_line=end_line,
            )
            if not insertions:
                log.info("  No probes in LLM response for %s, skipping", para_name)
                break

            new_para_lines = _apply_insertions(para_lines, start_line, insertions)
            probes_in_response, para_branch_meta, next_branch_id = _collect_probe_info(
                new_para_lines,
                para_name,
            )
            if probes_in_response == 0:
                log.info("  No probes in parsed insertion plan for %s, skipping", para_name)
                break

            trial_lines = list(lines)
            trial_lines[start_line:end_line] = new_para_lines
            syntax_ok, syntax_output = _syntax_check_details(trial_lines, mock_cbl_path)
            if syntax_ok:
                lines[start_line:end_line] = new_para_lines
                delta = len(new_para_lines) - (end_line - start_line)
                branch_meta.update(para_branch_meta)
                total_probes += probes_in_response
                total_instrumented += 1
                branch_id = next_branch_id

                log.info("  Instrumented %s: %d probes inserted", para_name, probes_in_response)

                remaining_paras_adjusted = []
                for pn, ps, pe in paragraphs:
                    if ps > start_line:
                        remaining_paras_adjusted.append((pn, ps + delta, pe + delta))
                    else:
                        remaining_paras_adjusted.append((pn, ps, pe))
                paragraphs[:] = remaining_paras_adjusted
                accepted = True
                break

            if attempt >= _MAX_INSERTION_ATTEMPTS:
                log.info("  Syntax check failed for %s after %d attempts, reverting",
                         para_name, attempt)
                break

            log.info("  Syntax check failed for %s attempt %d/%d, retrying with compiler feedback",
                     para_name, attempt, _MAX_INSERTION_ATTEMPTS)
            messages.append(Message(role="assistant", content=response))
            messages.append(Message(
                role="user",
                content=(
                    "The insertion plan did not compile. Keep the paragraph insertion-only. "
                    "Do not rewrite original lines. Return corrected JSON only.\n\n"
                    f"Compiler output:\n{_truncate_syntax_feedback(syntax_output)}"
                ),
            ))

        if not accepted:
            continue

    # Write final instrumented source
    if total_probes > 0:
        mock_cbl_path.write_text("".join(lines))
        log.info("Branch instrumentation complete: %d probes in %d paragraphs",
                 total_probes, total_instrumented)

    return total_probes, total_instrumented, branch_meta


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _try_deterministic_branch_instrumentation(
    lines: list[str],
    reference_path: Path,
) -> tuple[list[str], int, int, dict] | None:
    """Try deterministic full-file branch tracing before invoking the LLM."""
    from .cobol_mock import _add_branch_tracing

    instrumented_lines, branch_meta, total_probes = _add_branch_tracing(lines)
    if total_probes <= 0:
        log.info("Deterministic branch tracer found no safe probes to insert")
        return instrumented_lines, 0, 0, {}

    syntax_ok, syntax_output = _syntax_check_details(instrumented_lines, reference_path)
    if not syntax_ok:
        log.info(
            "Deterministic branch tracer failed syntax check, falling back to insertion-only LLM path"
        )
        log.debug("Deterministic branch tracer compiler output:\n%s", syntax_output)
        return None

    instrumented_paragraphs = len({meta.get("paragraph", "") for meta in branch_meta.values() if meta.get("paragraph")})
    return instrumented_lines, total_probes, instrumented_paragraphs, branch_meta


def _remove_existing_branch_instrumentation(lines: list[str]) -> list[str]:
    """Strip active @@B/@@V instrumentation lines so re-runs stay idempotent."""
    cleaned: list[str] = []
    for line in lines:
        if len(line) > 6 and line[6] in ("*", "/"):
            cleaned.append(line)
            continue
        if "@@B:" in line or "@@V:" in line:
            continue
        cleaned.append(line)
    return cleaned

def _find_procedure_division(lines: list[str]) -> int | None:
    """Find the line index of PROCEDURE DIVISION."""
    for i, line in enumerate(lines):
        if len(line) > 6 and line[6] in ("*", "/"):
            continue
        content = line[6:72].upper() if len(line) > 6 else line.upper()
        if "PROCEDURE DIVISION" in content:
            return i
    return None


def _find_paragraphs(
    lines: list[str], proc_start: int,
) -> list[tuple[str, int, int]]:
    """Find all paragraphs after PROCEDURE DIVISION.

    Returns list of (name, start_line_idx, end_line_idx) tuples.
    The range is [start, end) — start is the label line, end is the
    line where the next paragraph starts (or end of file).
    """
    paragraphs: list[tuple[str, int, int]] = []
    current_name: str | None = None
    current_start: int | None = None

    for i in range(proc_start + 1, len(lines)):
        line = lines[i]
        m = _PARA_RE.match(line)
        if m:
            # Close previous paragraph
            if current_name is not None and current_start is not None:
                paragraphs.append((current_name, current_start, i))
            current_name = m.group(1).strip().upper()
            current_start = i

    # Close last paragraph
    if current_name is not None and current_start is not None:
        paragraphs.append((current_name, current_start, len(lines)))

    return paragraphs


def _clean_llm_response(response: str) -> str:
    """Strip markdown code fences and other wrappers from LLM output."""
    # Remove ```cobol ... ``` or ``` ... ```
    cleaned = re.sub(r"```\w*\n?", "", response)
    # Remove leading/trailing whitespace lines
    lines = cleaned.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()

    # Remove line numbers if the LLM included them
    result = []
    for line in lines:
        # Strip leading "  1234: " pattern
        m = re.match(r"^\s*\d+\s*:\s?(.*)", line)
        if m:
            result.append(m.group(1))
        else:
            result.append(line)

    return "\n".join(result)


def _format_numbered_paragraph(para_lines: list[str], start_line: int) -> str:
    """Format a paragraph with stable physical line numbers for insertion plans."""
    return "\n".join(
        f"{start_line + i + 1:5d}: {line.rstrip()}"
        for i, line in enumerate(para_lines)
    )


def _build_insertion_prompt(
    *,
    para_name: str,
    start_line: int,
    end_line: int,
    branch_id: int,
    numbered_para: str,
) -> str:
    """Build an insertion-only prompt for branch probes."""
    return (
        "Insert @@B: branch coverage probes into this COBOL paragraph using INSERTIONS ONLY.\n\n"
        f"Starting branch ID: {branch_id}\n"
        f"Paragraph: {para_name}\n\n"
        "Rules:\n"
        "- You may ONLY insert new COBOL lines after existing physical line numbers.\n"
        "- You must NOT rewrite, delete, reorder, renumber, or restate any original line.\n"
        "- Return JSON only in this form:\n"
        "  {\"insertions\": [{\"after_line\": 123, \"lines\": [\"DISPLAY '@@B:7:T'\"]}]}\n"
        "- `after_line` must be one of the numbered lines shown in the paragraph.\n"
        "- Each inserted line must be standalone valid COBOL source text without line numbers.\n"
        "- DISPLAY probe lines must be `DISPLAY '@@B:<id>:<suffix>'` with NO trailing period.\n"
        "- For IF true path: insert `DISPLAY '@@B:<id>:T'` after the IF line or before the first true-body statement.\n"
        "- For ELSE path: insert `DISPLAY '@@B:<id>:F'` immediately after the ELSE line.\n"
        "- For structured IF without ELSE: insert `ELSE` and `DISPLAY '@@B:<id>:F'` immediately before END-IF.\n"
        "- For period-delimited IF with no END-IF: insert TRUE probe only. Do not invent END-IF.\n"
        "- For EVALUATE: after each WHEN line insert `DISPLAY '@@B:<id>:W<n>'`, where <n> starts at 1 for that EVALUATE.\n"
        "- Use the same <id> for all directions belonging to one IF or one EVALUATE. Increment <id> for each new IF/EVALUATE.\n"
        "- Inserted lines should be valid fixed-format COBOL in Area B.\n"
        "- Keep every inserted line within columns 8-72.\n"
        "- If no safe probe insertion is possible, return {\"insertions\": []}.\n\n"
        f"Source (lines {start_line}-{end_line}):\n"
        f"```cobol\n{numbered_para}\n```"
    )


def _extract_json_object(text: str) -> dict | None:
    """Extract the first JSON object from a model response."""
    cleaned = _clean_llm_response(text).strip()
    if not cleaned:
        return None
    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    start = cleaned.find("{")
    if start == -1:
        return None
    depth = 0
    for idx in range(start, len(cleaned)):
        ch = cleaned[idx]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    parsed = json.loads(cleaned[start:idx + 1])
                    return parsed if isinstance(parsed, dict) else None
                except json.JSONDecodeError:
                    return None
    return None


def _normalize_inserted_line(content: str) -> str | None:
    """Normalize a proposed inserted COBOL line into fixed-format source."""
    stripped = content.strip()
    if not stripped:
        return None

    line = re.sub(r"^\s*\d+\s*:\s?", "", content.rstrip("\n"))
    if len(line) > 6 and line[6] in ("*", "/", "-", " "):
        candidate = line
    else:
        candidate = _AREA_B + stripped

    candidate = candidate.rstrip()
    if len(candidate) > 72:
        return None
    return candidate + "\n"


def _parse_insertion_plan(
    response: str,
    *,
    min_line: int,
    max_line: int,
) -> list[tuple[int, list[str]]]:
    """Parse an insertion-only probe plan from JSON response."""
    parsed = _extract_json_object(response)
    if not parsed:
        return []

    raw_insertions = parsed.get("insertions", [])
    if not isinstance(raw_insertions, list):
        return []

    result: list[tuple[int, list[str]]] = []
    for entry in raw_insertions:
        if not isinstance(entry, dict):
            continue
        try:
            after_line = int(entry.get("after_line"))
        except (TypeError, ValueError):
            continue
        if not (min_line <= after_line <= max_line):
            continue

        raw_lines = entry.get("lines", [])
        if isinstance(raw_lines, str):
            raw_lines = [raw_lines]
        if not isinstance(raw_lines, list):
            continue

        normalized_lines: list[str] = []
        for raw in raw_lines:
            if not isinstance(raw, str):
                continue
            normalized = _normalize_inserted_line(raw)
            if normalized:
                normalized_lines.append(normalized)
        if normalized_lines:
            result.append((after_line, normalized_lines))

    result.sort(key=lambda item: item[0])
    return result


def _apply_insertions(
    para_lines: list[str],
    start_line: int,
    insertions: list[tuple[int, list[str]]],
) -> list[str]:
    """Apply insertion plan while preserving all original paragraph lines exactly."""
    by_after_line: dict[int, list[str]] = {}
    for after_line, lines_to_insert in insertions:
        by_after_line.setdefault(after_line, []).extend(lines_to_insert)

    result: list[str] = []
    for idx, original in enumerate(para_lines):
        physical_line = start_line + idx + 1
        result.append(original)
        result.extend(by_after_line.get(physical_line, []))
    return result


def _collect_probe_info(
    lines: list[str],
    para_name: str,
) -> tuple[int, dict[str, dict], int]:
    """Collect probe count and metadata from instrumented paragraph lines."""
    probe_count = 0
    branch_meta: dict[str, dict] = {}
    max_branch_id = -1

    for line in lines:
        if len(line) > 6 and line[6] in ("*", "/"):
            continue
        matches = re.findall(r"@@B:(\d+):(T|F|W\d+)", line)
        for bid, direction in matches:
            probe_count += 1
            max_branch_id = max(max_branch_id, int(bid))
            branch_meta.setdefault(
                bid,
                {
                    "paragraph": para_name,
                    "type": "IF" if direction in ("T", "F") else "EVALUATE",
                },
            )

    return probe_count, branch_meta, max_branch_id + 1 if max_branch_id >= 0 else 0


def _truncate_syntax_feedback(stderr: str, max_lines: int = 12) -> str:
    """Trim compiler feedback to the most relevant lines for retry prompts."""
    lines = [ln for ln in stderr.splitlines() if ln.strip()]
    if not lines:
        return "(no compiler output provided)"
    return "\n".join(lines[:max_lines])


def _count_probes(lines: list[str]) -> int:
    """Count @@B: probes in a set of lines."""
    count = 0
    for line in lines:
        if "@@B:" in line and not (len(line) > 6 and line[6] in ("*", "/")):
            count += 1
    return count


def _syntax_check_details(lines: list[str], reference_path: Path) -> tuple[bool, str]:
    """Write lines to a temp file and run cobc syntax-only check."""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".cbl", delete=False,
            dir=str(reference_path.parent),
        ) as f:
            f.write("".join(lines))
            tmp_path = Path(f.name)

        cmd = [
            "cobc", "-fsyntax-only",
            "-std=ibm",
            "-frelax-syntax-checks",
            "-frelax-level-hierarchy",
            "-fmax-errors=10",
            str(tmp_path),
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=_SYNTAX_CHECK_TIMEOUT,
        )
        output = ((result.stderr or "") + "\n" + (result.stdout or "")).strip()
        return result.returncode == 0, output
    except (subprocess.TimeoutExpired, Exception) as e:
        log.debug("Syntax check error: %s", e)
        return False, str(e)
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass


def _syntax_check(lines: list[str], reference_path: Path) -> bool:
    """Compatibility wrapper for callers that only need success/failure."""
    ok, _ = _syntax_check_details(lines, reference_path)
    return ok
