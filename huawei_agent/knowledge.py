from __future__ import annotations

import asyncio
import csv
import copy
import hashlib
import io
import os
import json
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from .settings import DATA, get_ima_credentials
from .store import now

KB_NAME = "华为PC知识库1"
KB_LINK = os.environ.get("IMA_KNOWLEDGE_SHARE_URL") or "https://ima.qq.com/"


class KnowledgeError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, operation: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.operation = operation


def uid(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:24]


def official_url(text: str) -> str:
    urls = re.findall(r"https://[^\s<>\)\]，。]+", text)
    for u in sorted(urls, key=lambda x: "/specs" not in x):
        host = urlparse(u).hostname or ""
        if host == "consumer.huawei.com" or host.endswith(".huawei.com") or host.endswith(".vmall.com") or host == "www.vmall.com":
            return u.rstrip("\"'")
    return ""


class KnowledgeService:
    def __init__(self):
        self.kb_id = ""
        self.status = {"configured": all(get_ima_credentials()), "connected": False, "name": KB_NAME,
                       "message": "凭证已配置，尚未测试" if all(get_ima_credentials()) else "未配置 ima 凭证"}
        self.index: list[dict] = []
        self.discovery_index: list[dict] = []
        self._product_identities: dict[str, dict] = {}
        self._evidence_packets: dict[str, dict] = {}
        self._index_gaps: list[dict] = []
        self._index_partial = False
        self._lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(6)
        self._documents: dict[str, tuple[float, str]] = {}
        self._media_info: dict[str, dict] = {}

    async def api(self, operation: str, body: dict) -> dict:
        client_id, api_key = get_ima_credentials()
        if not client_id or not api_key:
            raise KnowledgeError("未配置 ima 凭证，请在本机 ~/.config/ima 配置或设置对应环境变量")
        async with self._semaphore, httpx.AsyncClient(timeout=40) as client:
            for attempt in range(2):
                try:
                    r = await client.post(f"https://ima.qq.com/openapi/wiki/v1/{operation}", json=body,
                                          headers={"ima-openapi-clientid": client_id, "ima-openapi-apikey": api_key})
                    # Read-only operations may encounter a short service overload. A
                    # single retry remains inside the caller's overall timeout.
                    if (attempt == 0 and operation in {"search_knowledge_base", "get_knowledge_base", "get_knowledge_list", "get_media_info", "search_knowledge"}
                            and r.status_code in {429, 502, 503, 504}):
                        await asyncio.sleep(0.3)
                        continue
                    r.raise_for_status()
                    result = r.json()
                    break
                except (httpx.HTTPError, ValueError) as e:
                    status_code = e.response.status_code if isinstance(e, httpx.HTTPStatusError) else None
                    detail = f"HTTP {status_code}" if status_code else type(e).__name__
                    raise KnowledgeError(f"ima {operation} 接口连接失败（{detail}），请检查连接后重试", status_code=status_code, operation=operation) from None
        if result.get("code") != 0:
            raise KnowledgeError(f"ima：{result.get('msg', '接口返回失败')}", operation=operation)
        return result.get("data", {})

    async def connect(self) -> dict:
        try:
            data = await self.api("search_knowledge_base", {"query": KB_NAME, "cursor": "", "limit": 20})
            matches = [x for x in data.get("info_list", []) if (x.get("kb_name") or x.get("name")) == KB_NAME]
            if len(matches) != 1:
                raise KnowledgeError("未唯一找到指定知识库，请检查凭证所属账号与共享权限")
            record = matches[0]
            self.kb_id = record.get("kb_id") or record.get("id")
            detail = await self.api("get_knowledge_base", {"ids": [self.kb_id]})
            if not any(x.get("name") == KB_NAME for x in detail.get("infos", {}).values()):
                raise KnowledgeError("知识库详情与指定名称不一致")
            self.status = {"configured": True, "connected": True, "name": KB_NAME, "message": "名称与接口权限验证通过",
                           "role": record.get("role_type", "未返回"), "checked_at": now(),
                           "identity_verified": False, "identity_note": "接口可证明当前凭证权限，未提供独立账号资料接口"}
            return self.status
        except KnowledgeError as e:
            self.status.update(connected=False, message=str(e))
            raise

    async def children(self, folder_id: str | None = None) -> list[dict]:
        if not self.kb_id:
            await self.connect()
        result, cursor, seen = [], "", set()
        while True:
            body = {"knowledge_base_id": self.kb_id, "cursor": cursor, "limit": 50}
            if folder_id:
                body["folder_id"] = folder_id
            data = await self.api("get_knowledge_list", body)
            result.extend(data.get("knowledge_list", []))
            nxt = data.get("next_cursor", "")
            if data.get("is_end", True) or not nxt or nxt in seen:
                break
            seen.add(nxt)
            cursor = nxt
        return result

    async def ensure_index(self, refresh: bool = False, *, allow_partial: bool = False):
        async with self._lock:
            if (self.index or self.discovery_index or self._index_partial) and not refresh:
                if self._index_partial and not allow_partial:
                    first = self._index_gaps[0] if self._index_gaps else {}
                    raise KnowledgeError("部分产品资料目录不可达，严格检索未使用不完整索引",
                                         status_code=first.get("http_status"), operation=first.get("operation"))
                return
            if refresh:
                self._documents.clear()
                self._media_info.clear()
                self._product_identities.clear()
                self._evidence_packets.clear()
            await self.connect()
            roots = await self.children()
            # Only the approved product parameter branch supplies product facts/assets.
            containers = roots
            for root in roots:
                if root.get("media_type") == 99 and "华为PC全板块" in root.get("title", ""):
                    containers = await self.children(root["media_id"])
                    break
            p1 = next((x for x in containers if x.get("title", "").startswith("P1-")), None)
            if not p1:
                raise KnowledgeError("未找到产品参数库目录；不会改用营销案例补充产品事实")
            index: list[dict] = []
            discovery_index: list[dict] = []
            index_gaps: list[dict] = []
            visited_count = 0
            frontier = [(p1["media_id"], p1["title"], "", False)]
            visited = set()
            for depth in range(9):
                if not frontier:
                    break
                current, frontier = frontier, []
                if allow_partial and visited_count + len(current) > 96:
                    skipped = current[max(0, 96 - visited_count):]
                    current = current[:max(0, 96 - visited_count)]
                    index_gaps.extend({"kind": "query_limit", "path": path,
                                       "message": "本轮目录读取达到96个分支上限；未读分支不代表没有匹配依据"}
                                      for _, path, _, _ in skipped)
                visited_count += len(current)
                responses = await asyncio.gather(*(self.children(fid) for fid, _, _, _ in current), return_exceptions=True)
                for (fid, parent_path, model, parent_discovery_only), items in zip(current, responses):
                    if isinstance(items, Exception):
                        if allow_partial:
                            index_gaps.append({"kind": "service_failure", "path": parent_path,
                                "operation": getattr(items, "operation", None) or "get_knowledge_list",
                                **({"http_status": items.status_code} if getattr(items, "status_code", None) else {}),
                                "message": parent_path + "目录暂不可达；保留其他已成功目录，不把该分支视为无证据"})
                            continue
                        if isinstance(items, KnowledgeError):
                            raise items
                        raise KnowledgeError(str(items))
                    visited.add(fid)
                    for item in items:
                        title = item.get("title", "")
                        path = parent_path + "/" + title
                        discovery_only = parent_discovery_only or any(x in path for x in ["官方公开价格快照", "扩展产品目录", "全库横向索引", "华为智选及生态", "型号检索卡"])
                        item_model = model
                        if item.get("media_type") == 99 and ("MateBook" in title or "擎云" in title) and not title.startswith(("01-", "02-", "03-", "04-")):
                            item_model = title
                        if item.get("media_type") == 99:
                            if item["media_id"] not in visited:
                                frontier.append((item["media_id"], path, item_model, discovery_only))
                        else:
                            entry = item | {"path": path, "model": item_model, "discovery_only": discovery_only}
                            if discovery_only:
                                discovery_index.append(entry)
                            else:
                                index.append(entry)
            if frontier:
                if not allow_partial:
                    raise KnowledgeError("目录深度超出当前索引上限，需检查目录后继续")
                index_gaps.extend({"kind": "query_limit", "path": path,
                    "message": "此分支超过目录深度上限；未读取部分不能作为无匹配的依据"} for _, path, _, _ in frontier)
            self.index = index
            self.discovery_index = discovery_index
            self._index_gaps = index_gaps
            self._index_partial = bool(index_gaps)
            (DATA / "ima_index.json").write_text(json.dumps({"updated_at": now(), "items": index,
                "partial": self._index_partial, "unreachable_branches": index_gaps}, ensure_ascii=False, indent=2), encoding="utf-8")

    async def search(self, query: str, limit: int = 12) -> list[dict]:
        await self.ensure_index()
        words = [x.lower() for x in re.split(r"[\s，,、/]+", query) if x]
        def score(item):
            t = (item["path"] + " " + item["model"]).lower()
            s = sum(8 if w in item["model"].lower() else 2 for w in words if w in t)
            if item["title"] == "产品事实.md": s += 10
            if "图片索引" in item["title"]: s += 2
            return s
        matches = [x for x in self.index if not words or any(w in (x["path"] + x["model"]).lower() for w in words)]
        return sorted(matches, key=score, reverse=True)[:limit]

    async def media_info(self, media_id: str) -> dict:
        if media_id not in self._media_info:
            self._media_info[media_id] = await self.api("get_media_info", {"media_id": media_id})
        return self._media_info[media_id]

    async def raw(self, item: dict) -> bytes:
        info = await self.media_info(item["media_id"])
        access = info.get("url_info") or {}
        if not access.get("url"):
            raise KnowledgeError("此资料无法通过接口读取原文，请使用 ima 客户端查看原文")
        async with self._semaphore, httpx.AsyncClient(timeout=45, follow_redirects=False) as client:
            try:
                r = await client.get(access["url"], headers=access.get("headers") or {})
                # Access headers from ima are not forwarded to arbitrary redirects.
                if r.status_code != 200:
                    self._media_info.pop(item["media_id"], None)
                    raise KnowledgeError("原文链接不可访问，请使用 ima 客户端查看原文")
                if len(r.content) > 25 * 1024 * 1024:
                    raise KnowledgeError("原文超过当前处理上限")
                return r.content
            except httpx.HTTPError:
                raise KnowledgeError("读取资料原文失败，请检查连接或使用 ima 客户端") from None

    async def text(self, item: dict) -> str:
        cached = self._documents.get(item["media_id"])
        if cached and time.time() - cached[0] < 3600:
            return cached[1]
        raw = await self.raw(item)
        if raw.startswith(b"%PDF"):
            text = "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(raw)).pages)
        else:
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                raise KnowledgeError("资料不是可确认的 UTF-8 文本，未做猜测性转码") from None
            if "<html" in text[:500].lower():
                text = BeautifulSoup(text, "html.parser").get_text("\n", strip=True)
        self._documents[item["media_id"]] = (time.time(), text)
        return text

    async def retrieve(self, product: str = "", software: str = "", refresh: bool = False) -> dict:
        await self.ensure_index(refresh)
        cores = [x for x in self.index if x["title"] == "产品事实.md" and x["model"]]
        # Read exact document titles before choosing a model. Folder aliases such as
        # "MateBook X系列" are not sufficient to resolve a year, OS or SKU.
        core_texts = await asyncio.gather(*(self.text(c) for c in cores))
        cores = [c | {"canonical_model": next((line.lstrip("# ").split(" - 产品事实")[0].strip()
                          for line in text.splitlines() if line.startswith("# ")), c["model"])} for c, text in zip(cores, core_texts)]
        if product:
            compact = lambda s: re.sub(r"[\s（）()_-]", "", s).lower().replace("huawei", "")
            exact = [x for x in cores if compact(product) in compact(x["canonical_model"]) or compact(x["canonical_model"]) in compact(product)]
            if not exact:
                words = re.findall(r"[A-Za-z]+|\d+|[\u4e00-\u9fff]+", product)
                exact = [x for x in cores if all(w.lower() in (x["canonical_model"] + x["model"]).lower() for w in words if w.lower() not in {"huawei", "华为"})]
            if re.search(r"鸿蒙|HarmonyOS", product, re.I):
                exact = [x for x in exact if "鸿蒙" in x["path"] or "鸿蒙" in x["canonical_model"]]
            if re.search(r"Windows|酷睿|Ultra", product, re.I):
                exact = [x for x in exact if "Windows" in x["path"] or re.search(r"酷睿|Ultra", x["canonical_model"], re.I)]
            years = re.findall(r"20\d{2}", product)
            if years:
                exact = [x for x in exact if all(y in x["canonical_model"] for y in years)]
            cores = exact
        # A requested platform/OS is a hard filter, not an inference of software compatibility.
        if re.search(r"windows|\.exe|win32", software, re.I):
            cores = [x for x in cores if "Windows" in x["path"]]
        ambiguous = [x["canonical_model"] for x in cores] if product and len(cores) > 1 else []
        cores = sorted(cores, key=lambda x: x["model"])[:4]
        facts, assets, evidence, warnings = [], [], [], []
        for core in cores:
            text = await self.text(core)
            title = next((s.lstrip("# ").split(" - 产品事实")[0].strip() for s in text.splitlines() if s.startswith("# ")), core["model"])
            source = official_url(text)
            document_id = uid(core["media_id"])
            evidence.append({"id": document_id, "title": core["model"] + "／产品事实", "source_url": source or KB_LINK,
                             "excerpt": text[:14000], "retrieved_at": now(), "kind": "ima_product_fact"})
            discovery = any(s in text for s in ["产品发现卡；尚未升级", "本条用于产品发现与检索", "待补对应规格页"])
            if discovery or not source:
                warnings.append(f"{title} 缺少完整规格依据，仅用于发现产品")
                continue
            for section in re.split(r"\n(?=## )", text):
                match = re.match(r"## ([^\n]+)\n(.*)", section.strip(), re.S)
                if not match:
                    continue
                heading, content = match.groups()
                if heading in {"来源", "官方规格摘录", "建库状态", "动态信息边界"}:
                    continue
                content = re.split(r"即将离开|您即将跳转", content)[0].strip()
                if not content or len(content) > 1800:
                    continue
                facts.append({"id": uid(core["media_id"] + heading), "product_id": uid(title), "model": title,
                              "category": heading, "claim": f"{heading}：{content}", "excerpt": content,
                              "source_title": core["model"] + "／产品事实", "source_url": source,
                              "document_id": document_id, "verified": True, "verification": "已对照ima原文；保留原文配置与测试限定", "retrieved_at": now()})
            images = [x for x in self.index if x["model"] == core["model"] and x.get("media_type") == 9]
            indexes = [x for x in self.index if x["model"] == core["model"] and "图片索引" in x["title"]]
            mapping = {}
            for index in indexes:
                csv_text = await self.text(index)
                for row in csv.DictReader(io.StringIO(csv_text)):
                    name = row.get("文件名") or row.get("图片文件名") or row.get("filename") or ""
                    if name:
                        mapping[name] = row
            for image in images[:8]:
                row = mapping.get(image["title"], {})
                row_source = row.get("页面来源") or row.get("来源页面") or row.get("source_url") or source
                # The exact product folder plus the product-specific index is required.
                verified = bool(row and source and row_source)
                asset_id = uid(image["media_id"])
                assets.append({"id": asset_id, "name": image["title"], "model": title, "product_id": uid(title),
                               "url": f"/api/assets/{asset_id}", "source_title": core["model"] + "／图片索引",
                               "source_url": row_source, "original_source": row.get("原始图片URL", ""),
                               "verified": verified, "caption": row.get("画面说明") or row.get("说明") or title,
                               "position": "正文中部", "license_status": "需按素材使用授权发布",
                               "verification": "型号目录与图片索引匹配" if verified else "缺少产品图片索引映射"})
        if not cores:
            warnings.append("没有找到匹配的完整产品档案；请明确型号，不能用相近型号补齐")
        return {"facts": facts, "assets": assets, "evidence": evidence, "warnings": warnings,
                "ambiguous_models": ambiguous,
                "catalog": sorted({x["canonical_model"] for x in cores})}

    @staticmethod
    def document_ref(item: dict) -> str:
        """Opaque references are minted from the approved index, never model output."""
        return "doc-" + uid(str(item.get("media_id", "")) + "|" + item.get("path", ""))

    @staticmethod
    def _document_kind(item: dict) -> str:
        name = item.get("title", "")
        if any(word in name for word in ("快照", "历史销售", "销售配置")):
            return "sales_snapshot"
        if name == "产品事实.md":
            return "product_fact"
        if "图片索引" in name:
            return "image_index"
        if any(word in name for word in ("卖点", "限制", "注意事项", "适用")):
            return "selling_points"
        if any(word in name for word in ("目录", "索引", "检索卡", "发现卡")):
            return "catalog"
        return "reference"

    def _discovery_items(self) -> list[dict]:
        return list({self.document_ref(x): x for x in self.index + self.discovery_index}.values())

    @staticmethod
    def _system_metadata(model: str, folder: str, text: str = "") -> dict:
        sections = re.findall(r"(?ms)^## (?:操作系统|系统)\s*\n(.*?)(?=^## |\Z)", text)
        explicit = "\n".join(sections)
        identity_text = explicit if explicit else model + " " + folder
        systems = [name for name, pattern in (("Windows", r"Windows"), ("HarmonyOS", r"鸿蒙|HarmonyOS"), ("Linux", r"Linux"))
                   if re.search(pattern, identity_text, re.I)]
        return {"system": systems[0] if len(systems) == 1 else None, "systems": systems,
                "system_source": "product_fact.operating_system" if explicit else "directory_or_title_metadata",
                "system_options_unresolved": len(systems) > 1}

    @staticmethod
    def _identity_aliases(model: str, systems: list[str]) -> list[str]:
        aliases = [model]
        for system in systems:
            suffixes = ["鸿蒙版", "HarmonyOS版"] if system == "HarmonyOS" else [system + "版"]
            aliases.extend(model + " " + suffix for suffix in suffixes)
        return list(dict.fromkeys(aliases))

    def _product_catalog(self) -> list[dict]:
        items = self._discovery_items()
        cores = [x for x in items if x.get("title") == "产品事实.md" and x.get("model")]
        # Some approved catalog folders contain only a discovery card. They remain
        # discoverable but cannot become certified product facts without originals.
        core_scopes = {x.get("path", "").rsplit("/", 1)[0] for x in cores}
        for item in items:
            scope = item.get("path", "").rsplit("/", 1)[0]
            if item.get("model") and self._document_kind(item) == "catalog" and scope not in core_scopes:
                cores.append(item)
                core_scopes.add(scope)
        catalog, seen_scopes = [], set()
        for core in cores:
            scope = core.get("path", "").rsplit("/", 1)[0]
            if scope in seen_scopes:
                continue
            seen_scopes.add(scope)
            # A product document belongs to its exact subtree, not a similar family name.
            nested_scopes = [x.get("path", "").rsplit("/", 1)[0] for x in cores
                             if x is not core and x.get("path", "").rsplit("/", 1)[0] != scope
                             and x.get("path", "").startswith(scope + "/")]
            docs = [x for x in items if x.get("media_type") != 9
                    and x.get("path", "").startswith(scope + "/")
                    and not any(x.get("path", "").startswith(other + "/") for other in nested_scopes)]
            system_metadata = self._system_metadata(core["model"], scope)
            catalog.append({"product_ref": "product-" + uid(scope),
                            "model": core["model"], "scope_path": scope,
                            "aliases": self._identity_aliases(core["model"], system_metadata["systems"]),
                            "identity_scope": {"folder": scope, "canonical_model": None,
                                               **system_metadata, "year": None, "configuration": "尚未读取事实原文"},
                            "core_document_ref": self.document_ref(core),
                            "documents": [{"document_ref": self.document_ref(x), "title": x["title"],
                                           "path": x["path"], "kind": self._document_kind(x)} for x in docs],
                            "summaries": [], "discovery_reasons": []})
        for product in catalog:
            resolved = self._product_identities.get(product["product_ref"])
            if resolved:
                product["model"] = resolved["model"]
                product["identity_scope"] = resolved["configuration_scope"]
                product["aliases"] = resolved["aliases"]
        return catalog

    def _assets_for_documents(self, catalog: list[dict], documents: list[dict]) -> list[dict]:
        assets = []
        for product in catalog:
            indexes = [d for d in documents if d["kind"] == "image_index" and d["product_ref"] == product["product_ref"]]
            if not indexes:
                continue
            resolved = self._product_identities.get(product["product_ref"], {})
            model = resolved.get("model", product["model"])
            source = resolved.get("source_url", "")
            mapping = {}
            for document in indexes:
                for row in csv.DictReader(io.StringIO(document["text"])):
                    name = row.get("文件名") or row.get("图片文件名") or row.get("filename")
                    if name:
                        mapping[name] = row
            images = []
            for item in self._discovery_items():
                if item.get("media_type") != 9 or not item.get("path", "").startswith(product["scope_path"] + "/"):
                    continue
                owners = [p for p in catalog if item.get("path", "").startswith(p["scope_path"] + "/")]
                owner = max(owners, key=lambda p: len(p["scope_path"]))
                if owner["product_ref"] == product["product_ref"]:
                    images.append(item)
            for image in images[:8]:
                row = mapping.get(image["title"], {})
                row_source = row.get("页面来源") or row.get("来源页面") or row.get("source_url") or source
                verified = bool(row and resolved.get("certified") and source and row_source and not image.get("discovery_only"))
                asset_id = uid(image["media_id"])
                assets.append({"id": asset_id, "name": image["title"], "model": model,
                    "product_id": product["product_ref"], "product_ref": product["product_ref"],
                    "aliases": resolved.get("aliases", product.get("aliases", [model])),
                    "url": f"/api/assets/{asset_id}", "source_title": model + "／图片索引",
                    "source_url": row_source, "original_source": row.get("原始图片URL", ""),
                    "verified": verified, "caption": row.get("画面说明") or row.get("说明") or model,
                    "position": "正文中部", "license_status": "需按素材使用授权发布",
                    "verification": "精确产品目录与图片索引匹配" if verified else "缺少对应产品事实或图片索引映射"})
        return assets

    def _document_packet(self, item: dict, text: str, product: dict | None) -> dict:
        document_ref = self.document_ref(item)
        kind = self._document_kind(item)
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        model = (next((line.lstrip("# ").split(" - 产品事实")[0].strip()
                       for line in text.splitlines() if line.startswith("# ")), item.get("model", ""))
                 if kind == "product_fact" else (product or {}).get("model", item.get("model", "")))
        product_ref = (product or {}).get("product_ref")
        historical = kind == "sales_snapshot" or any(w in item.get("path", "") for w in ("历史", "快照"))
        source = official_url(text)
        date = next(iter(re.findall(r"(?:资料日期|更新日期|版本日期|采集日期|抓取日期|截至)[：: \t]*(20\d{2}[-/年]\d{1,2}(?:[-/月]\d{1,2}日?)?)", text)), "")
        version = {"content_hash": content_hash, "source_date": date or item.get("updated_at") or item.get("update_time") or None,
                   "retrieved_at": now()}
        system_metadata = self._system_metadata(model, (product or {}).get("scope_path", ""), text if kind == "product_fact" else "")
        aliases = self._identity_aliases(model, system_metadata["systems"])
        scope = {"product_ref": product_ref, "model": model,
                 "folder": (product or {}).get("scope_path", ""), **system_metadata,
                 "year": next(iter(re.findall(r"20\d{2}", model)), None),
                 "configuration": "各条原文所列配置及限定；参数选项不代表可自由组合的SKU"}
        document = {"document_ref": document_ref, "product_ref": product_ref, "model": model,
                    "title": item["title"], "path": item.get("path", ""), "kind": kind,
                    "text": text[:24000], "truncated": len(text) > 24000,
                    "source_url": source or KB_LINK, "version": version,
                    "configuration_scope": scope, "historical": historical, "aliases": aliases,
                    "instruction_authority": "data_only"}
        evidence_refs, facts = [], []
        # Section offsets refer to the complete retrieved text, including all qualifiers.
        matches = list(re.finditer(r"(?m)^## ([^\n]+)\n", text))
        sections = [(m.group(1), m.start(), m.end(), matches[i + 1].start() if i + 1 < len(matches) else len(text))
                    for i, m in enumerate(matches)]
        if not sections:
            sections = [(item["title"], 0, 0, len(text))]
        is_fact = kind == "product_fact" and bool(source) and not historical and not item.get("discovery_only") and not any(
            marker in text for marker in ("产品发现卡；尚未升级", "本条用于产品发现与检索", "待补对应规格页"))
        if kind == "product_fact" and product_ref:
            self._product_identities[product_ref] = {"model": model, "configuration_scope": scope, "aliases": aliases,
                                                      "source_url": source, "certified": is_fact}
        for heading, start, body_start, end in sections:
            excerpt = text[body_start:end].strip()
            if not excerpt:
                continue
            ref_id = "ev-" + uid(document_ref + content_hash + str(start) + str(end))
            fact_id = uid(str(item["media_id"]) + content_hash + str(start))
            allowed_section = heading not in {"来源", "官方规格摘录", "建库状态", "动态信息边界"}
            fact_ids = [fact_id] if is_fact and allowed_section and len(excerpt) <= 1800 else []
            limitations = [line.strip() for line in excerpt.splitlines()
                           if re.search(r"约|最高|可选|部分|条件|仅|不支持|以.*为准|因.*而异", line)][:12]
            ref = {"id": ref_id, "product_ref": product_ref, "document_ref": document_ref,
                   "fact_ids": fact_ids, "fact_id": fact_ids[0] if fact_ids else None,
                   "excerpt": excerpt, "quote": excerpt,
                   "locator": {"path": item.get("path", ""), "heading": heading,
                               "line_start": text.count("\n", 0, start) + 1,
                               "line_end": text.count("\n", 0, end) + 1,
                               "char_start": start, "char_end": end},
                   "version": version, "configuration_scope": scope, "historical": historical,
                   "conflict": False, "limitations": limitations, "source_url": source or KB_LINK,
                   "kind": kind, "instruction_authority": "data_only"}
            evidence_refs.append(ref)
            if fact_ids:
                facts.append({"id": fact_id, "product_id": product_ref, "product_ref": product_ref,
                              "model": model, "aliases": aliases, "category": heading, "claim": f"{heading}：{excerpt}",
                              "excerpt": excerpt, "source_title": item.get("model", model) + "／产品事实",
                              "source_url": source, "document_id": document_ref, "document_ref": document_ref,
                              "evidence_ref_ids": [ref_id], "configuration_scope": scope,
                              "verified": True, "verification": "ima原文事实；适用范围与限定随原文保存",
                              "retrieved_at": version["retrieved_at"], "version": version})
        evidence = {"id": document_ref, "title": item.get("model", model) + "／" + item["title"],
                    "product_ref": product_ref, "source_url": source or KB_LINK,
                    "excerpt": text[:14000], "retrieved_at": version["retrieved_at"],
                    "kind": "ima_" + kind, "version": version, "historical": historical}
        return {"document": document, "evidence_refs": evidence_refs, "facts": facts, "evidence": evidence}

    def _check_document_conflicts(self, result: dict) -> None:
        """Compare same-folder originals; quarantine only the affected identity/attribute.

        Different option lists are a scope ambiguity, not proof that either source is
        false. Neither is silently upgraded to a current, common SKU.
        """
        touched = {d.get("product_ref") for d in result["documents"] if d.get("product_ref")}
        packets = [p for p in self._evidence_packets.values() if p["document"].get("product_ref") in touched]
        facts = [copy.deepcopy(f) for p in packets for f in p["facts"]]
        refs = {r["id"]: copy.deepcopy(r) for p in packets for r in p["evidence_refs"]}
        compact = lambda value: re.sub(r"\s+", "", str(value)).lower()
        numerical = lambda value: {(m.group(2).lower(), m.group(1)) for m in re.finditer(
            r"(\d+(?:\.\d+)?)\s*(GB|TB|GHz|kg|Wh|mm|Hz|英寸|小时|核|线程|%)", value, re.I)}
        grouped = {}
        for fact in facts:
            grouped.setdefault((fact["product_ref"], fact["category"]), []).append(fact)
        for (product_ref, category), items in grouped.items():
            documents = list(dict.fromkeys(f["document_ref"] for f in items))
            for fact in items:
                fact["conflict"] = False
                fact["conflict_check"] = {"status": "single_source" if len(documents) == 1 else "compared_originals",
                                          "document_refs": documents}
                for ref_id in fact.get("evidence_ref_ids", []):
                    refs[ref_id]["conflict_check"] = fact["conflict_check"]
            for i, left in enumerate(items):
                for right in items[i + 1:]:
                    if left["id"] == right["id"] or compact(left["excerpt"]) == compact(right["excerpt"]):
                        continue
                    identity_conflict = compact(left["model"]) != compact(right["model"])
                    a, b = numerical(left["excerpt"]), numerical(right["excerpt"])
                    common_units = {unit for unit, _ in a} & {unit for unit, _ in b}
                    different_specs = any({v for u, v in a if u == unit}.isdisjoint({v for u, v in b if u == unit})
                                          for unit in common_units)
                    def compat(text):
                        return [(m.group(1), compact(m.group(2))) for m in re.finditer(
                            r"(不支持|不兼容|不可用|支持|兼容)([^，。；\n]{1,50})", text)]
                    opposition = any((x.startswith("不") != y.startswith("不")) and tx == ty
                                     for x, tx in compat(left["excerpt"]) for y, ty in compat(right["excerpt"]))
                    if not (identity_conflict or different_specs or opposition):
                        continue
                    conflict_type = "identity_conflict" if identity_conflict else "contradiction" if opposition else "configuration_scope_ambiguity"
                    ids = [left["id"], right["id"]]
                    for fact in (left, right):
                        fact.update(conflict=True, verified=False, conflict_type=conflict_type,
                                    conflicting_fact_ids=[x for x in ids if x != fact["id"]])
                        for ref_id in fact.get("evidence_ref_ids", []):
                            refs[ref_id].update(conflict=True, conflict_type=conflict_type,
                                               conflicting_fact_ids=ids)
                    if identity_conflict and product_ref in self._product_identities:
                        self._product_identities[product_ref]["certified"] = False
                    result["gaps"].append({"kind": "evidence_conflict", "product_ref": product_ref,
                        "attribute": category, "fact_ids": ids, "conflict_type": conflict_type,
                        "message": "同产品目录原文的身份、参数或配置范围不一致；隔离此项，未按抓取日期择一合并"})
        identities = {}
        for packet in packets:
            document = packet["document"]
            if document["kind"] == "product_fact":
                identities.setdefault(document["product_ref"], set()).add(compact(document["model"]))
        ambiguous_products = {key for key, models in identities.items() if len(models) > 1}
        for fact in facts:
            if fact["product_ref"] in ambiguous_products:
                fact.update(conflict=True, verified=False, conflict_type="identity_conflict")
                for ref_id in fact.get("evidence_ref_ids", []):
                    refs[ref_id].update(conflict=True, conflict_type="identity_conflict")
        for product_ref in ambiguous_products:
            self._product_identities[product_ref]["certified"] = False
            result["gaps"].append({"kind": "evidence_conflict", "product_ref": product_ref,
                "attribute": "product_identity", "conflict_type": "identity_conflict",
                "message": "同目录原文标注了不同系统、年份或型号，未将其参数与图片混为一个产品"})
        # Include prior originals when their status changed, so ID-based merge invalidates
        # previously usable support rather than leaving stale verified rows in the task.
        current = {f["id"]: f for f in result["facts"]}
        current.update({f["id"]: f for f in facts})
        result["facts"] = list(current.values())
        existing_refs = {r["id"]: r for r in result["evidence_refs"]}
        existing_refs.update(refs)
        result["evidence_refs"] = list(existing_refs.values())

    async def read_documents(self, refs: list[str], *, max_reads: int = 8, timeout_seconds: float = 50) -> dict:
        """Read only document references already returned by the approved catalog."""
        started = time.monotonic()
        result = {"documents": [], "facts": [], "assets": [], "evidence": [], "evidence_refs": [],
                  "gaps": [], "warnings": []}
        limit = min(max(int(max_reads), 0), 32)
        timeout_seconds = min(max(float(timeout_seconds), 0.01), 120)
        try:
            await asyncio.wait_for(self.ensure_index(allow_partial=True), timeout_seconds)
        except (KnowledgeError, asyncio.TimeoutError) as exc:
            result["gaps"].append({"kind": "service_failure", "message": str(exc) or "ima目录读取超时",
                                   **({"http_status": exc.status_code} if getattr(exc, "status_code", None) else {}),
                                   **({"operation": exc.operation} if getattr(exc, "operation", None) else {})})
            return result
        result["gaps"].extend(copy.deepcopy(self._index_gaps))
        catalog = self._product_catalog()
        products_by_ref = {d["document_ref"]: p for p in catalog for d in p["documents"]}
        items = {self.document_ref(x): x for x in self._discovery_items() if x.get("media_type") != 9}
        unique = []
        for ref in refs if isinstance(refs, list) else []:
            if not isinstance(ref, str):
                result["gaps"].append({"kind": "invalid_reference", "message": "文档引用必须是已提供的字符串引用"})
            elif ref not in unique:
                unique.append(ref)
        reads = 0
        for reference in unique:
            if not isinstance(reference, str) or reference not in items:
                result["gaps"].append({"kind": "invalid_reference", "document_ref": str(reference)[:120],
                                       "message": "文档引用不在已授权索引中；未执行读取"})
                continue
            remaining = timeout_seconds - (time.monotonic() - started)
            if reads >= limit or remaining <= 0:
                result["gaps"].append({"kind": "query_limit", "document_ref": reference,
                                       "message": "本轮读取次数或耗时达到上限，未推断资料内容"})
                continue
            reads += 1
            try:
                text = await asyncio.wait_for(self.text(items[reference]), remaining)
                packet = self._document_packet(items[reference], text, products_by_ref.get(reference))
                previous = self._evidence_packets.get(reference)
                if previous and previous["document"]["version"]["content_hash"] != packet["document"]["version"]["content_hash"]:
                    for fact in previous["facts"]:
                        result["facts"].append(dict(fact, verified=False, superseded=True))
                    for ref in previous["evidence_refs"]:
                        result["evidence_refs"].append(dict(ref, superseded=True))
                self._evidence_packets[reference] = copy.deepcopy(packet)
                result["documents"].append(packet["document"])
                result["facts"].extend(packet["facts"])
                result["evidence_refs"].extend(packet["evidence_refs"])
                result["evidence"].append(packet["evidence"])
            except asyncio.TimeoutError:
                result["gaps"].append({"kind": "service_failure", "document_ref": reference, "message": "ima原文读取超时"})
            except KnowledgeError as exc:
                kind = "original_unreachable" if any(w in str(exc) for w in ("原文", "客户端", "资料不是")) else "service_failure"
                result["gaps"].append({"kind": kind, "document_ref": reference, "message": str(exc),
                                       **({"http_status": exc.status_code} if getattr(exc, "status_code", None) else {}),
                                   **({"operation": exc.operation} if getattr(exc, "operation", None) else {})})
            except (ValueError, OSError, PdfReadError):
                result["gaps"].append({"kind": "original_unreachable", "document_ref": reference,
                                       "message": "原文格式无法解析，已保留其他成功读取的证据"})
        self._check_document_conflicts(result)
        result["catalog"] = self._product_catalog()
        result["assets"] = self._assets_for_documents(result["catalog"], result["documents"])
        result["budget"] = {"reads": reads, "limit": limit, "elapsed_seconds": round(time.monotonic() - started, 3)}
        return result

    @staticmethod
    def _context_terms(context: dict, queries: list[str] | None = None) -> list[str]:
        pieces = []
        def collect(value):
            if isinstance(value, str):
                pieces.append(value)
            elif isinstance(value, list):
                for child in value:
                    collect(child)
            elif isinstance(value, dict):
                # Provenance/reason text and backend IDs do not become search intent.
                for key in ("value", "name", "task", "description", "audience", "use_tasks", "communication_contexts", "conditions", "content_task"):
                    if key in value:
                        collect(value[key])
        collect(context)
        collect(queries or [])
        text = " ".join(pieces)
        seeds = re.findall(r"[A-Za-z][A-Za-z0-9.+-]*|[\u4e00-\u9fff]{2,}", text)
        topics = {"建模": ["建模", "三维", "设计", "兼容"], "编程": ["编程", "开发", "系统"],
                  "AI": ["AI", "人工智能"], "携带": ["携带", "便携", "重量"],
                  "学习": ["学习", "课堂", "文档"], "学生": ["学生", "校园", "学习"],
                  "办公": ["办公", "会议", "文档"], "剪辑": ["剪辑", "视频", "创作"],
                  "网页版": ["网页版", "浏览器", "联网"], "续航": ["续航", "电池"]}
        terms = [word for key, words in topics.items() if key.lower() in text.lower() for word in words]
        terms.extend(seed for seed in seeds if len(seed) <= 40)
        return list(dict.fromkeys(w.lower() for w in terms))[:60]

    @staticmethod
    def _model_matches(requested: str, model: str, *, strict: bool = True) -> bool:
        compact = lambda s: re.sub(r"[\s（）()_\-]", "", s).lower().replace("huawei", "").replace("华为", "")
        a, b = compact(requested), compact(model)
        if not a or not b:
            return False
        if strict:
            if any(y not in b for y in re.findall(r"20\d{2}", a)):
                return False
            if re.search(r"鸿蒙|harmonyos", a) and not re.search(r"鸿蒙|harmonyos", b):
                return False
            if "windows" in a and "windows" not in b:
                return False
        def contained(left, right):
            if left not in right:
                return False
            suffix = right[right.index(left) + len(left):]
            return not suffix or bool(re.match(r"^(?:20\d{2}|windows|harmonyos|鸿蒙|非凡大师|酷睿|ultra|版|笔记本|电脑)", suffix))
        if contained(a, b) or contained(b, a):
            return True
        if not strict:
            base = re.sub(r"20\d{2}|鸿蒙版|windows版|harmonyos", "", a)
            family = re.sub(r"系列$", "", b)
            return bool(base and (contained(base, b) or (family and base.startswith(family))))
        return False

    async def discover(self, context: dict, refresh: bool = False, *, queries: list[str] | None = None,
                       document_refs: list[str] | None = None, max_reads: int = 18,
                       timeout_seconds: float = 50) -> dict:
        """Bounded two-stage discovery. Relevance is a lookup hint, never a fit score."""
        started = time.monotonic()
        result = {"catalog": [], "facts": [], "assets": [], "evidence": [], "evidence_refs": [],
                  "gaps": [], "warnings": [], "ambiguous_models": []}
        max_reads = min(max(int(max_reads), 0), 32)
        timeout_seconds = min(max(float(timeout_seconds), 0.01), 120)
        try:
            await asyncio.wait_for(self.ensure_index(refresh, allow_partial=True), timeout_seconds)
        except (KnowledgeError, asyncio.TimeoutError) as exc:
            result["gaps"].append({"kind": "service_failure", "message": str(exc) or "ima目录读取超时",
                                   **({"http_status": exc.status_code} if getattr(exc, "status_code", None) else {}),
                                   **({"operation": exc.operation} if getattr(exc, "operation", None) else {})})
            return result
        result["gaps"].extend(copy.deepcopy(self._index_gaps))
        result["index_partial"] = self._index_partial
        catalog = self._product_catalog()
        if not catalog:
            result["gaps"].append({"kind": "evidence_missing" if self._index_partial else "no_match",
                "message": "已成功读取的目录中尚无可定位档案；仍有目录不可达，不能认定全库无匹配" if self._index_partial else "已授权产品目录中没有可定位的产品档案"})
            return result
        intent = context.get("product_intent") or {}
        selected = [x for x in intent.get("selected", []) if isinstance(x, str)]
        compared = [x for x in intent.get("compare", []) if isinstance(x, str)]
        requested = list(dict.fromkeys(selected + compared))
        terms = self._context_terms(context, queries)
        def relevance(product):
            searchable = (product["model"] + " " + " ".join(s.get("excerpt", "") for s in product["summaries"])).lower()
            product["discovery_reasons"] = [term for term in terms if term in searchable]
            priority = 1000 if any(self._model_matches(x, product["model"], strict=False) for x in selected) else 500 if any(self._model_matches(x, product["model"], strict=False) for x in compared) else 0
            return priority + len(product["discovery_reasons"])
        catalog.sort(key=relevance, reverse=True)
        # Read brief selling/limitation documents across the catalog before selecting facts.
        summaries = [(p, d) for p in catalog for d in p["documents"] if d["kind"] in {"selling_points", "catalog"}]
        summary_budget = min(len(summaries), max_reads // 2)
        refs = [d["document_ref"] for _, d in summaries[:summary_budget]]
        read = await self.read_documents(refs, max_reads=summary_budget,
                                         timeout_seconds=max(.01, timeout_seconds - (time.monotonic() - started)))
        reads = read.get("budget", {}).get("reads", 0)
        packets = list(read["documents"])
        for key in ("facts", "evidence", "evidence_refs", "gaps", "warnings"):
            result[key].extend(read[key])
        for product in catalog:
            for document in read["documents"]:
                if document["product_ref"] == product["product_ref"]:
                    product["summaries"].append({"document_ref": document["document_ref"], "kind": document["kind"],
                                                  "excerpt": document["text"], "instruction_authority": "data_only"})
        catalog.sort(key=relevance, reverse=True)
        # Exact user choice is preserved, including evidence that could contradict it.
        relevant = [p for p in catalog if not requested or any(self._model_matches(x, p["model"], strict=False) for x in requested)]
        if requested and not relevant:
            # Folder aliases may omit OS/year/product suffix. Read bounded originals
            # to resolve identity; the strict post-read filter still forbids substitution.
            relevant = list(catalog)
        # Reserve existing image-index reads for each candidate whose facts are read.
        # This preserves the generator's original image contract within the same budget.
        remaining = max_reads - reads
        fact_refs, reserved_images = [], 0
        for product in relevant:
            image_count = sum(d["kind"] == "image_index" for d in product["documents"])
            if len(fact_refs) + 1 + reserved_images + image_count > remaining:
                break
            core_refs = [d["document_ref"] for d in product["documents"] if d["kind"] == "product_fact"] or [product["core_document_ref"]]
            if len(fact_refs) + len(core_refs) + reserved_images + image_count > remaining:
                break
            fact_refs.extend(core_refs)
            reserved_images += image_count
        # Explicit read actions must still be catalog references and share the same budget.
        fact_refs = list(dict.fromkeys((document_refs or []) + fact_refs))
        read = await self.read_documents(fact_refs[:max(0, remaining - reserved_images)], max_reads=remaining,
                                         timeout_seconds=max(.01, timeout_seconds - (time.monotonic() - started)))
        reads += read.get("budget", {}).get("reads", 0)
        packets.extend(read["documents"])
        for key in ("facts", "evidence", "evidence_refs", "gaps", "warnings"):
            result[key].extend(read[key])
        for product in catalog:
            core = next((d for d in packets if d["document_ref"] == product["core_document_ref"]), None)
            if core:
                product["model"] = core["model"]
                product["identity_scope"] = core["configuration_scope"]
                product["aliases"] = core["aliases"]
            product["selected_match"] = any(self._model_matches(x, alias) for x in selected for alias in product.get("aliases", [product["model"]]))
            product["comparison_match"] = any(self._model_matches(x, alias) for x in compared for alias in product.get("aliases", [product["model"]]))
        if requested:
            allowed = {p["product_ref"] for p in catalog if p["selected_match"] or p["comparison_match"]}
            for key in ("facts", "evidence_refs"):
                result[key] = [x for x in result[key] if x.get("product_ref") in allowed]
            if selected and not any(p["selected_match"] for p in catalog):
                result["gaps"].append({"kind": "no_match", "message": "尚未取得指定产品版本的有效依据；保留用户选择，不替换为其他型号"})
        else:
            allowed = {p["product_ref"] for p in catalog if any(f["product_ref"] == p["product_ref"] for f in result["facts"])}
        # Images retain the existing original-image/index association, now scoped by exact folder.
        image_refs = []
        for product in catalog:
            if product["product_ref"] in allowed:
                image_refs.extend(d["document_ref"] for d in product["documents"] if d["kind"] == "image_index")
        remaining = max_reads - reads
        read = await self.read_documents(image_refs[:remaining], max_reads=remaining,
                                         timeout_seconds=max(.01, timeout_seconds - (time.monotonic() - started)))
        reads += read.get("budget", {}).get("reads", 0)
        for key in ("facts", "evidence", "evidence_refs", "gaps", "warnings"):
            result[key].extend(read[key])
        result["assets"] = [a for a in read["assets"] if a.get("product_ref") in allowed]
        if len(summaries) > summary_budget or len(fact_refs) < len(relevant):
            result["gaps"].append({"kind": "query_limit", "message": "目录尚有未读资料，可在剩余额度内定向读取；未读资料不代表无适配产品"})
        if not result["facts"] and not any(g["kind"] in {"service_failure", "original_unreachable", "no_match"} for g in result["gaps"]):
            result["gaps"].append({"kind": "evidence_missing", "message": "已读资料尚不足以支持产品事实；可缩小结论或定向补查"})
        for key in ("facts", "assets", "evidence", "evidence_refs"):
            result[key] = list({x["id"]: x for x in result[key]}.values())
        result["gaps"] = list({json.dumps(g, ensure_ascii=False, sort_keys=True): g for g in result["gaps"]}.values())
        result["catalog"] = catalog
        result["index_partial"] = self._index_partial
        result["budget"] = {"reads": reads, "limit": max_reads, "elapsed_seconds": round(time.monotonic() - started, 3)}
        return result

    async def asset_bytes(self, asset_id: str) -> tuple[bytes, str]:
        # An already indexed exact image does not depend on an unrelated failed branch.
        if not any(uid(x["media_id"]) == asset_id and x.get("media_type") == 9 for x in self.index):
            await self.ensure_index()
        item = next((x for x in self.index if uid(x["media_id"]) == asset_id and x.get("media_type") == 9), None)
        if not item:
            raise KeyError("素材不存在")
        path = DATA / "media" / (asset_id + ".image")
        if path.exists():
            raw = path.read_bytes()
        else:
            raw = await self.raw(item)
            from PIL import Image
            try:
                with Image.open(io.BytesIO(raw)) as im:
                    im.verify()
            except Exception:
                raise KnowledgeError("素材不是可确认的有效图片") from None
            path.write_bytes(raw)
        import mimetypes
        return raw, mimetypes.guess_type(item["title"])[0] or "image/jpeg"


knowledge = KnowledgeService()
