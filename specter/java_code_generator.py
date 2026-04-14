"""Generate a Maven Java project from a COBOL Program AST.

COBOL paragraphs are grouped by section (thousands-bucket of the leading
numeric prefix) into ``SectionBase`` subclasses.  Each section is a single
``.java`` file whose methods contain the translated paragraph logic.
A top-level ``<ProgramId>Program`` class instantiates all sections
(which register their paragraphs) and exposes a ``run()`` entry point.

The generated project is self-contained and can be built with
``mvn package``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from .code_generator import (
    _FIGURATIVE_SOURCES,
    _PARAGRAPH_ORDER,
    _get_thru_range,
    _oneline,
    _strip_cobol_comments,
    _strip_comments_arithmetic,
    _strip_comments_condition,
    _tokenize_cobol_vars,
    _var_name,
    _vk,
)
from .condition_parser import parse_when_value
from .java_condition_parser import cobol_condition_to_java, resolve_when_value_java
from .java_templates.docker import DOCKER_COMPOSE_YML, DOCKERFILE
from .java_templates.equivalence import (
    COBOL_SNAPSHOT_JAVA,
    EQUIVALENCE_ASSERT_JAVA,
)
from .java_templates.integration_test import (
    INTEGRATION_POM_XML,
    MOCKITO_INTEGRATION_TEST_JAVA,
)
from .java_templates.pom_xml import POM_XML
from .java_templates.runtime import (
    APP_CONFIG_JAVA,
    CICS_PROGRAM_JAVA,
    COBOL_RUNTIME_JAVA,
    DEFAULT_STUB_EXECUTOR_JAVA,
    GOBACK_SIGNAL_JAVA,
    JDBC_STUB_EXECUTOR_JAVA,
    MAIN_JAVA,
    PARAGRAPH_JAVA,
    PARAGRAPH_REGISTRY_JAVA,
    PROGRAM_STATE_JAVA,
    SECTION_BASE_JAVA,
    STUB_EXECUTOR_JAVA,
)
from .java_templates.terminal import (
    BMS_SCREEN_JAVA,
    CICS_RETURN_SIGNAL_JAVA,
    HEADLESS_SCREEN_JAVA,
    MULTI_PROGRAM_RUNNER_JAVA,
    SCREEN_LAYOUT_JAVA,
    TERMINAL_MAIN_JAVA,
    TERMINAL_SCREEN_JAVA,
    TERMINAL_STUB_EXECUTOR_JAVA,
    XCTL_SIGNAL_JAVA,
)
from .models import Program, Statement
from .variable_extractor import VariableReport, extract_variables

# ---------------------------------------------------------------------------
# 88-level mutual exclusion detection
# ---------------------------------------------------------------------------

# Map from variable name to set of sibling names (populated per-program).
_88_LEVEL_SIBLINGS: dict[str, set[str]] = {}


def _detect_88_level_groups(program: Program) -> dict[str, set[str]]:
    """Detect 88-level sibling groups from SET TO TRUE targets.

    In COBOL, 88-level variables on the same parent field are mutually
    exclusive.  We detect sibling groups by collecting all variables that
    are targets of ``SET X TO TRUE`` and grouping them by shared naming
    prefix (the part before the last hyphen-separated component varies).

    We then validate each candidate group against EVALUATE TRUE usage:
    at least 2 members must appear as simple conditions in the same
    EVALUATE TRUE statement.

    Returns a dict mapping each variable to its set of siblings.
    """
    # Step 1: collect all SET TO TRUE targets
    set_true_vars: set[str] = set()
    _VN = r"[A-Z0-9][A-Z0-9-]*"

    def _collect_set_true(stmts: list[Statement]) -> None:
        for s in stmts:
            if s.type == "SET":
                m = re.search(
                    rf"SET\s+({_VN})\s+TO\s+TRUE", s.text, re.IGNORECASE
                )
                if m:
                    set_true_vars.add(m.group(1).upper())
            if s.children:
                _collect_set_true(s.children)

    for para in program.paragraphs:
        _collect_set_true(para.statements)

    # Step 2: collect EVALUATE TRUE simple conditions
    eval_groups: list[set[str]] = []

    def _scan_evaluate(stmt: Statement) -> None:
        subject = stmt.attributes.get("subject", "TRUE")
        if subject.upper() != "TRUE":
            return
        when_vars: set[str] = set()
        for child in stmt.children:
            if child.type != "WHEN":
                continue
            vt, is_other = parse_when_value(child.text)
            if is_other:
                continue
            vt_stripped = vt.strip()
            if re.match(r"^[A-Z0-9][A-Z0-9-]*$", vt_stripped, re.IGNORECASE):
                v = vt_stripped.upper()
                # Only include if also a SET TO TRUE target
                if v in set_true_vars:
                    when_vars.add(v)
        if len(when_vars) >= 2:
            eval_groups.append(when_vars)

    def _walk(stmts: list[Statement]) -> None:
        for s in stmts:
            if s.type == "EVALUATE":
                _scan_evaluate(s)
            if s.children:
                _walk(s.children)

    for para in program.paragraphs:
        _walk(para.statements)

    # Step 3: split each EVALUATE group by naming prefix to separate
    # different 88-level families that appear in the same EVALUATE.
    # The first hyphen-separated component is used as the prefix.
    refined_groups: list[set[str]] = []
    for eg in eval_groups:
        by_prefix: dict[str, set[str]] = {}
        for v in eg:
            prefix = v.split("-")[0] if "-" in v else v
            by_prefix.setdefault(prefix, set()).add(v)

        has_multi = any(len(s) >= 2 for s in by_prefix.values())
        if has_multi:
            # Keep only sub-groups with 2+ members
            for sub in by_prefix.values():
                if len(sub) >= 2:
                    refined_groups.append(sub)
        elif len(eg) >= 3 and len(by_prefix) == len(eg):
            # All singletons with 3+ members — likely one 88-level
            # family with non-prefix-matching names (e.g. COULD-NOT-...,
            # LOCKED-BUT-..., DATA-WAS-...)
            refined_groups.append(eg)

    # Step 4: supplementary prefix-based detection for SET TO TRUE
    # targets not found in any EVALUATE group.  Variables sharing a
    # 2-component prefix (e.g. "CDEMO-PGM") are likely 88-level siblings.
    eval_covered: set[str] = set()
    for rg in refined_groups:
        eval_covered |= rg

    by_prefix2: dict[str, set[str]] = {}
    for v in set_true_vars:
        parts = v.split("-")
        if len(parts) >= 3:
            prefix = "-".join(parts[:2])
            by_prefix2.setdefault(prefix, set()).add(v)
    for prefix, members in by_prefix2.items():
        if len(members) >= 2:
            # Only add members not already in a refined group, OR
            # add the whole group if it improves coverage
            uncovered = members - eval_covered
            if uncovered and len(members) >= 2:
                refined_groups.append(members)

    # Step 4b: detect boolean opposite pairs among SET TO TRUE targets.
    # Variables like PFK-VALID/PFK-INVALID, INPUT-OK/INPUT-ERROR share
    # a common stem with opposite suffixes and are 88-level siblings.
    _OPPOSITE_SUFFIXES = [
        ("-VALID", "-INVALID"), ("-OK", "-ERROR"),
        ("-ON", "-OFF"), ("-YES", "-NO"),
        ("-TRUE", "-FALSE"), ("-ACTIVE", "-INACTIVE"),
        ("-OPEN", "-CLOSED"), ("-FOUND", "-NOT-FOUND"),
    ]
    for v in set_true_vars:
        if v in eval_covered:
            continue
        vu = v.upper()
        for pos_sfx, neg_sfx in _OPPOSITE_SUFFIXES:
            for my_sfx, other_sfx in [(pos_sfx, neg_sfx), (neg_sfx, pos_sfx)]:
                if vu.endswith(my_sfx):
                    partner = vu[: -len(my_sfx)] + other_sfx
                    if partner in set_true_vars:
                        pair = {v, partner}
                        refined_groups.append(pair)
                        eval_covered |= pair
                    break

    # Step 5: build sibling map — use the largest refined group per var
    var_best: dict[str, set[str]] = {}
    for rg in refined_groups:
        for v in rg:
            existing = var_best.get(v)
            if existing is None or len(rg) > len(existing):
                var_best[v] = rg

    siblings: dict[str, set[str]] = {}
    for var, group in var_best.items():
        sibs = group - {var}
        if sibs:
            siblings[var] = sibs

    return siblings


# ---------------------------------------------------------------------------
# Java figurative constants (double-quoted strings)
# ---------------------------------------------------------------------------

_FIGURATIVE_SOURCES_JAVA: dict[str, str] = {
    "SPACES": '" "',
    "SPACE": '" "',
    "LOW-VALUES": '"\\u0000"',
    "LOW-VALUE": '"\\u0000"',
    "HIGH-VALUES": '"\\u00FF"',
    "HIGH-VALUE": '"\\u00FF"',
    "ZEROS": "0",
    "ZERO": "0",
    "ZEROES": "0",
}

# ---------------------------------------------------------------------------
# Name helpers
# ---------------------------------------------------------------------------


def _sanitize_java_name(name: str) -> str:
    """Convert a COBOL paragraph name to a valid Java class name.

    ``MAIN-PARA`` becomes ``Para_MAIN_PARA``.
    ``1000-INITIALIZE`` becomes ``Para_1000_INITIALIZE``.
    """
    cleaned = re.sub(
        r"[^A-Z0-9_]",
        "_",
        name.upper().replace("-", "_").replace(".", "_"),
    )
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return "Para_" + cleaned


def _sanitize_method_name(name: str) -> str:
    """Convert a COBOL paragraph name to a valid Java method name.

    ``1000-INITIALIZE`` becomes ``do_1000_INITIALIZE``.
    """
    cleaned = re.sub(
        r"[^A-Z0-9_]",
        "_",
        name.upper().replace("-", "_").replace(".", "_"),
    )
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return "do_" + cleaned


def _section_key(para_name: str) -> str:
    """Extract section key from paragraph name for grouping.

    Leading digit determines the thousands bucket (0-9).
    Non-numeric names go to 'Main'.
    """
    m = re.match(r"^(\d)", para_name)
    if m:
        return m.group(1)
    return "Main"


def _section_class_name(key: str) -> str:
    """Return the Java class name for a section key."""
    return f"Section{key}"


def _dq(value: str) -> str:
    """Escape a string for safe use inside double-quoted Java strings."""
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _java_string_literal(text: str) -> str:
    """Wrap *text* as a Java double-quoted string literal."""
    return f'"{_dq(text)}"'


def _java_numeric_literal(token: str) -> str:
    """Render a COBOL numeric token as a Java-safe numeric expression."""
    t = token.strip()
    if re.match(r"^[+-]?\d+$", t):
        digits = t.lstrip("+-").lstrip("0") or "0"
        # Keep small integer literals native for readability/perf.
        if len(digits) <= 18:
            n = int(t)
            if -2147483648 <= n <= 2147483647:
                return str(n)
            if -9223372036854775808 <= n <= 9223372036854775807:
                return f"{n}L"
        return f'CobolRuntime.toNum("{t}")'

    if re.match(r"^[+-]?\d+\.\d*$", t):
        return f'CobolRuntime.toNum("{t}")'

    return t


# ---------------------------------------------------------------------------
# Source resolution
# ---------------------------------------------------------------------------


def _strip_of_qualification(text: str) -> str:
    """Strip COBOL OF qualification: ``FIELD OF RECORD`` → ``FIELD``."""
    return re.sub(
        r"\s+OF\s+[A-Z][A-Z0-9-]*", "", text, flags=re.IGNORECASE
    ).strip()


def _resolve_source_java(source: str) -> str:
    """Resolve a MOVE source to a Java expression."""
    s = source.strip()

    # Strip leading ALL (MOVE ALL 'X' etc.)
    s = re.sub(r"^ALL\s+", "", s, flags=re.IGNORECASE).strip()

    # FUNCTION UPPER-CASE / LOWER-CASE
    m = re.match(
        r"FUNCTION\s+UPPER-CASE\s*\((.+)\)", s, re.IGNORECASE
    )
    if m:
        inner = _strip_of_qualification(m.group(1).strip())
        varname = _vk(inner)
        return f'String.valueOf(state.get("{varname}")).toUpperCase()'
    m = re.match(
        r"FUNCTION\s+LOWER-CASE\s*\((.+)\)", s, re.IGNORECASE
    )
    if m:
        inner = _strip_of_qualification(m.group(1).strip())
        varname = _vk(inner)
        return f'String.valueOf(state.get("{varname}")).toLowerCase()'

    # FUNCTION CURRENT-DATE
    if re.match(r"FUNCTION\s+CURRENT-DATE", s, re.IGNORECASE):
        return (
            'new java.text.SimpleDateFormat("yyyyMMddHHmmssSSS")'
            ".format(new java.util.Date())"
        )

    # Figurative constant
    upper = s.upper()
    if upper in _FIGURATIVE_SOURCES_JAVA:
        return str(_FIGURATIVE_SOURCES_JAVA[upper])

    # Quoted string literal -- convert single→double quotes
    if s.startswith("'") and s.endswith("'"):
        inner = s[1:-1]
        return _java_string_literal(inner)

    # Numeric literal
    if re.match(r"^[+-]?\d+\.?\d*$", s):
        return _java_numeric_literal(s)

    # LENGTH OF variable
    m = re.match(r"LENGTH\s+OF\s+(.+)", s, re.IGNORECASE)
    if m:
        varname = _vk(m.group(1).strip())
        return f'String.valueOf(state.get("{varname}")).length()'

    # Strip OF qualification for simple variable references
    s = _strip_of_qualification(s)

    # Variable with subscript like FOO(1:2)
    m = re.match(r"([A-Z][A-Z0-9-]*)\((\d+):(\d+)\)", s, re.IGNORECASE)
    if m:
        varname = _vk(m.group(1))
        start = int(m.group(2)) - 1  # COBOL is 1-based
        length = int(m.group(3))
        end = start + length
        return (
            f'(String.valueOf(state.get("{varname}")).length() > {start} ? '
            f'String.valueOf(state.get("{varname}"))'
            f".substring({start}, Math.min({end}, "
            f'String.valueOf(state.get("{varname}")).length())) : "")'
        )

    # Variable reference
    varname = _vk(s)
    return f'state.get("{varname}")'


# ---------------------------------------------------------------------------
# Java code builder
# ---------------------------------------------------------------------------


class _JavaCodeBuilder:
    """Builds Java source lines with brace-delimited blocks."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self._indent: int = 0
        self._loop_counter: int = 0
        self._branch_counter: int = 0
        self._temp_counter: int = 0
        self.branch_meta: dict[int, dict] = {}
        self.current_para: str = ""
        # Maps each 88-level child name to (parent_var, activating_value)
        # so bare COBOL conditions like ``IF APPL-AOK`` can be rewritten to
        # parent-value comparisons. Mirrors ``_CodeBuilder.level_88_map`` in
        # the Python generator.
        self.level_88_map: dict[str, tuple[str, object]] = {}
        # Maps each variable name to its PIC info (length + kind) so the
        # generated Java can truncate input values to COBOL field widths.
        # Built in generate_java_project from copybooks + inline source.
        self.pic_info: dict[str, dict[str, object]] = {}
        # Maps each FD file name to its ``FILE STATUS IS <var>`` variable
        # name. The COBOL mock's OPEN/READ/WRITE/CLOSE stubs always do
        # ``MOVE MOCK-ALPHA-STATUS TO <status-var>`` — including on EOF,
        # when MOCK-ALPHA-STATUS is SPACES. Java's applyStubOutcome can
        # only set variables named in the outcome pairs; with no outcome,
        # the status var keeps its stale value. Emitting an explicit
        # ``state.put(status-var, "")`` BEFORE applyStubOutcome mirrors
        # the COBOL "move SPACES when exhausted" behaviour so the two
        # runtimes stay aligned even for tests with empty stub FIFOs.
        self.file_status_map: dict[str, str] = {}

    # -- Branch / loop counters -------------------------------------------

    def next_branch_id(self) -> int:
        """Return a unique branch ID for instrumentation."""
        self._branch_counter += 1
        return self._branch_counter

    def next_loop_var(self) -> str:
        """Return a unique loop counter variable name."""
        self._loop_counter += 1
        return f"_lc{self._loop_counter}"

    def next_temp_var(self, prefix: str) -> str:
        """Return a unique temporary variable name with the given prefix."""
        self._temp_counter += 1
        return f"{prefix}{self._temp_counter}"

    # -- Output primitives ------------------------------------------------

    def stmt(self, text: str) -> None:
        """Emit a Java statement with semicolon and indentation."""
        self.lines.append("    " * self._indent + text + ";")

    def line(self, text: str) -> None:
        """Emit a line with indentation (no semicolon -- for control flow)."""
        self.lines.append("    " * self._indent + text)

    def comment(self, text: str) -> None:
        """Emit a Java line comment."""
        self.lines.append("    " * self._indent + "// " + text)

    def blank(self) -> None:
        self.lines.append("")

    # -- Block management -------------------------------------------------

    def open_block(self, header: str = "") -> None:
        """Emit an opening brace, optionally preceded by *header*."""
        if header:
            self.lines.append("    " * self._indent + header + " {")
        else:
            self.lines.append("    " * self._indent + "{")
        self._indent += 1

    def close_block(self, suffix: str = "") -> None:
        """Emit a closing brace with optional *suffix* (e.g. ``else``)."""
        self._indent = max(0, self._indent - 1)
        self.lines.append("    " * self._indent + "}" + suffix)

    # -- Bulk output ------------------------------------------------------

    def build(self) -> str:
        return "\n".join(self.lines) + "\n"


# ---------------------------------------------------------------------------
# Statement generators  (parallel to code_generator._gen_*)
# ---------------------------------------------------------------------------


def _gen_move_java(cb: _JavaCodeBuilder, stmt: Statement) -> None:
    source = stmt.attributes.get("source", "")
    targets = stmt.attributes.get("targets", "")

    if not source or not targets:
        m = re.search(r"MOVE\s+(.+?)\s+TO\s+(.+)", stmt.text, re.IGNORECASE)
        if m:
            source = m.group(1).strip()
            targets = m.group(2).strip()
        else:
            cb.comment(f"MOVE: {_oneline(stmt.text)}")
            return

    # The cobalt parser strips reference modifiers (``Y(1:1)``) when it
    # records ``targets`` in the AST attributes — it preserves the full
    # form only in ``stmt.text``. Re-attach any ``(start:length)`` suffix
    # from the raw text so the substring branch below fires correctly.
    if "(" not in targets and stmt.text:
        m_full = re.search(
            r"\bTO\s+([A-Z][A-Z0-9-]*\([\d:,\s]+\)(?:\s+[A-Z][A-Z0-9-]*(?:\([\d:,\s]+\))?)*)",
            stmt.text, re.IGNORECASE,
        )
        if m_full:
            targets = m_full.group(1).strip()

    is_move_all = bool(re.search(r"MOVE\s+ALL\s+", stmt.text, re.IGNORECASE))
    if is_move_all:
        source = re.sub(r"^ALL\s+", "", source, flags=re.IGNORECASE).strip()

    resolved = _resolve_source_java(source)
    # Strip OF qualifications from targets before tokenizing:
    # "ERRMSGO OF COSGN0AO" → "ERRMSGO", not three tokens
    clean_targets = _strip_of_qualification(_strip_cobol_comments(targets))
    for target_tok in _tokenize_cobol_vars(clean_targets):
        target_tok = target_tok.strip().rstrip(".")
        if not target_tok:
            continue
        tname = _var_name(target_tok)

        # Subscript targets — check the *raw* target_tok before
        # ``_var_name`` strips the ``(start:length)`` reference modifier.
        m = re.match(r"([A-Z][A-Z0-9-]*)\((\d+):(\d+)\)", target_tok, re.IGNORECASE)
        if m:
            varname = m.group(1)
            start = int(m.group(2)) - 1
            length = int(m.group(3))
            end = start + length
            cb.stmt(
                f'String _v = String.valueOf(state.get("{varname}"))'
            )
            cb.stmt(
                f'state.put("{varname}", '
                f"_v.substring(0, {start}) + "
                f"String.valueOf({resolved}).substring(0, Math.min({length}, "
                f"String.valueOf({resolved}).length())) + "
                f"_v.substring(Math.min({end}, _v.length())))"
            )
        elif is_move_all:
            cb.stmt(f'String _fill = String.valueOf({resolved})')
            cb.stmt(f'String _cur = String.valueOf(state.get("{tname}"))')
            cb.stmt("int _flen = Math.max(_cur.length(), 10)")
            cb.stmt(
                f'state.put("{tname}", _fill.repeat((_flen / '
                f"Math.max(1, _fill.length())) + 1).substring(0, _flen))"
            )
        else:
            cb.stmt(f'state.put("{tname}", {resolved})')


def _gen_compute_java(cb: _JavaCodeBuilder, stmt: Statement) -> None:
    target = stmt.attributes.get("target", "")
    expression = stmt.attributes.get("expression", "")

    if not target or not expression:
        _compute_re = re.compile(
            r"COMPUTE\s+([A-Z0-9][A-Z0-9-]*(?:\s*\([^)]*\))?)\s*"
            r"(?:ROUNDED\s*)?(?:=|EQUAL)\s*(.+)",
            re.IGNORECASE,
        )
        m = _compute_re.search(stmt.text)
        if m:
            raw_target = m.group(1).strip()
            target = re.sub(r"\s*\(.*\)", "", raw_target).upper()
            expression = m.group(2).strip().rstrip(".")
        else:
            cb.comment(f"COMPUTE: {_oneline(stmt.text)}")
            return

    # Strip COBOL inline comments
    if "*>" in expression:
        candidates = []

        s1 = _strip_cobol_comments(expression)
        s1 = " ".join(s1.split()).strip().rstrip(".")
        while s1 and s1[-1] in "+-*/":
            s1 = s1[:-1].strip()
        if s1:
            candidates.append(s1)

        s2 = re.sub(r"\*>.*", "", expression)
        s2 = " ".join(s2.split()).strip().rstrip(".")
        while s2 and s2[-1] in "+-*/":
            s2 = s2[:-1].strip()
        if s2 and s2 not in candidates:
            candidates.append(s2)

        s3 = _strip_comments_arithmetic(expression)
        s3 = " ".join(s3.split()).strip().rstrip(".")
        while s3 and s3[-1] in "+-*/":
            s3 = s3[:-1].strip()
        if s3 and s3 not in candidates:
            candidates.append(s3)

        expression = candidates[0] if candidates else ""

    if not expression:
        cb.comment("COMPUTE: empty expression after comment strip")
        return

    # Balance parentheses
    open_count = expression.count("(") - expression.count(")")
    if open_count > 0:
        expression += ")" * open_count

    # Preprocess: resolve complex COBOL constructs to Java snippets using
    # placeholders so replace_var won't mangle them.
    expr = expression
    _placeholders: dict[str, str] = {}
    _ph_counter = 0

    def _ph(java_code: str) -> str:
        nonlocal _ph_counter
        key = f"__PH{_ph_counter}__"
        _ph_counter += 1
        _placeholders[key] = java_code
        return key

    # LENGTH OF <var>
    expr = re.sub(
        r"LENGTH\s+OF\s+([A-Z][A-Z0-9-]*)",
        lambda m: _ph(
            f'String.valueOf(state.get("{_vk(m.group(1))}")).length()'
        ),
        expr,
        flags=re.IGNORECASE,
    )

    # FUNCTION calls
    def _resolve_function_java(text: str) -> str:
        while True:
            positions = [
                m.start()
                for m in re.finditer(r"FUNCTION\s+", text, re.IGNORECASE)
            ]
            if not positions:
                break
            resolved_any = False
            for pos in reversed(positions):
                m = re.match(
                    r"FUNCTION\s+([\w-]+)\s*\(", text[pos:], re.IGNORECASE
                )
                if not m:
                    continue
                fname = m.group(1)
                paren_start = pos + m.end() - 1
                depth = 0
                end_idx = None
                for i in range(paren_start, len(text)):
                    if text[i] == "(":
                        depth += 1
                    elif text[i] == ")":
                        depth -= 1
                        if depth == 0:
                            end_idx = i + 1
                            break
                if end_idx is None:
                    continue
                inner = text[paren_start + 1 : end_idx - 1]
                upper_fname = fname.upper()
                if "INTEGER-OF-DATE" in upper_fname:
                    inner_var = re.search(
                        r"([A-Z][A-Z0-9-]*)", inner, re.IGNORECASE
                    )
                    varname = inner_var.group(1).upper() if inner_var else "0"
                    replacement = _ph(
                        f'CobolRuntime.toNum(state.get("{varname}"))'
                    )
                elif "DATE-OF-INTEGER" in upper_fname:
                    replacement = _ph(_resolve_function_java(inner))
                elif "NUMVAL" in upper_fname:
                    cleaned = _strip_of_qualification(inner)
                    varname = _vk(cleaned)
                    replacement = _ph(
                        f'CobolRuntime.toNum(state.get("{varname}"))'
                    )
                elif "UPPER-CASE" in upper_fname:
                    cleaned = _strip_of_qualification(inner)
                    varname = _vk(cleaned)
                    replacement = _ph(
                        f'String.valueOf(state.get("{varname}")).toUpperCase()'
                    )
                elif "LOWER-CASE" in upper_fname:
                    cleaned = _strip_of_qualification(inner)
                    varname = _vk(cleaned)
                    replacement = _ph(
                        f'String.valueOf(state.get("{varname}")).toLowerCase()'
                    )
                elif "CURRENT-DATE" in upper_fname:
                    replacement = _ph(
                        'new java.text.SimpleDateFormat("yyyyMMddHHmmssSSS")'
                        '.format(new java.util.Date())'
                    )
                else:
                    replacement = _ph("0")
                text = text[:pos] + replacement + text[end_idx:]
                resolved_any = True
                break
            if not resolved_any:
                break
        return text

    expr = _resolve_function_java(expr)

    # Strip remaining bare FUNCTION keyword
    expr = re.sub(r"\bFUNCTION\b\s*", "", expr, flags=re.IGNORECASE)

    # VAR OF QUALIFIER -> use the first identifier
    expr = re.sub(
        r"([A-Z][A-Z0-9-]*)\s+OF\s+[A-Z][A-Z0-9-]*",
        r"\1",
        expr,
        flags=re.IGNORECASE,
    )

    # Convert remaining variable references to Java
    def replace_var(m: re.Match) -> str:
        name = m.group(1)
        upper = name.upper()
        if re.match(r"^__PH\d+__$", name):
            return name
        if re.match(r"^[+-]?\d+\.?\d*$", name):
            return _java_numeric_literal(name)
        if upper in _FIGURATIVE_SOURCES_JAVA:
            return str(_FIGURATIVE_SOURCES_JAVA[upper])
        return f'CobolRuntime.toNum(state.get("{upper}"))'

    java_expr = re.sub(
        r"([A-Z_][A-Z0-9_-]*)(?:\s*\([^)]*\))?",
        replace_var,
        expr,
        flags=re.IGNORECASE,
    )

    # Restore placeholders
    for key, val in _placeholders.items():
        java_expr = java_expr.replace(key, val)

    # Strip trailing arithmetic operators (from incomplete comment stripping)
    java_expr = java_expr.strip()
    while java_expr and java_expr[-1] in "+-*/":
        java_expr = java_expr[:-1].strip()
    # Also strip trailing operators before closing parens
    java_expr = re.sub(r"[+\-*/]\s*\)", ")", java_expr)

    if not java_expr:
        cb.comment("COMPUTE: empty expression after cleanup")
        return

    # Division handling
    has_div = "/" in java_expr
    rounded = "ROUNDED" in stmt.text.upper()
    if has_div and not rounded:
        cb.stmt(f'state.put("{_vk(target)}", (long)({java_expr}))')
    elif has_div and rounded:
        cb.stmt(f'state.put("{_vk(target)}", Math.round({java_expr}))')
    else:
        cb.stmt(f'state.put("{_vk(target)}", {java_expr})')


def _gen_add_java(cb: _JavaCodeBuilder, stmt: Statement) -> None:
    text = _strip_cobol_comments(stmt.text)
    m_giving = re.search(r"ADD\s+(.+?)\s+GIVING\s+(.+)", text, re.IGNORECASE)
    m_to = re.search(r"ADD\s+(.+?)\s+TO\s+(.+)", text, re.IGNORECASE)
    if m_giving:
        addends_str = m_giving.group(1).strip()
        target_str = re.sub(
            r"\s+ROUNDED\b.*",
            "",
            m_giving.group(2).strip().rstrip("."),
            flags=re.IGNORECASE,
        )
        tname = _var_name(target_str)
        parts: list[str] = []
        for tok in _tokenize_cobol_vars(addends_str):
            if re.match(r"^[+-]?\d+\.?\d*$", tok):
                parts.append(_java_numeric_literal(tok))
            elif tok.upper() not in ("TO", "GIVING", "ROUNDED"):
                vname = _var_name(tok)
                parts.append(f'CobolRuntime.toNum(state.get("{vname}"))')
        if parts:
            cb.stmt(f'state.put("{tname}", {" + ".join(parts)})')
        else:
            cb.comment(f"ADD: {_oneline(stmt.text)}")
    elif m_to:
        addends_str = m_to.group(1).strip()
        targets_str = m_to.group(2).strip().rstrip(".")

        add_parts: list[str] = []
        for tok in _tokenize_cobol_vars(addends_str):
            if re.match(r"^[+-]?\d+\.?\d*$", tok):
                add_parts.append(_java_numeric_literal(tok))
            elif tok.upper() not in ("TO", "GIVING", "ROUNDED"):
                add_parts.append(
                    f'CobolRuntime.toNum(state.get("{_var_name(tok)}"))'
                )
        val = " + ".join(add_parts) if add_parts else "0"

        for tok in _tokenize_cobol_vars(targets_str):
            tname = _var_name(tok)
            if tname and tname not in ("TO", "GIVING", "ROUNDED"):
                cb.stmt(
                    f'state.put("{tname}", '
                    f'CobolRuntime.toNum(state.get("{tname}")) + {val})'
                )
    else:
        cb.comment(f"ADD: {_oneline(stmt.text)}")


def _gen_subtract_java(cb: _JavaCodeBuilder, stmt: Statement) -> None:
    text = _strip_cobol_comments(stmt.text)
    m_giving = re.search(
        r"SUBTRACT\s+(.+?)\s+FROM\s+(.+?)\s+GIVING\s+(.+)",
        text,
        re.IGNORECASE,
    )
    m = re.search(r"SUBTRACT\s+(.+?)\s+FROM\s+(.+)", text, re.IGNORECASE)
    if m_giving:
        subtrahend = m_giving.group(1).strip()
        minuend = m_giving.group(2).strip().rstrip(".")
        target_str = re.sub(
            r"\s+ROUNDED\b.*",
            "",
            m_giving.group(3).strip().rstrip("."),
            flags=re.IGNORECASE,
        )
        tname = _var_name(target_str)

        def _sv(v: str) -> str:
            v = v.strip()
            if re.match(r"^[+-]?\d+\.?\d*$", v):
                return _java_numeric_literal(v)
            return f'CobolRuntime.toNum(state.get("{_var_name(v)}"))'

        cb.stmt(f'state.put("{tname}", {_sv(minuend)} - {_sv(subtrahend)})')
    elif m:
        subtrahend = m.group(1).strip()
        targets_str = m.group(2).strip().rstrip(".")

        if re.match(r"^-?\d+\.?\d*$", subtrahend):
            val = _java_numeric_literal(subtrahend)
        else:
            val = f'CobolRuntime.toNum(state.get("{_var_name(subtrahend)}"))'

        for tok in _tokenize_cobol_vars(targets_str):
            tname = _var_name(tok)
            if tname and tname not in ("FROM", "GIVING", "ROUNDED"):
                cb.stmt(
                    f'state.put("{tname}", '
                    f'CobolRuntime.toNum(state.get("{tname}")) - {val})'
                )
    else:
        cb.comment(f"SUBTRACT: {_oneline(stmt.text)}")


def _gen_multiply_java(cb: _JavaCodeBuilder, stmt: Statement) -> None:
    _text = _strip_cobol_comments(stmt.text)
    m_giving = re.search(
        r"MULTIPLY\s+(\S+)\s+BY\s+(\S+)\s+GIVING\s+(.+)",
        _text,
        re.IGNORECASE,
    )
    m = re.search(r"MULTIPLY\s+(.+?)\s+BY\s+(.+)", _text, re.IGNORECASE)
    if m_giving:
        f1 = m_giving.group(1).strip().rstrip(".")
        f2 = m_giving.group(2).strip().rstrip(".")
        target_str = re.sub(
            r"\s+ROUNDED\b.*",
            "",
            m_giving.group(3).strip().rstrip("."),
            flags=re.IGNORECASE,
        )
        tname = _var_name(target_str)

        def _mv(v: str) -> str:
            v = v.strip()
            if re.match(r"^[+-]?\d+\.?\d*$", v):
                return _java_numeric_literal(v)
            return f'CobolRuntime.toNum(state.get("{_var_name(v)}"))'

        cb.stmt(f'state.put("{tname}", {_mv(f1)} * {_mv(f2)})')
    elif m:
        factor = m.group(1).strip()
        targets_str = m.group(2).strip().rstrip(".")
        if re.match(r"^-?\d+\.?\d*$", factor):
            val = _java_numeric_literal(factor)
        else:
            val = f'CobolRuntime.toNum(state.get("{_var_name(factor)}"))'
        for tok in _tokenize_cobol_vars(targets_str):
            tname = _var_name(tok)
            if tname and tname not in ("GIVING", "ROUNDED"):
                cb.stmt(
                    f'state.put("{tname}", '
                    f'CobolRuntime.toNum(state.get("{tname}")) * {val})'
                )
    else:
        cb.comment(f"MULTIPLY: {_oneline(stmt.text)}")


def _gen_divide_java(cb: _JavaCodeBuilder, stmt: Statement) -> None:
    def _div_val(v: str) -> str:
        v = v.strip().rstrip(".")
        v = re.sub(r"\s+ROUNDED$", "", v, flags=re.IGNORECASE)
        if re.match(r"^[+-]?\d+\.?\d*$", v):
            return _java_numeric_literal(v)
        vn = _vk(re.sub(r"\s*\(.*", "", v))
        return f'CobolRuntime.toNum(state.get("{vn}"))'

    m_by = re.search(
        r"DIVIDE\s+(.+?)\s+BY\s+(.+?)\s+GIVING\s+(\S+)"
        r"(?:\s+REMAINDER\s+(\S+))?",
        stmt.text,
        re.IGNORECASE,
    )
    m_into_giving = re.search(
        r"DIVIDE\s+(.+?)\s+INTO\s+(\S+)\s+GIVING\s+(\S+)"
        r"(?:\s+REMAINDER\s+(\S+))?",
        stmt.text,
        re.IGNORECASE,
    )
    m_into = re.search(
        r"DIVIDE\s+(.+?)\s+INTO\s+(.+)", stmt.text, re.IGNORECASE
    )
    if m_by:
        dividend = _div_val(m_by.group(1))
        divisor = _div_val(m_by.group(2))
        tname = _vk(
            re.sub(r"\s*\(.*", "", m_by.group(3).strip().rstrip("."))
        )
        tname = re.sub(r"\s+ROUNDED$", "", tname, flags=re.IGNORECASE)
        cb.stmt(
            f'state.put("{tname}", '
            f"(long)({dividend} / "
            f"Math.max(1, {divisor})))"
        )
        if m_by.group(4):
            rname = _vk(
                re.sub(r"\s*\(.*", "", m_by.group(4).strip().rstrip("."))
            )
            cb.stmt(
                f'state.put("{rname}", '
                f"(long)({dividend} % "
                f"Math.max(1, {divisor})))"
            )
    elif m_into_giving:
        divisor = _div_val(m_into_giving.group(1))
        dividend = _div_val(m_into_giving.group(2))
        tname = _vk(
            re.sub(
                r"\s*\(.*",
                "",
                m_into_giving.group(3).strip().rstrip("."),
            )
        )
        tname = re.sub(r"\s+ROUNDED$", "", tname, flags=re.IGNORECASE)
        cb.stmt(
            f'state.put("{tname}", '
            f"(long)({dividend} / "
            f"Math.max(1, {divisor})))"
        )
        if m_into_giving.group(4):
            rname = _vk(
                re.sub(
                    r"\s*\(.*",
                    "",
                    m_into_giving.group(4).strip().rstrip("."),
                )
            )
            cb.stmt(
                f'state.put("{rname}", '
                f"(long)({dividend} % "
                f"Math.max(1, {divisor})))"
            )
    elif m_into:
        divisor = m_into.group(1).strip()
        targets_str = m_into.group(2).strip().rstrip(".")
        if re.match(r"^-?\d+\.?\d*$", divisor):
            val = _java_numeric_literal(divisor)
        else:
            val = f'CobolRuntime.toNum(state.get("{_var_name(divisor)}"))'
        for tok in _tokenize_cobol_vars(targets_str):
            tname = _var_name(tok)
            if tname and tname not in ("GIVING", "REMAINDER", "ROUNDED"):
                cb.stmt(
                    f'state.put("{tname}", '
                    f'(long)(CobolRuntime.toNum(state.get("{tname}")) / '
                    f"Math.max(1, {val})))"
                )
    else:
        cb.comment(f"DIVIDE: {_oneline(stmt.text)}")


def _gen_if_java(cb: _JavaCodeBuilder, stmt: Statement) -> None:
    condition = stmt.attributes.get("condition", "")
    if "*>" in condition:
        condition = _strip_comments_condition(condition)

    bid = cb.next_branch_id()
    cb.branch_meta[bid] = {
        "condition": condition,
        "paragraph": cb.current_para,
        "type": "IF",
    }

    if not condition:
        cb.open_block(f"if (true) /* IF: {_oneline(stmt.text)} */")
    else:
        java_cond = cobol_condition_to_java(condition, cb.level_88_map)
        cb.open_block(f"if ({java_cond})")

    cb.stmt(f"state.addBranch({bid})")

    # Split children into then / else
    else_node = None
    then_children: list[Statement] = []
    for child in stmt.children:
        if child.type == "ELSE":
            else_node = child
        else:
            then_children.append(child)

    if not then_children:
        cb.comment("empty THEN")
    else:
        for child in then_children:
            _gen_statement_java(cb, child)

    if else_node:
        cb.close_block(" else {")
        cb._indent += 1
        cb.stmt(f"state.addBranch(-{bid})")
        if not else_node.children:
            cb.comment("empty ELSE")
        else:
            for child in else_node.children:
                _gen_statement_java(cb, child)
        cb.close_block()
    else:
        cb.close_block(" else {")
        cb._indent += 1
        cb.stmt(f"state.addBranch(-{bid})")
        cb.close_block()


def _gen_evaluate_java(cb: _JavaCodeBuilder, stmt: Statement) -> None:
    subject = stmt.attributes.get("subject", "TRUE")
    is_true = subject.upper() == "TRUE"
    eval_var = cb.next_temp_var("_evalSubject")
    has_numeric_when = False

    if not is_true:
        cb.stmt(f'Object {eval_var} = state.get("{_vk(subject)}")')
        # Check if WHEN values are numeric -- coerce subject to number
        for child in stmt.children:
            if child.type == "WHEN":
                vt, io = parse_when_value(child.text)
                if not io and re.match(r"^[+-]?\d+\.?\d*$", vt.strip()):
                    has_numeric_when = True
                    break
        if has_numeric_when:
            cb.stmt(f"{eval_var} = CobolRuntime.toNum({eval_var})")

    # Process non-WHEN children (statements outside WHEN clauses).
    for child in stmt.children:
        if child.type != "WHEN":
            _gen_statement_java(cb, child)

    # Group stacked WHENs.  In COBOL, consecutive WHEN clauses where
    # all but the last have no body share the last clause's body:
    #     WHEN condition-a          -- empty
    #     WHEN condition-b          -- has body
    #         statements            -- executed for a OR b
    when_children = [c for c in stmt.children if c.type == "WHEN"]
    groups: list[list[Statement]] = []
    current_group: list[Statement] = []
    for wc in when_children:
        body = [c for c in wc.children if c.type != "WHEN"]
        _, is_other = parse_when_value(wc.text)
        current_group.append(wc)
        if body or is_other:
            groups.append(current_group)
            current_group = []
    if current_group:
        groups.append(current_group)

    first_when = True
    for group in groups:
        owner = group[-1]  # last WHEN has the body
        owner_vt, owner_is_other = parse_when_value(owner.text)

        if owner_is_other:
            cb.open_block("else")
        else:
            # Combine all conditions in the group with ||
            parts: list[str] = []
            for wc in group:
                vt, _ = parse_when_value(wc.text)
                resolved = resolve_when_value_java(vt, is_true, cb.level_88_map)
                if is_true:
                    parts.append(f"({resolved})")
                else:
                    cmp_val = resolved
                    if has_numeric_when:
                        cmp_val = f"CobolRuntime.toNum({resolved})"
                    parts.append(
                        f"(java.util.Objects.equals({eval_var}, {cmp_val}))"
                    )
            combined = " || ".join(parts)
            keyword = "if" if first_when else "else if"
            cb.open_block(f"{keyword} ({combined})")
            first_when = False

        bid = cb.next_branch_id()
        cond_label = " OR ".join(
            parse_when_value(wc.text)[0] for wc in group
        ) if not owner_is_other else "OTHER"
        cb.branch_meta[bid] = {
            "condition": cond_label,
            "paragraph": cb.current_para,
            "type": "EVALUATE",
            "subject": subject,
        }
        cb.stmt(f"state.addBranch({bid})")

        when_body = [c for c in owner.children if c.type != "WHEN"]
        if not when_body:
            cb.comment("empty WHEN")
        else:
            for c in when_body:
                _gen_statement_java(cb, c)
        cb.close_block()


def _gen_perform_java(cb: _JavaCodeBuilder, stmt: Statement) -> None:
    target = stmt.attributes.get("target", "")
    if not target:
        cb.comment(f"PERFORM: {_oneline(stmt.text)}")
        return

    func_name = _sanitize_java_name(target)
    times_str = stmt.attributes.get("times", "")
    if times_str:
        m = re.match(r"(\d+)\s+TIMES?", times_str, re.IGNORECASE)
        if m:
            count = int(m.group(1))
            cb.open_block(f"for (int _i = 0; _i < {count}; _i++)")
            cb.stmt(f'perform(state, "{target}")')
            cb.close_block()
            return
        mv = re.match(
            r"([A-Z][A-Z0-9-]*)\s+TIMES?", times_str, re.IGNORECASE
        )
        if mv:
            vname = mv.group(1).upper()
            cb.open_block(
                f"for (int _i = 0; _i < (int)CobolRuntime.toNum("
                f'state.get("{vname}")); _i++)'
            )
            cb.stmt(f'perform(state, "{target}")')
            cb.close_block()
            return

    # VARYING
    m_vary = re.search(
        r"VARYING\s+([A-Z][A-Z0-9-]*)\s+FROM\s+(\S+)\s+BY\s+(\S+)"
        r"\s+UNTIL\s+(.+)",
        stmt.text,
        re.IGNORECASE,
    )
    if m_vary:
        loop_var = m_vary.group(1).upper()
        from_val = _resolve_source_java(m_vary.group(2).strip())
        by_val = _resolve_source_java(m_vary.group(3).strip())
        until_cond = m_vary.group(4).strip().rstrip(".")
        java_until = cobol_condition_to_java(until_cond, cb.level_88_map)
        bid = cb.next_branch_id()
        cb.branch_meta[bid] = {
            "condition": until_cond,
            "paragraph": cb.current_para,
            "type": "PERFORM_VARYING",
        }
        lv = cb.next_loop_var()
        cb.stmt(
            f'state.put("{loop_var}", CobolRuntime.toNum({from_val}))'
        )
        cb.stmt(f"int {lv} = 0")
        cb.open_block(f"while (!({java_until}))")
        cb.stmt(f"state.addBranch({bid})")
        cb.stmt(f'perform(state, "{target}")')
        cb.stmt(
            f'state.put("{loop_var}", '
            f'CobolRuntime.toNum(state.get("{loop_var}")) + '
            f"CobolRuntime.toNum({by_val}))"
        )
        cb.stmt(f"{lv}++")
        cb.open_block(f"if ({lv} >= 10000)")
        # Loop didn't terminate naturally — mirror COBOL's mid-error-loop
        # abort by setting abended + throwing GobackSignal so the closes
        # never run (matching the COBOL binary's truncated trace).
        cb.stmt("state.abended = true")
        cb.line("throw new GobackSignal();")
        cb.close_block()
        cb.close_block()
        cb.open_block(f"if ({lv} == 0)")
        cb.stmt(f"state.addBranch(-{bid})")
        cb.close_block()
        return

    cb.stmt(f'perform(state, "{target}")')


def _gen_perform_thru_java(cb: _JavaCodeBuilder, stmt: Statement) -> None:
    target = stmt.attributes.get("target", "")
    thru = stmt.attributes.get("thru", "")
    condition = stmt.attributes.get("condition", "")

    m_thru = re.search(r"THRU\s+([A-Z][A-Z0-9-]*)", stmt.text, re.IGNORECASE)
    if m_thru:
        thru = m_thru.group(1).upper()

    if not target:
        cb.comment(f"PERFORM_THRU: {_oneline(stmt.text)}")
        return

    if thru and thru != target:
        range_paras = _get_thru_range(target, thru)
    else:
        range_paras = [target]

    if condition:
        java_cond = cobol_condition_to_java(condition, cb.level_88_map)
        bid = cb.next_branch_id()
        cb.branch_meta[bid] = {
            "condition": condition,
            "paragraph": cb.current_para,
            "type": "PERFORM_UNTIL",
        }
        lv = cb.next_loop_var()
        cb.stmt(f"int {lv} = 0")
        cb.open_block(f"while (!({java_cond}))")
        cb.stmt(f"state.addBranch({bid})")
        for para_name in range_paras:
            cb.stmt(f'perform(state, "{para_name}")')
        cb.stmt(f"{lv}++")
        cb.open_block(f"if ({lv} >= 10000)")
        # Loop didn't terminate naturally — mirror COBOL's mid-error-loop
        # abort by setting abended + throwing GobackSignal so the closes
        # never run (matching the COBOL binary's truncated trace).
        cb.stmt("state.abended = true")
        cb.line("throw new GobackSignal();")
        cb.close_block()
        cb.close_block()
        cb.open_block(f"if ({lv} == 0)")
        cb.stmt(f"state.addBranch(-{bid})")
        cb.close_block()
    else:
        if len(range_paras) == 1:
            cb.stmt(f'perform(state, "{range_paras[0]}")')
        else:
            cb.stmt(f'performThru(state, "{target}", "{thru}")')


def _gen_perform_inline_java(cb: _JavaCodeBuilder, stmt: Statement) -> None:
    condition = stmt.attributes.get("condition", "")
    varying = stmt.attributes.get("varying", "")
    lv = cb.next_loop_var()
    vary_increment = None
    loop_bid = None

    if condition:
        java_cond = cobol_condition_to_java(condition, cb.level_88_map)
        loop_bid = cb.next_branch_id()
        cb.branch_meta[loop_bid] = {
            "condition": condition,
            "paragraph": cb.current_para,
            "type": "PERFORM_UNTIL",
        }
        cb.stmt(f"int {lv} = 0")
        cb.open_block(f"while (!({java_cond}))")
    elif varying:
        m_vary = re.match(
            r"VARYING\s+([A-Z][A-Z0-9-]*)\s+FROM\s+(\S+)\s+BY\s+(\S+)"
            r"\s+UNTIL\s+(.+)",
            varying,
            re.IGNORECASE,
        )
        if m_vary:
            loop_var = m_vary.group(1).upper()
            from_val = _resolve_source_java(m_vary.group(2).strip())
            by_val = _resolve_source_java(m_vary.group(3).strip())
            until_cond = m_vary.group(4).strip()
            java_until = cobol_condition_to_java(until_cond, cb.level_88_map)
            loop_bid = cb.next_branch_id()
            cb.branch_meta[loop_bid] = {
                "condition": until_cond,
                "paragraph": cb.current_para,
                "type": "PERFORM_VARYING",
            }
            cb.stmt(
                f'state.put("{loop_var}", CobolRuntime.toNum({from_val}))'
            )
            cb.stmt(f"int {lv} = 0")
            cb.open_block(f"while (!({java_until}))")
            vary_increment = (loop_var, by_val)
        else:
            cb.stmt(f"int {lv} = 0")
            cb.open_block(f"while (true) /* VARYING: {varying[:50]} */")
    else:
        cb.stmt(f"int {lv} = 0")
        cb.open_block("while (true) /* PERFORM_INLINE */")

    if loop_bid is not None:
        cb.stmt(f"state.addBranch({loop_bid})")
    if not stmt.children:
        cb.comment("empty loop body")
    else:
        for child in stmt.children:
            _gen_statement_java(cb, child)
    if vary_increment:
        loop_var, by_val = vary_increment
        cb.stmt(
            f'state.put("{loop_var}", '
            f'CobolRuntime.toNum(state.get("{loop_var}")) + '
            f"CobolRuntime.toNum({by_val}))"
        )
    cb.stmt(f"{lv}++")
    cb.open_block(f"if ({lv} >= 10000)")
    cb.stmt("state.abended = true")
    cb.line("throw new GobackSignal();")
    cb.close_block()
    cb.close_block()

    if loop_bid is not None:
        cb.open_block(f"if ({lv} == 0)")
        cb.stmt(f"state.addBranch(-{loop_bid})")
        cb.close_block()


def _gen_set_java(cb: _JavaCodeBuilder, stmt: Statement) -> None:
    _VN = r"[A-Z0-9][A-Z0-9-]*"
    m = re.search(rf"SET\s+({_VN})\s+TO\s+TRUE", stmt.text, re.IGNORECASE)
    if m:
        varname = m.group(1).upper()
        # Clear 88-level siblings (mutual exclusion)
        siblings = _88_LEVEL_SIBLINGS.get(varname, set())
        for sib in sorted(siblings):
            cb.stmt(f'state.put("{sib}", false)')
        cb.stmt(f'state.put("{varname}", true)')
        return
    m = re.search(rf"SET\s+({_VN})\s+TO\s+FALSE", stmt.text, re.IGNORECASE)
    if m:
        cb.stmt(f'state.put("{m.group(1).upper()}", false)')
        return
    m = re.search(
        rf"SET\s+({_VN})\s+UP\s+BY\s+(.+)", stmt.text, re.IGNORECASE
    )
    if m:
        varname = m.group(1).upper()
        value = m.group(2).strip().rstrip(".")
        cb.stmt(
            f'state.put("{varname}", '
            f'CobolRuntime.toNum(state.get("{varname}")) + '
            f"CobolRuntime.toNum({_resolve_source_java(value)}))"
        )
        return
    m = re.search(
        rf"SET\s+({_VN})\s+DOWN\s+BY\s+(.+)", stmt.text, re.IGNORECASE
    )
    if m:
        varname = m.group(1).upper()
        value = m.group(2).strip().rstrip(".")
        cb.stmt(
            f'state.put("{varname}", '
            f'CobolRuntime.toNum(state.get("{varname}")) - '
            f"CobolRuntime.toNum({_resolve_source_java(value)}))"
        )
        return
    m = re.search(
        rf"SET\s+({_VN})\s+TO\s+(.+)", stmt.text, re.IGNORECASE
    )
    if m:
        varname = m.group(1).upper()
        value = m.group(2).strip().rstrip(".")
        cb.stmt(f'state.put("{varname}", {_resolve_source_java(value)})')
        return
    cb.comment(f"SET: {_oneline(stmt.text)}")


def _gen_display_java(cb: _JavaCodeBuilder, stmt: Statement) -> None:
    text = stmt.text.strip()
    m = re.match(r"DISPLAY\s+(.*)", text, re.IGNORECASE)
    if not m:
        cb.stmt(f'display(state, {_java_string_literal(_oneline(text))})')
        return

    content = m.group(1).rstrip(".")
    parts: list[str] = []
    pos = 0
    while pos < len(content):
        if content[pos] == "'":
            end = (
                content.index("'", pos + 1)
                if "'" in content[pos + 1 :]
                else len(content)
            )
            inner = content[pos + 1 : end]
            parts.append(_java_string_literal(inner))
            pos = end + 1
        elif content[pos] in (" ", "\t"):
            pos += 1
        else:
            end = pos
            while end < len(content) and content[end] not in (" ", "\t", "'"):
                end += 1
            token = content[pos:end]
            var = _vk(token)
            if var not in ("UPON", "CONSOLE", "SYSIN", "SYSOUT"):
                # Numeric PIC variables that haven't been initialised should
                # render as ``0`` (COBOL's PIC 9 default) rather than
                # ``" "`` (the runtime's missing-key default for alpha).
                pic = cb.pic_info.get(var) if cb.pic_info else None
                kind = (pic or {}).get("kind") if pic else None
                if kind in ("numeric", "packed", "comp"):
                    parts.append(
                        f'String.valueOf((long) CobolRuntime.toNum(state.get("{var}")))'
                    )
                else:
                    parts.append(
                        f'String.valueOf(state.get("{var}"))'
                    )
            pos = end

    if parts:
        cb.stmt(f'display(state, {", ".join(parts)})')
    else:
        cb.stmt('display(state, "")')


def _extract_exec_param(raw: str, param: str) -> str:
    """Extract a parenthesized parameter value from raw EXEC text.

    E.g. ``_extract_exec_param(text, "DATASET")`` on
    ``EXEC CICS READ DATASET (WS-FILE) ...`` returns ``"WS-FILE"``.
    Also handles the non-parenthesized ``SEGMENT SEGNAME`` form.
    """
    # Try parenthesized form first: PARAM ( VALUE )  or PARAM(VALUE)
    m = re.search(
        rf"\b{param}\s*\(\s*([^)]+?)\s*\)", raw, re.IGNORECASE
    )
    if m:
        return m.group(1).strip()
    # Non-parenthesized: PARAM VALUE (single token)
    m = re.search(
        rf"\b{param}\s+([A-Z][A-Z0-9_-]*)", raw, re.IGNORECASE
    )
    if m:
        return m.group(1).strip()
    return ""


def _extract_where_clause(raw: str) -> tuple[str, str]:
    """Extract WHERE (COL = VAR) from DLI raw text.

    Returns (column, variable) or ("", "").
    """
    m = re.search(
        r"\bWHERE\s*\(\s*([A-Z][A-Z0-9_-]*)\s*=\s*([A-Z][A-Z0-9_-]*)\s*\)",
        raw,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return "", ""


def _extract_call_using_vars(stmt: Statement) -> list[str]:
    """Pull COBOL variable names from a CALL ... USING ... clause.

    Looks first at ``stmt.attributes["using"]`` (preferred — list[str]),
    then at any USING child statements, then falls back to scanning
    ``stmt.attributes["raw_text"]`` for a ``USING <name> [<name> ...]``
    pattern. Returns an empty list when no USING clause is detected.
    """
    raw_using = stmt.attributes.get("using")
    if isinstance(raw_using, (list, tuple)):
        return [str(x) for x in raw_using if x]
    if isinstance(raw_using, str) and raw_using.strip():
        return [raw_using.strip()]
    for child in stmt.children:
        if child.type and child.type.upper() == "USING":
            names = [c.text for c in child.children if c.text]
            if names:
                return names
    raw = stmt.attributes.get("raw_text", "") or stmt.text or ""
    m = re.search(r"\bUSING\s+(.+)", raw, re.IGNORECASE)
    if not m:
        return []
    tail = m.group(1).strip().rstrip(".")
    parts = re.split(r"[\s,]+|\bBY\s+(?:CONTENT|REFERENCE|VALUE)\b",
                     tail, flags=re.IGNORECASE)
    return [p.strip() for p in parts if p and p.strip().upper()
            not in {"BY", "CONTENT", "REFERENCE", "VALUE", "RETURNING"}]


_ABEND_ROUTINES = {"CEE3ABD", "ILBOABN0", "ILBOABNS"}


def _gen_call_java(cb: _JavaCodeBuilder, stmt: Statement) -> None:
    target = stmt.attributes.get("target", "UNKNOWN")
    upper = target.upper()
    if upper == "MQOPEN":
        cb.stmt('stubs.mqOpen(state, "WS-REQUEST-QNAME")')
    elif upper == "MQGET":
        cb.stmt('stubs.mqGet(state, "W01-GET-BUFFER", "W01-DATALEN", "MQGMO-WAITINTERVAL")')
    elif upper == "MQPUT1":
        cb.stmt('stubs.mqPut1(state, "WS-REPLY-QNAME", "W02-PUT-BUFFER", "W02-BUFLEN")')
    elif upper == "MQCLOSE":
        cb.stmt("stubs.mqClose(state)")
    elif upper in _ABEND_ROUTINES:
        # CEE3ABD and friends are the standard IBM ABEND routines. The
        # COBOL mock (cobol_mock._replace_call_stmts) emits ``STOP RUN``
        # after the stub consume so the binary terminates at the first
        # abend — otherwise a batch program's 9999-ABEND-PROGRAM would
        # return to the main loop, re-enter the failing path, and blow
        # GnuCOBOL's call stack (rc=160) after thousands of retries.
        # Java mirrors that by setting ``state.abended`` AND throwing
        # GobackSignal so the run()'s try/catch unwinds cleanly to the
        # program's exit point (closes are skipped — same as COBOL's
        # STOP RUN which bypasses the PROCEDURE DIVISION's end).
        cb.stmt(
            f'stubs.callProgram(state, "{_dq(target)}", '
            "java.util.Collections.<String>emptyList(), "
            "java.util.Collections.<String>emptyList())"
        )
        cb.stmt("state.abended = true")
        cb.line("throw new GobackSignal();")
    else:
        using = _extract_call_using_vars(stmt)
        in_list = ", ".join(f'"{_dq(v)}"' for v in using) if using else ""
        in_arg = f"java.util.List.of({in_list})" if in_list else "java.util.Collections.emptyList()"
        # outputVars left empty: WireMock decides which keys to set on the response.
        cb.stmt(
            f'stubs.callProgram(state, "{_dq(target)}", {in_arg}, '
            f'java.util.Collections.<String>emptyList())'
        )


def _gen_exec_java(
    cb: _JavaCodeBuilder, stmt: Statement, kind: str
) -> None:
    raw = stmt.attributes.get("raw_text", "")
    upper = raw.upper()

    # -- EXEC CICS typed dispatch -----------------------------------------
    if kind == "CICS":
        if "READ" in upper and "DATASET" in upper:
            dataset = _extract_exec_param(raw, "DATASET") or "TABLE"
            ridfld = _extract_exec_param(raw, "RIDFLD") or "KEY"
            into = _extract_exec_param(raw, "INTO") or "RECORD"
            resp = _extract_exec_param(raw, "RESP") or ""
            resp2 = _extract_exec_param(raw, "RESP2") or ""
            resp_arg = f'"{_dq(resp)}"' if resp else "null"
            resp2_arg = f'"{_dq(resp2)}"' if resp2 else "null"
            cb.stmt(
                f'stubs.cicsRead(state, "{_dq(dataset)}", "{_dq(ridfld)}", '
                f'"{_dq(into)}", {resp_arg}, {resp2_arg})'
            )
            return
        if "RETURN" in upper:
            has_transid = "TRANSID" in upper
            cb.stmt(f"stubs.cicsReturn(state, {str(has_transid).lower()})")
            return
        if "RETRIEVE" in upper:
            into = _extract_exec_param(raw, "INTO") or ""
            into_arg = f'"{_dq(into)}"' if into else "null"
            cb.stmt(f"stubs.cicsRetrieve(state, {into_arg})")
            return
        if "SYNCPOINT" in upper:
            cb.stmt("stubs.cicsSyncpoint(state)")
            return
        if "ASKTIME" in upper:
            abstime = _extract_exec_param(raw, "ABSTIME") or ""
            abstime_arg = f'"{_dq(abstime)}"' if abstime else "null"
            cb.stmt(f"stubs.cicsAsktime(state, {abstime_arg})")
            return
        if "FORMATTIME" in upper:
            abstime = _extract_exec_param(raw, "ABSTIME") or ""
            abstime_arg = f'"{_dq(abstime)}"' if abstime else "null"
            # Try various date format params
            date_var = (_extract_exec_param(raw, "YYYYMMDD")
                        or _extract_exec_param(raw, "YYDDD")
                        or _extract_exec_param(raw, "YYMMDD")
                        or _extract_exec_param(raw, "MMDDYY")
                        or "")
            date_arg = f'"{_dq(date_var)}"' if date_var else "null"
            time_var = _extract_exec_param(raw, "TIME") or ""
            time_arg = f'"{_dq(time_var)}"' if time_var else "null"
            ms_var = _extract_exec_param(raw, "MILLISECONDS") or ""
            ms_arg = f'"{_dq(ms_var)}"' if ms_var else "null"
            cb.stmt(
                f"stubs.cicsFormattime(state, {abstime_arg}, "
                f"{date_arg}, {time_arg}, {ms_arg})"
            )
            return
        if "WRITEQ" in upper and "TD" in upper:
            queue = _extract_exec_param(raw, "QUEUE") or ""
            # Strip surrounding quotes from QUEUE('CSSL')
            queue = queue.strip("'\"")
            from_rec = _extract_exec_param(raw, "FROM") or ""
            queue_arg = f'"{_dq(queue)}"' if queue else "null"
            from_arg = f'"{_dq(from_rec)}"' if from_rec else "null"
            cb.stmt(f"stubs.cicsWriteqTd(state, {queue_arg}, {from_arg})")
            return

    # -- EXEC DLI typed dispatch ------------------------------------------
    if kind == "DLI":
        if re.search(r"\bSCHD\b", upper):
            psb = _extract_exec_param(raw, "PSB") or ""
            # Strip parens from PSB((PSB-NAME))
            psb = psb.strip("()")
            psb_arg = f'"{_dq(psb)}"' if psb else "null"
            cb.stmt(f"stubs.dliSchedulePsb(state, {psb_arg})")
            return
        if re.search(r"\bTERM\b", upper):
            cb.stmt("stubs.dliTerminate(state)")
            return
        if re.search(r"\bGU\b", upper):
            segment = _extract_exec_param(raw, "SEGMENT") or "SEGMENT"
            into = _extract_exec_param(raw, "INTO") or "RECORD"
            col, var = _extract_where_clause(raw)
            col_arg = f'"{_dq(col)}"' if col else "null"
            var_arg = f'"{_dq(var)}"' if var else "null"
            cb.stmt(
                f'stubs.dliGetUnique(state, "{_dq(segment)}", '
                f'"{_dq(into)}", {col_arg}, {var_arg})'
            )
            return
        if re.search(r"\bISRT\b", upper):
            # Check for child insert pattern (two SEGMENT clauses)
            segments = re.findall(
                r"\bSEGMENT\s*\(\s*([^)]+?)\s*\)", raw, re.IGNORECASE
            )
            from_rec = _extract_exec_param(raw, "FROM") or ""
            from_arg = f'"{_dq(from_rec)}"' if from_rec else "null"
            if len(segments) >= 2:
                parent_seg = segments[0].strip()
                child_seg = segments[1].strip()
                col, var = _extract_where_clause(raw)
                col_arg = f'"{_dq(col)}"' if col else "null"
                var_arg = f'"{_dq(var)}"' if var else "null"
                cb.stmt(
                    f'stubs.dliInsertChild(state, "{_dq(parent_seg)}", '
                    f'{col_arg}, {var_arg}, "{_dq(child_seg)}", {from_arg})'
                )
            else:
                segment = segments[0].strip() if segments else "SEGMENT"
                cb.stmt(
                    f'stubs.dliInsert(state, "{_dq(segment)}", {from_arg})'
                )
            return
        if re.search(r"\bREPL\b", upper):
            segment = _extract_exec_param(raw, "SEGMENT") or "SEGMENT"
            from_rec = _extract_exec_param(raw, "FROM") or ""
            from_arg = f'"{_dq(from_rec)}"' if from_rec else "null"
            cb.stmt(
                f'stubs.dliReplace(state, "{_dq(segment)}", {from_arg})'
            )
            return

    # -- Fallback: generic dummyExec --------------------------------------
    escaped = _dq(raw)
    if len(escaped) > 200:
        escaped = escaped[:200] + "..."
    cb.stmt(f'stubs.dummyExec(state, "{kind}", "{escaped}")')


def _gen_initialize_java(cb: _JavaCodeBuilder, stmt: Statement) -> None:
    text = _strip_cobol_comments(stmt.text)
    m = re.search(r"INITIALIZE\s+(.+)", text, re.IGNORECASE)
    if m:
        targets = m.group(1).strip().rstrip(".")
        for tok in _tokenize_cobol_vars(targets):
            tname = _var_name(tok)
            if tname and tname not in (
                "REPLACING",
                "ALPHANUMERIC",
                "NUMERIC",
                "BY",
                "ALL",
            ):
                cb.stmt(
                    f'state.put("{tname}", '
                    f'state.get("{tname}") instanceof Number ? 0 : "")'
                )
    else:
        cb.comment(f"INITIALIZE: {_oneline(stmt.text)}")


def _gen_string_stmt_java(cb: _JavaCodeBuilder, stmt: Statement) -> None:
    m = re.search(r"INTO\s+([A-Z][A-Z0-9-]*)", stmt.text, re.IGNORECASE)
    if m:
        target = m.group(1).upper()
        parts_text = re.split(r"\bINTO\b", stmt.text, flags=re.IGNORECASE)[0]
        parts_text = re.sub(
            r"^STRING\s+", "", parts_text, flags=re.IGNORECASE
        )

        segments = re.split(
            r"\s+DELIMITED\s+BY\s+SIZE\s*",
            parts_text,
            flags=re.IGNORECASE,
        )
        py_parts: list[str] = []
        for seg in segments:
            seg = seg.strip()
            if not seg:
                continue
            for token in re.findall(
                r"'[^']*'|[A-Z][A-Z0-9-]*", seg, re.IGNORECASE
            ):
                if token.startswith("'"):
                    py_parts.append(_java_string_literal(token[1:-1]))
                else:
                    py_parts.append(
                        f'String.valueOf(state.get("{_vk(token)}"))'
                    )

        if py_parts:
            expr = " + ".join(py_parts)
            cb.stmt(f'state.put("{target}", {expr})')
        else:
            cb.comment(f"STRING: {_oneline(stmt.text)}")
    else:
        cb.comment(f"STRING: {_oneline(stmt.text)}")


def _gen_unstring_java(cb: _JavaCodeBuilder, stmt: Statement) -> None:
    text = " ".join(stmt.text.split())

    m_src = re.match(
        r"UNSTRING\s+([A-Z][A-Z0-9-]*(?:\s*\([^)]*\))?)",
        text,
        re.IGNORECASE,
    )
    if not m_src:
        cb.comment(f"UNSTRING (unparsed): {_oneline(text)}")
        return

    src_raw = m_src.group(1).strip()
    src_var = re.sub(r"\s*\(.*\)", "", src_raw).upper()

    m_delim = re.search(r"DELIMITED\s+BY\s+(\S+)", text, re.IGNORECASE)
    if m_delim:
        delim_token = m_delim.group(1).strip()
        if _vk(delim_token) in ("SPACES", "SPACE"):
            java_delim = '"\\\\s+"'  # regex split on whitespace
        elif delim_token.startswith("'") and delim_token.endswith("'"):
            java_delim = _java_string_literal(delim_token[1:-1])
        else:
            java_delim = (
                f'String.valueOf(state.get("{_vk(delim_token)}"))'
            )
    else:
        java_delim = '"\\\\s+"'

    m_into = re.search(
        r"\bINTO\s+(.+?)(?:\s+END-UNSTRING|\s*$)",
        text,
        re.IGNORECASE,
    )
    if not m_into:
        cb.comment(f"UNSTRING (no INTO): {_oneline(text)}")
        return

    targets_str = m_into.group(1).strip()
    targets: list[str] = []
    for tok in re.findall(
        r"[A-Z][A-Z0-9-]*(?:\s*\([^)]*\))?", targets_str, re.IGNORECASE
    ):
        clean = re.sub(r"\s*\(.*\)", "", tok).upper()
        if clean not in (
            "END-UNSTRING",
            "DELIMITER",
            "COUNT",
            "IN",
            "ALL",
            "OR",
        ):
            targets.append(clean)

    if not targets:
        cb.comment(f"UNSTRING (no targets): {_oneline(text)}")
        return

    cb.stmt(
        f'String[] _usParts = String.valueOf(state.get("{src_var}"))'
        f".split({java_delim})"
    )
    for i, tgt in enumerate(targets):
        cb.stmt(
            f'state.put("{tgt}", '
            f"{i} < _usParts.length ? _usParts[{i}].trim() : " + '"")'
        )


def _gen_read_java(cb: _JavaCodeBuilder, stmt: Statement) -> None:
    m = re.search(r"READ\s+([A-Z][A-Z0-9-]*)", stmt.text, re.IGNORECASE)
    if m:
        fname = m.group(1).upper()
        cb.stmt(f'state.reads.add("{fname}")')
        _emit_file_status_reset(cb, fname)
        cb.stmt(f'stubs.applyStubOutcome(state, "READ:{fname}")')
    else:
        cb.stmt('state.reads.add("UNKNOWN")')
        cb.stmt('stubs.applyStubOutcome(state, "READ:UNKNOWN")')


def _gen_write_java(cb: _JavaCodeBuilder, stmt: Statement) -> None:
    m = re.search(r"WRITE\s+([A-Z][A-Z0-9-]*)", stmt.text, re.IGNORECASE)
    if m:
        recname = m.group(1).upper()
        cb.stmt(f'state.writes.add("{recname}")')
        cb.stmt(f'stubs.applyStubOutcome(state, "WRITE:{recname}")')
    else:
        cb.stmt('state.writes.add("UNKNOWN")')
        cb.stmt('stubs.applyStubOutcome(state, "WRITE:UNKNOWN")')


def _gen_rewrite_java(cb: _JavaCodeBuilder, stmt: Statement) -> None:
    m = re.search(r"REWRITE\s+([A-Z][A-Z0-9-]*)", stmt.text, re.IGNORECASE)
    if m:
        recname = m.group(1).upper()
        cb.stmt(f'state.writes.add("{recname}")')
        cb.stmt(f'stubs.applyStubOutcome(state, "REWRITE:{recname}")')
    else:
        cb.stmt('state.writes.add("UNKNOWN")')


def _emit_file_status_reset(cb: _JavaCodeBuilder, file_token: str) -> None:
    """Emit ``state.put("<status-var>", "")`` so OPEN/READ/etc. stubs see
    a freshly blanked status field.

    Mirrors the COBOL mock's unconditional ``MOVE MOCK-ALPHA-STATUS TO
    <status-var>`` (which is SPACES on FIFO/EOF). Without this, Java
    stub calls with empty FIFOs leave the status var holding whatever
    value was last stored (often an injected test input), diverging from
    COBOL's behaviour where the status is always re-seeded.
    """
    status_var = cb.file_status_map.get(file_token.upper())
    if not status_var:
        return
    cb.stmt(f'state.put("{status_var}", "")')


def _gen_open_java(cb: _JavaCodeBuilder, stmt: Statement) -> None:
    m = re.search(
        r"OPEN\s+(?:INPUT|OUTPUT|I-O|EXTEND)\s+(.+)",
        stmt.text,
        re.IGNORECASE,
    )
    if m:
        files_str = m.group(1).strip().rstrip(".")
        for tok in re.split(r"\s+", files_str):
            tok = _vk(tok.strip())
            if tok and tok not in ("INPUT", "OUTPUT", "I-O", "EXTEND"):
                _emit_file_status_reset(cb, tok)
                cb.stmt(
                    f'stubs.applyStubOutcome(state, "OPEN:{tok}")'
                )
    cb.comment(_oneline(stmt.text, 70))


def _gen_close_java(cb: _JavaCodeBuilder, stmt: Statement) -> None:
    m = re.search(r"CLOSE\s+(.+)", stmt.text, re.IGNORECASE)
    if m:
        files_str = m.group(1).strip().rstrip(".")
        for tok in re.split(r"\s+", files_str):
            tok = _vk(tok.strip())
            if tok:
                _emit_file_status_reset(cb, tok)
                cb.stmt(
                    f'stubs.applyStubOutcome(state, "CLOSE:{tok}")'
                )
    cb.comment(_oneline(stmt.text, 70))


def _gen_search_java(cb: _JavaCodeBuilder, stmt: Statement) -> None:
    text = stmt.text.strip()

    m_table = re.match(
        r"SEARCH\s+([A-Z][A-Z0-9-]*)", text, re.IGNORECASE
    )
    if not m_table:
        cb.comment(f"SEARCH (unparsed): {_oneline(text)}")
        return

    table_name = m_table.group(1).upper()
    m_vary = re.search(
        r"VARYING\s+([A-Z][A-Z0-9-]*)", text, re.IGNORECASE
    )
    index_var = m_vary.group(1).upper() if m_vary else None

    bid = cb.next_branch_id()
    cb.branch_meta[bid] = {
        "condition": f"SEARCH {table_name} FOUND",
        "paragraph": cb.current_para,
        "type": "SEARCH",
    }
    stub_key = f"SEARCH:{table_name}"
    sl_var = cb.next_temp_var("_sl")
    found_var = cb.next_temp_var("_searchFound")
    cb.stmt(
        f'java.util.List<?> {sl_var} = (java.util.List<?>)'
        f' state.stubOutcomes.getOrDefault("{stub_key}", '
        f"java.util.Collections.emptyList())"
    )
    cb.stmt(
        f"boolean {found_var} = !{sl_var}.isEmpty() "
        f"? (Boolean) ((java.util.List<?>) {sl_var}).remove(0) : true"
    )
    cb.open_block(f"if ({found_var})")
    cb.stmt(f"state.addBranch({bid})")
    if index_var:
        cb.stmt(f'state.put("{index_var}", 1)')
    _gen_search_body_java(cb, text, "WHEN")
    cb.close_block(" else {")
    cb._indent += 1
    cb.stmt(f"state.addBranch(-{bid})")
    _gen_search_body_java(cb, text, "AT END")
    cb.close_block()


def _gen_search_body_java(
    cb: _JavaCodeBuilder, full_text: str, section: str
) -> None:
    """Generate Java code for a SEARCH body section (AT END or WHEN)."""
    if section == "WHEN":
        when_pos = re.search(r"\bWHEN\b", full_text, re.IGNORECASE)
        if when_pos:
            body = full_text[when_pos.end() :].strip()
        else:
            cb.comment("empty WHEN")
            return
    else:
        at_end_pos = re.search(r"\bAT\s+END\b", full_text, re.IGNORECASE)
        when_pos = re.search(r"\bWHEN\b", full_text, re.IGNORECASE)
        if at_end_pos and when_pos:
            body = full_text[at_end_pos.end() : when_pos.start()].strip()
        elif at_end_pos:
            body = full_text[at_end_pos.end() :].strip()
        else:
            cb.comment("empty AT END")
            return

    if not body:
        cb.comment(f"empty {section}")
        return

    generated = False

    # Extract MOVE statements
    for m in re.finditer(
        r"MOVE\s+(.+?)\s+TO\s+([A-Z][A-Z0-9-]*(?:\s*\([^)]*\))?)",
        body,
        re.IGNORECASE,
    ):
        source = m.group(1).strip()
        target = m.group(2).strip().rstrip(".")
        resolved = _resolve_source_java(source)
        clean = re.sub(r"\s*\([^)]*\)", "", _vk(target))
        cb.stmt(f'state.put("{clean}", {resolved})')
        generated = True

    # Extract GO TO
    m_goto = re.search(r"GO\s+TO\s+([A-Z][A-Z0-9-]*)", body, re.IGNORECASE)
    if m_goto:
        cb.stmt(f'registry.get("{m_goto.group(1).upper()}").execute(state)')
        cb.line("return;")
        generated = True

    # Extract PERFORM
    for m in re.finditer(
        r"PERFORM\s+([A-Z][A-Z0-9-]*)(?:\s+THRU\s+([A-Z][A-Z0-9-]*))?",
        body,
        re.IGNORECASE,
    ):
        target = m.group(1).upper()
        thru = m.group(2).upper() if m.group(2) else None
        if thru and thru != target:
            cb.stmt(f'performThru(state, "{target}", "{thru}")')
        else:
            cb.stmt(f'perform(state, "{target}")')
        generated = True

    if not generated:
        cb.comment(f"{section} body: {_oneline(body)}")


def _gen_goto_java(cb: _JavaCodeBuilder, stmt: Statement) -> None:
    target = stmt.attributes.get("target", "")
    if target:
        cb.stmt(f'registry.get("{target}").execute(state)')
        cb.line("return;")
    else:
        cb.comment(f"GO TO: {_oneline(stmt.text)}")


def _gen_accept_java(cb: _JavaCodeBuilder, stmt: Statement) -> None:
    m = re.search(r"ACCEPT\s+([A-Z][A-Z0-9-]*)", stmt.text, re.IGNORECASE)
    if m:
        cb.comment(f"ACCEPT {m.group(1).upper()} -- uses preset state value")
    else:
        cb.comment(f"ACCEPT: {_oneline(stmt.text)}")


def _gen_inspect_java(cb: _JavaCodeBuilder, stmt: Statement) -> None:
    text = stmt.text.strip()

    m = re.search(
        r"INSPECT\s+([A-Z][A-Z0-9-]*(?:\s*\([^)]*\))?)\s+"
        r"TALLYING\s+([A-Z][A-Z0-9-]*)\s+FOR\s+LEADING\s+(\S+)",
        text,
        re.IGNORECASE,
    )
    if m:
        src_var = _vk(re.sub(r"\s*\(.*\)", "", m.group(1).strip()))
        counter = _vk(m.group(2).strip())
        what = m.group(3).strip().upper().rstrip(".")
        if what in ("SPACES", "SPACE"):
            char = " "
        elif what in ("ZEROS", "ZEROES", "ZERO"):
            char = "0"
        else:
            char = what.strip("'")

        cb.stmt(
            f'String _insV = String.valueOf(state.get("{src_var}"))'
        )
        cb.stmt("int _insC = 0")
        cb.open_block("for (int _idx = 0; _idx < _insV.length(); _idx++)")
        cb.open_block(
            f"if (_insV.charAt(_idx) == '{_dq(char)}')"
        )
        cb.stmt("_insC++")
        cb.close_block(" else {")
        cb._indent += 1
        cb.line("break;")
        cb.close_block()
        cb.close_block()
        cb.stmt(
            f'state.put("{counter}", '
            f'CobolRuntime.toNum(state.get("{counter}")) + _insC)'
        )
        return

    m = re.search(
        r"INSPECT\s+([A-Z][A-Z0-9-]*(?:\s*\([^)]*\))?)\s+REPLACING\s+(.+)",
        text,
        re.IGNORECASE,
    )
    if m:
        cb.comment(f"INSPECT REPLACING: {_oneline(text)}")
        return

    cb.comment(f"INSPECT: {_oneline(text)}")


# ---------------------------------------------------------------------------
# Statement dispatcher
# ---------------------------------------------------------------------------


def _gen_statement_java(cb: _JavaCodeBuilder, stmt: Statement) -> None:
    """Generate Java code for a single COBOL statement."""
    stype = stmt.type

    if stype == "MOVE":
        _gen_move_java(cb, stmt)
    elif stype == "COMPUTE":
        _gen_compute_java(cb, stmt)
    elif stype == "ADD":
        _gen_add_java(cb, stmt)
    elif stype == "SUBTRACT":
        _gen_subtract_java(cb, stmt)
    elif stype == "MULTIPLY":
        _gen_multiply_java(cb, stmt)
    elif stype == "DIVIDE":
        _gen_divide_java(cb, stmt)
    elif stype == "IF":
        _gen_if_java(cb, stmt)
    elif stype == "ELSE":
        pass  # handled inside IF
    elif stype == "EVALUATE":
        _gen_evaluate_java(cb, stmt)
    elif stype == "WHEN":
        pass  # handled inside EVALUATE
    elif stype == "PERFORM":
        _gen_perform_java(cb, stmt)
    elif stype == "PERFORM_THRU":
        _gen_perform_thru_java(cb, stmt)
    elif stype == "PERFORM_INLINE":
        _gen_perform_inline_java(cb, stmt)
    elif stype == "SET":
        _gen_set_java(cb, stmt)
    elif stype == "DISPLAY":
        _gen_display_java(cb, stmt)
    elif stype == "CALL":
        _gen_call_java(cb, stmt)
    elif stype == "EXEC_SQL":
        _gen_exec_java(cb, stmt, "SQL")
    elif stype == "EXEC_CICS":
        _gen_exec_java(cb, stmt, "CICS")
    elif stype == "EXEC_DLI":
        _gen_exec_java(cb, stmt, "DLI")
    elif stype == "EXEC_OTHER":
        _gen_exec_java(cb, stmt, "OTHER")
    elif stype == "GOBACK":
        cb.stmt("throw new GobackSignal()")
    elif stype == "STOP_RUN":
        cb.stmt("throw new GobackSignal()")
    elif stype == "EXIT":
        cb.comment("EXIT")
    elif stype in ("CONTINUE", "CONTINUE_STMT"):
        cb.comment("CONTINUE")
    elif stype == "INITIALIZE":
        _gen_initialize_java(cb, stmt)
    elif stype == "OPEN":
        _gen_open_java(cb, stmt)
    elif stype == "CLOSE":
        _gen_close_java(cb, stmt)
    elif stype == "READ":
        _gen_read_java(cb, stmt)
    elif stype == "WRITE":
        _gen_write_java(cb, stmt)
    elif stype == "REWRITE":
        _gen_rewrite_java(cb, stmt)
    elif stype == "ACCEPT":
        _gen_accept_java(cb, stmt)
    elif stype == "STRING":
        _gen_string_stmt_java(cb, stmt)
    elif stype == "UNSTRING":
        _gen_unstring_java(cb, stmt)
    elif stype == "INSPECT":
        _gen_inspect_java(cb, stmt)
    elif stype == "SEARCH":
        _gen_search_java(cb, stmt)
    elif stype == "SORT":
        cb.comment(f"SORT: {_oneline(stmt.text)}")
    elif stype == "GO_TO":
        _gen_goto_java(cb, stmt)
    elif stype == "ALTER":
        cb.comment(f"ALTER: {_oneline(stmt.text)}")
    elif stype == "START":
        m = re.search(
            r"START\s+([A-Z][A-Z0-9-]*)", stmt.text, re.IGNORECASE
        )
        if m:
            fname = m.group(1).upper()
            cb.stmt(
                f'stubs.applyStubOutcome(state, "START:{fname}")'
            )
        cb.comment(_oneline(stmt.text, 70))
    elif stype == "DELETE":
        m = re.search(
            r"DELETE\s+([A-Z][A-Z0-9-]*)", stmt.text, re.IGNORECASE
        )
        if m:
            fname = m.group(1).upper()
            cb.stmt(
                f'stubs.applyStubOutcome(state, "DELETE:{fname}")'
            )
        cb.comment(_oneline(stmt.text, 70))
    else:
        # Check for UNKNOWN statements that are actually START/DELETE
        text_upper = stmt.text.strip().upper()
        if text_upper.startswith("START "):
            m = re.search(
                r"START\s+([A-Z][A-Z0-9-]*)", stmt.text, re.IGNORECASE
            )
            if m:
                fname = m.group(1).upper()
                cb.stmt(
                    f'stubs.applyStubOutcome(state, "START:{fname}")'
                )
        elif text_upper.startswith("DELETE "):
            m = re.search(
                r"DELETE\s+([A-Z][A-Z0-9-]*)", stmt.text, re.IGNORECASE
            )
            if m:
                fname = m.group(1).upper()
                cb.stmt(
                    f'stubs.applyStubOutcome(state, "DELETE:{fname}")'
                )
        cb.comment(f"{stype}: {_oneline(stmt.text)}")


def _is_terminal_statement(stmt: Statement) -> bool:
    """Return True when the statement always transfers control out."""
    return stmt.type in {"GO_TO", "GOBACK", "STOP_RUN"}


# ---------------------------------------------------------------------------
# Paragraph class file generation
# ---------------------------------------------------------------------------


def _generate_paragraph_java(
    para_name: str,
    statements: list[Statement],
    package_name: str,
    cb: _JavaCodeBuilder,
) -> str:
    """Generate a Java class file for a single COBOL paragraph.

    Returns the complete Java source as a string.
    """
    class_name = _sanitize_java_name(para_name)

    lines: list[str] = []
    lines.append(f"package {package_name};")
    lines.append("")
    lines.append("/**")
    lines.append(f" * Generated paragraph: {para_name}.")
    lines.append(" */")
    lines.append(
        f"public class {class_name} extends Paragraph {{"
    )
    lines.append("")
    lines.append(
        f"    public {class_name}(ParagraphRegistry registry, "
        f"StubExecutor stubs) {{"
    )
    lines.append(f'        super("{para_name}", registry, stubs);')
    lines.append("    }")
    lines.append("")
    lines.append("    @Override")
    lines.append(
        "    protected void doExecute(ProgramState state) {"
    )

    # Build the body using the shared code builder
    body_cb = _JavaCodeBuilder()
    body_cb._indent = 2
    body_cb._branch_counter = cb._branch_counter
    body_cb._loop_counter = cb._loop_counter
    body_cb._temp_counter = cb._temp_counter
    body_cb.branch_meta = cb.branch_meta
    body_cb.current_para = para_name
    body_cb.level_88_map = cb.level_88_map
    body_cb.pic_info = cb.pic_info
    body_cb.file_status_map = cb.file_status_map

    if not statements:
        body_cb.comment("empty paragraph")
    else:
        for stmt in statements:
            _gen_statement_java(body_cb, stmt)
            if _is_terminal_statement(stmt):
                # Some parsed tails become unreachable after unconditional
                # control transfer (e.g. GO TO paragraph). Stop emitting
                # method-level code to keep Java compilable.
                break

    # Propagate counters back
    cb._branch_counter = body_cb._branch_counter
    cb._loop_counter = body_cb._loop_counter
    cb._temp_counter = body_cb._temp_counter

    lines.extend(body_cb.lines)
    lines.append("    }")
    lines.append("}")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Section class file generation
# ---------------------------------------------------------------------------


def _generate_paragraph_method(
    para_name: str,
    statements: list[Statement],
    cb: _JavaCodeBuilder,
) -> tuple[str, list[str]]:
    """Generate a paragraph as a method body (no class wrapper).

    Returns ``(method_name, lines)`` where *lines* is the complete
    method definition including signature and closing brace.
    """
    method_name = _sanitize_method_name(para_name)

    body_cb = _JavaCodeBuilder()
    body_cb._indent = 2  # method body indent
    body_cb._branch_counter = cb._branch_counter
    body_cb._loop_counter = cb._loop_counter
    body_cb._temp_counter = cb._temp_counter
    body_cb.branch_meta = cb.branch_meta
    body_cb.current_para = para_name
    body_cb.level_88_map = cb.level_88_map
    body_cb.pic_info = cb.pic_info
    body_cb.file_status_map = cb.file_status_map

    if not statements:
        # Known copybook implementations for empty paragraphs
        if para_name == "YYYY-STORE-PFKEY":
            body_cb.comment(
                "Implements CSSTRPFY copybook: map EIBAID to CCARD-AID flags"
            )
            body_cb.stmt('state.put("CCARD-AID-ENTER", false)')
            body_cb.stmt('state.put("CCARD-AID-PFK03", false)')
            body_cb.stmt('state.put("CCARD-AID-PFK05", false)')
            body_cb.stmt('state.put("CCARD-AID-PFK12", false)')
            body_cb.stmt('Object eibaid = state.get("EIBAID")')
            body_cb.line('if ("DFHENTER".equals(eibaid)) {')
            body_cb._indent += 1
            body_cb.stmt('state.put("CCARD-AID-ENTER", true)')
            body_cb._indent -= 1
            body_cb.line('} else if ("DFHPF3".equals(eibaid)) {')
            body_cb._indent += 1
            body_cb.stmt('state.put("CCARD-AID-PFK03", true)')
            body_cb._indent -= 1
            body_cb.line('} else if ("DFHPF5".equals(eibaid)) {')
            body_cb._indent += 1
            body_cb.stmt('state.put("CCARD-AID-PFK05", true)')
            body_cb._indent -= 1
            body_cb.line('} else if ("DFHPF12".equals(eibaid)) {')
            body_cb._indent += 1
            body_cb.stmt('state.put("CCARD-AID-PFK12", true)')
            body_cb._indent -= 1
            body_cb.line("}")
        else:
            body_cb.comment("empty paragraph")
    else:
        for stmt in statements:
            _gen_statement_java(body_cb, stmt)
            if _is_terminal_statement(stmt):
                # Some parsed tails become unreachable after unconditional
                # control transfer (e.g. GO TO paragraph). Stop emitting
                # method-level code to keep Java compilable.
                break

    # Propagate counters back
    cb._branch_counter = body_cb._branch_counter
    cb._loop_counter = body_cb._loop_counter
    cb._temp_counter = body_cb._temp_counter

    lines: list[str] = []
    lines.append(f"    void {method_name}(ProgramState state) {{")
    lines.extend(body_cb.lines)
    lines.append("    }")
    return method_name, lines


def _generate_section_class(
    section_key: str,
    paragraphs: list[tuple[str, list[Statement]]],
    package_name: str,
    cb: _JavaCodeBuilder,
) -> tuple[str, str]:
    """Generate a Section class containing multiple paragraph methods.

    Returns ``(class_name, source_text)``.
    """
    class_name = _section_class_name(section_key)

    # First pass: generate all method bodies and collect names
    method_infos: list[tuple[str, str, list[str]]] = []
    for para_name, statements in paragraphs:
        method_name, method_lines = _generate_paragraph_method(
            para_name, statements, cb,
        )
        method_infos.append((para_name, method_name, method_lines))

    lines: list[str] = []
    lines.append(f"package {package_name};")
    lines.append("")
    lines.append("/**")
    lines.append(f" * Generated section: {class_name}.")
    lines.append(" */")
    lines.append(f"public class {class_name} extends SectionBase {{")
    lines.append("")

    # Constructor -- register all paragraphs via method references
    lines.append(
        f"    public {class_name}(ParagraphRegistry registry, "
        f"StubExecutor stubs) {{"
    )
    lines.append("        super(registry, stubs);")
    for para_name, method_name, _ in method_infos:
        lines.append(
            f'        paragraph("{para_name}", this::{method_name});'
        )
    lines.append("    }")
    lines.append("")

    # Emit all paragraph methods
    for _, _, method_lines in method_infos:
        lines.extend(method_lines)
        lines.append("")

    lines.append("}")
    lines.append("")
    return class_name, "\n".join(lines)


# ---------------------------------------------------------------------------
# Program class generation
# ---------------------------------------------------------------------------


def _program_class_name(program_id: str) -> str:
    """Convert a COBOL program-id to a Java class name."""
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", program_id)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    if cleaned and cleaned[0].isdigit():
        cleaned = "P" + cleaned
    # Title-case
    parts = cleaned.split("_")
    return "".join(p.capitalize() for p in parts if p) + "Program"


def _generate_program_class(
    program: Program,
    var_report: VariableReport,
    package_name: str,
    section_classes: list[str] | None = None,
    is_terminal: bool = False,
    screen_layout_class: str = "ScreenLayout",
    lit_defaults: dict[str, str] | None = None,
    level_88_map: dict[str, tuple[str, object]] | None = None,
    pic_info: dict[str, dict[str, object]] | None = None,
    injectable_vars: set[str] | None = None,
    group_layouts: dict[str, list[dict]] | None = None,
    redefines_groups: dict[str, dict] | None = None,
    file_status_map: dict[str, str] | None = None,
) -> str:
    """Generate the top-level <ProgramId>Program.java source.

    If *section_classes* is provided, the constructor instantiates
    section classes (which self-register their paragraphs) instead of
    individual paragraph classes.

    If *is_terminal* is True, the class implements CicsProgram with
    programId() and screenLayout() methods for XCTL routing.

    *screen_layout_class* is the name of the ScreenLayout class to
    reference (e.g. ``ScreenLayout_COSGN00C`` in multi-program mode).
    """
    class_name = _program_class_name(program.program_id)

    lines: list[str] = []
    lines.append(f"package {package_name};")
    lines.append("")
    lines.append("import java.util.LinkedHashMap;")
    if is_terminal:
        lines.append("import java.util.List;")
    lines.append("import java.util.Map;")
    lines.append("")
    lines.append("/**")
    lines.append(
        f" * Generated program entry point for COBOL program "
        f"{program.program_id}."
    )
    lines.append(" *")
    lines.append(" * <p>Auto-generated by Specter. Do not edit.")
    lines.append(" */")
    implements = " implements CicsProgram" if is_terminal else ""
    lines.append(f"public class {class_name}{implements} {{")
    lines.append("")
    lines.append("    private final ParagraphRegistry registry;")
    lines.append("    private final StubExecutor stubs;")
    lines.append("")

    # Default constructor
    lines.append(f"    public {class_name}() {{")
    lines.append("        this(new DefaultStubExecutor());")
    lines.append("    }")
    lines.append("")

    # Constructor with StubExecutor
    lines.append(f"    public {class_name}(StubExecutor stubs) {{")
    lines.append("        this.stubs = stubs;")
    lines.append("        this.registry = new ParagraphRegistry();")
    if section_classes:
        for sec_class in section_classes:
            lines.append(
                f"        new {sec_class}(registry, stubs);"
            )
    else:
        for para in program.paragraphs:
            java_class = _sanitize_java_name(para.name)
            lines.append(
                f"        registry.register(new {java_class}"
                f"(registry, stubs));"
            )
    lines.append("    }")
    lines.append("")

    # defaultState() — uses COBOL VALUE clauses from pic_info when available;
    # falls back to classification heuristics otherwise.
    lines.append(
        "    public static Map<String, Object> defaultState() {"
    )
    lines.append(
        '        Map<String, Object> state = new LinkedHashMap<>();'
    )
    for name in sorted(var_report.variables.keys()):
        info = var_report.variables[name]
        # 1. Source VALUE clause wins (most accurate to COBOL semantics).
        pic_entry = (pic_info or {}).get(name) if pic_info else None
        default: str | None = None
        if pic_entry is not None and "value" in pic_entry:
            v = pic_entry["value"]
            if isinstance(v, bool):
                default = "true" if v else "false"
            elif isinstance(v, (int, float)):
                default = repr(v)
            else:
                default = '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'
        # 2. Classification + naming heuristics.
        if default is None:
            if info.classification == "flag":
                default = '" "'
            elif info.classification == "status":
                if "SQLCODE" in name.upper():
                    default = "0"
                else:
                    default = '" "'
            elif any(
                kw in name.upper()
                for kw in (
                    "CNT", "COUNT", "AMT", "AMOUNT", "FREQ", "DAYS",
                    "TIME", "9C", "CODE", "LEN",
                )
            ):
                default = "0"
            else:
                default = '""'
        lines.append(f'        state.put("{_dq(name)}", {default});')
    lines.append("        return state;")
    lines.append("    }")
    lines.append("")

    # run()
    lines.append(
        "    public ProgramState run(Map<String, Object> initialState) {"
    )
    lines.append(
        "        ProgramState state = ProgramState.withDefaults();"
    )
    lines.append("        state.putAll(defaultState());")
    lines.append("        if (initialState != null) {")
    lines.append("            state.putAll(initialState);")
    lines.append("        }")
    lines.append("        try {")

    entry_stmts = getattr(program, "entry_statements", None)
    if entry_stmts:
        # Generate entry statements inline -- use a temporary code builder
        entry_cb = _JavaCodeBuilder()
        entry_cb._indent = 3
        if level_88_map:
            entry_cb.level_88_map = level_88_map
        if pic_info:
            entry_cb.pic_info = pic_info
        if file_status_map:
            entry_cb.file_status_map = file_status_map
        for s in entry_stmts:
            _gen_statement_java(entry_cb, s)
        lines.extend(entry_cb.lines)
    else:
        # Fallback when the AST lacks ``entry_statements`` (the cobalt
        # parser drops the PROCEDURE DIVISION top-level statements). Call
        # every labeled paragraph in source order. This is approximate —
        # it can re-execute paragraphs already reached via PERFORM and
        # exercise CLOSE paragraphs the COBOL only reaches after a normal
        # loop exit. See AGENTS.md for the limitation.
        for para in program.paragraphs:
            lines.append(
                f'            registry.get("{para.name}").execute(state);'
            )

    lines.append("        } catch (GobackSignal e) {")
    lines.append("            // normal GOBACK/STOP RUN termination")
    lines.append("        } catch (ArithmeticException e) {")
    lines.append("            state.abended = true;")
    lines.append("        }")
    lines.append("        return state;")
    lines.append("    }")
    lines.append("")

    # Convenience run() with no args
    lines.append("    public ProgramState run() {")
    lines.append("        return run((Map<String, Object>) null);")
    lines.append("    }")
    lines.append("")

    # run(ProgramState) — execute with pre-built state (for testing with stubs)
    if is_terminal:
        lines.append("    @Override")
    lines.append(
        "    public ProgramState run(ProgramState state) {"
    )
    lines.append("        try {")

    if entry_stmts:
        entry_cb2 = _JavaCodeBuilder()
        entry_cb2._indent = 3
        if level_88_map:
            entry_cb2.level_88_map = level_88_map
        if pic_info:
            entry_cb2.pic_info = pic_info
        if file_status_map:
            entry_cb2.file_status_map = file_status_map
        for s in entry_stmts:
            _gen_statement_java(entry_cb2, s)
        lines.extend(entry_cb2.lines)
    else:
        # Fallback when the AST lacks ``entry_statements`` (the cobalt
        # parser drops the PROCEDURE DIVISION top-level statements). Call
        # every labeled paragraph in source order. This is approximate —
        # it can re-execute paragraphs already reached via PERFORM and
        # exercise CLOSE paragraphs the COBOL only reaches after a normal
        # loop exit. See AGENTS.md for the limitation.
        for para in program.paragraphs:
            lines.append(
                f'            registry.get("{para.name}").execute(state);'
            )

    lines.append("        } catch (GobackSignal e) {")
    lines.append("            // normal GOBACK/STOP RUN termination")
    lines.append("        } catch (ArithmeticException e) {")
    lines.append("            state.abended = true;")
    lines.append("        }")
    lines.append("        return state;")
    lines.append("    }")
    lines.append("")

    # Getters for testing
    lines.append(
        "    public ParagraphRegistry getRegistry() {"
    )
    lines.append("        return registry;")
    lines.append("    }")
    lines.append("")
    lines.append("    public StubExecutor getStubs() {")
    lines.append("        return stubs;")
    lines.append("    }")
    lines.append("")

    # Helper methods so entry_statements code emitted by the section
    # statement generator (which assumes a SectionBase context with
    # ``perform``/``display``/``goback`` helpers) compiles in this class
    # too. Inlined to avoid pulling SectionBase into the program's parent.
    lines.append("    private void perform(ProgramState state, String paraName) {")
    lines.append("        Paragraph p = registry.get(paraName);")
    lines.append("        if (p != null) p.execute(state);")
    lines.append("    }")
    lines.append("")
    lines.append("    private void performThru(ProgramState state, String from, String thru) {")
    lines.append("        for (Paragraph p : registry.getThruRange(from, thru)) p.execute(state);")
    lines.append("    }")
    lines.append("")
    lines.append("    private void performTimes(ProgramState state, String paraName, int n) {")
    lines.append("        Paragraph p = registry.get(paraName);")
    lines.append("        if (p != null) for (int i = 0; i < n; i++) p.execute(state);")
    lines.append("    }")
    lines.append("")
    lines.append("    private void display(ProgramState state, String... parts) {")
    lines.append('        state.addDisplay(String.join("", parts));')
    lines.append("    }")
    lines.append("")
    lines.append("    private void goback() { throw new GobackSignal(); }")
    lines.append("")

    # PIC info map — used by the integration-test harness (and any caller
    # that stages user input) to truncate values to COBOL field widths so
    # ``MOVE 'NVGFYGWWQC' TO END-OF-FILE`` matches COBOL's PIC X(1)
    # truncation behaviour.
    if pic_info:
        lines.append(
            "    /** Per-variable PIC info: ``length`` is the COBOL field "
            "width; ``kind`` is one of {{alpha,numeric,packed,comp}}. */"
        )
        lines.append(
            "    public static final java.util.Map<String, int[]> PIC_INFO ="
        )
        lines.append("        java.util.Map.<String, int[]>ofEntries(")
        # Map<String, int[]> where int[] is [length]. Kind isn't strictly
        # needed for truncation (alpha-only), but we keep length-only to
        # stay under the Map.ofEntries 10-arg limit by using ofEntries.
        entries = []
        for var, info in sorted(pic_info.items()):
            length = int(info.get("length", 0) or 0)
            kind = (info.get("kind") or "alpha")
            # Only truncate alpha; numeric/packed/comp are precision-typed
            # and best handled at numeric coercion time.
            kind_code = 0 if kind == "alpha" else 1
            if length <= 0:
                continue
            v_escaped = var.replace("\\", "\\\\").replace('"', '\\"')
            entries.append(
                f'            java.util.Map.entry("{v_escaped}", new int[]{{{length}, {kind_code}}})'
            )
        if entries:
            lines.append(",\n".join(entries))
        lines.append("        );")
        lines.append("")
        lines.append(
            "    /** Apply COBOL PIC truncation to a single value. */"
        )
        lines.append(
            "    public static Object truncateForPic(String key, Object val) {"
        )
        lines.append("        if (val == null) return null;")
        lines.append("        int[] info = PIC_INFO.get(key);")
        lines.append("        if (info == null) return val;")
        lines.append("        int length = info[0];")
        lines.append("        int kind = info[1];")
        lines.append(
            "        if (kind == 0 && val instanceof String) {"
        )
        lines.append(
            "            String s = (String) val;"
        )
        lines.append(
            "            if (length > 0 && s.length() > length) return s.substring(0, length);"
        )
        lines.append("        }")
        lines.append("        return val;")
        lines.append("    }")
        lines.append("")
    else:
        # Always emit the symbols so callers can reference them safely.
        lines.append(
            "    public static final java.util.Map<String, int[]> PIC_INFO = java.util.Map.of();"
        )
        lines.append(
            "    public static Object truncateForPic(String key, Object val) { return val; }"
        )
        lines.append("")

    # INJECTABLE_VARS: the set of variables COBOL would actually accept
    # from the INIT records. The IT filters input_state by this set so
    # both runtimes see the same starting state — without it, Java seeds
    # variables (e.g. END-OF-FILE) that COBOL silently leaves at their
    # source ``VALUE`` clause, diverging from loop entry onward.
    if injectable_vars:
        sorted_vars = sorted(injectable_vars)
        lines.append("    /** COBOL-injectable variables (mirrors cobol_coverage filter). */")
        lines.append("    public static final java.util.Set<String> INJECTABLE_VARS =")
        lines.append("        java.util.Set.of(")
        var_lines = ['            "' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
                     for v in sorted_vars]
        lines.append(",\n".join(var_lines))
        lines.append("        );")
        lines.append("")
    else:
        lines.append("    public static final java.util.Set<String> INJECTABLE_VARS = java.util.Set.of();")
        lines.append("")

    # GROUP_LAYOUTS — registered on ProgramState so get/put for parent
    # group items composes/splits across the children's PIC widths.
    # Each layout is ``Object[][]{{{name,kind,length}, ...}}``.
    lines.append("    /** GROUP-item layouts: parent → ordered children with PIC widths. */")
    if group_layouts:
        lines.append(
            "    public static final java.util.Map<String, Object[][]> GROUP_LAYOUTS_INIT ="
        )
        lines.append("        java.util.Map.<String, Object[][]>ofEntries(")
        entries = []
        for parent, children in sorted(group_layouts.items()):
            child_arr = []
            for ch in children:
                cname = str(ch.get("name", "")).replace("\\", "\\\\").replace('"', '\\"')
                ckind = str(ch.get("kind", "alpha")).replace("\\", "\\\\").replace('"', '\\"')
                clen = int(ch.get("length", 0) or 0)
                if not cname or clen <= 0:
                    continue
                child_arr.append(
                    f'                new Object[]{{"{cname}", "{ckind}", {clen}}}'
                )
            if not child_arr:
                continue
            p_escaped = parent.replace("\\", "\\\\").replace('"', '\\"')
            entries.append(
                f'            java.util.Map.entry("{p_escaped}", new Object[][]{{\n'
                + ",\n".join(child_arr) + "\n            })"
            )
        if entries:
            lines.append(",\n".join(entries))
        lines.append("        );")
        lines.append("")
        lines.append("    static {")
        lines.append("        ProgramState.registerGroupLayouts(GROUP_LAYOUTS_INIT);")
        lines.append("    }")
        lines.append("")
    else:
        lines.append(
            "    public static final java.util.Map<String, Object[][]> GROUP_LAYOUTS_INIT ="
        )
        lines.append("        java.util.Collections.emptyMap();")
        lines.append("")

    # REDEFINES layouts: byte-buffer storage for memory-aliased fields.
    # Two static maps: group widths + per-field membership/offset/kind.
    lines.append("    /** REDEFINES groups: group_id → byte-buffer width. */")
    if redefines_groups:
        lines.append(
            "    public static final java.util.Map<String, Integer> REDEFINES_GROUP_WIDTH_INIT ="
        )
        lines.append("        java.util.Map.<String, Integer>ofEntries(")
        width_entries = []
        for gid, info in sorted(redefines_groups.items()):
            g_escaped = gid.replace("\\", "\\\\").replace('"', '\\"')
            width_entries.append(
                f'            java.util.Map.entry("{g_escaped}", {int(info["width"])})'
            )
        lines.append(",\n".join(width_entries))
        lines.append("        );")
        lines.append("")
        lines.append(
            "    /** REDEFINES fields: name → {group, offset, length, kind, signed, digits}. */"
        )
        lines.append(
            "    public static final java.util.Map<String, Object[]> REDEFINES_FIELD_INIT ="
        )
        lines.append("        java.util.Map.<String, Object[]>ofEntries(")
        field_entries = []
        for gid, info in sorted(redefines_groups.items()):
            g_escaped = gid.replace("\\", "\\\\").replace('"', '\\"')
            for fname, fent in info["members"].items():
                f_escaped = fname.replace("\\", "\\\\").replace('"', '\\"')
                k_escaped = str(fent["kind"]).replace("\\", "\\\\").replace('"', '\\"')
                signed = "true" if fent.get("signed") else "false"
                field_entries.append(
                    f'            java.util.Map.entry("{f_escaped}", new Object[]{{'
                    f'"{g_escaped}", '
                    f'{int(fent["offset"])}, '
                    f'{int(fent["length"])}, '
                    f'"{k_escaped}", '
                    f'{signed}, '
                    f'{int(fent.get("digits", 0))}}})'
                )
        lines.append(",\n".join(field_entries))
        lines.append("        );")
        lines.append("")
        lines.append("    static {")
        lines.append(
            "        ProgramState.registerRedefinesLayouts("
            "REDEFINES_GROUP_WIDTH_INIT, REDEFINES_FIELD_INIT);"
        )
        lines.append("    }")
        lines.append("")
    else:
        lines.append(
            "    public static final java.util.Map<String, Integer> REDEFINES_GROUP_WIDTH_INIT ="
        )
        lines.append("        java.util.Collections.emptyMap();")
        lines.append(
            "    public static final java.util.Map<String, Object[]> REDEFINES_FIELD_INIT ="
        )
        lines.append("        java.util.Collections.emptyMap();")
        lines.append("")

    # CicsProgram interface methods
    if is_terminal:
        lines.append("    @Override")
        lines.append(f'    public String programId() {{')
        lines.append(f'        return "{program.program_id}";')
        lines.append("    }")
        lines.append("")
        lines.append("    @Override")
        lines.append(
            f"    public List<CicsScreen.Field> screenLayout() {{"
        )
        lines.append(
            f"        return {screen_layout_class}.FIELDS;"
        )
        lines.append("    }")
        lines.append("")
        lines.append("    @Override")
        lines.append("    public void initState(ProgramState state) {")
        lines.append(
            f'        state.put("WS-TRANID", "{program.program_id[:4]}");'
        )
        lines.append(
            f'        state.put("WS-PGMNAME", "{program.program_id}");'
        )
        if lit_defaults:
            for var, val in lit_defaults.items():
                lines.append(
                    f'        state.put("{var}", "{val}");'
                )
        lines.append("    }")
    else:
        # Non-terminal programs get programId() for convenience but
        # not screenLayout() (no CicsScreen dependency).
        lines.append(f'    public String programId() {{')
        lines.append(f'        return "{program.program_id}";')
        lines.append("    }")

    lines.append("}")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# JUnit test generation
# ---------------------------------------------------------------------------


def _generate_test_class(
    program: Program,
    package_name: str,
    resource_name: str = "test_store.jsonl",
) -> str:
    """Generate a JUnit 5 test class with parameterized tests from test store."""
    class_name = _program_class_name(program.program_id)
    test_class_name = class_name + "Test"

    return f"""\
package {package_name};

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.MethodSource;
import static org.junit.jupiter.api.Assertions.*;

import com.google.gson.Gson;
import com.google.gson.JsonObject;
import com.google.gson.JsonElement;
import com.google.gson.JsonArray;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.stream.*;

/**
 * Generated integration tests for {class_name}.
 *
 * <p>Loads test cases from the JSONL test store (src/test/resources/{resource_name}).
 * Each test case provides input state, stub outcomes, and stub defaults that
 * reproduce a specific execution path through the COBOL program.
 */
class {test_class_name} {{

    private static final Gson GSON = new Gson();

    // --- Smoke tests ---

    @Test
    @DisplayName("Program runs with default state")
    void testRunCompletes() {{
        {class_name} program = new {class_name}();
        // Program may abend without stubs, but should not throw unhandled exceptions
        ProgramState result = assertDoesNotThrow(() -> program.run());
        assertNotNull(result);
    }}

    @Test
    @DisplayName("Default state is populated")
    void testDefaultState() {{
        Map<String, Object> defaults = {class_name}.defaultState();
        assertNotNull(defaults);
        assertFalse(defaults.isEmpty(), "default state should have variables");
    }}

    // --- Parameterized integration tests from test store ---

    static Stream<TestCaseData> testCases() throws IOException {{
        InputStream is = {test_class_name}.class.getResourceAsStream("/{resource_name}");
        if (is == null) {{
            return Stream.empty();
        }}
        BufferedReader reader = new BufferedReader(new InputStreamReader(is, StandardCharsets.UTF_8));
        List<TestCaseData> cases = new ArrayList<>();
        String line;
        while ((line = reader.readLine()) != null) {{
            line = line.trim();
            if (line.isEmpty()) continue;
            JsonObject obj = GSON.fromJson(line, JsonObject.class);
            if (!obj.has("input_state")) continue;  // skip progress records
            cases.add(TestCaseData.fromJson(obj));
        }}
        reader.close();
        return cases.stream();
    }}

    @ParameterizedTest(name = "TC#{{index}} layer={{0}} target={{1}}")
    @MethodSource("testCases")
    void testFromStore(TestCaseData tc) {{
        {class_name} program = new {class_name}();
        Set<String> knownParagraphs = new LinkedHashSet<>(program.getRegistry().allNames());

        // Build initial state with stub wiring
        Map<String, Object> overrides = new LinkedHashMap<>(tc.inputState);

        ProgramState state = ProgramState.withDefaults();
        state.putAll({class_name}.defaultState());
        state.putAll(overrides);

        // Wire stub outcomes
        for (Map.Entry<String, List<List<Object[]>>> e : tc.stubOutcomes.entrySet()) {{
            state.stubOutcomes.put(e.getKey(), new ArrayList<>(e.getValue()));
        }}
        for (Map.Entry<String, List<Object[]>> e : tc.stubDefaults.entrySet()) {{
            state.stubDefaults.put(e.getKey(), new ArrayList<>(e.getValue()));
        }}

        // Execute with the same target semantics as synthesis replay.
        String resolvedDirect = null;
        if (tc.target != null && tc.target.startsWith("direct:")) {{
            String para = tc.target.substring("direct:".length());
            int pipe = para.indexOf('|');
            if (pipe >= 0) {{
                para = para.substring(0, pipe);
            }}
            resolvedDirect = resolveParagraphName(para, knownParagraphs);
            Paragraph p = resolvedDirect == null ? null : program.getRegistry().get(resolvedDirect);
            if (p != null) {{
                p.execute(state);
            }} else {{
                // If target can't be resolved against this registry, run entry.
                program.run(state);
            }}
        }} else {{
            // For non-direct targets, execute normal program entry.
            program.run(state);
        }}

        // Assertions
        assertFalse(state.abended,
            "TC " + tc.id.substring(0, 8) + " abended unexpectedly");

        Set<String> covered = new LinkedHashSet<>(state.trace);

        // For direct targets, require the resolved paragraph to execute.
        if (resolvedDirect != null) {{
            assertTrue(covered.contains(resolvedDirect),
                "Expected direct paragraph " + resolvedDirect + " not covered in TC " + tc.id.substring(0, 8));
        }}

        // Optional strict mode: validate all resolvable expected paragraphs.
        boolean strictCoverage = Boolean.parseBoolean(System.getProperty("specter.strictCoverage", "false"));
        if (strictCoverage && !tc.expectedParagraphs.isEmpty()) {{
            for (String expected : tc.expectedParagraphs) {{
                String resolved = resolveParagraphName(expected, knownParagraphs);
                if (resolved != null) {{
                    assertTrue(covered.contains(resolved),
                        "Expected paragraph " + expected + " (resolved=" + resolved + ") not covered in TC " + tc.id.substring(0, 8));
                }}
            }}
        }}
    }}

    private static String normalizeParaName(String s) {{
        if (s == null) return "";
        return s.toUpperCase().replaceAll("[^A-Z0-9]", "");
    }}

    private static String resolveParagraphName(String requested, Set<String> known) {{
        if (requested == null || requested.isBlank() || known == null || known.isEmpty()) {{
            return null;
        }}
        if (known.contains(requested)) {{
            return requested;
        }}
        String req = requested.toUpperCase();
        for (String k : known) {{
            if (k.equalsIgnoreCase(req)) return k;
        }}
        String nreq = normalizeParaName(requested);
        for (String k : known) {{
            if (normalizeParaName(k).equals(nreq)) return k;
        }}
        for (String k : known) {{
            String nk = normalizeParaName(k);
            if (nk.endsWith(nreq) || nreq.endsWith(nk)) return k;
        }}
        return null;
    }}

    // --- Test case data holder ---

    static class TestCaseData {{
        final String id;
        final int layer;
        final String target;
        final Map<String, Object> inputState;
        final Map<String, List<List<Object[]>>> stubOutcomes;
        final Map<String, List<Object[]>> stubDefaults;
        final List<String> expectedParagraphs;

        TestCaseData(String id, int layer, String target,
                     Map<String, Object> inputState,
                     Map<String, List<List<Object[]>>> stubOutcomes,
                     Map<String, List<Object[]>> stubDefaults,
                     List<String> expectedParagraphs) {{
            this.id = id;
            this.layer = layer;
            this.target = target;
            this.inputState = inputState;
            this.stubOutcomes = stubOutcomes;
            this.stubDefaults = stubDefaults;
            this.expectedParagraphs = expectedParagraphs;
        }}

        static TestCaseData fromJson(JsonObject obj) {{
            String id = obj.has("id") ? obj.get("id").getAsString() : "";
            int layer = obj.has("layer") ? obj.get("layer").getAsInt() : 0;
            String target = obj.has("target") ? obj.get("target").getAsString() : "";

            Map<String, Object> inputState = new LinkedHashMap<>();
            if (obj.has("input_state")) {{
                for (Map.Entry<String, JsonElement> e : obj.getAsJsonObject("input_state").entrySet()) {{
                    inputState.put(e.getKey(), jsonToJava(e.getValue()));
                }}
            }}

            Map<String, List<List<Object[]>>> stubOutcomes = new LinkedHashMap<>();
            if (obj.has("stub_outcomes")) {{
                for (Map.Entry<String, JsonElement> e : obj.getAsJsonObject("stub_outcomes").entrySet()) {{
                    JsonArray queue = e.getValue().getAsJsonArray();
                    List<List<Object[]>> entries = new ArrayList<>();
                    for (JsonElement qe : queue) {{
                        List<Object[]> pairs = new ArrayList<>();
                        for (JsonElement pe : qe.getAsJsonArray()) {{
                            JsonArray pair = pe.getAsJsonArray();
                            String var = pair.get(0).getAsString();
                            Object val = jsonToJava(pair.get(1));
                            pairs.add(new Object[]{{var, val}});
                        }}
                        entries.add(pairs);
                    }}
                    stubOutcomes.put(e.getKey(), entries);
                }}
            }}

            Map<String, List<Object[]>> stubDefaults = new LinkedHashMap<>();
            if (obj.has("stub_defaults")) {{
                for (Map.Entry<String, JsonElement> e : obj.getAsJsonObject("stub_defaults").entrySet()) {{
                    List<Object[]> pairs = new ArrayList<>();
                    for (JsonElement pe : e.getValue().getAsJsonArray()) {{
                        JsonArray pair = pe.getAsJsonArray();
                        String var = pair.get(0).getAsString();
                        Object val = jsonToJava(pair.get(1));
                        pairs.add(new Object[]{{var, val}});
                    }}
                    stubDefaults.put(e.getKey(), pairs);
                }}
            }}

            List<String> paras = new ArrayList<>();
            if (obj.has("paragraphs_covered")) {{
                for (JsonElement e : obj.getAsJsonArray("paragraphs_covered")) {{
                    paras.add(e.getAsString());
                }}
            }}

            return new TestCaseData(id, layer, target, inputState,
                                    stubOutcomes, stubDefaults, paras);
        }}

        private static Object jsonToJava(JsonElement e) {{
            if (e.isJsonNull()) return "";
            if (e.isJsonPrimitive()) {{
                var p = e.getAsJsonPrimitive();
                if (p.isBoolean()) return p.getAsBoolean();
                if (p.isNumber()) {{
                    double d = p.getAsDouble();
                    if (d == Math.floor(d) && !Double.isInfinite(d)) {{
                        long l = p.getAsLong();
                        if (l >= Integer.MIN_VALUE && l <= Integer.MAX_VALUE) {{
                            return (int) l;
                        }}
                        return l;
                    }}
                    return d;
                }}
                return p.getAsString();
            }}
            return e.toString();
        }}

        @Override
        public String toString() {{
            return "layer=" + layer + " target=" + target;
        }}
    }}
}}
"""


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def _generate_mockito_verify_calls(test_store_path: str) -> str:
    """Analyze test store JSONL to determine which verify() calls to emit.

    Scans stub_outcomes keys across all test cases and generates Mockito
    verify calls for the typed operations that appear.
    """
    import json

    op_keys: set[str] = set()
    try:
        with open(test_store_path) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                if "stub_outcomes" in obj:
                    op_keys.update(obj["stub_outcomes"].keys())
                if "stub_defaults" in obj:
                    op_keys.update(obj["stub_defaults"].keys())
    except Exception:
        pass

    lines: list[str] = []
    # Map operation key patterns to typed verify calls
    if "CICS" in op_keys:
        lines.append(
            "        // CICS operations were used in test data"
        )
    if "DLI" in op_keys:
        lines.append(
            "        // DLI operations were used in test data"
        )
    for key in sorted(op_keys):
        if key.startswith("CALL:MQ"):
            mq_op = key.split(":", 1)[1]
            if mq_op == "MQOPEN":
                lines.append(
                    "        // MQ operations detected in test store"
                )
                break

    # Verify that stub executor was engaged if stubs were consumed
    if op_keys:
        lines.append(
            "        // Verify stub executor was engaged (if stubs were consumed)"
        )
        lines.append(
            "        if (!consumedKeys.isEmpty()) {"
        )
        lines.append(
            "            verify(spyStubs, atLeastOnce())"
            ".applyStubOutcome(any(ProgramState.class), anyString());"
        )
        lines.append(
            "        }"
        )

    return "\n".join(lines) if lines else "        // No stub operations detected"


# ---------------------------------------------------------------------------
# BMS screen field extraction
# ---------------------------------------------------------------------------


def _walk_all_statements(stmts: list[Statement]):
    """Yield every statement in a tree (depth-first)."""
    for s in stmts:
        yield s
        yield from _walk_all_statements(s.children)


def _extract_bms_info(program: Program) -> dict | None:
    """Extract BMS map field info from the COBOL AST.

    Scans EXEC CICS SEND MAP / RECEIVE MAP statements and collects field
    names from ``FIELD OF <RECORD>`` patterns in MOVE statements.

    Field order is preserved from the AST paragraph order — this matches
    the original BMS map layout, which is critical for correct screen
    rendering.

    Returns a dict keyed by map name, each with 'output' and 'input' field
    lists, or None if no BMS operations are found.
    """
    maps: dict[str, dict[str, list[str]]] = {}
    _seen: dict[str, dict[str, set[str]]] = {}  # dedup tracking

    # Pass 1: find map names from SEND MAP / RECEIVE MAP
    # Also discover record names from FROM(...) / INTO(...) clauses
    records: dict[str, dict[str, str | None]] = {}  # map_name -> {out_record, in_record}
    for para in program.paragraphs:
        for stmt in _walk_all_statements(para.statements):
            if stmt.type != "EXEC_CICS":
                continue
            raw = stmt.attributes.get("raw_text", "") + " " + stmt.text
            # Literal map name: MAP('NAME')
            for pat in [r"SEND\s+MAP\s*\('([^']+)'\)",
                        r"RECEIVE\s+MAP\s*\('([^']+)'\)"]:
                m = re.search(pat, raw, re.IGNORECASE)
                if m:
                    mn = m.group(1).upper()
                    maps.setdefault(mn, {"output": [], "input": []})
                    _seen.setdefault(mn, {"output": set(), "input": set()})
            # Variable map name: MAP(VAR) with FROM/INTO record
            if re.search(r"(?:SEND|RECEIVE)\s+MAP", raw, re.IGNORECASE):
                from_m = re.search(r"FROM\((\w+)\)", raw, re.IGNORECASE)
                into_m = re.search(r"INTO\((\w+)\)", raw, re.IGNORECASE)
                if from_m:
                    rec = from_m.group(1).upper()
                    # Derive map name from record: CACTUPAO -> CACTUPA
                    if rec.endswith("O"):
                        derived = rec[:-1]
                        maps.setdefault(derived, {"output": [], "input": []})
                        _seen.setdefault(derived, {"output": set(), "input": set()})
                        records.setdefault(derived, {"out_record": None, "in_record": None})
                        records[derived]["out_record"] = rec
                if into_m:
                    rec = into_m.group(1).upper()
                    if rec.endswith("I"):
                        derived = rec[:-1]
                        maps.setdefault(derived, {"output": [], "input": []})
                        _seen.setdefault(derived, {"output": set(), "input": set()})
                        records.setdefault(derived, {"out_record": None, "in_record": None})
                        records[derived]["in_record"] = rec

    if not maps:
        return None

    # Pass 2: collect field references from OF <RECORD> patterns,
    # preserving first-seen order (AST paragraph order = BMS map order).
    for map_name, info in maps.items():
        seen = _seen[map_name]
        rec_info = records.get(map_name, {})
        out_record = rec_info.get("out_record") or (map_name + "O")
        in_record = rec_info.get("in_record") or (map_name + "I")
        for para in program.paragraphs:
            for stmt in _walk_all_statements(para.statements):
                text = stmt.text + " " + stmt.attributes.get("source", "")
                text += " " + stmt.attributes.get("targets", "")
                for m in re.finditer(
                    rf"([A-Z][A-Z0-9-]+)\s+OF\s+{re.escape(out_record)}\b",
                    text, re.IGNORECASE,
                ):
                    fname = m.group(1).upper()
                    if fname not in seen["output"]:
                        seen["output"].add(fname)
                        info["output"].append(fname)
                for m in re.finditer(
                    rf"([A-Z][A-Z0-9-]+)\s+OF\s+{re.escape(in_record)}\b",
                    text, re.IGNORECASE,
                ):
                    fname = m.group(1).upper()
                    if fname not in seen["input"]:
                        seen["input"].add(fname)
                        info["input"].append(fname)

    # Separate length/attribute fields from value fields in input
    result = {}
    for map_name, info in maps.items():
        # Only keep "I" suffixed fields (data), skip "A" (attribute) and "L" (length)
        data_inputs = [
            f for f in info["input"]
            if f.endswith("I") and not f.endswith("LI")
        ]
        # If no "I"-suffixed fields, fall back to all non-L/non-A fields
        if not data_inputs:
            data_inputs = [
                f for f in info["input"]
                if not f.endswith("L") and not f.endswith("A")
            ]
        length_fields = [
            f for f in info["input"] if f.endswith("L")
        ]
        result[map_name] = {
            "output": info["output"],
            "input": data_inputs,
            "length_fields": length_fields,
        }
    return result


# Common BMS field abbreviation → human-readable label mapping.
# Keyed by uppercase base name (no I/O/A/L suffix).
_BMS_LABEL_MAP: dict[str, str] = {
    "ACCTSID": "Account ID",
    "AADDGRP": "Group",
    "ACSFNAM": "First Name",
    "ACSMNAM": "Middle Name",
    "ACSLNAM": "Last Name",
    "ACSADL1": "Address Line 1",
    "ACSADL2": "Address Line 2",
    "ACSCITY": "City",
    "ACSCTRY": "Country",
    "ACSSTE": "State",
    "ACSSTTE": "State",
    "ACSZPC": "Zip",
    "ACSZIPCO": "Zip",
    "ACRDLIM": "Credit Limit",
    "ACSHLIM": "Cash Limit",
    "ACURBAL": "Current Balance",
    "ACRCYCR": "Cycle Credit",
    "ACRCYDB": "Cycle Debit",
    "ACSEFTC": "EFT Account",
    "ACSGOVT": "Govt ID",
    "ACSPFLG": "Primary Holder",
    "ACSTFCO": "FICO Score",
    "ACSTTUS": "Status",
    "ACSTNUMO": "Customer#",
    "ACTSSN1": "SSN-1",
    "ACTSSN2": "SSN-2",
    "ACTSSN3": "SSN-3",
    "ACSPH1A": "Phone1 Area",
    "ACSPH1B": "Phone1 Prefix",
    "ACSPH1C": "Phone1 Line",
    "ACSPH2A": "Phone2 Area",
    "ACSPH2B": "Phone2 Prefix",
    "ACSPH2C": "Phone2 Line",
    "PGMNAME": "Program",
    "TRNNAME": "Trans",
    "CURDATE": "Date",
    "CURTIME": "Time",
    "APPLID": "Applid",
    "SYSID": "Sysid",
    "USERID": "User ID",
    "PASSWD": "Password",
    "ERRMSG": "Error",
    "INFOMSG": "Info",
    "OPNYEAR": "Open Year",
    "OPNMON": "Open Month",
    "OPNDAY": "Open Day",
    "EXPYEAR": "Exp Year",
    "EXPMON": "Exp Month",
    "EXPDAY": "Exp Day",
    "RISYEAR": "Reissue Year",
    "RISMON": "Reissue Month",
    "RISDAY": "Reissue Day",
    "DOBYEAR": "DOB Year",
    "DOBMON": "DOB Month",
    "DOBDAY": "DOB Day",
}


def _bms_label(field_name: str) -> str:
    """Derive a human-readable label from a BMS field name."""
    # Strip common suffixes
    base = field_name
    for suffix in ("I", "O", "A", "L", "C"):
        if base.endswith(suffix) and len(base) > 2:
            candidate = base[:-1]
            if candidate.upper() in _BMS_LABEL_MAP:
                return _BMS_LABEL_MAP[candidate.upper()]
    if base.upper() in _BMS_LABEL_MAP:
        return _BMS_LABEL_MAP[base.upper()]
    # Fallback: strip suffix, expand
    base = field_name
    if base.endswith(("I", "O")) and len(base) > 2:
        base = base[:-1]
    return base.replace("-", " ").replace("_", " ").title()


def _compute_screen_layout(
    bms_info: dict,
) -> list[dict]:
    """Compute row/col positions for BMS fields using naming heuristics.

    Returns a list of field dicts with keys: name, row, col, width, type,
    label, masked.
    """
    layout: list[dict] = []

    # Use the first (typically only) map
    map_name = next(iter(bms_info))
    info = bms_info[map_name]
    output = info["output"]
    input_fields = info["input"]

    row = 0

    # Title fields (centered)
    titles = sorted(f for f in output if "TITLE" in f)
    for f in titles:
        layout.append({
            "name": f, "row": row, "col": 0, "width": 80,
            "type": "CENTER", "label": None, "masked": False,
        })
        row += 1
    row = max(row, 2)

    # Navigation info line (transaction, program, date, time)
    nav_fields = [f for f in output
                  if any(x in f for x in ("TRNNAME", "PGMNAME"))]
    date_fields = [f for f in output
                   if any(x in f for x in ("CURDATE", "CURTIME"))]
    col = 2
    for f in sorted(nav_fields):
        label = _bms_label(f)
        layout.append({
            "name": f, "row": row, "col": col, "width": 12,
            "type": "DISPLAY", "label": label, "masked": False,
        })
        col += 22
    col = 50
    for f in sorted(date_fields):
        label = _bms_label(f)
        layout.append({
            "name": f, "row": row, "col": col, "width": 10,
            "type": "DISPLAY", "label": label, "masked": False,
        })
        col += 18
    if nav_fields or date_fields:
        row += 1

    # System info (APPLID, SYSID)
    sys_fields = [f for f in output
                  if any(x in f for x in ("APPLID", "SYSID"))]
    col = 2
    for f in sorted(sys_fields):
        label = _bms_label(f)
        layout.append({
            "name": f, "row": row, "col": col, "width": 10,
            "type": "DISPLAY", "label": label, "masked": False,
        })
        col += 22
    if sys_fields:
        row += 1

    row += 1  # blank separator

    # Remaining output fields (not titles, nav, date, sys, or messages)
    covered = {d["name"] for d in layout}
    msg_fields = [f for f in output if any(x in f for x in ("ERRMSG", "MSG"))]
    remaining = [f for f in output if f not in covered and f not in msg_fields]

    # Reserve rows: 22 for messages, 23 for status bar
    max_data_row = 21
    avail_rows = max_data_row - row

    # Budget: split available rows between output (display) and input
    n_out = len(remaining)
    n_in = len(input_fields)
    total = n_out + n_in

    if total <= avail_rows:
        # Everything fits in single column
        out_budget = n_out
        in_budget = n_in
    else:
        # Prioritise input fields; output fields get 2-column layout
        in_budget = min(n_in, avail_rows - 2)  # at least 2 rows for output
        out_budget_rows = avail_rows - in_budget
        out_budget = out_budget_rows * 2  # 2-column

    # Output fields (order preserved from AST = BMS map order)
    placed_out = 0
    for i, f in enumerate(remaining):
        if placed_out >= out_budget:
            break
        label = _bms_label(f)
        if total > avail_rows:
            # 2-column layout
            c = 2 if i % 2 == 0 else 42
            r = row + i // 2
        else:
            c = 2
            r = row + i
        if r >= max_data_row:
            break
        layout.append({
            "name": f, "row": r, "col": c, "width": 35,
            "type": "DISPLAY", "label": label, "masked": False,
        })
        placed_out += 1
    if placed_out > 0:
        if total > avail_rows:
            row += (placed_out + 1) // 2
        else:
            row += placed_out

    # Input fields (order preserved from AST = BMS map order,
    # but push password fields to the end)
    pw_inputs = [f for f in input_fields
                 if any(x in f.upper() for x in ("PASSW", "PWD", "PIN"))]
    non_pw_inputs = [f for f in input_fields if f not in pw_inputs]
    ordered_inputs = non_pw_inputs + pw_inputs
    for i, f in enumerate(ordered_inputs):
        if i >= in_budget:
            break
        r = row + i
        if r >= max_data_row:
            break
        label = _bms_label(f)
        is_password = any(x in f.upper() for x in ("PASSW", "PWD", "PIN"))
        layout.append({
            "name": f, "row": r, "col": 30, "width": 20,
            "type": "INPUT", "label": label, "masked": is_password,
        })

    # Message/error fields near bottom
    msg_row = max_data_row
    for f in sorted(msg_fields):
        layout.append({
            "name": f, "row": msg_row, "col": 2, "width": 76,
            "type": "MESSAGE", "label": None, "masked": False,
        })
        msg_row += 1

    return layout


def _generate_screen_layout_java(
    layout: list[dict],
    package_name: str,
    prog_class_name: str,
    screen_layout_class_name: str = "ScreenLayout",
) -> str:
    """Generate ScreenLayout.java with static field definitions.

    *screen_layout_class_name* controls the Java class name — use
    ``ScreenLayout_PROGRAMID`` in multi-program mode to avoid collisions.
    """
    entries = []
    for f in layout:
        masked = "true" if f["masked"] else "false"
        label = f'"{f["label"]}"' if f["label"] else "null"
        entries.append(
            f'        new CicsScreen.Field("{f["name"]}", '
            f'{f["row"]}, {f["col"]}, {f["width"]}, '
            f'CicsScreen.FieldType.{f["type"]}, {label}, {masked})'
        )
    field_entries = ",\n".join(entries)
    return SCREEN_LAYOUT_JAVA.format(
        package_name=package_name,
        program_class_name=prog_class_name,
        screen_layout_class_name=screen_layout_class_name,
        field_entries=field_entries,
    )


def generate_java_project(
    program: Program,
    var_report: VariableReport | None = None,
    output_dir: str = ".",
    instrument: bool = False,
    test_store_path: str | None = None,
    copybook_paths: list[str] | None = None,
    docker: bool = False,
    integration_tests: bool = False,
    snapshot_dir: str | None = None,
    cobol_source: str | None = None,
) -> str:
    """Generate a complete Maven project from a COBOL Program AST.

    Args:
        program: Parsed COBOL program AST.
        var_report: Optional variable report (extracted if not given).
        output_dir: Root directory for the Maven project.
        instrument: If True, generate instrumented state tracking
            (reserved for future use).
        test_store_path: If provided, generate JUnit test classes.
        copybook_paths: Directories containing .cpy files for DDL generation.
        docker: If True, generate Dockerfile and docker-compose.yml.
        integration_tests: If True, generate integration-tests/ with Mockito.

    Returns:
        The absolute path to the generated Maven project directory.
    """
    if var_report is None:
        var_report = extract_variables(program)

    # Update global paragraph order for _get_thru_range
    import specter.code_generator as _cg

    _cg._PARAGRAPH_ORDER[:] = [p.name for p in program.paragraphs]

    # Detect 88-level mutual exclusion groups
    global _88_LEVEL_SIBLINGS
    _88_LEVEL_SIBLINGS = _detect_88_level_groups(program)

    # Naming
    program_id = program.program_id
    artifact_id = re.sub(r"[^a-z0-9-]", "-", program_id.lower())
    package_name = "com.specter.generated"
    group_id = "com.specter"

    # Directory structure
    out = Path(output_dir)
    src_main = out / "src" / "main" / "java" / "com" / "specter" / "generated"
    src_test = (
        out / "src" / "test" / "java" / "com" / "specter" / "generated"
    )
    src_main.mkdir(parents=True, exist_ok=True)
    src_test.mkdir(parents=True, exist_ok=True)

    prog_class_name = _program_class_name(program_id)
    main_class = f"{package_name}.Main"

    # pom.xml
    pom_content = POM_XML.format(
        group_id=group_id,
        artifact_id=artifact_id,
        program_name=program_id,
        main_class=main_class,
    )
    (out / "pom.xml").write_text(pom_content, encoding="utf-8")

    # Runtime classes
    fmt_args = {
        "package_name": package_name,
        "program_id": program_id,
        "program_class_name": prog_class_name,
    }
    _runtime_files = {
        "ProgramState.java": PROGRAM_STATE_JAVA,
        "GobackSignal.java": GOBACK_SIGNAL_JAVA,
        "CobolRuntime.java": COBOL_RUNTIME_JAVA,
        "Paragraph.java": PARAGRAPH_JAVA,
        "ParagraphRegistry.java": PARAGRAPH_REGISTRY_JAVA,
        "StubExecutor.java": STUB_EXECUTOR_JAVA,
        "DefaultStubExecutor.java": DEFAULT_STUB_EXECUTOR_JAVA,
        "JdbcStubExecutor.java": JDBC_STUB_EXECUTOR_JAVA,
        "SectionBase.java": SECTION_BASE_JAVA,
        "AppConfig.java": APP_CONFIG_JAVA,
        "Main.java": MAIN_JAVA,
    }
    for filename, template in _runtime_files.items():
        content = template.format(**fmt_args)
        (src_main / filename).write_text(content, encoding="utf-8")

    # Shared code builder for tracking branch/loop IDs across paragraphs
    shared_cb = _JavaCodeBuilder()

    # Build the 88-level child→(parent, value) map so bare condition-name
    # references like ``IF APPL-AOK`` get rewritten to a parent-value
    # comparison (mirrors specter.code_generator.generate_code's level_88_map).
    if copybook_paths:
        from .copybook_parser import parse_copybook
        import os as _os
        for d in copybook_paths:
            if not _os.path.isdir(d):
                continue
            for fname in sorted(_os.listdir(d)):
                if not fname.lower().endswith(".cpy"):
                    continue
                with open(_os.path.join(d, fname)) as fh:
                    rec = parse_copybook(fh.read(), copybook_file=fname)
                if not rec.fields:
                    continue
                for fld in rec.fields:
                    if not fld.values_88:
                        continue
                    parent_name = fld.name.upper() if fld.name else ""
                    if not parent_name:
                        continue
                    for child_name, child_value in fld.values_88.items():
                        shared_cb.level_88_map.setdefault(
                            child_name.upper(),
                            (parent_name, child_value),
                        )
    if cobol_source:
        try:
            from .variable_domain import _extract_88_values_from_source
            for parent_name, children in _extract_88_values_from_source(cobol_source).items():
                for child_name, child_value in children.items():
                    shared_cb.level_88_map.setdefault(
                        child_name.upper(),
                        (parent_name.upper(), child_value),
                    )
        except Exception as exc:  # noqa: BLE001
            print(f"  Warning: 88-level inline extract failed: {exc}")

    # Build the PIC info map (var_name → {length, kind}) so the generated
    # Java can truncate input values to COBOL field widths. Sources: parsed
    # copybooks + inline DATA DIVISION fields scanned from cobol_source.
    shared_injectable: set[str] = set()
    shared_group_layouts: dict = {}
    shared_redefines: dict = {}
    try:
        from .pic_extractor import (
            build_pic_info,
            group_layouts_from_source,
            injectable_var_names,
        )
        from .redefines_extractor import extract_redefines_groups
        from .copybook_parser import parse_copybook as _parse_cpy
        import os as _os
        _pic_records = []
        if copybook_paths:
            for d in copybook_paths:
                if not _os.path.isdir(d):
                    continue
                for fname in sorted(_os.listdir(d)):
                    if not fname.lower().endswith(".cpy"):
                        continue
                    with open(_os.path.join(d, fname)) as fh:
                        rec = _parse_cpy(fh.read(), copybook_file=fname)
                    if rec.fields:
                        _pic_records.append(rec)
        shared_cb.pic_info = build_pic_info(_pic_records, cobol_source)
        shared_injectable = injectable_var_names(
            program, var_report, _pic_records, cobol_source,
        )
        if cobol_source:
            shared_group_layouts = group_layouts_from_source(cobol_source)
            shared_redefines = extract_redefines_groups(cobol_source)
            # File → status-var map (SELECT ... FILE STATUS IS <var>) so
            # OPEN/READ/CLOSE codegen can emit ``state.put(status-var, "")``
            # before each stub call, matching the COBOL mock's unconditional
            # ``MOVE MOCK-ALPHA-STATUS TO <status-var>`` (which is SPACES on
            # empty FIFO). Without this, Java tests with no stub outcomes
            # inherit the injected input value for the status var instead of
            # COBOL's freshly-blanked "  ", producing systematic display
            # divergences like ``FILE STATUS IS: NNNN0000`` vs snapshot's
            # ``FILE STATUS IS: NNNN 032``.
            try:
                from .cobol_mock import _extract_file_status_map as _fsm
                with open(cobol_source, "r") as _fh:
                    shared_cb.file_status_map = _fsm(_fh.readlines())
            except Exception as _exc:  # noqa: BLE001
                print(f"  Warning: file_status_map extract failed: {_exc}")
    except Exception as exc:  # noqa: BLE001
        print(f"  Warning: PIC / injectable / group / redefines extract failed: {exc}")

    # Collect all PERFORM targets to detect missing paragraphs
    defined_paras = {p.name for p in program.paragraphs}
    referenced_paras: set[str] = set()

    def _collect_targets(stmt: Statement) -> None:
        target = stmt.attributes.get("target", "")
        if target:
            referenced_paras.add(target)
        for child in stmt.children:
            _collect_targets(child)

    for para in program.paragraphs:
        for stmt in para.statements:
            _collect_targets(stmt)

    # Group paragraphs into sections by leading digit, preserving
    # COBOL source order (important for PERFORM THRU).
    from collections import OrderedDict

    sections: OrderedDict[str, list[tuple[str, list[Statement]]]] = (
        OrderedDict()
    )
    for para in program.paragraphs:
        key = _section_key(para.name)
        if key not in sections:
            sections[key] = []
        sections[key].append((para.name, para.statements))

    # Include stubs for referenced but undefined paragraphs
    missing = referenced_paras - defined_paras
    for name in sorted(missing):
        key = _section_key(name)
        if key not in sections:
            sections[key] = []
        sections[key].append((name, []))

    # Generate one Java file per section
    section_classes: list[str] = []
    for key in sections:
        sec_class_name, sec_src = _generate_section_class(
            key, sections[key], package_name, shared_cb,
        )
        (src_main / f"{sec_class_name}.java").write_text(
            sec_src, encoding="utf-8"
        )
        section_classes.append(sec_class_name)

    # Terminal UI detection (needed before program class generation)
    bms_info = _extract_bms_info(program)
    is_terminal = bms_info is not None

    # Compute per-program literal constants for CicsProgram.initState()
    _lit_defaults_for_class = None
    if is_terminal:
        _lit_defaults_for_class = {
            "LIT-THISTRANID": program_id[:4],
            "LIT-THISPGM": program_id,
            "LIT-THISMAP": next(iter(bms_info), ""),
            "LIT-THISMAPSET": next(iter(bms_info), "")[:6]
                if bms_info else "",
            "LIT-MENUPGM": "COMEN01C",
            "LIT-MENUTRANID": "COME",
            "CCDA-TITLE01": "Credit Card Demo Application",
            "CCDA-TITLE02": program_id + " - Account Update",
            "CCDA-MSG-THANK-YOU": "Thank you for using the application",
            "CCDA-MSG-INVALID-KEY": "Invalid key pressed",
        }

    # Program class
    prog_src = _generate_program_class(
        program, var_report, package_name,
        section_classes=section_classes,
        is_terminal=is_terminal,
        screen_layout_class="ScreenLayout",
        lit_defaults=_lit_defaults_for_class,
        level_88_map=shared_cb.level_88_map,
        pic_info=shared_cb.pic_info,
        injectable_vars=shared_injectable,
        group_layouts=shared_group_layouts,
        redefines_groups=shared_redefines,
        file_status_map=shared_cb.file_status_map,
    )
    (src_main / f"{prog_class_name}.java").write_text(
        prog_src, encoding="utf-8"
    )

    # Test class + test resources
    if test_store_path is not None:
        import shutil

        test_src = _generate_test_class(program, package_name)
        test_class_name = prog_class_name + "Test"
        (src_test / f"{test_class_name}.java").write_text(
            test_src, encoding="utf-8"
        )

        # Copy test store JSONL into test resources
        test_resources = out / "src" / "test" / "resources"
        test_resources.mkdir(parents=True, exist_ok=True)
        shutil.copy2(test_store_path, test_resources / "test_store.jsonl")

    # Parse copybooks once -- shared between init.sql and per-test seed SQL.
    copybook_records: list = []
    if copybook_paths:
        import os as _os

        from .copybook_parser import (
            generate_init_sql,
            parse_copybook,
        )

        sql_dir = out / "sql"
        sql_dir.mkdir(parents=True, exist_ok=True)
        ddl = generate_init_sql(copybook_paths, dialect="postgresql")
        (sql_dir / "init.sql").write_text(ddl, encoding="utf-8")

        for d in copybook_paths:
            if not _os.path.isdir(d):
                continue
            for fname in sorted(_os.listdir(d)):
                if not fname.lower().endswith(".cpy"):
                    continue
                with open(_os.path.join(d, fname)) as fh:
                    rec = parse_copybook(fh.read(), copybook_file=fname)
                if rec.name and rec.fields:
                    copybook_records.append(rec)

    # Integration tests (Mockito spy-based) + per-test-case WireMock + seed SQL.
    if integration_tests and test_store_path is not None:
        import json as _json
        import shutil

        from .java_templates.seed_sql import build_seed_sql, build_table_index
        from .java_templates.wiremock import write_mappings

        it_dir = out / "integration-tests"
        it_src = (
            it_dir / "src" / "test" / "java"
            / "com" / "specter" / "generated"
        )
        it_src.mkdir(parents=True, exist_ok=True)

        # Integration POM
        it_pom = INTEGRATION_POM_XML.format(
            group_id=group_id,
            artifact_id=artifact_id,
            program_name=program_id,
        )
        (it_dir / "pom.xml").write_text(it_pom, encoding="utf-8")

        # Mockito integration test class
        verify_calls = _generate_mockito_verify_calls(test_store_path)
        it_test_src = MOCKITO_INTEGRATION_TEST_JAVA.format(
            package_name=package_name,
            program_class_name=prog_class_name,
            verify_calls=verify_calls,
        )
        it_test_class = prog_class_name + "IT"
        (it_src / f"{it_test_class}.java").write_text(
            it_test_src, encoding="utf-8"
        )

        # Equivalence support classes (always emitted so the IT compiles
        # even when no snapshots are present — assertEquivalent no-ops on
        # missing snapshot resources).
        (it_src / "CobolSnapshot.java").write_text(
            COBOL_SNAPSHOT_JAVA.format(package_name=package_name),
            encoding="utf-8",
        )
        (it_src / "EquivalenceAssert.java").write_text(
            EQUIVALENCE_ASSERT_JAVA.format(package_name=package_name),
            encoding="utf-8",
        )

        # Copy test store JSONL into integration test resources
        it_resources = it_dir / "src" / "test" / "resources"
        it_resources.mkdir(parents=True, exist_ok=True)
        shutil.copy2(test_store_path, it_resources / "test_store.jsonl")

        # Copy COBOL ground-truth snapshots if provided.
        if snapshot_dir is not None:
            snap_src = Path(snapshot_dir)
            if snap_src.is_dir():
                snap_dst = it_resources / "cobol_snapshots"
                snap_dst.mkdir(parents=True, exist_ok=True)
                copied = 0
                for f in sorted(snap_src.glob("*.json")):
                    shutil.copy2(f, snap_dst / f.name)
                    copied += 1
                print(f"  COBOL snapshots: {copied} files copied for equivalence assertions")

        # Per-test-case artifacts: WireMock mappings + seed SQL.
        wm_root_run = out / "wiremock" / "mappings"
        wm_root_it = it_resources / "wiremock" / "mappings"
        seeds_dir = it_resources / "seeds"
        seeds_dir.mkdir(parents=True, exist_ok=True)
        wm_root_run.mkdir(parents=True, exist_ok=True)
        wm_root_it.mkdir(parents=True, exist_ok=True)

        table_index = build_table_index(copybook_records) if copybook_records else {}
        seeds_written = 0
        wm_count = 0
        from .cobol_snapshot import normalize_stub_outcomes

        with open(test_store_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = _json.loads(line)
                except _json.JSONDecodeError:
                    continue
                if "input_state" not in obj or "id" not in obj:
                    continue
                tc_id = str(obj["id"])
                stub_outcomes = normalize_stub_outcomes(obj.get("stub_outcomes"))

                # WireMock mappings (always emit when there are routable CALLs;
                # written under both project root and IT test resources).
                files_run = write_mappings(tc_id, stub_outcomes, wm_root_run)
                files_it = write_mappings(tc_id, stub_outcomes, wm_root_it)
                wm_count += len(files_run) + len(files_it)

                # Seed SQL only when copybook DDL is available.
                if table_index:
                    sql = build_seed_sql(
                        tc_id,
                        obj.get("input_state") or {},
                        stub_outcomes,
                        table_index,
                    )
                    if sql:
                        (seeds_dir / f"{tc_id}.sql").write_text(
                            sql, encoding="utf-8"
                        )
                        seeds_written += 1

        if not table_index:
            print(
                "  Warning: no copybook DDL provided; seed SQL skipped. "
                "JdbcStubExecutor reads will return NOTFND."
            )
        else:
            print(f"  Seed SQL written for {seeds_written} test cases")
        print(f"  WireMock mappings: {wm_count} files written")

    # Docker deployment files
    if docker:
        dockerfile = DOCKERFILE.format(artifact_id=artifact_id)
        (out / "Dockerfile").write_text(dockerfile, encoding="utf-8")

        compose = DOCKER_COMPOSE_YML.format(program_name=program_id)
        (out / "docker-compose.yml").write_text(compose, encoding="utf-8")

        # Ensure sql/ directory exists for docker-compose volume mount
        sql_dir = out / "sql"
        sql_dir.mkdir(parents=True, exist_ok=True)
        init_sql = sql_dir / "init.sql"
        if not init_sql.exists():
            init_sql.write_text(
                "-- Auto-generated placeholder. Add CREATE TABLE statements here.\n",
                encoding="utf-8",
            )

    # Terminal UI (Lanterna BMS screen emulation)
    if bms_info is not None:
        layout = _compute_screen_layout(bms_info)
        screen_layout_src = _generate_screen_layout_java(
            layout, package_name, prog_class_name,
        )
        (src_main / "ScreenLayout.java").write_text(
            screen_layout_src, encoding="utf-8"
        )

        # Static terminal classes
        _terminal_files = {
            "CicsReturnSignal.java": CICS_RETURN_SIGNAL_JAVA,
            "CicsScreen.java": TERMINAL_SCREEN_JAVA,
            "HeadlessScreen.java": HEADLESS_SCREEN_JAVA,
            "BmsScreen.java": BMS_SCREEN_JAVA,
            "TerminalStubExecutor.java": TERMINAL_STUB_EXECUTOR_JAVA,
            "XctlSignal.java": XCTL_SIGNAL_JAVA,
            "CicsProgram.java": CICS_PROGRAM_JAVA,
        }
        for filename, template in _terminal_files.items():
            content = template.format(**fmt_args)
            (src_main / filename).write_text(content, encoding="utf-8")

        # TerminalMain needs initial state lines for CICS fields
        initial_lines = []
        initial_lines.append(
            '        state.put("WS-TRANID", "' + program_id[:4] + '");'
        )
        initial_lines.append(
            '        state.put("WS-PGMNAME", "' + program_id + '");'
        )

        # Seed COBOL literal constants (LIT-*, CCDA-*) used for
        # screen titles, program names, map names, etc.
        _lit_defaults = {
            "LIT-THISTRANID": program_id[:4],
            "LIT-THISPGM": program_id,
            "LIT-THISMAP": next(iter(bms_info), ""),
            "LIT-THISMAPSET": next(iter(bms_info), "")[:6]
                if bms_info else "",
            "LIT-MENUPGM": "COMEN01C",
            "LIT-MENUTRANID": "COME",
            "CCDA-TITLE01": "Credit Card Demo Application",
            "CCDA-TITLE02": program_id + " - Account Update",
            "CCDA-MSG-THANK-YOU": "Thank you for using the application",
            "CCDA-MSG-INVALID-KEY": "Invalid key pressed",
        }
        for var, val in _lit_defaults.items():
            initial_lines.append(
                f'        state.put("{var}", "{val}");'
            )
        terminal_main_src = TERMINAL_MAIN_JAVA.format(
            **fmt_args,
            initial_state_lines="\n".join(initial_lines),
        )
        (src_main / "TerminalMain.java").write_text(
            terminal_main_src, encoding="utf-8"
        )

    return str(out.resolve())


# ---------------------------------------------------------------------------
# Multi-program project generation (XCTL routing)
# ---------------------------------------------------------------------------


def generate_multi_program_project(
    ast_paths: list[str],
    output_dir: str = ".",
    package_name: str = "com.specter.generated",
    per_program_stores: dict[str, str] | None = None,
) -> str:
    """Generate a single Maven project containing multiple CICS programs.

    Each AST file is parsed independently.  All programs share the same
    runtime classes (ProgramState, StubExecutor, etc.) and are written
    into one Maven project.  A ``MultiProgramRunner`` is generated that
    routes XCTL transfers between the programs.

    Args:
        ast_paths: Paths to JSON AST files.
        output_dir: Root directory for the Maven project.
        package_name: Java package name for generated classes.
        per_program_stores: Optional mapping of program_id → JSONL test
            store path.  When provided, a JUnit test class and test
            resource are generated for each program that has a store.

    Returns:
        The absolute path to the generated Maven project directory.
    """
    from .ast_parser import parse_ast
    from collections import OrderedDict

    out = Path(output_dir)
    src_main = out / "src" / "main" / "java" / "com" / "specter" / "generated"
    src_test = out / "src" / "test" / "java" / "com" / "specter" / "generated"
    src_main.mkdir(parents=True, exist_ok=True)
    src_test.mkdir(parents=True, exist_ok=True)

    # Parse all programs
    programs: list[tuple[Program, VariableReport]] = []
    for ast_path in ast_paths:
        program = parse_ast(ast_path)
        var_report = extract_variables(program)
        programs.append((program, var_report))
        print(f"  Parsed {program.program_id}: "
              f"{len(program.paragraphs)} paragraphs, "
              f"{len(var_report.variables)} variables")

    # Use first program for artifact naming
    first_id = programs[0][0].program_id
    artifact_id = "carddemo-multi"
    group_id = "com.specter"
    first_class = _program_class_name(first_id)

    # pom.xml (only written once)
    pom_content = POM_XML.format(
        group_id=group_id,
        artifact_id=artifact_id,
        program_name="CardDemo-Multi",
        main_class=f"{package_name}.MultiProgramRunner",
    )
    (out / "pom.xml").write_text(pom_content, encoding="utf-8")

    # Runtime classes (shared, only written once)
    fmt_args = {
        "package_name": package_name,
        "program_id": first_id,
        "program_class_name": first_class,
    }
    _runtime_files = {
        "ProgramState.java": PROGRAM_STATE_JAVA,
        "GobackSignal.java": GOBACK_SIGNAL_JAVA,
        "CobolRuntime.java": COBOL_RUNTIME_JAVA,
        "Paragraph.java": PARAGRAPH_JAVA,
        "ParagraphRegistry.java": PARAGRAPH_REGISTRY_JAVA,
        "StubExecutor.java": STUB_EXECUTOR_JAVA,
        "DefaultStubExecutor.java": DEFAULT_STUB_EXECUTOR_JAVA,
        "JdbcStubExecutor.java": JDBC_STUB_EXECUTOR_JAVA,
        "SectionBase.java": SECTION_BASE_JAVA,
        "AppConfig.java": APP_CONFIG_JAVA,
        "Main.java": MAIN_JAVA,
    }
    for filename, template in _runtime_files.items():
        content = template.format(**fmt_args)
        (src_main / filename).write_text(content, encoding="utf-8")

    # Terminal infrastructure (shared, only written once)
    _terminal_infra = {
        "CicsReturnSignal.java": CICS_RETURN_SIGNAL_JAVA,
        "CicsScreen.java": TERMINAL_SCREEN_JAVA,
        "HeadlessScreen.java": HEADLESS_SCREEN_JAVA,
        "BmsScreen.java": BMS_SCREEN_JAVA,
        "TerminalStubExecutor.java": TERMINAL_STUB_EXECUTOR_JAVA,
        "XctlSignal.java": XCTL_SIGNAL_JAVA,
        "CicsProgram.java": CICS_PROGRAM_JAVA,
    }
    for filename, template in _terminal_infra.items():
        content = template.format(**fmt_args)
        (src_main / filename).write_text(content, encoding="utf-8")

    # Per-program generation
    import specter.code_generator as _cg

    first_program_id: str | None = None

    for program, var_report in programs:
        program_id = program.program_id
        prog_class_name = _program_class_name(program_id)

        if first_program_id is None:
            first_program_id = program_id

        # Update global paragraph order for this program
        _cg._PARAGRAPH_ORDER[:] = [p.name for p in program.paragraphs]

        # Detect 88-level mutual exclusion groups
        global _88_LEVEL_SIBLINGS
        _88_LEVEL_SIBLINGS = _detect_88_level_groups(program)

        # Shared code builder for this program
        shared_cb = _JavaCodeBuilder()

        # Collect PERFORM targets
        defined_paras = {p.name for p in program.paragraphs}
        referenced_paras: set[str] = set()

        def _collect_targets(stmt: Statement) -> None:
            target = stmt.attributes.get("target", "")
            if target:
                referenced_paras.add(target)
            for child in stmt.children:
                _collect_targets(child)

        for para in program.paragraphs:
            for stmt in para.statements:
                _collect_targets(stmt)

        # Group paragraphs by section
        sections: OrderedDict[str, list[tuple[str, list[Statement]]]] = (
            OrderedDict()
        )
        for para in program.paragraphs:
            key = _section_key(para.name)
            if key not in sections:
                sections[key] = []
            sections[key].append((para.name, para.statements))

        # Include stubs for missing paragraphs
        missing = referenced_paras - defined_paras
        for name in sorted(missing):
            key = _section_key(name)
            if key not in sections:
                sections[key] = []
            sections[key].append((name, []))

        # Generate section classes with program-specific prefix to avoid
        # class name collisions across programs.
        section_classes: list[str] = []
        for key in sections:
            sec_base_name = _section_class_name(key)
            # Prefix with program id to avoid collisions
            sec_class_name_prefixed = f"{sec_base_name}_{program_id}"
            sec_class_name, sec_src = _generate_section_class(
                key, sections[key], package_name, shared_cb,
            )
            # Rename the class in the generated source
            sec_src = sec_src.replace(
                f"class {sec_class_name} ",
                f"class {sec_class_name_prefixed} ",
            )
            sec_src = sec_src.replace(
                f"public {sec_class_name}(",
                f"public {sec_class_name_prefixed}(",
            )
            (src_main / f"{sec_class_name_prefixed}.java").write_text(
                sec_src, encoding="utf-8"
            )
            section_classes.append(sec_class_name_prefixed)

        # BMS screen layout with unique class name
        bms_info = _extract_bms_info(program)
        is_terminal = bms_info is not None
        screen_layout_class = f"ScreenLayout_{program_id}"

        if bms_info is not None:
            layout = _compute_screen_layout(bms_info)
            screen_layout_src = _generate_screen_layout_java(
                layout, package_name, prog_class_name,
                screen_layout_class_name=screen_layout_class,
            )
            (src_main / f"{screen_layout_class}.java").write_text(
                screen_layout_src, encoding="utf-8"
            )

        # Compute per-program literal constants for CicsProgram.initState()
        _lit_defaults_for_class = None
        if is_terminal:
            _lit_defaults_for_class = {
                "LIT-THISTRANID": program_id[:4],
                "LIT-THISPGM": program_id,
                "LIT-THISMAP": next(iter(bms_info), ""),
                "LIT-THISMAPSET": next(iter(bms_info), "")[:6]
                    if bms_info else "",
                "LIT-MENUPGM": "COMEN01C",
                "LIT-MENUTRANID": "COME",
                "CCDA-TITLE01": "Credit Card Demo Application",
                "CCDA-TITLE02": program_id + " - Account Update",
                "CCDA-MSG-THANK-YOU": "Thank you for using the application",
                "CCDA-MSG-INVALID-KEY": "Invalid key pressed",
            }

        # Program class (implements CicsProgram for terminal programs)
        prog_src = _generate_program_class(
            program, var_report, package_name,
            section_classes=section_classes,
            is_terminal=is_terminal,
            screen_layout_class=screen_layout_class,
            lit_defaults=_lit_defaults_for_class,
            level_88_map=shared_cb.level_88_map,
            file_status_map=shared_cb.file_status_map,
        )
        (src_main / f"{prog_class_name}.java").write_text(
            prog_src, encoding="utf-8"
        )

        print(f"  Generated {prog_class_name}: "
              f"{len(section_classes)} sections, "
              f"terminal={'yes' if is_terminal else 'no'}")

        # Per-program test class + test store resource
        if per_program_stores and program_id in per_program_stores:
            store_path = per_program_stores[program_id]
            resource_name = f"test_store_{program_id}.jsonl"
            test_src = _generate_test_class(
                program, package_name, resource_name=resource_name,
            )
            (src_test / f"{prog_class_name}Test.java").write_text(
                test_src, encoding="utf-8"
            )
            # Copy JSONL to test resources
            src_resources = out / "src" / "test" / "resources"
            src_resources.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.copy2(store_path, str(src_resources / resource_name))
            print(f"  Tests for {prog_class_name}: {resource_name}")

    # Generate MultiProgramRunner with Function<StubExecutor, CicsProgram>
    # factories so the runner can wire TerminalStubExecutor per program.
    runner_entries = []
    for program, var_report in programs:
        program_id = program.program_id
        prog_class_name = _program_class_name(program_id)
        runner_entries.append(
            f'        registry.put("{program_id}", '
            f"(stubs) -> new {prog_class_name}(stubs));"
        )

    # Set firstProgram
    runner_entries.insert(
        0,
        f'        firstProgram = "{first_program_id}";'
    )

    runner_src = MULTI_PROGRAM_RUNNER_JAVA.format(
        package_name=package_name,
        program_registry_entries="\n".join(runner_entries),
    )
    (src_main / "MultiProgramRunner.java").write_text(
        runner_src, encoding="utf-8"
    )

    # Also generate per-program TerminalMain for backwards compatibility
    for program, var_report in programs:
        program_id = program.program_id
        prog_class_name = _program_class_name(program_id)
        bms_info = _extract_bms_info(program)
        if bms_info is not None:
            prog_fmt = {
                "package_name": package_name,
                "program_id": program_id,
                "program_class_name": prog_class_name,
            }
            initial_lines = []
            initial_lines.append(
                '        state.put("WS-TRANID", "' + program_id[:4] + '");'
            )
            initial_lines.append(
                '        state.put("WS-PGMNAME", "' + program_id + '");'
            )
            _lit_defaults = {
                "LIT-THISTRANID": program_id[:4],
                "LIT-THISPGM": program_id,
                "LIT-THISMAP": next(iter(bms_info), ""),
                "LIT-THISMAPSET": next(iter(bms_info), "")[:6]
                    if bms_info else "",
                "LIT-MENUPGM": "COMEN01C",
                "LIT-MENUTRANID": "COME",
                "CCDA-TITLE01": "Credit Card Demo Application",
                "CCDA-TITLE02": program_id + " - Account Update",
                "CCDA-MSG-THANK-YOU": "Thank you for using the application",
                "CCDA-MSG-INVALID-KEY": "Invalid key pressed",
            }
            for var, val in _lit_defaults.items():
                initial_lines.append(
                    f'        state.put("{var}", "{val}");'
                )
            # Use program-specific ScreenLayout in TerminalMain
            screen_layout_ref = f"ScreenLayout_{program_id}"
            terminal_main_template = TERMINAL_MAIN_JAVA.replace(
                "ScreenLayout.FIELDS", f"{screen_layout_ref}.FIELDS"
            )
            terminal_main_src = terminal_main_template.format(
                **prog_fmt,
                initial_state_lines="\n".join(initial_lines),
            )
            terminal_main_file = f"TerminalMain_{program_id}.java"
            # Fix the class name in the source
            terminal_main_src = terminal_main_src.replace(
                "public class TerminalMain {",
                f"public class TerminalMain_{program_id} {{",
            )
            (src_main / terminal_main_file).write_text(
                terminal_main_src, encoding="utf-8"
            )

    return str(out.resolve())
