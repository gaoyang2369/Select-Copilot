"""OpenAI-compatible service for one-shot LLM requests."""

from __future__ import annotations

import os
from collections.abc import Callable

import httpx
from dotenv import load_dotenv

from services.completion import CompletionError, TextCallback, complete


class LLMError(RuntimeError):
    """Raised when an LLM request cannot produce usable text."""


class LLMService:
    """Send a single prompt to an OpenAI-compatible Chat Completions API."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        client_factory: Callable[..., httpx.AsyncClient] = httpx.AsyncClient,
        *, thinking: str | None = None, stream: bool | None = None,
    ) -> None:
        load_dotenv()
        self._base_url = os.getenv("BASE_URL", "") if base_url is None else base_url
        self._api_key = os.getenv("API_KEY", "") if api_key is None else api_key
        self._model = os.getenv("MODEL", "") if model is None else model
        self._client_factory = client_factory
        self._thinking = os.getenv("DEEPSEEK_THINKING", "disabled").lower() if thinking is None else thinking
        self._stream = (os.getenv("LLM_STREAM", "true").lower() != "false") if stream is None else stream

    async def ask(self, prompt: str, *, on_delta: TextCallback | None = None) -> str:
        """Return the plain-text completion for a non-empty prompt."""
        if not prompt.strip():
            return ""
        return await self.chat([{"role": "user", "content": prompt}], on_delta=on_delta)

    async def chat(
        self, messages: list[dict[str, str]], *, on_delta: TextCallback | None = None,
    ) -> str:
        """Return a complete reply, optionally delivering text as it arrives."""
        if not messages:
            return ""
        try:
            return await complete(
                base_url=self._base_url, api_key=self._api_key, model=self._model,
                messages=messages, client_factory=self._client_factory,
                temperature=0.3, thinking=self._thinking, stream=self._stream,
                on_delta=on_delta, label="llm",
            )
        except CompletionError as error:
            raise LLMError(str(error)) from error
