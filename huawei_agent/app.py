from __future__ import annotations

import asyncio
import base64
import getpass
import hashlib
import hmac
import io
import ipaddress
import json
import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote, urlparse

import httpx
from fastapi import Body, Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from .knowledge import KnowledgeError, knowledge
from . import auth
from .policies import CHANNELS, PLATFORMS, SCENARIOS, platform
from .pricing import calculate_quotes
from .providers import ProviderError, dify_chat, generate_background, json_chat, search_prices
from .settings import DATA, ROOT, allowed_origins, configured, dify_ready, hosted, load_settings, managed_config, save_settings
from .store import create_task, get_task, list_tasks, restore, save_task
from .validation import reconcile_visual_evidence, validate, review_recommendation_claims
from .task_context import ensure_context, apply_brief_save
from .workflow import chat_task, generate_task, retrieve_task, task_lock, verify_task

CONNECTION_RESULTS: dict[str, dict] = {}
logger = logging.getLogger(__name__)


def _diagnostic_authority(value: str) -> tuple[str, int | None]:
    """Return only a bounded, valid DNS/IP host and port, never raw input."""
    if (not isinstance(value, str) or len(value) > 300 or not value.isascii()
            or any(ord(char) <= 32 or ord(char) == 127 or char in "\\/@?#%" for char in value)):
        return "invalid", None
    try:
        parsed = urlparse("//" + value)
        name = parsed.hostname
        port = parsed.port
        if not name or parsed.path or parsed.query or parsed.fragment or value.endswith(":"):
            return "invalid", None
        if port is not None and not 1 <= port <= 65535:
            return "invalid", None
        if ":" in name:
            name = ipaddress.IPv6Address(name).compressed
        elif (len(name) > 253 or any(not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
                for label in name.rstrip(".").split("."))):
            return "invalid", None
        return name.lower(), port
    except ValueError:
        return "invalid", None


def _diagnostic_origin(value: str | None) -> tuple[str, str, int | str]:
    if not isinstance(value, str) or len(value) > 512:
        return "invalid", "invalid", "invalid"
    try:
        parsed = urlparse(value)
        if parsed.scheme not in {"https", "http"} or parsed.path or parsed.params or parsed.query or parsed.fragment:
            return "invalid", "invalid", "invalid"
        name, port = _diagnostic_authority(parsed.netloc)
        if name == "invalid" or value != parsed.scheme + "://" + parsed.netloc:
            return "invalid", "invalid", "invalid"
        return parsed.scheme, name, port if port is not None else 443 if parsed.scheme == "https" else 80
    except ValueError:
        return "invalid", "invalid", "invalid"


def _log_login_origin_rejection(request: Request, reason: str):
    if request.method != "POST" or request.url.path != "/api/login":
        return
    scheme, hostname, port = _diagnostic_origin(request.headers.get("origin"))
    request_hostname, _ = _diagnostic_authority(request.headers.get("host", ""))
    logger.warning("event=origin_rejected reason=%s origin_scheme=%s origin_hostname=%s origin_port=%s request_host_hostname=%s",
                   reason, scheme, hostname, port, request_hostname)


@asynccontextmanager
async def lifespan(app):
    access = load_settings()
    if hosted(access) and not auth.configured(access):
        raise RuntimeError("托管工作台必须配置有效的 STUDIO_USERNAME 和 STUDIO_PASSWORD_HASH，服务未启动")
    if hosted(access):
        try:
            allowed_origins(access)
        except ValueError as exc:
            raise RuntimeError(str(exc)) from None
    async def connect():
        try:
            await knowledge.connect()
        except KnowledgeError:
            pass
    startup = asyncio.create_task(connect())
    yield
    if not startup.done(): startup.cancel()


app = FastAPI(title="华为 PC 图文工作台 API", version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def origin_guard(request: Request, call_next):
    tool_route = request.url.path.startswith(("/api/tools/", "/api/dify/"))
    access = load_settings()
    online = hosted(access)
    request.state.hosted = online
    login_enabled = auth.configured(access)
    if online and not login_enabled:
        _log_login_origin_rejection(request, "config_invalid")
        return JSONResponse({"detail": "托管登录尚未安全配置，服务不可用"}, status_code=503)
    try:
        origins = allowed_origins(access) if online else None
    except ValueError:
        _log_login_origin_rejection(request, "config_invalid")
        return JSONResponse({"detail": "托管请求来源配置无效，服务不可用"}, status_code=503)
    # The platform's loopback proxy is never evidence that an online visitor is local.
    if not tool_route and request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        if online and origins is not None:
            valid_origin = origin in origins
        else:
            valid_origin = not ((online and not origin) or (origin and (
                urlparse(origin).netloc != request.headers.get("host") or (online and urlparse(origin).scheme != "https"))))
        if not valid_origin:
            reason = ("missing_origin" if not origin else "null_origin" if origin == "null"
                      else "https_required" if online and not origin.startswith("https://")
                      else "not_allowed" if origins is not None else "host_mismatch")
            _log_login_origin_rejection(request, reason)
            return JSONResponse({"detail": "请求来源不匹配"}, status_code=403)
    public = request.method in {"GET", "HEAD"} and request.url.path in {
        "/healthz", "/login", "/static/login.js", "/static/login.css"}
    public = public or (request.method == "POST" and request.url.path == "/api/login")
    if login_enabled and not tool_route and not public:
        username = auth.sessions.username(request.cookies.get(auth.SESSION_COOKIE, ""), access)
        method = "session" if username else ""
        if not username and not online:
            username = auth.basic_username(access, request.headers.get("authorization", ""))
            method = "basic" if username else ""
        if not username:
            if request.method == "GET" and not request.url.path.startswith("/api/"):
                return RedirectResponse("/login", status_code=303)
            headers = {} if online else {"WWW-Authenticate": 'Basic realm="Huawei PC Studio", charset="UTF-8"'}
            return JSONResponse({"detail": "登录已失效，请重新登录工作台"}, status_code=401, headers=headers)
        request.state.username = username
        request.state.authentication_method = method
    if request.url.path.startswith("/api/") and not tool_route and not public:
        host = request.client.host if request.client else ""
        if host not in {"127.0.0.1", "::1", "testclient"} and not login_enabled:
            return JSONResponse({"detail": "业务界面接口仅允许本机访问；公网请仅代理已鉴权的工具接口"}, status_code=403)
    response = await call_next(request)
    return response


@app.middleware("http")
async def security_headers(request: Request, call_next):
    # This outer middleware also covers rejected logins and authentication redirects.
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store" if request.url.path.startswith(("/api/", "/login")) else "no-cache"
    if getattr(request.state, "hosted", False):
        response.headers["Content-Security-Policy"] = "frame-ancestors 'self' https://modelscope.cn https://www.modelscope.cn"
    return response


@app.exception_handler(KeyError)
async def missing(request, exc):
    return JSONResponse({"detail": str(exc).strip("'")}, status_code=404)


@app.exception_handler(ValueError)
async def invalid(request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=422)


@app.exception_handler(KnowledgeError)
@app.exception_handler(ProviderError)
async def upstream(request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=502)


def local_task(task_id: str) -> dict:
    return get_task(task_id, "local")


def safe_task(task: dict) -> dict:
    # Do not expose connector/media credentials or internal ima resource IDs.
    return {k: v for k, v in task.items() if k not in {"owner"}}


async def require_tool(request: Request):
    token = load_settings()["tool_token"]
    bearer = request.headers.get("authorization")
    alternate = request.headers.get("x-tool-token")
    # A supplied but incorrect credential is never ignored in favor of the other.
    if (not token or (bearer is None and alternate is None)
            or (bearer is not None and not hmac.compare_digest(bearer, "Bearer " + token))
            or (alternate is not None and not hmac.compare_digest(alternate, token))):
        raise HTTPException(401, "工具接口鉴权失败")


@app.get("/healthz")
async def health():
    return {"status": "ok"}


@app.get("/login")
async def login_page():
    return FileResponse(ROOT / "static" / "login.html")


@app.post("/api/login")
async def login(request: Request, payload: dict = Body(...)):
    access = load_settings()
    peer = request.client.host if request.client else "unknown"
    if auth.login_limiter.blocked(peer):
        return JSONResponse({"detail": "登录失败次数过多，请五分钟后再试"}, status_code=429, headers={"Retry-After": "300"})
    if not auth.verify(access, payload.get("username", ""), payload.get("password", "")):
        auth.login_limiter.failed(peer)
        raise HTTPException(401, "登录名或密码不正确")
    auth.login_limiter.succeeded(peer)
    auth.sessions.revoke(request.cookies.get(auth.SESSION_COOKIE, ""))
    response = JSONResponse({"status": "authenticated"})
    online = hosted(access)
    response.set_cookie(auth.SESSION_COOKIE, auth.sessions.issue(access), max_age=auth.SESSION_SECONDS,
                        httponly=True, secure=online or request.url.scheme == "https", samesite="none" if online else "lax", path="/")
    if online:
        # Python 3.12's cookie API does not yet expose CHIPS. Keep a host-only,
        # Secure cookie and append the standards-defined partition attribute.
        response.headers["set-cookie"] += "; Partitioned"
    return response


@app.post("/api/logout")
async def logout(request: Request):
    auth.sessions.revoke(request.cookies.get(auth.SESSION_COOKIE, ""))
    response = JSONResponse({"status": "logged_out"})
    online = hosted(load_settings())
    response.delete_cookie(auth.SESSION_COOKIE, path="/", httponly=True,
                           secure=online or request.url.scheme == "https", samesite="none" if online else "lax")
    if online:
        response.headers["set-cookie"] += "; Partitioned"
    return response


@app.get("/api/status")
async def status(request: Request):
    s, flags = load_settings(), configured()
    connections = {}
    for key, flag in flags.items():
        connections[key] = {"configured": flag, "connected": False, "message": "已配置，尚未验证" if flag else "待配置"} | CONNECTION_RESULTS.get(key, {})
    connections["ima"] = knowledge.status | {"configured": flags["ima"]}
    return {"app_name": "华为 PC 图文工作台", "version": "0.1.0",
            "mode": "dify" if dify_ready() else "deepseek" if flags["deepseek"] else "rules",
            "connections": connections, "user": {"name": getattr(request.state, "username", getpass.getuser()), "verified": True,
                "source": "工作台登录账号" if getattr(request.state, "username", None) else "本机操作系统账号"},
            "platforms": PLATFORMS, "scenarios": SCENARIOS, "channels": CHANNELS,
            "settings": {k: s[k] for k in ["dify_base_url", "deepseek_base_url", "dashscope_base_url", "text_model", "vision_model", "image_model", "public_api_base"]},
            "managed_config": managed_config(s),
            "authentication": {"enabled": auth.configured(s), "method": getattr(request.state, "authentication_method", "local"), "shared_workspace": True},
            "notice": "模型未接通时为规则草稿；实时价格仅在获得可核实报价后计算。"}


@app.post("/api/settings")
async def settings(payload: dict = Body(...)):
    if managed_config(load_settings()):
        raise HTTPException(403, "托管连接配置由部署者安全管理，工作台仅可查看状态与测试连接")
    save_settings(payload)
    for key in ["dify", "deepseek", "vision", "image", "search"]:
        CONNECTION_RESULTS.pop(key, None)
    return {"status": "saved"}


@app.post("/api/connections/test")
async def test_connection(payload: dict = Body(...)):
    key = payload.get("connection")
    if key == "ima":
        return await knowledge.connect()
    if key not in {"dify", "deepseek", "vision", "image", "search"}:
        raise ValueError("未知连接")
    s = load_settings()
    if not configured()[key]:
        raise ValueError("请先配置该服务")
    if key == "dify":
        url, token = s["dify_base_url"].rstrip("/") + "/info", s["dify_api_key"]
    elif key == "deepseek":
        url, token = s["deepseek_base_url"].rstrip("/") + "/models", s["deepseek_api_key"]
    elif key in {"vision", "image"}:
        url, token = s["dashscope_base_url"].rstrip("/") + "/compatible-mode/v1/models", s["dashscope_api_key"]
    else:
        # Saving a key is not proof of a successful (billable) search.
        return {"configured": True, "connected": False, "message": "已配置；首次执行联网查询时验证，当前未发起计费查询"}
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            r = await client.get(url, headers={"Authorization": f"Bearer {token}"})
        passed = r.status_code == 200
        result = {"configured": True, "connected": passed, "message": "鉴权接口通过；具体工作流或模型推理仍需任务验证" if passed else f"接口返回 HTTP {r.status_code}"}
        CONNECTION_RESULTS[key] = result
        return result
    except httpx.HTTPError:
        CONNECTION_RESULTS[key] = {"configured": True, "connected": False, "message": "连接失败或超时"}
        raise ProviderError("连接失败或超时") from None


@app.get("/api/tasks")
async def tasks():
    return {"tasks": list_tasks()}


@app.post("/api/tasks")
async def new_task(payload: dict = Body(default={})):
    return safe_task(create_task(str(payload.get("title") or "新的内容任务")))


@app.get("/api/tasks/{task_id}")
async def read_task(task_id: str):
    return safe_task(local_task(task_id))


@app.post("/api/tasks/{task_id}/brief")
@app.patch("/api/tasks/{task_id}/brief")
async def update_brief(task_id: str, payload: dict = Body(...)):
    async with task_lock(task_id):
        task = local_task(task_id)
        ensure_context(task)
        old = dict(task["brief"])
        changes = payload.get("brief", payload)
        for key, value in changes.items():
            if key in task["brief"] and isinstance(value, (str, list)):
                task["brief"][key] = value
        platform(task["brief"]["platform"])
        apply_brief_save(task, old)
        if old != task["brief"]:
            if task.get("matching_key") != task.get("task_context", {}).get("matching_key"):
                task["selling_point_plan"], task["candidates"], task["fit_assessments"] = {}, [], []
            task["checks"] = [{"category": "任务需求", "status": "blocked", "message": "需求已修改，请重新生成或核验后交付"}]
            task["status"] = "ready"
            task["needs_regeneration"] = True
        if any(old.get(k) != task["brief"].get(k) for k in ["product", "software"]):
            task["facts"], task["assets"], task["evidence"] = [], [], []
        return safe_task(save_task(task, "修改任务需求"))


async def run_dify(task: dict, message: str) -> dict:
    if not load_settings()["tool_token"] or not load_settings()["public_api_base"]:
        raise ValueError("使用 Dify 前请配置工具密钥与云端可访问的 HTTPS 服务地址，并导入工作流")
    data = await dify_chat(message, task["id"], task.get("dify_conversation_id", ""))
    result = local_task(task["id"])
    result["dify_conversation_id"] = data.get("conversation_id", task.get("dify_conversation_id", ""))
    result["orchestrator"] = "dify"
    CONNECTION_RESULTS["dify"] = {"configured": True, "connected": True, "message": "工作流调用通过"}
    return save_task(result, "Dify 编排完成", version=False)


@app.post("/api/tasks/{task_id}/chat")
async def chat(task_id: str, payload: dict = Body(...)):
    message = payload.get("message", "").strip()
    if not message or len(message) > 12000:
        raise ValueError("请输入 1–12000 字的任务或补充信息")
    # Do not hold the task lock while Dify calls back into execute.
    if dify_ready():
        return safe_task(await run_dify(local_task(task_id), message))
    async with task_lock(task_id):
        return safe_task(await chat_task(local_task(task_id), message))


@app.post("/api/tasks/{task_id}/generate")
async def generate(task_id: str, payload: dict = Body(default={})):
    if dify_ready():
        async with task_lock(task_id):
            task = local_task(task_id)
            if payload.get("platform"):
                platform(payload["platform"])
                task["brief"]["platform"] = payload["platform"]
                task = save_task(task, "切换平台", version=False)
        return safe_task(await run_dify(task, "[生成当前任务]" + str(payload.get("instruction", ""))))
    async with task_lock(task_id):
        task = local_task(task_id)
        if payload.get("platform"):
            platform(payload["platform"])
            task["brief"]["platform"] = payload["platform"]
        # A user-triggered generation is a new bounded round; retained facts remain valid.
        task.pop('query_control',None)
        task['retrieval_runs']=[]
        return safe_task(await generate_task(task, str(payload.get("instruction", ""))))


@app.post("/api/tasks/{task_id}/retrieve")
async def retrieve(task_id: str, payload: dict = Body(default={})):
    async with task_lock(task_id):
        task = await retrieve_task(local_task(task_id), str(payload.get("query", "")), bool(payload.get("refresh", False)))
        if task.get("draft"):
            task = await verify_task(task)
            task = save_task(task, "刷新依据后核验")
        return safe_task(task)


@app.post("/api/tasks/{task_id}/draft")
@app.put("/api/tasks/{task_id}/draft")
async def edit_draft(task_id: str, payload: dict = Body(...)):
    async with task_lock(task_id):
        task = local_task(task_id)
        if payload.get("revision") != task["revision"]:
            raise ValueError("内容已更新，请重新打开后再保存")
        draft = payload.get("draft")
        if not isinstance(draft, dict) or any(not isinstance(draft.get(k, ""), str) for k in ["title", "lead", "body", "cta"]):
            raise ValueError("成品字段类型不正确")
        if "images" in draft and (not isinstance(draft["images"], list) or
                any(not isinstance(x, dict) or not isinstance(x.get("id"), str) for x in draft["images"])):
            raise ValueError("配图必须是包含有效素材ID的对象数组")
        if "fact_ids" in draft and (not isinstance(draft["fact_ids"], list) or any(not isinstance(x, str) for x in draft["fact_ids"])):
            raise ValueError("事实引用必须是字符串数组")
        if "tags" in draft and (not isinstance(draft["tags"], list) or any(not isinstance(x, str) for x in draft["tags"])):
            raise ValueError("标签必须是字符串数组")
        prior = task.get("draft") or {}
        task.pop("vision_result", None)
        task["draft"] = {k: draft.get(k, prior.get(k, [] if k in {"images", "tags", "fact_ids"} else "")) for k in
                         ["title", "lead", "body", "cta", "images", "tags", "fact_ids", "generator", "disclosure"]}
        task["draft"]["disclosure"] = "广告｜AI辅助内容，发布前核验"
        task = await verify_task(task)
        if task.get("needs_regeneration"):
            task["checks"].append({"category": "任务需求", "status": "blocked", "message": "需求发生变化，请按当前需求重新生成"})
            task["status"] = "blocked"
        if task["brief"]["platform"] == "poster" and task["status"] != "blocked":
            from .media import compose_poster
            old_background = prior.get("background") or {}
            background_name = Path(str(old_background.get("url", ""))).name
            background_path = DATA / "generated" / background_name if old_background.get("generated") and background_name else None
            task["draft"]["poster_url"] = await compose_poster(task, str(background_path) if background_path and background_path.is_file() else None)
            if background_path and background_path.is_file():
                task["draft"]["background"] = old_background
        return safe_task(save_task(task, "人工编辑与核验", expected_revision=payload["revision"]))


@app.post("/api/tasks/{task_id}/verify")
async def verify(task_id: str):
    async with task_lock(task_id):
        return safe_task(save_task(await verify_task(local_task(task_id)), "重新核验"))


@app.post("/api/tasks/{task_id}/versions/{version_id}/restore")
async def restore_version(task_id: str, version_id: str):
    async with task_lock(task_id):
        return safe_task(restore(task_id, version_id))


@app.post("/api/tasks/{task_id}/quotes")
async def quotes(task_id: str, payload: dict = Body(...)):
    async with task_lock(task_id):
        task = local_task(task_id)
        task["offers"] = payload.get("offers", [])
        task["buyer"] = payload.get("buyer", {})
        result = calculate_quotes({k: v for k, v in payload.items() if k != "now"} | {"region": task["brief"].get("region", "杭州")})
        task["quotes"] = result
        if task.get("draft"):
            task = await verify_task(task)
        return safe_task(save_task(task, "计算并核验报价"))


@app.post("/api/tasks/{task_id}/prices/search")
async def price_search(task_id: str):
    async with task_lock(task_id):
        task = local_task(task_id)
        task["price_evidence"], warnings = await search_prices(task["brief"])
        task["price_search_warnings"] = warnings
        if task["price_evidence"]:
            CONNECTION_RESULTS["search"] = {"configured": True, "connected": True, "message": "已取得当前查询结果；商家报价条件待核验"}
        return safe_task(save_task(task, "联网查找报价依据"))


@app.post("/api/tasks/{task_id}/background")
async def background(task_id: str, payload: dict = Body(default={})):
    async with task_lock(task_id):
        task = local_task(task_id)
        if task["brief"]["platform"] != "poster" or not task.get("draft"):
            raise ValueError("请先生成海报文案与配图")
        if task["status"] == "blocked":
            raise ValueError("请先处理阻断项，再生成背景")
        url = await generate_background(str(payload.get("prompt") or "冷静专业、浅灰蓝色、柔和光线"))
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.get(url)
            if r.status_code != 200 or len(r.content) > 25 * 1024 * 1024:
                raise ProviderError("生成背景无法保存，未替换已有成品")
        from PIL import Image
        Image.open(io.BytesIO(r.content)).verify()
        directory = DATA / "generated"
        directory.mkdir(exist_ok=True)
        path = directory / (task_id + "-background.png")
        path.write_bytes(r.content)
        from .media import compose_poster
        task["draft"]["poster_url"] = await compose_poster(task, str(path))
        task["draft"]["background"] = {"generated": True, "provider": "Qwen-Image", "model": load_settings()["image_model"], "url": "/api/files/" + path.name}
        task["checks"] = [c for c in task.get("checks", []) if c.get("category") != "视觉核验"]
        task.pop("vision_result", None)
        CONNECTION_RESULTS["image"] = {"configured": True, "connected": True, "message": "已实际生成背景并完成原图合成"}
        return safe_task(save_task(task, "生成AI背景并合成海报"))


@app.post("/api/tasks/{task_id}/vision")
async def vision_check(task_id: str):
    async with task_lock(task_id):
        task = local_task(task_id)
        poster = task.get("draft", {}).get("poster_url", "")
        if not poster:
            raise ValueError("请先合成海报")
        path = DATA / "generated" / Path(poster).name
        if not path.is_file():
            raise ValueError("海报文件不存在，请重新生成")
        images = ["data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()]
        for image in task["draft"].get("images", [])[:1]:
            raw, mime = await knowledge.asset_bytes(image["id"])
            images.append(f"data:{mime};base64," + base64.b64encode(raw).decode())
        from .media import verify_render_manifest
        proof = await verify_render_manifest(task)
        result = await json_chat("你负责成品可用性核验，只按输入的文案和已授权模板检查实际缺陷。主图与正文清楚完整时返回passed=true,issues=[]。阻断仅限清楚可见的缺字错字、裁切、遮挡、拉伸或重绘；疑虑与审美建议放notes。不得虚构品牌字体/颜色规范、Unicode编码差异或未提供的授权要求；同一句文字、标点间距及正常换行不构成缺陷。顶部‘HUAWEI PC · 产品指南’、‘发布前请复核’、产品型号、底部广告/AI声明、来源说明和AI水印均为已授权模板内容。AI背景与文字层均已获准，背景不必与原图相同。程序提供像素校验：主图区域等于原图等比例贴层时，外观细节缩小不能判断为重绘。不得凭照片猜内部配置或把视觉相似当型号证明。返回JSON {passed:bool,issues:[{category:'product_pixels或text或layout或other',expected:'来自输入的明确要求',observed:'实际可见差异',reason:'具体缺陷'}],notes:[],recognized_text:string}。product_pixels只指主图区域。每个issue必须有可见实际差异，不要把检查通过、相同文字或已自行排除的问题写入issues。", {"draft": task["draft"], "programmatic_proof": proof}, vision_images=images)
        task["vision_raw_result"] = result
        result = reconcile_visual_evidence(result, proof)
        if task["draft"].get("render_manifest") and not proof.get("verified"):
            result["issues"].append({"category": "render_integrity", "reason": "成品与服务端渲染记录不一致，请重新合成后核验", "evidence": proof.get("errors", [])})
            result["passed"] = False
        issues = result.get("issues", [])
        if not isinstance(issues, list):
            issues = [issues or "视觉模型未返回有效核验项目"]
        passed = result.get("passed") is True and not issues
        result["passed"], result["issues"] = passed, issues
        task["vision_result"] = result
        task["render_verification"] = proof
        CONNECTION_RESULTS["vision"] = {"configured": True, "connected": True, "message": "已实际调用成品与原图视觉核验；核验结论见任务"}
        task["checks"] = [c for c in task["checks"] if c["category"] != "视觉核验"]
        task["checks"].append({"category": "视觉核验", "status": "pass" if passed else "blocked", "message": ("视觉辅助核验通过；" + ("成品与原图像素一致性已验证；" if proof.get("verified") else "") + "型号仍由资产来源证明") if passed else "；".join(str(issue) for issue in issues) or "视觉模型无法确认成品"})
        task["status"] = "blocked" if any(c.get("status") == "blocked" for c in task["checks"]) else "draft"
        return safe_task(save_task(task, "视觉辅助核验"))


@app.get("/api/assets/{asset_id}")
async def asset(asset_id: str):
    raw, mime = await knowledge.asset_bytes(asset_id)
    return Response(raw, media_type=mime)


@app.get("/api/files/{filename}")
async def generated_file(filename: str):
    if Path(filename).name != filename or not filename.endswith((".png", ".pdf")):
        raise HTTPException(404)
    path = DATA / "generated" / filename
    if not path.is_file(): raise HTTPException(404)
    return FileResponse(path)


@app.get("/api/tasks/{task_id}/export")
async def export(task_id: str, format: str = "txt"):
    task = local_task(task_id)
    # Recompute all offer validity at export time; a saved lowest quote may have expired.
    if task.get("offers"):
        task["quotes"] = calculate_quotes({"offers": task["offers"], "buyer": task.get("buyer", {}), "region": task["brief"].get("region")})
    recommendation_checks = review_recommendation_claims(task, task.get("semantic_review"))["checks"]
    current_checks = validate(task.get("draft"), task["facts"], task["assets"], task["quotes"], task["brief"]["platform"], task.get("semantic_review"))
    # Existing semantic/visual/dirty-brief blocks must not disappear at export.
    task["checks"] = current_checks + recommendation_checks + [c for c in task.get("checks", []) if c.get("status") == "blocked" or c.get("category") == "视觉核验"]
    if (task.get("draft") or {}).get("render_manifest"):
        from .media import verify_render_manifest
        proof = await verify_render_manifest(task)
        task["checks"].append({"category": "成品一致性", "status": "pass" if proof.get("verified") else "blocked", "message": "已重验文件、原图像素与排版输入" if proof.get("verified") else "成品与渲染记录不一致，请重新合成后交付"})
    if task.get("needs_regeneration"):
        task["checks"].append({"category": "任务需求", "status": "blocked", "message": "需求已修改，需重新生成后交付"})
    if format not in {"json", "report"} and any(c.get("status") == "blocked" for c in task["checks"]):
        raise ValueError("核验存在阻断项，请修正后导出；可以导出核验数据 JSON 或审核报告")
    if format == "zip":
        for item in (task.get("draft") or {}).get("images", []):
            await knowledge.asset_bytes(item["id"])
    from .exports import export_task
    raw, mime, filename = export_task(task, format)
    return Response(raw, media_type=mime, headers={"Content-Disposition": "attachment; filename*=UTF-8''" + quote(filename)})


@app.get("/api/tasks/{task_id}/copy")
async def copy_text(task_id: str):
    task = local_task(task_id)
    if not task.get("draft"):
        raise ValueError("尚无可复制的成品")
    if task.get("offers"):
        task["quotes"] = calculate_quotes({"offers": task["offers"], "buyer": task.get("buyer", {}), "region": task["brief"].get("region")})
    checks = validate(task["draft"], task["facts"], task["assets"], task["quotes"], task["brief"]["platform"], task.get("semantic_review")) + review_recommendation_claims(task, task.get("semantic_review"))["checks"]
    if task["draft"].get("render_manifest"):
        from .media import verify_render_manifest
        if not (await verify_render_manifest(task)).get("verified"):
            raise ValueError("成品与渲染记录不一致，请重新合成后复制")
    if task.get("needs_regeneration") or any(c.get("status") == "blocked" for c in checks + task.get("checks", [])):
        raise ValueError("核验存在阻断问题，请修正后复制成品；核验报告仍可导出")
    d = task["draft"]
    text = "\n\n".join(str(d.get(k, "")) for k in ["title", "lead", "body", "cta"] if d.get(k))
    if d.get("tags"):
        text += "\n\n" + " ".join("#" + str(t).lstrip("#") for t in d["tags"])
    text += "\n\n" + str(d.get("disclosure") or "广告｜AI辅助生成，发布前核验")
    if any(c.get("status") == "warning" for c in checks):
        text += "\n待复核草稿：请确认核验记录与适用条件后发布。"
    return {"text": text}


@app.post("/api/dify/execute", dependencies=[Depends(require_tool)])
async def dify_execute(payload: dict = Body(...)):
    task_id = payload.get("task_id")
    user = payload.get("user") or "preview"
    if task_id:
        task = get_task(task_id)
        expected = hmac.new(load_settings()["tool_token"].encode(), (user + ":" + task_id).encode(), hashlib.sha256).hexdigest()
        if task.get("owner") != user or not hmac.compare_digest(str(payload.get("context_token", "")), expected):
            raise HTTPException(403, "任务身份校验失败")
    else:
        user = str(user)[:100]
        if not user.startswith("preview:"):
            user = "preview:" + user
        task = create_task(owner=user)
        task_id = task["id"]
    async with task_lock(task_id):
        task = get_task(task_id)
        if task.get("owner") != user:
            raise HTTPException(403, "任务身份校验失败")
        action = payload.get("action", "chat")
        if payload.get("brief"):
            ensure_context(task)
            old_brief = dict(task["brief"])
            task["brief"].update({k: v for k, v in payload["brief"].items() if k in task["brief"]})
            apply_brief_save(task, old_brief)
            if old_brief != task["brief"]:
                if task.get("matching_key") != task.get("task_context", {}).get("matching_key"):
                    task["selling_point_plan"], task["candidates"], task["fit_assessments"] = {}, [], []
                task["needs_regeneration"] = True
            if any(old_brief.get(k) != task["brief"].get(k) for k in ["product", "software"]):
                task["facts"], task["assets"], task["evidence"], task["quotes"] = [], [], [], {"quotes": [], "best": [], "warnings": []}
        if payload.get("platform"):
            platform(payload["platform"])
            task["brief"]["platform"] = payload["platform"]
        if action == "chat": result = await chat_task(task, str(payload.get("message", "")))
        elif action == "generate": result = await generate_task(task, str(payload.get("instruction", "")))
        elif action == "retrieve": result = await retrieve_task(task)
        elif action == "verify": result = save_task(await verify_task(task), "Dify重新核验")
        else: raise ValueError("未知工作流动作")
    context_token = hmac.new(load_settings()["tool_token"].encode(), (user + ":" + result["id"]).encode(), hashlib.sha256).hexdigest()
    return {"task_id": result["id"], "user": user, "context_token": context_token, "reply": next((m["content"] for m in reversed(result["messages"]) if m["role"] == "assistant"), result["stage"]),
            "status": result["status"], "result": safe_task(result)}


@app.post("/api/tools/search", dependencies=[Depends(require_tool)])
async def tool_search(payload: dict = Body(...)):
    result = await knowledge.retrieve(str(payload.get("model") or payload.get("query", "")))
    return {k: result[k] for k in ["facts", "assets", "evidence", "warnings", "catalog"]}


@app.post("/api/tools/quotes", dependencies=[Depends(require_tool)])
async def tool_quotes(payload: dict = Body(...)):
    return calculate_quotes({k: v for k, v in payload.items() if k != "now"})


@app.post("/api/tools/verify", dependencies=[Depends(require_tool)])
async def tool_verify(payload: dict = Body(...)):
    checks = validate(payload.get("draft"), payload.get("facts", []), payload.get("assets", []), payload.get("quotes", {}), payload.get("platform", "wechat"))
    return {"checks": checks, "passed": not any(c["status"] == "blocked" for c in checks)}


@app.get("/")
async def index():
    return FileResponse(ROOT / "static" / "index.html")


app.mount("/static", StaticFiles(directory=ROOT / "static", check_dir=False), name="static")
