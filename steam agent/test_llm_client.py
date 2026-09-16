"""离线测试：隔离真实环境和 .env，所有 API 响应均为模拟数据。"""

import os
from pathlib import Path
import tempfile
import traceback
import unittest
from unittest.mock import Mock, patch

import requests

import llm_client


FAKE_KEY = "test-only-not-a-real-api-key"


class LLMClientTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"SILICONFLOW_API_KEY": FAKE_KEY}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.loader = patch("llm_client.load_dotenv")
        self.load = self.loader.start()
        self.addCleanup(self.loader.stop)
        self.network = patch("llm_client.requests.post")
        self.post = self.network.start()
        self.addCleanup(self.network.stop)
        self.post.return_value = Mock(status_code=200)
        self.post.return_value.json.return_value = {
            "choices": [{"message": {"content": " 模拟回复 "}}]
        }

    def test_invalid_prompt(self):
        for prompt in ("", " \n", None, 123):
            with self.subTest(prompt=prompt):
                with self.assertRaisesRegex(ValueError, "prompt"):
                    llm_client.ask_llm(prompt)
        self.load.assert_not_called()
        self.post.assert_not_called()

    def test_missing_or_placeholder_key(self):
        for key in (None, "", " ", "your_api_key_here"):
            if key is None:
                os.environ.pop("SILICONFLOW_API_KEY", None)
            else:
                os.environ["SILICONFLOW_API_KEY"] = key
            with self.assertRaisesRegex(llm_client.LLMError, "SILICONFLOW_API_KEY"):
                llm_client.ask_llm("hello")
        self.post.assert_not_called()

    def test_success_and_request(self):
        self.assertEqual(llm_client.ask_llm("hello"), "模拟回复")
        self.post.assert_called_once_with(
            "https://api.siliconflow.cn/v1/chat/completions",
            headers={"Authorization": f"Bearer {FAKE_KEY}"},
            json={"model": "Qwen/Qwen3.5-4B",
                  "messages": [{"role": "user", "content": "hello"}], "stream": False},
            timeout=(10, 120), allow_redirects=False,
        )
        self.load.assert_called_once_with(llm_client.ENV_PATH, override=False, interpolate=False)

    def test_network_errors_do_not_leak_key(self):
        for error, message in [(requests.Timeout(FAKE_KEY), "超时"),
                               (requests.ConnectionError(FAKE_KEY), "网络请求失败")]:
            self.post.side_effect = error
            try:
                llm_client.ask_llm("hello")
            except llm_client.LLMError as exc:
                self.assertIn(message, str(exc))
                self.assertNotIn(FAKE_KEY, traceback.format_exc())
            else:
                self.fail("应当抛出 LLMError")

    def test_http_errors_do_not_echo_response(self):
        for status in (302, 400, 401, 403, 404, 429, 500, 503):
            with self.subTest(status=status):
                self.post.return_value.status_code = status
                self.post.return_value.text = FAKE_KEY
                with self.assertRaisesRegex(llm_client.LLMError, f"HTTP {status}") as context:
                    llm_client.ask_llm("hello")
                self.assertNotIn(FAKE_KEY, str(context.exception))
        self.post.return_value.json.assert_not_called()

    def test_malformed_and_empty_responses(self):
        cases = [None, {}, {"choices": []}, {"choices": [None]}]
        cases += [{"choices": [{"message": {"content": value}}]}
                  for value in (None, "", "  ", 123, [])]
        for data in cases:
            with self.subTest(data=data):
                self.post.return_value.json.return_value = data
                with self.assertRaises(llm_client.LLMError):
                    llm_client.ask_llm("hello")

    def test_invalid_json(self):
        self.post.return_value.json.side_effect = ValueError(FAKE_KEY)
        with self.assertRaisesRegex(llm_client.LLMError, "回复格式异常") as context:
            llm_client.ask_llm("hello")
        self.assertNotIn(FAKE_KEY, str(context.exception))

    def test_echoed_key_is_redacted(self):
        self.post.return_value.json.return_value = {
            "choices": [{"message": {"content": f"response {FAKE_KEY}"}}]
        }
        self.assertEqual(llm_client.ask_llm("hello"), "response [REDACTED]")

    def test_dotenv_loading_and_environment_precedence(self):
        # 只创建、读取临时测试文件，不接触项目真实 .env。
        self.loader.stop()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("SILICONFLOW_API_KEY=test-only-file-key\n", encoding="utf-8")
            with patch("llm_client.ENV_PATH", path):
                llm_client.ask_llm("hello")
                self.assertEqual(self.post.call_args.kwargs["headers"]["Authorization"],
                                 f"Bearer {FAKE_KEY}")
                del os.environ["SILICONFLOW_API_KEY"]
                llm_client.ask_llm("hello")
                self.assertEqual(self.post.call_args.kwargs["headers"]["Authorization"],
                                 "Bearer test-only-file-key")


if __name__ == "__main__":
    unittest.main()
