"""Per-test-case seed SQL generator.

Translates ``CICS-READ`` / ``READ:<file>`` / ``DLI-GU`` stub outcomes from
a test case into ``INSERT`` statements that populate the real application
tables (defined in ``sql/init.sql`` from copybook DDL).

The generated SQL is intended to run in the integration test's
``@BeforeEach`` so a real ``JdbcStubExecutor.cicsRead()`` SELECT will
return the data each test case expects, rather than NOTFND.

Limitations (documented inline):
- TODO(multi-read): When the same CICS-READ key has multiple FIFO entries,
  only the first uses ``input_state[ridfld]`` as the key value. Subsequent
  entries fall back to a synthetic ``<ridfld_value>__<seq>`` suffix because
  the original ridfld for each subsequent call is not recoverable from
  ``input_state`` alone.
- The op_keys ``CICS-READ`` and ``DLI-GU`` carry no resource name in the
  current schema, so we treat each FIFO entry as targeting the *first*
  table among ``table_index`` whose columns intersect the entry's variable
  names. When ambiguous, we fall back to the first matching table and emit
  a ``-- TODO(ambiguous-table)`` comment.
"""

from __future__ import annotations

from typing import Any, Mapping

from ..copybook_parser import CopybookField, CopybookRecord, _sql_column_name


# Op_keys we consider DB-read operations and therefore worth seeding.
_READ_OP_PREFIXES = ("READ:", "CICS-READ", "DLI-GU")


def is_seedable_op_key(op_key: str) -> bool:
    """True when this op_key represents a read whose result we should pre-seed."""
    if op_key.startswith("READ:"):
        return True
    upper = op_key.upper()
    return upper.startswith("CICS-READ") or upper.startswith("DLI-GU")


def build_table_index(
    records: list[CopybookRecord],
) -> dict[str, CopybookRecord]:
    """Index copybook records by their PostgreSQL table name (UPPER, ``_`` sep).

    The DDL generator (``copybook_parser.generate_ddl``) uses
    ``_sql_column_name(record.name)`` for the table; we mirror that here.
    """
    index: dict[str, CopybookRecord] = {}
    for rec in records:
        if not rec.name or not rec.fields:
            continue
        table = _sql_column_name(rec.name)
        index[table] = rec
    return index


def _record_columns(rec: CopybookRecord) -> dict[str, CopybookField]:
    """Return ``{COLUMN_NAME: field}`` for non-filler, non-group fields."""
    cols: dict[str, CopybookField] = {}
    for f in rec.fields:
        if f.is_filler or f.pic_type == "group":
            continue
        if f.occurs > 1:
            for i in range(1, f.occurs + 1):
                cols[f"{_sql_column_name(f.name)}_{i}"] = f
        else:
            cols[_sql_column_name(f.name)] = f
    return cols


def _resolve_table_for_op(
    op_key: str,
    entry_columns: set[str],
    table_index: dict[str, dict[str, CopybookField]],
) -> tuple[str | None, str | None]:
    """Find the (table_name, ambiguity_note) best matching this op outcome.

    For ``READ:<FILE>`` we use ``<FILE>`` directly (with hyphen→underscore).
    For ``CICS-READ`` / ``DLI-GU`` we pick the table whose columns share the
    most names with ``entry_columns``. Ties go to the first match in
    insertion order; ambiguity is reported via the second return value.
    """
    if op_key.startswith("READ:"):
        raw = op_key.split(":", 1)[1]
        table = _sql_column_name(raw)
        return (table, None) if table in table_index else (None, None)

    best_table: str | None = None
    best_score = 0
    ties = 0
    for table, cols in table_index.items():
        score = sum(1 for c in entry_columns if c in cols)
        if score > best_score:
            best_table = table
            best_score = score
            ties = 0
        elif score == best_score and best_score > 0:
            ties += 1
    if best_table is None:
        return (None, None)
    note = "ambiguous-table" if ties else None
    return (best_table, note)


def _sql_quote(val: Any) -> str:
    """Render a Python value as a PostgreSQL literal."""
    if val is None or val == "":
        return "NULL"
    if isinstance(val, bool):
        return "TRUE" if val else "FALSE"
    if isinstance(val, (int, float)):
        return str(val)
    s = str(val).replace("'", "''")
    return f"'{s}'"


def _ridfld_for_op(op_key: str, input_state: Mapping[str, Any]) -> tuple[str, Any] | None:
    """Best-effort: find a ridfld variable + value from input_state.

    ``CICS-READ`` op_keys do not carry the ridfld name in their key, so we
    look in ``input_state`` for keys whose suffix ends in ``-ID`` or
    ``-KEY``. Returns ``None`` if nothing plausible is found.
    """
    candidates = [
        k for k in input_state
        if k.upper().endswith(("-ID", "-KEY", "_ID", "_KEY"))
    ]
    if not candidates:
        return None
    # Prefer non-empty values
    for k in candidates:
        v = input_state.get(k)
        if v not in (None, ""):
            return (k, v)
    return (candidates[0], input_state.get(candidates[0]))


def build_seed_sql(
    test_case_id: str,
    input_state: Mapping[str, Any],
    stub_outcomes: Mapping[str, list],
    table_index: dict[str, CopybookRecord],
) -> str:
    """Generate per-test-case seed SQL.

    Args:
        test_case_id: Used in the SQL header comment for traceability.
        input_state: COBOL variable assignments at the start of the test.
        stub_outcomes: FIFO queues keyed by op_key.
        table_index: Output of ``build_table_index(records)``.

    Returns:
        A multi-statement SQL script with a ``TRUNCATE`` prologue per
        touched table followed by per-outcome ``INSERT`` statements.
        Returns the empty string when no seedable op_keys are present
        or when no outcomes can be matched to a known table.
    """
    if not table_index:
        return ""

    cols_by_table = {t: _record_columns(r) for t, r in table_index.items()}

    inserts: list[str] = []
    touched_tables: list[str] = []

    for op_key, queue in stub_outcomes.items():
        if not is_seedable_op_key(op_key):
            continue
        if not queue:
            continue

        # Pre-derive ridfld guess (only used for non-READ:<FILE> ops).
        ridfld_guess = None
        if not op_key.startswith("READ:"):
            ridfld_guess = _ridfld_for_op(op_key, input_state)

        for seq, entry in enumerate(queue):
            if not entry:
                continue
            entry_pairs = [
                (_sql_column_name(p[0]), p[1])
                for p in entry
                if isinstance(p, (list, tuple)) and len(p) >= 2
            ]
            entry_columns = {col for col, _ in entry_pairs}

            table, note = _resolve_table_for_op(op_key, entry_columns, cols_by_table)
            if table is None or table not in cols_by_table:
                inserts.append(
                    f"-- TODO(seed): no table matches op_key={op_key} "
                    f"entry={seq} columns={sorted(entry_columns) or 'EMPTY'}"
                )
                continue

            allowed_cols = cols_by_table[table]
            row: dict[str, Any] = {}

            # Key column from input_state ridfld (or synthetic when seq>0).
            if op_key.startswith("READ:"):
                key_col = None
                key_val = None
            elif ridfld_guess:
                ridfld_name, ridfld_val = ridfld_guess
                key_col = _sql_column_name(ridfld_name)
                if seq == 0:
                    key_val = ridfld_val
                else:
                    # TODO(multi-read): synthetic key for entries past the first.
                    key_val = f"{ridfld_val}__{seq}" if ridfld_val not in (None, "") else f"seed_{seq}"
            else:
                key_col = None
                key_val = None

            if key_col and key_col in allowed_cols:
                row[key_col] = key_val

            # Outcome (var, val) pairs become column values.
            for col, val in entry_pairs:
                if col in allowed_cols:
                    row[col] = val

            if not row:
                inserts.append(
                    f"-- TODO(seed): op_key={op_key} entry={seq} "
                    f"yielded no columns matching table {table}"
                )
                continue

            if table not in touched_tables:
                touched_tables.append(table)

            cols = list(row.keys())
            vals = [_sql_quote(row[c]) for c in cols]
            comment = f"-- {op_key} entry {seq}"
            if note:
                comment += f" ({note})"
            inserts.append(comment)
            inserts.append(
                f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(vals)});"
            )

    if not inserts:
        return ""

    header = [
        f"-- Auto-generated by Specter for test case {test_case_id}",
        "-- Reset target tables before inserting per-test-case rows.",
    ]
    truncates = [f"TRUNCATE TABLE {t} CASCADE;" for t in touched_tables]
    body = "\n".join(header + truncates + [""] + inserts) + "\n"
    return body
