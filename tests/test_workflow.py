"""Workflow boundary regressions; all evidence is synthetic and providers mocked."""

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from huawei_agent import store, workflow
from huawei_agent.validation import validate


def content_task():
    task = store.create_task("合成流程测试")
    task["brief"].update(audience="移动办公者", scenario="office", goal="了解配置", product="Synthetic Model A", platform="moments")
    task["facts"] = [{"id": "fact-a", "product_id": "product-a", "model": "Synthetic Model A", "category": "屏幕",
                      "claim": "屏幕：14英寸", "excerpt": "14英寸", "source_title": "合成事实文档",
                      "source_url": "https://example.invalid/facts", "verified": True}]
    task["assets"] = [{"id": "a" * 24, "product_id": "product-a", "model": "Synthetic Model A", "name": "合成图.png",
                       "caption": "合成测试图", "source_title": "合成索引", "source_url": "https://example.invalid/image",
                       "url": "/api/assets/" + "a" * 24, "verified": True}]
    task["draft"] = {"title": "按实际任务选择配置", "lead": "给移动办公者的选择建议", "body": "屏幕为14英寸。广告，AI辅助内容。",
                     "cta": "咨询具体配置", "tags": [], "fact_ids": ["fact-a"],
                     "images": [{"id": "a" * 24, "caption": "合成测试图", "position": "正文后"}], "generator": "rules"}
    task["checks"] = [{"category": "语义核验", "status": "warning", "message": "合成规则草稿"}]
    task["status"] = "draft"
    return store.save_task(task, "合成内容")


def run_validation(task):
    return validate(task["draft"], task["facts"], task["assets"], task["quotes"], task["brief"]["platform"])


class WorkflowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data_patch = patch.object(store, "DATA", Path(self.temp.name))
        self.data_patch.start()
        self.addCleanup(self.data_patch.stop)
        settings_patch = patch.object(workflow, "load_settings", return_value={"deepseek_api_key": ""})
        settings_patch.start()
        self.addCleanup(settings_patch.stop)
        self.addCleanup(workflow.LOCKS.clear)

    async def test_incomplete_input_asks_questions_without_retrieving_or_inventing(self):
        task = store.create_task()
        with patch.object(workflow.knowledge, "retrieve", new_callable=AsyncMock) as retrieval:
            result = await workflow.chat_task(task, "帮我写一篇内容")
        self.assertEqual(result["status"], "needs_input")
        self.assertIsNone(result["draft"])
        self.assertIn("还需要补充", result["messages"][-1]["content"])
        retrieval.assert_not_awaited()

    async def test_changing_product_in_chat_discards_old_facts_and_images_before_retrieval(self):
        task = content_task()
        captured = []
        async def stop_before_generation(updated, instruction="", refresh=False):
            captured.append(deepcopy(updated))
            return updated
        with patch.object(workflow, "generate_task", side_effect=stop_before_generation):
            await workflow.chat_task(task, "改用 MateBook D 16 2026，给移动办公者推荐")
        self.assertEqual(captured[0]["facts"], [])
        self.assertEqual(captured[0]["assets"], [])
        self.assertEqual(captured[0]["evidence"], [])

    async def test_retrieval_failure_does_not_create_fabricated_content(self):
        task = content_task()
        task["facts"], task["assets"], task["draft"] = [], [], None
        with patch.object(workflow.knowledge, "discover", new_callable=AsyncMock,
                          return_value={"facts": [], "assets": [], "evidence": [], "warnings": [], "catalog": []}):
            result = await workflow.generate_task(task)
        self.assertEqual(result["status"], "needs_evidence")
        self.assertIsNone(result["draft"])

    async def test_scene_change_changes_title_and_content_focus(self):
        task = content_task()
        office = workflow.rule_draft(task)
        task["brief"]["scenario"] = "school"
        school = workflow.rule_draft(task)
        self.assertNotEqual((office["title"], office["lead"]), (school["title"], school["lead"]))
        self.assertNotEqual(office["lead"], school["lead"])

    async def test_platform_change_changes_structure_tags_and_cta(self):
        task = content_task()
        moments = workflow.rule_draft(task)
        task["brief"]["platform"] = "xiaohongshu"
        xhs = workflow.rule_draft(task)
        self.assertNotEqual(moments["title"], xhs["title"])
        self.assertNotEqual(moments["cta"], xhs["cta"])
        self.assertEqual(moments["tags"], [])
        self.assertTrue(xhs["tags"])

    async def test_unknown_asset_reference_is_blocked(self):
        task = content_task()
        task["draft"]["images"][0]["id"] = "not-in-evidence"
        self.assertTrue(any(c["status"] == "blocked" and c["category"] == "图片型号" for c in run_validation(task)))

    async def test_known_but_different_product_image_is_blocked(self):
        task = content_task()
        task["assets"][0].update(model="Synthetic Model B", product_id="product-b")
        self.assertTrue(any(c["status"] == "blocked" and c["category"] == "图片型号" for c in run_validation(task)))

    async def test_unreferenced_fact_id_is_blocked(self):
        task = content_task()
        task["draft"]["fact_ids"] = ["unknown-fact"]
        self.assertTrue(any(c["status"] == "blocked" and c["category"] == "产品事实" for c in run_validation(task)))

    async def test_price_with_currency_prefix_cannot_bypass_evidence_check(self):
        for price in ["¥9999", "￥9,999.00", "人民币9999元", "CNY 9999"]:
            with self.subTest(price=price):
                task = content_task()
                task["draft"]["body"] += " 确定到手价" + price
                self.assertTrue(any(c["status"] == "blocked" and c["category"] == "价格" for c in run_validation(task)))

    async def test_conditional_price_cannot_become_a_confirmed_claim(self):
        task = content_task()
        task["quotes"] = {"quotes": [{"status": "conditional", "checkout_amount": "10000.00", "conditional_checkout_amount": "9999.00"}], "best": []}
        task["draft"]["body"] += " 确定到手价9999元。"
        self.assertTrue(any(c["status"] == "blocked" and c["category"] == "价格" for c in run_validation(task)))

    async def test_price_comparison_is_exact_not_a_substring_of_higher_amount(self):
        task = content_task()
        task["quotes"] = {"quotes": [{"offer_id": "offer-a", "status": "verified", "checkout_amount": "18999.00"}],
                          "best": [{"offer_id": "offer-a", "checkout_amount": "18999.00"}]}
        task["draft"]["body"] += " 确定到手价8999元。"
        self.assertTrue(any(c["status"] == "blocked" and c["category"] == "价格" for c in run_validation(task)))

    async def test_forbidden_and_fake_personal_experience_are_blocked(self):
        task = content_task()
        task["draft"]["body"] += " 我亲测这台是全网最低。"
        categories = {c["category"] for c in run_validation(task) if c["status"] == "blocked"}
        self.assertIn("营销合规", categories)
        self.assertIn("体验依据", categories)


if __name__ == "__main__":
    unittest.main()
