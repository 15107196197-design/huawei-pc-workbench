"""Eight focused runtime regressions; synthetic evidence and no external calls."""

import base64
from copy import deepcopy
import hashlib
import importlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from huawei_agent import providers, settings, store, workflow
from huawei_agent.validation import validate
from test_workflow import content_task


api = importlib.import_module("huawei_agent.app")


class RuntimeEdgeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.config = dict(settings.DEFAULTS, deepseek_api_key="synthetic-not-a-real-key", tool_token="synthetic-bearer-token")
        for module, field, replacement in [
            (store, "DATA", Path(temporary.name)),
            (workflow, "load_settings", lambda: self.config),
            (api, "load_settings", lambda: self.config),
            (api, "dify_ready", lambda: False),
            (api, "configured", lambda: {key: False for key in ["ima", "dify", "deepseek", "vision", "image", "search"]}),
        ]:
            patcher = patch.object(module, field, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(providers.httpx, "AsyncClient", side_effect=AssertionError("本测试禁止外部HTTP调用"))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(workflow.LOCKS.clear)

    def checks(self, task):
        return validate(task["draft"], task["facts"], task["assets"], task["quotes"], task["brief"]["platform"])

    async def test_explicit_budget_statements_are_not_mistaken_for_checkout_prices(self):
        for budget in ["用户自述预算6000元。", "先按6000元左右预算了解选择。"]:
            with self.subTest(budget=budget):
                task = content_task()
                task["draft"]["body"] += budget
                self.assertFalse(any(check["category"] == "价格" and check["status"] == "blocked" for check in self.checks(task)))

    async def test_budget_context_does_not_exempt_an_actual_checkout_price_claim(self):
        task = content_task()
        task["draft"]["body"] += "预算内到手价￥6000。"
        self.assertTrue(any(check["category"] == "价格" and check["status"] == "blocked" for check in self.checks(task)))

    async def test_verified_quote_of_a_different_product_cannot_support_current_product_amount(self):
        task = content_task()
        task["draft"]["body"] += "这款产品确定到手价6000元。"
        task["quotes"] = {"quotes": [{"offer_id": "other-offer", "product_name": "Synthetic Model B", "status": "verified", "checkout_amount": "6000.00"}],
                          "best": [{"offer_id": "other-offer", "checkout_amount": "6000.00"}]}
        self.assertTrue(any(check["category"] == "价格" and check["status"] == "blocked" for check in self.checks(task)))

    async def test_semantic_failure_triggers_one_repair_and_a_fresh_review(self):
        task = content_task()
        initial = deepcopy(task["draft"])
        initial["body"] = "屏幕为15英寸。广告，AI辅助内容。"
        repaired = deepcopy(task["draft"])
        repaired["title"] = "已修正的合成文案"
        responses = [initial, {"passed": False, "issues": ["原句15英寸与证据14英寸不符"], "notes": []},
                     repaired, {"passed": True, "issues": [], "notes": []}]
        with patch.object(workflow, "json_chat", new_callable=AsyncMock, side_effect=responses) as model:
            result = await workflow.generate_task(task)
        self.assertEqual(model.await_count, 4)
        self.assertEqual(result["repair_record"]["attempts"], 1)
        self.assertEqual(result["draft"]["title"], repaired["title"])
        self.assertEqual(result["status"], "draft")
        self.assertFalse(any(check["status"] == "blocked" for check in result["checks"]))
        self.assertTrue(model.await_args_list[2].args[1]["issues"])

    async def test_repair_remains_bounded_and_preserves_persistent_blocked_findings(self):
        task = content_task()
        invalid = deepcopy(task["draft"])
        invalid["body"] = "屏幕为15英寸。广告，AI辅助内容。"
        failure = {"passed": False, "issues": ["15英寸没有资料支持"], "notes": []}
        with patch.object(workflow, "json_chat", new_callable=AsyncMock,
                          side_effect=[deepcopy(invalid), deepcopy(failure), deepcopy(invalid), deepcopy(failure)]) as model:
            result = await workflow.generate_task(task)
        self.assertEqual(model.await_count, 4)
        self.assertEqual(result["repair_record"]["attempts"], 1)
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(any(check["category"] == "语义核验" and check["status"] == "blocked" for check in result["checks"]))

    async def test_optional_review_notes_do_not_become_issues_or_trigger_a_repair(self):
        task = content_task()
        responses = [deepcopy(task["draft"]), {"passed": True, "issues": [], "notes": ["可选补充未在正文使用的其他事实"]}]
        with patch.object(workflow, "json_chat", new_callable=AsyncMock, side_effect=responses) as model:
            result = await workflow.generate_task(task)
        self.assertEqual(model.await_count, 2)
        self.assertEqual(result["status"], "draft")
        self.assertNotIn("repair_record", result)
        self.assertFalse(any(check["category"] == "语义核验" and check["status"] == "blocked" for check in result["checks"]))

    def enable_login(self):
        password = "synthetic-login-password"
        salt, iterations = bytes.fromhex("00112233445566778899aabbccddeeff"), 1000
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations).hex()
        self.config.update(studio_username="synthetic-operator", studio_password_hash=f"pbkdf2_sha256${iterations}${salt.hex()}${digest}")
        credentials = base64.b64encode((self.config["studio_username"] + ":" + password).encode()).decode()
        return {"Authorization": "Basic " + credentials}

    async def test_operator_basic_login_protects_settings_and_accepts_only_correct_credentials(self):
        headers = self.enable_login()
        with patch.object(api.knowledge, "connect", new_callable=AsyncMock), \
             patch.object(api, "save_settings") as save, \
             TestClient(api.app, raise_server_exceptions=False) as client:
            for request_headers in [{}, {"Authorization": "Basic " + base64.b64encode(b"synthetic-operator:wrong").decode()}]:
                denied = client.post("/api/settings", json={"text_model": "synthetic"}, headers=request_headers)
                self.assertEqual(denied.status_code, 401)
                self.assertIn("Basic", denied.headers["WWW-Authenticate"])
            save.assert_not_called()
            allowed = client.post("/api/settings", json={"text_model": "synthetic"}, headers=headers)
            self.assertEqual(allowed.status_code, 200)
            save.assert_called_once_with({"text_model": "synthetic"})
            status = client.get("/api/status", headers=headers)
            self.assertEqual(status.status_code, 200)
            self.assertEqual(status.json()["user"]["name"], "synthetic-operator")
            self.assertNotIn(self.config["studio_password_hash"], status.text)

    async def test_operator_login_does_not_replace_or_block_tool_bearer_authentication(self):
        basic_headers = self.enable_login()
        with patch.object(api.knowledge, "connect", new_callable=AsyncMock), \
             TestClient(api.app, raise_server_exceptions=False) as client:
            body = {"region": "杭州", "offers": []}
            self.assertEqual(client.post("/api/tools/quotes", json=body).status_code, 401)
            self.assertEqual(client.post("/api/tools/quotes", json=body, headers=basic_headers).status_code, 401)
            valid = client.post("/api/tools/quotes", json=body, headers={"Authorization": "Bearer " + self.config["tool_token"]})
            self.assertEqual(valid.status_code, 200)


if __name__ == "__main__":
    unittest.main()
