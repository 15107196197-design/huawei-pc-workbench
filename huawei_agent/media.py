"""Deterministic poster compositor: product pixels are never generated."""

from __future__ import annotations

import io
import hashlib
import json
from pathlib import Path
import re
import uuid

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .knowledge import knowledge
from .settings import DATA


SIZE = (1080, 1620)
INK = "#16283C"
MUTED = "#576A80"
BLUE = "#2865C8"
PRODUCT_FIT = (864, 416)
PRODUCT_ORIGIN = (108, 500)
DEFAULT_CTA = "咨询门店，了解适合你的配置与体验方式"


def _font(size: int):
    candidates = [
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    ]
    for candidate in candidates:
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size)
    raise ValueError("缺少中文字体，无法可靠排版海报；请安装 Noto Sans CJK")


def _wrap(draw, text: str, font, width: int):
    lines = []
    for paragraph in text.splitlines() or [""]:
        line = ""
        for char in paragraph:
            if draw.textlength(line + char, font=font) > width and line:
                lines.append(line)
                line = char
            else:
                line += char
        lines.append(line)
    return lines


def _fit(draw, text: str, width: int, height: int, maximum: int, minimum: int, label: str):
    for size in range(maximum, minimum - 1, -1):
        font = _font(size)
        lines = _wrap(draw, text, font, width)
        spacing = round(size * 1.4)
        if len(lines) * spacing <= height:
            return font, lines, spacing
    raise ValueError(f"{label}过长，无法在海报中完整保留；请缩短后重新生成")


def _text(draw, value, x, y, width, height, maximum=36, minimum=24, fill=INK, label="文本"):
    text = str(value or "").strip()
    if not text:
        return {"text": "", "lines": [], "position": [x, y]}
    font, lines, spacing = _fit(draw, text, width, height, maximum, minimum, label)
    for index, line in enumerate(lines):
        draw.text((x, y + index * spacing), line, font=font, fill=fill, anchor="lt")
    return {"text": text, "lines": lines, "position": [x, y],
            "font_size": font.size, "line_height": spacing}


def _points(draft: dict):
    points = draft.get("selling_points") or draft.get("points")
    if not isinstance(points, list):
        points = [re.sub(r"^\s*(?:[•·*\-]\s*|\d+[.、]\s+)", "", paragraph).strip()
                  for paragraph in str(draft.get("body") or "").splitlines() if paragraph.strip()]
    points = [str(point).strip() for point in points if str(point).strip()]
    if len(points) > 3:
        raise ValueError("海报最多三个卖点；请精简正文后重新生成，系统不会截断事实或限定条件")
    return points


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _product_geometry(subject):
    fitted = ImageOps.contain(subject, PRODUCT_FIT, method=Image.Resampling.LANCZOS)
    position = (PRODUCT_ORIGIN[0] + (PRODUCT_FIT[0] - fitted.width) // 2,
                PRODUCT_ORIGIN[1] + (PRODUCT_FIT[1] - fitted.height) // 2)
    # The actual product card is opaque white, including every transparent pixel.
    expected = Image.new("RGBA", fitted.size, "white")
    expected.alpha_composite(fitted)
    return fitted, position, expected.convert("RGB")


def _drawn_text(draft):
    return {"title": str(draft.get("title") or "").strip(),
            "lead": str(draft.get("lead") or "").strip(),
            "body_points": _points(draft),
            "cta": str(draft.get("cta") or DEFAULT_CTA).strip()}


async def compose_poster(task: dict, background_path: str | None = None) -> str:
    """Create PNG and sibling PDF, returning the PNG's authenticated file URL."""
    if any(check.get("status") == "blocked" for check in task.get("checks", [])):
        raise ValueError("核验存在阻断问题，修正后才能生成正式海报")
    draft = task.get("draft") or {}
    if not draft.get("title") or not draft.get("body"):
        raise ValueError("请先生成完整的海报标题与卖点")
    selected = draft.get("images") or []
    if len(selected) != 1:
        raise ValueError("海报需选择一张已核验的产品主图")
    asset = next((a for a in task.get("assets", []) if a.get("id") == selected[0].get("id")), None)
    if not asset or asset.get("verified") is not True:
        raise ValueError("产品主图缺少已确认的型号和 ima 图片索引关联")
    used_ids = set(draft.get("fact_ids") or [])
    used_facts = [fact for fact in task.get("facts", []) if fact.get("id") in used_ids]
    if not used_facts or len(used_facts) != len(used_ids) or any(fact.get("verified") is not True for fact in used_facts):
        raise ValueError("海报缺少已核实的产品事实依据")
    identity = asset.get("product_id") or asset.get("model")
    if not identity or any((fact.get("product_id") or fact.get("model")) != identity for fact in used_facts):
        raise ValueError("海报卖点与主图涉及不同型号；请为同一产品选择事实和图片")
    points = _points(draft)
    raw, _ = await knowledge.asset_bytes(asset["id"])
    try:
        with Image.open(io.BytesIO(raw)) as source:
            source.load()
            subject = ImageOps.exif_transpose(source).convert("RGBA")
    except Exception:
        raise ValueError("产品原图无法读取，未生成海报") from None
    if background_path:
        path = Path(background_path)
        if not path.is_file() or path.stat().st_size > 25 * 1024 * 1024:
            raise ValueError("背景文件不存在或超过25MB")
        try:
            with Image.open(path) as background:
                canvas = ImageOps.fit(ImageOps.exif_transpose(background).convert("RGB"), SIZE,
                                      method=Image.Resampling.LANCZOS).convert("RGBA")
        except Exception:
            raise ValueError("背景文件不是有效图片") from None
        veil = Image.new("RGBA", SIZE, (245, 248, 252, 182))
        canvas = Image.alpha_composite(canvas, veil)
    else:
        canvas = Image.new("RGBA", SIZE, "#F4F7FB")
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((64, 62, 348, 109), radius=23, fill="#E4EDFC")
    draw.text((86, 74), "HUAWEI PC · 产品指南", font=_font(23), fill=BLUE, anchor="lt")
    title_record = _text(draw, draft["title"], 64, 150, 952, 178, 70, 44, label="主标题")
    lead_record = _text(draw, draft.get("lead"), 67, 342, 946, 100, 33, 24, MUTED, "副标题")

    # A white product card also preserves white pixels in source photography.
    draw.rounded_rectangle((64, 468, 1016, 1004), radius=32, fill="white", outline="#E1E7EF", width=2)
    fitted, product_position, expected_product = _product_geometry(subject)
    canvas.alpha_composite(fitted, product_position)
    draw = ImageDraw.Draw(canvas)
    _text(draw, asset.get("model") or task.get("brief", {}).get("product") or "", 108, 941, 864, 40,
          28, 21, MUTED, "产品型号")

    point_records = []
    for index, point in enumerate(points):
        top = 1051 + index * 88
        draw.ellipse((69, top + 7, 82, top + 20), fill=BLUE)
        point_records.append(_text(draw, point, 105, top, 900, 77, 31, 24, INK, f"第{index + 1}条卖点"))
    draw.rounded_rectangle((64, 1350, 1016, 1478), radius=26, fill=BLUE)
    cta_record = _text(draw, draft.get("cta") or DEFAULT_CTA, 100, 1382, 880, 74,
                       32, 25, "white", "行动引导")
    _text(draw, "广告 · AI辅助排版" + ("，含AI生成背景" if background_path else "，纯色背景"),
          67, 1517, 946, 33, 23, 20, MUTED, "发布标识")
    _text(draw, "产品原图来自指定ima知识库；配置、活动与价格条件以核验记录和购买页面为准。",
          67, 1561, 946, 42, 20, 17, MUTED, "说明")
    if any(check.get("status") == "warning" for check in task.get("checks", [])) or not task.get("checks"):
        draw.rounded_rectangle((795, 65, 1016, 111), radius=20, fill="#FFF1D6")
        draw.text((816, 77), "发布前请复核", font=_font(22), fill="#80591E", anchor="lt")
    directory = DATA / "generated"
    directory.mkdir(parents=True, exist_ok=True)
    filename = "poster-" + uuid.uuid4().hex + ".png"
    final = canvas.convert("RGB")
    crop_box = (*product_position, product_position[0] + fitted.width, product_position[1] + fitted.height)
    actual_product_hash = _sha256(final.crop(crop_box).tobytes())
    expected_product_hash = _sha256(expected_product.tobytes())
    if actual_product_hash != expected_product_hash:
        raise ValueError("最终成品产品区域与原图等比例白底贴层不一致，已停止交付")
    encoded = io.BytesIO()
    final.save(encoded, "PNG", optimize=True)
    png_bytes = encoded.getvalue()
    manifest = {
        "version": 1, "poster_file": filename, "asset_id": asset["id"],
        "source_sha256": _sha256(raw), "source_size": list(subject.size),
        "fit_box": list(PRODUCT_FIT), "fitted_size": list(fitted.size),
        "position": list(product_position), "product_crop_box": list(crop_box),
        "expected_product_pixels_sha256": expected_product_hash,
        "actual_product_pixels_sha256": actual_product_hash,
        "product_pixels_match": True, "poster_sha256": _sha256(png_bytes),
        "poster_size": list(final.size),
        "text_rendered": {"title": title_record["text"], "lead": lead_record["text"],
                          "body_points": [record["text"] for record in point_records], "cta": cta_record["text"]},
        "text_layout": {"title": title_record, "lead": lead_record,
                        "body_points": point_records, "cta": cta_record},
        "product_transform": "EXIF orientation + proportional LANCZOS contain + alpha composite on opaque white; no crop or redraw",
    }
    (directory / filename).write_bytes(png_bytes)
    final.save(directory / Path(filename).with_suffix(".pdf"), "PDF", resolution=144.0)
    # This server-side sidecar is not exposed by /api/files.  A task field alone
    # is insufficient evidence: a client must not be able to fabricate a proof.
    (directory / Path(filename).with_suffix(".render.json")).write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    draft["render_manifest"] = manifest
    return "/api/files/" + filename


async def verify_render_manifest(task: dict) -> dict:
    """Recompute product-pixel proof and bind it to server-recorded final bytes.

    Text is a record of the exact strings sent to Pillow, not OCR or a general
    readability assessment.  No semantic, model-identity or compliance finding
    is automatically waived by this narrow rendering proof.
    """
    result = {"available": False, "verified": False, "product_pixels_verified": False,
              "poster_sha256_verified": False, "source_sha256_verified": False,
              "text_binding_verified": False, "text_rendered": {}, "checks": {}, "errors": [],
              "scope": "仅证明指定原图按比例贴白底后的产品区域像素，以及与同一PNG绑定的程序绘字记录；不替代事实、型号及其他视觉检查"}
    try:
        draft = task.get("draft") or {}
        manifest = draft.get("render_manifest")
        url = draft.get("poster_url", "")
        if not isinstance(manifest, dict):
            result["errors"].append("缺少服务端渲染记录")
            return result
        result["available"] = True
        if not isinstance(url, str) or not re.fullmatch(r"/api/files/poster-[0-9a-f]{32}\.png", url):
            raise ValueError("海报文件引用无效")
        filename = url.rsplit("/", 1)[-1]
        directory = DATA / "generated"
        sidecar = directory / Path(filename).with_suffix(".render.json")
        server_manifest = json.loads(sidecar.read_text(encoding="utf-8"))
        checks = result["checks"]
        checks["server_manifest_matches"] = manifest == server_manifest and manifest.get("poster_file") == filename and manifest.get("version") == 1
        if not checks["server_manifest_matches"]:
            raise ValueError("任务渲染记录与服务端原始记录不一致")
        selected = draft.get("images") or []
        asset_id = manifest.get("asset_id")
        asset = next((item for item in task.get("assets", []) if item.get("id") == asset_id), None)
        checks["asset_binding_matches"] = len(selected) == 1 and selected[0].get("id") == asset_id and bool(asset and asset.get("verified") is True)
        if not checks["asset_binding_matches"]:
            raise ValueError("渲染原图与当前选图不一致或素材未核验")
        png_bytes = (directory / filename).read_bytes()
        checks["poster_sha256_matches"] = _sha256(png_bytes) == manifest.get("poster_sha256")
        result["poster_sha256_verified"] = checks["poster_sha256_matches"]
        raw, _ = await knowledge.asset_bytes(asset_id)
        checks["source_sha256_matches"] = _sha256(raw) == manifest.get("source_sha256")
        result["source_sha256_verified"] = checks["source_sha256_matches"]
        with Image.open(io.BytesIO(raw)) as source:
            subject = ImageOps.exif_transpose(source).convert("RGBA")
        fitted, position, expected_product = _product_geometry(subject)
        crop_box = (*position, position[0] + fitted.width, position[1] + fitted.height)
        checks["geometry_matches"] = (manifest.get("source_size") == list(subject.size)
                                      and manifest.get("fit_box") == list(PRODUCT_FIT)
                                      and manifest.get("fitted_size") == list(fitted.size)
                                      and manifest.get("position") == list(position)
                                      and manifest.get("product_crop_box") == list(crop_box))
        with Image.open(io.BytesIO(png_bytes)) as image:
            image.load()
            checks["poster_size_matches"] = image.size == SIZE and manifest.get("poster_size") == list(SIZE)
            actual_hash = _sha256(image.convert("RGB").crop(crop_box).tobytes())
        expected_hash = _sha256(expected_product.tobytes())
        checks["product_pixels_match"] = (actual_hash == expected_hash
                                          and actual_hash == manifest.get("actual_product_pixels_sha256")
                                          and expected_hash == manifest.get("expected_product_pixels_sha256")
                                          and manifest.get("product_pixels_match") is True)
        checks["text_binding_matches"] = manifest.get("text_rendered") == _drawn_text(draft)
        result["product_pixels_verified"] = all(checks[key] for key in ["server_manifest_matches", "asset_binding_matches", "poster_sha256_matches", "source_sha256_matches", "geometry_matches", "poster_size_matches", "product_pixels_match"])
        result["text_binding_verified"] = result["product_pixels_verified"] and checks["text_binding_matches"]
        result["verified"] = all(checks.values())
        if result["text_binding_verified"]:
            result["text_rendered"] = manifest["text_rendered"]
        result["errors"] = [key for key, passed in checks.items() if not passed]
    except Exception as error:
        # Only fixed error categories are returned; upstream errors may contain
        # credentials or signed URLs and must not be forwarded into the proof.
        result["errors"].append("无法完成渲染证明校验：" + type(error).__name__)
        result["verified"] = False
        result["product_pixels_verified"] = False
        result["text_binding_verified"] = False
        result["text_rendered"] = {}
    return result
