#!/usr/bin/env python3
"""Build the complete Chinese manual directly with an embedded TrueType font.

Usage (the Codex bundled Python already includes reportlab/Pillow):
  python scripts/build_manual_pdf.py
  python scripts/build_manual_pdf.py --output output/submission/作品说明书.pdf

The Markdown remains the source of truth. Only the Mermaid block is replaced by
docs/assets/architecture.png. No LibreOffice or system CJK font substitution is
used. Set MANUAL_FONT to an equivalent licensed Unicode TrueType font on Linux.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
from pathlib import Path
from urllib.parse import quote

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image, KeepTogether, LongTable, PageBreak, Paragraph, SimpleDocTemplate,
    Spacer, TableStyle,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/作品说明书.md"
DEFAULT_OUTPUT = ROOT / "output/submission/作品说明书.pdf"
FONT = Path(os.environ.get("MANUAL_FONT", "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"))
PAGE_W, PAGE_H = A4
MARGIN_X, MARGIN_TOP, MARGIN_BOTTOM = 48, 43, 43
CONTENT_W = PAGE_W - 2 * MARGIN_X
INK = colors.HexColor("#111827")
MUTED = colors.HexColor("#4b5563")
LIGHT = colors.HexColor("#f5f6f8")
BORDER = colors.HexColor("#d7dce3")


def setup_styles() -> dict[str, ParagraphStyle]:
    if not FONT.is_file():
        raise FileNotFoundError(f"Chinese TrueType font missing: {FONT}; set MANUAL_FONT")
    pdfmetrics.registerFont(TTFont("ManualUnicode", str(FONT)))
    # One embedded Unicode face for all glyphs prevents missing Chinese headings.
    pdfmetrics.registerFontFamily("ManualUnicode", normal="ManualUnicode", bold="ManualUnicode",
                                  italic="ManualUnicode", boldItalic="ManualUnicode")
    common = dict(fontName="ManualUnicode", textColor=INK, wordWrap="CJK",
                  splitLongWords=True, allowWidows=False, allowOrphans=False)
    return {
        "title": ParagraphStyle("ManualTitle", fontSize=22, leading=29, spaceAfter=14, **common),
        "h2": ParagraphStyle("ManualH2", fontSize=15, leading=22, spaceBefore=7,
                             spaceAfter=10, keepWithNext=True, **common),
        "h3": ParagraphStyle("ManualH3", fontSize=12, leading=18, spaceBefore=10,
                             spaceAfter=7, keepWithNext=True, **common),
        "body": ParagraphStyle("ManualBody", fontSize=9.8, leading=15.8, spaceAfter=6,
                               alignment=TA_LEFT, **common),
        "small": ParagraphStyle("ManualSmall", fontSize=8.5, leading=13, spaceAfter=7,
                                textColor=MUTED, fontName="ManualUnicode", wordWrap="CJK"),
        "quote": ParagraphStyle("ManualQuote", fontSize=9.7, leading=16.1,
                                leftIndent=11, rightIndent=9, borderPadding=9,
                                backColor=LIGHT, spaceBefore=3, spaceAfter=11, **common),
        "code": ParagraphStyle("ManualCode", fontSize=9.4, leading=15,
                               leftIndent=11, rightIndent=9, borderPadding=9,
                               backColor=LIGHT, spaceBefore=4, spaceAfter=10, **common),
        "cell": ParagraphStyle("ManualCell", fontSize=9.3, leading=14.2, spaceAfter=0, **common),
        "cell_header": ParagraphStyle("ManualCellHeader", fontSize=9.5, leading=14.4,
                                      spaceAfter=0, **common),
        "caption": ParagraphStyle("ManualCaption", fontSize=8.5, leading=13,
                                  alignment=TA_CENTER, spaceBefore=5, spaceAfter=6,
                                  textColor=MUTED, fontName="ManualUnicode", wordWrap="CJK"),
    }


def plain_compat(value: str) -> str:
    return value.replace("\u2011", "-").replace("\u2013", "-").replace("\u2014", "-")


def inline(text: str, repository: str | None = None) -> str:
    """Only supported Markdown markup; escape all text before ReportLab XML."""
    text = plain_compat(text)
    saved: list[str] = []

    def save(xml: str) -> str:
        saved.append(xml)
        return f"\x00{len(saved) - 1}\x00"

    def link(match: re.Match[str]) -> str:
        label, target = match.groups()
        if target.startswith(("https://", "http://")):
            return save(f'<link href="{html.escape(target, quote=True)}" color="#111827">'
                        f'{html.escape(label)}</link>')
        filename = Path(target).name
        readable = label if filename == label else f"{label}（{filename}）"
        if repository:
            resolved = (SOURCE.parent / target).resolve()
            try:
                relative = resolved.relative_to(ROOT).as_posix()
            except ValueError:
                return save(html.escape(readable))
            url = repository.rstrip("/") + "/blob/main/" + quote(relative)
            return save(f'<link href="{html.escape(url, quote=True)}" color="#111827">'
                        f'{html.escape(readable)}</link>')
        return save(html.escape(readable))

    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", link, text)
    text = re.sub(r"`([^`]+)`", lambda m: save(f'<font size="9.5">{html.escape(m[1])}</font>'), text)
    text = re.sub(r"\*\*([^*]+)\*\*", lambda m: save(html.escape(m[1])), text)
    text = html.escape(text)
    return re.sub(r"\x00(\d+)\x00", lambda m: saved[int(m[1])], text)


def fitted_image(path: Path, max_w: float, max_h: float) -> Image:
    with PILImage.open(path) as im:
        w, h = im.size
    scale = min(max_w / w, max_h / h)
    image = Image(str(path), width=w * scale, height=h * scale)
    image.hAlign = "CENTER"
    return image


def split_pages(source: str) -> list[str]:
    # Content-specific logical pages preserve every source paragraph and table.
    sections = re.split(r"(?m)^(?=## \d+\.)", source)
    if len(sections) != 8:
        raise ValueError("Manual section structure changed; expected introduction plus 7 numbered sections")
    intro, s1, s2, s3, s4, s5, s6, s7 = sections
    marker = "### 案例 B：同一任务转换为门店海报"
    before_b, after_heading = s2.split(marker, 1)
    image_match = re.search(r"!\[[^\]]*\]\([^\n]+\)", after_heading)
    if not image_match:
        raise ValueError("Poster image missing from case B")
    before_image = after_heading[:image_match.start()].strip()
    if before_image:
        raise ValueError("Unexpected prose before poster image; update deliberate pagination")
    poster_page = marker + "\n\n" + image_match.group(0)
    after_b = after_heading[image_match.end():].strip()
    # Repeat only an explicit continuation label, not factual content.
    continuation = "### 案例 B：海报生成与核验说明（续）\n\n" + after_b
    cloud_marker = "### 新增：云端接口实测"
    local_results, cloud_results = continuation.split(cloud_marker, 1)
    # Keep the short validation commands with the final limitations page so a
    # longer deployment section cannot leave a near-empty continuation page.
    check_marker = "### 检查命令"
    deployment, checks = s6.split(check_marker, 1)
    return [intro + s1, before_b, poster_page, local_results,
            cloud_marker + cloud_results, s3, s4 + s5,
            deployment, check_marker + checks + "\n\n" + s7]


def markdown_story(text: str, styles: dict[str, ParagraphStyle], repository: str | None) -> list:
    lines = text.splitlines()
    result: list = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        if line.startswith("```mermaid"):
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                i += 1
            result.append(fitted_image(ROOT / "docs/assets/architecture.png", CONTENT_W, 425))
            result.append(Paragraph("架构图：实线为已实现业务链，Dify 为待云端联调的可选编排入口。", styles["caption"]))
            i += 1
            continue
        if line.startswith("```"):
            code = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(html.escape(plain_compat(lines[i])))
                i += 1
            result.append(Paragraph("<br/>".join(code), styles["code"]))
            i += 1
            continue
        if line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-+:?", c.replace(" ", "")) for c in cells):
                    rows.append(cells)
                i += 1
            columns = len(rows[0])
            if columns == 3:
                widths = [CONTENT_W * .19, CONTENT_W * .33, CONTENT_W * .48]
            else:
                # Keep long review labels readable without starving result text.
                first = .38 if "核验项目" in rows[0][0] else .17
                widths = [CONTENT_W * first, CONTENT_W * (1 - first)]
            grid = [[Paragraph(inline(c, repository), styles["cell_header" if r == 0 else "cell"])
                     for c in row] for r, row in enumerate(rows)]
            table = LongTable(grid, colWidths=widths, repeatRows=1, hAlign="LEFT")
            padding_y = 4 if columns == 3 else 7
            table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), LIGHT),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), padding_y),
                ("BOTTOMPADDING", (0, 0), (-1, -1), padding_y),
                ("LINEBELOW", (0, 0), (-1, 0), .55, BORDER),
                ("LINEBELOW", (0, 1), (-1, -1), .35, BORDER),
                ("BOX", (0, 0), (-1, -1), .4, BORDER),
            ]))
            result.extend([table, Spacer(1, 9)])
            continue
        image = re.fullmatch(r"!\[([^\]]*)\]\(([^)]+)\)", line)
        if image:
            path = (SOURCE.parent / image.group(2)).resolve()
            # Complete 2:3 poster fills a dedicated page while keeping margins.
            result.append(fitted_image(path, CONTENT_W - 45, 650))
            result.append(Paragraph(image.group(1), styles["caption"]))
            i += 1
            continue
        if line.startswith("# "):
            result.append(Paragraph(inline(line[2:], repository), styles["title"]))
        elif line.startswith("## "):
            result.append(Paragraph(inline(line[3:], repository), styles["h2"]))
        elif line.startswith("### "):
            result.append(Paragraph(inline(line[4:], repository), styles["h3"]))
        elif line.startswith("> "):
            result.append(Paragraph(inline(line[2:], repository), styles["quote"]))
        elif re.match(r"^(?:- |\d+\. )", line):
            label = re.match(r"^(-|\d+\.) ", line).group(1)
            text = re.sub(r"^(?:- |\d+\. )", "", line)
            prefix = "• " if label == "-" else label + " "
            result.append(Paragraph(inline(prefix + text, repository), styles["body"]))
        else:
            result.append(Paragraph(inline(line, repository), styles["body"]))
        i += 1
    return result


def draw_page(canvas, doc):
    canvas.saveState()
    canvas.setFont("ManualUnicode", 8)
    canvas.setFillColor(MUTED)
    if doc.page > 1:
        canvas.drawString(MARGIN_X, PAGE_H - 25, "华为 PC 图文工作台 | 作品说明书")
    canvas.drawRightString(PAGE_W - MARGIN_X, 24, str(doc.page))
    canvas.restoreState()


def build(output: Path) -> None:
    styles = setup_styles()
    source = SOURCE.read_text(encoding="utf-8")
    manifest = json.loads((ROOT / "docs/submission-manifest.json").read_text(encoding="utf-8"))
    repository = manifest.get("links", {}).get("github")
    output.parent.mkdir(parents=True, exist_ok=True)
    story = []
    pages = split_pages(source)
    for index, page in enumerate(pages):
        if index:
            story.append(PageBreak())
        story.extend(markdown_story(page, styles, repository))
        if index == 0:
            for label, key in [("GitHub", "github"), ("魔搭展示", "modelscope")]:
                url = manifest.get("links", {}).get(key)
                if url and url not in source:
                    story.append(Paragraph(inline(f"{label}：[打开项目入口]({url})"), styles["small"]))
    doc = SimpleDocTemplate(str(output), pagesize=A4, rightMargin=MARGIN_X,
                            leftMargin=MARGIN_X, topMargin=MARGIN_TOP,
                            bottomMargin=MARGIN_BOTTOM, title="华为 PC 图文工作台 | 作品说明书",
                            author="华为 PC 图文工作台", subject="功能、真实运行结果、架构与复现说明",
                            pageCompression=1)
    doc.build(story, onFirstPage=draw_page, onLaterPages=draw_page)
    from pypdf import PdfReader
    reader = PdfReader(output)
    if not 6 <= len(reader.pages) <= 10:
        raise RuntimeError(f"Unexpected page count: {len(reader.pages)} (expected 6–10)")
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    for required in ["解决的问题", "真实运行结果", "提示词与核验设计", "ima 调用方式", "已知限制"]:
        if required not in text:
            raise RuntimeError(f"Content completeness check failed: {required}")
    print(json.dumps({"output": str(output.relative_to(ROOT)), "pages": len(reader.pages),
                      "chinese_text_extracted": "作品说明书" in text,
                      "embedded_font": FONT.name}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    build(args.output.resolve())
