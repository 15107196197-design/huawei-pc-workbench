#!/usr/bin/env python3
"""One-session review publisher. Run explicitly; importing never starts/publishes.

  uv venv output/publish-env --python .venv/bin/python
  uv pip install --python output/publish-env/bin/python modelscope-hub==0.4.0
  .venv/bin/python scripts/publish_review.py

Open http://127.0.0.1:8790/ to supply tokens locally. Configuration only verifies
identity. The coordinating process must separately POST a publish action, with
Origin: http://127.0.0.1:8790 and X-CSRF-Token from the GET / response header.
Tokens are never persisted, returned, placed in URLs, or used to read browser
cookies. Stopping this process discards them. GitHub upload requires separate
create → prepare → upload actions, the latter with the reviewed manifest hash.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import html
import importlib.metadata
import io
import json
import logging
import re
import secrets
import sys
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "review-site"
ORIGIN = "http://127.0.0.1:8790"
DEFAULT_SLUG = "huawei-pc-content-studio"
CSRF = secrets.token_urlsafe(32)
NONCE = secrets.token_urlsafe(24)
SLUG = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
USERNAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}\Z")
TOP_LEVEL = frozenset({"index.html", "styles.css", "app.js", "config.json", "README.md"})
ASSET_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".pdf", ".json", ".html", ".txt", ".md", ".zip"})
FORBIDDEN_PARTS = frozenset({"data", "output", "env", "venv", "node_modules", "__pycache__", "scripts"})
SOURCE_TOP = frozenset({"README.md", "pyproject.toml", "uv.lock", "requirements.lock", ".env.example", ".gitignore", ".dockerignore", "Dockerfile", "compose.yml", "启动工作台.command", "deploy/modelscope/Dockerfile"})
SOURCE_EXTENSIONS = {
    "huawei_agent": {".py"}, "tests": {".py", ".mjs"}, "scripts": {".py", ".sh"},
    "static": {".html", ".css", ".js", ".svg", ".png", ".jpg", ".jpeg", ".webp", ".ico", ".json"},
    "dify": {".py", ".yml", ".yaml", ".json", ".md", ".example"},
    "docs": {".md", ".json", ".png", ".jpg", ".jpeg", ".pdf", ".svg", ".html", ".css", ".docx"},
    "review-site": {".html", ".css", ".js", ".json", ".md", ".txt", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".pdf", ".zip", ".py"},
    "deploy": {".py", ".md", ".json"},
}
SOURCE_FORBIDDEN = frozenset({"data", "output", "env", "venv", ".venv", ".git", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "build", "dist"})
SENSITIVE_LITERAL = re.compile(rb"(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)")
SENSITIVE_ASSIGNMENT = re.compile(rb"(?i)(?:api[_-]?key|client[_-]?(?:id|secret)|access[_-]?token)\s*[\"']?\s*[:=]\s*[\"']([A-Za-z0-9]{20,})[\"']")
LOCAL_PATH = re.compile(rb"/(?:Users|home)/[A-Za-z0-9_.-]+/")
GIT_SHA = re.compile(r"[0-9a-f]{40}\Z")


class SafeError(Exception):
    def __init__(self, category: str, status: int = 400):
        self.category, self.status = category, status


@dataclass(repr=False)
class Account:
    token: str = ""
    username: str = ""


accounts = {"modelscope": Account(), "github": Account()}
created: dict[str, set[str]] = {"modelscope": set(), "github": set()}
github_heads: dict[str, tuple[str, str]] = {}
prepared_sources: dict[str, str] = {}
operation_lock = asyncio.Lock()
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


def fail_external(exc: Exception) -> SafeError:
    """Never forward exception text, response bodies, URLs, or request headers."""
    code = getattr(exc, "status_code", None)
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
    if code in (401, 403):
        return SafeError("authentication_or_permission", 403)
    if code in (409, 422):
        return SafeError("repository_conflict", 409)
    if isinstance(exc, (httpx.TimeoutException, TimeoutError)) or "Timeout" in type(exc).__name__:
        return SafeError("upstream_timeout", 504)
    return SafeError("upstream_failure", 502)


def load_sdk() -> tuple[Any, Any]:
    """Import the isolated pinned SDK without changing the application deps."""
    candidates = list((ROOT / "output" / "publish-env" / "lib").glob("python*/site-packages"))
    if len(candidates) != 1:
        raise SafeError("publisher_sdk_unavailable", 503)
    location = str(candidates[0])
    if location not in sys.path:
        sys.path.insert(0, location)
    try:
        if importlib.metadata.version("modelscope-hub") != "0.4.0":
            raise SafeError("publisher_sdk_version", 503)
        from modelscope_hub import HubApi, HubConfig
        return HubApi, HubConfig
    except SafeError:
        raise
    except Exception:
        raise SafeError("publisher_sdk_unavailable", 503) from None


def modelscope_api(token: str) -> Any:
    HubApi, HubConfig = load_sdk()

    class MemoryConfig(HubConfig):
        """The official SDK accepts a config; disable its disk credential layer."""
        def _repair_credential_permissions(self) -> None:
            pass

        def load_token(self) -> None:
            return None

        def load_cookies(self) -> None:
            return None

        def load_git_token(self) -> None:
            return None

        def get_session_id(self) -> str:
            return CSRF[:32]

        def ensure_dirs(self) -> None:
            raise SafeError("credential_persistence_forbidden", 500)

        def save_token(self, *_: Any) -> None:
            raise SafeError("credential_persistence_forbidden", 500)

        save_cookies = save_token
        save_git_token = save_token
        save_user_info = save_token

    # Explicit token/config root prevent both environment and saved-login fallback.
    config = MemoryConfig(token=token, endpoint="https://modelscope.cn", config_dir=ROOT / "output" / "unused-publisher-config")
    api = HubApi(config=config)
    # Pinned SDK 0.4.0 uses these requests Sessions for authenticated calls.
    # Bypass environment proxies without changing TLS checks or system settings.
    api.openapi._session.trust_env = False
    api.legacy._session.trust_env = False
    return api


def github_client(token: str) -> httpx.Client:
    return httpx.Client(base_url="https://api.github.com", timeout=30, follow_redirects=False, trust_env=False,
                        headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
                                 "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "Huawei-PC-Review-Publisher/1"})


def verify_account(provider: str, token: str) -> str:
    try:
        if provider == "modelscope":
            # whoami() uses official GET /openapi/v1/users/me. Never call login().
            user = modelscope_api(token).whoami()
            username = user.username
        else:
            with github_client(token) as client:
                response = client.get("/user")
                response.raise_for_status()
                username = response.json().get("login")
        if not isinstance(username, str) or not USERNAME.fullmatch(username):
            raise SafeError("identity_unavailable", 502)
        return username
    except SafeError:
        raise
    except Exception as exc:
        raise fail_external(exc) from None


def public_status() -> dict[str, dict[str, str | bool]]:
    return {key: {"configured": bool(value.token and value.username), "username": value.username}
            for key, value in accounts.items()}


def public_files() -> dict[str, bytes]:
    """Only reviewed static file classes; no build scripts or arbitrary folders."""
    if not SITE.is_dir() or SITE.is_symlink():
        raise SafeError("review_site_unavailable", 409)
    files: dict[str, bytes] = {}
    total = 0
    for path in sorted(SITE.rglob("*")):
        relative = path.relative_to(SITE)
        parts = relative.parts
        if path.is_symlink():
            raise SafeError("review_site_symlink", 409)
        if any(part.startswith(".") or part.lower() in FORBIDDEN_PARTS for part in parts):
            continue
        if not path.is_file():
            continue
        name = relative.as_posix()
        allowed = name in TOP_LEVEL or (len(parts) >= 2 and parts[0] in {"assets", "docs"} and path.suffix.lower() in ASSET_EXTENSIONS)
        if not allowed:
            continue
        if not path.resolve().is_relative_to(SITE.resolve()) or path.stat().st_size > 50 * 1024 * 1024:
            raise SafeError("review_site_file_limit", 409)
        content = path.read_bytes()
        inspect_public_bytes(content)
        total += len(content)
        if total > 100 * 1024 * 1024:
            raise SafeError("review_site_size_limit", 409)
        files[name] = content
    if "index.html" not in files:
        raise SafeError("review_site_entry_missing", 409)
    return files


def inspect_public_bytes(content: bytes, *, archive_depth: int = 0) -> None:
    """Fail closed on credential literals, personal paths, or unsafe ZIP members."""
    if SENSITIVE_LITERAL.search(content) or SENSITIVE_ASSIGNMENT.search(content) or LOCAL_PATH.search(content):
        raise SafeError("source_contains_sensitive_literal", 409)
    local_name = Path.home().name
    if len(local_name) >= 4 and local_name not in {"root", "user", "admin", "runner"} and local_name.encode() in content:
        raise SafeError("source_contains_local_identity", 409)
    for account in accounts.values():
        if len(account.token) >= 8 and account.token.encode() in content:
            raise SafeError("source_contains_sensitive_literal", 409)
    if content.startswith(b"PK\x03\x04"):
        if archive_depth >= 2:
            raise SafeError("source_archive_nesting", 409)
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                members = archive.infolist()
                if len(members) > 1000 or sum(member.file_size for member in members) > 100 * 1024 * 1024:
                    raise SafeError("source_archive_size_limit", 409)
                for member in members:
                    path = Path(member.filename)
                    if path.is_absolute() or ".." in path.parts or member.flag_bits & 1:
                        raise SafeError("source_archive_unsafe", 409)
                    if any(part in SOURCE_FORBIDDEN or part == ".env" for part in path.parts):
                        raise SafeError("source_archive_unsafe", 409)
                    if not member.is_dir():
                        inspect_public_bytes(archive.read(member), archive_depth=archive_depth + 1)
        except SafeError:
            raise
        except Exception:
            raise SafeError("source_archive_invalid", 409) from None


def source_files() -> dict[str, bytes]:
    """A fixed source allowlist, never a client-supplied folder or git checkout."""
    candidates = [ROOT / name for name in SOURCE_TOP]
    for directory in SOURCE_EXTENSIONS:
        parent = ROOT / directory
        if parent.is_symlink():
            raise SafeError("source_symlink", 409)
        if parent.is_dir():
            candidates.extend(parent.rglob("*"))
    files: dict[str, bytes] = {}
    total = 0
    for path in sorted(set(candidates)):
        relative = path.relative_to(ROOT)
        parts = relative.parts
        name = relative.as_posix()
        if path.is_symlink():
            raise SafeError("source_symlink", 409)
        if name not in SOURCE_TOP and any(part.startswith(".") or part.lower() in SOURCE_FORBIDDEN for part in parts):
            continue
        if not path.is_file():
            continue
        allowed = name in SOURCE_TOP or (len(parts) > 1 and path.suffix.lower() in SOURCE_EXTENSIONS.get(parts[0], set()))
        if not allowed:
            continue
        if not path.resolve().is_relative_to(ROOT) or path.stat().st_size > 50 * 1024 * 1024:
            raise SafeError("source_file_limit", 409)
        content = path.read_bytes()
        total += len(content)
        if total > 100 * 1024 * 1024:
            raise SafeError("source_size_limit", 409)
        inspect_public_bytes(content)
        files[name] = content
    if not {"README.md", "pyproject.toml", "requirements.lock"}.issubset(files):
        raise SafeError("source_required_files_missing", 409)
    return files


def source_manifest(files: dict[str, bytes]) -> tuple[str, list[dict[str, Any]]]:
    entries = [{"path": name, "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}
               for name, content in sorted(files.items())]
    digest = hashlib.sha256(json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return digest, entries


def github_identity(slug: str) -> tuple[Account, str]:
    account = accounts["github"]
    if not account.token or not account.username:
        raise SafeError("github_not_configured", 409)
    return account, f"{account.username}/{slug}"


def prepare_github(slug: str) -> dict[str, Any]:
    _, repo_id = github_identity(slug)
    digest, entries = source_manifest(source_files())
    prepared_sources[repo_id] = digest
    return {"repository": repo_id, "manifest_sha256": digest, "files": entries, "uploaded": False}


def github_head(client: httpx.Client, repo_id: str, branch: str) -> str:
    from urllib.parse import quote
    response = client.get(f"/repos/{repo_id}/git/ref/heads/{quote(branch, safe='')}")
    response.raise_for_status()
    sha = response.json().get("object", {}).get("sha", "")
    if not isinstance(sha, str) or not GIT_SHA.fullmatch(sha):
        raise SafeError("github_head_unavailable", 502)
    return sha


def upload_github(slug: str, expected_digest: str) -> dict[str, Any]:
    account, repo_id = github_identity(slug)
    if repo_id not in created["github"] or repo_id not in github_heads:
        raise SafeError("repository_not_created_by_session", 409)
    files = source_files()
    digest, entries = source_manifest(files)
    if prepared_sources.get(repo_id) != digest or not secrets.compare_digest(expected_digest, digest):
        raise SafeError("source_manifest_changed_or_unreviewed", 409)
    branch, expected_head = github_heads[repo_id]
    try:
        with github_client(account.token) as client:
            head = github_head(client, repo_id, branch)
            if head != expected_head:
                raise SafeError("remote_head_changed", 409)

            def blob(item: tuple[str, bytes]) -> dict[str, str]:
                name, content = item
                response = client.post(f"/repos/{repo_id}/git/blobs", json={"encoding": "base64", "content": base64.b64encode(content).decode("ascii")})
                response.raise_for_status()
                sha = response.json().get("sha", "")
                if not isinstance(sha, str) or not GIT_SHA.fullmatch(sha):
                    raise SafeError("github_blob_unavailable", 502)
                return {"path": name, "mode": "100755" if name.endswith((".sh", ".command")) else "100644", "type": "blob", "sha": sha}

            # These immutable blob creations are independent. No branch is changed
            # until every reviewed file, tree, and commit has been created.
            with ThreadPoolExecutor(max_workers=4) as executor:
                tree_entries = list(executor.map(blob, sorted(files.items())))
            response = client.post(f"/repos/{repo_id}/git/trees", json={"tree": tree_entries})
            response.raise_for_status()
            tree_sha = response.json().get("sha", "")
            if not isinstance(tree_sha, str) or not GIT_SHA.fullmatch(tree_sha):
                raise SafeError("github_tree_unavailable", 502)
            response = client.post(f"/repos/{repo_id}/git/commits", json={"message": "Publish reviewed Huawei PC agent source", "tree": tree_sha, "parents": [head]})
            response.raise_for_status()
            commit_sha = response.json().get("sha", "")
            if not isinstance(commit_sha, str) or not GIT_SHA.fullmatch(commit_sha):
                raise SafeError("github_commit_unavailable", 502)
            from urllib.parse import quote
            response = client.patch(f"/repos/{repo_id}/git/refs/heads/{quote(branch, safe='')}", json={"sha": commit_sha, "force": False})
            response.raise_for_status()
            github_heads[repo_id] = (branch, commit_sha)
            prepared_sources.pop(repo_id, None)
        return {"url": f"https://github.com/{repo_id}", "source_uploaded": True, "commit": commit_sha, "manifest_sha256": digest, "uploaded_files": len(entries)}
    except SafeError:
        raise
    except Exception as exc:
        raise fail_external(exc) from None


def publish_modelscope(slug: str) -> dict[str, Any]:
    account = accounts["modelscope"]
    if not account.token or not account.username:
        raise SafeError("modelscope_not_configured", 409)
    files = public_files()  # Validate before any remote mutation.
    repo_id = f"{account.username}/{slug}"
    api = modelscope_api(account.token)
    try:
        from modelscope_hub.errors import NotExistError
        try:
            api.get_repo(repo_id, repo_type="studio")
            exists = True
        except NotExistError:
            exists = False
        if exists and repo_id not in created["modelscope"]:
            raise SafeError("existing_repository_not_owned_by_session", 409)
        if not exists:
            api.create_repo(repo_id, repo_type="studio", visibility="public", sdk_type="static",
                            chinese_name="华为 PC 图文内容 Agent", description="基于 ima 的事实取材、平台适配与图文核验工作台评审展示")
            created["modelscope"].add(repo_id)
        # SDK upload caching is disabled; this directory contains public bytes only.
        with tempfile.TemporaryDirectory(prefix="huawei-review-public-") as temp:
            directory = Path(temp)
            for name, content in files.items():
                target = directory / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
            api.upload_folder(repo_id, repo_type="studio", folder_path=directory, revision="master",
                              allow_patterns=sorted(files), use_cache=False, max_workers=2,
                              disable_tqdm=True, sync_remote_repo=False, commit_message="Publish reviewed project showcase")
        api.deploy_repo(repo_id, repo_type="studio")
        return {"url": f"https://modelscope.cn/studios/{repo_id}", "uploaded_files": len(files), "deployment_requested": True}
    except SafeError:
        raise
    except Exception as exc:
        raise fail_external(exc) from None


def create_github(slug: str) -> dict[str, Any]:
    account, repo_id = github_identity(slug)
    try:
        with github_client(account.token) as client:
            response = client.get(f"/repos/{repo_id}")
            if response.status_code == 200:
                if repo_id not in created["github"]:
                    raise SafeError("existing_repository_not_owned_by_session", 409)
            elif response.status_code == 404:
                response = client.post("/user/repos", json={"name": slug, "private": False, "auto_init": True,
                                                           "description": "华为 PC 图文内容 Agent：ima 取材、平台适配、确定性报价与核验"})
                response.raise_for_status()
                created["github"].add(repo_id)
            else:
                response.raise_for_status()
            if repo_id not in github_heads:
                branch = response.json().get("default_branch", "")
                if not isinstance(branch, str) or not branch or len(branch) > 200:
                    raise SafeError("github_branch_unavailable", 502)
                github_heads[repo_id] = (branch, github_head(client, repo_id, branch))
        return {"url": f"https://github.com/{repo_id}", "source_uploaded": False}
    except SafeError:
        raise
    except Exception as exc:
        raise fail_external(exc) from None


@app.middleware("http")
async def local_only(request: Request, call_next: Any) -> Any:
    if request.client is None or request.client.host not in {"127.0.0.1", "::1"} or request.headers.get("host") != "127.0.0.1:8790":
        return JSONResponse({"error": "loopback_host_required"}, status_code=403)
    if request.method != "GET":
        if request.headers.get("origin") != ORIGIN or not secrets.compare_digest(request.headers.get("x-csrf-token", ""), CSRF):
            return JSONResponse({"error": "origin_or_csrf_rejected"}, status_code=403)
    try:
        response = await call_next(request)
    except Exception:
        return JSONResponse({"error": "publisher_failure"}, status_code=500)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = f"default-src 'none'; script-src 'nonce-{NONCE}'; style-src 'nonce-{NONCE}'; connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
    return response


@app.exception_handler(SafeError)
async def safe_error(_: Request, exc: SafeError) -> JSONResponse:
    return JSONResponse({"error": exc.category}, status_code=exc.status)


@app.exception_handler(RequestValidationError)
async def invalid_request(_: Request, __: RequestValidationError) -> JSONResponse:
    return JSONResponse({"error": "invalid_request"}, status_code=400)


async def body_json(request: Request) -> dict[str, Any]:
    raw = await request.body()
    if len(raw) > 16384:
        raise SafeError("request_too_large", 413)
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError):
        raise SafeError("invalid_json") from None
    if not isinstance(value, dict):
        raise SafeError("invalid_request")
    return value


@app.get("/api/status")
async def status() -> dict[str, Any]:
    return public_status()


@app.post("/api/configure")
async def configure(request: Request) -> dict[str, Any]:
    values = await body_json(request)
    if set(values) - {"modelscope_token", "github_token"}:
        raise SafeError("invalid_request")
    supplied = [(key, values.get(key + "_token", "")) for key in accounts]
    if not any(token for _, token in supplied):
        raise SafeError("token_required")
    for _, token in supplied:
        if not isinstance(token, str) or len(token) > 4096 or any(ch.isspace() or ord(ch) < 33 or ord(ch) > 126 for ch in token):
            raise SafeError("invalid_token_format")
    async with operation_lock:
        verified: dict[str, Account] = {}
        for key, token in supplied:
            if token:
                username = await run_in_threadpool(verify_account, key, token)
                verified[key] = Account(token, username)
        accounts.update(verified)
    return public_status()


@app.post("/api/clear")
async def clear() -> dict[str, Any]:
    async with operation_lock:
        accounts.update({key: Account() for key in accounts})
    return public_status()


@app.post("/api/actions/{provider}/{action}")
async def action(provider: str, action: str, request: Request) -> dict[str, Any]:
    values = await body_json(request)
    slug = values.get("slug", DEFAULT_SLUG)
    allowed = {"slug", "manifest_sha256"} if (provider, action) == ("github", "upload") else {"slug"}
    if set(values) - allowed or not isinstance(slug, str) or not SLUG.fullmatch(slug):
        raise SafeError("invalid_repository_slug")
    async with operation_lock:
        if (provider, action) == ("modelscope", "publish"):
            return await run_in_threadpool(publish_modelscope, slug)
        if (provider, action) == ("github", "create"):
            return await run_in_threadpool(create_github, slug)
        if (provider, action) == ("github", "prepare"):
            return await run_in_threadpool(prepare_github, slug)
        if (provider, action) == ("github", "upload"):
            digest = values.get("manifest_sha256", "")
            if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
                raise SafeError("invalid_manifest_digest")
            return await run_in_threadpool(upload_github, slug, digest)
    raise SafeError("unsupported_action", 404)


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    page = """<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>评审材料发布授权</title>
<style nonce="__NONCE__">body{font:16px system-ui;background:#f4f6fa;color:#1d2939;max-width:660px;margin:6vh auto;padding:24px}main{background:white;border:1px solid #e3e7ee;border-radius:18px;padding:30px}h1{font-size:24px}p{line-height:1.7;color:#526071}label{display:block;margin:20px 0 8px}input{box-sizing:border-box;width:100%;padding:12px;border:1px solid #cbd3df;border-radius:8px}button{margin:22px 10px 0 0;padding:11px 17px;border:0;border-radius:8px;background:#2464db;color:white;cursor:pointer}button:disabled{opacity:.6}#status{white-space:pre-wrap;line-height:1.7}a{color:#2464db}</style>
<main><h1>评审材料发布授权</h1><p>令牌仅在此本机发布进程的内存中使用。这里只验证账号；配置成功后由代理另行发布已经整理好的公开材料。关闭发布进程后授权消失。</p>
<form id="form" autocomplete="off"><label for="ms">魔搭 ModelScope 写权限 Token</label><input id="ms" type="password" name="modelscope-token" autocomplete="off" spellcheck="false" maxlength="4096"><p><a href="https://modelscope.cn/my/access/token" target="_blank" rel="noopener noreferrer">打开魔搭令牌管理</a>，选择允许创建、上传与部署的令牌。</p>
<label for="gh">GitHub Token（可选）</label><input id="gh" type="password" name="github-token" autocomplete="off" spellcheck="false" maxlength="4096"><p>已有 GitHub 发布授权时可留空。此入口仅验证 GitHub 身份；源码上传由代理另行处理。</p><button id="save" type="submit">验证并暂存本次授权</button><button id="clear" type="button">清除本次授权</button></form><p id="status" role="status" aria-live="polite"></p></main>
<script nonce="__NONCE__">const csrf='__CSRF__';const form=document.getElementById('form');const status=document.getElementById('status');const save=document.getElementById('save');const clear=document.getElementById('clear');
function show(data){status.textContent=['魔搭：'+(data.modelscope.configured?'已验证 '+data.modelscope.username:'未配置'),'GitHub：'+(data.github.configured?'已验证 '+data.github.username:'未配置')].join('\\n');}
async function send(url,data){const r=await fetch(url,{method:'POST',credentials:'omit',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(data)});const result=await r.json();if(!r.ok)throw new Error(result.error||'request_failed');return result;}
form.addEventListener('submit',async(e)=>{e.preventDefault();let data={modelscope_token:document.getElementById('ms').value.trim(),github_token:document.getElementById('gh').value.trim()};form.reset();save.disabled=clear.disabled=true;status.textContent='正在验证账号…';try{show(await send('/api/configure',data));}catch(err){status.textContent='未完成：'+err.message;}finally{data=null;save.disabled=clear.disabled=false;}});
clear.addEventListener('click',async()=>{form.reset();save.disabled=clear.disabled=true;try{show(await send('/api/clear',{}));}catch(err){status.textContent='未完成：'+err.message;}finally{save.disabled=clear.disabled=false;}});
fetch('/api/status',{credentials:'omit',cache:'no-store'}).then(r=>r.json()).then(show).catch(()=>status.textContent='状态读取失败');</script></html>"""
    return HTMLResponse(page.replace("__NONCE__", html.escape(NONCE)).replace("__CSRF__", CSRF), headers={"X-CSRF-Token": CSRF})


def main() -> None:
    import uvicorn
    # One-purpose local process: suppress SDK diagnostics and request access logs.
    logging.disable(logging.CRITICAL)
    print("本机一次性发布授权：http://127.0.0.1:8790/（配置只验证身份，不自动发布）", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=8790, access_log=False, log_level="critical", proxy_headers=False)


if __name__ == "__main__":
    main()
