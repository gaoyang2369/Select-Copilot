"""Qt integration tests with a gated, local HTTP response (no external API)."""
from __future__ import annotations

import asyncio
import os
import threading
import time
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import httpx
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from services.llm import LLMService
from services.translator import Translator
from tests.test_completion import event
from ui.toolbar import FloatingToolbar
from ui.chat_window import ChatWindow


class StreamingUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.release = threading.Event()
        self.closed = threading.Event()
        self.window = None
        release, closed = self.release, self.closed
        class GatedStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield event('first🙂').encode('utf-8')
                while not release.is_set():
                    await asyncio.sleep(0.01)
                yield (event(' second') + event(finish_reason='stop')).encode()
            async def aclose(self):
                closed.set()
        def handler(request):
            return httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=GatedStream())
        self.options = dict(base_url='https://example.test/v1', api_key='test', model='test', client_factory=lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs))

    def tearDown(self):
        self.release.set()
        if self.window is not None:
            self.window.shutdown()
            self.window.close()
        self.application.processEvents()

    def wait_for(self, condition):
        deadline = time.monotonic() + 2
        while not condition() and time.monotonic() < deadline:
            self.application.processEvents()
            QTest.qWait(10)
        self.assertTrue(condition())

    def test_toolbar_displays_before_completion_and_ignores_old_selection(self):
        self.window = toolbar = FloatingToolbar(translator=Translator(**self.options))
        toolbar.show_for_selection('water')
        toolbar._start_translation()
        self.wait_for(lambda: toolbar._translation_popup._text.toPlainText() == 'first🙂')
        self.assertTrue(toolbar._translation_worker.isRunning())
        # Even reselecting identical text must invalidate the previous request.
        toolbar.show_for_selection('water')
        self.release.set()
        self.wait_for(lambda: toolbar._translation_worker is None)
        self.assertFalse(toolbar._translation_popup.isVisible())

    def test_explanation_is_not_overwritten_by_earlier_translation(self):
        class QuickLLM:
            async def ask(self, prompt, *, on_delta=None):
                on_delta('explanation')
                return 'explanation'
        self.window = toolbar = FloatingToolbar(translator=Translator(**self.options), llm_service=QuickLLM())
        toolbar.show_for_selection('water')
        toolbar._start_translation()
        self.wait_for(lambda: toolbar._translation_popup._text.toPlainText() == 'first🙂')
        toolbar._start_explanation()
        self.wait_for(lambda: toolbar._llm_worker is None)
        self.release.set()
        self.wait_for(lambda: toolbar._translation_worker is None)
        self.assertEqual(toolbar._translation_popup._text.toPlainText(), 'explanation')

    def test_popup_escape_does_not_reopen_on_next_chunk(self):
        self.window = toolbar = FloatingToolbar(translator=Translator(**self.options))
        toolbar.show_for_selection('water')
        toolbar._start_translation()
        self.wait_for(lambda: toolbar._translation_popup._text.toPlainText() == 'first🙂')
        toolbar._translation_popup.hide()
        self.release.set()
        self.wait_for(lambda: toolbar._translation_worker is None)
        self.assertFalse(toolbar._translation_popup.isVisible())

    def test_chat_streams_without_duplicate_answer_and_preserves_history(self):
        self.window = window = ChatWindow('context', LLMService(**self.options))
        window.show()
        window._input.setPlainText('question')
        window._send_message()
        self.wait_for(lambda: 'first🙂' in window._messages.toPlainText())
        self.assertTrue(window._worker.isRunning())
        self.assertFalse(window._send_button.isEnabled())
        self.release.set()
        self.wait_for(lambda: window._worker is None)
        self.assertEqual(window._messages.toPlainText().count('first🙂 second'), 1)
        window._input.setPlainText('another question')
        window._send_message()
        self.wait_for(lambda: window._worker is None)
        self.assertEqual(window._messages.toPlainText().count('first🙂 second'), 2)
        self.assertEqual(len(window._session.messages), 5)

    def test_closing_streaming_chat_cancels_http_and_rolls_back_history(self):
        self.window = window = ChatWindow('context', LLMService(**self.options))
        window.show()
        window._input.setPlainText('question')
        window._send_message()
        self.wait_for(lambda: 'first🙂' in window._messages.toPlainText())
        session, worker = window._session, window._worker
        window.close()
        self.assertFalse(worker.isRunning())
        self.assertTrue(self.closed.is_set())
        self.assertEqual(len(session.messages), 1)
        self.window = None
