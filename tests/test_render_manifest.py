"""Narrow pixel/text provenance proof, using actual local compositor output."""

from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from PIL import Image, ImageDraw

from huawei_agent import media, store
from test_workflow import content_task


class RenderManifestTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        for module in [store, media]:
            patcher = patch.object(module, "DATA", self.directory)
            patcher.start()
            self.addCleanup(patcher.stop)

    def source(self, transparent=False, altered=False):
        image = Image.new("RGBA", (240, 120), (0, 0, 0, 0) if transparent else "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((30, 20, 210, 95), fill=(45, 85, 145, 128 if transparent else 255))
        draw.rectangle((85, 45, 155, 65), fill=(240, 240, 240, 255))
        if altered:
            draw.rectangle((100, 45, 120, 65), fill=(255, 0, 0, 255))
        output = io.BytesIO()
        image.save(output, "PNG")
        return output.getvalue()

    def task(self):
        task = content_task()
        task["brief"]["platform"] = "poster"
        task["facts"][0].update(category="存储", claim="存储：512 GB / 1 TB", excerpt="512 GB / 1 TB")
        task["draft"].update(title="完整保留产品原图", lead="合成程序证明测试", body="512 GB / 1 TB", cta="咨询配置")
        return task

    async def render(self, task, source):
        with patch.object(media.knowledge, "asset_bytes", new_callable=AsyncMock, return_value=(source, "image/png")):
            task["draft"]["poster_url"] = await media.compose_poster(task)
        return self.directory / "generated" / Path(task["draft"]["poster_url"]).name

    async def proof(self, task, source):
        with patch.object(media.knowledge, "asset_bytes", new_callable=AsyncMock, return_value=(source, "image/png")):
            return await media.verify_render_manifest(task)

    async def test_opaque_and_transparent_product_pixels_match_proportional_white_backed_source(self):
        for transparent in [False, True]:
            with self.subTest(transparent=transparent):
                task, source = self.task(), self.source(transparent)
                path = await self.render(task, source)
                manifest = task["draft"]["render_manifest"]
                self.assertEqual(manifest["source_sha256"], hashlib.sha256(source).hexdigest())
                self.assertEqual(manifest["poster_sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
                self.assertEqual(manifest["actual_product_pixels_sha256"], manifest["expected_product_pixels_sha256"])
                self.assertEqual(manifest["fitted_size"], [832, 416])
                self.assertEqual(manifest["position"], [124, 500])
                result = await self.proof(task, source)
                self.assertTrue(result["verified"])
                self.assertTrue(result["product_pixels_verified"])
                self.assertTrue(result["poster_sha256_verified"])
                self.assertTrue(result["source_sha256_verified"])
                if transparent:
                    with Image.open(path) as poster:
                        self.assertEqual(poster.getpixel(tuple(manifest["position"])), (255, 255, 255))

    async def test_final_drawn_text_record_preserves_512_and_binds_to_current_draft(self):
        task, source = self.task(), self.source()
        task["draft"]["body"] = "1. 512 GB / 1 TB"
        await self.render(task, source)
        manifest = task["draft"]["render_manifest"]
        self.assertEqual(manifest["text_rendered"]["body_points"], ["512 GB / 1 TB"])
        self.assertEqual(manifest["text_layout"]["body_points"][0]["lines"], ["512 GB / 1 TB"])
        result = await self.proof(task, source)
        self.assertTrue(result["text_binding_verified"])
        self.assertEqual(result["text_rendered"]["body_points"], ["512 GB / 1 TB"])
        task["draft"]["body"] = "1. 1024 GB / 1 TB"
        stale = await self.proof(task, source)
        self.assertFalse(stale["verified"])
        self.assertFalse(stale["text_binding_verified"])
        self.assertEqual(stale["text_rendered"], {})

    async def test_changed_png_inside_or_outside_product_area_invalidates_final_file_binding(self):
        task, source = self.task(), self.source()
        path = await self.render(task, source)
        original = path.read_bytes()
        manifest = task["draft"]["render_manifest"]
        for point in [tuple(manifest["position"]), (64, 150)]:
            with self.subTest(point=point):
                with Image.open(io.BytesIO(original)) as image:
                    changed = image.convert("RGB")
                changed.putpixel(point, (255, 0, 0))
                changed.save(path, "PNG")
                proof = await self.proof(task, source)
                self.assertFalse(proof["verified"])
                self.assertFalse(proof["poster_sha256_verified"])
                self.assertFalse(proof["product_pixels_verified"])
                self.assertFalse(proof["text_binding_verified"])

    async def test_changed_original_cannot_reuse_previous_product_pixel_proof(self):
        task, source = self.task(), self.source()
        await self.render(task, source)
        changed = await self.proof(task, self.source(altered=True))
        self.assertFalse(changed["verified"])
        self.assertFalse(changed["source_sha256_verified"])
        self.assertFalse(changed["product_pixels_verified"])

    async def test_client_cannot_rebind_modified_png_by_forging_visible_manifest_fields(self):
        task, source = self.task(), self.source()
        path = await self.render(task, source)
        forged = deepcopy(task)
        with Image.open(path) as original:
            changed = original.convert("RGB")
        changed.putpixel((64, 150), (255, 0, 0))
        changed.save(path, "PNG")
        forged["draft"]["render_manifest"]["poster_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        proof = await self.proof(forged, source)
        self.assertFalse(proof["verified"])
        self.assertFalse(proof["checks"]["server_manifest_matches"])
        self.assertFalse(proof["product_pixels_verified"])

    async def test_missing_record_or_upstream_failure_returns_safe_failure_instead_of_exception(self):
        empty = await media.verify_render_manifest(self.task())
        self.assertFalse(empty["available"])
        self.assertFalse(empty["verified"])
        task, source = self.task(), self.source()
        await self.render(task, source)
        with patch.object(media.knowledge, "asset_bytes", new_callable=AsyncMock,
                          side_effect=RuntimeError("SYNTHETIC_SECRET_MUST_NOT_LEAK")):
            failure = await media.verify_render_manifest(task)
        self.assertFalse(failure["verified"])
        self.assertNotIn("SYNTHETIC_SECRET", json.dumps(failure))
        self.assertEqual(failure["text_rendered"], {})


if __name__ == "__main__":
    unittest.main()
