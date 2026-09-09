from __future__ import annotations

import asyncio
import json
import unittest

import httpx

from services.llm import LLMError, LLMService
from services.prompts import build_quick_ask_prompt


class LLMServiceTests(unittest.TestCase):
    def test_ask_sends_openai_compatible_request(self) -> None:
        captured_request = None

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal captured_request
            captured_request = request
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "解释结果"}}]},
            )

        transport = httpx.MockTransport(handler)
        service = LLMService(
            base_url="https://example.test/v1",
            api_key="test-key",
            model="test-model",
            client_factory=lambda **kwargs: httpx.AsyncClient(transport=transport, **kwargs),
        )
        prompt = build_quick_ask_prompt("Wasserstein distance")

        result = asyncio.run(service.ask(prompt))

        self.assertEqual(result, "解释结果")
        self.assertEqual(captured_request.url.path, "/v1/chat/completions")
        self.assertEqual(captured_request.headers["authorization"], "Bearer test-key")
        self.assertEqual(json.loads(captured_request.content)["messages"][0]["content"], prompt)

    def test_missing_configuration_has_clear_error(self) -> None:
        service = LLMService(base_url="", api_key="", model="")

        with self.assertRaisesRegex(LLMError, "Missing .env configuration"):
            asyncio.run(service.ask("explain this"))

    def test_quick_ask_prompt_contains_the_selected_text(self) -> None:
        prompt = build_quick_ask_prompt("Wasserstein distance")

        self.assertIn("计算机专业硕士", prompt)
        self.assertIn("Wasserstein distance", prompt)

    def test_chat_sends_entire_message_history(self) -> None:
        captured_request = None

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal captured_request
            captured_request = request
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "reply"}}]},
            )

        transport = httpx.MockTransport(handler)
        service = LLMService(
            base_url="https://example.test/v1",
            api_key="test-key",
            model="test-model",
            client_factory=lambda **kwargs: httpx.AsyncClient(transport=transport, **kwargs),
        )
        messages = [
            {"role": "system", "content": "context"},
            {"role": "user", "content": "question"},
        ]

        self.assertEqual(asyncio.run(service.chat(messages)), "reply")
        self.assertEqual(json.loads(captured_request.content)["messages"], messages)
