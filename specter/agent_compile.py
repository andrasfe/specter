"""Agent-driven COBOL compilation with LLM error fixing.

A cleaner replacement for the complex compile_cobol() in cobol_mock.py.
Key differences:
- Groups ALL errors and sends each group to the LLM with 500 lines of context
- LLM sees the full error picture, not one error at a time
- Verifies each fix doesn't make things worse (reverts if error count increases)
- Wall-clock timeout (default 1800s), no retry count limit
- Caches verified fixes to cobol_fix_cache.json
"""

from __future__ import annotations

import hashlib
import logging
import re
import subprocess
import time
from pathlib import Path

log = logging.getLogger(__name__)

# Maximum consecutive passes with no improvement before rotating to a
# different error group.
_STALL_LIMIT = 5


def agent_compile(
    source_path: Path,
    output_path: Path | None = None,
    copybook_dirs: list[Path] | None = None,
    llm_provider=None,
    llm_model: str | None = None,
    wall_clock_timeout: float = 1800.0,
) -> tuple[bool, str]:
    """Compile COBOL source with agent-driven LLM error fixing.

    The agent sees ALL errors at once (grouped by proximity), gets a
    large chunk of the source around each group, and decides the fix
    strategy holistically.  Fixes are verified by recompiling — if
    error count increases the fix is reverted.

    Args:
        source_path: Path to the COBOL source file to compile.
        output_path: Path for the compiled executable.  Defaults to
            source_path without suffix.
        copybook_dirs: Directories to search for copybooks (-I flags).
        llm_provider: An LLM provider instance (from llm_providers).
            If None, only rule-based fixes are attempted.
        llm_model: Optional model override for the LLM provider.
        wall_clock_timeout: Maximum seconds to spend in the fix loop.

    Returns:
        (success, message) tuple.
    """
    source_path = Path(source_path)
    if output_path is None:
        output_path = source_path.with_suffix("")

    cmd = [
        "cobc", "-x",
        "-std=ibm",
        "-Wno-dialect",
        "-frelax-syntax-checks",
        "-frelax-level-hierarchy",
        "-fmax-errors=10000",
        "-o", str(output_path), str(source_path),
    ]
    if copybook_dirs:
        for d in copybook_dirs:
            cmd.extend(["-I", str(d)])

    # Initialize fix cache
    from .cobol_fix_cache import (
        CobolFixCache,
        parse_compilation_errors,
        _parse_llm_fix_response,
    )
    cache_path = source_path.parent / "cobol_fix_cache.json"
    cache = CobolFixCache(cache_path)

    deadline = time.monotonic() + wall_clock_timeout
    pass_number = 0
    stall_count = 0
    best_error_count = 999999
    best_source = source_path.read_text(errors="replace")
    last_stderr = ""
    current_group_idx = 0  # which error group to focus on
    failed_fix_hashes: set[str] = set()

    while time.monotonic() < deadline:
        # --- Compile ---
        remaining = max(60, deadline - time.monotonic())
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=remaining,
            )
        except subprocess.TimeoutExpired:
            cache.save()
            return False, "Compilation timed out"
        except Exception as e:
            cache.save()
            return False, f"Compilation error: {e}"

        last_stderr = result.stderr or ""

        # --- Check success ---
        if result.returncode == 0:
            cache.save()
            msg = f"Compiled: {output_path}"
            if pass_number > 0:
                msg += f" (after {pass_number} fix passes)"
            return True, msg

        # --- Parse errors ---
        src_name = source_path.name
        errors = parse_compilation_errors(last_stderr, src_name)
        if not errors:
            cache.save()
            return False, f"Compilation failed (no parseable errors):\n{last_stderr}"

        n_errors = len(errors)
        log.info("=== Agent pass %d: %d errors (best=%d, stall=%d) ===",
                 pass_number + 1, n_errors, best_error_count, stall_count)

        # --- Track progress ---
        if n_errors < best_error_count:
            best_error_count = n_errors
            best_source = source_path.read_text(errors="replace")
            stall_count = 0
            current_group_idx = 0
        else:
            stall_count += 1

        # --- Stall: rotate to different error group ---
        if stall_count >= _STALL_LIMIT:
            current_group_idx += 1
            stall_count = 0
            log.info("  Stalled — rotating to error group %d", current_group_idx)

        # --- Group errors by proximity (within 50 lines of each other) ---
        groups = _group_errors(errors, max_gap=50)

        if not groups:
            cache.save()
            return False, f"Compilation failed with {n_errors} errors:\n{last_stderr}"

        # Pick which group to work on
        group_idx = current_group_idx % len(groups)
        src_lines = source_path.read_text(errors="replace").splitlines(keepends=True)

        # --- Try to fix each group ---
        any_fixed = False
        groups_to_try = [groups[group_idx]] + [g for i, g in enumerate(groups) if i != group_idx]

        for group in groups_to_try:
            if time.monotonic() >= deadline:
                break

            # Extract context: 500 lines before first error to 10 lines after last
            first_line = group[0][0]
            last_line = group[-1][0]
            ctx_start = max(0, first_line - 501)
            ctx_end = min(len(src_lines), last_line + 10)

            # Try rule-based fixes first (fast, no LLM call)
            rule_fixes = _apply_rule_fixes(group, src_lines)
            if rule_fixes:
                snapshot = list(src_lines)
                for fix_ln, fix_content in rule_fixes.items():
                    idx = fix_ln - 1
                    if 0 <= idx < len(src_lines):
                        src_lines[idx] = fix_content
                source_path.write_text("".join(src_lines))

                # Verify
                try:
                    verify = subprocess.run(
                        cmd, capture_output=True, text=True, timeout=120,
                    )
                    new_errors = parse_compilation_errors(
                        verify.stderr or "", src_name,
                    ) if verify.returncode != 0 else []
                except (subprocess.TimeoutExpired, Exception):
                    new_errors = errors  # treat as no improvement

                if len(new_errors) < n_errors:
                    any_fixed = True
                    for fix_ln in rule_fixes:
                        idx = fix_ln - 1
                        if 0 <= idx < len(src_lines):
                            err_msg = _find_error_for_line(group, fix_ln)
                            if err_msg:
                                ws = max(0, idx - 5)
                                we = min(len(snapshot), idx + 6)
                                cache.record(
                                    err_msg, list(snapshot[ws:we]),
                                    list(src_lines[ws:we]),
                                    source="rule", verified=True,
                                )
                    log.info("  Rule fix accepted: %d -> %d errors",
                             n_errors, len(new_errors))
                    if verify.returncode == 0:
                        cache.save()
                        msg = f"Compiled: {output_path} (after {pass_number + 1} fix passes)"
                        return True, msg
                    break  # recompile from top
                else:
                    # Revert
                    src_lines[:] = snapshot
                    source_path.write_text("".join(src_lines))

            # Try LLM fix
            if not llm_provider:
                continue

            context_lines = src_lines[ctx_start:ctx_end]
            numbered_context = "\n".join(
                f"{ctx_start + i + 1:5d}: {line.rstrip()}"
                for i, line in enumerate(context_lines)
            )
            error_desc = "\n".join(
                f"  Line {ln}: {msg}" for ln, msg in group
            )

            # Detect section
            section = "DATA DIVISION"
            for i in range(min(ctx_start, len(src_lines))):
                if "PROCEDURE DIVISION" in src_lines[i].upper():
                    section = "PROCEDURE DIVISION"
                    break

            prompt = (
                "You are fixing GnuCOBOL compilation errors in an instrumented COBOL mock.\n"
                "The original code compiles on IBM mainframes but GnuCOBOL (-std=ibm) is stricter.\n\n"
                f"File: {src_name} ({len(src_lines)} lines total)\n"
                f"Section: {section}\n"
                f"Total errors in file: {n_errors}\n"
                f"Errors in this group ({len(group)}):\n{error_desc}\n\n"
                f"Source context (lines {ctx_start + 1}-{ctx_end}):\n"
                f"```cobol\n{numbered_context}\n```\n\n"
                "Common fixes:\n"
                "- 'X is not defined': add '       01 X PIC X(256).' to WORKING-STORAGE\n"
                "- 'duplicate FD/SELECT': comment the duplicate with * in column 7\n"
                "- 'PICTURE clause required': add appropriate PIC clause\n"
                "- 'unexpected ELSE/END-IF': fix IF nesting or add missing IF\n"
                "- VALUES ARE -> VALUE\n"
                "- Missing terminal period on data definition\n"
                "- Don't comment out data definitions that other code references\n\n"
                "Output ONLY the corrected lines as a flat JSON object mapping line number to fixed content.\n"
                'Example: {"5417": "       10  EXT-K1-WS  PIC 99.", "5418": "       10  EXT-K2-WS  PIC 99."}\n'
                "Do NOT wrap in outer keys. Do NOT add explanations.\n"
                "Only include lines that changed. Preserve COBOL column formatting (cols 7-72)."
            )

            try:
                from .llm_coverage import _query_llm_sync
                response, _ = _query_llm_sync(llm_provider, prompt, llm_model)
            except Exception as e:
                log.warning("  LLM query failed: %s", e)
                continue

            # Parse response
            fixes = _parse_llm_fix_response(response, ctx_start, ctx_end)
            if not fixes:
                snippet = response[:200].replace("\n", "\\n") if response else "(empty)"
                log.info("  LLM response not parsed: %s", snippet)
                continue

            # Compute fix hash to avoid retrying known-bad fixes
            fix_hash = hashlib.sha256(
                str(sorted(fixes.items())).encode()
            ).hexdigest()[:16]
            if fix_hash in failed_fix_hashes:
                log.info("  Skipping known-bad fix (hash %s)", fix_hash)
                continue

            # Apply fixes
            snapshot = list(src_lines)
            for fix_ln, fix_content in fixes.items():
                idx = fix_ln - 1
                if 0 <= idx < len(src_lines):
                    src_lines[idx] = fix_content

            source_path.write_text("".join(src_lines))

            # Verify
            try:
                verify = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=120,
                )
                new_errors = parse_compilation_errors(
                    verify.stderr or "", src_name,
                ) if verify.returncode != 0 else []
            except (subprocess.TimeoutExpired, Exception):
                new_errors = errors

            new_count = len(new_errors)

            if verify.returncode == 0:
                # Cache all fixes as verified
                for fix_ln, fix_content in fixes.items():
                    idx = fix_ln - 1
                    err_msg = _find_error_for_line(group, fix_ln)
                    if err_msg and 0 <= idx < len(snapshot):
                        ws = max(0, idx - 5)
                        we = min(len(snapshot), idx + 6)
                        cache.record(
                            err_msg, list(snapshot[ws:we]),
                            list(src_lines[ws:we]),
                            source="llm", model=llm_model or "",
                            verified=True,
                        )
                cache.save()
                return True, f"Compiled: {output_path} (after {pass_number + 1} fix passes)"

            if new_count < n_errors:
                any_fixed = True
                # Cache as pending
                for fix_ln, fix_content in fixes.items():
                    idx = fix_ln - 1
                    err_msg = _find_error_for_line(group, fix_ln)
                    if err_msg and 0 <= idx < len(snapshot):
                        ws = max(0, idx - 5)
                        we = min(len(snapshot), idx + 6)
                        cache.record(
                            err_msg, list(snapshot[ws:we]),
                            list(src_lines[ws:we]),
                            source="llm", model=llm_model or "",
                            verified=False,
                        )
                log.info("  LLM fix accepted: %d -> %d errors (%d lines changed)",
                         n_errors, new_count, len(fixes))
                break  # recompile from top
            else:
                # Revert
                failed_fix_hashes.add(fix_hash)
                src_lines[:] = snapshot
                source_path.write_text("".join(src_lines))
                log.info("  LLM fix reverted: %d -> %d errors", n_errors, new_count)

        if not any_fixed and not llm_provider:
            # No LLM and rule fixes didn't help — no point continuing
            cache.save()
            return False, (
                f"Compilation failed with {n_errors} errors "
                f"(no LLM provider for fixes):\n{last_stderr}"
            )

        pass_number += 1

    cache.save()
    return False, (
        f"Compilation timed out after {pass_number} passes "
        f"({best_error_count} best errors):\n{last_stderr}"
    )


# ---------------------------------------------------------------------------
# Error grouping
# ---------------------------------------------------------------------------

def _group_errors(
    errors: list[tuple[int, str]], max_gap: int = 50,
) -> list[list[tuple[int, str]]]:
    """Group errors by proximity — errors within max_gap lines of each other.

    Returns a list of groups, each group is a list of (lineno, msg) tuples.
    """
    if not errors:
        return []

    sorted_errors = sorted(errors, key=lambda e: e[0])
    groups: list[list[tuple[int, str]]] = []
    current: list[tuple[int, str]] = [sorted_errors[0]]

    for lineno, msg in sorted_errors[1:]:
        if lineno - current[-1][0] <= max_gap:
            current.append((lineno, msg))
        else:
            groups.append(current)
            current = [(lineno, msg)]
    groups.append(current)

    return groups


# ---------------------------------------------------------------------------
# Rule-based fixes (fast, no LLM)
# ---------------------------------------------------------------------------

def _apply_rule_fixes(
    group: list[tuple[int, str]],
    src_lines: list[str],
) -> dict[int, str]:
    """Apply deterministic rule-based fixes for common errors.

    Returns {lineno: fixed_content} for lines that were changed.
    """
    fixes: dict[int, str] = {}

    for lineno, error_msg in group:
        idx = lineno - 1
        if idx < 0 or idx >= len(src_lines):
            continue
        ln = src_lines[idx]

        # VALUES ARE -> VALUE
        if "VALUES ARE" in ln.upper() or "VALUES IS" in ln.upper():
            fixed = re.sub(r"\bVALUES\s+ARE\b", "VALUE", ln, flags=re.IGNORECASE)
            fixed = re.sub(r"\bVALUES\s+IS\b", "VALUE", fixed, flags=re.IGNORECASE)
            if fixed != ln:
                fixes[lineno] = fixed
                continue

        # P.I.C. -> PIC
        if "P.I.C." in ln:
            fixes[lineno] = ln.replace("P.I.C.", "PIC")
            continue

        # IBM compiler directives
        if len(ln) > 6 and ln[6] not in ("*", "/"):
            content = ln[6:72].strip().upper() if len(ln) > 6 else ln.strip().upper()
            if content in ("EJECT", "EJECT.", "SKIP1", "SKIP1.",
                           "SKIP2", "SKIP2.", "SKIP3", "SKIP3."):
                fixes[lineno] = ln[:6] + "*" + ln[7:]
                continue
            if content.startswith("SERVICE RELOAD") or content.startswith("SERVICE LABEL"):
                fixes[lineno] = ln[:6] + "*" + ln[7:]
                continue

    return fixes


def _find_error_for_line(
    group: list[tuple[int, str]], lineno: int,
) -> str | None:
    """Find the error message for a given line number in a group."""
    for ln, msg in group:
        if ln == lineno:
            return msg
    # Return the nearest error message
    if group:
        return group[0][1]
    return None
