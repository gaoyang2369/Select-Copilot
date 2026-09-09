"""In-memory multi-turn chat session for one selected text context."""

from __future__ import annotations

import asyncio

from services.completion import TextCallback
from services.llm import LLMService
from services.prompts import build_chat_context_message


class ChatSession:
    """Keep one temporary conversation and send it through ``LLMService``."""

    def __init__(self, selection: str, llm_service: LLMService) -> None:
        self.messages: list[dict[str, str]] = [
            {"role": "system", "content": build_chat_context_message(selection)}
        ]
        self._llm_service = llm_service

    async def send(self, user_message: str, *, on_delta: TextCallback | None = None) -> str:
        """Append a user message, request a reply, then retain that reply in memory."""
        if not user_message.strip():
            return ""

        user_entry = {"role": "user", "content": user_message.strip()}
        self.messages.append(user_entry)
        try:
            reply = await self._llm_service.chat(self.messages, on_delta=on_delta)
        except (Exception, asyncio.CancelledError):
            self.messages.pop()
            raise

        self.messages.append({"role": "assistant", "content": reply})
        return reply
