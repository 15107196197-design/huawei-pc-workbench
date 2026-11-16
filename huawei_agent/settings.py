from __future__ import annotations

import json
import ipaddress
import os
import re
import secrets
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("STUDIO_DATA_DIR") or ROOT / "data").expanduser().resolve()
DATA.mkdir(parents=True, exist_ok=True)
(DATA / "media").mkdir(parents=True, exist_ok=True)
CONFIG = DATA / "settings.json"

DEFAULTS = {
    "dify_base_url": "https://api.dify.ai/v1",
    "dify_api_key": "", "deepseek_api_key": "",
    "deepseek_base_url": "https://api.deepseek.com",
    "dashscope_api_key": "", "dashscope_base_url": "https://dashscope.aliyuncs.com",
    "text_model": "deepseek-flash", "vision_model": "qwen3-vl-plus",
    "image_model": "qwen-image-2.1-pro", "tavily_api_key": "",
    "public_api_base": "", "tool_token": "",
    "studio_username": "", "studio_password_hash": "",
    "studio_hosted": "0", "studio_managed_config": "0",
    "studio_allowed_origins": "",
}


def enabled(value) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def hosted(values: dict) -> bool:
    return enabled(values.get("studio_hosted"))


def managed_config(values: dict) -> bool:
    return hosted(values) or enabled(values.get("studio_managed_config"))


def allowed_origins(values: dict) -> frozenset[str] | None:
    """An explicit JSON origin allowlist, independent of proxy-supplied headers."""
    raw = values.get("studio_allowed_origins", "")
    if isinstance(raw, str) and not raw.strip():
        return None
    message = "STUDIO_ALLOWED_ORIGINS必须是非空的HTTPS origin JSON字符串数组（无路径或尾斜线）"
    try:
        entries = json.loads(raw)
        if not isinstance(entries, list) or not 1 <= len(entries) <= 16:
            raise ValueError(message)
        for origin in entries:
            if (not isinstance(origin, str) or not origin.isascii() or len(origin) > 2048
                    or any(ord(char) <= 32 or ord(char) == 127 or char in "\\*?#" for char in origin)):
                raise ValueError(message)
            parsed = urlparse(origin)
            if (not origin.startswith("https://") or parsed.scheme != "https" or not parsed.hostname
                    or parsed.path or parsed.params or parsed.query or parsed.fragment
                    or parsed.username is not None or parsed.password is not None
                    or parsed.netloc.endswith(":")):
                raise ValueError(message)
            if parsed.port is not None and not 1 <= parsed.port <= 65535:
                raise ValueError(message)
            if ":" in parsed.hostname:
                ipaddress.IPv6Address(parsed.hostname)
            elif (len(parsed.hostname) > 253 or any(not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
                    for label in parsed.hostname.rstrip(".").split("."))):
                raise ValueError(message)
        return frozenset(entries)
    except (ValueError, TypeError):
        raise ValueError(message) from None


def load_settings() -> dict:
    values = dict(DEFAULTS)
    # A small dotenv reader: no shell execution or expansion.
    envfile = ROOT / ".env"
    if envfile.exists():
        for line in envfile.read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                if key.lower().strip() in values:
                    values[key.lower().strip()] = val.strip().strip("\"'")
    if CONFIG.exists():
        values.update(json.loads(CONFIG.read_text(encoding="utf-8")))
    for key in DEFAULTS:
        if os.environ.get(key.upper()):
            values[key] = os.environ[key.upper()]
    return values


def save_settings(changes: dict) -> None:
    values = load_settings()
    for key, val in changes.items():
        if key not in DEFAULTS or not isinstance(val, str):
            raise ValueError(f"不支持的配置项：{key}")
        # Blank secret input means keep the existing secret; it is never returned.
        if key.endswith("key") or key == "tool_token":
            if val.strip():
                values[key] = val.strip()
        elif key.endswith("url") or key == "public_api_base":
            if val and (urlparse(val).scheme != "https" or not urlparse(val).hostname):
                raise ValueError("外部服务地址必须是有效的 HTTPS 地址")
            values[key] = val.rstrip("/")
        else:
            values[key] = val.strip()
    # User-provisioned IMA credentials are deliberately never stored here.
    tmp = CONFIG.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(values, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG)
    os.chmod(CONFIG, 0o600)


def get_ima_credentials() -> tuple[str, str]:
    base = Path.home() / ".config" / "ima"
    def read(name: str) -> str:
        path = base / name
        return path.read_text(encoding="utf-8").strip() if path.exists() else ""
    return (
        os.environ.get("IMA_OPENAPI_CLIENTID") or os.environ.get("IMA_CLIENT_ID") or read("client_id"),
        os.environ.get("IMA_OPENAPI_APIKEY") or os.environ.get("IMA_API_KEY") or read("api_key"),
    )


def configured() -> dict:
    s = load_settings()
    return {"ima": all(get_ima_credentials()), "dify": bool(s["dify_api_key"]),
            "deepseek": bool(s["deepseek_api_key"]), "vision": bool(s["dashscope_api_key"]),
            "image": bool(s["dashscope_api_key"]), "search": bool(s["deepseek_api_key"] or s["tavily_api_key"])}


def dify_ready() -> bool:
    s = load_settings()
    return bool(s["dify_api_key"] and s["public_api_base"] and s["tool_token"])
