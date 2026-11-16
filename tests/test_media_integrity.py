"""Regression checks for numerical text and saved poster state; no model calls."""

from copy import deepcopy
import importlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from huawei_agent import exports, media, providers, settings, store, workflow
from test_workflow import content_task


api = importlib.import_module("huawei_agent.app")


class MediaIntegrityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.config = dict(settings.DEFAULTS)
        for module in [settings, store, exports, media, api]:
            patcher = patch.object(module, "DATA", self.directory)
            patcher.start()
            self.addCleanup(patcher.stop)
        for module in [api, workflow]:
            patcher = patch.object(module, "load_settings", return_value=self.config)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(providers.httpx, "AsyncClient", side_effect=AssertionError("图片完整性测试禁止外部HTTP调用"))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = TestClient(api.app, raise_server_exceptions=False)
        self.addCleanup(self.client.close)
        self.addCleanup(workflow.LOCKS.clear)

    def picture_bytes(self):
        image = Image.new("RGB", (120, 60), "white")
        ImageDraw.Draw(image).rectangle((20, 15, 100, 45), fill="#B4C6DE")
        content = io.BytesIO()
        image.save(content, "PNG")
        return content.getvalue()

    def poster_task(self):
        task = content_task()
        task["brief"]["platform"] = "poster"
        task["facts"][0].update(category="存储", claim="存储：512 GB / 1 TB", excerpt="512 GB / 1 TB")
        task["draft"].update(title="合成海报检查", lead="核对具体配置", body="512 GB / 1 TB")
        return store.save_task(task, "合成存储规格海报")

    async def test_points_keep_specification_numbers_and_remove_only_actual_list_markers(self):
        cases = {
            "512 GB / 1 TB": "512 GB / 1 TB",
            "1.25 kg": "1.25 kg",
            "120 Hz": "120 Hz",
            "3.5 GHz": "3.5 GHz",
            "1. 512 GB / 1 TB": "512 GB / 1 TB",
            "2、 1.25 kg": "1.25 kg",
            "• 16 GB": "16 GB",
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(media._points({"body": source}), [expected])

    async def test_actual_compositor_renders_complete_specification_text_into_real_output(self):
        task = self.poster_task()
        calls = []
        original = ImageDraw.ImageDraw.text
        def capture_and_draw(draw, xy, text, *args, **kwargs):
            calls.append(text)
            return original(draw, xy, text, *args, **kwargs)
        with patch.object(media.knowledge, "asset_bytes", new_callable=AsyncMock,
                          return_value=(self.picture_bytes(), "image/png")), \
             patch.object(ImageDraw.ImageDraw, "text", new=capture_and_draw):
            url = await media.compose_poster(task)
        self.assertIn("512 GB / 1 TB", calls, "数值必须完整传入真实Pillow文字绘制过程")
        png = self.directory / "generated" / Path(url).name
        with Image.open(png) as rendered:
            self.assertEqual(rendered.size, (1080, 1620))
            point_region = rendered.crop((100, 1045, 600, 1115)).convert("RGB")
            data = point_region.tobytes()
            pixels = zip(data[0::3], data[1::3], data[2::3])
            self.assertTrue(any(max(pixel) - min(pixel) < 100 and max(pixel) < 140 for pixel in pixels),
                            "数值所在卖点区域必须实际绘有文字像素")
        pdf = png.with_suffix(".pdf")
        self.assertTrue(pdf.read_bytes().startswith(b"%PDF"))

    async def test_manual_edit_reuses_existing_ai_background_and_persists_its_metadata(self):
        task = self.poster_task()
        directory = self.directory / "generated"
        directory.mkdir(exist_ok=True)
        background = directory / "synthetic-existing-background.png"
        background.write_bytes(self.picture_bytes())
        metadata = {"generated": True, "provider": "Qwen-Image", "model": "synthetic-model", "url": "/api/files/" + background.name}
        task["draft"]["background"] = metadata
        task = store.save_task(task, "保存既有AI背景")
        edited = deepcopy(task["draft"])
        edited["title"] = "人工修改后的海报标题"
        with patch.object(media, "compose_poster", new_callable=AsyncMock,
                          return_value="/api/files/poster-" + "b" * 32 + ".png") as compositor:
            result = self.client.put(f"/api/tasks/{task['id']}/draft", json={"revision": task["revision"], "draft": edited})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(compositor.await_count, 1)
        self.assertEqual(compositor.await_args.args[1], str(background))
        reopened = store.get_task(task["id"])
        self.assertEqual(reopened["draft"]["background"], metadata)
        self.assertEqual(reopened["draft"]["title"], edited["title"])

    async def test_warning_export_describes_actual_generator_without_mislabeling_model_draft_as_rules(self):
        task = content_task()
        task["checks"] = [{"category": "价格", "status": "warning", "message": "活动待确认"}]
        for generator, expected in [("rules", "待审核规则草稿"), ("deepseek", "待复核草稿")]:
            with self.subTest(generator=generator):
                task["draft"]["generator"] = generator
                raw, _, _ = exports.export_task(task, "json")
                label = json.loads(raw)["导出状态"]
                self.assertIn(expected, label)
                if generator != "rules":
                    self.assertNotIn("规则草稿", label)

    async def test_successful_vision_retry_removes_its_old_block_but_preserves_other_real_blocks(self):
        for has_other_block in [False, True]:
            with self.subTest(has_other_block=has_other_block):
                task = self.poster_task()
                directory = self.directory / "generated"
                directory.mkdir(exist_ok=True)
                poster = directory / ("poster-" + "c" * 32 + ".png")
                poster.write_bytes(self.picture_bytes())
                task["draft"]["poster_url"] = "/api/files/" + poster.name
                task["status"] = "blocked"
                task["checks"] = [{"category": "视觉核验", "status": "blocked", "message": "旧视觉结果未通过"}]
                if has_other_block:
                    task["checks"].append({"category": "产品事实", "status": "blocked", "message": "仍待修正的事实错误"})
                task = store.save_task(task, "保存待重试视觉结果")
                with patch.object(api.knowledge, "asset_bytes", new_callable=AsyncMock,
                                  return_value=(self.picture_bytes(), "image/png")), \
                     patch.object(api, "json_chat", new_callable=AsyncMock,
                                  return_value={"passed": True, "issues": [], "notes": ["非阻断建议"]}):
                    result = self.client.post(f"/api/tasks/{task['id']}/vision")
                self.assertEqual(result.status_code, 200)
                updated = result.json()
                self.assertEqual(updated["status"], "blocked" if has_other_block else "draft")
                vision_checks = [check for check in updated["checks"] if check["category"] == "视觉核验"]
                self.assertEqual(len(vision_checks), 1)
                self.assertEqual(vision_checks[0]["status"], "pass")

    async def test_text_reverification_cannot_clear_visual_failure_for_the_same_poster(self):
        task = self.poster_task()
        task["draft"]["poster_url"] = "/api/files/poster-" + "d" * 32 + ".png"
        task["checks"] = [{"category": "视觉核验", "status": "blocked", "message": "成品漏绘512，须重新合成并核验"}]
        task["vision_result"] = {"passed": False, "issues": ["成品漏绘512"]}
        task["status"] = "blocked"
        task = store.save_task(task, "保存真实视觉阻断")
        result = self.client.post(f"/api/tasks/{task['id']}/verify")
        self.assertEqual(result.status_code, 200)
        updated = result.json()
        self.assertEqual(updated["status"], "blocked")
        self.assertEqual(updated["draft"]["poster_url"], task["draft"]["poster_url"])
        self.assertTrue(any(check["category"] == "视觉核验" and check["status"] == "blocked" for check in updated["checks"]))
        self.assertEqual(self.client.get(f"/api/tasks/{task['id']}/copy").status_code, 422)
        self.assertEqual(self.client.get(f"/api/tasks/{task['id']}/export?format=txt").status_code, 422)

    async def test_a_new_draft_without_a_poster_does_not_inherit_an_unrelated_visual_check(self):
        task = self.poster_task()
        task["draft"].pop("poster_url", None)
        task["checks"] = [{"category": "视觉核验", "status": "blocked", "message": "旧海报的数字丢失"}]
        task["status"] = "blocked"
        task = store.save_task(task, "新文稿尚未合成")
        result = self.client.post(f"/api/tasks/{task['id']}/verify")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["status"], "draft")
        self.assertFalse(any(check["category"] == "视觉核验" for check in result.json()["checks"]))
        self.assertFalse(store.get_task(task["id"])["draft"].get("poster_url"))

    def run_synthetic_vision(self, model_result):
        task = self.poster_task()
        directory = self.directory / "generated"
        directory.mkdir(exist_ok=True)
        path = directory / ("poster-" + "e" * 32 + ".png")
        path.write_bytes(self.picture_bytes())
        task["draft"]["poster_url"] = "/api/files/" + path.name
        task = store.save_task(task, "准备视觉结构边界验证")
        with patch.object(api.knowledge, "asset_bytes", new_callable=AsyncMock,
                          return_value=(self.picture_bytes(), "image/png")), \
             patch.object(api, "json_chat", new_callable=AsyncMock, return_value=model_result):
            response = self.client.post(f"/api/tasks/{task['id']}/vision")
        return task, response

    async def test_object_vision_issues_are_recorded_as_blocking_findings_without_server_error(self):
        issue = {"region": "存储卖点", "reason": "512 数字丢失", "expected": "512 GB / 1 TB", "observed": "GB / 1 TB"}
        task, response = self.run_synthetic_vision({"passed": False, "issues": [issue], "notes": []})
        self.assertEqual(response.status_code, 200)
        updated = response.json()
        self.assertEqual(updated["status"], "blocked")
        self.assertEqual(updated["vision_result"]["issues"], [issue])
        finding = next(check for check in updated["checks"] if check["category"] == "视觉核验")
        self.assertEqual(finding["status"], "blocked")
        self.assertIn("512", finding["message"])
        self.assertEqual(self.client.get(f"/api/tasks/{task['id']}/copy").status_code, 422)
        self.assertEqual(self.client.get(f"/api/tasks/{task['id']}/export?format=json").status_code, 200)

    async def test_contradictory_vision_pass_with_issues_remains_blocked(self):
        task, response = self.run_synthetic_vision({"passed": True, "issues": ["成品仍遗漏512这一关键数字"], "notes": []})
        self.assertEqual(response.status_code, 200)
        updated = response.json()
        self.assertIs(updated["vision_result"]["passed"], False)
        self.assertEqual(updated["status"], "blocked")
        self.assertTrue(any(check["category"] == "视觉核验" and check["status"] == "blocked" for check in updated["checks"]))
        self.assertEqual(self.client.get(f"/api/tasks/{task['id']}/copy").status_code, 422)
        self.assertEqual(self.client.get(f"/api/tasks/{task['id']}/export?format=txt").status_code, 422)


if __name__ == "__main__":
    unittest.main()
