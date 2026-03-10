"""Tests for code_generator module."""

import unittest

from specter.ast_parser import parse_ast
from specter.code_generator import generate_code
from specter.variable_extractor import extract_variables


class TestCodeGenerator(unittest.TestCase):

    def _make_program(self, statements):
        return parse_ast({
            "program_id": "TEST",
            "paragraphs": [{
                "name": "MAIN-PARA",
                "line_start": 1,
                "line_end": 100,
                "statements": statements,
            }],
        })

    def test_generates_valid_python(self):
        program = self._make_program([
            {"type": "DISPLAY", "text": "DISPLAY 'HELLO'",
             "line_start": 1, "line_end": 1, "attributes": {}, "children": []},
            {"type": "GOBACK", "text": "GOBACK",
             "line_start": 2, "line_end": 2, "attributes": {}, "children": []},
        ])
        code = generate_code(program)
        # Must compile without error
        compile(code, "<test>", "exec")

    def test_run_function_exists(self):
        program = self._make_program([
            {"type": "DISPLAY", "text": "DISPLAY 'HELLO'",
             "line_start": 1, "line_end": 1, "attributes": {}, "children": []},
        ])
        code = generate_code(program)
        ns = {}
        exec(code, ns)
        self.assertIn("run", ns)
        result = ns["run"]()
        self.assertIn("_display", result)

    def test_move_generates_assignment(self):
        program = self._make_program([
            {"type": "MOVE", "text": "MOVE 'X' TO MY-VAR",
             "line_start": 1, "line_end": 1,
             "attributes": {"source": "'X'", "targets": "MY-VAR"},
             "children": []},
        ])
        code = generate_code(program)
        ns = {}
        exec(code, ns)
        result = ns["run"]()
        self.assertEqual(result["MY-VAR"], "X")

    def test_if_else(self):
        program = self._make_program([
            {
                "type": "IF", "text": "IF MY-FLAG = 'Y'",
                "line_start": 1, "line_end": 5,
                "attributes": {"condition": "MY-FLAG = 'Y'"},
                "children": [
                    {"type": "MOVE", "text": "MOVE 1 TO RESULT",
                     "line_start": 2, "line_end": 2,
                     "attributes": {"source": "1", "targets": "RESULT"},
                     "children": []},
                    {"type": "ELSE", "text": "ELSE",
                     "line_start": 3, "line_end": 4,
                     "attributes": {},
                     "children": [
                         {"type": "MOVE", "text": "MOVE 2 TO RESULT",
                          "line_start": 4, "line_end": 4,
                          "attributes": {"source": "2", "targets": "RESULT"},
                          "children": []},
                     ]},
                ],
            },
        ])
        code = generate_code(program)
        ns = {}
        exec(code, ns)

        # Test with flag = 'Y'
        result = ns["run"]({"MY-FLAG": "Y"})
        self.assertEqual(result["RESULT"], 1)

        # Test with flag = 'N'
        result = ns["run"]({"MY-FLAG": "N"})
        self.assertEqual(result["RESULT"], 2)

    def test_perform_calls_paragraph(self):
        data = {
            "program_id": "TEST",
            "paragraphs": [
                {
                    "name": "MAIN-PARA",
                    "line_start": 1, "line_end": 5,
                    "statements": [
                        {"type": "PERFORM", "text": "PERFORM SUB-PARA",
                         "line_start": 2, "line_end": 2,
                         "attributes": {"target": "SUB-PARA"},
                         "children": []},
                    ],
                },
                {
                    "name": "SUB-PARA",
                    "line_start": 6, "line_end": 10,
                    "statements": [
                        {"type": "MOVE", "text": "MOVE 'DONE' TO STATUS",
                         "line_start": 7, "line_end": 7,
                         "attributes": {"source": "'DONE'", "targets": "STATUS"},
                         "children": []},
                    ],
                },
            ],
        }
        program = parse_ast(data)
        code = generate_code(program)
        ns = {}
        exec(code, ns)
        result = ns["run"]()
        self.assertEqual(result["STATUS"], "DONE")

    def test_missing_perform_target_with_parentheses_generates_valid_stub(self):
        program = self._make_program([
            {"type": "PERFORM", "text": "PERFORM BUCKET-AGED-DEROGATORY(1",
             "line_start": 1, "line_end": 1,
             "attributes": {"target": "BUCKET-AGED-DEROGATORY(1"},
             "children": []},
        ])
        code = generate_code(program)
        compile(code, "<test>", "exec")

    def test_goback_stops_execution(self):
        data = {
            "program_id": "TEST",
            "paragraphs": [
                {
                    "name": "MAIN-PARA",
                    "line_start": 1, "line_end": 5,
                    "statements": [
                        {"type": "MOVE", "text": "MOVE 'A' TO X",
                         "line_start": 1, "line_end": 1,
                         "attributes": {"source": "'A'", "targets": "X"},
                         "children": []},
                        {"type": "GOBACK", "text": "GOBACK",
                         "line_start": 2, "line_end": 2,
                         "attributes": {}, "children": []},
                        {"type": "MOVE", "text": "MOVE 'B' TO X",
                         "line_start": 3, "line_end": 3,
                         "attributes": {"source": "'B'", "targets": "X"},
                         "children": []},
                    ],
                },
            ],
        }
        program = parse_ast(data)
        code = generate_code(program)
        ns = {}
        exec(code, ns)
        result = ns["run"]()
        self.assertEqual(result["X"], "A")

    def test_call_records_external(self):
        program = self._make_program([
            {"type": "CALL", "text": "CALL 'CBLTDLI' USING X Y",
             "line_start": 1, "line_end": 1,
             "attributes": {"target": "CBLTDLI"},
             "children": []},
        ])
        code = generate_code(program)
        ns = {}
        exec(code, ns)
        result = ns["run"]()
        self.assertEqual(len(result["_calls"]), 1)
        self.assertEqual(result["_calls"][0]["name"], "CBLTDLI")

    def test_set_to_true(self):
        program = self._make_program([
            {"type": "SET", "text": "SET MY-FLAG TO TRUE",
             "line_start": 1, "line_end": 1,
             "attributes": {}, "children": []},
        ])
        code = generate_code(program)
        ns = {}
        exec(code, ns)
        result = ns["run"]()
        self.assertTrue(result["MY-FLAG"])

    def test_exec_sql_records(self):
        program = self._make_program([
            {"type": "EXEC_SQL", "text": "EXEC SQL SELECT 1",
             "line_start": 1, "line_end": 1,
             "attributes": {"raw_text": "EXEC SQL SELECT 1 END-EXEC"},
             "children": []},
        ])
        code = generate_code(program)
        ns = {}
        exec(code, ns)
        result = ns["run"]()
        self.assertEqual(len(result["_execs"]), 1)
        self.assertEqual(result["_execs"][0]["kind"], "SQL")

    def test_add(self):
        program = self._make_program([
            {"type": "ADD", "text": "ADD 5 TO MY-COUNTER",
             "line_start": 1, "line_end": 1,
             "attributes": {}, "children": []},
        ])
        code = generate_code(program)
        ns = {}
        exec(code, ns)
        result = ns["run"]({"MY-COUNTER": 10})
        self.assertEqual(result["MY-COUNTER"], 15)

    def test_initialize(self):
        program = self._make_program([
            {"type": "INITIALIZE", "text": "INITIALIZE MY-VAR",
             "line_start": 1, "line_end": 1,
             "attributes": {}, "children": []},
        ])
        code = generate_code(program)
        ns = {}
        exec(code, ns)
        result = ns["run"]({"MY-VAR": "something"})
        self.assertEqual(result["MY-VAR"], "")


    def test_compute_with_star_comment(self):
        """COMPUTE with *> comments should strip comments and generate code."""
        program = self._make_program([
            {"type": "COMPUTE",
             "text": "COMPUTE WS-RESULT = WS-A * *> OLD-VAR. WS-B",
             "line_start": 1, "line_end": 1,
             "attributes": {"target": "WS-RESULT",
                            "expression": "WS-A * *> OLD-VAR. WS-B"},
             "children": []},
        ])
        code = generate_code(program)
        ns = {}
        exec(code, ns)
        result = ns["run"]({"WS-A": 5, "WS-B": 3})
        self.assertEqual(result["WS-RESULT"], 15)

    def test_add_no_keyword_leak(self):
        """ADD with *> comments should not treat COBOL keywords as variables."""
        program = self._make_program([
            {"type": "ADD",
             "text": "ADD WS-X *> TO OLD-TARGET. TO WS-Y",
             "line_start": 1, "line_end": 1,
             "attributes": {}, "children": []},
        ])
        code = generate_code(program)
        # Should not contain state['TO']
        self.assertNotIn("state['TO']", code)
        ns = {}
        exec(code, ns)
        result = ns["run"]({"WS-X": 10, "WS-Y": 5})
        self.assertEqual(result["WS-Y"], 15)

    def test_if_with_star_comment_in_condition(self):
        """IF with *> comments in condition should strip and parse correctly."""
        program = self._make_program([
            {"type": "IF",
             "text": "IF WS-FLAG AND *> old-check. WS-OTHER",
             "line_start": 1, "line_end": 1,
             "attributes": {"condition": "WS-FLAG AND *> old-check. WS-OTHER"},
             "children": [
                 {"type": "DISPLAY", "text": "DISPLAY 'YES'",
                  "line_start": 2, "line_end": 2,
                  "attributes": {}, "children": []},
             ]},
        ])
        code = generate_code(program)
        ns = {}
        exec(code, ns)
        # Both WS-FLAG and WS-OTHER truthy → should display YES
        result = ns["run"]({"WS-FLAG": True, "WS-OTHER": True})
        self.assertIn("YES", str(result.get("_display", [])))


if __name__ == "__main__":
    unittest.main()
