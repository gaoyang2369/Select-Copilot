from __future__ import annotations

import asyncio
import os
import threading
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from services.chat import ChatSession
from ui.chat_window import ChatWindow


class FakeLLMService:
    def __init__(self) -> None:
        self.requests: list[list[dict[str, str]]] = []

    async def chat(self, messages: list[dict[str, str]], *, on_delta=None) -> str:
        self.requests.append([message.copy() for message in messages])
        return f"reply {len(self.requests)}"


class ChatSessionTests(unittest.TestCase):
    def test_session_keeps_context_and_multiple_turns(self) -> None:
        llm_service = FakeLLMService()
        session = ChatSession("asyncio.create_task", llm_service)

        first_reply = asyncio.run(session.send("Why use async?"))
        second_reply = asyncio.run(session.send("What is the difference?"))

        self.assertEqual(first_reply, "reply 1")
        self.assertEqual(second_reply, "reply 2")
        self.assertIn("asyncio.create_task", session.messages[0]["content"])
        self.assertEqual([message["role"] for message in session.messages], [
            "system", "user", "assistant", "user", "assistant"
        ])
        self.assertEqual(len(llm_service.requests[1]), 4)


class ChatWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_send_shows_a_reply_without_blocking_ui(self) -> None:
        window = ChatWindow("async", FakeLLMService())
        window.show()
        window._input.setPlainText("Why use async?")

        window._send_message()
        deadline = time.monotonic() + 2
        while window._worker is not None and time.monotonic() < deadline:
            self.application.processEvents()
            QTest.qWait(10)
        self.application.processEvents()

        self.assertIsNone(window._worker)
        self.assertIn("You:\nWhy use async?", window._messages.toPlainText())
        self.assertIn("AI:\nreply 1", window._messages.toPlainText())
        window.close()

    def test_close_cancels_pending_chat_before_deleting_window(self) -> None:
        started = threading.Event()
        cleaned = threading.Event()
        class SlowLLM:
            async def chat(self, messages, *, on_delta=None):
                started.set()
                try:
                    await asyncio.sleep(60)
                    return "late reply"
                finally:
                    cleaned.set()
        window = ChatWindow("context", SlowLLM())
        window.show()
        window._input.setPlainText("question")
        window._send_message()
        worker = window._worker
        try:
            self.assertTrue(started.wait(2))
        finally:
            window.close()
        self.assertFalse(worker.isRunning())
        self.assertTrue(cleaned.is_set())

    def test_messages_are_literal_text(self) -> None:
        window = ChatWindow("context", FakeLLMService())
        window._append_message("AI", "<b>literal markup</b>")
        self.assertIn("<b>literal markup</b>", window._messages.toPlainText())
        window.close()
