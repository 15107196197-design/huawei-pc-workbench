"""Offline publication boundaries; only synthetic credentials and mocked transports."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, create_autospec, patch

import httpx
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("publish_app_under_test", ROOT / "scripts/publish_app.py")
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)
common = publisher.common
REAL_CONFIGURATION = publisher.configuration
try:
    HubApi, HubConfig = common.load_sdk()
    from modelscope_hub.errors import APIError, NotExistError
except common.SafeError:
    # Publishing is an optional tool, separate from the core application runtime.
    HubApi = HubConfig = APIError = NotExistError = None


SYNTHETIC = {
    "DEEPSEEK_API_KEY": "synthetic-deepseek-value-0123456789",
    "DASHSCOPE_API_KEY": "synthetic-dashscope-value-0123456789",
    "IMA_OPENAPI_CLIENTID": "synthetic-ima-client-id-0123456789",
    "IMA_OPENAPI_APIKEY": "synthetic-ima-apikey-0123456789",
    "STUDIO_USERNAME": "studio",
    "STUDIO_PASSWORD_HASH": "synthetic-pbkdf-hash-0123456789",
}
HARDWARE = {"name": "platform/2v-cpu-8g-mem", "resource_type": "free", "supported_sdk_types": ["docker"]}


class PublicationTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patches = [
            patch.object(publisher, "ROOT", self.root),
            patch.object(publisher, "configuration", return_value=dict(SYNTHETIC)),
            patch.object(Path, "home", return_value=Path("/home/synthetic_local_identity")),
            patch("requests.sessions.Session.send", side_effect=AssertionError("Real network forbidden in publication test")),
            patch.object(httpx.HTTPTransport, "handle_request", side_effect=AssertionError("Real network forbidden in publication test")),
        ]
        for item in self.patches:
            item.start()
        self.addCleanup(lambda: [item.stop() for item in reversed(self.patches)])
        self.addCleanup(self.temp.cleanup)
        publisher.account = common.Account("synthetic-publish-token-0123456789", "synthetic-owner")
        publisher.created.clear()
        publisher.resumed_applications.clear()
        publisher.prepared = ""
        publisher.stage = "authorized"
        publisher.deployment = {}
        if publisher.cloud_client:
            publisher.cloud_client.close()
        publisher.cloud_client = None
        publisher.cloud_host = ""
        self.repo = f"synthetic-owner/{publisher.SLUG}"
        for name, content in {
            "huawei_agent/app.py": b"print('application')\n",
            "static/index.html": b"<!doctype html><h1>Workbench</h1>",
            "static/app.js": b"console.log('public client')",
            "requirements.lock": b"# synthetic locked dependencies\n",
            "deploy/modelscope/Dockerfile": b"FROM python:3.12-slim\nEXPOSE 7860\n",
            "deploy/modelscope/entrypoint.py": b"# synthetic startup\n",
            "deploy/modelscope/healthcheck.py": b"# synthetic health\n",
            "data/settings.json": json.dumps(SYNTHETIC).encode(),
            ".env": b"SYNTHETIC_PRIVATE_DATA=not-public\n",
            "output/private.txt": b"not-public",
            "static/data/hidden.html": b"private nested directory",
        }.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)

    def api_mock(self):
        api = create_autospec(HubApi, instance=True)
        api.openapi = MagicMock()
        api.list_studio_hardware.return_value = [dict(HARDWARE)]
        api.get_repo.side_effect = NotExistError("synthetic absent", status_code=404)
        api.list_secrets.return_value = [{"key": "DEEPSEEK_API_KEY"}]
        api.openapi.get_studio.return_value = {
            "status": "Running", "runtime": {"status": "running"},
            "host": "https://synthetic-owner-huawei-pc-agent-app-v2.ms.show",
            "visibility": "public", "sdk_type": "docker",
            "hardware": HARDWARE["name"],
        }
        return api

    def prepare(self):
        result = publisher.manifest(publisher.application_files())
        publisher.prepared = result["manifest_sha256"]
        return result

    def assert_safe_error(self, category, callback):
        with self.assertRaises(common.SafeError) as raised:
            callback()
        self.assertEqual(raised.exception.category, category)


class ManifestAndSourceTests(PublicationTestCase):
    def test_allowed_origins_configuration_matches_core_exact_json_contract(self):
        values = {key: "synthetic-config-value" for key in [
            "deepseek_api_key", "deepseek_base_url", "dashscope_api_key", "dashscope_base_url",
            "text_model", "vision_model", "image_model",
        ]}
        with patch.object(publisher, "load_settings", return_value=values), patch.object(publisher, "get_ima_credentials", return_value=("synthetic-client-id", "synthetic-api-key")):
            result = REAL_CONFIGURATION()
        expected = ["https://synthetic-owner-huawei-pc-agent-app-v2.ms.show", "https://studio-synthetic-owner-huawei-pc-agent-app-v2.api-inference.modelscope.net"]
        self.assertEqual(json.loads(result["STUDIO_ALLOWED_ORIGINS"]), expected)
        from huawei_agent.settings import allowed_origins
        self.assertEqual(allowed_origins({"studio_allowed_origins": result["STUDIO_ALLOWED_ORIGINS"]}), frozenset(expected))

    def test_only_public_application_whitelist_is_loaded(self):
        files = publisher.application_files()
        self.assertEqual(set(files), {
            "huawei_agent/app.py", "static/index.html", "static/app.js", "requirements.lock",
            "deploy/modelscope/entrypoint.py", "deploy/modelscope/healthcheck.py", "Dockerfile", "README.md",
        })
        combined = b"\n".join(files.values())
        for value in SYNTHETIC.values():
            if len(value) >= 8:
                self.assertNotIn(value.encode(), combined)

    def test_known_provider_secret_or_local_identity_blocks_upload(self):
        for content in [SYNTHETIC["IMA_OPENAPI_CLIENTID"], "synthetic_local_identity"]:
            (self.root / "static/app.js").write_text(content)
            with self.assertRaises(common.SafeError):
                publisher.application_files()

    def test_unknown_credential_literal_blocks_upload(self):
        (self.root / "static/app.js").write_text("const value = 'sk-" + "x" * 32 + "';")
        self.assert_safe_error("source_contains_sensitive_literal", publisher.application_files)

    def test_fixed_file_symlink_is_rejected(self):
        path = self.root / "requirements.lock"
        path.unlink()
        path.symlink_to(self.root / "data/settings.json")
        self.assert_safe_error("application_symlink", publisher.application_files)

    def test_source_directory_symlink_is_rejected(self):
        (self.root / "huawei_agent/app.py").unlink()
        (self.root / "huawei_agent").rmdir()
        (self.root / "huawei_agent").symlink_to(self.root / "static", target_is_directory=True)
        self.assert_safe_error("application_source_directory_invalid", publisher.application_files)

    def test_manifest_changes_block_all_remote_calls(self):
        digest = self.prepare()["manifest_sha256"]
        (self.root / "static/app.js").write_text("console.log('changed')")
        with patch.object(publisher, "api") as api:
            self.assert_safe_error("application_manifest_changed_or_not_reviewed", lambda: publisher.publish(digest))
        api.assert_not_called()


@unittest.skipUnless(HubApi is not None, "Optional isolated ModelScope publishing SDK is not installed")
class PublishFlowTests(PublicationTestCase):
    def test_restart_only_deploys_current_free_docker_application(self):
        publisher.created.add(self.repo)
        api = self.api_mock()
        with patch.object(publisher, "api", return_value=api):
            result = publisher.restart_application()
        self.assertTrue(result["restart_requested"])
        api.deploy_repo.assert_called_once_with(self.repo, repo_type="studio")
        api.list_studio_hardware.assert_called_once_with(sdk_type="docker", repo_id=self.repo)
        api.create_repo.assert_not_called()
        api.upload_folder.assert_not_called()
        api.list_secrets.assert_not_called()
        api.add_secret.assert_not_called()
        api.update_secret.assert_not_called()

    def test_restart_rejects_unrelated_or_paid_application_before_mutation(self):
        api = self.api_mock()
        with patch.object(publisher, "api", return_value=api):
            self.assert_safe_error("application_not_created_by_session", publisher.restart_application)
        publisher.created.add(self.repo)
        api.openapi.get_studio.return_value["hardware"] = "paid/instance"
        with patch.object(publisher, "api", return_value=api):
            self.assert_safe_error("current_application_not_verified_free_docker", publisher.restart_application)
        api.deploy_repo.assert_not_called()

    def test_create_secrets_upload_deploy_status_follow_sdk_signatures(self):
        digest = self.prepare()["manifest_sha256"]
        api = self.api_mock()
        uploaded = {}

        def capture_upload(repo_id, repo_type, folder_path, **options):
            for path in Path(folder_path).rglob("*"):
                if path.is_file():
                    uploaded[path.relative_to(folder_path).as_posix()] = path.read_bytes()
            self.assertEqual(repo_id, self.repo)
            self.assertEqual(repo_type, "studio")
            self.assertEqual(options["allow_patterns"], sorted(uploaded))
            self.assertFalse(options["use_cache"])
            self.assertFalse(options["sync_remote_repo"])
            self.assertEqual(options["revision"], "master")

        api.upload_folder.side_effect = capture_upload
        with patch.object(publisher, "api", return_value=api):
            result = publisher.publish(digest)
            info = publisher.remote_info()
        api.create_repo.assert_called_once_with(
            self.repo, repo_type="studio", visibility="public", sdk_type="docker",
            hardware=HARDWARE["name"], display_name="华为 PC 图文工作台 第二版",
            description="可登录操作的图文Agent：ima取材、模型生成、规则报价、核验与导出",
        )
        api.list_secrets.assert_called_once_with(self.repo)
        api.update_secret.assert_called_once_with(self.repo, "DEEPSEEK_API_KEY", SYNTHETIC["DEEPSEEK_API_KEY"])
        self.assertEqual(api.add_secret.call_count, len(SYNTHETIC) - 1)
        api.deploy_repo.assert_called_once_with(self.repo, repo_type="studio")
        names = [name for name, _, _ in api.mock_calls]
        self.assertLess(names.index("create_repo"), names.index("list_secrets"))
        self.assertLess(names.index("list_secrets"), names.index("upload_folder"))
        self.assertLess(names.index("upload_folder"), names.index("deploy_repo"))
        self.assertEqual(result["secret_names"], sorted(SYNTHETIC))
        self.assertEqual(info["host"], "https://synthetic-owner-huawei-pc-agent-app-v2.ms.show")
        combined = json.dumps(result).encode() + b"\n".join(uploaded.values())
        for value in SYNTHETIC.values():
            if len(value) >= 8:
                self.assertNotIn(value.encode(), combined)

    def test_existing_space_is_never_overwritten(self):
        digest = self.prepare()["manifest_sha256"]
        api = self.api_mock()
        api.get_repo.side_effect = None
        with patch.object(publisher, "api", return_value=api):
            self.assert_safe_error("existing_application_not_owned_by_session", lambda: publisher.publish(digest))
        api.create_repo.assert_not_called()
        api.list_secrets.assert_not_called()
        api.upload_folder.assert_not_called()
        api.deploy_repo.assert_not_called()

    def test_paid_or_unverified_hardware_never_creates_space(self):
        digest = self.prepare()["manifest_sha256"]
        api = self.api_mock()
        for hardware in [dict(HARDWARE, resource_type="paid"), dict(HARDWARE, name="paid/a"), dict(HARDWARE, name="other-free")]:
            api.list_studio_hardware.return_value = [hardware]
            with patch.object(publisher, "api", return_value=api):
                self.assert_safe_error("free_docker_hardware_unavailable", lambda: publisher.publish(digest))
        api.get_repo.assert_not_called()
        api.create_repo.assert_not_called()

    def test_creation_platform_failures_have_safe_actionable_categories(self):
        digest = self.prepare()["manifest_sha256"]
        for message, status, category in [
            ("Aliyun real-name verification required", 403, "needs_aliyun_verification"),
            ("请先完成实名认证及绑定阿里云", 403, "needs_aliyun_verification"),
            ("studio quota exceeded", 400, "studio_quota_exceeded"),
        ]:
            api = self.api_mock()
            api.create_repo.side_effect = APIError(message, status_code=status, url="https://synthetic.invalid/private")
            with patch.object(publisher, "api", return_value=api):
                self.assert_safe_error(category, lambda: publisher.publish(digest))
            api.list_secrets.assert_not_called()

    def test_remote_host_must_be_plain_platform_https_host(self):
        api = self.api_mock()
        for host in ["http://bad.ms.show", "https://example.com", "https://x.ms.show:444", "https://x.ms.show/private", "https://x.ms.show/?token=x"]:
            api.openapi.get_studio.return_value = {"host": host}
            with patch.object(publisher, "api", return_value=api):
                self.assert_safe_error("invalid_application_host", publisher.remote_info)

    def test_logs_redact_plain_and_json_escaped_credentials(self):
        api = self.api_mock()
        synthetic = dict(SYNTHETIC, DEEPSEEK_API_KEY='synthetic-key-with-quote-"and-backslash-\\')
        api.get_repo_logs.return_value = {"text": synthetic["DEEPSEEK_API_KEY"] + " Bearer synthetic-other-token"}
        publisher.created.add(self.repo)
        with patch.object(publisher, "api", return_value=api), patch.object(publisher, "configuration", return_value=synthetic):
            result = publisher.logs("run")
        self.assertNotIn("synthetic-key-with-quote", result["logs"])
        self.assertNotIn("synthetic-other-token", result["logs"])


class LocalGuardTests(PublicationTestCase):
    def setUp(self):
        super().setUp()
        self.client = TestClient(publisher.app, base_url=publisher.ORIGIN, client=("127.0.0.1", 12345))
        self.addCleanup(self.client.close)
        self.headers = {"Origin": publisher.ORIGIN, "X-CSRF-Token": publisher.CSRF}

    def test_host_origin_csrf_are_independent_requirements(self):
        self.assertEqual(self.client.get("/api/status", headers={"Host": "evil.invalid"}).status_code, 403)
        self.assertEqual(self.client.post("/api/clear", json={}).status_code, 403)
        self.assertEqual(self.client.post("/api/clear", json={}, headers={"Origin": publisher.ORIGIN}).status_code, 403)
        self.assertEqual(self.client.post("/api/clear", json={}, headers={**self.headers, "Origin": "https://evil.invalid"}).status_code, 403)
        self.assertEqual(self.client.post("/api/clear", json={}, headers=self.headers).status_code, 200)

    def test_nonloopback_client_is_rejected(self):
        with TestClient(publisher.app, base_url=publisher.ORIGIN, client=("203.0.113.9", 1234)) as outside:
            self.assertEqual(outside.get("/api/status").status_code, 403)

    def test_fresh_process_never_uses_common_publisher_account(self):
        publisher.account = common.Account()
        with patch.dict(common.accounts, {"modelscope": common.Account("synthetic-old-token-0123456789", "old-owner")}):
            response = self.client.get("/api/status")
        self.assertFalse(response.json()["configured"])
        self.assertEqual(response.json()["username"], "")

    def test_token_not_in_status_and_account_switch_is_rejected(self):
        publisher.account = common.Account()
        token = "synthetic-new-token-0123456789"
        with patch.object(common, "verify_account", return_value="synthetic-owner"):
            response = self.client.post("/api/configure", json={"modelscope_token": token}, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(token, response.text + self.client.get("/api/status").text)
        with patch.object(common, "verify_account", return_value="other-owner"):
            response = self.client.post("/api/configure", json={"modelscope_token": "synthetic-other-token-0123456789"}, headers=self.headers)
        self.assertEqual(response.json()["error"], "different_account_requires_fresh_process")

    def test_prepare_then_changed_source_blocks_publish_through_route(self):
        response = self.client.post("/api/actions/prepare", json={}, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        (self.root / "static/app.js").write_text("changed public source")
        with patch.object(publisher, "api") as api:
            response = self.client.post("/api/actions/publish", json={"manifest_sha256": response.json()["manifest_sha256"]}, headers=self.headers)
        self.assertEqual(response.json()["error"], "application_manifest_changed_or_not_reviewed")
        api.assert_not_called()

    def test_safe_diagnostics_restart_and_login_error_routes(self):
        with patch.object(publisher, "safe_diagnostics", return_value={"check": {"category": "origin", "status_code": 403}}):
            response = self.client.post("/api/actions/diagnostics", json={}, headers=self.headers)
        self.assertEqual(response.json()["check"], {"category": "origin", "status_code": 403})
        with patch.object(publisher, "restart_application", return_value={"restart_requested": True}):
            response = self.client.post("/api/actions/restart", json={}, headers=self.headers)
        self.assertTrue(response.json()["restart_requested"])
        diagnostic = {"category": "origin", "phase": "login", "status_code": 403, "session_cookie_present": False}
        with patch.object(publisher, "application_request", side_effect=publisher.DiagnosticError(diagnostic)):
            response = self.client.post("/api/actions/request", json={"path": "/api/status"}, headers=self.headers)
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json(), {"error": "application_login_origin_failed", "diagnostics": diagnostic})


class CloudVerificationTests(PublicationTestCase):
    def test_safe_diagnostics_probes_business_auth_then_cookie_attributes(self):
        real_client = httpx.Client
        calls = []

        def handler(request):
            calls.append((request.method, request.url.path))
            self.assertEqual(request.url.host, "studio-synthetic-owner-huawei-pc-agent-app-v2.api-inference.modelscope.net")
            self.assertEqual(request.headers["Authorization"], "Bearer " + publisher.account.token)
            if request.url.path == "/healthz":
                self.assertNotIn("Cookie", request.headers)
                return httpx.Response(200, json={"status": "ok"})
            if request.url.path == "/api/login":
                self.assertNotIn("Cookie", request.headers)
                return httpx.Response(200, json={}, headers={"Set-Cookie": "huawei_studio_session=synthetic-session; Secure; HttpOnly; SameSite=None; Partitioned; Path=/"})
            if request.url.path == "/api/status":
                self.assertIn("huawei_studio_session=synthetic-session", request.headers.get("Cookie", ""))
                return httpx.Response(200, json={"mode": "deepseek", "managed_config": True, "connections": {"ima": {"name": "Synthetic Knowledge"}}, "not_forwarded": publisher.account.token})
            self.assertNotIn("Cookie", request.headers)
            return httpx.Response(401, json={"detail": "请使用工作台账号登录"})

        def factory(**options):
            return real_client(transport=httpx.MockTransport(handler), **options)

        info = {"status": "Running", "host": self.host, "api_host": self.api_host, "sdk_type": "docker", "visibility": "public", "hardware": HARDWARE["name"]}
        with patch.object(publisher, "remote_info", return_value=info), patch.object(publisher.httpx, "Client", side_effect=factory):
            result = publisher.safe_diagnostics()
        self.assertTrue(result["without_application_cookie"][0]["healthy"])
        self.assertTrue(all(item["denied_without_application_cookie"] for item in result["without_application_cookie"][1:]))
        self.assertEqual(result["cookie"], {"present": True, "secure": True, "httponly": True, "samesite": "none", "partitioned": True, "path": "/"})
        self.assertEqual(result["application"], {"mode": "deepseek", "managed_config": True, "ima_name": "Synthetic Knowledge"})
        self.assertNotIn(publisher.account.token, json.dumps(result))
        self.assertNotIn("synthetic-session", json.dumps(result))
        self.assertEqual(calls, [("GET", "/healthz"), ("GET", "/api/tasks"), ("POST", "/api/tasks"), ("POST", "/api/settings"), ("GET", "/api/files/nonexistent.png"), ("POST", "/api/login"), ("GET", "/api/status")])

    def setUp(self):
        super().setUp()
        publisher.created.add(self.repo)
        self.host = "https://synthetic-owner-huawei-pc-agent-app-v2.ms.show"
        self.api_host = "https://studio-synthetic-owner-huawei-pc-agent-app-v2.api-inference.modelscope.net"

    def invoke_with_transport(self, handler, method="GET", path="/api/status", body=None):
        real_client = httpx.Client
        clients = []

        def factory(**options):
            self.assertFalse(options["trust_env"])
            self.assertFalse(options["follow_redirects"])
            self.assertEqual(options["base_url"], self.api_host)
            result = real_client(transport=httpx.MockTransport(handler), **options)
            clients.append(result)
            return result

        with patch.object(publisher, "remote_info", return_value={"status": "Running", "host": self.host}), \
             patch.object(publisher.httpx, "Client", side_effect=factory):
            result = publisher.application_request(method, path, body)
        for client in clients:
            self.addCleanup(client.close)
        return result

    def test_api_token_is_sent_only_to_platform_api_host_with_business_cookie(self):
        calls = []

        def handler(request):
            calls.append(request.url.path)
            self.assertEqual(request.url.host, "studio-synthetic-owner-huawei-pc-agent-app-v2.api-inference.modelscope.net")
            self.assertEqual(request.headers["Authorization"], "Bearer " + publisher.account.token)
            self.assertEqual(request.headers["Origin"], self.api_host)
            if request.url.path == "/api/login":
                self.assertEqual(set(json.loads(request.content)), {"username", "password"})
                return httpx.Response(200, json={"status": "authenticated"}, headers={"Set-Cookie": "huawei_studio_session=synthetic-session; Secure; HttpOnly; Path=/"})
            self.assertIn("huawei_studio_session=synthetic-session", request.headers.get("Cookie", ""))
            return httpx.Response(200, json={"mode": "deepseek"})

        result = self.invoke_with_transport(handler)
        self.assertEqual(calls, ["/api/login", "/api/status"])
        self.assertEqual(result["body"], {"mode": "deepseek"})

    def test_restart_unauthorized_response_reauthenticates_once(self):
        calls = []
        statuses = iter([401, 200])

        def handler(request):
            calls.append(request.url.path)
            if request.url.path == "/api/login":
                return httpx.Response(200, json={}, headers={"Set-Cookie": "huawei_studio_session=synthetic-session; Secure; Path=/"})
            return httpx.Response(next(statuses), json={"status": "synthetic"})

        result = self.invoke_with_transport(handler)
        self.assertEqual(calls, ["/api/login", "/api/status", "/api/login", "/api/status"])
        self.assertEqual(result["status_code"], 200)

    def test_missing_login_cookie_fails_closed(self):
        with self.assertRaises(common.SafeError) as raised:
            self.invoke_with_transport(lambda request: httpx.Response(200, json={}))
        self.assertEqual(raised.exception.category, "application_login_cookie_failed")
        self.assertEqual(raised.exception.diagnostics["status_code"], 200)

    def test_login_failure_diagnostics_classify_without_raw_response(self):
        for status, payload, category in [
            (403, {"detail": "请求来源不匹配"}, "origin"),
            (401, {"detail": "登录名或密码不正确"}, "password"),
            (401, {"Code": 10010101007, "Message": "SDK Token platform refused"}, "platform"),
            (200, {}, "cookie"),
        ]:
            with self.assertRaises(publisher.DiagnosticError) as raised:
                self.invoke_with_transport(lambda request: httpx.Response(status, json=dict(payload, private=publisher.account.token)))
            diagnostic = raised.exception.diagnostics
            self.assertEqual(diagnostic["category"], category)
            self.assertEqual(diagnostic["status_code"], status)
            self.assertNotIn(publisher.account.token, json.dumps(diagnostic))
            self.assertNotIn("detail", diagnostic)

    def test_settings_mutation_and_encoded_path_escape_are_rejected(self):
        for method, path, body in [
            ("POST", "/api/settings", {}), ("POST", "/api/tasks/../../settings", {}),
            ("POST", "/api/tasks/%2e%2e/%2e%2e/settings", {}), ("GET", "https://example.com", None),
        ]:
            with patch.object(publisher, "remote_info") as remote:
                with self.assertRaises(common.SafeError):
                    publisher.application_request(method, path, body)
                remote.assert_not_called()

    def test_put_patch_and_export_formats_use_validated_paths(self):
        task_id = "a" * 32
        requests = []

        def handler(request):
            requests.append((request.method, request.url.path, request.url.query, request.content))
            if request.url.path == "/api/login":
                return httpx.Response(200, json={}, headers={"Set-Cookie": "huawei_studio_session=synthetic-session; Secure; Path=/"})
            return httpx.Response(200, json={"status": "saved"})

        self.invoke_with_transport(handler, "PATCH", f"/api/tasks/{task_id}/brief", {"brief": {"platform": "poster"}})
        self.invoke_with_transport(handler, "PUT", f"/api/tasks/{task_id}/draft", {"revision": 1, "draft": {}})
        self.invoke_with_transport(handler, "GET", f"/api/tasks/{task_id}/export?format=pdf")
        self.assertEqual([item[0] for item in requests], ["POST", "PATCH", "PUT", "GET"])
        self.assertEqual(requests[-1][2], b"format=pdf")
        self.assertEqual(json.loads(requests[1][3]), {"brief": {"platform": "poster"}})
        self.assertEqual(json.loads(requests[2][3]), {"revision": 1, "draft": {}})

    def test_export_query_and_method_mutations_are_rejected(self):
        task_id = "a" * 32
        for method, path in [
            ("GET", f"/api/tasks/{task_id}/export?format=secret"),
            ("GET", f"/api/tasks/{task_id}/export?format=pdf&token=anything"),
            ("POST", f"/api/tasks/{task_id}/export?format=pdf"),
            ("PATCH", "/api/settings"), ("PUT", "/api/settings"),
            ("GET", "/api/status;ignored"), ("GET", "/api/status?format=pdf"),
        ]:
            with patch.object(publisher, "remote_info") as remote:
                with self.assertRaises(common.SafeError):
                    publisher.application_request(method, path, {})
            remote.assert_not_called()

    def test_metadata_mismatch_never_sends_token_to_another_host(self):
        with patch.object(publisher, "remote_info", return_value={"status": "Running", "host": "https://another.ms.show"}), \
             patch.object(publisher.httpx, "Client") as client:
            self.assert_safe_error("application_metadata_host_mismatch", lambda: publisher.application_request("GET", "/api/status", None))
        client.assert_not_called()

    def test_cookie_token_and_login_password_are_redacted_from_results(self):
        def handler(request):
            if request.url.path == "/api/login":
                return httpx.Response(200, json={}, headers={"Set-Cookie": "huawei_studio_session=synthetic-session; Secure; Path=/"})
            return httpx.Response(200, json={"debug": [publisher.account.token, publisher.login_password, "synthetic-session"]})

        result = self.invoke_with_transport(handler)
        self.assertEqual(result["body"], {"debug": ["[redacted]", "[redacted]", "[redacted]"]})


class ResumeTests(PublicationTestCase):
    def receipt(self, url=None, requested=True):
        path = self.root / "output/submission/full-app-v2-deployment.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"result": {
            "url": url or f"https://modelscope.cn/studios/{self.repo}", "deployment_requested": requested,
        }}))
        return path

    def test_matching_receipt_restores_only_verified_fixed_application(self):
        self.receipt()
        publisher.account = common.Account()
        headers = {"Origin": publisher.ORIGIN, "X-CSRF-Token": publisher.CSRF}
        with patch.object(publisher, "RESUMED_LOGIN", True), patch.object(common, "verify_account", return_value="synthetic-owner"), \
             TestClient(publisher.app, base_url=publisher.ORIGIN, client=("127.0.0.1", 12345)) as client:
            response = client.post("/api/configure", json={"modelscope_token": "synthetic-resume-token-0123456789"}, headers=headers)
        self.assertTrue(response.json()["application_restored"])
        self.assertIn(self.repo, publisher.created)
        self.assertIn(self.repo, publisher.resumed_applications)
        digest = self.prepare()["manifest_sha256"]
        api = self.api_mock()
        api.get_repo.side_effect = None
        with patch.object(publisher, "api", return_value=api):
            result = publisher.publish(digest)
        self.assertTrue(result["deployment_requested"])
        api.create_repo.assert_not_called()
        api.upload_folder.assert_called_once()
        api.deploy_repo.assert_called_once_with(self.repo, repo_type="studio")

    def test_wrong_owner_wrong_slug_or_unrequested_receipt_cannot_restore(self):
        with patch.object(publisher, "RESUMED_LOGIN", True):
            for url, requested in [
                ("https://modelscope.cn/studios/other-owner/" + publisher.SLUG, True),
                ("https://modelscope.cn/studios/synthetic-owner/different-app", True),
                ("https://modelscope.cn/studios/synthetic-owner/huawei-pc-agent-app", True),
                (None, False), (None, "true"),
            ]:
                self.receipt(url, requested)
                self.assert_safe_error("application_resume_record_invalid", lambda: publisher.resume_record("synthetic-owner"))
        self.assertEqual(publisher.created, set())

    def test_absent_or_symlinked_receipt_cannot_restore(self):
        with patch.object(publisher, "RESUMED_LOGIN", True):
            self.assert_safe_error("application_resume_record_unavailable", lambda: publisher.resume_record("synthetic-owner"))
            path = self.receipt()
            real = path.with_suffix(".real.json")
            path.rename(real)
            path.symlink_to(real)
            self.assert_safe_error("application_resume_record_unavailable", lambda: publisher.resume_record("synthetic-owner"))

    def test_resume_login_environment_is_popped_during_import(self):
        values = {"PUBLISH_RESUME_LOGIN_USERNAME": "synthetic-resume-user", "PUBLISH_RESUME_LOGIN_PASSWORD": "synthetic-resume-password-0123456789"}
        with patch.dict(os.environ, values):
            local_spec = importlib.util.spec_from_file_location("synthetic_resumed_publisher", ROOT / "scripts/publish_app.py")
            resumed = importlib.util.module_from_spec(local_spec)
            local_spec.loader.exec_module(resumed)
            self.assertTrue(resumed.RESUMED_LOGIN)
            self.assertEqual(resumed.login_name, values["PUBLISH_RESUME_LOGIN_USERNAME"])
            self.assertEqual(resumed.login_password, values["PUBLISH_RESUME_LOGIN_PASSWORD"])
            self.assertNotIn("PUBLISH_RESUME_LOGIN_USERNAME", os.environ)
            self.assertNotIn("PUBLISH_RESUME_LOGIN_PASSWORD", os.environ)


@unittest.skipUnless(HubApi is not None, "Optional isolated ModelScope publishing SDK is not installed")
class SdkMemoryConfigurationTests(unittest.TestCase):
    def test_sdk_memory_config_creates_no_credential_directory(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(common, "ROOT", Path(temporary)), \
             patch.object(common, "load_sdk", return_value=(HubApi, HubConfig)), \
             patch.object(HubConfig, "load_token", side_effect=AssertionError("disk credentials forbidden")), \
             patch.object(HubConfig, "load_cookies", side_effect=AssertionError("disk credentials forbidden")), \
             patch.object(HubConfig, "load_git_token", side_effect=AssertionError("disk credentials forbidden")):
            api = common.modelscope_api("synthetic-memory-token-0123456789")
            self.assertFalse((Path(temporary) / "output").exists())
            self.assertFalse(api.openapi._session.trust_env)
            self.assertFalse(api.legacy._session.trust_env)

    def test_sdk_create_payload_fields_match_official_wire_names(self):
        api = common.modelscope_api("synthetic-memory-token-0123456789")
        capture = []

        def create(payload):
            capture.append(payload)
            return {"owner": "synthetic-owner", "repo_name": "synthetic-app", "sdk_type": "docker"}

        with patch.object(api.openapi, "create_studio", side_effect=create):
            api.create_repo("synthetic-owner/synthetic-app", repo_type="studio", visibility="public", sdk_type="docker",
                            hardware=HARDWARE["name"], display_name="Synthetic Application")
        self.assertEqual(capture, [{"owner": "synthetic-owner", "repo_name": "synthetic-app", "visibility": "public", "private": False,
                                   "sdk_type": "docker", "hardware": HARDWARE["name"], "display_name": "Synthetic Application"}])

    def test_sdk_secret_and_deploy_routes_use_private_secret_fields(self):
        api = common.modelscope_api("synthetic-memory-token-0123456789")
        calls = []

        def request(method, path, **options):
            calls.append((method, path, options))
            return {"secrets": [{"key": "SYNTHETIC_KEY"}]} if method == "GET" else {}

        with patch.object(api.openapi, "_request", side_effect=request):
            self.assertEqual(api.list_secrets("synthetic-owner/synthetic-app"), [{"key": "SYNTHETIC_KEY"}])
            api.add_secret("synthetic-owner/synthetic-app", "SYNTHETIC_KEY", "synthetic-private-value")
            api.update_secret("synthetic-owner/synthetic-app", "SYNTHETIC_KEY", "synthetic-updated-value")
            api.deploy_repo("synthetic-owner/synthetic-app", repo_type="studio")
            api.openapi.get_studio("synthetic-owner", "synthetic-app")
        self.assertEqual([(method, path) for method, path, _ in calls], [
            ("GET", "/studios/synthetic-owner/synthetic-app/secrets"),
            ("POST", "/studios/synthetic-owner/synthetic-app/secrets"),
            ("PUT", "/studios/synthetic-owner/synthetic-app/secrets"),
            ("POST", "/studios/synthetic-owner/synthetic-app/deploy"),
            ("GET", "/studios/synthetic-owner/synthetic-app"),
        ])
        self.assertEqual(calls[1][2]["json_body"], {"key": "SYNTHETIC_KEY", "value": "synthetic-private-value"})
        self.assertEqual(calls[2][2]["json_body"], {"key": "SYNTHETIC_KEY", "value": "synthetic-updated-value"})


if __name__ == "__main__":
    unittest.main()
