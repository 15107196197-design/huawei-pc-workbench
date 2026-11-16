#!/usr/bin/env python3
"""Publish the independent V2 application to a new ModelScope Docker Studio.

Run with .venv/bin/python scripts/publish_app.py. This is separate from the
read-only showcase publisher. Tokens and generated login credentials stay in
this process, while service credentials are submitted only as Studio Secrets.
"""
from __future__ import annotations

import asyncio
import hashlib
import html
import io
import json
import os
import re
import secrets
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import publish_review as common
from huawei_agent.settings import get_ima_credentials, load_settings

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "http://127.0.0.1:8791"
CSRF, NONCE = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
# Fixed independent target: this publisher never updates the original Studio.
SLUG = "huawei-pc-agent-app-v2"
DEPLOYMENT_RECEIPT = "output/submission/full-app-v2-deployment.json"
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
lock = asyncio.Lock()
account = common.Account()
created: set[str] = set()
resumed_applications: set[str] = set()
prepared = ""
_resume_username = os.environ.pop("PUBLISH_RESUME_LOGIN_USERNAME", "")
_resume_password = os.environ.pop("PUBLISH_RESUME_LOGIN_PASSWORD", "")
RESUMED_LOGIN = bool(_resume_username or _resume_password)
if RESUMED_LOGIN and (not _resume_username or ":" in _resume_username or len(_resume_username) > 100
                      or not 12 <= len(_resume_password) <= 1024):
    raise RuntimeError("resume_login_configuration_invalid")
login_name = _resume_username if RESUMED_LOGIN else "studio"
login_password = _resume_password if RESUMED_LOGIN else secrets.token_urlsafe(24)
del _resume_username, _resume_password
login_salt = secrets.token_bytes(16)
login_hash = "pbkdf2_sha256$600000$" + login_salt.hex() + "$" + hashlib.pbkdf2_hmac(
    "sha256", login_password.encode(), login_salt, 600000).hex()
cloud_client: httpx.Client | None = None
cloud_host = ""
stage = "waiting_for_token"
deployment: dict[str, Any] = {}


class DiagnosticError(common.SafeError):
    def __init__(self, diagnostics: dict[str, Any]):
        super().__init__("application_login_" + diagnostics["category"] + "_failed", 502)
        self.diagnostics = diagnostics


def external_failure(exc: Exception) -> common.SafeError:
    """Classify actionable platform refusals without returning their raw contents."""
    message = str(exc).lower()
    status = getattr(exc, "status_code", None)
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
    if status == 403 and any(marker in message for marker in ("aliyun", "实名认证", "绑定阿里云", "real-name", "real name")):
        return common.SafeError("needs_aliyun_verification", 403)
    if any(marker in message for marker in ("quota", "配额", "免费资源不足", "创空间数量上限")):
        return common.SafeError("studio_quota_exceeded", 409)
    return common.fail_external(exc)


def configuration() -> dict[str, str]:
    values = load_settings()
    client_id, ima_key = get_ima_credentials()
    if not values.get("deepseek_api_key") or not values.get("dashscope_api_key") or not client_id or not ima_key:
        raise common.SafeError("application_provider_configuration_missing", 409)
    result = {key.upper(): values[key] for key in [
        "deepseek_api_key", "deepseek_base_url", "dashscope_api_key", "dashscope_base_url",
        "text_model", "vision_model", "image_model",
    ]}
    result.update(IMA_OPENAPI_CLIENTID=client_id, IMA_OPENAPI_APIKEY=ima_key,
                  STUDIO_USERNAME=login_name, STUDIO_PASSWORD_HASH=login_hash,
                  STUDIO_ALLOWED_ORIGINS=json.dumps(application_origins(), separators=(",", ":")))
    # No Dify app or verified cloud workflow has been supplied for this project.
    # Do not turn on a half-configured orchestrator when direct model mode works.
    return result


def application_files() -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for folder, extensions in {"huawei_agent": {".py"}, "static": {".html", ".js", ".css", ".svg", ".png", ".ico"}}.items():
        source_root = ROOT / folder
        if source_root.is_symlink() or not source_root.is_dir():
            raise common.SafeError("application_source_directory_invalid", 409)
        for path in sorted(source_root.rglob("*")):
            if path.is_symlink():
                raise common.SafeError("application_symlink", 409)
            if any(part in common.SOURCE_FORBIDDEN or part == ".env" for part in path.relative_to(source_root).parts):
                continue
            if path.is_file() and path.suffix.lower() in extensions and "__pycache__" not in path.parts:
                files[path.relative_to(ROOT).as_posix()] = path.read_bytes()
    for filename in ["requirements.lock", "deploy/modelscope/entrypoint.py", "deploy/modelscope/healthcheck.py"]:
        if any(path.is_symlink() for path in [ROOT / filename, *(ROOT / filename).parents] if path != ROOT and path.is_relative_to(ROOT)):
            raise common.SafeError("application_symlink", 409)
        files[filename] = (ROOT / filename).read_bytes()
    if any(path.is_symlink() for path in [ROOT / "deploy/modelscope/Dockerfile", ROOT / "deploy/modelscope", ROOT / "deploy"]):
        raise common.SafeError("application_symlink", 409)
    files["Dockerfile"] = (ROOT / "deploy/modelscope/Dockerfile").read_bytes()
    files["README.md"] = ("# 华为 PC 图文工作台 第二版\n\n这是独立于第一版的可登录单操作人工作台，"
        "支持自然语言需求、ima事实与原图、DeepSeek生成与搜索、规则报价、Qwen背景与视觉核验、改稿及导出。"
        "授权操作者共享任务；账号由部署者管理，模型和ima凭证只在平台Secret中。"
        "Dify云端工作区尚未联调，当前在线生成使用后端直连模型。"
        "没有已确认的杭州最低到手价。\n").encode()
    private_values = [value.encode() for key, value in configuration().items()
                      if key.endswith(("API_KEY", "APIKEY", "CLIENTID", "PASSWORD_HASH")) and len(value) >= 8]
    private_values += [v.encode() for v in [account.token, login_password] if len(v) >= 8]
    personal_name = Path.home().name.encode()
    for name, contents in files.items():
        common.inspect_public_bytes(contents)
        if any(value in contents for value in private_values) or personal_name in contents:
            raise common.SafeError("application_contains_private_value", 409)
        if len(contents) > 10 * 1024 * 1024:
            raise common.SafeError("application_file_limit", 409)
    return files


def manifest(files: dict[str, bytes]) -> dict[str, Any]:
    entries = [{"path": key, "bytes": len(value), "sha256": hashlib.sha256(value).hexdigest()} for key, value in sorted(files.items())]
    digest = hashlib.sha256(json.dumps(entries, sort_keys=True).encode()).hexdigest()
    return {"files": entries, "manifest_sha256": digest}


def api():
    if not account.token or not account.username:
        raise common.SafeError("modelscope_not_configured", 409)
    return common.modelscope_api(account.token)


def application_api_host(browser_host: str) -> str:
    """Bind the platform-provided API address to this verified owner and fixed app."""
    owner = account.username.lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", owner):
        raise common.SafeError("application_api_owner_not_supported", 409)
    expected_browser = f"https://{owner}-{SLUG}.ms.show"
    if browser_host.rstrip("/") != expected_browser:
        raise common.SafeError("application_metadata_host_mismatch", 502)
    # This address format is the API URL returned by the ModelScope gateway for
    # the verified application. SDK tokens never go to the browser host.
    host = f"https://studio-{owner}-{SLUG}.api-inference.modelscope.net"
    parsed = urlparse(host)
    if (parsed.scheme != "https" or parsed.netloc != f"studio-{owner}-{SLUG}.api-inference.modelscope.net"
            or not parsed.hostname.endswith(".api-inference.modelscope.net") or parsed.port is not None):
        raise common.SafeError("invalid_application_api_host", 502)
    return host


def application_origins() -> list[str]:
    if not account.username or not account.token:
        raise common.SafeError("modelscope_not_configured", 409)
    browser = f"https://{account.username.lower()}-{SLUG}.ms.show"
    return [browser, application_api_host(browser)]


def resume_record(username: str) -> dict[str, Any] | None:
    """Restore the continuously authorized, exact application from its deployment receipt."""
    if not RESUMED_LOGIN:
        return None
    path = ROOT / DEPLOYMENT_RECEIPT
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
        raise common.SafeError("application_resume_record_unavailable", 409)
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        result = record.get("result") if isinstance(record, dict) else None
    except (OSError, ValueError):
        raise common.SafeError("application_resume_record_invalid", 409) from None
    expected = f"https://modelscope.cn/studios/{username}/{SLUG}"
    if not isinstance(result, dict) or result.get("url") != expected or result.get("deployment_requested") is not True:
        raise common.SafeError("application_resume_record_invalid", 409)
    return {"url": expected, "deployment_requested": True, "resumed_for_application_repairs": True}


def response_diagnostics(response: httpx.Response, phase: str, cookie_present: bool = False) -> dict[str, Any]:
    """Return only fixed classifications and HTTP/code metadata, never upstream text."""
    try:
        payload = response.json()
    except (ValueError, UnicodeError):
        payload = {}
    payload = payload if isinstance(payload, dict) else {}
    message = " ".join(str(payload.get(key, "")) for key in ("detail", "message", "Message")).lower()
    code = payload.get("Code", payload.get("code"))
    if isinstance(code, bool) or not re.fullmatch(r"[0-9]{1,20}", str(code)):
        code = None
    if response.status_code == 200:
        category = "cookie" if phase == "login" and not cookie_present else "ok"
    elif "请求来源不匹配" in message or any(marker in message for marker in ("origin", "来源", "cross-site")):
        category = "origin"
    elif code is not None or any(marker in message for marker in ("sdk token", "api专用", "invalid token", "modelscope token", "token无效")):
        category = "platform"
    elif phase == "login" and (response.status_code == 429 or any(marker in message for marker in ("密码", "password", "credential"))):
        category = "password"
    elif response.status_code == 401 and phase != "login":
        category = "cookie"
    else:
        category = "platform"
    result = {"phase": phase, "category": category, "status_code": response.status_code,
              "session_cookie_present": cookie_present}
    if code is not None:
        result["platform_code"] = code
    return result


def redact_response(text: str) -> str:
    values = [account.token, login_password]
    if cloud_client is not None:
        values.extend(cookie.value for cookie in cloud_client.cookies.jar)
    for value in values:
        if len(value) >= 8:
            text = text.replace(json.dumps(value, ensure_ascii=False)[1:-1], "[redacted]")
            text = text.replace(value, "[redacted]")
    return text


def remote_info() -> dict[str, Any]:
    if not account.username:
        raise common.SafeError("modelscope_not_configured", 409)
    try:
        data = api().openapi.get_studio(account.username, SLUG)
        host = str(data.get("host", "")).rstrip("/")
        parsed = urlparse(host)
        if host and (parsed.scheme != "https" or not (parsed.hostname or "").endswith(".ms.show") or parsed.username or parsed.password
                     or parsed.path not in {"", "/"} or parsed.query or parsed.fragment or parsed.port not in {None, 443}):
            raise common.SafeError("invalid_application_host", 502)
        return {"status": data.get("status"), "runtime": data.get("runtime"), "host": host,
                "api_host": application_api_host(host) if host else "",
                "hardware": data.get("hardware"),
                "visibility": data.get("visibility"), "sdk_type": data.get("sdk_type"),
                "url": f"https://modelscope.cn/studios/{account.username}/{SLUG}"}
    except common.SafeError:
        raise
    except Exception as exc:
        raise external_failure(exc) from None


def publish(digest: str) -> dict[str, Any]:
    global stage, deployment
    files = application_files()
    current = manifest(files)["manifest_sha256"]
    if digest != prepared or digest != current:
        raise common.SafeError("application_manifest_changed_or_not_reviewed", 409)
    client, repo_id = api(), f"{account.username}/{SLUG}"
    try:
        hardware = client.list_studio_hardware(sdk_type="docker")
        free = [h for h in hardware if h.get("resource_type") == "free" and "docker" in h.get("supported_sdk_types", []) and not str(h.get("name", "")).startswith("paid/")]
        selected = next((h for h in free if h.get("name") == "platform/2v-cpu-8g-mem"), None)
        if selected is None:
            raise common.SafeError("free_docker_hardware_unavailable", 409)
        from modelscope_hub.errors import NotExistError
        try:
            client.get_repo(repo_id, repo_type="studio")
            exists = True
        except NotExistError:
            exists = False
        if exists and repo_id not in created:
            raise common.SafeError("existing_application_not_owned_by_session", 409)
        if exists:
            verify_current_application(client, selected["name"])
        if not exists:
            stage = "creating_application"
            client.create_repo(repo_id, repo_type="studio", visibility="public", sdk_type="docker",
                               hardware=selected["name"], display_name="华为 PC 图文工作台 第二版",
                               description="可登录操作的图文Agent：ima取材、模型生成、规则报价、核验与导出")
            created.add(repo_id)
        stage = "configuring_private_secrets"
        existing = {item.get("key") or item.get("name") for item in client.list_secrets(repo_id)}
        values = configuration()
        for key, value in values.items():
            (client.update_secret if key in existing else client.add_secret)(repo_id, key, value)
        stage = "uploading_application"
        with tempfile.TemporaryDirectory(prefix="huawei-cloud-public-code-") as temporary:
            folder = Path(temporary)
            for name, contents in files.items():
                path = folder / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(contents)
            client.upload_folder(repo_id, repo_type="studio", folder_path=folder, revision="master",
                                 allow_patterns=sorted(files), use_cache=False, max_workers=2,
                                 disable_tqdm=True, sync_remote_repo=False, commit_message="Deploy independent Huawei PC content application V2")
        stage = "building_application"
        client.deploy_repo(repo_id, repo_type="studio")
        deployment = {"url": f"https://modelscope.cn/studios/{repo_id}", "uploaded_files": len(files),
                      "secret_names": sorted(values), "hardware": {key: selected.get(key) for key in ["name", "resource_type"]},
                      "manifest_sha256": digest, "deployment_requested": True}
        return deployment
    except common.SafeError:
        stage = "deployment_needs_attention"
        raise
    except Exception as exc:
        stage = "deployment_needs_attention"
        raise external_failure(exc) from None


def verify_current_application(client, selected_hardware: str = "platform/2v-cpu-8g-mem") -> None:
    data = client.openapi.get_studio(account.username, SLUG)
    application_api_host(str(data.get("host", "")))
    hardware = data.get("hardware")
    hardware = hardware.get("name") if isinstance(hardware, dict) else hardware
    if data.get("sdk_type") != "docker" or hardware != selected_hardware:
        raise common.SafeError("current_application_not_verified_free_docker", 409)


def restart_application() -> dict[str, Any]:
    global stage, cloud_client, deployment
    repo_id = f"{account.username}/{SLUG}"
    if repo_id not in created:
        raise common.SafeError("application_not_created_by_session", 409)
    client = api()
    try:
        hardware = client.list_studio_hardware(sdk_type="docker", repo_id=repo_id)
        if not any(item.get("name") == "platform/2v-cpu-8g-mem" and item.get("resource_type") == "free"
                   and "docker" in item.get("supported_sdk_types", []) for item in hardware):
            raise common.SafeError("free_docker_hardware_unavailable", 409)
        verify_current_application(client)
        client.deploy_repo(repo_id, repo_type="studio")
        if cloud_client:
            cloud_client.close()
            cloud_client = None
        stage = "building_application"
        deployment = {"url": f"https://modelscope.cn/studios/{repo_id}", "deployment_requested": True,
                      "restart_requested": True, "hardware": {"name": "platform/2v-cpu-8g-mem", "resource_type": "free"}}
        return deployment
    except common.SafeError:
        raise
    except Exception as exc:
        raise external_failure(exc) from None


def logs(kind: str) -> dict[str, Any]:
    if f"{account.username}/{SLUG}" not in created or kind not in {"build", "run"}:
        raise common.SafeError("application_not_created_by_session", 409)
    try:
        result = api().get_repo_logs(f"{account.username}/{SLUG}", log_type=kind, page_size=100)
        text = json.dumps(result, ensure_ascii=False)
        for value in [account.token, login_password, *configuration().values()]:
            if len(value) >= 8:
                text = text.replace(value, "[redacted]")
                text = text.replace(json.dumps(value, ensure_ascii=False)[1:-1], "[redacted]")
        text = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~+/-]+", r"\1[redacted]", text)
        return {"kind": kind, "logs": text[-18000:]}
    except common.SafeError:
        raise
    except Exception as exc:
        raise external_failure(exc) from None


def application_request(method: str, path: str, body: dict | None) -> dict[str, Any]:
    global cloud_client, cloud_host
    if f"{account.username}/{SLUG}" not in created:
        raise common.SafeError("application_not_created_by_session", 409)
    if (not isinstance(method, str) or method not in {"GET", "POST", "PUT", "PATCH"} or not isinstance(path, str)
            or (body is not None and not isinstance(body, dict)) or "%" in path or "\\" in path):
        raise common.SafeError("verification_path_not_allowed", 400)
    parsed_path = urlparse(path)
    route = parsed_path.path
    if route == "/api/settings":
        raise common.SafeError("verification_may_not_modify_configuration", 400)
    task_id = r"[0-9a-f]{32}"
    task = rf"/api/tasks/{task_id}"
    permitted = {
        "GET": rf"/api/(?:status|products|tasks|tasks/{task_id}(?:/(?:copy|export))?|assets/[0-9a-f]{{24}}|files/[A-Za-z0-9][A-Za-z0-9_.-]{{0,199}}\.(?:png|pdf))",
        "POST": rf"(?:/api/tasks|{task}/(?:chat|generate|retrieve|verify|quotes|prices/search|background|vision|versions/{task_id}/restore)|/api/connections/test)",
        "PUT": rf"{task}/draft",
        "PATCH": rf"{task}/brief",
    }
    export_query = method == "GET" and re.fullmatch(rf"{task}/export", route) and re.fullmatch(r"format=(?:txt|html|json|zip|png|pdf|report)", parsed_path.query)
    if (parsed_path.scheme or parsed_path.netloc or parsed_path.fragment or parsed_path.params or any(part in {".", ".."} for part in route.split("/"))
            or not re.fullmatch(permitted[method], route) or (parsed_path.query and not export_query)):
        raise common.SafeError("verification_path_not_allowed", 400)
    info = remote_info()
    if info["status"] != "Running" or not info["host"]:
        raise common.SafeError("application_not_running", 409)
    host = application_api_host(info["host"])
    request_headers = {"Origin": host, "Authorization": "Bearer " + account.token}
    def authenticated_client():
        global cloud_client, cloud_host
        if cloud_client is None or cloud_host != host:
            if cloud_client:
                cloud_client.close()
            cloud_client = httpx.Client(base_url=host, timeout=300, trust_env=False, follow_redirects=False)
            cloud_host = host
            response = cloud_client.post("/api/login", headers=request_headers, json={"username": login_name, "password": login_password})
            cookie_present = bool(cloud_client.cookies.get("huawei_studio_session"))
            if response.status_code != 200 or not cookie_present:
                diagnostic = response_diagnostics(response, "login", cookie_present)
                cloud_client.close()
                cloud_client = None
                raise DiagnosticError(diagnostic)
        return cloud_client
    try:
        client = authenticated_client()
        response = client.request(method, path, headers=request_headers, json=body if method in {"POST", "PUT", "PATCH"} else None)
        if response.status_code == 401:
            # Opaque application sessions are intentionally lost on a container
            # restart; authenticate once again without replaying successful work.
            cloud_client.close()
            cloud_client = None
            client = authenticated_client()
            response = client.request(method, path, headers=request_headers, json=body if method in {"POST", "PUT", "PATCH"} else None)
    except common.SafeError:
        raise
    except httpx.HTTPError as exc:
        if cloud_client:
            cloud_client.close()
            cloud_client = None
        raise external_failure(exc) from None
    result: dict[str, Any] = {"status_code": response.status_code, "content_type": response.headers.get("content-type", "")}
    if "application/json" in result["content_type"]:
        result["body"] = json.loads(redact_response(json.dumps(response.json(), ensure_ascii=False)))
    elif result["content_type"].startswith("text/"):
        result["text"] = redact_response(response.text[:24000])
    else:
        result.update(bytes=len(response.content), sha256=hashlib.sha256(response.content).hexdigest())
    if response.status_code >= 400:
        result["diagnostics"] = response_diagnostics(response, "request", bool(client.cookies.get("huawei_studio_session")))
    return result


def safe_diagnostics() -> dict[str, Any]:
    global cloud_client
    info = remote_info()
    result = {key: info[key] for key in ("status", "host", "api_host", "sdk_type", "visibility", "hardware")}
    if info["status"] != "Running":
        result["check"] = {"category": "platform", "phase": "startup", "status_code": None}
        return result
    host = application_api_host(info["host"])
    headers = {"Authorization": "Bearer " + account.token, "Origin": host}
    probes = [("health", "GET", "/healthz"), ("list_tasks", "GET", "/api/tasks"),
              ("create_task", "POST", "/api/tasks"), ("settings", "POST", "/api/settings"),
              ("generated_file", "GET", "/api/files/nonexistent.png")]
    result["without_application_cookie"] = []
    try:
        with httpx.Client(base_url=host, timeout=30, trust_env=False, follow_redirects=False) as probe_client:
            for name, method, path in probes:
                probe_client.cookies.clear()
                response = probe_client.request(method, path, headers=headers, json={} if method == "POST" else None)
                diagnostic = response_diagnostics(response, "health" if name == "health" else "without_application_cookie")
                diagnostic.update(name=name, method=method, path=path)
                if name == "health":
                    try:
                        diagnostic["healthy"] = response.status_code == 200 and response.json() == {"status": "ok"}
                    except (ValueError, UnicodeError):
                        diagnostic["healthy"] = False
                else:
                    diagnostic["denied_without_application_cookie"] = response.status_code == 401 and diagnostic["category"] == "cookie"
                result["without_application_cookie"].append(diagnostic)
        if cloud_client:
            cloud_client.close()
            cloud_client = None
        checked = application_request("GET", "/api/status", None)
        result["check"] = checked.get("diagnostics", {"category": "ok", "phase": "authenticated_status", "status_code": checked["status_code"]})
        cookies = [cookie for cookie in cloud_client.cookies.jar if cookie.name == "huawei_studio_session"] if cloud_client else []
        result["cookie"] = {"present": bool(cookies)}
        if cookies:
            cookie = cookies[0]
            attributes = {key.lower(): value for key, value in cookie._rest.items()}
            result["cookie"].update(secure=cookie.secure, httponly="httponly" in attributes,
                                    samesite=str(attributes.get("samesite", "")).lower(),
                                    partitioned="partitioned" in attributes, path=cookie.path)
        body = checked.get("body")
        if isinstance(body, dict) and checked["status_code"] == 200:
            connections = body.get("connections") or {}
            ima = connections.get("ima") if isinstance(connections, dict) else {}
            result["application"] = {"mode": body.get("mode"), "managed_config": body.get("managed_config"),
                                     "ima_name": ima.get("name") if isinstance(ima, dict) else None}
    except DiagnosticError as error:
        result["check"] = error.diagnostics
    except common.SafeError as error:
        result["check"] = {"category": "platform", "phase": "request", "error": error.category}
    except httpx.HTTPError as error:
        result["check"] = {"category": "platform", "phase": "request", "error": external_failure(error).category}
    return result


@app.middleware("http")
async def guard(request: Request, call_next):
    if request.client is None or request.client.host not in {"127.0.0.1", "::1"} or request.headers.get("host") != "127.0.0.1:8791":
        return JSONResponse({"error": "loopback_host_required"}, status_code=403)
    if request.method not in {"GET", "HEAD"} and (request.headers.get("origin") != ORIGIN or not secrets.compare_digest(request.headers.get("x-csrf-token", ""), CSRF)):
        return JSONResponse({"error": "same_origin_csrf_required"}, status_code=403)
    try:
        response = await call_next(request)
    except Exception:
        return JSONResponse({"error": "publisher_failure"}, status_code=500)
    response.headers.update({"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": f"default-src 'none'; script-src 'nonce-{NONCE}'; style-src 'nonce-{NONCE}'; connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"})
    return response


@app.exception_handler(common.SafeError)
async def safe_error(_: Request, exc: common.SafeError):
    result = {"error": exc.category}
    if isinstance(exc, DiagnosticError):
        result["diagnostics"] = exc.diagnostics
    return JSONResponse(result, status_code=exc.status)


@app.get("/api/status")
async def status():
    return {"configured": bool(account.token), "username": account.username, "stage": stage, "deployment": deployment}


@app.post("/api/configure")
async def configure(request: Request):
    global account, stage, deployment
    values = await common.body_json(request)
    if set(values) != {"modelscope_token"}:
        raise common.SafeError("invalid_request")
    token = values["modelscope_token"]
    if not isinstance(token, str) or not 8 <= len(token) <= 4096 or any(ord(c) < 33 or ord(c) > 126 for c in token):
        raise common.SafeError("invalid_token")
    async with lock:
        username = await run_in_threadpool(common.verify_account, "modelscope", token)
        if account.username and account.username != username:
            raise common.SafeError("different_account_requires_fresh_process", 409)
        restored = resume_record(username)
        account = common.Account(token, username)
        if restored:
            repo_id = f"{username}/{SLUG}"
            created.add(repo_id)
            resumed_applications.add(repo_id)
            deployment = restored
            stage = "restored_for_application_repairs"
        else:
            stage = "authorized"
    return {"configured": True, "username": username, "application_restored": bool(restored)}


@app.post("/api/access")
async def access():
    if not account.token:
        raise common.SafeError("modelscope_not_configured", 409)
    return {"username": login_name, "password": login_password}


@app.post("/api/clear")
async def clear():
    global account, cloud_client
    async with lock:
        account = common.Account()
        if cloud_client:
            cloud_client.close()
            cloud_client = None
    return {"configured": False}


@app.post("/api/actions/{action}")
async def action(action: str, request: Request):
    global prepared
    values = await common.body_json(request)
    async with lock:
        if action == "prepare" and not values:
            result = await run_in_threadpool(lambda: manifest(application_files()))
            prepared = result["manifest_sha256"]
            return result
        if action == "publish" and set(values) == {"manifest_sha256"}:
            return await run_in_threadpool(publish, values["manifest_sha256"])
        if action == "status" and not values:
            return await run_in_threadpool(remote_info)
        if action == "diagnostics" and not values:
            return await run_in_threadpool(safe_diagnostics)
        if action == "restart" and not values:
            return await run_in_threadpool(restart_application)
        if action == "logs" and set(values) == {"kind"}:
            return await run_in_threadpool(logs, values["kind"])
        if action == "request" and set(values) <= {"method", "path", "body"}:
            return await run_in_threadpool(application_request, values.get("method", "GET"), values.get("path", ""), values.get("body"))
    raise common.SafeError("unsupported_action", 404)


@app.get("/")
async def index():
    page = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>第二版独立应用发布</title><style nonce="__NONCE__">body{font:16px/1.7 system-ui;background:#f6f8fb;color:#243247;margin:0}main{max-width:680px;background:white;border:1px solid #dce2eb;border-radius:18px;margin:42px auto;padding:30px}h1{font-size:26px;margin:0 0 12px}input{box-sizing:border-box;display:block;width:100%;padding:12px;border:1px solid #cbd3df;border-radius:9px;margin:8px 0 14px}button{padding:11px 18px;border-radius:8px;border:1px solid #b8c7dd;background:#eef3fb;color:#173a71;cursor:pointer;margin-right:8px}small{color:#64748b}#state{white-space:pre-line}.access{margin-top:26px;padding:18px;background:#f6f8fb;border-radius:12px}.access[hidden]{display:none}</style><main><h1>发布第二版独立工作台</h1><p>固定发布至 huawei-pc-agent-app-v2，使用独立创空间及任务数据。第一版 huawei-pc-agent-app 和原成果展示页保持原样。</p><p>复用你已有的魔搭可写 Token。验收工具已升级为魔搭官方 API 入口；原授权保存在旧进程内存，不能自动转交。请复用现有令牌，无需创建新令牌或扩大权限。</p><form id="form" autocomplete="off"><label for="token">现有魔搭可写 Token</label><input id="token" type="password" autocomplete="off" spellcheck="false"><button type="submit" id="verify">验证本次发布授权</button></form><p id="state" role="status"></p><small>Token 只在本机进程内存使用；已有模型及 ima 凭证只通过平台 Secret 注入，不进入源码、镜像或网页。部署仅选择当前免费 CPU 规格。</small><section class="access" id="access" hidden><h2>在线工作台登录账号</h2><p>登录可保护模型调用与任务。请复制保存，勿公开放入说明书或源码。</p><label for="username">登录名</label><input id="username" readonly><label for="password">工作台密码</label><input id="password" type="password" readonly><button id="copy" type="button">复制工作台密码</button><small id="copied"></small></section></main><script nonce="__NONCE__">const csrf='__CSRF__';const form=document.getElementById('form');const token=document.getElementById('token');const state=document.getElementById('state');async function send(path,data){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(data)});const value=await r.json();if(!r.ok)throw new Error(value.error||'request_failed');return value;}async function access(){const value=await send('/api/access',{});document.getElementById('username').value=value.username;document.getElementById('password').value=value.password;document.getElementById('access').hidden=false;}form.addEventListener('submit',async(e)=>{e.preventDefault();let value=token.value.trim();form.reset();document.getElementById('verify').disabled=true;state.textContent='正在验证…';try{const result=await send('/api/configure',{modelscope_token:value});state.textContent='已验证 '+result.username+(result.application_restored?'。已恢复当前应用的修复发布与验收权限。':'。第二版部署由代理继续执行。');await access();}catch(error){state.textContent='未完成：'+error.message;}finally{value=null;document.getElementById('verify').disabled=false;}});document.getElementById('copy').addEventListener('click',async()=>{await navigator.clipboard.writeText(document.getElementById('password').value);document.getElementById('copied').textContent='已复制';});fetch('/api/status').then(r=>r.json()).then(async(value)=>{if(value.configured){state.textContent='已验证 '+value.username+' · '+value.stage;await access();}});</script></html>'''
    return HTMLResponse(page.replace("__NONCE__", NONCE).replace("__CSRF__", CSRF), headers={"X-CSRF-Token": CSRF})


if __name__ == "__main__":
    import logging
    import uvicorn
    logging.getLogger("httpx").setLevel(logging.WARNING)
    print("第二版独立应用发布入口：http://127.0.0.1:8791/（仅本机，Token不落盘）")
    uvicorn.run(app, host="127.0.0.1", port=8791, access_log=False, log_level="error")
