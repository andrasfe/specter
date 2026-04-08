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
    _generate_all_success_state,
    _generate_all_success_stubs,
    _generate_random_state,
    _generate_directed_input,
    _generate_random_value,
    _generate_stub_outcomes,
    _is_recursion_prone,
    _mutate_state,
    _pick_target,
    _select_seed,
    _should_add_to_corpus,
    _update_energy,
    run_monte_carlo,
)
from specter.variable_domain import VariableDomain
from specter.static_analysis import (
    GatingCondition,
    PathConstraints,
    build_static_call_graph,
    compute_path_constraints,
    extract_gating_conditions,
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
            mutated, _ = _mutate_state(parent, var_report, rng, fuzzer)
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

    def test_generate_random_state_uses_jit_for_input_fields(self):
        class StubJITInference:
            def generate_value(self, var_name, domain, strategy, rng, **kwargs):
                return "CA"

            def infer_profile(self, var_name, domain, **kwargs):
                return None

        report = VariableReport()
        report.variables = {
            "WS-STATE": VariableInfo(name="WS-STATE", classification="input"),
        }
        rng = random.Random(42)
        state = _generate_random_state(
            report,
            rng,
            domains={
                "WS-STATE": VariableDomain(
                    name="WS-STATE",
                    classification="input",
                    data_type="alpha",
                    max_length=2,
                ),
            },
            jit_inference=StubJITInference(),
            semantic_profiles={},
        )
        self.assertEqual(state["WS-STATE"], "CA")


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


class TestStubFlipMutation(unittest.TestCase):

    def test_stub_flip_changes_outcomes(self):
        var_report = VariableReport()
        var_report.variables = {
            "X": VariableInfo(name="X", classification="input"),
            "SQLCODE": VariableInfo(name="SQLCODE", classification="status",
                                    condition_literals=[0, -803, 100]),
        }
        stub_mapping = {"SQL": ["SQLCODE"]}
        parent = {"X": "A", "SQLCODE": 0}
        parent_stub = {"SQL": [("SQLCODE", 0)]}
        fuzzer = _FuzzerState()
        rng = random.Random(42)

        # Run many mutations — at least some should flip stubs
        flipped = False
        for _ in range(100):
            _, new_stubs = _mutate_state(
                parent, var_report, rng, fuzzer,
                stub_mapping=stub_mapping,
                parent_stub_outcomes=parent_stub,
            )
            if new_stubs and new_stubs != parent_stub:
                flipped = True
                break
        self.assertTrue(flipped)


class TestDirectedFuzzing(unittest.TestCase):

    def test_pick_target_weighted_by_path_length(self):
        rng = random.Random(42)
        uncovered = {"SHORT", "LONG"}
        # SHORT has path len 2, LONG has path len 5
        path_constraints = {
            "SHORT": PathConstraints(target="SHORT", path=["A", "SHORT"], constraints=[]),
            "LONG": PathConstraints(target="LONG", path=["A", "B", "C", "D", "LONG"], constraints=[]),
        }
        picks = [_pick_target(uncovered, path_constraints, rng) for _ in range(200)]
        # SHORT should be picked more often (1/2 vs 1/5 weight)
        self.assertGreater(picks.count("SHORT"), picks.count("LONG"))

    def test_pick_target_empty_uncovered(self):
        rng = random.Random(42)
        self.assertIsNone(_pick_target(set(), {}, rng))

    def test_generate_directed_input_satisfies_constraints(self):
        rng = random.Random(42)
        var_report = VariableReport()
        var_report.variables = {
            "WS-CODE": VariableInfo(name="WS-CODE", classification="input",
                                    condition_literals=["A", "B", "C"]),
        }
        pc = PathConstraints(
            target="DEEP",
            path=["MAIN", "STEP-1", "DEEP"],
            constraints=[
                GatingCondition(variable="WS-CODE", values=["A"], negated=False),
            ],
        )
        fuzzer = _FuzzerState()

        state, _ = _generate_directed_input("DEEP", pc, var_report, None, rng, fuzzer)
        self.assertEqual(state.get("WS-CODE"), "A")

    def test_generate_directed_input_with_stubs(self):
        rng = random.Random(42)
        var_report = VariableReport()
        var_report.variables = {
            "SQLCODE": VariableInfo(name="SQLCODE", classification="status",
                                    condition_literals=[0, -803]),
        }
        pc = PathConstraints(target="ERR", path=["MAIN", "ERR"], constraints=[])
        stub_mapping = {"SQL": ["SQLCODE"]}
        fuzzer = _FuzzerState()

        state, stub_out = _generate_directed_input(
            "ERR", pc, var_report, stub_mapping, rng, fuzzer,
        )
        self.assertIsNotNone(stub_out)
        self.assertIn("SQL", stub_out)

    def test_guided_with_static_analysis(self):
        """End-to-end: guided fuzzing with static analysis should reach
        error-handling paragraphs gated behind SQLCODE checks."""
        prog = _make_program([
            {
                "name": "MAIN-PARA", "line_start": 1, "line_end": 10,
                "statements": [
                    {
                        "type": "EXEC_SQL",
                        "text": "EXEC SQL SELECT 1 END-EXEC",
                        "line_start": 1, "line_end": 1,
                        "attributes": {"raw_text": "SELECT 1"},
                        "children": [],
                    },
                    {
                        "type": "IF",
                        "text": "IF SQLCODE NOT = 0",
                        "line_start": 2, "line_end": 5,
                        "attributes": {"condition": "SQLCODE NOT = 0"},
                        "children": [
                            {
                                "type": "PERFORM",
                                "text": "PERFORM SQL-ERROR",
                                "line_start": 3, "line_end": 3,
                                "attributes": {"target": "SQL-ERROR"},
                                "children": [],
                            },
                            {
                                "type": "ELSE", "text": "ELSE",
                                "line_start": 4, "line_end": 5,
                                "attributes": {},
                                "children": [{
                                    "type": "PERFORM",
                                    "text": "PERFORM SQL-OK",
                                    "line_start": 5, "line_end": 5,
                                    "attributes": {"target": "SQL-OK"},
                                    "children": [],
                                }],
                            },
                        ],
                    },
                ],
            },
            {
                "name": "SQL-ERROR", "line_start": 11, "line_end": 15,
                "statements": [{
                    "type": "MOVE", "text": "MOVE 'ERROR' TO WS-RESULT",
                    "line_start": 12, "line_end": 12,
                    "attributes": {"source": "'ERROR'", "targets": "WS-RESULT"},
                    "children": [],
                }],
            },
            {
                "name": "SQL-OK", "line_start": 16, "line_end": 20,
                "statements": [{
                    "type": "MOVE", "text": "MOVE 'OK' TO WS-RESULT",
                    "line_start": 17, "line_end": 17,
                    "attributes": {"source": "'OK'", "targets": "WS-RESULT"},
                    "children": [],
                }],
            },
        ])
        var_report = extract_variables(prog)
        call_graph = build_static_call_graph(prog)
        gating_conds = extract_gating_conditions(prog, call_graph)
        from specter.variable_extractor import extract_stub_status_mapping
        stub_mapping = extract_stub_status_mapping(prog, var_report)

        code = generate_code(prog, var_report=var_report, instrument=True)
        tmp = tempfile.NamedTemporaryFile(suffix=".py", delete=False, mode="w")
        tmp.write(code)
        tmp.close()
        path = Path(tmp.name)
        try:
            all_paras = [p.name for p in prog.paragraphs]
            report = run_monte_carlo(
                path, n_iterations=2000, seed=42,
                var_report=var_report, instrument=True,
                all_paragraphs=all_paras, guided=True,
                call_graph=call_graph,
                gating_conditions=gating_conds,
                stub_mapping=stub_mapping,
            )
            hit = set(report.analysis_report.paragraph_hit_counts.keys())
            # Both branches should be hit: stub diversification sets SQLCODE != 0
            self.assertIn("SQL-ERROR", hit)
            self.assertIn("SQL-OK", hit)
        finally:
            path.unlink(missing_ok=True)

    def test_reachability_in_report(self):
        """Analysis report should include reachability info when call_graph given."""
        prog = _make_program([
            {
                "name": "MAIN", "line_start": 1, "line_end": 5,
                "statements": [{
                    "type": "PERFORM", "text": "PERFORM A",
                    "line_start": 1, "line_end": 1,
                    "attributes": {"target": "A"}, "children": [],
                }],
            },
            {
                "name": "A", "line_start": 6, "line_end": 10,
                "statements": [],
            },
            {
                "name": "ORPHAN", "line_start": 11, "line_end": 15,
                "statements": [],
            },
        ])
        var_report = extract_variables(prog)
        call_graph = build_static_call_graph(prog)
        gating_conds = extract_gating_conditions(prog, call_graph)

        code = generate_code(prog, var_report=var_report, instrument=True)
        tmp = tempfile.NamedTemporaryFile(suffix=".py", delete=False, mode="w")
        tmp.write(code)
        tmp.close()
        path = Path(tmp.name)
        try:
            all_paras = [p.name for p in prog.paragraphs]
            report = run_monte_carlo(
                path, n_iterations=100, seed=42,
                var_report=var_report, instrument=True,
                all_paragraphs=all_paras, guided=True,
                call_graph=call_graph,
                gating_conditions=gating_conds,
            )
            analysis = report.analysis_report
            self.assertIn("ORPHAN", analysis.structurally_unreachable)
            summary = analysis.summary()
            self.assertIn("structurally unreachable", summary)
        finally:
            path.unlink(missing_ok=True)


class TestAllSuccessGeneration(unittest.TestCase):

    def test_all_success_state_has_success_values(self):
        report = VariableReport()
        report.variables = {
            "FS-INPUT": VariableInfo(name="FS-INPUT", classification="status",
                                     condition_literals=["00", "10", "35"]),
            "FS-OUTPUT": VariableInfo(name="FS-OUTPUT", classification="status"),
            "WS-RETURN-CODE": VariableInfo(name="WS-RETURN-CODE", classification="status",
                                            condition_literals=[0, 4, 8]),
            "WS-FLAG": VariableInfo(name="WS-FLAG", classification="flag",
                                     condition_literals=["Y", "N"]),
            "WS-DATA": VariableInfo(name="WS-DATA", classification="input"),
        }
        state = _generate_all_success_state(report)
        # Status vars should have first harvested literal or default success
        self.assertEqual(state["FS-INPUT"], "00")
        self.assertEqual(state["FS-OUTPUT"], "00")
        self.assertEqual(state["WS-RETURN-CODE"], 0)
        # Flag should have first harvested literal
        self.assertEqual(state["WS-FLAG"], "Y")
        # Input should have a value
        self.assertIn("WS-DATA", state)

    def test_all_success_stubs_all_succeed(self):
        report = VariableReport()
        report.variables = {
            "SQLCODE": VariableInfo(name="SQLCODE", classification="status",
                                    condition_literals=[0, -803, 100]),
            "FS-FILE1": VariableInfo(name="FS-FILE1", classification="status",
                                      condition_literals=["00", "10"]),
        }
        stub_mapping = {"SQL": ["SQLCODE"], "OPEN_FILE1": ["FS-FILE1"]}
        stubs = _generate_all_success_stubs(stub_mapping, report)
        # SQL gets multiple success outcome entries + EOF (SQLCODE=100)
        # Each entry is a list of (var, val) pairs
        sql_stubs = stubs["SQL"]
        for entry in sql_stubs[:-1]:
            self.assertIsInstance(entry, list)
            self.assertTrue(all(v == 0 for _, v in entry))
        # Last entry is EOF
        self.assertEqual(sql_stubs[-1], [("SQLCODE", 100)])
        # Non-READ/SQL operations get multiple outcome entries
        self.assertTrue(len(stubs["OPEN_FILE1"]) >= 1)
        self.assertEqual(stubs["OPEN_FILE1"][0], [("FS-FILE1", "00")])


class TestGatePreservingMutation(unittest.TestCase):

    def test_gate_preserving_only_changes_non_status(self):
        report = VariableReport()
        report.variables = {
            "FS-INPUT": VariableInfo(name="FS-INPUT", classification="status"),
            "FS-OUTPUT": VariableInfo(name="FS-OUTPUT", classification="status"),
            "WS-DATA": VariableInfo(name="WS-DATA", classification="input",
                                     condition_literals=["A", "B"]),
            "WS-FLAG": VariableInfo(name="WS-FLAG", classification="flag"),
        }
        parent = {"FS-INPUT": "00", "FS-OUTPUT": "00", "WS-DATA": "A", "WS-FLAG": True}
        fuzzer = _FuzzerState()

        # Force the gate-preserving branch (r in [0.48, 0.60))
        # Run many mutations and check that when gate-preserving fires,
        # status vars are unchanged
        rng = random.Random(42)
        gate_preserving_fired = False
        for _ in range(500):
            rng_state = rng.getstate()
            r = rng.random()
            if 0.48 <= r < 0.60:
                # This would be the gate-preserving branch
                gate_preserving_fired = True
                # Restore state and run the actual mutation
                rng.setstate(rng_state)
                mutated, _ = _mutate_state(parent, report, rng, fuzzer)
                # Status vars should be unchanged
                self.assertEqual(mutated["FS-INPUT"], "00")
                self.assertEqual(mutated["FS-OUTPUT"], "00")
                break
        self.assertTrue(gate_preserving_fired)


class TestSeedInjection(unittest.TestCase):

    def test_seed_injection_populates_corpus(self):
        """All-success seed injection should add entries to corpus before main loop."""
        prog = _make_program([
            {
                "name": "MAIN-PARA", "line_start": 1, "line_end": 10,
                "statements": [
                    {"type": "MOVE", "text": "MOVE 'A' TO WS-RESULT",
                     "line_start": 1, "line_end": 1,
                     "attributes": {"source": "'A'", "targets": "WS-RESULT"},
                     "children": []},
                ],
            },
        ])
        var_report = extract_variables(prog)
        code = generate_code(prog, var_report=var_report, instrument=True)
        tmp = tempfile.NamedTemporaryFile(suffix=".py", delete=False, mode="w")
        tmp.write(code)
        tmp.close()
        path = Path(tmp.name)
        try:
            all_paras = [p.name for p in prog.paragraphs]
            # Run with just 1 iteration — seeds should already be in corpus
            report = run_monte_carlo(
                path, n_iterations=1, seed=42,
                var_report=var_report, instrument=True,
                all_paragraphs=all_paras, guided=True,
            )
            # Should have successful runs from seed injection
            self.assertGreater(report.n_successful, 0)
            self.assertIn("MAIN-PARA",
                          report.analysis_report.paragraph_hit_counts)
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
