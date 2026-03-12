"""Parse COBOL copybook files and generate SQL DDL and Java DAO classes."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field


@dataclass
class CopybookField:
    level: int
    name: str
    pic: str | None
    pic_type: str       # "alpha", "numeric", "packed", "comp", "group"
    length: int
    precision: int      # decimal places
    occurs: int         # OCCURS n TIMES, default 1
    is_filler: bool
    values_88: dict[str, str] = field(default_factory=dict)


@dataclass
class CopybookRecord:
    name: str
    fields: list[CopybookField]
    copybook_file: str


def _parse_pic(pic_clause: str, usage: str) -> tuple[str, int, int]:
    """Return (pic_type, length, precision) from a PIC clause and USAGE."""
    pic = pic_clause.strip().upper()

    # Determine precision from V (implied decimal)
    precision = 0
    if 'V' in pic:
        after_v = pic.split('V', 1)[1]
        # count decimal digits: e.g. V99 -> 2, V9(4) -> 4
        precision = _count_digits(after_v)

    # Determine base type from usage first
    usage_up = usage.upper().strip()
    if 'COMP-3' in usage_up or 'PACKED' in usage_up:
        length = _integer_digits(pic)
        return ('packed', length, precision)
    if 'COMP' in usage_up or 'BINARY' in usage_up:
        length = _integer_digits(pic)
        return ('comp', length, precision)

    # Now determine from PIC itself
    if pic.startswith('X') or pic.startswith('+') and 'X' in pic:
        length = _count_alpha(pic)
        return ('alpha', length, 0)

    if pic.startswith('S') or pic.startswith('9') or pic.startswith('+') or pic.startswith('-'):
        length = _integer_digits(pic)
        return ('numeric', length, precision)

    # Fallback: treat as alpha
    length = _count_alpha(pic)
    return ('alpha', length, 0)


def _count_alpha(pic: str) -> int:
    """Count character length from PIC X patterns."""
    total = 0
    for m in re.finditer(r'X\((\d+)\)', pic):
        total += int(m.group(1))
    # Remove X(n) patterns, then count remaining standalone X
    stripped = re.sub(r'X\(\d+\)', '', pic)
    total += stripped.count('X')
    if total == 0:
        # try counting 9s for numeric display as alpha
        total = _total_digits(pic)
    return max(total, 1)


def _count_nines(s: str) -> int:
    """Count digit positions from a PIC fragment like '99' or '9(4)' or '9(04)'."""
    total = 0
    # First, find all 9(n) patterns and sum their counts
    for m in re.finditer(r'9\((\d+)\)', s):
        total += int(m.group(1))
    # Remove those patterns, then count remaining standalone 9s
    stripped = re.sub(r'9\(\d+\)', '', s)
    total += stripped.count('9')
    return total


def _count_digits(s: str) -> int:
    """Count digit positions in a PIC fragment like '99' or '9(4)'."""
    return _count_nines(s)


def _integer_digits(pic: str) -> int:
    """Count integer digit positions (before V) in a PIC clause."""
    s = pic.lstrip('S+-')
    if 'V' in s:
        s = s.split('V', 1)[0]
    result = _count_nines(s)
    return max(result, 1)


def _total_digits(pic: str) -> int:
    """Count all digit positions (before and after V) in a PIC clause."""
    s = pic.lstrip('S+-')
    result = _count_nines(s)
    return max(result, 1)


def parse_copybook(text: str, copybook_file: str = '') -> CopybookRecord:
    """Parse COBOL copybook text into a CopybookRecord."""
    # Normalize: join continuation lines, strip comments
    lines = _preprocess(text)

    # Parse into statements (terminated by period)
    statements = _split_statements(lines)

    record_name = ''
    fields: list[CopybookField] = []
    current_field: CopybookField | None = None

    for stmt in statements:
        tokens = stmt.split()
        if not tokens:
            continue

        # First token should be level number
        try:
            level = int(tokens[0])
        except ValueError:
            continue

        if level == 88:
            # 88-level condition: attach to current field
            if current_field is not None:
                name_88 = tokens[1] if len(tokens) > 1 else ''
                value_88 = _extract_88_value(stmt)
                current_field.values_88[name_88] = value_88
            continue

        name = tokens[1] if len(tokens) > 1 else ''

        if level == 1:
            record_name = name.rstrip('.')
            # 01 level is the record itself, not a field
            continue

        is_filler = (name.upper() == 'FILLER')

        # Extract PIC clause
        pic_clause = _extract_pic(stmt)
        # Extract USAGE
        usage = _extract_usage(stmt)
        # Extract OCCURS
        occurs = _extract_occurs(stmt)

        if pic_clause:
            pic_type, length, precision = _parse_pic(pic_clause, usage)
        else:
            # Group item (no PIC)
            pic_type = 'group'
            length = 0
            precision = 0

        f = CopybookField(
            level=level,
            name=name.rstrip('.'),
            pic=pic_clause,
            pic_type=pic_type,
            length=length,
            precision=precision,
            occurs=occurs,
            is_filler=is_filler,
            values_88={},
        )
        current_field = f
        fields.append(f)

    return CopybookRecord(
        name=record_name,
        fields=fields,
        copybook_file=copybook_file,
    )


def _preprocess(text: str) -> list[str]:
    """Strip comment lines and handle continuation. Return cleaned lines."""
    result = []
    for raw in text.splitlines():
        # COBOL comment: column 7 is '*' or '/' (if line is long enough)
        if len(raw) > 6 and raw[6] in ('*', '/'):
            continue
        # Strip sequence numbers (columns 1-6) if present and line is >= 7 chars
        # Also strip identification area (cols 73+)
        line = raw
        if len(line) > 72:
            line = line[:72]
        # Simple approach: just use the line as-is for our purposes
        # Strip leading/trailing whitespace for easier parsing
        result.append(line.strip())
    return result


def _split_statements(lines: list[str]) -> list[str]:
    """Join lines into period-terminated statements."""
    buf = ''
    stmts = []
    for line in lines:
        if not line:
            continue
        buf += ' ' + line
        if '.' in line:
            # Split on period
            parts = buf.split('.')
            for p in parts[:-1]:
                s = p.strip()
                if s:
                    stmts.append(s)
            buf = parts[-1]
    if buf.strip():
        stmts.append(buf.strip())
    return stmts


def _extract_pic(stmt: str) -> str | None:
    """Extract PIC/PICTURE clause from a statement."""
    m = re.search(r'\bPIC(?:TURE)?\s+(.*)', stmt, re.IGNORECASE)
    if not m:
        return None
    rest = m.group(1)
    # PIC clause ends before OCCURS, VALUE, COMP, BINARY or end
    # Capture the PIC pattern
    pic_match = re.match(
        r'([SsXx0-9+\-()V.]+)',
        rest,
    )
    if pic_match:
        return pic_match.group(1).upper().rstrip('.')
    return None


def _extract_usage(stmt: str) -> str:
    """Extract USAGE (COMP, COMP-3, BINARY, PACKED-DECIMAL)."""
    upper = stmt.upper()
    if 'COMP-3' in upper or 'PACKED-DECIMAL' in upper:
        return 'COMP-3'
    if 'COMP' in upper or 'BINARY' in upper:
        # Check it's not COMP-3
        if re.search(r'\bCOMP\b', upper) or re.search(r'\bBINARY\b', upper):
            return 'COMP'
    return ''


def _extract_occurs(stmt: str) -> int:
    """Extract OCCURS n TIMES."""
    m = re.search(r'\bOCCURS\s+(\d+)', stmt, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return 1


def _extract_88_value(stmt: str) -> str:
    """Extract VALUE from an 88-level statement."""
    m = re.search(r'\bVALUE\s+(.+)', stmt, re.IGNORECASE)
    if m:
        val = m.group(1).strip().rstrip('.')
        # Remove quotes if present
        val = val.strip("'\"")
        return val
    return ''


# ---------------------------------------------------------------------------
# DDL generation
# ---------------------------------------------------------------------------

def _sql_column_name(cobol_name: str) -> str:
    return cobol_name.replace('-', '_').upper()


def _sql_type(f: CopybookField) -> str:
    """Map a CopybookField to a SQL column type."""
    if f.pic_type == 'alpha':
        if f.length <= 4:
            return f'CHAR({f.length})'
        return f'VARCHAR({f.length})'
    if f.pic_type == 'numeric':
        if f.precision > 0:
            total = f.length + f.precision
            return f'DECIMAL({total}, {f.precision})'
        if f.length <= 9:
            return f'NUMERIC({f.length})'
        return f'NUMERIC({f.length})'
    if f.pic_type == 'packed':
        if f.precision > 0:
            total = f.length + f.precision
            return f'DECIMAL({total}, {f.precision})'
        return f'DECIMAL({f.length}, 0)'
    if f.pic_type == 'comp':
        if f.precision > 0:
            total = f.length + f.precision
            return f'DECIMAL({total}, {f.precision})'
        if f.length <= 9:
            return 'INTEGER'
        return 'BIGINT'
    return f'VARCHAR({f.length})'


def generate_ddl(
    record: CopybookRecord,
    table_name: str | None = None,
    dialect: str = "ansi",
) -> str:
    """Generate CREATE TABLE DDL from a CopybookRecord.

    Args:
        record: Parsed copybook record.
        table_name: Override table name (default: derived from record name).
        dialect: ``"postgresql"`` adds ``IF NOT EXISTS`` and infers primary key
                 from the first ``*-ID`` field; ``"ansi"`` emits plain SQL.
    """
    if table_name is None:
        table_name = _sql_column_name(record.name)

    columns: list[str] = []
    pk_col: str | None = None

    for f in record.fields:
        # Skip: FILLER, group items, 88-levels (already not in fields list)
        if f.is_filler:
            continue
        if f.pic_type == 'group':
            continue

        col_type = _sql_type(f)

        if f.occurs > 1:
            for i in range(1, f.occurs + 1):
                col_name = f'{_sql_column_name(f.name)}_{i}'
                columns.append(f'    {col_name:<28s}{col_type}')
        else:
            col_name = _sql_column_name(f.name)
            columns.append(f'    {col_name:<28s}{col_type}')
            # Infer PK: first field whose name ends with -ID
            if pk_col is None and f.name.upper().endswith('-ID'):
                pk_col = col_name

    if dialect == "postgresql" and pk_col:
        columns.append(f'    PRIMARY KEY ({pk_col})')

    body = ',\n'.join(columns)
    exists = " IF NOT EXISTS" if dialect == "postgresql" else ""
    return f'CREATE TABLE{exists} {table_name} (\n{body}\n);'


def generate_all_ddl(copybook_dir: str | list[str], dialect: str = "ansi") -> str:
    """Scan directory/directories for .cpy files, parse each, generate DDL."""
    if isinstance(copybook_dir, str):
        dirs = [copybook_dir]
    else:
        dirs = copybook_dir

    results: list[str] = []
    for d in dirs:
        if not os.path.isdir(d):
            continue
        for fname in sorted(os.listdir(d)):
            if fname.lower().endswith('.cpy'):
                path = os.path.join(d, fname)
                with open(path, 'r') as fh:
                    text = fh.read()
                rec = parse_copybook(text, copybook_file=fname)
                if rec.name and rec.fields:
                    results.append(generate_ddl(rec, dialect=dialect))

    return '\n\n'.join(results)


def generate_init_sql(
    copybook_dirs: list[str],
    dialect: str = "postgresql",
) -> str:
    """Combine DDL from all copybooks into a single init script.

    Args:
        copybook_dirs: List of directory paths containing .cpy files.
        dialect: SQL dialect (``"postgresql"`` or ``"ansi"``).

    Returns:
        Combined DDL string suitable for ``/docker-entrypoint-initdb.d/``.
    """
    header = "-- Auto-generated by Specter from COBOL copybooks\n\n"
    ddl = generate_all_ddl(copybook_dirs, dialect=dialect)
    return header + ddl + "\n" if ddl else header


# ---------------------------------------------------------------------------
# Java DAO generation
# ---------------------------------------------------------------------------

def _java_class_name(cobol_name: str) -> str:
    """Convert COBOL name like CARD-XREF-RECORD to CamelCase CardXrefRecord."""
    parts = cobol_name.split('-')
    return ''.join(p.capitalize() for p in parts)


def _java_rs_getter(f: CopybookField) -> str:
    """Return the ResultSet getter method for a field."""
    if f.pic_type == 'alpha':
        return 'getString'
    if f.pic_type in ('numeric', 'packed', 'comp'):
        if f.precision > 0:
            return 'getBigDecimal'
        if f.length <= 9:
            return 'getLong'
        return 'getLong'
    return 'getString'


def _java_ps_setter(f: CopybookField) -> str:
    """Return the PreparedStatement setter method for a field."""
    if f.pic_type == 'alpha':
        return 'setString'
    if f.pic_type in ('numeric', 'packed', 'comp'):
        if f.precision > 0:
            return 'setBigDecimal'
        if f.length <= 9:
            return 'setLong'
        return 'setLong'
    return 'setString'


def _java_ps_value_expr(f: CopybookField, state_key: str) -> str:
    """Return the expression to convert state value for PreparedStatement."""
    if f.pic_type == 'alpha':
        return f'state.get("{state_key}").toString()'
    if f.pic_type in ('numeric', 'packed', 'comp'):
        if f.precision > 0:
            return f'new java.math.BigDecimal(state.get("{state_key}").toString())'
        return f'CobolRuntime.toNum(state.get("{state_key}"))'
    return f'state.get("{state_key}").toString()'


def generate_dao_java(record: CopybookRecord, package_name: str) -> str:
    """Generate a Java DAO class for a copybook record."""
    class_name = _java_class_name(record.name) + 'Dao'

    populate_lines: list[str] = []
    bind_lines: list[str] = []
    bind_index = 1

    for f in record.fields:
        if f.is_filler:
            continue
        if f.pic_type == 'group':
            continue

        if f.occurs > 1:
            for i in range(1, f.occurs + 1):
                cobol_key = f'{f.name}({i})'
                col_name = f'{_sql_column_name(f.name)}_{i}'
                getter = _java_rs_getter(f)
                setter = _java_ps_setter(f)
                populate_lines.append(
                    f'        state.put("{cobol_key}", rs.{getter}("{col_name}"));'
                )
                val_expr = _java_ps_value_expr(f, cobol_key)
                bind_lines.append(
                    f'        ps.{setter}({bind_index}, {val_expr});'
                )
                bind_index += 1
        else:
            cobol_key = f.name
            col_name = _sql_column_name(f.name)
            getter = _java_rs_getter(f)
            setter = _java_ps_setter(f)
            populate_lines.append(
                f'        state.put("{cobol_key}", rs.{getter}("{col_name}"));'
            )
            val_expr = _java_ps_value_expr(f, cobol_key)
            bind_lines.append(
                f'        ps.{setter}({bind_index}, {val_expr});'
            )
            bind_index += 1

    populate_body = '\n'.join(populate_lines)
    bind_body = '\n'.join(bind_lines)

    return f"""package {package_name};

import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;

public class {class_name} {{
    public static void populateFromResultSet(ProgramState state, ResultSet rs) throws SQLException {{
{populate_body}
    }}

    public static void bindToStatement(ProgramState state, PreparedStatement ps) throws SQLException {{
{bind_body}
    }}
}}
"""
