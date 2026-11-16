"""Four-part, allowlisted public exports with verification-aware boundaries."""

from __future__ import annotations

import html
import io
import json
from pathlib import Path
import re
from urllib.parse import urlparse
import zipfile

from .policies import platform
from .settings import DATA


STATUS_NAMES = {"pass": "通过", "warning": "待确认", "blocked": "阻断", "verified": "已核实",
                "conditional": "条件报价", "excluded": "已剔除"}


def _safe_url(value):
    if not isinstance(value, str):
        return ""
    if value.startswith(("/api/assets/", "/api/files/")) and ".." not in value:
        return value
    try:
        parsed = urlparse(value)
        return value if parsed.scheme in {"https", "http"} and parsed.hostname else ""
    except ValueError:
        return ""


def _public(task):
    draft, brief = task.get("draft") or {}, task.get("brief") or {}
    checks = task.get("checks") or []
    blocked = any(item.get("status") == "blocked" for item in checks)
    warning = not checks or any(item.get("status") == "warning" for item in checks)
    pending = "待审核规则草稿，不可直接发布" if draft.get("generator") == "rules" else "待复核草稿，发布前处理待确认项"
    status = "核验阻断，仅供审核" if blocked else (pending if warning else "已完成当前核验，发布前确认时效与平台声明")
    assets = {item.get("id"): item for item in task.get("assets", [])}
    images = []
    for item in draft.get("images", []):
        asset = assets.get(item.get("id"), {})
        images.append({"图片名称": asset.get("name", "未关联图片"), "产品型号": asset.get("model", ""),
                       "来源": _safe_url(asset.get("source_url")), "资料标题": asset.get("source_title", ""),
                       "插入位置": item.get("position") or asset.get("position", ""),
                       "图片说明": item.get("caption") or asset.get("caption", ""),
                       "图片链接": _safe_url(asset.get("url")), "型号核验": "已核验" if asset.get("verified") is True else "待核验"})
    used = set(draft.get("fact_ids", []))
    facts = [{"产品型号": fact.get("model", ""), "事实点": fact.get("claim", ""),
              "资料标题": fact.get("source_title", ""), "来源": _safe_url(fact.get("source_url")),
              "核验状态": "已核验" if fact.get("verified") is True else "待核验"}
             for fact in task.get("facts", []) if fact.get("id") in used]
    quotes = []
    for quote in task.get("quotes", {}).get("quotes", []):
        quotes.append({"产品": quote.get("product_name") or quote.get("sku_key", ""),
                       "渠道": quote.get("channel", ""), "商家": quote.get("seller", ""),
                       "商品状态": quote.get("condition", ""),
                       "报价状态": STATUS_NAMES.get(quote.get("status"), "待确认"),
                       "结算金额": quote.get("checkout_amount"), "现金净支出": quote.get("estimated_cash_outlay"),
                       "旧机回收款或抵扣": quote.get("trade_in_credit"),
                       "条件估算结算额": quote.get("conditional_checkout_amount"),
                       "采集时间": quote.get("observed_at"), "失效时间": quote.get("expires_at"),
                       "来源": _safe_url(quote.get("source_url")),
                       "计算明细": [{"项目": step.get("label"), "计算前": step.get("before"),
                                     "变化金额": step.get("amount"), "计算后": step.get("after"),
                                     "来源": _safe_url(step.get("source_url"))} for step in quote.get("steps", [])],
                       "待确认": quote.get("assumptions", []), "问题": quote.get("issues", [])})
    try:
        platform_name = platform(brief.get("platform", "wechat"))["name"]
    except ValueError:
        platform_name = str(brief.get("platform", "未指定"))
    return {
        "导出状态": status,
        "一、场景判断": {"目标人群": brief.get("audience", ""), "使用场景": brief.get("scenario", ""),
                         "用户问题": brief.get("problem") or brief.get("software", ""),
                         "购买阶段": brief.get("purchase_stage", ""), "内容目标": brief.get("goal", ""),
                         "平台": platform_name, "地区": brief.get("region", "杭州")},
        "二、知识库依据": {"产品事实": facts, "实时报价依据与计算": quotes,
                           "报价边界": task.get("quotes", {}).get("warnings", [])},
        "三、图文软文": {"标题": draft.get("title", ""), "导语": draft.get("lead", ""),
                         "正文": draft.get("body", ""), "行动引导": draft.get("cta", ""),
                         "平台标签": draft.get("tags", []), "图片方案": images,
                         "海报": _safe_url(draft.get("poster_url"))},
        "四、核验结果": [{"项目": check.get("category", ""), "结果": STATUS_NAMES.get(check.get("status"), "待确认"),
                          "说明": check.get("message", "")} for check in checks],
    }


def _flatten(value, indent=0):
    lines = []
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                lines.append(" " * indent + str(key) + "：")
                lines.extend(_flatten(item, indent + 2))
            elif item not in (None, ""):
                lines.append(" " * indent + str(key) + "：" + str(item))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            if isinstance(item, (dict, list)):
                lines.append(" " * indent + f"{index + 1}.")
                lines.extend(_flatten(item, indent + 2))
            else:
                lines.append(" " * indent + "- " + str(item))
    return lines


def _plain(public):
    return "\n".join(_flatten(public)) + "\n"


def _html(public):
    def esc(value):
        return html.escape(str(value or ""), quote=True)
    def block(value):
        if isinstance(value, dict):
            return "".join(f"<div class='field'><strong>{esc(key)}</strong>{block(item)}</div>" for key, item in value.items())
        if isinstance(value, list):
            return "<ol>" + "".join("<li>" + block(item) + "</li>" for item in value) + "</ol>"
        url = _safe_url(value)
        return f"<p><a href='{esc(url)}'>{esc(value)}</a></p>" if url else f"<p>{esc(value).replace(chr(10), '<br>')}</p>"
    content = "".join(f"<section><h2>{esc(title)}</h2>{block(value)}</section>" for title, value in public.items() if title != "导出状态")
    images = public["三、图文软文"]["图片方案"]
    gallery = "".join(f"<figure><img src='{esc(item['图片链接'])}' alt='{esc(item['图片说明'])}'><figcaption>{esc(item['插入位置'])} · {esc(item['图片说明'])}</figcaption></figure>"
                      for item in images if item["图片链接"])
    title = public["三、图文软文"]["标题"] or "华为PC内容与核验报告"
    return ("<!doctype html><html lang='zh-CN'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{esc(title)}</title><style>body{{font:16px/1.7 system-ui,sans-serif;color:#18283b;background:#f4f7fb;margin:0}}"
            "main{max-width:900px;margin:32px auto;padding:32px;background:#fff;border:1px solid #e1e7ef;border-radius:20px}"
            "h1{font-size:28px}h2{font-size:21px;color:#2865c8}section{margin-top:32px}p{white-space:normal;overflow-wrap:anywhere;margin:5px 0 13px}"
            ".status{padding:12px 16px;background:#fff3d9;border-radius:10px}.field{padding:5px 0}img{max-width:100%;height:auto}"
            "figure{margin:24px 0}figcaption{color:#576a80;font-size:14px}</style><main>"
            f"<h1>{esc(title)}</h1><p class='status'>{esc(public['导出状态'])}</p>{content}{gallery}</main></html>")


def _filename(task):
    stem = str((task.get("draft") or {}).get("title") or task.get("title") or "华为PC内容")
    stem = re.sub(r"[\x00-\x1f\\/:*?\"<>|]", "_", stem).strip(" .")[:70]
    return stem or "华为PC内容"


def _poster_path(task, extension):
    url = (task.get("draft") or {}).get("poster_url", "")
    if not isinstance(url, str) or not url.startswith("/api/files/"):
        raise ValueError("尚未生成海报，请先完成主图选择与海报排版")
    filename = url.removeprefix("/api/files/")
    if not re.fullmatch(r"poster-[0-9a-f]{32}\.png", filename):
        raise ValueError("海报文件引用无效")
    path = DATA / "generated" / Path(filename).with_suffix("." + extension)
    if not path.is_file():
        raise ValueError("海报文件不存在，请重新生成海报")
    return path


def export_task(task: dict, format: str) -> tuple[bytes, str, str]:
    if format not in {"txt", "html", "json", "zip", "png", "pdf", "report"}:
        raise ValueError("不支持的导出格式")
    public = _public(task)
    if any(check.get("status") == "blocked" for check in task.get("checks", [])) and format not in {"json", "report"}:
        raise ValueError("核验存在阻断问题，不能导出正式成品；可先导出JSON或审核报告并修正问题")
    name = _filename(task)
    if format in {"png", "pdf"}:
        path = _poster_path(task, format)
        return path.read_bytes(), "image/png" if format == "png" else "application/pdf", name + "." + format
    if format == "json":
        return json.dumps(public, ensure_ascii=False, indent=2).encode(), "application/json", name + ".json"
    if format in {"txt", "report"}:
        return _plain(public).encode(), "text/plain; charset=utf-8", name + ("-审核报告.txt" if format == "report" else ".txt")
    if format == "html":
        return _html(public).encode(), "text/html; charset=utf-8", name + ".html"
    output = io.BytesIO()
    assets = {item.get("id"): item for item in task.get("assets", [])}
    packaged = json.loads(json.dumps(public, ensure_ascii=False))
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for index, image in enumerate((task.get("draft") or {}).get("images", [])):
            asset = assets.get(image.get("id"), {})
            asset_id = str(asset.get("id", ""))
            if not re.fullmatch(r"[0-9a-f]{24}", asset_id):
                raise ValueError("选中素材引用无效，无法完成素材包")
            path = DATA / "media" / (asset_id + ".image")
            if not path.is_file():
                raise ValueError("选中产品图尚未缓存，请加载原图后重新导出素材包")
            from PIL import Image
            with Image.open(path) as original:
                extension = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp", "GIF": ".gif"}.get(original.format, ".image")
            filename = f"media/配图{index + 1}{extension}"
            archive.writestr(filename, path.read_bytes())
            packaged["三、图文软文"]["图片方案"][index]["图片链接"] = filename
        if (task.get("draft") or {}).get("poster_url"):
            archive.writestr("海报.png", _poster_path(task, "png").read_bytes())
            archive.writestr("海报.pdf", _poster_path(task, "pdf").read_bytes())
            packaged["三、图文软文"]["海报"] = "海报.png"
        archive.writestr("成稿与核验.txt", _plain(packaged))
        archive.writestr("成稿与核验.json", json.dumps(packaged, ensure_ascii=False, indent=2))
        archive.writestr("index.html", _html(packaged))
    return output.getvalue(), "application/zip", name + ".zip"
