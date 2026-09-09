from __future__ import annotations

import asyncio
import json
import unittest

import httpx

from services.translator import TranslationError, Translator


class TranslatorTests(unittest.TestCase):
    def test_translate_sends_openai_compatible_request(self) -> None:
        captured_request = None

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal captured_request
            captured_request = request
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "水"}}]},
            )

        transport = httpx.MockTransport(handler)
        translator = Translator(
            base_url="https://example.test/v1",
            api_key="test-key",
            model="test-model",
            client_factory=lambda **kwargs: httpx.AsyncClient(transport=transport, **kwargs),
        )

        result = asyncio.run(translator.translate("water"))

        self.assertEqual(result, "水")
        self.assertEqual(captured_request.url.path, "/v1/chat/completions")
        self.assertEqual(captured_request.headers["authorization"], "Bearer test-key")
        self.assertEqual(json.loads(captured_request.content)["model"], "test-model")

    def test_missing_configuration_has_clear_error(self) -> None:
        translator = Translator(base_url="", api_key="", model="")

        with self.assertRaisesRegex(TranslationError, "Missing .env configuration"):
            asyncio.run(translator.translate("water"))

    def test_timeout_error_includes_its_type(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("", request=request)

        service = Translator(
            base_url="https://example.test/v1",
            api_key="test-key",
            model="test-model",
            client_factory=lambda **kwargs: httpx.AsyncClient(
                transport=httpx.MockTransport(handler), **kwargs
            ),
        )

        with self.assertRaisesRegex(TranslationError, "ReadTimeout"):
            asyncio.run(service.translate("water"))
