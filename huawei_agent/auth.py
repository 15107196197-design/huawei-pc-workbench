"""Single-operator authentication; opaque sessions never survive a restart."""
from __future__ import annotations

import base64
from collections import defaultdict, deque
import hashlib
import hmac
import re
import secrets
import time

SESSION_COOKIE = "huawei_studio_session"
SESSION_SECONDS = 8 * 60 * 60


def password_parts(value: str) -> tuple[int, bytes, str] | None:
    try:
        algorithm, iterations, salt, digest = str(value).split("$")
        count = int(iterations)
        if (algorithm != "pbkdf2_sha256" or not 1000 <= count <= 2_000_000
                or not re.fullmatch(r"[0-9a-f]{32,128}", salt)
                or not re.fullmatch(r"[0-9a-f]{64}", digest)):
            return None
        return count, bytes.fromhex(salt), digest
    except (ValueError, TypeError):
        return None


def configured(values: dict) -> bool:
    username = values.get("studio_username", "")
    return bool(isinstance(username, str) and username.strip() and ":" not in username
                and len(username) <= 100 and password_parts(values.get("studio_password_hash", "")))


def verify(values: dict, username: str, password: str) -> bool:
    parts = password_parts(values.get("studio_password_hash", ""))
    if not configured(values) or not isinstance(username, str) or not isinstance(password, str):
        return False
    if len(username) > 100 or len(password) > 1024:
        return False
    count, salt, digest = parts
    try:
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, count).hex()
        same_user = hmac.compare_digest(username.encode(), values["studio_username"].encode())
    except UnicodeError:
        return False
    return same_user and hmac.compare_digest(candidate, digest)


def basic_username(values: dict, authorization: str) -> str | None:
    if not authorization.startswith("Basic "):
        return None
    try:
        username, password = base64.b64decode(authorization[6:], validate=True).decode().split(":", 1)
        return username if verify(values, username, password) else None
    except (ValueError, UnicodeError):
        return None


def _identity(values: dict) -> str:
    return hashlib.sha256((values.get("studio_username", "") + "\0" + values.get("studio_password_hash", "")).encode()).hexdigest()


class SessionStore:
    def __init__(self):
        self.sessions: dict[str, tuple[float, str]] = {}

    def _prune(self):
        current = time.monotonic()
        self.sessions = {key: value for key, value in self.sessions.items() if value[0] > current}

    def issue(self, values: dict) -> str:
        self._prune()
        token = secrets.token_urlsafe(32)
        self.sessions[hashlib.sha256(token.encode()).hexdigest()] = (time.monotonic() + SESSION_SECONDS, _identity(values))
        return token

    def username(self, token: str, values: dict) -> str | None:
        if not token or len(token) > 128 or not configured(values):
            return None
        key = hashlib.sha256(token.encode()).hexdigest()
        record = self.sessions.get(key)
        if not record:
            return None
        if record[0] <= time.monotonic() or not hmac.compare_digest(record[1], _identity(values)):
            self.sessions.pop(key, None)
            return None
        return values["studio_username"]

    def revoke(self, token: str):
        self.sessions.pop(hashlib.sha256(token.encode()).hexdigest(), None)


class LoginLimiter:
    """Five failures per peer and fifty overall within five minutes."""
    def __init__(self):
        self.failures: dict[str, deque] = defaultdict(deque)
        self.overall = deque()

    def _prune(self):
        cutoff = time.monotonic() - 300
        while self.overall and self.overall[0] <= cutoff:
            self.overall.popleft()
        for peer, failures in list(self.failures.items()):
            while failures and failures[0] <= cutoff:
                failures.popleft()
            if not failures:
                self.failures.pop(peer, None)

    def blocked(self, peer: str) -> bool:
        self._prune()
        return len(self.failures.get(peer, ())) >= 5 or len(self.overall) >= 50

    def failed(self, peer: str):
        current = time.monotonic()
        self.failures[peer].append(current)
        self.overall.append(current)

    def succeeded(self, peer: str):
        self.failures.pop(peer, None)


sessions = SessionStore()
login_limiter = LoginLimiter()
