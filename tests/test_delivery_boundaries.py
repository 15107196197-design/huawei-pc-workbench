"""Delivery/state regressions across saved versions, copy, export and poster repair."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from huawei_agent import exports, media, providers, settings, store, workflow
from huawei_agent.pricing import calculate_quotes
from test_api import synthetic_offer
from test_workflow import content_task


api = importlib.import_module("huawei_agent.app")


class DeliveryBoundaryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.config = dict(settings.DEFAULTS)
        for module in [settings, store, exports, media, api]:
            patcher = patch.object(module, "DATA", Path(temporary.name))
            patcher.start()
            self.addCleanup(patcher.stop)
        for module in [api, workflow]:
            patcher = patch.object(module, "load_settings", return_value=self.config)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(api, "configured", return_value={name: False for name in ["ima", "dify", "deepseek", "vision", "image", "search"]})
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.object(api, "dify_ready", return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.object(providers.httpx, "AsyncClient", side_effect=AssertionError("状态回归测试禁止任何外部HTTP调用"))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = TestClient(api.app, raise_server_exceptions=False)
        self.addCleanup(self.client.close)
        self.addCleanup(workflow.LOCKS.clear)

    def priced_task(self):
        task = content_task()
        task["offers"] = [synthetic_offer()]
        task["buyer"] = {"kind": "personal"}
        task["quotes"] = calculate_quotes({"offers": task["offers"], "region": "杭州", "buyer": task["buyer"]})
        task["draft"]["body"] += "本型号当前结算价9999元。"
        task["semantic_review"] = {"passed": True, "issues": [], "notes": []}
        return store.save_task(task, "保存当前有效报价")

    def future_clock(self):
        frozen = datetime.now(timezone.utc) + timedelta(hours=2)
        class FutureClock(datetime):
            @classmethod
            def now(cls, tz=None):
                return frozen.astimezone(tz) if tz else frozen.replace(tzinfo=None)
        return patch("huawei_agent.pricing.datetime", FutureClock)

    async def test_restore_preserves_historical_block_and_current_conversation_without_revision_rollback(self):
        task = content_task()
        task["messages"] = [{"role": "user", "content": "历史问题"}]
        task["checks"] = [{"category": "视觉核验", "status": "blocked", "message": "历史海报遮挡产品接口，尚未修正"}]
        task = store.save_task(task, "带实际阻断的历史内容")
        version_id = task["versions"][0]["id"]
        task["checks"] = [{"category": "核验", "status": "pass", "message": "后续版本"}]
        task["messages"].append({"role": "user", "content": "当前补充需求需要保留"})
        current = store.save_task(task, "后续讨论")
        restored = store.restore(task["id"], version_id)
        reopened = store.get_task(task["id"])
        self.assertGreater(restored["revision"], current["revision"])
        self.assertEqual(reopened["messages"], current["messages"])
        self.assertEqual(reopened["status"], "blocked")
        self.assertTrue(any(check["status"] == "blocked" and "遮挡产品接口" in check["message"] for check in reopened["checks"]))
        self.assertEqual(self.client.get(f"/api/tasks/{task['id']}/copy").status_code, 422)
        self.assertEqual(self.client.get(f"/api/tasks/{task['id']}/export?format=txt").status_code, 422)
        audit = self.client.get(f"/api/tasks/{task['id']}/export?format=json")
        self.assertEqual(audit.status_code, 200)
        self.assertIn("遮挡产品接口", audit.text)

    async def test_foreign_version_restore_does_not_change_target_task_state(self):
        first, second = content_task(), content_task()
        foreign_version = first["versions"][0]["id"]
        before = store.get_task(second["id"])
        result = self.client.post(f"/api/tasks/{second['id']}/versions/{foreign_version}/restore")
        self.assertEqual(result.status_code, 404)
        self.assertEqual(store.get_task(second["id"]), before)

    async def test_copy_outputs_article_with_draft_notice_and_never_mutates_saved_state(self):
        task = content_task()
        task["draft"]["tags"] = ["华为电脑", "#移动办公"]
        task["evidence"] = [{"excerpt": "原始工作资料不应混入复制正文"}]
        task = store.save_task(task, "准备复制")
        before = store.get_task(task["id"])
        result = self.client.get(f"/api/tasks/{task['id']}/copy")
        self.assertEqual(result.status_code, 200)
        text = result.json()["text"]
        for field in ["title", "lead", "body", "cta"]:
            self.assertIn(task["draft"][field], text)
        self.assertIn("#华为电脑 #移动办公", text)
        self.assertIn("广告", text)
        self.assertIn("待复核草稿", text)
        self.assertNotIn("原始工作资料不应混入复制正文", text)
        self.assertNotIn(task["id"], text)
        self.assertEqual(store.get_task(task["id"]), before)

    async def test_brief_change_blocks_copy_and_delivery_even_if_old_article_is_still_visible(self):
        task = content_task()
        change = self.client.patch(f"/api/tasks/{task['id']}/brief", json={"brief": {"scenario": "school"}})
        self.assertEqual(change.status_code, 200)
        self.assertTrue(change.json()["needs_regeneration"])
        self.assertTrue(change.json()["draft"])
        self.assertEqual(self.client.get(f"/api/tasks/{task['id']}/copy").status_code, 422)
        self.assertEqual(self.client.get(f"/api/tasks/{task['id']}/export?format=html").status_code, 422)
        self.assertEqual(self.client.get(f"/api/tasks/{task['id']}/export?format=report").status_code, 200)

    async def test_time_transition_revokes_copy_and_export_but_audit_shows_current_exclusion(self):
        task = self.priced_task()
        self.assertEqual(self.client.get(f"/api/tasks/{task['id']}/copy").status_code, 200)
        self.assertEqual(self.client.get(f"/api/tasks/{task['id']}/export?format=txt").status_code, 200)
        before = store.get_task(task["id"])
        with self.future_clock():
            self.assertEqual(self.client.get(f"/api/tasks/{task['id']}/copy").status_code, 422)
            self.assertEqual(self.client.get(f"/api/tasks/{task['id']}/export?format=txt").status_code, 422)
            audit = self.client.get(f"/api/tasks/{task['id']}/export?format=json")
        self.assertEqual(audit.status_code, 200)
        quotes = audit.json()["二、知识库依据"]["实时报价依据与计算"]
        self.assertEqual(quotes[0]["报价状态"], "已剔除")
        self.assertIsNone(quotes[0]["结算金额"])
        self.assertEqual(store.get_task(task["id"]), before)

    async def test_restoring_previously_valid_price_does_not_bypass_current_expiry(self):
        task = self.priced_task()
        historical_version = task["versions"][0]["id"]
        task["draft"]["title"] = "后续版本"
        store.save_task(task, "后来修改")
        with self.future_clock():
            restored = self.client.post(f"/api/tasks/{task['id']}/versions/{historical_version}/restore")
            self.assertEqual(restored.status_code, 200)
            self.assertNotEqual(restored.json()["draft"]["title"], "后续版本")
            self.assertEqual(self.client.get(f"/api/tasks/{task['id']}/copy").status_code, 422)
            self.assertEqual(self.client.get(f"/api/tasks/{task['id']}/export?format=txt").status_code, 422)
            self.assertEqual(self.client.get(f"/api/tasks/{task['id']}/export?format=report").status_code, 200)

    async def test_overlong_poster_is_repaired_before_composition_or_remains_blocked(self):
        self.config["deepseek_api_key"] = "synthetic-mocked-key"
        for repair_succeeds in [True, False]:
            with self.subTest(repair_succeeds=repair_succeeds):
                task = content_task()
                task["brief"]["platform"] = "poster"
                initial = deepcopy(task["draft"])
                initial["body"] = "屏幕为14英寸。\n核对具体配置。\n咨询使用场景。\n到店了解功能。"
                revised = deepcopy(initial)
                if repair_succeeds:
                    revised["body"] = "屏幕为14英寸。\n核对具体配置。\n到店咨询使用场景。"
                approval = {"passed": True, "issues": [], "notes": []}
                with patch.object(workflow, "json_chat", new_callable=AsyncMock,
                                  side_effect=[initial, deepcopy(approval), revised, deepcopy(approval)]) as model, \
                     patch.object(media, "compose_poster", new_callable=AsyncMock,
                                  return_value="/api/files/poster-" + "a" * 32 + ".png") as compositor:
                    result = await workflow.generate_task(task)
                self.assertEqual(model.await_count, 4)
                self.assertEqual(result["repair_record"]["attempts"], 1)
                if repair_succeeds:
                    self.assertEqual(result["status"], "draft")
                    compositor.assert_awaited_once()
                else:
                    self.assertEqual(result["status"], "blocked")
                    compositor.assert_not_awaited()
                    self.assertTrue(any(check["category"] == "海报版式" and check["status"] == "blocked" for check in result["checks"]))


if __name__ == "__main__":
    unittest.main()
