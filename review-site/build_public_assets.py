"""Rebuild only the explicitly approved, scrubbed public review materials.

Run from the repository root. Never reads private data/, credentials or the DB.
"""
from __future__ import annotations

import html
import json
from pathlib import Path
import re
import shutil
import sys
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from huawei_agent.policies import PLATFORMS, SCENARIOS

ASSETS = ROOT / "review-site" / "assets"
ASSETS.mkdir(exist_ok=True)
SECTIONS = ["一、场景判断", "二、知识库依据", "三、图文软文", "四、核验结果"]


def save_json(name, value):
    (ASSETS / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sanitize_case(name):
    raw = json.loads((ROOT / "output" / name).read_text(encoding="utf-8"))
    public = {key: raw[key] for key in SECTIONS}
    public["一、场景判断"]["使用场景"] = "开学季"
    for index, image in enumerate(public["三、图文软文"]["图片方案"], 1):
        ext = ".png" if image["图片名称"].endswith(".png") else ".jpg"
        image["图片名称"] = f"配图 {index} · {image['图片说明']}"
        image["图片链接"] = f"article-image-{index}{ext}" if name.startswith("article") else "poster.png"
    public["三、图文软文"]["海报"] = "poster.png" if name == "poster.json" else ""
    return public


def plain(value, depth=0):
    indent = "  " * depth
    if isinstance(value, dict):
        return "\n".join(indent + key + ("：\n" + plain(item, depth + 1) if isinstance(item, (list, dict)) else "：" + str(item)) for key, item in value.items())
    if isinstance(value, list):
        return "\n".join(indent + f"{index}.\n" + plain(item, depth + 1) if isinstance(item, dict) else indent + "- " + str(item) for index, item in enumerate(value, 1))
    return indent + str(value)


article = sanitize_case("article-json.json")
poster = sanitize_case("poster.json")
save_json("article-json.json", article)
save_json("poster.json", poster)
for name, case in [("article-txt.txt", article), ("poster-audit.txt", poster)]:
    (ASSETS / name).write_text("公开评审成果快照 · 2026-10-19\n发布前仍需人工复核待确认事项；该文件不是实时价格信息。\n\n" + plain(case) + "\n", encoding="utf-8")
with ZipFile(ROOT / "output" / "article-zip.zip") as archive:
    for index, internal in enumerate(["media/配图1.png", "media/配图2.jpg", "media/配图3.png"], 1):
        (ASSETS / f"article-image-{index}{Path(internal).suffix}").write_bytes(archive.read(internal))
for name in ["poster.png", "poster.pdf", "scenario-platform-check.json"]:
    shutil.copyfile(ROOT / "output" / name, ASSETS / name)
save_json("strategies.json", {"scenarios": SCENARIOS, "platforms": PLATFORMS})
draft = article["三、图文软文"]
paragraphs = "".join("<p>" + html.escape(p) + "</p>" for p in draft["正文"].split("\n\n"))
image_blocks = "".join(f'<figure><img src="{html.escape(image["图片链接"])}" alt="{html.escape(image["图片说明"])}"><figcaption>{html.escape(image["图片说明"])} · 来源：<a href="{html.escape(image["来源"])}">华为官网，经 ima 产品图片索引</a></figcaption></figure>' for image in draft["图片方案"])
article_html = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(draft['标题'])}</title><style>body{{max-width:780px;margin:40px auto;padding:0 24px;font:17px/1.9 system-ui,sans-serif;color:#253247}}img{{max-width:100%;height:auto}}figcaption,aside{{font-size:14px;color:#56647a}}pre{{white-space:pre-wrap;font:14px/1.6 system-ui}}</style><article><aside>2026-10-19 真实模型成果快照 · AI 辅助创作 · 价格与发布标识待确认</aside><h1>{html.escape(draft['标题'])}</h1><p>{html.escape(draft['导语'])}</p>{paragraphs}{image_blocks}<p>{html.escape(draft['行动引导'])}</p><h2>完整依据与核验</h2><pre>{html.escape(plain({'二、知识库依据':article['二、知识库依据'],'四、核验结果':article['四、核验结果']}))}</pre></article></html>'''
(ASSETS / "article-html.html").write_text(article_html, encoding="utf-8")
with ZipFile(ASSETS / "article-zip.zip", "w", ZIP_DEFLATED) as archive:
    for name in ["article-json.json", "article-txt.txt", "article-html.html", "article-image-1.png", "article-image-2.jpg", "article-image-3.png"]:
        archive.write(ASSETS / name, name)
for path in ASSETS.iterdir():
    if path.suffix in {".json", ".txt", ".html"}:
        contents = path.read_text(encoding="utf-8")
        forbidden = [r"/api/assets/", r"/api/files/", r"/Users/", re.escape(Path.home().name), r"client_id", r"client_secret", r"api_key", r"task_id", r"shareId="]
        for pattern in forbidden:
            if re.search(pattern, contents, re.IGNORECASE):
                raise ValueError(f"Public data rejected: {path.name}, {pattern}")
print("Approved public cases, images, reports and portable article ZIP rebuilt.")
