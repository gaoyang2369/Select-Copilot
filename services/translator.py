"""OpenAI-compatible translation service."""

from __future__ import annotations

import logging
import os
import threading
from collections import OrderedDict
from collections.abc import Callable

import httpx
from dotenv import load_dotenv

from config.paths import application_dir
from services.completion import CompletionError, TextCallback, complete

logger = logging.getLogger(__name__)


class TranslationError(RuntimeError):
    """Raised when a translation request cannot produce usable text."""


class Translator:
    """Translate text through an OpenAI-compatible Chat Completions endpoint."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        client_factory: Callable[..., httpx.AsyncClient] = httpx.AsyncClient,
        *, thinking: str | None = None, stream: bool | None = None,
    ) -> None:
        load_dotenv(application_dir() / ".env")
        self._base_url = os.getenv("BASE_URL", "") if base_url is None else base_url
        self._api_key = os.getenv("API_KEY", "") if api_key is None else api_key
        self._model = os.getenv("MODEL", "") if model is None else model
        self._client_factory = client_factory
        self._thinking = os.getenv("DEEPSEEK_TRANSLATION_THINKING", "disabled").lower() if thinking is None else thinking
        self._stream = (os.getenv("LLM_STREAM", "true").lower() != "false") if stream is None else stream
        self._cache: OrderedDict[tuple[str, str], str] = OrderedDict()
        self._cache_lock = threading.Lock()

    async def translate(
        self, text: str, target_language: str = "Simplified Chinese", *,
        on_delta: TextCallback | None = None,
    ) -> str:
        """Stream a translation; cache only successful, complete results in memory."""
        if not text.strip():
            return ""
        key = (text, target_language)
        with self._cache_lock:
            cached = self._cache.get(key)
            if cached is not None:
                self._cache.move_to_end(key)
        if cached is not None:
            logger.info("Translation cache hit")
            if on_delta is not None:
                on_delta(cached)
            return cached
        try:
            result = await complete(
                base_url=self._base_url, api_key=self._api_key, model=self._model,
                messages=[
                    {"role": "system", "content": self._build_instruction(text, target_language)},
                    {"role": "user", "content": text},
                ],
                client_factory=self._client_factory, temperature=0.2,
                thinking=self._thinking, stream=self._stream,
                on_delta=on_delta, label="translation",
            )
        except CompletionError as error:
            raise TranslationError(str(error)) from error
        # Bound both entry count and individual size; never persist selected text.
        if len(text) + len(target_language) + len(result) <= 16384:
            with self._cache_lock:
                self._cache[key] = result
                self._cache.move_to_end(key)
                while len(self._cache) > 128:
                    self._cache.popitem(last=False)
        return result

    @staticmethod
    def _build_instruction(text: str, target_language: str) -> str:
        if len(text.split()) == 1:
            return (
                f"Translate the user's single word into {target_language}. "
                "Include its part of speech and common meanings concisely. "
                "Use plain text without a title."
            )
        return (
            f"Translate the user's text naturally and accurately into {target_language}. "
            "Do not add a title or lengthy explanation. Use plain text."
        )
