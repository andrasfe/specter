"""Tests for the Java equivalence templates and IT wiring."""

import unittest

from specter.java_templates.equivalence import (
    COBOL_SNAPSHOT_JAVA,
    EQUIVALENCE_ASSERT_JAVA,
)
from specter.java_templates.integration_test import MOCKITO_INTEGRATION_TEST_JAVA


class TestCobolSnapshotTemplate(unittest.TestCase):
    def setUp(self) -> None:
        self.src = COBOL_SNAPSHOT_JAVA.format(package_name="com.foo")

    def test_class_declared_in_correct_package(self):
        self.assertIn("package com.foo;", self.src)
        self.assertIn("public class CobolSnapshot", self.src)

    def test_load_for_resource_path(self):
        self.assertIn("/cobol_snapshots/", self.src)
        self.assertIn("loadFor", self.src)

    def test_exposes_expected_fields(self):
        for f in [
            "public final String id",
            "public final boolean abended",
            "public final List<String> displays",
            "public final List<String> paragraphsCovered",
            "public final Map<String, String> finalState",
        ]:
            self.assertIn(f, self.src, f"missing field: {f}")


class TestEquivalenceAssertTemplate(unittest.TestCase):
    def setUp(self) -> None:
        self.src = EQUIVALENCE_ASSERT_JAVA.format(package_name="com.foo")

    def test_class_declared_in_correct_package(self):
        self.assertIn("package com.foo;", self.src)
        self.assertIn("public final class EquivalenceAssert", self.src)

    def test_assert_equivalent_signature(self):
        self.assertIn(
            "public static void assertEquivalent(CobolSnapshot snapshot, ProgramState state)",
            self.src,
        )

    def test_normalize_handles_trailing_spaces_and_numerics(self):
        # Spot-check key normalisation snippets are present.
        self.assertIn("stripTrailing(s, ' ')", self.src)
        self.assertIn("stripLeading(s, '0')", self.src)
        self.assertIn("NUMERIC.matcher", self.src)

    def test_branch_ids_documented_as_not_compared(self):
        # Per design, branches are NOT compared cross-tool (IDs differ).
        self.assertNotIn("snapshot.branches.equals(state.branches)", self.src)
        self.assertNotIn("assertEquals(snapshot.branches", self.src)

    def test_strict_checks_on_displays_and_trace(self):
        self.assertIn("snapDisplays.equals(javaDisplays)", self.src)
        # Trace comparison goes through dedupPreserveOrder (COBOL's
        # parse_trace dedups; Java's state.trace is a full execution log).
        self.assertIn("javaUniqueTrace = dedupPreserveOrder(state.trace)", self.src)
        self.assertIn("snapshot.paragraphsCovered.equals(javaUniqueTrace)", self.src)


class TestIntegrationTestWiring(unittest.TestCase):
    def setUp(self) -> None:
        self.src = MOCKITO_INTEGRATION_TEST_JAVA.format(
            package_name="com.foo",
            program_class_name="DEMO01Program",
            verify_calls="        // none",
        )

    def test_loads_snapshot_and_calls_assertEquivalent(self):
        self.assertIn("CobolSnapshot.loadFor", self.src)
        self.assertIn("EquivalenceAssert.assertEquivalent(snapshot, state)", self.src)

    def test_layer_field_is_string_to_handle_both_jsonl_formats(self):
        # cobol_coverage._save_test_case writes layer as a string strategy
        # name (e.g. "baseline"); TestStore.append writes it as an int.
        # The IT loader must accept both — getAsString() works for both.
        self.assertIn("final String layer", self.src)
        self.assertIn('layer = obj.get("layer").getAsString()', self.src)
        self.assertNotIn('obj.get("layer").getAsInt()', self.src)

    def test_stub_outcomes_loader_handles_both_shapes(self):
        # cobol_coverage writes a JSON array; TestStore writes a JSON object.
        self.assertIn("so.isJsonObject()", self.src)
        self.assertIn("so.isJsonArray()", self.src)
        self.assertIn("computeIfAbsent", self.src)


if __name__ == "__main__":
    unittest.main()
