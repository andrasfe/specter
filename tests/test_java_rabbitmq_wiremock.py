"""Tests for the RabbitMQ + WireMock + real-DB-seed Java generation defaults.

Validates that the generated Maven project, runtime classes, docker-compose,
and integration-test harness use RabbitMQ (not ActiveMQ Artemis), include the
WireMock sidecar, and route non-MQ CALLs through ``stubs.callProgram(...)``.
"""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from specter.code_generator import _PARAGRAPH_ORDER  # noqa: F401  (side effect import path)
from specter.java_code_generator import (
    _extract_call_using_vars,
    _gen_call_java,
    generate_java_project,
)
from specter.java_templates.docker import DOCKER_COMPOSE_YML
from specter.java_templates.integration_test import (
    INTEGRATION_POM_XML,
    MOCKITO_INTEGRATION_TEST_JAVA,
)
from specter.java_templates.pom_xml import POM_XML
from specter.java_templates.runtime import (
    APP_CONFIG_JAVA,
    JDBC_STUB_EXECUTOR_JAVA,
    MAIN_JAVA,
    STUB_EXECUTOR_JAVA,
)
from specter.models import Paragraph, Program, Statement


class _FakeBuilder:
    """Minimal stand-in for _JavaCodeBuilder.stmt() — just records emissions."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def stmt(self, s: str) -> None:
        self.lines.append(s)

    def emit(self, s: str) -> None:
        self.lines.append(s)


def _make_call(target: str, raw_text: str = "", using=None) -> Statement:
    attrs: dict[str, object] = {"target": target}
    if raw_text:
        attrs["raw_text"] = raw_text
    if using is not None:
        attrs["using"] = using
    return Statement(
        type="CALL",
        text=raw_text or f"CALL '{target}'",
        line_start=0,
        line_end=0,
        attributes=attrs,
        children=[],
    )


class TestPomDeps(unittest.TestCase):
    def test_main_pom_uses_amqp_client(self):
        pom = POM_XML.format(
            group_id="g", artifact_id="a", program_name="p", main_class="m.M"
        )
        self.assertIn("com.rabbitmq", pom)
        self.assertIn("amqp-client", pom)
        self.assertIn("httpclient5", pom)
        self.assertNotIn("artemis-jakarta-client", pom)
        self.assertNotIn("jakarta.jms-api", pom)
        self.assertNotIn("netty-handler", pom)

    def test_integration_pom_uses_amqp_client(self):
        pom = INTEGRATION_POM_XML.format(
            group_id="g", artifact_id="a", program_name="p"
        )
        self.assertIn("amqp-client", pom)
        self.assertIn("httpclient5", pom)
        self.assertNotIn("artemis-jakarta-client", pom)
        self.assertNotIn("jakarta.jms-api", pom)


class TestDockerCompose(unittest.TestCase):
    def setUp(self) -> None:
        self.compose = DOCKER_COMPOSE_YML.format(program_name="P")

    def test_replaces_activemq_with_rabbitmq(self):
        self.assertIn("rabbitmq:3-management", self.compose)
        self.assertNotIn("apache/activemq-artemis", self.compose)
        self.assertNotIn("ARTEMIS_USER", self.compose)

    def test_includes_wiremock_sidecar(self):
        self.assertIn("wiremock/wiremock", self.compose)
        self.assertIn("/home/wiremock/mappings", self.compose)
        self.assertIn("--global-response-templating", self.compose)

    def test_app_env_has_amqp_and_call_base_url(self):
        self.assertIn("SPECTER_AMQP_HOST: rabbitmq", self.compose)
        self.assertIn("SPECTER_CALL_BASE_URL: http://wiremock:8080", self.compose)
        self.assertNotIn("SPECTER_JMS_URL", self.compose)


class TestRuntimeTemplates(unittest.TestCase):
    def setUp(self) -> None:
        self.fmt = dict(
            package_name="com.foo", program_id="X", program_class_name="XProgram"
        )

    def test_app_config_exposes_amqp_and_call_base_url(self):
        cfg = APP_CONFIG_JAVA.format(**self.fmt)
        for getter in (
            "getAmqpHost",
            "getAmqpPort",
            "getAmqpUser",
            "getAmqpPassword",
            "getAmqpVirtualHost",
            "getCallBaseUrl",
        ):
            self.assertIn(getter, cfg, f"missing {getter} in AppConfig")
        self.assertNotIn("getJmsBrokerUrl", cfg)

    def test_main_uses_typed_rabbitmq_factory(self):
        main = MAIN_JAVA.format(**self.fmt)
        self.assertIn("com.rabbitmq.client.ConnectionFactory", main)
        self.assertNotIn("ActiveMQConnectionFactory", main)

    def test_jdbc_executor_uses_amqp_and_http(self):
        src = JDBC_STUB_EXECUTOR_JAVA.format(**self.fmt)
        self.assertIn("com.rabbitmq.client.Channel", src)
        self.assertIn("com.rabbitmq.client.GetResponse", src)
        self.assertIn("CloseableHttpClient", src)
        self.assertIn("HttpPost", src)
        self.assertIn("AppConfig.getCallBaseUrl()", src)
        self.assertIn("public void callProgram(", src)
        self.assertNotIn("jmsConsumer", src)
        self.assertNotIn("jakarta.jms", src)

    def test_stub_executor_interface_has_call_program_default(self):
        src = STUB_EXECUTOR_JAVA.format(**self.fmt)
        self.assertIn("default void callProgram(", src)


class TestGenCallJava(unittest.TestCase):
    def test_mq_calls_unchanged(self):
        for op, expected in [
            ("MQOPEN", "stubs.mqOpen("),
            ("MQGET", "stubs.mqGet("),
            ("MQPUT1", "stubs.mqPut1("),
            ("MQCLOSE", "stubs.mqClose("),
        ]:
            cb = _FakeBuilder()
            _gen_call_java(cb, _make_call(op))
            self.assertEqual(len(cb.lines), 1)
            self.assertIn(expected, cb.lines[0], f"{op}: {cb.lines[0]}")

    def test_non_mq_call_emits_callProgram(self):
        cb = _FakeBuilder()
        _gen_call_java(cb, _make_call("CUSTAPI"))
        self.assertEqual(len(cb.lines), 1)
        self.assertIn("stubs.callProgram(", cb.lines[0])
        self.assertIn('"CUSTAPI"', cb.lines[0])
        # No USING -> empty input list.
        self.assertIn("emptyList()", cb.lines[0])

    def test_call_with_using_threads_input_vars(self):
        cb = _FakeBuilder()
        stmt = _make_call(
            "CUSTAPI",
            raw_text="CALL 'CUSTAPI' USING WS-REQ WS-RESP",
            using=["WS-REQ", "WS-RESP"],
        )
        _gen_call_java(cb, stmt)
        self.assertIn("stubs.callProgram(", cb.lines[0])
        self.assertIn('"WS-REQ"', cb.lines[0])
        self.assertIn('"WS-RESP"', cb.lines[0])
        self.assertIn("java.util.List.of(", cb.lines[0])


class TestExtractCallUsing(unittest.TestCase):
    def test_uses_attribute_list(self):
        stmt = _make_call("FOO", using=["A", "B"])
        self.assertEqual(_extract_call_using_vars(stmt), ["A", "B"])

    def test_falls_back_to_raw_text_parse(self):
        stmt = _make_call("FOO", raw_text="CALL 'FOO' USING WS-A WS-B WS-C.")
        self.assertEqual(_extract_call_using_vars(stmt), ["WS-A", "WS-B", "WS-C"])

    def test_returns_empty_when_no_using(self):
        stmt = _make_call("FOO", raw_text="CALL 'FOO'")
        self.assertEqual(_extract_call_using_vars(stmt), [])


class TestGenerateProjectEndToEnd(unittest.TestCase):
    """End-to-end: feed a small AST through generate_java_project and verify
    the on-disk artifacts (POM, docker-compose, runtime files, IT, WireMock
    mappings, seed SQL) come out right."""

    def _make_program(self) -> Program:
        # One paragraph, one CALL statement to a non-MQ program.
        para = Paragraph(
            name="0100-MAIN",
            line_start=0,
            line_end=0,
            statements=[
                _make_call("CUSTAPI", raw_text="CALL 'CUSTAPI' USING WS-REQ"),
            ],
        )
        return Program(program_id="DEMO01", paragraphs=[para])

    def _make_test_store_jsonl(self, path: Path) -> None:
        cases = [
            {
                "id": "abc12345",
                "input_state": {"WS-REQ": "X"},
                "stub_outcomes": {
                    "CALL:CUSTAPI": [[["WS-RESP", "OK"], ["WS-CODE", 0]]],
                },
                "stub_defaults": {},
                "paragraphs_covered": ["0100-MAIN"],
                "branches_covered": [],
                "layer": 1,
                "target": "0100-MAIN",
            }
        ]
        with path.open("w", encoding="utf-8") as fh:
            for c in cases:
                fh.write(json.dumps(c) + "\n")

    def test_generates_full_project_with_wiremock_and_seeds(self):
        prog = self._make_program()
        with TemporaryDirectory() as td:
            store = Path(td) / "tests.jsonl"
            self._make_test_store_jsonl(store)
            out = Path(td) / "out"
            generate_java_project(
                prog,
                output_dir=str(out),
                test_store_path=str(store),
                copybook_paths=None,
                docker=True,
                integration_tests=True,
            )

            compose = (out / "docker-compose.yml").read_text()
            self.assertIn("rabbitmq:3-management", compose)
            self.assertIn("wiremock/wiremock", compose)

            pom = (out / "pom.xml").read_text()
            self.assertIn("amqp-client", pom)
            self.assertNotIn("artemis-jakarta-client", pom)

            it_pom = (out / "integration-tests" / "pom.xml").read_text()
            self.assertIn("amqp-client", it_pom)
            self.assertNotIn("artemis-jakarta-client", it_pom)

            # WireMock mapping for the CALL was emitted.
            wm = out / "wiremock" / "mappings" / "abc12345"
            self.assertTrue(wm.exists(), f"missing wiremock dir at {wm}")
            files = list(wm.glob("*custapi.json"))
            self.assertEqual(len(files), 1)
            mapping = json.loads(files[0].read_text())
            self.assertEqual(mapping["request"]["urlPattern"], "/custapi")
            self.assertEqual(mapping["response"]["jsonBody"]["WS-RESP"], "OK")

            # Generated SectionMain.java references callProgram.
            section_files = list((out / "src" / "main" / "java" / "com"
                                  / "specter" / "generated").glob("Section*.java"))
            self.assertTrue(section_files)
            section_src = "\n".join(f.read_text() for f in section_files)
            self.assertIn("stubs.callProgram(", section_src)


if __name__ == "__main__":
    unittest.main()
