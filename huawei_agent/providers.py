from __future__ import annotations

import asyncio
import hashlib
import hmac
import json

import httpx

from .settings import load_settings


class ProviderError(RuntimeError):
    pass


async def json_chat(system: str, payload: dict, *, vision_images: list[str] | None = None) -> dict:
    s = load_settings()
    vision = vision_images is not None
    key = s["dashscope_api_key"] if vision else s["deepseek_api_key"]
    if not key:
        raise ProviderError("视觉模型尚未配置" if vision else "DeepSeek 尚未配置")
    base = (s["dashscope_base_url"] + "/compatible-mode/v1") if vision else s["deepseek_base_url"]
    content: str | list = json.dumps(payload, ensure_ascii=False)
    if vision:
        content = [{"type": "text", "text": content}] + [{"type": "image_url", "image_url": {"url": u}} for u in vision_images]
    body = {"model": s["vision_model"] if vision else s["text_model"],
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}],
            "temperature": 0.2, "max_tokens": 5000, "response_format": {"type": "json_object"}}
    if vision:
        body["enable_thinking"] = False
    else:
        body["thinking"] = {"type": "disabled"}
    for attempt in range(2):
        async with httpx.AsyncClient(timeout=120) as client:
            try:
                r = await client.post(base.rstrip("/") + "/chat/completions", json=body,
                                      headers={"Authorization": f"Bearer {key}"})
                if r.status_code != 200:
                    raise ProviderError(f"模型接口返回 HTTP {r.status_code}，请检查模型、地域、额度和凭证")
                data = r.json()
                text = data["choices"][0]["message"].get("content", "")
                if not isinstance(text, str):
                    raise ValueError("content is not a string")
                if text.startswith("```"):
                    text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
                parsed = json.loads(text)
                if not isinstance(parsed, dict):
                    raise ValueError("not an object")
                return parsed
            except (json.JSONDecodeError, KeyError, IndexError, ValueError):
                if attempt:
                    raise ProviderError("模型两次未返回可解析的 JSON，未使用不完整内容") from None
            except httpx.HTTPError:
                raise ProviderError("模型接口连接失败或超时，未生成结果") from None
    raise ProviderError("模型返回为空")


async def dify_chat(message: str, task_id: str, conversation_id: str = "") -> dict:
    s = load_settings()
    if not s["dify_api_key"]:
        raise ProviderError("Dify 尚未配置")
    async with httpx.AsyncClient(timeout=180) as client:
        try:
            r = await client.post(s["dify_base_url"].rstrip("/") + "/chat-messages",
                headers={"Authorization": f"Bearer {s['dify_api_key']}"},
                json={"inputs": {"task_id": task_id, "user": "local", "context_token": hmac.new(s["tool_token"].encode(), ("local:" + task_id).encode(), hashlib.sha256).hexdigest()}, "query": message, "response_mode": "blocking",
                      "conversation_id": conversation_id, "user": "huawei-pc-local"})
            if r.status_code != 200:
                raise ProviderError(f"Dify 返回 HTTP {r.status_code}，请检查应用类型、API Key、工作流和服务地址")
            data = r.json()
            if data.get("event") == "error" or data.get("code"):
                raise ProviderError("Dify 应用执行失败，请查看工作区运行日志")
            return data
        except httpx.HTTPError:
            raise ProviderError("Dify 连接失败或运行超时，请检查云端节点记录后重试") from None


async def search_prices(brief: dict) -> tuple[list[dict], list[str]]:
    s = load_settings()
    if not s["tavily_api_key"] and not s["deepseek_api_key"]:
        return [], ["联网搜索未配置；可导入可追溯的商家报价。当前不生成实时价格或优惠承诺。"]
    query = f"{brief.get('region','杭州')} {brief.get('product') or '华为 MateBook 电脑'} 当前价格 优惠 教育优惠 国补 " + " ".join(brief.get("channels", []))
    async with httpx.AsyncClient(timeout=50) as client:
        try:
            if s["deepseek_api_key"]:
                r = await client.post(s["deepseek_base_url"].rstrip("/").removesuffix("/v1") + "/v1/tools/search",
                    headers={"Authorization": f"Bearer {s['deepseek_api_key']}"},
                    json={"query": query[:128], "count": 12, "need_content": True})
            else:
                r = await client.post("https://api.tavily.com/search", headers={"Authorization": f"Bearer {s['tavily_api_key']}"},
                                  json={"query": query, "search_depth": "basic", "max_results": 12,
                                        "include_answer": False, "include_raw_content": True, "time_range": "month"})
            if r.status_code != 200:
                raise ProviderError(f"联网搜索返回 HTTP {r.status_code}")
            data = r.json()
            records = [{"title": x.get("title", ""), "source_url": x.get("url", ""),
                        "excerpt": str(x.get("raw_content") or x.get("content") or x.get("snippet") or x.get("summary") or "")[:10000],
                        "verified": False, "kind": "price_discovery"} for x in r.json().get("results", [])]
        except httpx.HTTPError:
            raise ProviderError("联网搜索连接失败；未生成价格") from None
    return records, ["搜索结果仅是报价线索。需确认商家、精确 SKU、库存、时间、优惠条件后，才能进入已核实最低价。"]


async def generate_background(prompt: str) -> str:
    s = load_settings()
    if not s["dashscope_api_key"]:
        raise ProviderError("Qwen-Image 尚未配置")
    # Async generation avoids keeping the provider connection open during image inference.
    body = {"model": s["image_model"], "input": {"messages": [{"role": "user", "content": [{"text":
        "为电脑营销海报生成背景。只生成没有产品、电脑、品牌标志、文字、价格和二维码的环境或抽象背景；中下部留干净空间。" + prompt}]}]},
        "parameters": {"size": "1024*1536", "n": 1, "watermark": True}}
    headers = {"Authorization": f"Bearer {s['dashscope_api_key']}", "X-DashScope-Async": "enable"}
    async with httpx.AsyncClient(timeout=60) as client:
        try:
            r = await client.post(s["dashscope_base_url"].rstrip("/") + "/api/v1/services/aigc/image-generation/generation", json=body, headers=headers)
            if r.status_code != 200:
                raise ProviderError(f"图像接口返回 HTTP {r.status_code}，请检查模型与地域")
            task_id = r.json().get("output", {}).get("task_id")
            if not task_id:
                raise ProviderError("图像接口没有返回任务编号")
            for _ in range(90):
                await asyncio.sleep(2)
                result = await client.get(s["dashscope_base_url"].rstrip("/") + "/api/v1/tasks/" + task_id, headers={"Authorization": headers["Authorization"]})
                if result.status_code != 200:
                    raise ProviderError(f"图像任务查询返回 HTTP {result.status_code}，未接受无效结果")
                data = result.json()
                status = data.get("output", {}).get("task_status")
                if status == "SUCCEEDED":
                    output = data.get("output", {})
                    if output.get("results"):
                        return output["results"][0]["url"]
                    choices = output.get("choices", [])
                    for choice in choices:
                        for item in choice.get("message", {}).get("content", []):
                            if item.get("image"):
                                return item["image"]
                    raise ProviderError("图像任务成功但未返回图片地址")
                if status in {"FAILED", "CANCELED", "UNKNOWN"}:
                    raise ProviderError("图像任务失败，未替换已有背景")
            raise ProviderError("图像生成超时，可稍后重新生成背景")
        except httpx.HTTPError:
            raise ProviderError("图像接口连接失败，未替换已有背景") from None
