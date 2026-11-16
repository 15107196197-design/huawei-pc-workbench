"""Local API regression tests using isolated SQLite/files and mocked providers."""

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import importlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
import zipfile

from fastapi.testclient import TestClient

from huawei_agent import exports, media, settings, store, workflow
from huawei_agent.pricing import calculate_quotes
from test_workflow import content_task


api = importlib.import_module("huawei_agent.app")
TOKEN = "synthetic-tool-token-not-a-real-key"


def synthetic_offer(expired=False):
    current = datetime.now(timezone.utc)
    return {"id": "offer-a", "channel": "合成渠道", "seller": "合成商家", "sku_key": "SYNTHETIC-A",
            "product_name": "Synthetic Model A", "condition": "new_unactivated", "service_key": "invoice-warranty-1y",
            "base_price": "9999", "source_url": "https://example.invalid/offer",
            "observed_at": (current - timedelta(hours=2)).isoformat(),
            "expires_at": (current + timedelta(hours=-1 if expired else 1)).isoformat(),
            "verified": True, "in_stock": True, "currency": "CNY", "discounts": []}


class APITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        for module in [settings, store, media, exports, api]:
            patcher = patch.object(module, "DATA", self.directory)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.configuration = dict(settings.DEFAULTS, tool_token=TOKEN)
        for module in [api, workflow]:
            patcher = patch.object(module, "load_settings", return_value=self.configuration)
            patcher.start()
            self.addCleanup(patcher.stop)
        flags = {name: False for name in ["ima", "dify", "deepseek", "vision", "image", "search"]}
        patcher = patch.object(api, "configured", return_value=flags)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in ["asset_bytes", "retrieve", "connect"]:
            patcher = patch.object(api.knowledge, name, new_callable=AsyncMock,
                                   side_effect=AssertionError("本地集成测试禁止外部资料调用"))
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = TestClient(api.app, raise_server_exceptions=False)
        self.addCleanup(self.client.close)
        self.addCleanup(workflow.LOCKS.clear)

    def seed(self):
        return content_task()

    def test_create_reopen_and_local_owner_boundary(self):
        response = self.client.post("/api/tasks", json={"title": "合成测试"})
        self.assertEqual(response.status_code, 200)
        task_id = response.json()["id"]
        self.assertEqual(self.client.get("/api/tasks/" + task_id).json()["title"], "合成测试")
        other = store.create_task("另一个身份", owner="preview:other")
        self.assertEqual(self.client.get("/api/tasks/" + other["id"]).status_code, 404)

    def test_product_brief_change_invalidates_old_evidence_and_blocks_export(self):
        task = self.seed()
        response = self.client.patch(f"/api/tasks/{task['id']}/brief", json={"brief": {"product": "Synthetic Model B"}})
        self.assertEqual(response.status_code, 200)
        updated = response.json()
        self.assertEqual(updated["facts"], [])
        self.assertEqual(updated["assets"], [])
        self.assertTrue(any(c["status"] == "blocked" for c in updated["checks"]))
        self.assertEqual(self.client.get(f"/api/tasks/{task['id']}/export?format=txt").status_code, 422)

    def test_post_brief_saves_all_fields_and_reopens_without_external_calls(self):
        task = self.client.post("/api/tasks", json={}).json()
        brief = {"audience": "大学新生", "scenario": "school", "platform": "moments",
                 "goal": "帮助核对工科课程软件", "product": "Synthetic Model A", "budget": "6000–8000 元",
                 "region": "杭州", "purchase_stage": "对比选型", "software": "课程软件待核对",
                 "channels": ["华为商城", "线下门店"]}
        response = self.client.post(f"/api/tasks/{task['id']}/brief", json={"brief": brief})
        self.assertEqual(response.status_code, 200)
        updated = response.json()
        self.assertGreater(updated["revision"], task["revision"])
        reopened = self.client.get(f"/api/tasks/{task['id']}").json()
        for key, value in brief.items():
            self.assertEqual(reopened["brief"][key], value)
        self.assertTrue(reopened["needs_regeneration"])

    def test_post_draft_keeps_revision_conflict_protection(self):
        task = self.seed()
        changed = deepcopy(task["draft"])
        changed["title"] = "浏览器保存后的标题"
        path = f"/api/tasks/{task['id']}/draft"
        payload = {"revision": task["revision"], "draft": changed}
        response = self.client.post(path, json=payload)
        self.assertEqual(response.status_code, 200)
        changed["title"] = "过期提交不得覆盖"
        self.assertEqual(self.client.post(path, json=payload).status_code, 422)
        self.assertEqual(self.client.get(f"/api/tasks/{task['id']}").json()["draft"]["title"], "浏览器保存后的标题")

    def test_manual_text_edit_preserves_omitted_fact_references(self):
        task = self.seed()
        changed = deepcopy(task["draft"])
        changed["title"] = "人工修改后的标题"
        del changed["fact_ids"]
        response = self.client.put(f"/api/tasks/{task['id']}/draft", json={"revision": task["revision"], "draft": changed})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["draft"]["fact_ids"], ["fact-a"])
        self.assertGreater(response.json()["revision"], task["revision"])
        self.assertEqual(self.client.get(f"/api/tasks/{task['id']}").json()["draft"]["title"], changed["title"])

    def test_manual_explicit_removal_of_fact_references_is_blocked(self):
        task = self.seed()
        changed = deepcopy(task["draft"])
        changed["fact_ids"] = []
        response = self.client.put(f"/api/tasks/{task['id']}/draft", json={"revision": task["revision"], "draft": changed})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "blocked")

    def test_stale_revision_is_rejected_without_overwriting_newer_content(self):
        task = self.seed()
        newer = deepcopy(task)
        newer["draft"]["title"] = "已保存的新标题"
        store.save_task(newer, "更新")
        response = self.client.put(f"/api/tasks/{task['id']}/draft", json={"revision": task["revision"], "draft": task["draft"]})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(store.get_task(task["id"])["draft"]["title"], "已保存的新标题")

    def test_malformed_reference_field_returns_validation_error_not_server_error(self):
        for changes in [{"images": "not-a-list"}, {"images": ["not-an-object"]}, {"fact_ids": [None]}]:
            with self.subTest(changes=changes):
                task = self.seed()
                changed = task["draft"] | changes
                response = self.client.put(f"/api/tasks/{task['id']}/draft", json={"revision": task["revision"], "draft": changed})
                self.assertEqual(response.status_code, 422)

    def test_tool_bearer_is_required_and_not_accepted_as_query_argument(self):
        for headers in [{}, {"Authorization": "Bearer wrong"}]:
            response = self.client.post("/api/tools/quotes?token=" + TOKEN, json={"region": "杭州", "offers": []}, headers=headers)
            self.assertEqual(response.status_code, 401)
        response = self.client.post("/api/tools/quotes", json={"region": "杭州", "offers": []}, headers={"Authorization": "Bearer " + TOKEN})
        self.assertEqual(response.status_code, 200)

    def test_dify_existing_task_requires_bound_context_signature(self):
        task = self.seed()
        path = "/api/dify/execute"
        headers = {"Authorization": "Bearer " + TOKEN}
        for changes in [{"context_token": "wrong", "user": "local"},
                        {"context_token": hmac.new(TOKEN.encode(), ("other:" + task["id"]).encode(), hashlib.sha256).hexdigest(), "user": "other"}]:
            response = self.client.post(path, json={"task_id": task["id"], "action": "verify"} | changes, headers=headers)
            self.assertEqual(response.status_code, 403)
        signature = hmac.new(TOKEN.encode(), ("local:" + task["id"]).encode(), hashlib.sha256).hexdigest()
        response = self.client.post(path, json={"task_id": task["id"], "action": "verify", "user": "local", "context_token": signature}, headers=headers)
        self.assertEqual(response.status_code, 200)

    def test_dify_brief_change_uses_same_evidence_invalidation_as_ui(self):
        task = self.seed()
        signature = hmac.new(TOKEN.encode(), ("local:" + task["id"]).encode(), hashlib.sha256).hexdigest()
        response = self.client.post("/api/dify/execute", headers={"Authorization": "Bearer " + TOKEN},
                                   json={"task_id": task["id"], "action": "verify", "user": "local", "context_token": signature,
                                         "brief": {"product": "Synthetic Model B"}})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["result"]["facts"], [])
        self.assertEqual(response.json()["result"]["assets"], [])
        self.assertEqual(response.json()["status"], "blocked")

    def test_dify_signature_cannot_be_replayed_for_another_task(self):
        original, target = self.seed(), self.seed()
        signature = hmac.new(TOKEN.encode(), ("local:" + original["id"]).encode(), hashlib.sha256).hexdigest()
        response = self.client.post("/api/dify/execute", headers={"Authorization": "Bearer " + TOKEN},
                                   json={"task_id": target["id"], "action": "verify", "user": "local", "context_token": signature})
        self.assertEqual(response.status_code, 403)

    def test_quotes_endpoint_does_not_accept_forged_past_clock(self):
        task = self.seed()
        offer = synthetic_offer(expired=True)
        fake_now = (datetime.now(timezone.utc) - timedelta(hours=1, minutes=30)).isoformat()
        response = self.client.post(f"/api/tasks/{task['id']}/quotes", json={"offers": [offer], "buyer": {"kind": "personal"}, "now": fake_now})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["quotes"]["quotes"][0]["status"], "excluded")

    def test_export_rechecks_expired_price_with_currency_prefix(self):
        task = self.seed()
        task["offers"] = [synthetic_offer(expired=True)]
        task["buyer"] = {"kind": "personal"}
        task["quotes"] = {"best": [{"checkout_amount": "9999.00"}], "quotes": []}
        task["draft"]["body"] += " 确定到手价¥9999。"
        task = store.save_task(task, "保存将到期的报价")
        self.assertEqual(self.client.get(f"/api/tasks/{task['id']}/export?format=txt").status_code, 422)

    def test_export_cannot_discard_existing_semantic_block_when_rechecking_quotes(self):
        task = self.seed()
        task["offers"] = [synthetic_offer()]
        task["buyer"] = {"kind": "personal"}
        task["quotes"] = calculate_quotes({"region": "杭州", "offers": task["offers"], "buyer": task["buyer"]})
        task["checks"] = [{"category": "语义核验", "status": "blocked", "message": "已发现正文遗漏适用限定，尚未修正"}]
        task["status"] = "blocked"
        task = store.save_task(task, "记录阻断")
        self.assertEqual(self.client.get(f"/api/tasks/{task['id']}/export?format=txt").status_code, 422)
        self.assertEqual(self.client.get(f"/api/tasks/{task['id']}/export?format=json").status_code, 200)

    def test_restoring_blocked_history_cannot_turn_it_into_publishable_content(self):
        task = self.seed()
        task["draft"]["body"] += " 本产品是全网最低。"
        task["checks"] = [{"category": "营销合规", "status": "blocked", "message": "禁止无依据最低价"}]
        task = store.save_task(task, "存在阻断的历史版本")
        version_id = task["versions"][0]["id"]
        task["draft"]["body"] = "已修正的草稿，广告，AI辅助内容。"
        task["checks"] = [{"category": "审核", "status": "warning", "message": "合成草稿"}]
        store.save_task(task, "后续版本")
        response = self.client.post(f"/api/tasks/{task['id']}/versions/{version_id}/restore")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get(f"/api/tasks/{task['id']}/export?format=txt").status_code, 422)

    def test_restored_price_version_is_revalidated_against_current_time(self):
        task = self.seed()
        task["offers"] = [synthetic_offer(expired=True)]
        task["buyer"] = {"kind": "personal"}
        former_now = (datetime.now(timezone.utc) - timedelta(hours=1, minutes=30)).isoformat()
        task["quotes"] = calculate_quotes({"offers": task["offers"], "region": "杭州", "buyer": task["buyer"], "now": former_now})
        self.assertTrue(task["quotes"]["best"])
        task["draft"]["body"] += " 当时确定到手价9999元。"
        task = store.save_task(task, "历史有效报价")
        version_id = task["versions"][0]["id"]
        task["offers"], task["quotes"] = [], {"quotes": [], "best": []}
        store.save_task(task, "后续修改")
        response = self.client.post(f"/api/tasks/{task['id']}/versions/{version_id}/restore")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get(f"/api/tasks/{task['id']}/export?format=txt").status_code, 422)

    def test_blocked_export_only_allows_audit_json_and_report(self):
        task = self.seed()
        task["checks"] = [{"category": "事实", "status": "blocked", "message": "测试阻断"}]
        task = store.save_task(task, "阻断")
        for format in ["txt", "html", "zip", "png", "pdf"]:
            with self.subTest(format=format):
                self.assertEqual(self.client.get(f"/api/tasks/{task['id']}/export?format={format}").status_code, 422)
        for format in ["json", "report"]:
            self.assertEqual(self.client.get(f"/api/tasks/{task['id']}/export?format={format}").status_code, 200)

    def test_origin_guard_rejects_cross_origin_writes(self):
        response = self.client.post("/api/tasks", json={}, headers={"Origin": "https://unrelated.invalid"})
        self.assertEqual(response.status_code, 403)

    def test_export_has_four_parts_and_omits_raw_evidence_and_secret_fields(self):
        task = self.seed()
        task["evidence"] = [{"excerpt": "RAW_EVIDENCE_MUST_STAY_PRIVATE"}]
        task["deepseek_api_key"] = "SYNTHETIC_SECRET_MUST_NOT_EXPORT"
        task = store.save_task(task, "保留内部资料")
        response = self.client.get(f"/api/tasks/{task['id']}/export?format=json")
        self.assertEqual(response.status_code, 200)
        report = response.json()
        for section in ["一、场景判断", "二、知识库依据", "三、图文软文", "四、核验结果"]:
            self.assertIn(section, report)
        self.assertNotIn("RAW_EVIDENCE_MUST_STAY_PRIVATE", response.text)
        self.assertNotIn("SYNTHETIC_SECRET_MUST_NOT_EXPORT", response.text)
        self.assertNotIn(task["id"], response.text)

    def test_html_export_escapes_author_content_and_unsafe_source_links(self):
        task = self.seed()
        task["draft"]["title"] = "<script>alert(1)</script>"
        task["assets"][0]["source_url"] = "javascript:alert(1)"
        task = store.save_task(task, "转义测试")
        response = self.client.get(f"/api/tasks/{task['id']}/export?format=html")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("<script>", response.text)
        self.assertIn("&lt;script&gt;", response.text)
        self.assertNotIn("javascript:", response.text)

    def test_zip_export_includes_actual_selected_original_and_relative_html_reference(self):
        from PIL import Image
        task = self.seed()
        image = Image.new("RGB", (12, 8), "white")
        output = io.BytesIO()
        image.save(output, "PNG")
        raw = output.getvalue()
        async def cached_asset(asset_id):
            (self.directory / "media").mkdir(exist_ok=True)
            (self.directory / "media" / (asset_id + ".image")).write_bytes(raw)
            return raw, "image/png"
        with patch.object(api.knowledge, "asset_bytes", side_effect=cached_asset) as loader:
            response = self.client.get(f"/api/tasks/{task['id']}/export?format=zip")
        self.assertEqual(response.status_code, 200)
        loader.assert_awaited_once_with("a" * 24)
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            pictures = [name for name in archive.namelist() if name.startswith("media/")]
            self.assertEqual(len(pictures), 1)
            self.assertEqual(archive.read(pictures[0]), raw)
            self.assertIn(pictures[0], archive.read("index.html").decode())
            self.assertIn("四、核验结果", archive.read("成稿与核验.txt").decode())


class ConcurrentWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_generate_reads_current_task_after_acquiring_task_lock(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(store, "DATA", Path(directory)), \
             patch.object(api, "configured", return_value={"dify": False}):
            task = content_task()
            entered = asyncio.Event()
            release = asyncio.Event()
            observations = []
            async def fake_generate(incoming, instruction="", refresh=False):
                observations.append((incoming["revision"], store.get_task(incoming["id"])["revision"]))
                if len(observations) == 1:
                    entered.set()
                    await release.wait()
                return store.save_task(incoming, "并发测试")
            with patch.object(api, "generate_task", side_effect=fake_generate):
                first = asyncio.create_task(api.generate(task["id"], {}))
                await entered.wait()
                second = asyncio.create_task(api.generate(task["id"], {}))
                await asyncio.sleep(0)
                release.set()
                await asyncio.gather(first, second)
            self.assertEqual(observations[1][0], observations[1][1], "第二次生成必须在锁内读取第一轮保存后的任务")
        workflow.LOCKS.clear()

    async def test_dify_action_reads_current_task_after_acquiring_task_lock(self):
        self.addCleanup(workflow.LOCKS.clear)
        with tempfile.TemporaryDirectory() as directory, patch.object(store, "DATA", Path(directory)), \
             patch.object(api, "load_settings", return_value={"tool_token": TOKEN}):
            task = content_task()
            entered, release = asyncio.Event(), asyncio.Event()
            observations = []
            async def fake_verify(incoming):
                observations.append((incoming["revision"], store.get_task(incoming["id"])["revision"]))
                if len(observations) == 1:
                    entered.set()
                    await release.wait()
                return incoming
            signature = hmac.new(TOKEN.encode(), ("local:" + task["id"]).encode(), hashlib.sha256).hexdigest()
            payload = {"task_id": task["id"], "action": "verify", "user": "local", "context_token": signature}
            with patch.object(api, "verify_task", side_effect=fake_verify):
                first = asyncio.create_task(api.dify_execute(dict(payload)))
                await entered.wait()
                second = asyncio.create_task(api.dify_execute(dict(payload)))
                await asyncio.sleep(0)
                release.set()
                await asyncio.gather(first, second)
            self.assertEqual(observations[1][0], observations[1][1], "Dify并发动作必须在锁内读取最新任务")


if __name__ == "__main__":
    unittest.main()
