"""Post-compilation LLM-guided branch probe insertion.

After a COBOL mock compiles successfully, this module inserts @@B:
branch probes one paragraph at a time. Each paragraph with IF or
EVALUATE is sent to the LLM, which returns a version with probes
inserted. A syntax check verifies each insertion — failures are
reverted so the program stays compilable.
"""

from __future__ import annotations

import logging
import re
import subprocess
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)

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

    Reads the mock.cbl, finds paragraphs in PROCEDURE DIVISION, and
    for each paragraph containing IF or EVALUATE, asks the LLM to
    insert branch probes.  Each insertion is verified with a syntax
    check — failures are reverted.

    Args:
        mock_cbl_path: Path to the instrumented .mock.cbl file.
        llm_provider: An LLM provider instance.
        llm_model: Optional model override.

    Returns:
        (probes_inserted, paragraphs_instrumented, branch_meta)
        branch_meta maps branch_id (str) to {paragraph, type}.
    """
    from .llm_coverage import _query_llm_sync

    source_text = mock_cbl_path.read_text(errors="replace")
    lines = source_text.splitlines(keepends=True)

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

        # Build prompt for LLM
        numbered_para = "\n".join(
            f"{start_line + i + 1:5d}: {line.rstrip()}"
            for i, line in enumerate(para_lines)
        )

        prompt = (
            "Insert @@B: branch coverage probes into this COBOL paragraph.\n\n"
            f"Starting branch ID: {branch_id}\n"
            f"Paragraph: {para_name}\n\n"
            "Rules:\n"
            "- After each IF condition (before first body statement), insert:\n"
            "           DISPLAY '@@B:<id>:T'\n"
            "  Increment <id> for each IF.\n"
            "- After each ELSE keyword, insert:\n"
            "           DISPLAY '@@B:<id>:F'\n"
            "  using the SAME <id> as the matching IF.\n"
            "- For structured IF without ELSE: add ELSE + DISPLAY '@@B:<id>:F' before END-IF.\n"
            "- For period-delimited IF (ends with period, no END-IF): insert TRUE probe only.\n"
            "- For EVALUATE: insert DISPLAY '@@B:<id>:W<n>' after each WHEN clause\n"
            "  (where <n> is the WHEN number starting from 1). Use same <id> for all\n"
            "  WHENs in one EVALUATE. Increment <id> for each EVALUATE.\n"
            "- NO period at end of DISPLAY statement.\n"
            "- All DISPLAY lines must fit within 72 characters (COBOL Area B).\n"
            "- Use column 12 (Area B) for DISPLAY statements.\n"
            "- Preserve all existing code exactly as-is. Only ADD DISPLAY lines.\n"
            "- Do NOT remove or modify any existing lines.\n\n"
            f"Source (lines {start_line + 1}-{end_line}):\n"
            f"```cobol\n{numbered_para}\n```\n\n"
            "Return ONLY the modified paragraph source code (no line numbers, no markdown,\n"
            "no explanation). Include ALL lines of the paragraph, both original and new.\n"
            "The output must be valid fixed-format COBOL (columns 1-72)."
        )

        try:
            response, _ = _query_llm_sync(llm_provider, prompt, llm_model)
        except Exception as e:
            log.warning("  LLM failed for paragraph %s: %s", para_name, e)
            continue

        # Clean response — strip markdown
        cleaned = _clean_llm_response(response)
        if not cleaned.strip():
            log.info("  Empty LLM response for paragraph %s, skipping", para_name)
            continue

        # Parse into lines
        new_para_lines = [
            ln + "\n" if not ln.endswith("\n") else ln
            for ln in cleaned.splitlines()
        ]

        # Count probes in the response
        probes_in_response = _count_probes(new_para_lines)
        if probes_in_response == 0:
            log.info("  No probes in LLM response for %s, skipping", para_name)
            continue

        # Try replacing paragraph and verify syntax
        trial_lines = list(lines)
        trial_lines[start_line:end_line] = new_para_lines

        # Write trial source to temp file and syntax-check
        if _syntax_check(trial_lines, mock_cbl_path):
            # Accept the instrumented paragraph
            lines[start_line:end_line] = new_para_lines

            # Update line offsets for subsequent paragraphs
            delta = len(new_para_lines) - (end_line - start_line)

            # Build branch metadata from the probes
            for pl in new_para_lines:
                m = re.search(r"@@B:(\d+):(T|F|W\d+)", pl)
                if m:
                    bid = m.group(1)
                    direction = m.group(2)
                    if bid not in branch_meta:
                        branch_meta[bid] = {
                            "paragraph": para_name,
                            "type": "IF" if direction in ("T", "F") else "EVALUATE",
                        }

            total_probes += probes_in_response
            total_instrumented += 1
            branch_id += probes_in_response

            log.info("  Instrumented %s: %d probes inserted", para_name, probes_in_response)

            # Re-find paragraphs since line numbers shifted
            # (We break and restart the loop to handle shifts cleanly)
            # Actually, we process paragraphs in order and the shift only
            # affects subsequent paragraphs. Update the remaining entries.
            # Since we already extracted paragraphs list, we need to
            # adjust the remaining paragraph ranges.
            remaining_paras_adjusted = []
            for pn, ps, pe in paragraphs:
                if ps > start_line:
                    remaining_paras_adjusted.append((pn, ps + delta, pe + delta))
                else:
                    remaining_paras_adjusted.append((pn, ps, pe))
            paragraphs[:] = remaining_paras_adjusted
        else:
            log.info("  Syntax check failed for %s, reverting", para_name)

    # Write final instrumented source
    if total_probes > 0:
        mock_cbl_path.write_text("".join(lines))
        log.info("Branch instrumentation complete: %d probes in %d paragraphs",
                 total_probes, total_instrumented)

    return total_probes, total_instrumented, branch_meta


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _count_probes(lines: list[str]) -> int:
    """Count @@B: probes in a set of lines."""
    count = 0
    for line in lines:
        if "@@B:" in line and not (len(line) > 6 and line[6] in ("*", "/")):
            count += 1
    return count


def _syntax_check(lines: list[str], reference_path: Path) -> bool:
    """Write lines to a temp file and run cobc syntax-only check.

    Returns True if the syntax check passes.
    """
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
        return result.returncode == 0
    except (subprocess.TimeoutExpired, Exception) as e:
        log.debug("Syntax check error: %s", e)
        return False
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
