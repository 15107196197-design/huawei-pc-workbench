"""Provider protocol regressions. All HTTP and polling delays are mocked."""

import httpx
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from huawei_agent import providers, settings


DEEPSEEK_KEY = "synthetic-deepseek-key-never-real"
DASHSCOPE_KEY = "synthetic-qwen-key-never-real"
TAVILY_KEY = "synthetic-tavily-key-never-real"


def response(status=200, data=None):
    return httpx.Response(status, json={} if data is None else data)


def completion(content):
    return response(data={"choices": [{"message": {"content": content}}]})


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.config = dict(settings.DEFAULTS, deepseek_api_key=DEEPSEEK_KEY,
                           dashscope_api_key=DASHSCOPE_KEY, tavily_api_key="")
        patcher = patch.object(providers, "load_settings", return_value=self.config)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = MagicMock()
        self.client.post = AsyncMock()
        self.client.get = AsyncMock()
        manager = MagicMock()
        manager.__aenter__ = AsyncMock(return_value=self.client)
        manager.__aexit__ = AsyncMock(return_value=False)
        patcher = patch.object(providers.httpx, "AsyncClient", return_value=manager)
        self.client_factory = patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.object(providers.asyncio, "sleep", new_callable=AsyncMock)
        self.sleep = patcher.start()
        self.addCleanup(patcher.stop)

    async def test_deepseek_json_protocol_and_key_remain_in_request_header(self):
        self.client.post.return_value = completion('{"title":"合成测试"}')
        result = await providers.json_chat("测试系统提示", {"brief": "合成资料"})
        self.assertEqual(result, {"title": "合成测试"})
        args, kwargs = self.client.post.await_args
        self.assertEqual(args[0], "https://api.deepseek.com/chat/completions")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer " + DEEPSEEK_KEY)
        self.assertEqual(kwargs["json"]["response_format"], {"type": "json_object"})
        self.assertEqual(kwargs["json"]["thinking"], {"type": "disabled"})
        self.assertNotIn(DEEPSEEK_KEY, str(result))

    async def test_invalid_json_retries_at_most_twice_and_can_recover(self):
        self.client.post.side_effect = [completion("invalid-json"), completion('{"ok":true}')]
        self.assertEqual(await providers.json_chat("测试", {}), {"ok": True})
        self.assertEqual(self.client.post.await_count, 2)

    async def test_two_invalid_json_responses_fail_without_partial_output(self):
        self.client.post.return_value = completion("[not valid")
        with self.assertRaises(providers.ProviderError) as caught:
            await providers.json_chat("测试", {})
        self.assertEqual(self.client.post.await_count, 2)
        self.assertIn("两次", str(caught.exception))

    async def test_json_array_and_null_content_are_not_accepted_as_success(self):
        for content in ["[]", None, ["not-a-string"]]:
            with self.subTest(content=content):
                self.client.post.reset_mock()
                self.client.post.return_value = completion(content)
                with self.assertRaises(providers.ProviderError):
                    await providers.json_chat("测试", {})
                self.assertEqual(self.client.post.await_count, 2)

    async def test_http_error_does_not_retry_or_expose_key_or_upstream_body(self):
        self.client.post.return_value = response(401, {"error": "secret echo " + DEEPSEEK_KEY})
        with self.assertRaises(providers.ProviderError) as caught:
            await providers.json_chat("测试", {})
        self.assertEqual(self.client.post.await_count, 1)
        self.assertIn("401", str(caught.exception))
        self.assertNotIn(DEEPSEEK_KEY, str(caught.exception))
        self.assertNotIn("secret echo", str(caught.exception))

    async def test_network_error_has_safe_message_without_provider_credentials(self):
        self.client.post.side_effect = httpx.ConnectError("transport included " + DEEPSEEK_KEY)
        with self.assertRaises(providers.ProviderError) as caught:
            await providers.json_chat("测试", {})
        self.assertNotIn(DEEPSEEK_KEY, str(caught.exception))
        self.assertEqual(self.client.post.await_count, 1)

    async def test_vision_request_uses_multimodal_format_and_distinct_provider(self):
        self.client.post.return_value = completion('{"passed":true}')
        await providers.json_chat("检查", {"draft": "合成文案"}, vision_images=["data:image/png;base64,TEST_ONLY"])
        args, kwargs = self.client.post.await_args
        self.assertEqual(args[0], "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer " + DASHSCOPE_KEY)
        self.assertFalse(kwargs["json"]["enable_thinking"])
        self.assertEqual(kwargs["json"]["messages"][1]["content"][1]["type"], "image_url")

    async def test_qwen_async_endpoint_header_and_choices_image_output(self):
        self.client.post.return_value = response(data={"output": {"task_id": "synthetic-task"}})
        self.client.get.side_effect = [response(data={"output": {"task_status": "RUNNING"}}),
                                       response(data={"output": {"task_status": "SUCCEEDED", "choices": [
                                           {"message": {"content": [{"text": "test"}, {"image": "https://example.invalid/background.png"}]}}]}})]
        self.assertEqual(await providers.generate_background("浅灰蓝背景"), "https://example.invalid/background.png")
        args, kwargs = self.client.post.await_args
        self.assertEqual(args[0], "https://dashscope.aliyuncs.com/api/v1/services/aigc/image-generation/generation")
        self.assertEqual(kwargs["headers"]["X-DashScope-Async"], "enable")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer " + DASHSCOPE_KEY)
        self.assertTrue(kwargs["json"]["parameters"]["watermark"])
        self.assertEqual(self.client.get.await_count, 2)
        self.assertEqual(self.client.get.await_args.args[0], "https://dashscope.aliyuncs.com/api/v1/tasks/synthetic-task")

    async def test_qwen_legacy_results_url_is_supported(self):
        self.client.post.return_value = response(data={"output": {"task_id": "synthetic-task"}})
        self.client.get.return_value = response(data={"output": {"task_status": "SUCCEEDED", "results": [{"url": "https://example.invalid/legacy.png"}]}})
        self.assertEqual(await providers.generate_background("测试"), "https://example.invalid/legacy.png")

    async def test_qwen_failed_canceled_unknown_never_return_success_url(self):
        for status in ["FAILED", "CANCELED", "UNKNOWN"]:
            with self.subTest(status=status):
                self.client.get.reset_mock()
                self.client.post.return_value = response(data={"output": {"task_id": "synthetic-task"}})
                self.client.get.return_value = response(data={"output": {"task_status": status, "results": [{"url": "https://example.invalid/not-success.png"}]}})
                with self.assertRaises(providers.ProviderError):
                    await providers.generate_background("测试")
                self.assertEqual(self.client.get.await_count, 1)

    async def test_qwen_polling_timeout_is_bounded_and_not_reported_as_success(self):
        self.client.post.return_value = response(data={"output": {"task_id": "synthetic-task"}})
        self.client.get.return_value = response(data={"output": {"task_status": "RUNNING"}})
        with self.assertRaises(providers.ProviderError) as caught:
            await providers.generate_background("测试")
        self.assertIn("超时", str(caught.exception))
        self.assertEqual(self.client.get.await_count, 90)
        self.assertEqual(self.sleep.await_count, 90)

    async def test_qwen_success_without_image_is_an_error(self):
        self.client.post.return_value = response(data={"output": {"task_id": "synthetic-task"}})
        self.client.get.return_value = response(data={"output": {"task_status": "SUCCEEDED", "choices": []}})
        with self.assertRaises(providers.ProviderError) as caught:
            await providers.generate_background("测试")
        self.assertIn("未返回图片", str(caught.exception))

    async def test_qwen_missing_task_id_does_not_poll(self):
        self.client.post.return_value = response(data={"output": {}})
        with self.assertRaises(providers.ProviderError):
            await providers.generate_background("测试")
        self.client.get.assert_not_awaited()

    async def test_qwen_http_error_while_polling_cannot_be_false_success(self):
        self.client.post.return_value = response(data={"output": {"task_id": "synthetic-task"}})
        self.client.get.return_value = response(403, {"output": {"task_status": "SUCCEEDED", "results": [{"url": "https://example.invalid/not-success.png"}]}, "error": DASHSCOPE_KEY})
        with self.assertRaises(providers.ProviderError) as caught:
            await providers.generate_background("测试")
        self.assertNotIn(DASHSCOPE_KEY, str(caught.exception))

    async def test_deepseek_native_search_uses_shared_key_and_limits_query(self):
        self.client.post.return_value = response(data={"results": [{"title": "合成报价线索", "url": "https://example.invalid/offer", "content": "说明" * 6000}]})
        records, warnings = await providers.search_prices({"region": "杭州", "product": "超长型号" * 100, "channels": ["华为商城", "淘宝"]})
        args, kwargs = self.client.post.await_args
        self.assertEqual(args[0], "https://api.deepseek.com/v1/tools/search")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer " + DEEPSEEK_KEY)
        self.assertLessEqual(len(kwargs["json"]["query"]), 128)
        self.assertTrue(kwargs["json"]["need_content"])
        self.assertEqual(records[0]["kind"], "price_discovery")
        self.assertIs(records[0]["verified"], False)
        self.assertEqual(len(records[0]["excerpt"]), 10000)
        self.assertNotIn("checkout_amount", records[0])
        self.assertNotIn("base_price", records[0])
        self.assertTrue(warnings)

    async def test_deepseek_search_base_with_v1_does_not_duplicate_path(self):
        self.config["deepseek_base_url"] = "https://api.deepseek.com/v1/"
        self.client.post.return_value = response(data={"results": []})
        await providers.search_prices({"channels": []})
        self.assertEqual(self.client.post.await_args.args[0], "https://api.deepseek.com/v1/tools/search")

    async def test_tavily_is_used_when_native_search_key_is_not_configured(self):
        self.config.update(deepseek_api_key="", tavily_api_key=TAVILY_KEY)
        self.client.post.return_value = response(data={"results": [{"title": "合成备用线索", "url": "https://example.invalid/offer", "raw_content": "未经核实的报价描述"}]})
        records, warnings = await providers.search_prices({"region": "杭州", "channels": ["华为商城"]})
        args, kwargs = self.client.post.await_args
        self.assertEqual(args[0], "https://api.tavily.com/search")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer " + TAVILY_KEY)
        self.assertFalse(kwargs["json"]["include_answer"])
        self.assertIs(records[0]["verified"], False)
        self.assertEqual(records[0]["kind"], "price_discovery")
        self.assertTrue(warnings)

    async def test_search_without_keys_makes_no_http_request(self):
        self.config.update(deepseek_api_key="", tavily_api_key="")
        records, warnings = await providers.search_prices({})
        self.assertEqual(records, [])
        self.assertTrue(warnings)
        self.client_factory.assert_not_called()

    async def test_search_http_error_does_not_leak_secret_or_synthesize_results(self):
        self.client.post.return_value = response(429, {"error": DEEPSEEK_KEY})
        with self.assertRaises(providers.ProviderError) as caught:
            await providers.search_prices({})
        self.assertNotIn(DEEPSEEK_KEY, str(caught.exception))
        self.assertEqual(self.client.post.await_count, 1)


if __name__ == "__main__":
    unittest.main()
