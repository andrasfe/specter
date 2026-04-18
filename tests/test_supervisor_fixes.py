"""Tests for the three supervisor-channel / compile-fix bugs surfaced by the
end-to-end COTRN02C demo.

Each test is scoped to a single behavior change so a failure points at the
specific regression.
"""

from __future__ import annotations

import pytest

from specter.incremental_mock import (
    _count_actionable_errors,
    _is_deferred_to_later_phase,
    _normalize_phase_token,
)
from specter.supervisor_channel import SupervisorAbort, SupervisorRestart


# -------------------------- Fix #3: abort is terminal ----------------------


def test_supervisor_abort_is_not_exception() -> None:
    """SupervisorAbort must bypass `except Exception:` and `except RuntimeError:`.

    The coverage orchestrator's compile fallback wraps pipeline work in a
    broad `except RuntimeError:` and silently retries — that swallowed the
    original `RuntimeError("Supervisor aborted run: ...")` in the demo.
    Inheriting from BaseException is what fixes it.
    """
    assert issubclass(SupervisorAbort, BaseException)
    assert issubclass(SupervisorRestart, BaseException)
    assert not issubclass(SupervisorAbort, Exception)
    assert not issubclass(SupervisorRestart, Exception)


def test_supervisor_abort_not_caught_by_except_exception() -> None:
    caught_as_exception = False
    caught_as_base = False
    try:
        try:
            raise SupervisorAbort("teacher aborted")
        except Exception:  # noqa: BLE001 -- exercising the bug we fixed
            caught_as_exception = True
    except BaseException:  # noqa: BLE001
        caught_as_base = True
    assert caught_as_exception is False
    assert caught_as_base is True


def test_supervisor_abort_not_caught_by_except_runtime_error() -> None:
    caught_as_runtime = False
    caught_as_base = False
    try:
        try:
            raise SupervisorAbort("teacher aborted")
        except RuntimeError:
            caught_as_runtime = True
    except BaseException:  # noqa: BLE001
        caught_as_base = True
    assert caught_as_runtime is False
    assert caught_as_base is True


# ------------------- Fix #1 + #4: defer phase-3 class errors ----------------


EXEC_CICS_SRC = [
    "           MOVE ZEROS        TO CDEMO-PGM-CONTEXT\n",
    "           EXEC CICS\n",
    "               XCTL PROGRAM(CDEMO-TO-PROGRAM)\n",
    "               COMMAREA(CARDDEMO-COMMAREA)\n",
    "           END-EXEC.\n",
]


def test_defer_returns_true_for_exec_reserved_word_in_phase1() -> None:
    # Phase copy_resolution must not try to fix this; Phase 3 handles it.
    assert _is_deferred_to_later_phase(
        2, "'EXEC' is a reserved word, but isn't supported",
        EXEC_CICS_SRC, "copy_resolution",
    )


def test_defer_returns_true_for_unexpected_program_in_phase1() -> None:
    assert _is_deferred_to_later_phase(
        3, "syntax error, unexpected PROGRAM",
        EXEC_CICS_SRC, "copy_resolution",
    )


def test_defer_returns_true_contextually_near_exec_header() -> None:
    """Error message itself doesn't mention EXEC, but the line is inside
    an EXEC block. The contextual window should catch it."""
    assert _is_deferred_to_later_phase(
        4,
        "syntax error, unexpected '('",
        EXEC_CICS_SRC,
        "copy_resolution",
    )


def test_defer_returns_false_after_exec_replacement_phase() -> None:
    # Phase 3 onward, same error should NOT be deferred (it's now actionable).
    assert not _is_deferred_to_later_phase(
        2, "'EXEC' is a reserved word, but isn't supported",
        EXEC_CICS_SRC, "exec_replacement",
    )


def test_defer_returns_false_for_unrelated_errors() -> None:
    plain_src = [
        "           MOVE 1 TO WS-FOO\n",
        "           IF WS-FOO = 1\n",
        "               DISPLAY 'hi'\n",
        "           END-IF.\n",
    ]
    assert not _is_deferred_to_later_phase(
        2, "'WS-FOO' is not defined",
        plain_src, "copy_resolution",
    )


def test_normalize_phase_strips_transformed_suffix() -> None:
    # The phase gate uses checkpoint_name as its phase token, and those
    # carry suffixes like _transformed. The deferral lookup must still
    # resolve to the canonical token.
    assert _normalize_phase_token("copy_resolution_transformed") == "copy_resolution"
    assert _normalize_phase_token("mock_infrastructure_transformed") == "mock_infrastructure"
    assert _normalize_phase_token("exec_replacement") == "exec_replacement"
    assert _normalize_phase_token(None) == ""


def test_count_actionable_ignores_deferred(tmp_path) -> None:
    """_count_actionable_errors must drop deferred errors from its tally."""
    src = tmp_path / "prog.cbl"
    src.write_text("".join([
        "       IDENTIFICATION DIVISION.\n",
        "       PROGRAM-ID. TEST.\n",
        "       PROCEDURE DIVISION.\n",
        "       MAIN.\n",
        "           EXEC CICS\n",
        "               XCTL PROGRAM(X)\n",
        "           END-EXEC.\n",
        "           STOP RUN.\n",
    ]))

    # The actual cobc compile isn't needed for this test; patch the
    # helpers to simulate a realistic error list.
    import specter.incremental_mock as im

    def fake_syntax_check(_path, _cbks):
        # Simulate cobc returning two EXEC-class errors.
        return 1, "dummy stderr"

    def fake_parse_errors(_stderr, _name):
        return [
            (5, "'EXEC' is a reserved word, but isn't supported"),
            (6, "syntax error, unexpected PROGRAM"),
        ]

    orig_check = im._cobc_syntax_check
    orig_parse = im._parse_errors
    im._cobc_syntax_check = fake_syntax_check
    im._parse_errors = fake_parse_errors
    try:
        # In copy_resolution, both errors are deferred — count is 0.
        assert _count_actionable_errors(src, None, "copy_resolution") == 0
        # In exec_replacement, nothing is deferred — count is 2.
        assert _count_actionable_errors(src, None, "exec_replacement") == 2
        # Normalization works for suffixed checkpoint tokens too.
        assert _count_actionable_errors(src, None, "copy_resolution_transformed") == 0
    finally:
        im._cobc_syntax_check = orig_check
        im._parse_errors = orig_parse


# ------------------- Fix #2: teacher patches at parity ---------------------


def test_supervisor_channel_patch_verdict_has_fix_dict() -> None:
    """Smoke test that Resolution objects carry fixes in the expected
    form — the teacher-patch acceptance path assumes dict[int, str]."""
    from specter.supervisor_channel import _parse_resolution

    parsed = _parse_resolution({
        "id": "abc",
        "verdict": "patch",
        "fix": {"997": "      *     EXEC CICS\n", "1000": "           CONTINUE.\n"},
        "notes": "teacher fix",
    })
    assert parsed is not None
    assert parsed.verdict == "patch"
    # Keys must be ints so they index into src_lines correctly.
    assert set(parsed.fix.keys()) == {997, 1000}
    assert all(isinstance(v, str) for v in parsed.fix.values())
