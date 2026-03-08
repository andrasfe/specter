"""Tests for the concolic coverage engine (specter.concolic)."""

from __future__ import annotations

import sys
import unittest
from unittest.mock import patch
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Helper: minimal VariableInfo / VariableReport for tests
# ---------------------------------------------------------------------------

@dataclass
class _VarInfo:
    name: str
    classification: str = "input"
    condition_literals: list = field(default_factory=list)
    read_count: int = 1
    write_count: int = 0
    first_access: str = "read"


@dataclass
class _VarReport:
    variables: dict = field(default_factory=dict)


def _make_report(var_defs: dict[str, dict]) -> _VarReport:
    """Build a minimal VariableReport from {name: {classification, condition_literals}}."""
    variables = {}
    for name, attrs in var_defs.items():
        variables[name] = _VarInfo(
            name=name,
            classification=attrs.get("classification", "input"),
            condition_literals=attrs.get("condition_literals", []),
        )
    return _VarReport(variables=variables)


# ---------------------------------------------------------------------------
# Test: graceful degradation when z3 is not installed
# ---------------------------------------------------------------------------

class TestGracefulDegradation(unittest.TestCase):
    """Concolic engine must not crash when z3-solver is absent."""

    def test_solve_returns_empty_without_z3(self):
        """solve_for_uncovered_branches returns [] when z3 import fails."""
        # Temporarily make z3 un-importable
        with patch.dict(sys.modules, {"z3": None}):
            # Force re-import check inside the function
            import importlib
            from specter import concolic
            importlib.reload(concolic)

            result = concolic.solve_for_uncovered_branches(
                branch_meta={1: {"condition": "WS-X = 42", "paragraph": "PARA-1", "type": "IF"}},
                covered_branches={1},
                var_report=_make_report({"WS-X": {"classification": "input", "condition_literals": [42]}}),
                observed_states=[{}],
            )
            self.assertEqual(result, [])

            # Restore module
            importlib.reload(concolic)


# ---------------------------------------------------------------------------
# Tests that require z3 — skip if not installed
# ---------------------------------------------------------------------------

try:
    import z3
    _HAS_Z3 = True
except ImportError:
    _HAS_Z3 = False


@unittest.skipUnless(_HAS_Z3, "z3-solver not installed")
class TestConditionToZ3(unittest.TestCase):
    """Unit tests for cobol_condition_to_z3."""

    def setUp(self):
        from specter.concolic import cobol_condition_to_z3, build_var_env
        self.to_z3 = cobol_condition_to_z3
        self.build_env = build_var_env

    def _make_env(self, *names, numeric=True):
        env = {}
        for name in names:
            if numeric:
                env[name] = z3.Int(name)
            else:
                env[name] = z3.String(name)
        return env

    def test_simple_equality(self):
        env = self._make_env("WS-X")
        expr = self.to_z3("WS-X = 42", env)
        s = z3.Solver()
        s.add(expr)
        self.assertEqual(s.check(), z3.sat)
        m = s.model()
        self.assertEqual(m.eval(env["WS-X"]).as_long(), 42)

    def test_inequality(self):
        env = self._make_env("WS-Y")
        expr = self.to_z3("WS-Y > 10", env)
        s = z3.Solver()
        s.add(expr)
        s.add(env["WS-Y"] < 20)
        self.assertEqual(s.check(), z3.sat)
        val = s.model().eval(env["WS-Y"]).as_long()
        self.assertGreater(val, 10)
        self.assertLess(val, 20)

    def test_less_than(self):
        env = self._make_env("WS-CNT")
        expr = self.to_z3("WS-CNT LESS THAN 5", env)
        s = z3.Solver()
        s.add(expr)
        self.assertEqual(s.check(), z3.sat)
        val = s.model().eval(env["WS-CNT"]).as_long()
        self.assertLess(val, 5)

    def test_multi_value_or(self):
        env = self._make_env("WS-CODE")
        expr = self.to_z3("WS-CODE = 10 OR 20 OR 30", env)
        s = z3.Solver()
        s.add(expr)
        self.assertEqual(s.check(), z3.sat)
        val = s.model().eval(env["WS-CODE"]).as_long()
        self.assertIn(val, [10, 20, 30])

    def test_not_equal(self):
        env = self._make_env("WS-FLAG")
        expr = self.to_z3("WS-FLAG NOT = 0", env)
        s = z3.Solver()
        s.add(expr)
        self.assertEqual(s.check(), z3.sat)
        val = s.model().eval(env["WS-FLAG"]).as_long()
        self.assertNotEqual(val, 0)

    def test_and_condition(self):
        env = self._make_env("WS-A", "WS-B")
        expr = self.to_z3("WS-A = 1 AND WS-B = 2", env)
        s = z3.Solver()
        s.add(expr)
        self.assertEqual(s.check(), z3.sat)
        m = s.model()
        self.assertEqual(m.eval(env["WS-A"]).as_long(), 1)
        self.assertEqual(m.eval(env["WS-B"]).as_long(), 2)

    def test_or_condition(self):
        env = self._make_env("WS-A")
        expr = self.to_z3("WS-A = 1 OR WS-A = 2", env)
        s = z3.Solver()
        s.add(expr)
        self.assertEqual(s.check(), z3.sat)
        val = s.model().eval(env["WS-A"]).as_long()
        self.assertIn(val, [1, 2])

    def test_not_condition(self):
        env = self._make_env("WS-X")
        expr = self.to_z3("NOT WS-X = 5", env)
        s = z3.Solver()
        s.add(expr)
        self.assertEqual(s.check(), z3.sat)
        val = s.model().eval(env["WS-X"]).as_long()
        self.assertNotEqual(val, 5)

    def test_is_numeric_approximation(self):
        env = self._make_env("WS-X")
        expr = self.to_z3("WS-X IS NUMERIC", env)
        # IS NUMERIC is approximated as True — should be satisfiable
        s = z3.Solver()
        s.add(expr)
        self.assertEqual(s.check(), z3.sat)

    def test_figurative_constants(self):
        env = self._make_env("WS-CODE")
        expr = self.to_z3("WS-CODE = ZEROS", env)
        s = z3.Solver()
        s.add(expr)
        self.assertEqual(s.check(), z3.sat)
        val = s.model().eval(env["WS-CODE"]).as_long()
        self.assertEqual(val, 0)

    def test_dfhresp(self):
        env = self._make_env("EIBRESP")
        expr = self.to_z3("EIBRESP = DFHRESP(NORMAL)", env)
        s = z3.Solver()
        s.add(expr)
        self.assertEqual(s.check(), z3.sat)
        val = s.model().eval(env["EIBRESP"]).as_long()
        self.assertEqual(val, 0)

    def test_string_equality(self):
        env = self._make_env("WS-FLAG", numeric=False)
        expr = self.to_z3("WS-FLAG = 'Y'", env)
        s = z3.Solver()
        s.add(expr)
        self.assertEqual(s.check(), z3.sat)
        val = s.model().eval(env["WS-FLAG"]).as_string()
        self.assertEqual(val, "Y")

    def test_empty_condition(self):
        env = {}
        expr = self.to_z3("", env)
        self.assertTrue(z3.is_true(z3.simplify(expr)))

    def test_greater_equal(self):
        env = self._make_env("WS-AMT")
        expr = self.to_z3("WS-AMT >= 100", env)
        s = z3.Solver()
        s.add(expr)
        s.add(env["WS-AMT"] <= 200)
        self.assertEqual(s.check(), z3.sat)
        val = s.model().eval(env["WS-AMT"]).as_long()
        self.assertGreaterEqual(val, 100)
        self.assertLessEqual(val, 200)


@unittest.skipUnless(_HAS_Z3, "z3-solver not installed")
class TestSolveForBranch(unittest.TestCase):
    """Tests for solve_for_branch."""

    def test_negation_finds_solution(self):
        from specter.concolic import solve_for_branch, build_var_env
        branch_meta = {
            1: {"condition": "WS-X = 42", "paragraph": "PARA-A", "type": "IF"},
        }
        report = _make_report({"WS-X": {"classification": "input", "condition_literals": [42]}})
        env = build_var_env(report)
        sol = solve_for_branch(1, branch_meta, env, negate=True)
        self.assertIsNotNone(sol)
        self.assertIn("WS-X", sol.assignments)
        self.assertNotEqual(sol.assignments["WS-X"], 42)

    def test_positive_finds_solution(self):
        from specter.concolic import solve_for_branch, build_var_env
        branch_meta = {
            1: {"condition": "WS-X = 12345678", "paragraph": "PARA-A", "type": "IF"},
        }
        report = _make_report({"WS-X": {"classification": "input", "condition_literals": [12345678]}})
        env = build_var_env(report)
        sol = solve_for_branch(1, branch_meta, env, negate=False)
        self.assertIsNotNone(sol)
        self.assertEqual(sol.assignments["WS-X"], 12345678)

    def test_returns_none_on_missing_meta(self):
        from specter.concolic import solve_for_branch
        sol = solve_for_branch(99, {}, {}, negate=True)
        self.assertIsNone(sol)

    def test_returns_none_on_empty_condition(self):
        from specter.concolic import solve_for_branch
        branch_meta = {1: {"condition": "", "paragraph": "P", "type": "IF"}}
        sol = solve_for_branch(1, branch_meta, {}, negate=True)
        self.assertIsNone(sol)

    def test_evaluate_branch(self):
        from specter.concolic import solve_for_branch, build_var_env
        branch_meta = {
            1: {"condition": "42", "paragraph": "PARA-A", "type": "EVALUATE", "subject": "WS-CODE"},
        }
        report = _make_report({"WS-CODE": {"classification": "input", "condition_literals": [42]}})
        env = build_var_env(report)
        sol = solve_for_branch(1, branch_meta, env, negate=False)
        self.assertIsNotNone(sol)
        self.assertEqual(sol.assignments["WS-CODE"], 42)


@unittest.skipUnless(_HAS_Z3, "z3-solver not installed")
class TestSolveForUncoveredBranches(unittest.TestCase):
    """Tests for solve_for_uncovered_branches."""

    def test_finds_solutions_for_half_covered(self):
        from specter.concolic import solve_for_uncovered_branches
        branch_meta = {
            1: {"condition": "WS-X = 42", "paragraph": "PARA-A", "type": "IF"},
        }
        report = _make_report({"WS-X": {"classification": "input", "condition_literals": [42]}})
        # Branch 1 (positive) is covered; -1 (negative) is not
        solutions = solve_for_uncovered_branches(
            branch_meta,
            covered_branches={1},
            var_report=report,
            observed_states=[{"WS-X": 42}],
        )
        self.assertGreater(len(solutions), 0)
        sol = solutions[0]
        self.assertIn("WS-X", sol.assignments)
        self.assertNotEqual(sol.assignments["WS-X"], 42)

    def test_empty_meta_returns_empty(self):
        from specter.concolic import solve_for_uncovered_branches
        report = _make_report({})
        solutions = solve_for_uncovered_branches(
            branch_meta={},
            covered_branches=set(),
            var_report=report,
            observed_states=[{}],
        )
        self.assertEqual(solutions, [])

    def test_all_covered_returns_empty(self):
        from specter.concolic import solve_for_uncovered_branches
        branch_meta = {
            1: {"condition": "WS-X = 1", "paragraph": "P", "type": "IF"},
        }
        report = _make_report({"WS-X": {"classification": "input", "condition_literals": [1]}})
        solutions = solve_for_uncovered_branches(
            branch_meta,
            covered_branches={1, -1},
            var_report=report,
            observed_states=[{}],
        )
        self.assertEqual(solutions, [])


@unittest.skipUnless(_HAS_Z3, "z3-solver not installed")
class TestBuildVarEnv(unittest.TestCase):

    def test_input_var_is_free(self):
        from specter.concolic import build_var_env
        report = _make_report({"WS-X": {"classification": "input", "condition_literals": [1, 2]}})
        env = build_var_env(report)
        self.assertIn("WS-X", env)
        # Should be a free Z3 Int (not a constant)
        self.assertFalse(z3.is_int_value(env["WS-X"]))

    def test_internal_var_is_fixed(self):
        from specter.concolic import build_var_env
        report = _make_report({"WS-INTERNAL": {"classification": "internal", "condition_literals": [99]}})
        env = build_var_env(report, observed_state={"WS-INTERNAL": 99})
        self.assertIn("WS-INTERNAL", env)
        self.assertTrue(z3.is_int_value(env["WS-INTERNAL"]))

    def test_flag_is_numeric(self):
        from specter.concolic import build_var_env
        report = _make_report({"WS-FLAG": {"classification": "flag"}})
        env = build_var_env(report)
        self.assertIn("WS-FLAG", env)
        # Flag → Int (0/1)
        self.assertTrue(z3.is_int(env["WS-FLAG"]))

    def test_string_var(self):
        from specter.concolic import build_var_env
        report = _make_report({"WS-NAME": {"classification": "input", "condition_literals": ["ABC"]}})
        env = build_var_env(report)
        self.assertIn("WS-NAME", env)
        self.assertTrue(z3.is_string(env["WS-NAME"]))


@unittest.skipUnless(_HAS_Z3, "z3-solver not installed")
class TestEndToEnd(unittest.TestCase):
    """End-to-end: generate code with IF WS-X = 42, then use concolic to cover both branches."""

    def test_concolic_covers_both_branches(self):
        from specter.ast_parser import parse_ast
        from specter.code_generator import generate_code
        from specter.variable_extractor import extract_variables
        from specter.concolic import solve_for_uncovered_branches

        ast_dict = {
            "programId": "TEST-CONCOLIC",
            "paragraphs": [
                {
                    "name": "MAIN-PARA",
                    "lineStart": 1,
                    "lineEnd": 10,
                    "statements": [
                        {
                            "type": "IF",
                            "text": "IF WS-MAGIC = 12345678",
                            "lineNumber": 2,
                            "attributes": {"condition": "WS-MAGIC = 12345678"},
                            "children": [
                                {
                                    "type": "DISPLAY",
                                    "text": "DISPLAY 'MAGIC FOUND'",
                                    "lineNumber": 3,
                                    "attributes": {"value": "'MAGIC FOUND'"},
                                    "children": [],
                                },
                                {
                                    "type": "ELSE",
                                    "text": "ELSE",
                                    "lineNumber": 5,
                                    "attributes": {},
                                    "children": [
                                        {
                                            "type": "DISPLAY",
                                            "text": "DISPLAY 'NOT MAGIC'",
                                            "lineNumber": 6,
                                            "attributes": {"value": "'NOT MAGIC'"},
                                            "children": [],
                                        }
                                    ],
                                },
                            ],
                        },
                        {
                            "type": "GOBACK",
                            "text": "GOBACK",
                            "lineNumber": 8,
                            "attributes": {},
                            "children": [],
                        },
                    ],
                }
            ],
        }

        program = parse_ast(ast_dict)
        var_report = extract_variables(program)
        code = generate_code(program, var_report, instrument=True)

        # Verify code compiles
        compiled = compile(code, "<test>", "exec")
        ns = {}
        exec(compiled, ns)
        module_run = ns["run"]
        branch_meta = ns["_BRANCH_META"]

        # Verify branch_meta was emitted
        self.assertIn(1, branch_meta)
        self.assertEqual(branch_meta[1]["type"], "IF")
        self.assertEqual(branch_meta[1]["condition"], "WS-MAGIC = 12345678")

        # Run with random value — covers the else branch (-1)
        result1 = module_run({"WS-MAGIC": 0})
        branches1 = result1.get("_branches", set())
        self.assertIn(-1, branches1)

        # Now use concolic to find the magic value
        solutions = solve_for_uncovered_branches(
            branch_meta,
            covered_branches=branches1,
            var_report=var_report,
            observed_states=[{"WS-MAGIC": 0}],
        )

        # Should find WS-MAGIC = 12345678
        self.assertGreater(len(solutions), 0)
        found_magic = False
        for sol in solutions:
            if sol.assignments.get("WS-MAGIC") == 12345678:
                found_magic = True
                break
        self.assertTrue(found_magic, f"Expected WS-MAGIC=12345678, got: {solutions}")

        # Run with the solved value — covers branch 1
        result2 = module_run({"WS-MAGIC": 12345678})
        branches2 = result2.get("_branches", set())
        self.assertIn(1, branches2)

        # Together, both branches are covered
        all_branches = branches1 | branches2
        self.assertIn(1, all_branches)
        self.assertIn(-1, all_branches)


if __name__ == "__main__":
    unittest.main()
