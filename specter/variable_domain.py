"""Unified Variable Domain Model — bridges PIC clauses, AST analysis, and heuristics.

Each VariableDomain knows a variable's valid type, range, precision, semantic meaning,
and relationship to stub operations. The coverage engine uses this for all value generation.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from pathlib import Path

from .copybook_parser import CopybookField, CopybookRecord, parse_copybook
from .variable_extractor import VariableReport


# ---------------------------------------------------------------------------
# Data structure
# ---------------------------------------------------------------------------

@dataclass
class VariableDomain:
    """Unified domain model for a single COBOL variable."""

    name: str
    # Type info (from PIC clause or inference)
    data_type: str = "unknown"  # "alpha", "numeric", "packed", "comp", "flag", "unknown"
    max_length: int = 10        # max chars (PIC X(n)) or digits (PIC 9(n))
    precision: int = 0          # decimal places (from PIC V99)
    signed: bool = False        # from PIC S9(...)
    # Range constraints
    min_value: int | float | None = None
    max_value: int | float | None = None
    # Value domain
    condition_literals: list = field(default_factory=list)
    valid_88_values: dict[str, str] = field(default_factory=dict)
    # Semantic classification
    classification: str = "internal"  # "input", "internal", "status", "flag"
    semantic_type: str = "generic"
    # Stub relationship
    set_by_stub: str | None = None
    # Initial VALUE clause from COBOL source (non-88 variables)
    initial_value: str | int | float | None = None


# ---------------------------------------------------------------------------
# Semantic type inference from naming patterns
# ---------------------------------------------------------------------------

_SEMANTIC_PATTERNS: list[tuple[list[str], str]] = [
    (["DATE", "DT", "YYDDD", "YYMMDD", "YYYYMMDD", "MMDDYY"], "date"),
    (["TIME", "TM", "HHMMSS"], "time"),
    (["AMT", "AMOUNT", "BAL", "BALANCE", "TOTAL"], "amount"),
    (["CNT", "COUNT", "FREQ", "NBR"], "counter"),
    (["KEY", "NUM", "ID", "ACCT"], "identifier"),
    (["SQLCODE", "SQLSTATE"], "status_sql"),
    (["EIBRESP", "EIBAID"], "status_cics"),
]


def _infer_semantic_type(name: str, classification: str) -> str:
    """Infer semantic type from variable name and classification."""
    upper = name.upper()

    # Explicit status patterns
    if upper.endswith("-STATUS") or upper.startswith("FS-") or upper.startswith("FILE-STATUS"):
        return "status_file"
    if "FLAG" in upper or "FLG" in upper or upper.endswith("-ON") or upper.endswith("-OFF"):
        return "flag_bool"

    # Check naming patterns
    parts = set(upper.replace("_", "-").split("-"))
    for keywords, sem_type in _SEMANTIC_PATTERNS:
        for kw in keywords:
            if kw in parts or kw in upper:
                return sem_type

    # PCB status fields
    if "PCB-STATUS" in upper or upper.startswith("STATUS-CODE-"):
        return "status_file"

    if classification == "status":
        return "status_file"
    if classification == "flag":
        return "flag_bool"

    return "generic"


# ---------------------------------------------------------------------------
# Range computation from PIC clauses
# ---------------------------------------------------------------------------

def _compute_range(
    data_type: str, max_length: int, precision: int, signed: bool,
) -> tuple[int | float | None, int | float | None]:
    """Compute min/max value from PIC clause parameters."""
    if data_type in ("alpha", "unknown"):
        return None, None

    # Numeric types: max is 10^length - 1
    int_max = 10 ** max_length - 1
    if precision > 0:
        divisor = 10 ** precision
        fmax = int_max + (10 ** precision - 1) / divisor
        if signed:
            return -fmax, fmax
        return 0.0, fmax
    else:
        if signed:
            return -int_max, int_max
        return 0, int_max


# ---------------------------------------------------------------------------
# 88-level VALUE extraction from COBOL source
# ---------------------------------------------------------------------------

def _extract_88_values_from_source(
    cobol_source: str | Path,
) -> dict[str, dict[str, str | int | float]]:
    """Scan a COBOL source file for 88-level VALUE clauses.

    Returns a mapping ``parent_var_name -> {child_88_name -> child_value}``
    so that variables defined inline in the program (not in a copybook)
    still populate ``VariableDomain.valid_88_values``.

    This complements ``cobol_coverage._extract_88_siblings_from_source``
    (which only captures sibling *names*). The strategy layer needs the
    actual activating VALUE to inject ``APPL-RESULT = 16`` when a branch
    is gated on ``88 APPL-EOF VALUE 16``; without the VALUE, fault
    injection can flip the flag name but cannot set the underlying
    integer/string that activates it.

    We track the most recently seen non-88 parent line and attach any
    88-level children that follow it. The parser is deliberately
    line-based and cheap — it does not try to handle every exotic
    continuation, OCCURS-DEPENDING-ON, or multi-line VALUE clause.
    """
    result: dict[str, dict[str, str | int | float]] = {}
    path = Path(cobol_source)
    if not path.exists():
        return result

    # Match "nn PARENT-NAME ..." where nn is a level number in 01..49,
    # 66, 77. Anything at 88 is a child, not a parent.
    parent_re = re.compile(
        r"^\s+(0[1-9]|[1-4][0-9]|66|77)\s+([A-Z0-9][A-Z0-9-]*)",
        re.IGNORECASE,
    )
    # Match "88 NAME VALUE <literal>". The literal captures the rest of
    # the line so we can post-process strings, numerics and THRU ranges.
    child_re = re.compile(
        r"^\s+88\s+([A-Z0-9][A-Z0-9-]*)\s+VALUES?\s+(.+?)\s*\.?\s*$",
        re.IGNORECASE,
    )

    current_parent: str | None = None
    parent_is_based = False
    for raw in path.read_text(errors="replace").splitlines():
        # Skip fixed-format comment lines (col 7 = '*' or '/').
        if len(raw) > 6 and raw[6] in ("*", "/"):
            continue
        stripped = raw.rstrip()
        if not stripped:
            continue

        m_parent = parent_re.match(stripped)
        if m_parent:
            current_parent = m_parent.group(2).upper()
            # Skip BASED structures — their fields are pointer-addressed
            # and have no valid storage at startup. Injecting a value
            # via SPECTER-READ-INIT-VARS would dereference a null
            # pointer and crash the binary (the CBSTM03A regression
            # where UCB-ADDR inside 01 TIOT-ENTRY BASED caused
            # SIGSEGV on every test case). Also skip structures with
            # SET ADDRESS OF patterns, which imply the same layout.
            upper_line = stripped.upper()
            parent_is_based = bool(
                re.search(r"\bBASED\b", upper_line)
                or re.search(r"\bPOINTER\b", upper_line)
            )
            continue

        m_child = child_re.match(stripped)
        if m_child and current_parent is not None and not parent_is_based:
            child_name = m_child.group(1).upper()
            raw_value = m_child.group(2).strip()
            parsed = _parse_88_literal(raw_value)
            if parsed is not None:
                result.setdefault(current_parent, {})[child_name] = parsed

    return result


def _extract_initial_values_from_source(
    cobol_source: str | Path,
) -> dict[str, str | int | float]:
    """Scan a COBOL source for non-88-level VALUE clauses on named fields.

    Returns ``{VAR_NAME: initial_value}`` for variables whose DATA
    DIVISION definitions include an explicit ``VALUE`` clause.  This lets
    the coverage engine preserve startup constants instead of
    overwriting them with random INIT injection.

    Only captures leaf-level fields (with PIC clauses) — group items and
    FILLER are skipped.  88-level items are handled separately by
    ``_extract_88_values_from_source``.
    """
    result: dict[str, str | int | float] = {}
    path = Path(cobol_source)
    if not path.exists():
        return result

    # Match: "nn VARNAME PIC ... VALUE <literal>." on a single line.
    # Level 01..49, 66, 77.  Must have PIC clause (leaf), must NOT be
    # FILLER, and must have VALUE keyword.
    val_re = re.compile(
        r"^\s+(0[1-9]|[1-4][0-9]|66|77)\s+"
        r"([A-Z][A-Z0-9-]*)\s+"      # variable name (not FILLER)
        r".*?\bPIC\b.*?"              # must have PIC clause
        r"\bVALUES?\s+(.+?)\s*\.?\s*$",  # VALUE clause
        re.IGNORECASE,
    )

    for raw in path.read_text(errors="replace").splitlines():
        # Skip fixed-format comment lines.
        if len(raw) > 6 and raw[6] in ("*", "/"):
            continue
        stripped = raw.rstrip()
        if not stripped:
            continue
        m = val_re.match(stripped)
        if not m:
            continue
        var_name = m.group(2).upper()
        if var_name == "FILLER":
            continue
        raw_val = m.group(3).strip()
        parsed = _parse_88_literal(raw_val)
        if parsed is not None:
            result[var_name] = parsed

    return result


_FIGURATIVE_LITERAL_MAP: dict[str, str | int] = {
    "SPACES": " ", "SPACE": " ",
    "ZEROS": 0, "ZERO": 0, "ZEROES": 0,
    "LOW-VALUES": "", "LOW-VALUE": "",
    "HIGH-VALUES": "\xff", "HIGH-VALUE": "\xff",
    "QUOTES": '"', "QUOTE": '"',
}


def _parse_88_literal(raw: str) -> str | int | float | None:
    """Parse the right-hand side of an 88-level VALUE clause.

    Handles quoted strings, signed/unsigned integers, floats, figurative
    constants, and ``VALUE 'X' THRU 'Y'`` ranges (returns the low end).
    Multi-value lists like ``VALUE 'A', 'B', 'C'`` collapse to the first
    entry — strategies that want to exercise every member should iterate
    the sibling 88-level flags instead.
    """
    token = raw.strip()

    # Match a leading quoted literal first so we can peel it off cleanly
    # even when the VALUE clause is a multi-value list like
    # ``VALUE 'A', 'B', 'C'``. We only need the first member — sibling
    # 88-level flags are enumerated separately by the strategy layer.
    m_quoted = re.match(r"^\s*'([^']*)'", token)
    if m_quoted:
        return m_quoted.group(1)
    m_quoted = re.match(r'^\s*"([^"]*)"', token)
    if m_quoted:
        return m_quoted.group(1)

    # THRU / THROUGH ranges — use the low end.
    thru_split = re.split(r"\s+(?:THRU|THROUGH)\s+", token, maxsplit=1, flags=re.IGNORECASE)
    if len(thru_split) == 2:
        token = thru_split[0]

    # Unquoted multi-value list — use the first entry.
    # COBOL allows VALUE 400 401 402 (space-separated) or VALUE 400, 401
    # (comma-separated). Take only the first token.
    if "," in token:
        token = token.split(",", 1)[0].strip()
    if " " in token:
        token = token.split(None, 1)[0].strip()

    # Figurative constant.
    upper = token.upper()
    if upper in _FIGURATIVE_LITERAL_MAP:
        return _FIGURATIVE_LITERAL_MAP[upper]

    # Integer.
    if re.match(r"^[+-]?\d+$", token):
        try:
            return int(token)
        except ValueError:
            return None

    # Float.
    if re.match(r"^[+-]?\d+\.\d+$", token):
        try:
            return float(token)
        except ValueError:
            return None

    return None


# ---------------------------------------------------------------------------
# Construction: build_variable_domains()
# ---------------------------------------------------------------------------

def build_variable_domains(
    var_report: VariableReport,
    copybook_records: list[CopybookRecord] | None = None,
    stub_mapping: dict[str, list[str]] | None = None,
    cobol_source: str | Path | None = None,
) -> dict[str, VariableDomain]:
    """Build unified domain model by merging PIC, AST, stub, and heuristic info.

    Args:
        var_report: VariableReport from variable_extractor.
        copybook_records: Parsed copybook records (from parse_copybook).
        stub_mapping: Operation → status variable mapping.
        cobol_source: Optional path to the COBOL source file. When
            provided, 88-level VALUE clauses defined inline in the
            program (not in a copybook) are extracted and populated into
            ``VariableDomain.valid_88_values`` — this is what lets
            strategies inject ``APPL-RESULT = 16`` to activate
            ``88 APPL-EOF VALUE 16`` on programs like CBACT02C where
            the 88-level items live in the program source itself.

    Returns:
        dict mapping variable name to VariableDomain.
    """
    domains: dict[str, VariableDomain] = {}

    # Source 1: PIC clauses from copybooks
    field_index: dict[str, CopybookField] = {}
    if copybook_records:
        for rec in copybook_records:
            for f in rec.fields:
                if not f.is_filler and f.pic_type != "group":
                    field_index[f.name.upper()] = f

    # Source 2: AST variable info
    for name, info in var_report.variables.items():
        d = VariableDomain(name=name)
        d.classification = info.classification
        d.condition_literals = list(info.condition_literals)

        # Apply PIC clause if available
        upper_name = name.upper()
        cf = field_index.get(upper_name)
        if cf:
            d.data_type = cf.pic_type
            d.max_length = cf.length
            d.precision = cf.precision
            d.signed = cf.pic is not None and cf.pic.upper().startswith("S")
            d.valid_88_values = dict(cf.values_88)
            d.min_value, d.max_value = _compute_range(
                cf.pic_type, cf.length, cf.precision, d.signed,
            )
        else:
            # Infer from condition literals or naming
            if info.condition_literals:
                if all(isinstance(v, (int, float)) for v in info.condition_literals):
                    d.data_type = "numeric"
                elif all(isinstance(v, str) for v in info.condition_literals):
                    # Check if all literals look numeric
                    all_numeric = all(
                        re.match(r"^-?\d+\.?\d*$", str(v).strip())
                        for v in info.condition_literals
                    )
                    if all_numeric:
                        d.data_type = "numeric"
                    else:
                        d.data_type = "alpha"

        # Infer semantic type
        d.semantic_type = _infer_semantic_type(name, d.classification)

        domains[name] = d

    # Source 3: Stub mapping — which stub operation sets this variable
    if stub_mapping:
        for op_key, status_vars in stub_mapping.items():
            for var_name in status_vars:
                if var_name in domains:
                    domains[var_name].set_by_stub = op_key

    # Source 4: 88-level VALUE clauses scanned directly from the COBOL
    # source. This is the only path that captures 88-level values for
    # variables defined inline in the program (as opposed to variables
    # declared in a copybook — those are already picked up via Source 1
    # above). Without this, internal variables like APPL-RESULT with
    # 88-level children APPL-AOK/APPL-EOF never get valid_88_values
    # populated and strategies cannot inject the activating values.
    if cobol_source:
        source_88 = _extract_88_values_from_source(cobol_source)
        for parent_name, child_values in source_88.items():
            dom = domains.get(parent_name)
            if dom is None:
                # Variable referenced in the DATA DIVISION but not in
                # the AST (e.g. unused) — create a minimal domain so
                # strategies that enumerate all 88-bearing vars can find
                # it. Classification stays "internal" by default.
                dom = VariableDomain(name=parent_name)
                dom.semantic_type = _infer_semantic_type(parent_name, dom.classification)
                domains[parent_name] = dom
            # Merge in inline values without overwriting any copybook
            # entry that already claimed the same child name.
            for child, value in child_values.items():
                dom.valid_88_values.setdefault(child, value)

    # Source 5: Initial VALUE clauses for non-88 variables scanned from
    # the COBOL source.  This captures startup constants so the coverage
    # engine can preserve them instead of overwriting with random INIT
    # injection.
    if cobol_source:
        source_values = _extract_initial_values_from_source(cobol_source)
        for var_name, init_val in source_values.items():
            dom = domains.get(var_name)
            if dom is not None:
                dom.initial_value = init_val

    return domains


def load_copybooks(copybook_dirs: list[str | Path]) -> list[CopybookRecord]:
    """Load and parse all .cpy files from directories."""
    records: list[CopybookRecord] = []
    for d in copybook_dirs:
        d = Path(d)
        if not d.is_dir():
            continue
        for fname in sorted(d.iterdir()):
            if fname.suffix.lower() in (".cpy", ".cbl", ".cob"):
                text = fname.read_text(errors="replace")
                rec = parse_copybook(text, copybook_file=str(fname))
                if rec.fields:
                    records.append(rec)
    return records


# ---------------------------------------------------------------------------
# Value generation
# ---------------------------------------------------------------------------

# Status code tables for semantic-aware generation
_FILE_STATUS_CODES = ["00", "10", "23", "35", "39", "41", "46", "47"]
_SQL_STATUS_CODES = [0, 100, -803, -805, -811, -904]
_CICS_STATUS_CODES = [0, 12, 13, 16, 22, 26, 27, 70, 84]
_DLI_STATUS_CODES = ["  ", "II", "GE", "GB", "GG", "AI"]


def _append_unique_candidate(
    values: list[str | int | float],
    seen: set[tuple[str, str]],
    value: str | int | float,
) -> None:
    key = (type(value).__name__, str(value))
    if key in seen:
        return
    seen.add(key)
    values.append(value)


def payload_kind_for_domain(domain: VariableDomain | None) -> str:
    """Return the transcript payload encoding kind for a variable domain.

    File-status variables (``semantic_type == "status_file"``) are ALWAYS
    alpha (PIC XX per the COBOL standard) even though their condition
    literals ('00', '10') look numeric. Using the numeric mock field
    for these produces garbage because MOCK-NUM-STATUS (PIC S9(09)) is
    a 9-byte signed DISPLAY number whose raw bytes are often spaces,
    and moving spaces-as-numeric to a 2-byte GROUP item yields SPACES
    instead of '00'. This was the root cause of the OPEN success-path
    plateau: every WHEN arm for file-status variables in
    SPECTER-APPLY-MOCK-PAYLOAD was doing
    ``MOVE MOCK-NUM-STATUS TO <STATUS-VAR>`` instead of
    ``MOVE MOCK-ALPHA-STATUS TO <STATUS-VAR>``.
    """
    if domain is None:
        return "alpha"
    # File-status variables are always alphanumeric (PIC XX).
    if domain.semantic_type == "status_file":
        return "alpha"
    # GROUP items and unknowns are always alpha.
    if domain.data_type in {"alpha", "group", "unknown"}:
        return "alpha"
    return "numeric"


def build_payload_value_candidates(
    domain: VariableDomain,
    limit: int = 8,
    rng: random.Random | None = None,
) -> list[str | int | float]:
    """Build a compact, domain-aware payload candidate list for transcript search."""
    if rng is None:
        rng = random.Random(0)

    values: list[str | int | float] = []
    seen: set[tuple[str, str]] = set()

    for literal in domain.condition_literals:
        _append_unique_candidate(values, seen, literal)

    for literal in domain.valid_88_values.values():
        _append_unique_candidate(values, seen, literal)

    for strategy in ("semantic", "boundary", "adversarial", "random_valid"):
        try:
            candidate = generate_value(domain, strategy, rng)
        except Exception:
            continue
        _append_unique_candidate(values, seen, candidate)

    if not values and payload_kind_for_domain(domain) == "alpha":
        _append_unique_candidate(values, seen, "")
        _append_unique_candidate(values, seen, "X" * max(1, min(domain.max_length, 4)))

    return values[:limit]


def _coerce_numeric_value(value: str | int | float, precision: int) -> int | float:
    """Coerce mixed generator outputs into a numeric COBOL-compatible value."""
    if isinstance(value, (int, float)):
        return value

    text = str(value).strip()
    if not text:
        return 0.0 if precision > 0 else 0

    upper = text.upper()
    if upper in {"Y", "YES", "TRUE", "T", "ON"}:
        return 1.0 if precision > 0 else 1
    if upper in {"N", "NO", "FALSE", "F", "OFF"}:
        return 0.0 if precision > 0 else 0

    try:
        return float(text) if precision > 0 else int(float(text))
    except ValueError:
        return 0.0 if precision > 0 else 0


def generate_value(
    domain: VariableDomain,
    strategy: str,
    rng: random.Random | None = None,
) -> str | int | float:
    """Generate a valid value for a variable given its domain.

    Args:
        domain: The variable's domain model.
        strategy: One of "condition_literal", "88_value", "boundary",
                  "semantic", "random_valid", "adversarial".
        rng: Random number generator (for determinism).

    Returns:
        A value appropriate for the variable's type and constraints.
    """
    if rng is None:
        rng = random.Random()

    if strategy == "condition_literal" and domain.condition_literals:
        return rng.choice(domain.condition_literals)

    if strategy == "88_value" and domain.valid_88_values:
        return rng.choice(list(domain.valid_88_values.values()))

    if strategy == "boundary":
        return _generate_boundary(domain, rng)

    if strategy == "semantic":
        return _generate_semantic(domain, rng)

    if strategy == "adversarial":
        return _generate_adversarial(domain, rng)

    # "random_valid" or fallback
    return _generate_random_valid(domain, rng)


def _generate_boundary(domain: VariableDomain, rng: random.Random) -> str | int | float:
    """Generate boundary values for numeric types."""
    # Flag variables should get domain-aware values, not junk boundaries.
    if domain.semantic_type == "flag_bool":
        return _generate_semantic(domain, rng)

    if domain.data_type in ("alpha", "unknown"):
        choices = ["", " " * domain.max_length, "A" * domain.max_length]
        return rng.choice(choices)

    candidates: list[int | float] = []
    if domain.min_value is not None:
        candidates.append(domain.min_value)
        if isinstance(domain.min_value, int):
            candidates.append(domain.min_value + 1)
    if domain.max_value is not None:
        candidates.append(domain.max_value)
        if isinstance(domain.max_value, int):
            candidates.append(domain.max_value - 1)
    candidates.append(0)
    if domain.min_value is not None and domain.max_value is not None:
        mid = (domain.min_value + domain.max_value) / 2
        if domain.precision == 0:
            mid = int(mid)
        candidates.append(mid)

    return rng.choice(candidates) if candidates else 0


def _generate_semantic(domain: VariableDomain, rng: random.Random) -> str | int | float:
    """Generate domain-aware values based on semantic type."""
    sem = domain.semantic_type

    if sem == "date":
        year = rng.randint(2020, 2027)
        month = rng.randint(1, 12)
        day = rng.randint(1, 28)
        if domain.max_length >= 8:
            return f"{year:04d}{month:02d}{day:02d}"
        return f"{year % 100:02d}{month:02d}{day:02d}"

    if sem == "time":
        h = rng.randint(0, 23)
        m = rng.randint(0, 59)
        s = rng.randint(0, 59)
        return f"{h:02d}{m:02d}{s:02d}"

    if sem == "amount":
        if domain.precision > 0:
            return round(rng.uniform(0.01, 999999.99), domain.precision)
        return rng.randint(0, 999999)

    if sem == "counter":
        return rng.randint(0, 100)

    if sem == "identifier":
        digits = min(domain.max_length, 10) if domain.max_length > 0 else 10
        return str(rng.randint(10 ** (digits - 1), 10 ** digits - 1))

    if sem == "status_file":
        return rng.choice(_FILE_STATUS_CODES)

    if sem == "status_sql":
        return rng.choice(_SQL_STATUS_CODES)

    if sem == "status_cics":
        return rng.choice(_CICS_STATUS_CODES)

    if sem == "flag_bool":
        if domain.valid_88_values:
            return rng.choice(list(domain.valid_88_values.values()))
        if domain.condition_literals:
            return rng.choice(domain.condition_literals)
        if domain.data_type not in ("alpha", "unknown"):
            return rng.choice([0, 1])
        return rng.choice(["Y", "N"])

    # generic — fall through to random_valid
    return _generate_random_valid(domain, rng)


def _generate_random_valid(domain: VariableDomain, rng: random.Random) -> str | int | float:
    """Generate a random value within PIC constraints."""
    # Flag variables need domain-aware generation even in "random_valid" mode.
    # Without this, flags with data_type=unknown get random alpha garbage
    # which breaks gating conditions that check for boolean-like values.
    if domain.semantic_type == "flag_bool":
        return _generate_semantic(domain, rng)

    if domain.data_type in ("alpha", "unknown"):
        length = max(domain.max_length, 1)
        chars = "".join(rng.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 ") for _ in range(length))
        return chars

    # Numeric types
    if domain.precision > 0:
        lo = float(domain.min_value) if domain.min_value is not None else 0.0
        hi = float(domain.max_value) if domain.max_value is not None else 99999.99
        return round(rng.uniform(lo, hi), domain.precision)
    else:
        lo = int(domain.min_value) if domain.min_value is not None else 0
        hi = int(domain.max_value) if domain.max_value is not None else 99999
        return rng.randint(lo, hi)


def _generate_adversarial(domain: VariableDomain, rng: random.Random) -> str | int | float:
    """Generate edge-case / adversarial values."""
    if domain.data_type in ("alpha", "unknown"):
        candidates = [
            "",
            " " * domain.max_length,
            "9" * domain.max_length,
            "A" * domain.max_length,
        ]
        return rng.choice(candidates)

    candidates: list[int | float] = [0]
    if domain.max_value is not None:
        candidates.append(domain.max_value)
    if domain.min_value is not None:
        candidates.append(domain.min_value)
    # All nines
    nines = 10 ** domain.max_length - 1 if domain.max_length > 0 else 99999
    candidates.append(nines)
    if domain.signed:
        candidates.append(-nines)

    return rng.choice(candidates)


def format_value_for_cobol(domain: VariableDomain, value: str | int | float) -> str:
    """Format a value for use in COBOL INIT records (string representation).

    When ``data_type`` is ``unknown`` (e.g. for variables defined inline
    in the program source rather than in a copybook), the formatter
    infers numeric vs alpha from the value itself rather than defaulting
    to alpha padding. Without this, an 88-level literal like
    ``APPL-AOK VALUE 0`` gets written as the string ``'0         '``
    (space-padded) and the runtime ``MOVE`` into a ``PIC S9(9) COMP``
    field either fails or produces garbage.
    """
    if domain.data_type == "alpha":
        s = str(value)
        if domain.max_length > 0:
            s = s[:domain.max_length].ljust(domain.max_length)
        return s

    if domain.data_type == "unknown":
        # Infer from the value's type. Numeric values format as numbers,
        # strings fall back to the alpha path.
        if isinstance(value, bool):
            return "1" if value else "0"
        if isinstance(value, int):
            return str(value)
        if isinstance(value, float):
            return f"{value:.{max(1, domain.precision)}f}" if domain.precision > 0 else str(value)
        s = str(value)
        if domain.max_length > 0:
            s = s[:domain.max_length].ljust(domain.max_length)
        return s

    # Numeric: format appropriately
    value = _coerce_numeric_value(value, domain.precision)
    if domain.precision > 0:
        return f"{float(value):.{domain.precision}f}"
    return str(int(value))
