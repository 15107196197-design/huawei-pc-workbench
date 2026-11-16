"""Hosted single-operator boundaries, with synthetic credentials and isolated files."""
import base64
import hashlib
import importlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from huawei_agent import auth, settings, store

api = importlib.import_module("huawei_agent.app")
ORIGIN = "https://synthetic-studio.example"
PASSWORD = "synthetic-operator-password"


def password_hash(password=PASSWORD, salt="00112233445566778899aabbccddeeff"):
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 1000).hex()
    return f"pbkdf2_sha256$1000${salt}${digest}"


class HostedAuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.config = dict(settings.DEFAULTS, studio_hosted="1", studio_username="合成操作者",
                           studio_password_hash=password_hash(), tool_token="synthetic-tool-token")
        for module, name, value in [
            (api, "load_settings", lambda: self.config),
            (api, "configured", lambda: {name: False for name in ["ima", "dify", "deepseek", "image", "vision", "search"]}),
            (api, "dify_ready", lambda: False),
            (store, "DATA", Path(self.directory.name)),
            (api, "DATA", Path(self.directory.name)),
            (auth, "sessions", auth.SessionStore()),
            (auth, "login_limiter", auth.LoginLimiter()),
        ]:
            patcher = patch.object(module, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for name in ["connect", "asset_bytes", "retrieve"]:
            patcher = patch.object(api.knowledge, name, new_callable=AsyncMock,
                                   side_effect=AssertionError("认证测试不调用真实资料或模型"))
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = TestClient(api.app, base_url=ORIGIN, client=("127.0.0.1", 45000),
                                 raise_server_exceptions=False, follow_redirects=False)
        self.addCleanup(self.client.close)

    def login(self, **changes):
        return self.client.post("/api/login", json={"username": self.config["studio_username"], "password": PASSWORD} | changes,
                                headers={"Origin": ORIGIN})

    def test_post_save_routes_keep_session_and_origin_protection(self):
        paths = [f"/api/tasks/{'a' * 32}/{suffix}" for suffix in ["brief", "draft"]]
        for path in paths:
            self.assertEqual(self.client.post(path, json={}, headers={"Origin": ORIGIN}).status_code, 401)
        self.assertEqual(self.login().status_code, 200)
        task = self.client.post("/api/tasks", json={}, headers={"Origin": ORIGIN}).json()
        for suffix in ["brief", "draft"]:
            path = f"/api/tasks/{task['id']}/{suffix}"
            for origin in [None, "null", "https://unrelated.example"]:
                headers = {} if origin is None else {"Origin": origin}
                self.assertEqual(self.client.post(path, json={}, headers=headers).status_code, 403)
        response = self.client.post(f"/api/tasks/{task['id']}/brief", json={"brief": {"goal": "同源保存测试"}}, headers={"Origin": ORIGIN})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["brief"]["goal"], "同源保存测试")

    def test_hosted_startup_requires_complete_valid_login_before_knowledge_connection(self):
        for changes in [{"studio_username": ""}, {"studio_password_hash": ""},
                        {"studio_password_hash": "pbkdf2_sha256$999999999$bad$bad"}]:
            with self.subTest(changes=changes), patch.object(api, "load_settings", return_value=self.config | changes):
                with self.assertRaisesRegex(RuntimeError, "STUDIO_USERNAME"):
                    with TestClient(api.app):
                        pass
        api.knowledge.connect.assert_not_awaited()

    def test_loopback_proxy_and_forwarding_headers_never_bypass_missing_hosted_configuration(self):
        self.config["studio_password_hash"] = ""
        result = self.client.get("/api/tasks", headers={"X-Forwarded-For": "127.0.0.1", "X-Forwarded-Host": "localhost"})
        self.assertEqual(result.status_code, 503)
        self.assertNotIn("合成操作者", result.text)

    def test_health_and_login_are_public_without_sensitive_status(self):
        result = self.client.get("/healthz")
        self.assertEqual(result.json(), {"status": "ok"})
        self.assertNotIn("synthetic-tool-token", result.text)
        page = self.client.get("/login")
        self.assertEqual(page.status_code, 200)
        self.assertNotIn(self.config["studio_username"], page.text)
        self.assertNotIn(self.config["studio_password_hash"], page.text)

    def test_unauthenticated_routes_reject_tasks_media_exports_settings_and_model_actions(self):
        for method, path in [
            ("GET", "/api/status"), ("GET", "/api/tasks"), ("POST", "/api/tasks"),
            ("GET", "/api/tasks/unknown"), ("POST", "/api/tasks/unknown/generate"),
            ("POST", "/api/tasks/unknown/background"), ("POST", "/api/tasks/unknown/vision"),
            ("GET", "/api/assets/unknown"), ("GET", "/api/files/unknown.png"),
            ("GET", "/api/tasks/unknown/export?format=zip"), ("GET", "/api/tasks/unknown/copy"),
            ("POST", "/api/settings"), ("POST", "/api/connections/test"),
        ]:
            with self.subTest(path=path):
                result = self.client.request(method, path, headers={"Origin": ORIGIN})
                self.assertEqual(result.status_code, 401)
        root = self.client.get("/")
        self.assertEqual(root.status_code, 303)
        self.assertEqual(root.headers["location"], "/login")
        api.knowledge.asset_bytes.assert_not_awaited()
        api.knowledge.retrieve.assert_not_awaited()

    def test_cookie_authentication_works_and_secret_fields_are_never_returned(self):
        result = self.login()
        self.assertEqual(result.status_code, 200)
        cookie = result.headers["set-cookie"].lower()
        for attribute in ["httponly", "secure", "samesite=none", "partitioned", "max-age=28800", "path=/"]:
            self.assertIn(attribute, cookie)
        self.assertNotIn("domain=", cookie)
        status = self.client.get("/api/status")
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["authentication"], {"enabled": True, "method": "session", "shared_workspace": True})
        self.assertEqual(status.json()["user"]["name"], "合成操作者")
        self.assertTrue(status.json()["managed_config"])
        self.assertNotIn(self.config["studio_password_hash"], status.text)
        self.assertNotIn(self.config["tool_token"], status.text)
        created = self.client.post("/api/tasks", json={"title": "线上合成任务"}, headers={"Origin": ORIGIN})
        self.assertEqual(created.status_code, 200)
        task_id = created.json()["id"]
        self.assertEqual(self.client.get("/api/tasks/" + task_id).json()["title"], "线上合成任务")
        self.assertEqual(store.get_task(task_id)["owner"], "local")

    def test_tampering_expiry_password_rotation_and_logout_revoke_sessions(self):
        self.assertEqual(self.login().status_code, 200)
        token = self.client.cookies.get(auth.SESSION_COOKIE)
        self.client.cookies.clear()
        self.client.cookies.set(auth.SESSION_COOKIE, "different-opaque-token", domain="synthetic-studio.example", path="/")
        self.assertEqual(self.client.get("/api/tasks").status_code, 401)
        self.client.cookies.clear()
        self.client.cookies.set(auth.SESSION_COOKIE, token, domain="synthetic-studio.example", path="/")
        key = hashlib.sha256(token.encode()).hexdigest()
        auth.sessions.sessions[key] = (time.monotonic() - 1, auth.sessions.sessions[key][1])
        self.assertEqual(self.client.get("/api/tasks").status_code, 401)
        self.assertEqual(self.login().status_code, 200)
        self.config["studio_password_hash"] = password_hash(salt="11112233445566778899aabbccddeeff")
        self.assertEqual(self.client.get("/api/tasks").status_code, 401)
        self.assertEqual(self.login().status_code, 200)
        token = self.client.cookies.get(auth.SESSION_COOKIE)
        logout = self.client.post("/api/logout", headers={"Origin": ORIGIN})
        self.assertEqual(logout.status_code, 200)
        for attribute in ["httponly", "secure", "samesite=none", "partitioned", "max-age=0", "path=/"]:
            self.assertIn(attribute, logout.headers["set-cookie"].lower())
        self.assertEqual(self.client.get("/api/tasks").status_code, 401)
        self.client.cookies.set(auth.SESSION_COOKIE, token, domain="synthetic-studio.example", path="/")
        self.assertEqual(self.client.get("/api/tasks").status_code, 401)

    def test_basic_auth_is_not_a_hosted_cookie_login_bypass(self):
        credentials = base64.b64encode((self.config["studio_username"] + ":" + PASSWORD).encode()).decode()
        self.assertEqual(self.client.get("/api/tasks", headers={"Authorization": "Basic " + credentials}).status_code, 401)

    def test_hosted_frame_policy_allows_only_self_and_modelscope_on_success_and_denials(self):
        expected = "frame-ancestors 'self' https://modelscope.cn https://www.modelscope.cn"
        for response in [self.client.get("/login"), self.client.get("/api/tasks"),
                         self.client.post("/api/login", json={}, headers={"Origin": "https://unrelated.example"})]:
            self.assertEqual(response.headers["content-security-policy"], expected)
            self.assertNotIn("*", response.headers["content-security-policy"])
        self.assertEqual(self.login().headers["content-security-policy"], expected)
        self.assertEqual(self.client.get("/").headers["content-security-policy"], expected)

    def test_local_cookie_keeps_lax_without_partitioned_and_logout_matches(self):
        self.config["studio_hosted"] = "0"
        client = TestClient(api.app, base_url="http://localhost", client=("127.0.0.1", 45001))
        self.addCleanup(client.close)
        result = client.post("/api/login", json={"username": self.config["studio_username"], "password": PASSWORD},
                             headers={"Origin": "http://localhost"})
        self.assertEqual(result.status_code, 200)
        for response in [result, client.post("/api/logout", headers={"Origin": "http://localhost"})]:
            cookie = response.headers["set-cookie"].lower()
            self.assertIn("samesite=lax", cookie)
            self.assertIn("httponly", cookie)
            self.assertNotIn("partitioned", cookie)
            self.assertNotIn("secure", cookie)

    def test_online_mutations_require_exact_same_origin_even_with_valid_cookie(self):
        body = {"username": self.config["studio_username"], "password": PASSWORD}
        for headers in [{}, {"Origin": "https://unrelated.example"}, {"Origin": "http://synthetic-studio.example"}]:
            self.assertEqual(self.client.post("/api/login", json=body, headers=headers).status_code, 403)
        self.assertEqual(self.login().status_code, 200)
        for route in ["/api/tasks", "/api/logout", "/api/settings"]:
            self.assertEqual(self.client.post(route, json={}, headers={"Origin": "https://unrelated.example"}).status_code, 403)
        self.assertEqual(self.client.get("/api/tasks").status_code, 200)

    def test_explicit_origins_allow_verified_browser_origin_despite_rewritten_proxy_host(self):
        self.config["studio_allowed_origins"] = json.dumps([ORIGIN, "https://verified-api.example"])
        headers = {"Origin": ORIGIN, "Host": "internal-service:7860", "X-Forwarded-Host": "untrusted.example"}
        login = self.client.post("/api/login", json={"username": self.config["studio_username"], "password": PASSWORD}, headers=headers)
        self.assertEqual(login.status_code, 200)
        created = self.client.post("/api/tasks", json={"title": "反代来源测试"}, headers=headers)
        self.assertEqual(created.status_code, 200)
        self.assertEqual(self.client.get("/api/tasks/" + created.json()["id"], headers={"Host": "internal-service:7860"}).status_code, 200)

    def test_explicit_origins_reject_nonmembers_subdomains_missing_and_forwarded_origins(self):
        self.config["studio_allowed_origins"] = json.dumps([ORIGIN])
        body = {"username": self.config["studio_username"], "password": PASSWORD}
        for origin in [None, "http://synthetic-studio.example", "https://sub.synthetic-studio.example",
                       "https://synthetic-studio.example.evil.invalid", "https://internal-service:7860"]:
            headers = {"Host": "internal-service:7860", "X-Forwarded-Host": "synthetic-studio.example",
                       "X-Forwarded-Proto": "https", "X-Forwarded-Origin": ORIGIN}
            if origin is not None:
                headers["Origin"] = origin
            with self.subTest(origin=origin):
                self.assertEqual(self.client.post("/api/login", json=body, headers=headers).status_code, 403)

    def test_invalid_explicit_origin_configuration_fails_closed_and_prevents_startup(self):
        invalid = ["not-json", json.dumps({"origin": ORIGIN}), "[]", json.dumps([None]), json.dumps([123]),
                   json.dumps(["http://synthetic-studio.example"]), json.dumps([ORIGIN + "/"]),
                   json.dumps([ORIGIN + "/path"]), json.dumps([ORIGIN + "?query=1"]),
                   json.dumps([ORIGIN + "#fragment"]), json.dumps(["https://user@synthetic-studio.example"]),
                   json.dumps(["https://*.example"]), json.dumps(["https://example.com:99999"])]
        for value in invalid:
            with self.subTest(value=value):
                self.config["studio_allowed_origins"] = value
                with self.assertRaisesRegex(ValueError, "STUDIO_ALLOWED_ORIGINS"):
                    settings.allowed_origins(self.config)
                self.assertEqual(self.client.get("/healthz").status_code, 503)
                with self.assertRaisesRegex(RuntimeError, "STUDIO_ALLOWED_ORIGINS"):
                    with TestClient(api.app):
                        pass
        api.knowledge.connect.assert_not_awaited()

    def test_unconfigured_origin_allowlist_preserves_strict_host_matching(self):
        self.assertIsNone(settings.allowed_origins(self.config))
        body = {"username": self.config["studio_username"], "password": PASSWORD}
        rejected = self.client.post("/api/login", json=body, headers={"Origin": ORIGIN, "Host": "internal-service:7860"})
        self.assertEqual(rejected.status_code, 403)
        self.assertEqual(self.login().status_code, 200)

    def test_login_origin_diagnostics_are_bounded_and_never_log_sensitive_request_values(self):
        self.config["studio_allowed_origins"] = json.dumps([ORIGIN])
        secret = "synthetic-never-log-password-or-token"
        with self.assertLogs(api.logger, level="WARNING") as records:
            response = self.client.post("/api/login", json={"username": secret, "password": secret}, headers={
                "Origin": "https://" + secret + "@evil.example/path?token=" + secret,
                "Host": secret + "@internal.example/" + secret,
                "Authorization": "Bearer " + secret, "Cookie": "private=" + secret,
            })
        self.assertEqual(response.status_code, 403)
        logged = "\n".join(records.output)
        self.assertIn("event=origin_rejected reason=not_allowed", logged)
        self.assertIn("origin_scheme=invalid origin_hostname=invalid origin_port=invalid request_host_hostname=invalid", logged)
        self.assertNotIn(secret, logged)
        self.assertNotIn("Bearer", logged)
        self.assertNotIn("Cookie", logged)
        self.assertLess(len(logged), 400)

    def test_login_origin_diagnostic_reasons_do_not_change_rejection_or_acceptance(self):
        self.config["studio_allowed_origins"] = json.dumps([ORIGIN])
        for origin, reason in [(None, "missing_origin"), ("null", "null_origin"),
                               ("http://other.example", "https_required"), ("https://other.example:8443", "not_allowed")]:
            headers = {"Host": "INTERNAL.Service:7860"}
            if origin is not None:
                headers["Origin"] = origin
            with self.subTest(reason=reason), self.assertLogs(api.logger, level="WARNING") as records:
                self.assertEqual(self.client.post("/api/login", json={}, headers=headers).status_code, 403)
            self.assertIn("reason=" + reason, records.output[0])
            self.assertIn("request_host_hostname=internal.service", records.output[0])
            if origin == "https://other.example:8443":
                self.assertIn("origin_scheme=https origin_hostname=other.example origin_port=8443", records.output[0])
        with patch.object(api.logger, "warning") as warning:
            self.assertEqual(self.login().status_code, 200)
            self.assertEqual(self.client.post("/api/tasks", json={}, headers={"Origin": "https://other.example"}).status_code, 403)
            warning.assert_not_called()
        self.config["studio_allowed_origins"] = ""
        with self.assertLogs(api.logger, level="WARNING") as records:
            self.assertEqual(self.client.post("/api/login", json={}, headers={"Origin": ORIGIN, "Host": "internal.service:7860"}).status_code, 403)
        self.assertIn("reason=host_mismatch", records.output[0])
        self.config["studio_allowed_origins"] = "invalid-json"
        with self.assertLogs(api.logger, level="WARNING") as records:
            self.assertEqual(self.client.post("/api/login", json={}, headers={"Origin": ORIGIN}).status_code, 503)
        self.assertIn("reason=config_invalid", records.output[0])

    def test_diagnostic_origin_normalization_rejects_invalid_authorities(self):
        self.assertEqual(api._diagnostic_origin("https://[2001:0db8::1]:8443"), ("https", "2001:db8::1", 8443))
        for value in ["https://user:password@example.com", "https://example.com/path", "https://example.com?token=private",
                      "https://[fe80::1%private]", "https://bad..example", "https://example.com:99999", "https://" + "a" * 600]:
            with self.subTest(value=value):
                self.assertEqual(api._diagnostic_origin(value), ("invalid", "invalid", "invalid"))

    def test_failed_login_rate_limit_cannot_be_avoided_by_forwarding_headers(self):
        for _ in range(5):
            self.assertEqual(self.login(password="incorrect").status_code, 401)
        limited = self.login()
        self.assertEqual(limited.status_code, 429)
        self.assertEqual(limited.headers["retry-after"], "300")
        spoofed = self.client.post("/api/login", json={"username": self.config["studio_username"], "password": PASSWORD},
                                   headers={"Origin": ORIGIN, "X-Forwarded-For": "198.51.100.99"})
        self.assertEqual(spoofed.status_code, 429)

    def test_managed_settings_reject_all_writes_before_touching_configuration(self):
        self.assertEqual(self.login().status_code, 200)
        with patch.object(api, "save_settings") as save:
            result = self.client.post("/api/settings", json={"deepseek_base_url": "https://attacker.invalid", "studio_hosted": "0",
                "studio_username": "", "studio_password_hash": "", "tool_token": "replacement"}, headers={"Origin": ORIGIN})
            self.assertEqual(result.status_code, 403)
            save.assert_not_called()
        self.config["studio_hosted"] = "0"
        self.config["studio_managed_config"] = "1"
        with patch.object(api, "save_settings") as save:
            self.assertEqual(self.client.post("/api/settings", json={"text_model": "different"}, headers={"Origin": ORIGIN}).status_code, 403)
            save.assert_not_called()

    def test_tool_header_support_is_independent_of_cookie_and_never_ignores_a_wrong_credential(self):
        self.assertEqual(self.login().status_code, 200)
        token = self.config["tool_token"]
        for headers in [{}, {"X-Tool-Token": "wrong"}, {"Authorization": "Bearer wrong"},
                        {"X-Tool-Token": token, "Authorization": "Bearer wrong"},
                        {"X-Tool-Token": "wrong", "Authorization": "Bearer " + token}]:
            self.assertEqual(self.client.post("/api/tools/quotes", json={"offers": []}, headers=headers).status_code, 401)
        for headers in [{"X-Tool-Token": token}, {"Authorization": "Bearer " + token},
                        {"X-Tool-Token": token, "Authorization": "Bearer " + token}]:
            self.assertEqual(self.client.post("/api/tools/quotes", json={"offers": []}, headers=headers).status_code, 200)


if __name__ == "__main__":
    unittest.main()
