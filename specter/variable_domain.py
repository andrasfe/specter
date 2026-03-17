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
# Construction: build_variable_domains()
# ---------------------------------------------------------------------------

def build_variable_domains(
    var_report: VariableReport,
    copybook_records: list[CopybookRecord] | None = None,
    stub_mapping: dict[str, list[str]] | None = None,
) -> dict[str, VariableDomain]:
    """Build unified domain model by merging PIC, AST, stub, and heuristic info.

    Args:
        var_report: VariableReport from variable_extractor.
        copybook_records: Parsed copybook records (from parse_copybook).
        stub_mapping: Operation → status variable mapping.

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
        return rng.choice(["Y", "N"])

    # generic — fall through to random_valid
    return _generate_random_valid(domain, rng)


def _generate_random_valid(domain: VariableDomain, rng: random.Random) -> str | int | float:
    """Generate a random value within PIC constraints."""
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
    """Format a value for use in COBOL INIT records (string representation)."""
    if domain.data_type in ("alpha", "unknown"):
        s = str(value)
        # Right-pad to max_length
        if domain.max_length > 0:
            s = s[:domain.max_length].ljust(domain.max_length)
        return s

    # Numeric: format appropriately
    if domain.precision > 0:
        return f"{float(value):.{domain.precision}f}"
    return str(int(value)) if isinstance(value, (int, float)) else str(value)
