"""Tests for coverage-guided fuzzing."""

import random
import tempfile
import unittest
from pathlib import Path

from specter.ast_parser import parse_ast
from specter.code_generator import generate_code
from specter.monte_carlo import (
    MonteCarloReport,
    _CorpusEntry,
    _FuzzerState,
    _add_to_corpus,
    _fingerprint_state,
    _generate_random_value,
    _is_recursion_prone,
    _mutate_state,
    _select_seed,
    _should_add_to_corpus,
    _update_energy,
    run_monte_carlo,
)
from specter.variable_extractor import VariableInfo, VariableReport, extract_variables


def _make_program(paragraphs):
    return parse_ast({
        "program_id": "TEST",
        "paragraphs": paragraphs,
    })


class TestCorpusManagement(unittest.TestCase):

    def test_should_add_new_paragraphs(self):
        fuzzer = _FuzzerState()
        fuzzer.global_coverage = {"A", "B"}
        self.assertTrue(_should_add_to_corpus(fuzzer, frozenset({"A", "C"}), frozenset()))

    def test_should_add_new_edges(self):
        fuzzer = _FuzzerState()
        fuzzer.global_coverage = {"A", "B"}
        fuzzer.global_edges = {("A", "B")}
        self.assertTrue(_should_add_to_corpus(
            fuzzer, frozenset({"A", "B"}), frozenset({("B", "A")})))

    def test_should_not_add_subset(self):
        fuzzer = _FuzzerState()
        fuzzer.global_coverage = {"A", "B", "C"}
        fuzzer.global_edges = {("A", "B"), ("B", "C")}
        self.assertFalse(_should_add_to_corpus(
            fuzzer, frozenset({"A", "B"}), frozenset({("A", "B")})))

    def test_add_to_corpus_updates_global(self):
        fuzzer = _FuzzerState()
        entry = _CorpusEntry(
            input_state={"X": "1"},
            coverage=frozenset({"A", "B"}),
            edges=frozenset({("A", "B")}),
            added_at=5,
        )
        _add_to_corpus(fuzzer, entry)
        self.assertEqual(fuzzer.global_coverage, {"A", "B"})
        self.assertEqual(fuzzer.global_edges, {("A", "B")})
        self.assertEqual(fuzzer.stale_counter, 0)
        self.assertEqual(len(fuzzer.corpus), 1)
        self.assertEqual(fuzzer.coverage_timeline, [(5, 2)])

    def test_eviction_on_overflow(self):
        fuzzer = _FuzzerState()
        # Fill corpus to max
        from specter.monte_carlo import _MAX_CORPUS
        for i in range(_MAX_CORPUS):
            entry = _CorpusEntry(
                input_state={},
                coverage=frozenset({f"P{i}"}),
                edges=frozenset(),
                energy=1.0,
                added_at=i,
            )
            fuzzer.corpus.append(entry)
            fuzzer.global_coverage.add(f"P{i}")

        # Add one more — should trigger eviction
        new_entry = _CorpusEntry(
            input_state={},
            coverage=frozenset({"NEW"}),
            edges=frozenset(),
            energy=10.0,
            added_at=_MAX_CORPUS,
        )
        _add_to_corpus(fuzzer, new_entry)
        self.assertEqual(len(fuzzer.corpus), _MAX_CORPUS)
        self.assertIn("NEW", fuzzer.global_coverage)


class TestSeedSelection(unittest.TestCase):

    def test_select_by_energy(self):
        fuzzer = _FuzzerState()
        low = _CorpusEntry(input_state={"X": "low"}, coverage=frozenset(),
                           edges=frozenset(), energy=0.01)
        high = _CorpusEntry(input_state={"X": "high"}, coverage=frozenset(),
                            edges=frozenset(), energy=100.0)
        fuzzer.corpus = [low, high]

        rng = random.Random(42)
        picks = [_select_seed(fuzzer, rng).input_state["X"] for _ in range(100)]
        self.assertGreater(picks.count("high"), picks.count("low"))

    def test_update_energy_frontier_bonus(self):
        fuzzer = _FuzzerState()
        fuzzer.call_graph = {"A": {"B"}}  # A calls B
        entry = _CorpusEntry(
            input_state={}, coverage=frozenset({"A"}),
            edges=frozenset({("A", "B")}), added_at=10,
        )
        fuzzer.corpus = [entry]
        fuzzer.global_coverage = {"A", "B"}

        # B is covered, but A is a caller (branch point) so it gets frontier bonus
        _update_energy(fuzzer, ["A", "B", "C"])
        self.assertGreater(entry.energy, 1.0)

    def test_yield_penalty(self):
        fuzzer = _FuzzerState()
        entry = _CorpusEntry(
            input_state={}, coverage=frozenset({"A"}),
            edges=frozenset(), mutation_count=20,
            children_produced=0, added_at=1,
        )
        fuzzer.corpus = [entry]
        fuzzer.global_coverage = {"A"}
        _update_energy(fuzzer, ["A"])
        self.assertLess(entry.energy, 1.0)


class TestRecursionFingerprinting(unittest.TestCase):

    def test_fingerprint_status_flag_only(self):
        report = VariableReport()
        report.variables = {
            "WS-STATUS": VariableInfo(name="WS-STATUS", classification="status"),
            "WS-FLAG": VariableInfo(name="WS-FLAG", classification="flag"),
            "WS-DATA": VariableInfo(name="WS-DATA", classification="input"),
        }
        state = {"WS-STATUS": "00", "WS-FLAG": True, "WS-DATA": "hello"}
        fp = _fingerprint_state(state, report)
        self.assertIn(("WS-STATUS", "00"), fp)
        self.assertIn(("WS-FLAG", True), fp)
        self.assertNotIn(("WS-DATA", "hello"), fp)

    def test_recursion_prone_detection(self):
        report = VariableReport()
        report.variables = {
            "WS-STATUS": VariableInfo(name="WS-STATUS", classification="status"),
        }
        fuzzer = _FuzzerState()
        bad_fp = frozenset({("WS-STATUS", "99")})
        fuzzer.recursion_fingerprints = {bad_fp}

        self.assertTrue(_is_recursion_prone(fuzzer, {"WS-STATUS": "99"}, report))
        self.assertFalse(_is_recursion_prone(fuzzer, {"WS-STATUS": "00"}, report))


class TestMutation(unittest.TestCase):

    def _make_var_report(self):
        report = VariableReport()
        report.variables = {
            "X": VariableInfo(name="X", classification="input",
                              condition_literals=["A", "B", "C"]),
            "Y": VariableInfo(name="Y", classification="flag"),
            "Z": VariableInfo(name="Z", classification="status"),
        }
        return report

    def test_mutation_changes_state(self):
        var_report = self._make_var_report()
        parent = {"X": "A", "Y": True, "Z": "00"}
        fuzzer = _FuzzerState()
        rng = random.Random(42)

        # Run many mutations — at least some should differ
        changed = False
        for _ in range(50):
            mutated = _mutate_state(parent, var_report, rng, fuzzer)
            if mutated != parent:
                changed = True
                break
        self.assertTrue(changed)

    def test_generate_random_value_uses_literals(self):
        info = VariableInfo(name="X", classification="input",
                            condition_literals=["MAGIC"])
        rng = random.Random(42)
        values = [_generate_random_value("X", info, rng) for _ in range(100)]
        self.assertIn("MAGIC", values)


class TestGuidedIntegration(unittest.TestCase):
    """Integration tests using actual generated code."""

    def _branching_program(self):
        """Program with IF/ELSE: WS-MODE='Y' -> BRANCH-A, else -> BRANCH-B."""
        return _make_program([
            {
                "name": "MAIN-PARA",
                "line_start": 1, "line_end": 10,
                "statements": [{
                    "type": "IF", "text": "IF WS-MODE = 'Y'",
                    "line_start": 1, "line_end": 5,
                    "attributes": {"condition": "WS-MODE = 'Y'"},
                    "children": [
                        {"type": "PERFORM", "text": "PERFORM BRANCH-A",
                         "line_start": 2, "line_end": 2,
                         "attributes": {"target": "BRANCH-A"},
                         "children": []},
                        {"type": "ELSE", "text": "ELSE",
                         "line_start": 3, "line_end": 4,
                         "attributes": {},
                         "children": [
                             {"type": "PERFORM", "text": "PERFORM BRANCH-B",
                              "line_start": 4, "line_end": 4,
                              "attributes": {"target": "BRANCH-B"},
                              "children": []},
                         ]},
                    ],
                }],
            },
            {
                "name": "BRANCH-A",
                "line_start": 11, "line_end": 15,
                "statements": [
                    {"type": "MOVE", "text": "MOVE 'A' TO WS-RESULT",
                     "line_start": 12, "line_end": 12,
                     "attributes": {"source": "'A'", "targets": "WS-RESULT"},
                     "children": []},
                ],
            },
            {
                "name": "BRANCH-B",
                "line_start": 16, "line_end": 20,
                "statements": [
                    {"type": "MOVE", "text": "MOVE 'B' TO WS-RESULT",
                     "line_start": 17, "line_end": 17,
                     "attributes": {"source": "'B'", "targets": "WS-RESULT"},
                     "children": []},
                ],
            },
        ])

    def _deep_branching_program(self):
        """Program requiring WS-CODE='A' AND WS-TYPE='B' to reach DEEP-PARA."""
        return _make_program([
            {
                "name": "MAIN-PARA",
                "line_start": 1, "line_end": 10,
                "statements": [{
                    "type": "IF", "text": "IF WS-CODE = 'A'",
                    "line_start": 1, "line_end": 5,
                    "attributes": {"condition": "WS-CODE = 'A'"},
                    "children": [
                        {"type": "PERFORM", "text": "PERFORM STEP-1",
                         "line_start": 2, "line_end": 2,
                         "attributes": {"target": "STEP-1"},
                         "children": []},
                        {"type": "ELSE", "text": "ELSE",
                         "line_start": 3, "line_end": 4,
                         "attributes": {},
                         "children": [
                             {"type": "PERFORM", "text": "PERFORM FALLBACK",
                              "line_start": 4, "line_end": 4,
                              "attributes": {"target": "FALLBACK"},
                              "children": []},
                         ]},
                    ],
                }],
            },
            {
                "name": "STEP-1",
                "line_start": 11, "line_end": 20,
                "statements": [{
                    "type": "IF", "text": "IF WS-TYPE = 'B'",
                    "line_start": 11, "line_end": 15,
                    "attributes": {"condition": "WS-TYPE = 'B'"},
                    "children": [
                        {"type": "PERFORM", "text": "PERFORM DEEP-PARA",
                         "line_start": 12, "line_end": 12,
                         "attributes": {"target": "DEEP-PARA"},
                         "children": []},
                        {"type": "ELSE", "text": "ELSE",
                         "line_start": 13, "line_end": 14,
                         "attributes": {},
                         "children": [
                             {"type": "MOVE", "text": "MOVE 'SHALLOW' TO WS-RESULT",
                              "line_start": 14, "line_end": 14,
                              "attributes": {"source": "'SHALLOW'", "targets": "WS-RESULT"},
                              "children": []},
                         ]},
                    ],
                }],
            },
            {
                "name": "DEEP-PARA",
                "line_start": 21, "line_end": 25,
                "statements": [
                    {"type": "MOVE", "text": "MOVE 'DEEP' TO WS-RESULT",
                     "line_start": 22, "line_end": 22,
                     "attributes": {"source": "'DEEP'", "targets": "WS-RESULT"},
                     "children": []},
                ],
            },
            {
                "name": "FALLBACK",
                "line_start": 26, "line_end": 30,
                "statements": [
                    {"type": "MOVE", "text": "MOVE 'FALL' TO WS-RESULT",
                     "line_start": 27, "line_end": 27,
                     "attributes": {"source": "'FALL'", "targets": "WS-RESULT"},
                     "children": []},
                ],
            },
        ])

    def _generate_and_write(self, program, var_report=None):
        """Generate instrumented code and write to a temp file."""
        code = generate_code(program, var_report=var_report, instrument=True)
        tmp = tempfile.NamedTemporaryFile(suffix=".py", delete=False, mode="w")
        tmp.write(code)
        tmp.close()
        return Path(tmp.name)

    def test_guided_finds_both_branches(self):
        prog = self._branching_program()
        var_report = extract_variables(prog)
        path = self._generate_and_write(prog, var_report)
        try:
            all_paras = [p.name for p in prog.paragraphs]
            report = run_monte_carlo(
                path, n_iterations=200, seed=42,
                var_report=var_report, instrument=True,
                all_paragraphs=all_paras, guided=True,
            )
            self.assertIsNotNone(report.analysis_report)
            hit = set(report.analysis_report.paragraph_hit_counts.keys())
            self.assertIn("BRANCH-A", hit)
            self.assertIn("BRANCH-B", hit)
            self.assertIn("MAIN-PARA", hit)
        finally:
            path.unlink(missing_ok=True)

    def test_guided_finds_deep_path(self):
        prog = self._deep_branching_program()
        var_report = extract_variables(prog)
        path = self._generate_and_write(prog, var_report)
        try:
            all_paras = [p.name for p in prog.paragraphs]
            report = run_monte_carlo(
                path, n_iterations=500, seed=42,
                var_report=var_report, instrument=True,
                all_paragraphs=all_paras, guided=True,
            )
            hit = set(report.analysis_report.paragraph_hit_counts.keys())
            self.assertIn("DEEP-PARA", hit)
            self.assertIn("FALLBACK", hit)
        finally:
            path.unlink(missing_ok=True)

    def test_guided_better_than_random(self):
        """Guided fuzzing should achieve >= random coverage on branching program."""
        prog = self._deep_branching_program()
        var_report = extract_variables(prog)
        path = self._generate_and_write(prog, var_report)
        try:
            all_paras = [p.name for p in prog.paragraphs]

            guided_report = run_monte_carlo(
                path, n_iterations=300, seed=42,
                var_report=var_report, instrument=True,
                all_paragraphs=all_paras, guided=True,
            )
            random_report = run_monte_carlo(
                path, n_iterations=300, seed=42,
                var_report=var_report, instrument=True,
                all_paragraphs=all_paras, guided=False,
            )

            guided_coverage = len(guided_report.analysis_report.paragraph_hit_counts)
            random_coverage = len(random_report.analysis_report.paragraph_hit_counts)
            self.assertGreaterEqual(guided_coverage, random_coverage)
        finally:
            path.unlink(missing_ok=True)

    def test_guided_no_var_report(self):
        """Guided mode should work even without var_report."""
        prog = _make_program([{
            "name": "MAIN-PARA",
            "line_start": 1, "line_end": 5,
            "statements": [
                {"type": "MOVE", "text": "MOVE 'A' TO X",
                 "line_start": 1, "line_end": 1,
                 "attributes": {"source": "'A'", "targets": "X"},
                 "children": []},
            ],
        }])
        path = self._generate_and_write(prog)
        try:
            report = run_monte_carlo(
                path, n_iterations=50, seed=42,
                var_report=None, instrument=True,
                all_paragraphs=["MAIN-PARA"], guided=True,
            )
            self.assertGreater(report.n_successful, 0)
        finally:
            path.unlink(missing_ok=True)

    def test_guided_report_has_analysis(self):
        """Guided mode always produces an analysis report."""
        prog = self._branching_program()
        var_report = extract_variables(prog)
        path = self._generate_and_write(prog, var_report)
        try:
            all_paras = [p.name for p in prog.paragraphs]
            report = run_monte_carlo(
                path, n_iterations=100, seed=42,
                var_report=var_report, instrument=True,
                all_paragraphs=all_paras, guided=True,
            )
            self.assertIsNotNone(report.analysis_report)
            # Summary should be valid
            text = report.analysis_report.summary()
            self.assertIn("Dynamic Analysis", text)
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
