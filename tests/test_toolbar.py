from __future__ import annotations

import os
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from ui.toolbar import FloatingToolbar


class FakeTranslator:
    async def translate(self, text: str, *, on_delta=None) -> str:
        return f"translated: {text}"


class FakeLLMService:
    async def ask(self, prompt: str, *, on_delta=None) -> str:
        return "explanation result"


class FakeTTSService:
    def __init__(self) -> None:
        self.spoken_texts: list[str] = []

    def speak(self, text: str) -> None:
        self.spoken_texts.append(text)


class BlockingTTSService(FakeTTSService):
    def __init__(self) -> None:
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()

    def speak(self, text: str) -> None:
        super().speak(text)
        self.started.set()
        self.release.wait(timeout=2)


class FloatingToolbarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.toolbar = FloatingToolbar()
        self.toolbar.adjustSize()

    def tearDown(self) -> None:
        self.toolbar.shutdown()
        self.toolbar.close()

    def test_show_for_selection_keeps_selected_text(self) -> None:
        self.toolbar.show_for_selection("Wasserstein distance")

        self.assertTrue(self.toolbar.isVisible())
        self.assertEqual(self.toolbar.selected_text, "Wasserstein distance")

    def test_position_stays_inside_screen_at_bottom_right(self) -> None:
        screen = self.application.primaryScreen().availableGeometry()
        position = self.toolbar._position_near(screen.bottomRight())

        self.assertGreaterEqual(position.x(), screen.left())
        self.assertGreaterEqual(position.y(), screen.top())
        self.assertLessEqual(position.x() + self.toolbar.width() - 1, screen.right())
        self.assertLessEqual(position.y() + self.toolbar.height() - 1, screen.bottom())

    def test_empty_text_hides_toolbar(self) -> None:
        self.toolbar.show_for_selection("text")
        self.toolbar.show_for_selection("")

        self.assertFalse(self.toolbar.isVisible())

    def test_missing_selection_hides_toolbar_and_clears_stale_text(self) -> None:
        self.toolbar.show_for_selection("old selection")

        self.toolbar.hide_for_missing_selection()

        self.assertFalse(self.toolbar.isVisible())
        self.assertEqual(self.toolbar.selected_text, "")

    def test_translation_result_is_shown_after_worker_finishes(self) -> None:
        self.toolbar.close()
        self.toolbar = FloatingToolbar(translator=FakeTranslator())
        self.toolbar.show_for_selection("water")

        self.toolbar._start_translation()
        deadline = time.monotonic() + 2
        while self.toolbar._translation_worker is not None and time.monotonic() < deadline:
            self.application.processEvents()
            QTest.qWait(10)
        self.application.processEvents()

        self.assertIsNone(self.toolbar._translation_worker)
        self.assertTrue(self.toolbar._translation_popup.isVisible())
        self.assertEqual(self.toolbar._translation_popup._text.toPlainText(), "translated: water")

    def test_tts_plays_selected_text_in_background(self) -> None:
        self.toolbar.close()
        tts_service = FakeTTSService()
        self.toolbar = FloatingToolbar(tts_service=tts_service)
        self.toolbar.show_for_selection("water")

        self.toolbar._start_tts()
        deadline = time.monotonic() + 2
        while self.toolbar._tts_worker is not None and time.monotonic() < deadline:
            self.application.processEvents()
            QTest.qWait(10)
        self.application.processEvents()

        self.assertEqual(tts_service.spoken_texts, ["water"])
        self.assertIsNone(self.toolbar._tts_worker)
        self.assertTrue(self.toolbar._tts_button.isEnabled())

    def test_tts_ignores_repeated_clicks_while_playing(self) -> None:
        self.toolbar.close()
        tts_service = BlockingTTSService()
        self.toolbar = FloatingToolbar(tts_service=tts_service)
        self.toolbar.show_for_selection("water")

        self.toolbar._start_tts()
        self.assertTrue(tts_service.started.wait(timeout=1))
        self.toolbar._start_tts()
        self.assertEqual(tts_service.spoken_texts, ["water"])

        tts_service.release.set()
        deadline = time.monotonic() + 2
        while self.toolbar._tts_worker is not None and time.monotonic() < deadline:
            self.application.processEvents()
            QTest.qWait(10)
        self.application.processEvents()
        self.assertIsNone(self.toolbar._tts_worker)

    def test_explanation_result_is_shown_after_worker_finishes(self) -> None:
        self.toolbar.close()
        self.toolbar = FloatingToolbar(llm_service=FakeLLMService())
        self.toolbar.show_for_selection("Wasserstein distance")

        self.toolbar._start_explanation()
        deadline = time.monotonic() + 2
        while self.toolbar._llm_worker is not None and time.monotonic() < deadline:
            self.application.processEvents()
            QTest.qWait(10)
        self.application.processEvents()

        self.assertIsNone(self.toolbar._llm_worker)
        self.assertTrue(self.toolbar._translation_popup.isVisible())
        self.assertEqual(self.toolbar._translation_popup._text.toPlainText(), "explanation result")

    def test_chat_opens_window_with_current_selection(self) -> None:
        self.toolbar.show_for_selection("Wasserstein distance")

        self.toolbar._open_chat()

        self.assertEqual(len(self.toolbar._chat_windows), 1)
        window = self.toolbar._chat_windows[0]
        self.assertTrue(window.isVisible())
        self.assertIn("Wasserstein distance", window._session.messages[0]["content"])
        window.close()

    def test_late_result_does_not_reopen_dismissed_popup(self) -> None:
        self.toolbar.show_for_selection("water")
        self.toolbar._translation_source = "water"
        self.toolbar._explanation_source = "water"
        self.toolbar.hide()
        self.toolbar._show_translation("late translation")
        self.toolbar._show_explanation("late explanation")
        self.assertFalse(self.toolbar._translation_popup.isVisible())

    def test_empty_selection_discards_previous_text(self) -> None:
        self.toolbar.show_for_selection("old selection")
        self.toolbar.show_for_selection("")
        self.assertEqual(self.toolbar.selected_text, "")

    def test_escape_dismisses_without_toolbar_focus(self) -> None:
        self.toolbar.show_for_selection("water")
        self.toolbar._key_state = lambda key: 0x8000 if key == 0x1B else 0
        self.toolbar._check_dismissal()
        self.assertFalse(self.toolbar.isVisible())
        self.assertFalse(self.toolbar._dismiss_timer.isActive())

    def test_outside_click_dismisses_without_toolbar_focus(self) -> None:
        self.toolbar.show_for_selection("water")
        self.toolbar._left_button_down = False
        self.toolbar._key_state = lambda key: 0x8000 if key == 0x01 else 0
        position = self.toolbar.frameGeometry().topLeft() - QPoint(10, 10)
        with patch("ui.toolbar.QCursor.pos", return_value=position):
            self.toolbar._check_dismissal()
        self.assertFalse(self.toolbar.isVisible())

    def test_click_inside_result_keeps_toolbar_visible(self) -> None:
        self.toolbar.show_for_selection("water")
        self.toolbar._translation_popup.show_message("result", self.toolbar)
        self.toolbar._left_button_down = False
        self.toolbar._key_state = lambda key: 0x8000 if key == 0x01 else 0
        with patch("ui.toolbar.QCursor.pos", return_value=self.toolbar._translation_popup.frameGeometry().center()):
            self.toolbar._check_dismissal()
        self.assertTrue(self.toolbar.isVisible())


if __name__ == "__main__":
    unittest.main()
