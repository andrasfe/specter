"""Instrument COBOL source for standalone execution with mocked externals.

Takes a COBOL source file and produces a modified version that:
1. Replaces EXEC CICS/SQL/DLI blocks with mock reads from a sequential file
2. Replaces file I/O verbs (READ/WRITE/OPEN/CLOSE) with mock reads
3. Replaces CALL statements with mock reads
4. Adds DISPLAY tracing at each paragraph entry
5. Converts LINKAGE SECTION to WORKING-STORAGE
6. Makes the program compilable with GnuCOBOL as a standalone batch program
7. Resolves COPY statements from provided copybook directories

Mock data file format (line-sequential, 80 chars/record):
  Cols 1-30:  operation key (e.g., 'CICS-READ', 'SQL', 'DLI-GU')
  Cols 31-50: alphanumeric status value
  Cols 51-80: reserved / numeric status value

The mock file is read sequentially — one record per external operation
in execution order, matching _apply_stub_outcome's FIFO semantics.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

# Fixed-format COBOL column constants
_SEQ = "      "        # Cols 1-6: sequence area
_A = "       "         # Cols 1-7: area A start (col 8)
_B = "           "     # Cols 1-11: area B start (col 12)
_CONT = "              "  # Continuation indent (col 15)
_CMT = "      *"       # Comment line prefix (col 7 = *)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class MockConfig:
    """Configuration for COBOL instrumentation."""
    copybook_dirs: list[Path] = field(default_factory=list)
    trace_paragraphs: bool = True
    mock_file_name: str = "MOCKFILE"
    mock_dd_name: str = "MOCKDATA"
    stop_on_exec_return: bool = True  # EXEC CICS RETURN → STOP RUN
    stop_on_exec_xctl: bool = True   # EXEC CICS XCTL → STOP RUN
    initial_values: dict[str, str] = field(default_factory=dict)  # var→value MOVEs after OPEN


@dataclass
class InstrumentResult:
    """Result of COBOL instrumentation."""
    source: str               # Modified COBOL source
    original_path: Path
    exec_blocks_replaced: int
    io_verbs_replaced: int
    call_stmts_replaced: int
    paragraphs_traced: int
    copy_resolved: int
    copy_stubbed: int
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def instrument_cobol(
    source_path: str | Path,
    config: MockConfig | None = None,
) -> InstrumentResult:
    """Instrument a COBOL source file for standalone mock execution.

    Args:
        source_path: Path to the COBOL source file.
        config: Optional configuration. Defaults to auto-detected settings.

    Returns:
        InstrumentResult with the modified source and statistics.
    """
    source_path = Path(source_path)
    if config is None:
        config = MockConfig()
        # Auto-detect copybook dirs relative to source
        parent = source_path.parent
        for candidate in ["../cpy", "../cpy-bms", "../copy", "."]:
            cp = (parent / candidate).resolve()
            if cp.is_dir():
                config.copybook_dirs.append(cp)

    original = source_path.read_text(errors="replace")
    lines = original.splitlines(keepends=True)

    stats = {
        "exec_replaced": 0,
        "io_replaced": 0,
        "call_replaced": 0,
        "paras_traced": 0,
        "copy_resolved": 0,
        "copy_stubbed": 0,
    }
    warnings: list[str] = []

    # Phase 1: Resolve COPY statements
    lines, stats["copy_resolved"], stats["copy_stubbed"], copy_warns = (
        _resolve_copies(lines, config.copybook_dirs)
    )
    warnings.extend(copy_warns)

    # Phase 2: Identify divisions and sections
    divisions = _find_divisions(lines)

    # Phase 3: Replace EXEC blocks
    lines, stats["exec_replaced"] = _replace_exec_blocks(lines, config)

    # Phase 4: Replace file I/O verbs
    lines, stats["io_replaced"] = _replace_io_verbs(lines)

    # Phase 5: Replace CALL statements
    lines, stats["call_replaced"] = _replace_call_stmts(lines)

    # Phase 6: Add paragraph tracing
    if config.trace_paragraphs:
        lines, stats["paras_traced"] = _add_paragraph_tracing(lines)

    # Phase 7: Add mock infrastructure (WS entries, file control, FD)
    lines = _add_mock_infrastructure(lines, divisions, config)

    # Phase 8: Convert LINKAGE to WORKING-STORAGE
    lines = _convert_linkage(lines)

    # Phase 9: Fix PROCEDURE DIVISION header
    lines = _fix_procedure_division(lines)

    # Phase 10: Add mock file open/close around main logic
    lines = _add_mock_file_handling(lines, config)

    # Phase 11: Add common stub definitions (DFHAID, DFHBMSCA, DFHRESP)
    lines = _add_common_stubs(lines)

    result_source = "".join(lines)

    return InstrumentResult(
        source=result_source,
        original_path=source_path,
        exec_blocks_replaced=stats["exec_replaced"],
        io_verbs_replaced=stats["io_replaced"],
        call_stmts_replaced=stats["call_replaced"],
        paragraphs_traced=stats["paras_traced"],
        copy_resolved=stats["copy_resolved"],
        copy_stubbed=stats["copy_stubbed"],
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Phase 1: COPY resolution
# ---------------------------------------------------------------------------

def _resolve_copies(
    lines: list[str],
    copybook_dirs: list[Path],
) -> tuple[list[str], int, int, list[str]]:
    """Resolve COPY statements by inlining copybook content."""
    copy_re = re.compile(
        r"^(\s{6}\s+)COPY\s+'?([A-Za-z0-9_-]+)'?\s*\.?\s*$",
        re.IGNORECASE,
    )
    resolved = 0
    stubbed = 0
    warnings = []
    result: list[str] = []
    seen_copies: set[str] = set()

    for line in lines:
        m = copy_re.match(line.rstrip("\n\r"))
        if not m:
            result.append(line)
            continue

        indent = m.group(1)
        copyname = m.group(2).upper()

        if copyname in seen_copies:
            # Already inlined — skip duplicate COPY
            result.append(f"      * SPECTER: COPY {copyname} (already inlined).\n")
            continue

        # Search for copybook file
        found = _find_copybook(copyname, copybook_dirs)
        if found:
            seen_copies.add(copyname)
            result.append(f"      * SPECTER: COPY {copyname} inlined from {found.name}\n")
            copy_lines = found.read_text(errors="replace").splitlines(keepends=True)
            for cl in copy_lines:
                result.append(cl if cl.endswith("\n") else cl + "\n")
            resolved += 1
        else:
            # Generate stub — comment out the COPY
            seen_copies.add(copyname)
            result.append(f"      * SPECTER: COPY {copyname} (not found)\n")
            stubbed += 1
            warnings.append(f"Copybook not found: {copyname}")

    return result, resolved, stubbed, warnings


def _find_copybook(name: str, dirs: list[Path]) -> Path | None:
    """Search for a copybook file in the given directories."""
    # Try various extensions and case combinations
    candidates = [
        name, name.lower(), name.upper(),
        name + ".cpy", name.lower() + ".cpy", name.upper() + ".cpy",
        name + ".CPY", name.lower() + ".CPY", name.upper() + ".CPY",
        name + ".cbl", name.lower() + ".cbl", name.upper() + ".cbl",
        name + ".CBL",
    ]
    for d in dirs:
        for c in candidates:
            p = d / c
            if p.is_file():
                return p
    return None


# ---------------------------------------------------------------------------
# Phase 2: Find divisions
# ---------------------------------------------------------------------------

def _find_divisions(lines: list[str]) -> dict[str, int]:
    """Find line numbers of major COBOL divisions and sections."""
    divisions: dict[str, int] = {}
    for i, line in enumerate(lines):
        upper = line.upper().strip()
        if "IDENTIFICATION DIVISION" in upper:
            divisions["identification"] = i
        elif "ENVIRONMENT DIVISION" in upper:
            divisions["environment"] = i
        elif "DATA DIVISION" in upper:
            divisions["data"] = i
        elif "WORKING-STORAGE SECTION" in upper:
            divisions["working-storage"] = i
        elif "FILE SECTION" in upper:
            divisions["file-section"] = i
        elif "LINKAGE SECTION" in upper:
            divisions["linkage"] = i
        elif "PROCEDURE DIVISION" in upper:
            divisions["procedure"] = i
        elif re.match(r"\s*FILE-CONTROL\.", upper):
            divisions["file-control"] = i
        elif "CONFIGURATION SECTION" in upper:
            divisions["configuration"] = i
        elif "INPUT-OUTPUT SECTION" in upper:
            divisions["input-output"] = i
    return divisions


# ---------------------------------------------------------------------------
# Phase 3: Replace EXEC blocks
# ---------------------------------------------------------------------------

def _replace_exec_blocks(
    lines: list[str],
    config: MockConfig,
) -> tuple[list[str], int]:
    """Replace EXEC CICS/SQL/DLI ... END-EXEC with mock reads."""
    result: list[str] = []
    count = 0
    i = 0

    while i < len(lines):
        line = lines[i]
        upper = _get_cobol_content(line).upper().strip()

        # Detect start of EXEC block
        if re.search(r"\bEXEC\s+(CICS|SQL|DLI)\b", upper):
            # Collect the entire EXEC ... END-EXEC block
            block_lines = [line]
            block_text = upper
            j = i + 1
            while j < len(lines) and "END-EXEC" not in block_text:
                block_lines.append(lines[j])
                block_text += " " + _get_cobol_content(lines[j]).upper().strip()
                j += 1

            # Check if block ended with period (END-EXEC.)
            has_period = block_text.rstrip().endswith(".")

            # Parse the block
            indent = "      "  # standard area B
            mock_code = _generate_exec_mock(block_text, indent, config,
                                            has_period=has_period)

            # Comment out original and insert mock
            for bl in block_lines:
                result.append(_comment_line(bl))
            for mc in mock_code:
                result.append(mc)

            count += 1
            i = j
        else:
            result.append(line)
            i += 1

    return result, count


def _generate_exec_mock(
    block_text: str,
    indent: str,
    config: MockConfig,
    has_period: bool = False,
) -> list[str]:
    """Generate mock COBOL code for an EXEC block."""
    mock_lines = []
    ind = indent + "    "  # area B indent

    # Determine EXEC type
    if "EXEC CICS" in block_text:
        return _mock_cics(block_text, ind, config, has_period=has_period)
    elif "EXEC SQL" in block_text:
        return _mock_sql(block_text, ind, has_period=has_period)
    elif "EXEC DLI" in block_text:
        return _mock_dli(block_text, ind, has_period=has_period)
    else:
        mock_lines.append(f"{ind}CONTINUE\n")
    return mock_lines


def _mock_cics(
    block_text: str, ind: str, config: MockConfig,
    has_period: bool = False,
) -> list[str]:
    """Generate mock for EXEC CICS block."""
    lines = []
    # Use period only when original END-EXEC had one (preserves sentence scope)
    dot = "." if has_period else ""

    # Extract RESP variable if present
    resp_match = re.search(r"RESP\s*\(\s*([A-Z0-9_-]+)\s*\)", block_text)
    resp_var = resp_match.group(1) if resp_match else None
    resp2_match = re.search(r"RESP2\s*\(\s*([A-Z0-9_-]+)\s*\)", block_text)
    resp2_var = resp2_match.group(1) if resp2_match else None

    # Determine CICS operation
    if re.search(r"\bRETURN\b", block_text):
        if config.stop_on_exec_return:
            lines.append(f"{_B}DISPLAY 'SPECTER-CICS:RETURN'\n")
            lines.append(f"{_B}GO TO SPECTER-EXIT-PARA{dot}\n")
            return lines
    elif re.search(r"\bXCTL\b", block_text):
        prog_match = re.search(r"PROGRAM\s*\(\s*([^)]+)\s*\)", block_text)
        prog = prog_match.group(1).strip() if prog_match else "?"
        if config.stop_on_exec_xctl:
            lines.append(f"{_B}DISPLAY 'SPECTER-CICS:XCTL:{prog}'\n")
            lines.append(f"{_B}GO TO SPECTER-EXIT-PARA{dot}\n")
            return lines
    elif re.search(r"\bSYNCPOINT\b", block_text):
        lines.append(f"{_B}DISPLAY 'SPECTER-CICS:SYNCPOINT'\n")
        lines.append(f"{_B}CONTINUE\n")
        return lines

    # For READ, SEND, RECEIVE, WRITE, DELETE, etc:
    op = "CICS"
    for verb in ["READ", "WRITE", "SEND", "RECEIVE", "DELETE",
                  "STARTBR", "READNEXT", "READPREV", "ENDBR",
                  "LINK", "START", "INQUIRE", "WRITEQ", "READQ",
                  "DELETEQ", "UNLOCK"]:
        if re.search(rf"\b{verb}\b", block_text):
            op = f"CICS-{verb}"
            break

    lines.append(f"{_B}DISPLAY 'SPECTER-MOCK:{op}'\n")
    lines.append(f"{_B}READ MOCK-FILE INTO MOCK-RECORD\n")
    lines.append(f"{_CONT}AT END\n")
    lines.append(f"{_CONT}  MOVE '00' TO MOCK-ALPHA-STATUS\n")
    lines.append(f"{_CONT}  MOVE 0 TO MOCK-NUM-STATUS\n")
    lines.append(f"{_B}END-READ\n")

    if resp_var:
        lines.append(f"{_B}MOVE MOCK-NUM-STATUS TO {resp_var}\n")
    if resp2_var:
        lines.append(f"{_B}MOVE 0 TO {resp2_var}{dot}\n")
    elif resp_var:
        # Add period to last MOVE if needed
        lines[-1] = lines[-1].rstrip("\n") + dot + "\n" if dot else lines[-1]
    elif dot:
        # No RESP vars — add period to END-READ
        lines[-1] = lines[-1].rstrip("\n").rstrip() + dot + "\n"

    return lines


def _mock_sql(block_text: str, ind: str, has_period: bool = False) -> list[str]:
    """Generate mock for EXEC SQL block."""
    lines = []
    dot = "." if has_period else ""

    op = "SQL"
    for verb in ["SELECT", "INSERT", "UPDATE", "DELETE", "OPEN",
                  "CLOSE", "FETCH", "DECLARE", "PREPARE", "EXECUTE",
                  "INCLUDE", "COMMIT", "ROLLBACK"]:
        if re.search(rf"\b{verb}\b", block_text):
            op = f"SQL-{verb}"
            break

    # DECLARE and INCLUDE are compile-time — no mock needed
    if op in ("SQL-DECLARE", "SQL-INCLUDE"):
        lines.append(f"{_B}CONTINUE{dot}\n")
        return lines

    lines.append(f"{_B}DISPLAY 'SPECTER-MOCK:{op}'\n")
    lines.append(f"{_B}READ MOCK-FILE INTO MOCK-RECORD\n")
    lines.append(f"{_CONT}AT END\n")
    lines.append(f"{_CONT}  MOVE '00' TO MOCK-ALPHA-STATUS\n")
    lines.append(f"{_CONT}  MOVE 0 TO MOCK-NUM-STATUS\n")
    lines.append(f"{_B}END-READ\n")
    lines.append(f"{_B}MOVE MOCK-NUM-STATUS TO SQLCODE{dot}\n")

    return lines


def _mock_dli(block_text: str, ind: str, has_period: bool = False) -> list[str]:
    """Generate mock for EXEC DLI block."""
    lines = []
    dot = "." if has_period else ""

    op = "DLI"
    for verb in ["GU", "GN", "GNP", "GHU", "GHN", "GHNP",
                  "ISRT", "DLET", "REPL", "SCHD", "TERM"]:
        if re.search(rf"\b{verb}\b", block_text):
            op = f"DLI-{verb}"
            break

    if op == "DLI-TERM":
        lines.append(f"{_B}DISPLAY 'SPECTER-MOCK:DLI-TERM'\n")
        lines.append(f"{_B}CONTINUE{dot}\n")
        return lines

    lines.append(f"{_B}DISPLAY 'SPECTER-MOCK:{op}'\n")
    lines.append(f"{_B}READ MOCK-FILE INTO MOCK-RECORD\n")
    lines.append(f"{_CONT}AT END\n")
    lines.append(f"{_CONT}  MOVE '  ' TO MOCK-ALPHA-STATUS\n")
    lines.append(f"{_CONT}  MOVE 0 TO MOCK-NUM-STATUS\n")
    lines.append(f"{_B}END-READ\n")
    lines.append(f"{_B}MOVE MOCK-ALPHA-STATUS TO DIBSTAT{dot}\n")

    return lines


# ---------------------------------------------------------------------------
# Phase 4: Replace file I/O verbs
# ---------------------------------------------------------------------------

def _replace_io_verbs(lines: list[str]) -> tuple[list[str], int]:
    """Replace standalone READ/WRITE/OPEN/CLOSE/START/DELETE with mocks."""
    result: list[str] = []
    count = 0
    # Match standalone file I/O at area B (not inside EXEC blocks)
    io_re = re.compile(
        r"^(\s{6}\s+)(READ|WRITE|REWRITE|OPEN|CLOSE|START|DELETE)"
        r"\s+([A-Z0-9_-]+)",
        re.IGNORECASE,
    )

    i = 0
    while i < len(lines):
        line = lines[i]
        content = _get_cobol_content(line)
        m = io_re.match(line)

        # Skip if this is inside an already-commented block or EXEC
        if m and not content.strip().startswith("*"):
            ind = m.group(1)
            verb = m.group(2).upper()
            target = m.group(3).upper()
            # Skip our own mock reads
            if target == "MOCK-FILE":
                result.append(line)
                i += 1
                continue
            op_key = f"{verb}:{target}"

            # Collect continuation lines (until end-of-statement or new verb)
            block = [line]
            j = i + 1
            # Track if we're inside a scope-terminated block
            # (INVALID KEY / AT END / NOT ... => must find END-READ etc.)
            end_verb = f"END-{verb}"
            needs_end_verb = False
            # Check if the first line itself ends with a period
            first_ended = content.strip().rstrip().endswith(".")
            while j < len(lines) and not first_ended:
                next_content = _get_cobol_content(lines[j]).strip()
                if not next_content or next_content.startswith("*"):
                    block.append(lines[j])
                    j += 1
                    continue
                upper_next = next_content.upper()
                # Track if we entered a scoped clause
                if re.match(r"^(INVALID|AT\s+END|NOT\s+INVALID|NOT\s+AT)",
                            upper_next, re.IGNORECASE):
                    needs_end_verb = True
                # If inside a scoped clause, collect everything until END-verb
                if needs_end_verb:
                    block.append(lines[j])
                    if upper_next.startswith(end_verb):
                        j += 1
                        break
                    j += 1
                    continue
                # Check if this is a new statement (not a known continuation)
                if re.match(r"^[A-Z]", next_content) and not re.match(
                    r"^(AT|END-READ|END-WRITE|END-START|END-DELETE"
                    r"|INTO|FROM|INVALID|NOT|GIVING|STATUS|KEY|RECORD)",
                    next_content, re.IGNORECASE
                ):
                    break
                block.append(lines[j])
                # Check for end-of-statement period at end of line
                if next_content.rstrip().endswith("."):
                    j += 1
                    break
                j += 1

            # Comment out original
            for bl in block:
                result.append(_comment_line(bl))

            # Insert mock
            result.append(f"{_B}DISPLAY 'SPECTER-MOCK:{op_key}'\n")
            result.append(f"{_B}READ MOCK-FILE INTO MOCK-RECORD\n")
            result.append(f"{_CONT}AT END\n")
            result.append(f"{_CONT}  MOVE '00' TO MOCK-ALPHA-STATUS\n")
            result.append(f"{_CONT}  MOVE 0 TO MOCK-NUM-STATUS\n")
            result.append(f"{_B}END-READ\n")
            result.append(
                f"{_B}DISPLAY 'SPECTER-STATUS:' MOCK-ALPHA-STATUS\n"
            )

            count += 1
            i = j
        else:
            result.append(line)
            i += 1

    return result, count


# ---------------------------------------------------------------------------
# Phase 5: Replace CALL statements
# ---------------------------------------------------------------------------

def _replace_call_stmts(lines: list[str]) -> tuple[list[str], int]:
    """Replace CALL 'program' USING ... with mock reads."""
    result: list[str] = []
    count = 0
    call_re = re.compile(
        r"^(\s{6}\s+)CALL\s+'([^']+)'",
        re.IGNORECASE,
    )

    i = 0
    while i < len(lines):
        line = lines[i]
        content = _get_cobol_content(line)
        m = call_re.match(line)

        if m and not content.strip().startswith("*"):
            ind = m.group(1)
            prog = m.group(2).upper()

            # Collect CALL continuation lines (USING arguments)
            block = [line]
            j = i + 1
            while j < len(lines):
                next_content = _get_cobol_content(lines[j]).strip()
                # Stop at blank lines, comments, or new statements
                if not next_content or next_content.startswith("*"):
                    break
                # A new COBOL verb/statement means end of CALL
                if re.match(
                    r"^(IF|ELSE|END-IF|MOVE|PERFORM|EVALUATE|DISPLAY"
                    r"|ADD|SUBTRACT|COMPUTE|GO|READ|WRITE|OPEN|CLOSE"
                    r"|CALL|EXEC|SET|INITIALIZE|STRING|UNSTRING|INSPECT"
                    r"|ACCEPT|STOP|GOBACK|EXIT|CONTINUE|SEARCH)\b",
                    next_content, re.IGNORECASE
                ):
                    break
                # Check for end-of-statement period at end of line
                if next_content.rstrip().endswith("."):
                    block.append(lines[j])
                    j += 1
                    break
                block.append(lines[j])
                j += 1

            # Check if block ends with a period (sentence terminator)
            block_text = "".join(
                _get_cobol_content(bl) for bl in block
            ).strip()
            has_period = block_text.endswith(".")
            dot = "." if has_period else ""

            for bl in block:
                result.append(_comment_line(bl))

            result.append(f"{_B}DISPLAY 'SPECTER-MOCK:CALL:{prog}'\n")
            result.append(f"{_B}READ MOCK-FILE INTO MOCK-RECORD\n")
            result.append(f"{_CONT}AT END\n")
            result.append(f"{_CONT}  MOVE 0 TO MOCK-NUM-STATUS\n")
            result.append(f"{_B}END-READ\n")
            result.append(f"{_B}MOVE MOCK-NUM-STATUS TO RETURN-CODE{dot}\n")

            count += 1
            i = j
        else:
            result.append(line)
            i += 1

    return result, count


# ---------------------------------------------------------------------------
# Phase 6: Paragraph tracing
# ---------------------------------------------------------------------------

def _add_paragraph_tracing(lines: list[str]) -> tuple[list[str], int]:
    """Add DISPLAY tracing at paragraph entry points."""
    result: list[str] = []
    count = 0
    in_procedure = False

    # Paragraph: starts in area A (col 8-11), ends with period
    para_re = re.compile(
        r"^(\s{7})([A-Z0-9][A-Z0-9_-]*)\s*\.\s*$",
        re.IGNORECASE,
    )

    for line in lines:
        upper = line.upper().strip()
        if "PROCEDURE DIVISION" in upper:
            in_procedure = True

        result.append(line)

        if in_procedure:
            m = para_re.match(line)
            if m:
                para_name = m.group(2).upper()
                # Skip section headers
                if para_name.endswith("-SECTION"):
                    continue
                result.append(
                    f"{_B}DISPLAY 'SPECTER-TRACE:{para_name}'\n"
                )
                count += 1

    return result, count


# ---------------------------------------------------------------------------
# Phase 7: Add mock infrastructure
# ---------------------------------------------------------------------------

def _add_mock_infrastructure(
    lines: list[str],
    divisions: dict[str, int],
    config: MockConfig,
) -> list[str]:
    """Add WORKING-STORAGE entries and FILE-CONTROL for mock file."""
    result = list(lines)

    # Re-scan for current division positions (earlier phases may have shifted lines)
    divisions = _find_divisions(result)

    # --- Add to WORKING-STORAGE ---
    ws_entries = [
        "\n",
        f"{_CMT} SPECTER MOCK INFRASTRUCTURE\n",
        f"{_A}01 MOCK-RECORD.\n",
        f"{_B}05 MOCK-OP-KEY        PIC X(30).\n",
        f"{_B}05 MOCK-ALPHA-STATUS  PIC X(20).\n",
        f"{_B}05 MOCK-NUM-STATUS    PIC S9(09).\n",
        f"{_B}05 MOCK-FILLER        PIC X(21).\n",
        f"{_A}01 MOCK-FILE-STATUS      PIC XX VALUE '00'.\n",
        "\n",
        f"{_CMT} SPECTER COMMON STUBS\n",
        f"{_A}01 DIBSTAT               PIC X(02) VALUE SPACES.\n",
        f"{_A}01 SQLCODE               PIC S9(09) COMP VALUE 0.\n",
        "\n",
    ]

    # Find where to insert in WORKING-STORAGE
    ws_idx = divisions.get("working-storage")
    if ws_idx is not None:
        # Insert after WORKING-STORAGE SECTION line
        insert_at = ws_idx + 1
        for entry in reversed(ws_entries):
            result.insert(insert_at, entry)

    # --- Add FILE-CONTROL ---
    fc_entry = (
        f"{_B}SELECT MOCK-FILE ASSIGN TO\n"
        f"{_CONT}'{config.mock_dd_name}'\n"
        f"{_CONT}ORGANIZATION IS LINE SEQUENTIAL\n"
        f"{_CONT}FILE STATUS IS MOCK-FILE-STATUS.\n"
    )

    fc_idx = divisions.get("file-control")
    if fc_idx is not None:
        result.insert(fc_idx + 1, fc_entry)
    else:
        io_idx = divisions.get("input-output")
        if io_idx is not None:
            # INPUT-OUTPUT SECTION exists but no FILE-CONTROL — add it
            result.insert(io_idx + 1, f"{_A}FILE-CONTROL.\n")
            result.insert(io_idx + 2, fc_entry)
        else:
            # Need to add INPUT-OUTPUT SECTION + FILE-CONTROL
            env_idx = divisions.get("environment")
            if env_idx is not None:
                insert_at = env_idx + 1
                for k in range(insert_at, min(insert_at + 10, len(result))):
                    if "CONFIGURATION SECTION" in result[k].upper():
                        insert_at = k + 1
                        break
                io_block = [
                    f"{_A}INPUT-OUTPUT SECTION.\n",
                    f"{_A}FILE-CONTROL.\n",
                    fc_entry,
                ]
                for entry in reversed(io_block):
                    result.insert(insert_at, entry)

    # --- Add FILE SECTION with FD ---
    fd_block = [
        f"{_A}FILE SECTION.\n",
        f"{_A}FD MOCK-FILE.\n",
        f"{_A}01 MOCK-FILE-RECORD     PIC X(80).\n",
        "\n",
    ]

    # Find or create FILE SECTION
    fs_idx = None
    for i, line in enumerate(result):
        if "FILE SECTION" in line.upper() and not line.strip().startswith("*"):
            fs_idx = i
            break

    if fs_idx is not None:
        # Insert FD after FILE SECTION
        for entry in reversed(fd_block[1:]):  # skip "FILE SECTION" line
            result.insert(fs_idx + 1, entry)
    else:
        # Add FILE SECTION before WORKING-STORAGE
        for i, line in enumerate(result):
            if "WORKING-STORAGE SECTION" in line.upper():
                for entry in reversed(fd_block):
                    result.insert(i, entry)
                break

    return result


# ---------------------------------------------------------------------------
# Phase 8: Convert LINKAGE to WORKING-STORAGE
# ---------------------------------------------------------------------------

def _convert_linkage(lines: list[str]) -> list[str]:
    """Convert LINKAGE SECTION items to WORKING-STORAGE."""
    result: list[str] = []
    in_linkage = False
    linkage_items: list[str] = []

    for line in lines:
        upper = line.upper().strip()
        if "LINKAGE SECTION" in upper and not upper.startswith("*"):
            in_linkage = True
            result.append(_comment_line(line))
            continue

        if in_linkage:
            # End of linkage: next division/section
            if any(kw in upper for kw in [
                "PROCEDURE DIVISION", "WORKING-STORAGE SECTION",
                "LOCAL-STORAGE SECTION", "REPORT SECTION",
            ]):
                in_linkage = False
                # Insert linkage items into WS
                # Find last WS line
                ws_end = len(result) - 1
                for k in range(len(result) - 1, -1, -1):
                    if result[k].strip() and not result[k].strip().startswith("*"):
                        ws_end = k + 1
                        break
                for item in linkage_items:
                    result.insert(ws_end, item)
                    ws_end += 1
                result.append(line)
            else:
                # Collect linkage items
                if upper and not upper.startswith("*"):
                    linkage_items.append(line)
                result.append(_comment_line(line))
        else:
            result.append(line)

    return result


# ---------------------------------------------------------------------------
# Phase 9: Fix PROCEDURE DIVISION
# ---------------------------------------------------------------------------

def _fix_procedure_division(lines: list[str]) -> list[str]:
    """Remove USING clause and comment out DFHCOMMAREA copies."""
    result: list[str] = []
    pd_re = re.compile(
        r"^(\s+PROCEDURE\s+DIVISION)\s+USING\s+.*$",
        re.IGNORECASE,
    )
    # DFHCOMMAREA copy is meaningless in mock mode — comment it out
    comm_re = re.compile(
        r"MOVE\s+DFHCOMMAREA\s*\(",
        re.IGNORECASE,
    )
    in_comm_block = False
    for i, line in enumerate(lines):
        m = pd_re.match(line)
        content = _get_cobol_content(line)
        if m:
            result.append(m.group(1) + ".\n")
            in_comm_block = False
        elif comm_re.search(content):
            result.append(_comment_line(line))
            in_comm_block = True
        elif in_comm_block:
            # Check if this is a continuation of the DFHCOMMAREA MOVE
            stripped = content.strip()
            if not stripped:
                # Blank line ends the block
                result.append(line)
                in_comm_block = False
            elif stripped.startswith("*"):
                # Already commented (e.g., by CICS translator)
                result.append(line)
            elif not re.match(
                r"^(IF|ELSE|END-IF|MOVE|PERFORM|EVALUATE|DISPLAY"
                r"|ADD|SUBTRACT|COMPUTE|GO|READ|WRITE|OPEN|CLOSE"
                r"|CALL|EXEC|SET|INITIALIZE|STRING|UNSTRING|INSPECT"
                r"|ACCEPT|STOP|GOBACK|EXIT|CONTINUE|SEARCH)\b",
                stripped, re.IGNORECASE
            ):
                # Continuation line — comment it out
                result.append(_comment_line(line))
            else:
                # New statement — end of block
                # If next statement is END-IF/ELSE, insert CONTINUE to
                # avoid empty clause body (COBOL requires it)
                if re.match(r"^(END-IF|ELSE|END-EVALUATE)\b",
                            stripped, re.IGNORECASE):
                    result.append(f"{_B}CONTINUE\n")
                result.append(line)
                in_comm_block = False
        else:
            # Also detect already-commented DFHCOMMAREA lines (from CICS translator)
            if line[6:7] == "*" and comm_re.search(line[7:72] if len(line) > 7 else ""):
                result.append(line)
                in_comm_block = True
            else:
                result.append(line)
    return result


# ---------------------------------------------------------------------------
# Phase 10: Add mock file open/close
# ---------------------------------------------------------------------------

def _add_mock_file_handling(
    lines: list[str],
    config: MockConfig,
) -> list[str]:
    """Add OPEN/CLOSE for mock file around main logic."""
    result: list[str] = []
    proc_found = False
    first_para_found = False

    for i, line in enumerate(lines):
        upper = line.upper().strip()

        if "PROCEDURE DIVISION" in upper and not upper.startswith("*"):
            proc_found = True
            result.append(line)
            continue

        # Insert OPEN after first paragraph name
        if proc_found and not first_para_found:
            para_m = re.match(
                r"^(\s{7})([A-Z0-9][A-Z0-9_-]*)\s*\.\s*$",
                line, re.IGNORECASE,
            )
            if para_m:
                first_para_found = True
                result.append(line)
                result.append(
                    f"{_B}OPEN INPUT MOCK-FILE\n"
                )
                # Read initial variable values from mock file
                # Records with op-key starting with INIT: are consumed
                # and used to set variables before main logic runs.
                if config.initial_values:
                    result.append(
                        f"{_B}PERFORM SPECTER-READ-INIT-VARS\n"
                    )
                continue

        result.append(line)

    # Replace STOP RUN and GOBACK with close + stop
    # Skip if previous non-empty line already has CLOSE MOCK-FILE
    final: list[str] = []
    for line in result:
        content = _get_cobol_content(line).upper().strip()
        if (content == "STOP RUN" or content == "STOP RUN."
                or content == "GOBACK" or content == "GOBACK."):
            # Check if we already have a CLOSE MOCK-FILE right before
            already_closed = False
            for prev in reversed(final):
                pc = _get_cobol_content(prev).upper().strip()
                if pc:
                    if "CLOSE MOCK-FILE" in pc:
                        already_closed = True
                    break
            if not already_closed:
                final.append(f"{_B}CLOSE MOCK-FILE\n")
        final.append(line)

    # Append SPECTER-EXIT-PARA at the very end — target for GO TO
    # from mocked CICS RETURN/XCTL blocks
    final.append(f"\n")
    final.append(f"{_CMT} SPECTER: exit paragraph for CICS RETURN/XCTL\n")
    final.append(f"{_A}SPECTER-EXIT-PARA.\n")
    final.append(f"{_B}CLOSE MOCK-FILE\n")
    final.append(f"{_B}STOP RUN.\n")

    # Append init-vars reader paragraph if initial values are configured
    if config.initial_values:
        final.append(f"\n")
        final.append(f"{_CMT} SPECTER: read init records from mock file\n")
        final.append(f"{_A}SPECTER-READ-INIT-VARS.\n")
        final.append(f"{_B}READ MOCK-FILE INTO MOCK-RECORD\n")
        final.append(f"{_CONT}AT END\n")
        final.append(f"{_CONT}  GO TO SPECTER-INIT-DONE\n")
        final.append(f"{_B}END-READ\n")
        final.append(f"{_B}IF MOCK-OP-KEY(1:5) = 'INIT:'\n")
        # Evaluate variable name (cols 6-30 of op-key) and set value
        final.append(f"{_B}  EVALUATE MOCK-OP-KEY(6:25)\n")
        for var, val in config.initial_values.items():
            padded = f"{var:<25}"
            if val.isdigit() or (val.startswith("-") and val[1:].isdigit()):
                final.append(f"{_B}    WHEN '{padded}'\n")
                final.append(f"{_B}      MOVE {val} TO {var}\n")
            elif re.match(r"^X'[0-9A-Fa-f]+'$", val):
                final.append(f"{_B}    WHEN '{padded}'\n")
                final.append(f"{_B}      MOVE {val} TO {var}\n")
            else:
                final.append(f"{_B}    WHEN '{padded}'\n")
                final.append(f"{_B}      MOVE MOCK-ALPHA-STATUS TO {var}\n")
        final.append(f"{_B}  END-EVALUATE\n")
        final.append(f"{_B}  GO TO SPECTER-READ-INIT-VARS\n")
        final.append(f"{_B}END-IF.\n")
        final.append(f"{_A}SPECTER-INIT-DONE.\n")
        final.append(f"{_B}CONTINUE.\n")

    return final


# ---------------------------------------------------------------------------
# Phase 11: Common stubs (DFHAID, DFHBMSCA, DFHRESP)
# ---------------------------------------------------------------------------

def _add_common_stubs(lines: list[str]) -> list[str]:
    """Add stub definitions for common CICS/IMS constants if referenced."""
    full_text = "".join(lines).upper()

    stubs: list[str] = []

    # DFHAID — AID key constants
    if "DFHAID" in full_text or "EIBAID" in full_text:
        stubs.extend([
            "\n",
            f"{_CMT} SPECTER STUB: DFHAID (AID key values)\n",
            f"{_A}01 DFHAID-CONSTANTS.\n",
            f"{_B}05 DFHENTER        PIC X VALUE X'7D'.\n",
            f"{_B}05 DFHCLEAR        PIC X VALUE X'6D'.\n",
            f"{_B}05 DFHPA1          PIC X VALUE X'6C'.\n",
            f"{_B}05 DFHPA2          PIC X VALUE X'6E'.\n",
            f"{_B}05 DFHPA3          PIC X VALUE X'6B'.\n",
            f"{_B}05 DFHPF1          PIC X VALUE X'F1'.\n",
            f"{_B}05 DFHPF2          PIC X VALUE X'F2'.\n",
            f"{_B}05 DFHPF3          PIC X VALUE X'F3'.\n",
            f"{_B}05 DFHPF4          PIC X VALUE X'F4'.\n",
            f"{_B}05 DFHPF5          PIC X VALUE X'F5'.\n",
            f"{_B}05 DFHPF6          PIC X VALUE X'F6'.\n",
            f"{_B}05 DFHPF7          PIC X VALUE X'F7'.\n",
            f"{_B}05 DFHPF8          PIC X VALUE X'F8'.\n",
            f"{_B}05 DFHPF9          PIC X VALUE X'F9'.\n",
            f"{_B}05 DFHPF10         PIC X VALUE X'7A'.\n",
            f"{_B}05 DFHPF11         PIC X VALUE X'7B'.\n",
            f"{_B}05 DFHPF12         PIC X VALUE X'7C'.\n",
            f"{_B}05 DFHPF13         PIC X VALUE X'C1'.\n",
            f"{_B}05 DFHPF14         PIC X VALUE X'C2'.\n",
            f"{_B}05 DFHPF15         PIC X VALUE X'C3'.\n",
            f"{_B}05 DFHPF16         PIC X VALUE X'C4'.\n",
            f"{_B}05 DFHPF17         PIC X VALUE X'C5'.\n",
            f"{_B}05 DFHPF18         PIC X VALUE X'C6'.\n",
            f"{_B}05 DFHPF19         PIC X VALUE X'C7'.\n",
            f"{_B}05 DFHPF20         PIC X VALUE X'C8'.\n",
            f"{_B}05 DFHPF21         PIC X VALUE X'C9'.\n",
            f"{_B}05 DFHPF22         PIC X VALUE X'4A'.\n",
            f"{_B}05 DFHPF23         PIC X VALUE X'4B'.\n",
            f"{_B}05 DFHPF24         PIC X VALUE X'4C'.\n",
        ])

    # DFHBMSCA — BMS attribute constants
    if "DFHBMSCA" in full_text or "DFHBM" in full_text:
        stubs.extend([
            "\n",
            f"{_CMT} SPECTER STUB: DFHBMSCA (BMS attributes)\n",
            f"{_A}01 DFHBMSCA-CONSTANTS.\n",
            f"{_B}05 DFHBMPRO        PIC X VALUE X'F0'.\n",
            f"{_B}05 DFHBMUNP        PIC X VALUE X'C0'.\n",
            f"{_B}05 DFHBMUNN        PIC X VALUE X'D0'.\n",
            f"{_B}05 DFHBMPRF        PIC X VALUE X'61'.\n",
            f"{_B}05 DFHBMASF        PIC X VALUE X'C1'.\n",
            f"{_B}05 DFHBMASK        PIC X VALUE X'F0'.\n",
            f"{_B}05 DFHBMFSE        PIC X VALUE X'C8'.\n",
            f"{_B}05 DFHRED          PIC X VALUE X'F2'.\n",
            f"{_B}05 DFHBLUE         PIC X VALUE X'F4'.\n",
            f"{_B}05 DFHGREEN        PIC X VALUE X'F5'.\n",
            f"{_B}05 DFHWHITE        PIC X VALUE X'F7'.\n",
            f"{_B}05 DFHYELLO        PIC X VALUE X'F6'.\n",
            f"{_B}05 DFHTURQ         PIC X VALUE X'F1'.\n",
            f"{_B}05 DFHPINK         PIC X VALUE X'F3'.\n",
            f"{_B}05 DFHDFCOL        PIC X VALUE X'00'.\n",
            f"{_B}05 DFHNEUTR        PIC X VALUE X'00'.\n",
            f"{_B}05 DFHBMDAR        PIC X VALUE X'0C'.\n",
            f"{_B}05 DFHBMBRY        PIC X VALUE X'F0'.\n",
        ])

    # EIB fields
    if "EIBCALEN" in full_text or "EIBAID" in full_text or "EIBTRNID" in full_text:
        stubs.extend([
            "\n",
            f"{_CMT} SPECTER STUB: EIB (Execute Interface Block)\n",
            f"{_A}01 DFHEIBLK.\n",
            f"{_B}05 EIBTIME         PIC S9(7) COMP-3 VALUE 0.\n",
            f"{_B}05 EIBDATE         PIC S9(7) COMP-3 VALUE 0.\n",
            f"{_B}05 EIBTRNID        PIC X(4) VALUE SPACES.\n",
            f"{_B}05 EIBTASKN        PIC S9(7) COMP-3 VALUE 0.\n",
            f"{_B}05 EIBTRMID        PIC X(4) VALUE SPACES.\n",
            f"{_B}05 EIBCPOSN        PIC S9(4) COMP VALUE 0.\n",
            f"{_B}05 EIBCALEN        PIC S9(4) COMP VALUE 0.\n",
            f"{_B}05 EIBAID          PIC X VALUE SPACES.\n",
            f"{_B}05 EIBFN           PIC X(2) VALUE SPACES.\n",
            f"{_B}05 EIBRCODE        PIC X(6) VALUE SPACES.\n",
            f"{_B}05 EIBDS           PIC X(8) VALUE SPACES.\n",
            f"{_B}05 EIBREQID        PIC X(8) VALUE SPACES.\n",
            f"{_B}05 EIBRSRCE        PIC X(8) VALUE SPACES.\n",
            f"{_B}05 EIBSYNC         PIC X VALUE SPACES.\n",
            f"{_B}05 EIBFREE         PIC X VALUE SPACES.\n",
            f"{_B}05 EIBRECV         PIC X VALUE SPACES.\n",
            f"{_B}05 EIBSIG          PIC X VALUE SPACES.\n",
            f"{_B}05 EIBCONF         PIC X VALUE SPACES.\n",
            f"{_B}05 EIBERR          PIC X VALUE SPACES.\n",
            f"{_B}05 EIBERRCD        PIC X(4) VALUE SPACES.\n",
            f"{_B}05 EIBSYNRB        PIC X VALUE SPACES.\n",
            f"{_B}05 EIBNODAT        PIC X VALUE SPACES.\n",
            f"{_B}05 EIBRESP         PIC S9(8) COMP VALUE 0.\n",
            f"{_B}05 EIBRESP2        PIC S9(8) COMP VALUE 0.\n",
        ])

    # DFHRESP — inject as numeric constants via 88-levels or REPLACE
    # Actually, DFHRESP(NORMAL) etc. are function-like macros.
    # GnuCOBOL doesn't support these — we need to replace in source.
    # Handle this via text replacement.

    if not stubs:
        return lines

    # Insert stubs into WORKING-STORAGE
    result = list(lines)
    for i, line in enumerate(result):
        if "WORKING-STORAGE SECTION" in line.upper() and not line.strip().startswith("*"):
            insert_at = i + 1
            for entry in reversed(stubs):
                result.insert(insert_at, entry)
            break

    # Replace DFHRESP(xxx) with numeric literals
    dfhresp_map = {
        "NORMAL": "0", "ERROR": "1", "NOTFND": "13",
        "DUPREC": "14", "DUPKEY": "15", "INVREQ": "16",
        "NOTAUTH": "70", "DISABLED": "84", "IOERR": "17",
        "LENGERR": "22", "NOSPACE": "18", "PGMIDERR": "27",
        "SYSIDERR": "53", "ITEMERR": "26", "ENDFILE": "20",
        "QIDERR": "44", "EXPIRED": "31", "MAPFAIL": "36",
    }

    final: list[str] = []
    for line in result:
        for name, val in dfhresp_map.items():
            line = re.sub(
                rf"DFHRESP\s*\(\s*{name}\s*\)",
                val,
                line,
                flags=re.IGNORECASE,
            )
        final.append(line)

    return final


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_cobol_content(line: str) -> str:
    """Extract content area (cols 7-72) from a COBOL line."""
    if len(line) < 7:
        return ""
    # Col 7 is indicator (*, /, D, -)
    if len(line) > 6 and line[6] in ("*", "/"):
        return ""
    return line[6:72] if len(line) > 72 else line[6:]


def _comment_line(line: str) -> str:
    """Turn a COBOL line into a comment by putting * in column 7."""
    if len(line) < 7:
        return line
    return line[:6] + "*" + line[7:]


# ---------------------------------------------------------------------------
# Mock data generation from test cases
# ---------------------------------------------------------------------------

def generate_init_records(initial_values: dict[str, str]) -> str:
    """Generate INIT: records for the mock data file.

    These must be the first records in the file so the SPECTER-READ-INIT-VARS
    paragraph consumes them before main logic runs.
    """
    records: list[str] = []
    for var, val in initial_values.items():
        op_key = f"INIT:{var:<25}"[:30]
        alpha = str(val)
        try:
            num = int(val)
        except (ValueError, TypeError):
            num = 0
        record = f"{op_key:<30}{alpha:<20}{num:>10}"
        records.append(f"{record:<80}"[:80])
    # Sentinel: non-INIT record to stop the init loop
    records.append(f"{'END-INIT':<30}{'':<20}{0:>10}"[:80])
    return "\n".join(records)


def generate_mock_data(
    test_case,
    stub_mapping: dict[str, list[str]] | None = None,
) -> str:
    """Generate mock data file content from a Specter TestCase.

    Each record is 80 chars: op-key(30) + alpha-status(20) + num-status(10) + filler.
    Records are written in the order they'll be consumed (FIFO per operation).

    Args:
        test_case: A TestCase from test_store.
        stub_mapping: Optional operation→status-vars mapping.

    Returns:
        Content for the mock data file.
    """
    records: list[str] = []

    # Flatten stub_outcomes into ordered records
    # The mock file must contain records in execution order.
    # Since we don't know the exact execution order, we interleave
    # all operation queues. The COBOL program reads sequentially.
    #
    # Strategy: output all records for each operation in queue order,
    # grouped by operation key.
    for op_key, queue in test_case.stub_outcomes.items():
        for entry in queue:
            alpha_status = ""
            num_status = 0

            if isinstance(entry, list):
                for pair in entry:
                    if isinstance(pair, (list, tuple)) and len(pair) == 2:
                        var, val = pair
                        if isinstance(val, (int, float)):
                            num_status = int(val)
                            alpha_status = str(int(val))
                        else:
                            alpha_status = str(val)
                            try:
                                num_status = int(val)
                            except (ValueError, TypeError):
                                num_status = 0

            record = f"{op_key:<30}{alpha_status:<20}{num_status:>10}"
            # Pad/truncate to 80 chars
            record = f"{record:<80}"[:80]
            records.append(record)

    # Add defaults as extra records (will be consumed if queue is exhausted)
    if hasattr(test_case, "stub_defaults") and test_case.stub_defaults:
        for op_key, default in test_case.stub_defaults.items():
            for _ in range(10):  # repeat defaults
                alpha_status = ""
                num_status = 0
                if isinstance(default, list):
                    for pair in default:
                        if isinstance(pair, (list, tuple)) and len(pair) == 2:
                            var, val = pair
                            if isinstance(val, (int, float)):
                                num_status = int(val)
                                alpha_status = str(int(val))
                            else:
                                alpha_status = str(val)
                                try:
                                    num_status = int(val)
                                except (ValueError, TypeError):
                                    num_status = 0
                record = f"{op_key:<30}{alpha_status:<20}{num_status:>10}"
                records.append(f"{record:<80}"[:80])

    return "\n".join(records) + "\n" if records else "\n"


# ---------------------------------------------------------------------------
# Compile and run
# ---------------------------------------------------------------------------

def compile_cobol(
    source_path: str | Path,
    output_path: str | Path | None = None,
    copybook_dirs: list[Path] | None = None,
) -> tuple[bool, str]:
    """Compile COBOL source with GnuCOBOL.

    Returns (success, message).
    """
    source_path = Path(source_path)
    if output_path is None:
        output_path = source_path.with_suffix("")

    cmd = ["cobc", "-x", "-o", str(output_path), str(source_path)]

    if copybook_dirs:
        for d in copybook_dirs:
            cmd.extend(["-I", str(d)])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0:
            return True, f"Compiled: {output_path}"
        else:
            return False, f"Compilation failed:\n{result.stderr}\n{result.stdout}"
    except Exception as e:
        return False, f"Compilation error: {e}"


def run_cobol(
    executable_path: str | Path,
    mock_data_path: str | Path,
    timeout: int = 30,
) -> tuple[int, str, str]:
    """Run a compiled COBOL program with mock data.

    Returns (return_code, stdout, stderr).
    """
    executable_path = Path(executable_path)
    mock_data_path = Path(mock_data_path)

    env = dict(os.environ)
    env["MOCKDATA"] = str(mock_data_path)
    # GnuCOBOL uses DD_ prefix or environment variable for file assignment
    env["DD_MOCKDATA"] = str(mock_data_path)

    try:
        result = subprocess.run(
            [str(executable_path)],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Execution timed out"
    except Exception as e:
        return -1, "", f"Execution error: {e}"


def parse_trace(stdout: str) -> list[str]:
    """Extract paragraph trace from COBOL program output."""
    trace = []
    for line in stdout.splitlines():
        if line.startswith("SPECTER-TRACE:"):
            para = line[len("SPECTER-TRACE:"):].strip()
            trace.append(para)
    return trace


def parse_mock_ops(stdout: str) -> list[str]:
    """Extract mock operation log from COBOL program output."""
    ops = []
    for line in stdout.splitlines():
        if line.startswith("SPECTER-MOCK:"):
            op = line[len("SPECTER-MOCK:"):].strip()
            ops.append(op)
    return ops
