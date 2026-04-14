"""Tests for the WireMock mapping generator."""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from specter.java_templates.wiremock import (
    is_routable_call_key,
    render_mapping,
    write_mappings,
)


class TestIsRoutableCallKey(unittest.TestCase):
    def test_non_mq_call_is_routable(self):
        self.assertTrue(is_routable_call_key("CALL:CUSTAPI"))

    def test_mq_call_is_not_routable(self):
        self.assertFalse(is_routable_call_key("CALL:MQOPEN"))
        self.assertFalse(is_routable_call_key("CALL:MQGET"))
        self.assertFalse(is_routable_call_key("CALL:MQPUT1"))
        self.assertFalse(is_routable_call_key("CALL:MQCLOSE"))
        self.assertFalse(is_routable_call_key("CALL:mqopen"))

    def test_non_call_op_keys_are_not_routable(self):
        self.assertFalse(is_routable_call_key("SQL-SELECT"))
        self.assertFalse(is_routable_call_key("CICS-READ"))
        self.assertFalse(is_routable_call_key("READ:ACCOUNT-FILE"))


class TestRenderMapping(unittest.TestCase):
    def test_basic_shape(self):
        mapping = render_mapping(
            "CUSTAPI", [["ACCT-BAL", 100], ["ACCT-STATUS", "A"]]
        )
        self.assertEqual(mapping["request"]["method"], "POST")
        self.assertEqual(mapping["request"]["urlPattern"], "/custapi")
        self.assertEqual(mapping["response"]["status"], 200)
        self.assertEqual(
            mapping["response"]["headers"]["Content-Type"], "application/json"
        )
        self.assertEqual(
            mapping["response"]["jsonBody"],
            {"ACCT-BAL": 100, "ACCT-STATUS": "A"},
        )

    def test_progname_lowercased_in_url(self):
        mapping = render_mapping("FOO-BAR", [])
        self.assertEqual(mapping["request"]["urlPattern"], "/foo-bar")

    def test_scenario_chaining(self):
        mapping = render_mapping(
            "FOO",
            [["X", 1]],
            scenario_name="tc1_FOO",
            required_state="step_1",
            new_state="step_2",
        )
        self.assertEqual(mapping["scenarioName"], "tc1_FOO")
        self.assertEqual(mapping["requiredScenarioState"], "step_1")
        self.assertEqual(mapping["newScenarioState"], "step_2")

    def test_no_scenario_when_unspecified(self):
        mapping = render_mapping("FOO", [["X", 1]])
        self.assertNotIn("scenarioName", mapping)
        self.assertNotIn("requiredScenarioState", mapping)


class TestWriteMappings(unittest.TestCase):
    def test_skips_when_no_routable_calls(self):
        with TemporaryDirectory() as td:
            files = write_mappings(
                "tc1",
                {"CALL:MQGET": [[["WS-BUF", "x"]]], "SQL-SELECT": [[["SQLCODE", 0]]]},
                td,
            )
            self.assertEqual(files, [])
            # No subdir created either.
            self.assertFalse((Path(td) / "tc1").exists())

    def test_writes_one_file_per_outcome_no_chain(self):
        with TemporaryDirectory() as td:
            files = write_mappings(
                "tc1",
                {"CALL:CUSTAPI": [[["ACCT-BAL", 100]]]},
                td,
            )
            self.assertEqual(len(files), 1)
            self.assertTrue(files[0].name.endswith("custapi.json"))
            mapping = json.loads(files[0].read_text())
            self.assertEqual(
                mapping["response"]["jsonBody"], {"ACCT-BAL": 100}
            )
            self.assertNotIn("scenarioName", mapping)

    def test_multi_outcome_chains_via_scenario_state(self):
        with TemporaryDirectory() as td:
            files = write_mappings(
                "abc123",
                {
                    "CALL:FOO": [
                        [["A", 1]],
                        [["A", 2]],
                        [["A", 3]],
                    ]
                },
                td,
            )
            self.assertEqual(len(files), 3)
            mappings = [json.loads(f.read_text()) for f in files]
            for m in mappings:
                self.assertEqual(m["scenarioName"], "abc123_FOO")
            # First requires Started, transitions to step_1
            self.assertEqual(mappings[0]["requiredScenarioState"], "Started")
            self.assertEqual(mappings[0]["newScenarioState"], "step_1")
            # Middle requires step_1, transitions to step_2
            self.assertEqual(mappings[1]["requiredScenarioState"], "step_1")
            self.assertEqual(mappings[1]["newScenarioState"], "step_2")
            # Last requires step_2, no further transition
            self.assertEqual(mappings[2]["requiredScenarioState"], "step_2")
            self.assertNotIn("newScenarioState", mappings[2])

    def test_jsonBody_keys_match_cobol_var_names_exactly(self):
        with TemporaryDirectory() as td:
            files = write_mappings(
                "tc1",
                {"CALL:FOO": [[["WS-Mixed_Name", "v"], ["DASH-NAME", 1]]]},
                td,
            )
            mapping = json.loads(files[0].read_text())
            self.assertIn("WS-Mixed_Name", mapping["response"]["jsonBody"])
            self.assertIn("DASH-NAME", mapping["response"]["jsonBody"])

    def test_files_under_per_test_subdir(self):
        with TemporaryDirectory() as td:
            files = write_mappings(
                "tc-with-dash",
                {"CALL:FOO": [[["X", 1]]]},
                td,
            )
            self.assertEqual(len(files), 1)
            self.assertEqual(files[0].parent.name, "tc-with-dash")


if __name__ == "__main__":
    unittest.main()
