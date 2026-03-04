"""Tests for ast_parser module."""

import json
import unittest

from specter.ast_parser import parse_ast
from specter.models import Program


class TestParseAst(unittest.TestCase):

    def test_parse_minimal(self):
        data = {
            "program_id": "TEST001",
            "paragraphs": [
                {
                    "name": "MAIN-PARA",
                    "line_start": 1,
                    "line_end": 5,
                    "statements": [
                        {
                            "type": "DISPLAY",
                            "text": "DISPLAY 'HELLO'",
                            "line_start": 2,
                            "line_end": 2,
                            "attributes": {},
                            "children": [],
                        }
                    ],
                }
            ],
        }
        program = parse_ast(data)
        self.assertIsInstance(program, Program)
        self.assertEqual(program.program_id, "TEST001")
        self.assertEqual(len(program.paragraphs), 1)
        self.assertEqual(program.paragraphs[0].name, "MAIN-PARA")
        self.assertEqual(len(program.paragraphs[0].statements), 1)
        self.assertEqual(program.paragraphs[0].statements[0].type, "DISPLAY")

    def test_paragraph_index(self):
        data = {
            "program_id": "TEST002",
            "paragraphs": [
                {"name": "PARA-A", "line_start": 1, "line_end": 3, "statements": []},
                {"name": "PARA-B", "line_start": 4, "line_end": 6, "statements": []},
            ],
        }
        program = parse_ast(data)
        self.assertIn("PARA-A", program.paragraph_index)
        self.assertIn("PARA-B", program.paragraph_index)
        self.assertEqual(program.paragraph_index["PARA-A"].name, "PARA-A")

    def test_nested_children(self):
        data = {
            "program_id": "TEST003",
            "paragraphs": [
                {
                    "name": "MAIN",
                    "line_start": 1,
                    "line_end": 10,
                    "statements": [
                        {
                            "type": "IF",
                            "text": "IF X = 1",
                            "line_start": 2,
                            "line_end": 8,
                            "attributes": {"condition": "X = 1"},
                            "children": [
                                {
                                    "type": "MOVE",
                                    "text": "MOVE 1 TO Y",
                                    "line_start": 3,
                                    "line_end": 3,
                                    "attributes": {"source": "1", "targets": "Y"},
                                    "children": [],
                                },
                                {
                                    "type": "ELSE",
                                    "text": "ELSE",
                                    "line_start": 5,
                                    "line_end": 7,
                                    "attributes": {},
                                    "children": [
                                        {
                                            "type": "MOVE",
                                            "text": "MOVE 2 TO Y",
                                            "line_start": 6,
                                            "line_end": 6,
                                            "attributes": {"source": "2", "targets": "Y"},
                                            "children": [],
                                        }
                                    ],
                                },
                            ],
                        }
                    ],
                }
            ],
        }
        program = parse_ast(data)
        if_stmt = program.paragraphs[0].statements[0]
        self.assertEqual(if_stmt.type, "IF")
        self.assertEqual(len(if_stmt.children), 2)
        self.assertEqual(if_stmt.children[0].type, "MOVE")
        self.assertEqual(if_stmt.children[1].type, "ELSE")
        self.assertEqual(len(if_stmt.children[1].children), 1)

    def test_parse_from_file(self, tmp_path=None):
        """Test parsing from a file path."""
        import tempfile
        import os

        data = {
            "program_id": "FILETEST",
            "paragraphs": [
                {"name": "MAIN", "line_start": 1, "line_end": 2, "statements": []},
            ],
        }
        fd, path = tempfile.mkstemp(suffix=".ast")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f)
            program = parse_ast(path)
            self.assertEqual(program.program_id, "FILETEST")
        finally:
            os.unlink(path)

    def test_statement_walk(self):
        data = {
            "program_id": "WALK",
            "paragraphs": [{
                "name": "MAIN",
                "line_start": 1,
                "line_end": 10,
                "statements": [{
                    "type": "IF",
                    "text": "IF X = 1",
                    "line_start": 2,
                    "line_end": 5,
                    "attributes": {"condition": "X = 1"},
                    "children": [{
                        "type": "MOVE",
                        "text": "MOVE 1 TO Y",
                        "line_start": 3,
                        "line_end": 3,
                        "attributes": {"source": "1", "targets": "Y"},
                        "children": [],
                    }],
                }],
            }],
        }
        program = parse_ast(data)
        if_stmt = program.paragraphs[0].statements[0]
        nodes = list(if_stmt.walk())
        self.assertEqual(len(nodes), 2)
        self.assertEqual(nodes[0].type, "IF")
        self.assertEqual(nodes[1].type, "MOVE")


if __name__ == "__main__":
    unittest.main()
