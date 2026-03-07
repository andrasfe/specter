#!/usr/bin/env python3
"""Preprocess a scrambled COBOL source for GnuCOBOL compilation.

Handles:
  - Strip cols 73-80 (sequence/change-tag area)
  - Replace scrambled section names (INPUT-OUTPUT SECTION)
  - Remove RECORDING MODE (unsupported by GnuCOBOL)
  - Remove EXEC SQL blocks, replace with SQLCODE assignments
  - Remove scrambled COPY statements (SYM00271)
  - Stub CALL statements
  - Remove FD entries and FILE SECTION (replace with WS equivalents)

Usage:
    python3 tools/cobol_stub.py input.cbl output.cbl
"""

from __future__ import annotations

import re
import sys


def _comment(text: str) -> str:
    """Fixed-format comment (col 7 = *)."""
    return "      *> " + text.rstrip() + "\n"


def _code(text: str) -> str:
    """Fixed-format code line (col 8+)."""
    return "           " + text.rstrip() + "\n"


def _classify_sql(sql_text: str) -> str:
    upper = sql_text.upper()
    if "DECLARE" in upper and "CURSOR" in upper:
        return "DECLARE"
    if "FETCH" in upper:
        return "FETCH"
    if re.search(r"\bOPEN\b", upper):
        return "OPEN_CURSOR"
    if re.search(r"\bCLOSE\b", upper):
        return "CLOSE_CURSOR"
    if "SELECT" in upper and "INTO" in upper:
        return "SELECT_INTO"
    if "INSERT" in upper:
        return "INSERT"
    if "UPDATE" in upper:
        return "UPDATE"
    if "DELETE" in upper:
        return "DELETE"
    if "COMMIT" in upper:
        return "COMMIT"
    if "SET" in upper and "TIMESTAMP" in upper:
        return "SET_TIMESTAMP"
    return "OTHER"


def _extract_into_vars(sql_text: str) -> list[str]:
    """Extract :HOST-VAR names from INTO clause."""
    m = re.search(r"INTO\s+(.*?)(?:FROM|WHERE|$)", sql_text,
                  re.IGNORECASE | re.DOTALL)
    if not m:
        return []
    return re.findall(r":([A-Z][A-Z0-9-]*)", m.group(1), re.IGNORECASE)


def _extract_set_var(sql_text: str) -> str | None:
    m = re.search(r"SET\s+:([A-Z][A-Z0-9-]*)\s*=", sql_text, re.IGNORECASE)
    return m.group(1) if m else None


def process(lines: list[str]) -> list[str]:
    out: list[str] = []
    i = 0
    in_file_section = False
    skip_fd = False

    while i < len(lines):
        raw = lines[i]

        # Strip cols 73-80 (fixed-format sequence/change area)
        if len(raw) > 72:
            raw = raw[:72] + "\n"

        # Strip scrambler change tags (G##nnnnn, P##nnnnn, Sym00nnn)
        # These appear both in cols 73-80 AND inline in the code area.
        # After col-72 truncation, partial tags like " G#", " P#" may remain.
        # Also strip ##nnnnn concatenated directly with variable names.
        raw = re.sub(r"##\d*", "", raw)  # strip ##nnnnn anywhere
        # Fix periods followed by orphaned tag letters: ".G" -> "."
        raw = re.sub(r"\.[GP]\s*$", ".", raw.rstrip()) + "\n"
        raw = re.sub(r"\.[GP]\s", ". ", raw)
        raw = re.sub(r"\s+[GPS]#*\s*$", "", raw.rstrip()) + "\n"
        raw = re.sub(r"\s+[GPS]#[#\d]*", "", raw)
        # Also strip Sym/Sy partial tags that appear as inline fragments
        raw = re.sub(r"\s+Sym?\d*\s*$", "", raw.rstrip()) + "\n"
        # Strip lone trailing tag letters (S, G, P) after period+spaces
        raw = re.sub(r"\.\s+[SGP]\s*$", ".", raw.rstrip()) + "\n"

        # Fix cols 1-6: if they contain non-space non-digit text (developer
        # names like "KIRAN"), blank them out (fixed-format cols 1-6 are
        # sequence area, should be spaces or digits)
        if len(raw) >= 7:
            seq_area = raw[:6]
            if re.search(r"[A-Za-z]", seq_area):
                raw = "      " + raw[6:]

        # Remove blank-only lines left after stripping
        if raw.strip() == "":
            i += 1
            continue

        line = raw
        # ---- Replace scrambled keywords early (before pattern matching) ----
        line = re.sub(r"\bSYM00302\b", "TRUE", line)
        line = re.sub(r"\bSYM00496\b", "NUMVAL", line)
        line = re.sub(r"\bSYM00274\b", "REPLACING", line)
        line = re.sub(r"\bSYM00547\b", "EXEC", line)
        line = re.sub(r"\bSYM00548\b", "COMMIT", line)
        # SYM00565 = YYYYMMDD (ACCEPT FROM DATE format)
        line = re.sub(r"\bSYM00565\b", "YYYYMMDD", line)
        stripped = line.strip()

        # ---- ENVIRONMENT DIVISION fixes ----
        # Remove scrambled INPUT-OUTPUT SECTION and FILE-CONTROL entirely
        # (all file I/O is stubbed, no files needed)
        if re.match(r"SYM00003\s+SECTION", stripped):
            out.append(_comment("INPUT-OUTPUT SECTION removed"))
            i += 1
            continue

        if stripped.upper() == "FILE-CONTROL.":
            out.append(_comment("FILE-CONTROL removed"))
            i += 1
            # Skip all SELECT statements until next section/division
            while i < len(lines):
                s = lines[i].strip().upper()
                if (s.startswith("DATA DIVISION")
                        or s.startswith("PROCEDURE DIVISION")
                        or s.endswith("SECTION.")):
                    break
                out.append(_comment("  " + lines[i].strip()[:60]))
                i += 1
            continue

        # ---- RECORDING MODE (not supported by GnuCOBOL) ----
        if "RECORDING MODE" in stripped.upper():
            out.append(_comment("REMOVED: " + stripped))
            i += 1
            continue

        # ---- FILE SECTION: remove FDs, we'll stub the file vars ----
        if stripped.upper() == "FILE SECTION.":
            out.append(_comment("FILE SECTION removed - files stubbed"))
            in_file_section = True
            i += 1
            continue

        if in_file_section:
            if stripped.upper().startswith("WORKING-STORAGE SECTION"):
                in_file_section = False
                # Fall through to emit this line
            else:
                # Skip entire FILE SECTION
                i += 1
                continue

        # ---- Scrambled COPY statements (SYM00271 = COPY) ----
        if re.match(r"SYM00271\b", stripped):
            out.append(_comment("COPY stubbed: " + stripped[:60]))
            i += 1
            continue

        # ---- EXEC SQL blocks ----
        if "EXEC SQL" in stripped:
            sql_lines = [stripped]
            i += 1
            # If END-EXEC is already on the same line, skip the loop
            while (i < len(lines) and "END-EXEC" not in stripped
                   and "END-EXEC" not in lines[i]):
                # Strip cols 73-80 for sql content too
                sline = lines[i][:72] if len(lines[i]) > 72 else lines[i]
                sql_lines.append(sline.strip())
                i += 1
            if "END-EXEC" not in stripped:
                if i < len(lines):
                    sql_lines.append(lines[i].strip())
                    i += 1

            sql_text = " ".join(sql_lines)
            kind = _classify_sql(sql_text)
            out.append(_comment(f"SQL-{kind}: {stripped[:50]}"))

            if kind == "DECLARE":
                pass  # Cursor declarations are no-ops
            elif kind in ("SELECT_INTO", "FETCH"):
                out.append(_code("MOVE +100 TO SYM00372."))
            elif kind in ("INSERT", "UPDATE", "DELETE",
                          "OPEN_CURSOR", "CLOSE_CURSOR", "COMMIT"):
                out.append(_code("MOVE 0 TO SYM00372."))
            elif kind == "SET_TIMESTAMP":
                var = _extract_set_var(sql_text)
                if var:
                    out.append(_code(
                        f"MOVE '2026-01-01-00.00.00.000000'"
                    ))
                    out.append(_code(f"    TO {var}."))
                else:
                    out.append(_code("CONTINUE."))
            else:
                out.append(_code("CONTINUE."))
            continue

        # ---- CALL statements ----
        if re.match(r"CALL\b", stripped, re.IGNORECASE):
            out.append(_comment("CALL stubbed: " + stripped[:60]))
            # Consume continuation lines (USING ..., continuation data names)
            i += 1
            while i < len(lines):
                raw_next = lines[i]
                s = raw_next.strip()
                s_upper = s.upper()
                # Stop at paragraph headers (col 8 name + period)
                if re.match(r"       [A-Z]", raw_next) and re.match(
                    r"[A-Z][A-Z0-9-]+\.\s*$", s
                ):
                    break
                # USING keyword, or deeply indented SYM variable continuation,
                # ON EXCEPTION / NOT ON EXCEPTION / END-CALL
                if (s_upper.startswith("USING")
                        or re.match(r"^SYM\d+\.?\s*$", s)
                        or s_upper.startswith("ON EXCEPTION")
                        or s_upper.startswith("NOT ON")
                        or s_upper.startswith("END-CALL")):
                    out.append(_comment("  " + s[:60]))
                    i += 1
                else:
                    break
            out.append(_code("CONTINUE."))
            continue

        # ---- File I/O: OPEN/CLOSE ----
        if re.match(r"(OPEN|CLOSE)\b", stripped, re.IGNORECASE):
            out.append(_comment("File I/O stubbed: " + stripped[:60]))
            i += 1
            # Consume continuation lines (INPUT, OUTPUT, I-O, file names)
            while i < len(lines):
                raw_next = lines[i]
                s = raw_next.strip()
                # Stop if this looks like a paragraph header (col 8, name + period)
                if re.match(r"       [A-Z]", raw_next) and re.match(
                    r"[A-Z][A-Z0-9-]+\.\s*$", s
                ):
                    break
                # File continuation lines start with keywords or file names
                if re.match(
                    r"(INPUT|OUTPUT|I-O|EXTEND|SYM\d+)\b", s, re.IGNORECASE
                ):
                    out.append(_comment("  " + s[:60]))
                    i += 1
                else:
                    break
            out.append(_code("CONTINUE."))
            continue

        # ---- READ ----
        if re.match(r"READ\b", stripped, re.IGNORECASE):
            out.append(_comment("READ stubbed: " + stripped[:60]))
            i += 1
            # Consume INTO, AT END, NOT AT END, END-READ
            while i < len(lines):
                s = lines[i].strip().upper()
                if s.startswith(("INTO", "AT END", "NOT AT",
                                 "END-READ", "NEXT")):
                    out.append(_comment("  " + lines[i].strip()[:60]))
                    i += 1
                else:
                    break
            # Set first file status to EOF
            out.append(_code("MOVE '10' TO SYM00006."))
            continue

        # ---- WRITE / REWRITE ----
        if re.match(r"(WRITE|REWRITE)\b", stripped, re.IGNORECASE):
            out.append(_comment("WRITE stubbed: " + stripped[:60]))
            out.append(_code("CONTINUE"))
            i += 1
            continue

        # ---- Pass through ----
        out.append(line)
        i += 1

    return out


def inject_missing_vars(lines: list[str], original_lines: list[str]) -> list[str]:
    """Find where WORKING-STORAGE SECTION is and inject stub declarations
    for variables that were in FILE SECTION or COPY includes."""

    # Build PIC map from original source
    full_text = "".join(original_lines)
    pic_defs = {}
    for m in re.finditer(
        r"\b(SYM\d+)\s+PIC\s+(S?[9X]\(\d+\)(?:\s*COMP(?:-3)?)?)",
        full_text, re.IGNORECASE,
    ):
        name = m.group(1).upper()
        pic = m.group(2).strip()
        if name not in pic_defs:
            pic_defs[name] = pic

    # Detect INDEX BY names from original source (these are implicit defs)
    index_names = set()
    for m in re.finditer(r"INDEXED\s+BY\s+(SYM\d+)", full_text, re.IGNORECASE):
        index_names.add(m.group(1).upper())

    # Collect all variable names defined in the stubbed WS
    defined = set()
    for line in lines:
        m = re.match(r"\s+\d+\s+(SYM\d+)\b", line)
        if m:
            defined.add(m.group(1).upper())
        # 88-level
        m = re.match(r"\s+88\s+(SYM\d+)\b", line)
        if m:
            defined.add(m.group(1).upper())
    # Index names are implicitly defined
    defined |= index_names

    # Collect paragraph names (lines like "       SYM00288." at col 8)
    paragraph_names = set()
    in_proc = False
    for line in lines:
        if "PROCEDURE DIVISION" in line:
            in_proc = True
        if in_proc:
            m = re.match(r"       (SYM\d+)\.\s*$", line)
            if m:
                paragraph_names.add(m.group(1).upper())

    # Collect all variable names referenced in PROCEDURE DIVISION
    referenced = set()
    in_proc = False
    for line in lines:
        if "PROCEDURE DIVISION" in line:
            in_proc = True
        if in_proc:
            for m in re.finditer(r"\b(SYM\d+)\b", line):
                referenced.add(m.group(1).upper())

    # Also check WS for references (88-level TRUE values like SYM00302)
    for line in lines:
        for m in re.finditer(r"\bTO\s+(SYM\d+)\b", line, re.IGNORECASE):
            referenced.add(m.group(1).upper())

    missing = sorted(referenced - defined - paragraph_names)
    if not missing:
        return lines

    # Detect variables used in numeric context (COMPUTE, ADD, SUBTRACT, etc.)
    stubbed_text = "".join(lines)
    numeric_vars = set()
    for m in re.finditer(
        r"(?:COMPUTE|ADD|SUBTRACT|MULTIPLY|DIVIDE)\s+.*?(SYM\d+)",
        stubbed_text, re.IGNORECASE,
    ):
        numeric_vars.add(m.group(1).upper())
    # Also detect: MOVE +nnn TO var, SET var TO +nnn
    for m in re.finditer(r"MOVE\s+\+?\d+\s+TO\s+(SYM\d+)", stubbed_text, re.IGNORECASE):
        numeric_vars.add(m.group(1).upper())

    # Detect max reference-subscript size: VAR (offset:length) or VAR (offset + N:length)
    max_ref_size: dict[str, int] = {}
    for m in re.finditer(
        r"\b(SYM\d+)\s*\([^)]*?[+:]\s*(\d+)\s*(?::(\d+))?\)",
        stubbed_text, re.IGNORECASE,
    ):
        var = m.group(1).upper()
        offset = int(m.group(2))
        length = int(m.group(3)) if m.group(3) else 0
        needed = offset + length
        if needed > max_ref_size.get(var, 0):
            max_ref_size[var] = needed

    # Detect 88-level condition names: referenced in SET-TO-TRUE,
    # EVALUATE WHEN, or bare IF conditions
    condition_names = set()
    in_proc = False
    for line in lines:
        if "PROCEDURE DIVISION" in line:
            in_proc = True
        if not in_proc:
            continue
        # SET <cond> TO TRUE
        m = re.search(r"SET\s+(SYM\d+)\s+TO\s+TRUE", line, re.IGNORECASE)
        if m:
            condition_names.add(m.group(1).upper())
        # WHEN <cond> (bare condition in EVALUATE)
        m = re.match(r"\s+WHEN\s+(SYM\d+)\s*$", line)
        if m:
            condition_names.add(m.group(1).upper())
        # IF <cond> (bare condition, not followed by =, >, <, etc.)
        m = re.match(r"\s+IF\s+(SYM\d+)\s*$", line)
        if m:
            condition_names.add(m.group(1).upper())

    # Only consider missing vars that look like conditions
    condition_missing = condition_names & set(missing) - defined

    # Inject after WORKING-STORAGE SECTION line
    result = []
    for line in lines:
        result.append(line)
        if "WORKING-STORAGE SECTION" in line.upper():
            result.append(
                "      *> --- Stub declarations for FILE/COPY vars ---\n"
            )
            # First: parent variable for 88-level conditions
            if condition_missing:
                result.append(
                    "       01 STUB-COND-PARENT     PIC X(01) VALUE 'N'.\n"
                )
                for var in sorted(condition_missing):
                    result.append(
                        f"          88 {var:<20s} VALUE 'Y'.\n"
                    )

            # SQLCODE (SYM00372) needs to be S9(09) COMP for SQL stubs
            for var in missing:
                if var in condition_missing:
                    continue  # Already handled above
                if var == "SYM00372":
                    pic = "S9(09) COMP"
                elif var in pic_defs:
                    pic = pic_defs[var]
                elif var in numeric_vars:
                    pic = "S9(09) COMP"
                elif var in max_ref_size:
                    size = max(max_ref_size[var], 100)
                    pic = f"X({size})"
                else:
                    pic = "X(30)"
                result.append(f"       01 {var:<20s} PIC {pic}.\n")
            result.append(
                "      *> --- End stub declarations ---\n"
            )

    return result


def main():
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} input.cbl output.cbl", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1]) as f:
        lines = f.readlines()

    result = process(lines)
    result = inject_missing_vars(result, lines)

    with open(sys.argv[2], "w") as f:
        f.writelines(result)

    # Stats
    n_comments = sum(1 for l in result if l.lstrip().startswith("*>"))
    print(f"Stubbed: {len(lines)} -> {len(result)} lines ({n_comments} stub comments)")


if __name__ == "__main__":
    main()
