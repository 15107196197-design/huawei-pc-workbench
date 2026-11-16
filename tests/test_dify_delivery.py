"""Regression checks for the authenticated Dify callback delivery."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

import yaml

from dify import build_delivery, validate_delivery


class DifyDeliveryAuthenticationTests(unittest.TestCase):
    def test_all_delivered_graphs_preserve_secret_only_custom_header_authentication(self):
        for filename in ["huawei-pc-chatflow.yml", "ima-search-workflow.yml", "quote-engine-workflow.yml", "verify-workflow.yml"]:
            with self.subTest(filename=filename):
                nodes = validate_delivery.validate_graph(validate_delivery.HERE / filename)
                requests = [node["data"] for node in nodes.values() if node["data"]["type"] == "http-request"]
                self.assertEqual(len(requests), 1)

    def test_missing_literal_reserved_or_duplicated_callback_headers_fail_validation(self):
        valid = build_delivery.http_node("/api/tools/quotes")
        for invalid in [
            {"headers": "Content-Type: application/json"},
            {"headers": "Content-Type: application/json\nX-Tool-Token: synthetic-literal-secret"},
            {"headers": "Content-Type: application/json\nAuthorization: Bearer {{#env.TOOL_TOKEN#}}"},
            {"headers": valid["headers"] + "\nx-tool-token: {{#env.TOOL_TOKEN#}}"},
            {"authorization": {"type": "api-key", "config": {"type": "bearer", "api_key": "{{#env.TOOL_TOKEN#}}"}}},
            {"url": "https://example.invalid?token={{#env.TOOL_TOKEN#}}"},
        ]:
            with self.subTest(invalid=invalid), self.assertRaises(AssertionError):
                validate_delivery.validate_http_auth(valid | invalid)

    def test_plaintext_or_nonsecret_exported_tool_token_fails_graph_validation(self):
        delivered = yaml.safe_load((validate_delivery.HERE / "huawei-pc-chatflow.yml").read_text())
        for changes in [{"value": "synthetic-literal-secret"}, {"value_type": "string"}]:
            invalid = deepcopy(delivered)
            token = next(value for value in invalid["workflow"]["environment_variables"] if value["name"] == "TOOL_TOKEN")
            token.update(changes)
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "invalid.yml"
                path.write_text(yaml.safe_dump(invalid, allow_unicode=True))
                with self.subTest(changes=changes), self.assertRaises(AssertionError):
                    validate_delivery.validate_graph(path)

    def test_tool_secret_cannot_be_routed_into_code_parameters_or_reply_templates(self):
        delivered = yaml.safe_load((validate_delivery.HERE / "huawei-pc-chatflow.yml").read_text())
        for leak in ["selector", "template"]:
            invalid = deepcopy(delivered)
            data = next(node["data"] for node in invalid["workflow"]["graph"]["nodes"] if node["id"] == "payload")
            if leak == "selector":
                data["variables"].append({"variable": "secret", "value_selector": ["env", "TOOL_TOKEN"]})
            else:
                data["desc"] = "{{#env.TOOL_TOKEN#}}"
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "invalid.yml"
                path.write_text(yaml.safe_dump(invalid, allow_unicode=True))
                with self.subTest(leak=leak), self.assertRaises(AssertionError):
                    validate_delivery.validate_graph(path)

    def test_openapi_formats_match_and_all_operations_require_the_custom_header(self):
        validate_delivery.validate_openapi(validate_delivery.HERE / "tools.openapi.yml", validate_delivery.HERE / "tools.openapi.json")
        valid = build_delivery.openapi()
        insecure = deepcopy(valid)
        insecure["paths"]["/api/tools/search"]["post"]["security"] = []
        reserved = deepcopy(valid)
        reserved["components"]["securitySchemes"]["toolToken"] = {"type": "http", "scheme": "bearer"}
        for spec in [insecure, reserved]:
            with tempfile.TemporaryDirectory() as directory:
                yml, js = Path(directory) / "tools.yml", Path(directory) / "tools.json"
                yml.write_text(yaml.safe_dump(spec, allow_unicode=True))
                js.write_text(json.dumps(spec, ensure_ascii=False))
                with self.assertRaises(AssertionError):
                    validate_delivery.validate_openapi(yml, js)


if __name__ == "__main__":
    unittest.main()
