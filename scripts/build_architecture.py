#!/usr/bin/env python3
"""Rebuild the committed architecture PNG; Pillow and a CJK font are required.

The manual PDF can use docs/assets/architecture.png directly; running this script
is only necessary after the architecture content changes. --font or MANUAL_FONT
selects a local font without storing machine-specific user paths in source.
"""
from __future__ import annotations

import argparse
import os
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "docs/assets/architecture.png"


def choose_font(explicit: Path | None = None) -> Path:
    configured = explicit or (Path(os.environ["MANUAL_FONT"]) if os.environ.get("MANUAL_FONT") else None)
    if configured:
        if not configured.is_file():
            raise FileNotFoundError("Configured CJK font does not exist; check --font or MANUAL_FONT")
        return configured
    candidates = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansSC-Regular.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "C:/Windows/Fonts/msyh.ttc",
    ]
    for candidate in candidates:
        if Path(candidate).is_file():
            return Path(candidate)
    raise RuntimeError("Install a CJK font and select it with --font or MANUAL_FONT")


def build(output: Path = DEFAULT_OUTPUT, font_path: Path | None = None) -> Path:
    selected_font = choose_font(font_path)

    @lru_cache(maxsize=8)
    def font(size: int):
        return ImageFont.truetype(str(selected_font), size)

    im = Image.new("RGB", (1700, 1050), "white")
    dr = ImageDraw.Draw(im)

    def box(x, y, width, height, title, lines):
        dr.rounded_rectangle((x, y, x + width, y + height), radius=18,
                             fill="#F6F8FB", outline="#CFD7E3", width=2)
        dr.text((x + 24, y + 20), title, font=font(30), fill="#172438")
        for i, line in enumerate(lines):
            dr.text((x + 24, y + 68 + i * 40), line, font=font(25), fill="#4C5C70")

    def arrow(start, end):
        dr.line((start, end), fill="#5B718E", width=4)
        x, y = end
        dr.polygon([(x, y), (x - 13, y - 8), (x - 13, y + 8)], fill="#5B718E")

    box(35, 35, 470, 175, "图形工作台", ["对话与需求卡 · 四平台预览", "人工修改 · 核验与导出"])
    box(615, 35, 470, 175, "自研 Agent 业务流", ["场景解析 → 检索 → 生成", "事实与图片核验 → 合规检查"])
    box(1195, 35, 470, 175, "任务与交付", ["SQLite 任务与版本 · 私有缓存", "TXT / HTML / JSON / ZIP / PNG / PDF"])
    arrow((505, 120), (615, 120))
    arrow((1085, 120), (1195, 120))
    dr.line((850, 210, 850, 270), fill="#5B718E", width=4)
    dr.line((275, 270, 1425, 270), fill="#5B718E", width=3)
    for x in [275, 850, 1425]:
        dr.line((x, 270, x, 315), fill="#5B718E", width=3)
    box(35, 315, 500, 205, "ima 产品事实与原图",
        ["指定共享库与产品索引", "参数、限定、来源及型号关联", "凭证仅在服务端使用"])
    box(600, 315, 500, 205, "DeepSeek 与规则引擎",
        ["文本生成及语义辅助审校", "Search 只发现价格线索", "Decimal 引擎按已核实规则计算"])
    box(1165, 315, 500, 205, "Qwen 图像与视觉",
        ["Qwen-Image 仅生成背景", "ima 产品原图等比例贴层", "像素证明与视觉辅助核验"])
    box(35, 625, 1630, 155, "可选 Dify 云端编排",
        ["Chatflow / Workflow → 已鉴权 HTTPS 回调 → 同一自研后端与数据库",
         "已提供四份 DSL 与工具契约；Dify Cloud 导入及公网回调尚待真实验证"])
    dr.text((40, 845), "证据边界", font=font(30), fill="#172438")
    for i, line in enumerate([
        "产品事实与主体原图来自 ima；价格线索经过商家、SKU、时效与资格核实后才计算。",
        "模型负责内容表达与辅助审校；检查阻断时仅保留审核报告，不能正式复制与导出。",
        "公开评审页只展示已生成成果，不提供共享密钥或公开付费推理入口。",
    ]):
        dr.text((40, 900 + i * 43), line, font=font(25), fill="#4C5C70")
    output.parent.mkdir(parents=True, exist_ok=True)
    im.save(output)
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--font", type=Path)
    args = parser.parse_args()
    path = build(args.output, args.font)
    print(f"Architecture generated: {path.name} (1700 x 1050)")
