from __future__ import annotations

from dataclasses import replace
import os
import threading
import time
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app import CaptureRequest, CopilotController
from config.settings import Settings
from core.mouse import Drag, DragDetector, WM_LBUTTONDOWN, WM_LBUTTONUP


class FakeMouse(QObject):
    dragged = Signal(object)

    def __init__(self):
        super().__init__()
        self.running = False
        self.detector = DragDetector()
        self.window = 10

    def start(self):
        self.running = True

    def stop(self):
        self.running = False
        self.detector.reset()

    def foreground(self):
        return self.window

    def can_capture(self, window):
        return window == self.window

    def is_current(self, drag):
        return self.running and drag.generation == self.detector.generation and self.can_capture(drag.window)


class FakeHotkey:
    def __init__(self, callback, hotkey):
        self.hotkey = hotkey
        self._registered = False

    def start(self):
        self._registered = True

    def stop(self):
        self._registered = False

    def reconfigure(self, hotkey):
        if hotkey == "ctrl+f10":
            raise RuntimeError("occupied")
        self.hotkey = hotkey
        self._registered = True


class ControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.store = Mock()
        self.store.load.return_value = Settings(base_url="https://example.test/v1", api_key="test", model="old")
        with patch("app.MouseSelectionListener", FakeMouse), patch("app.GlobalHotkey", FakeHotkey), patch("app.CopilotTray"):
            self.controller = CopilotController(self.application, self.store)
        with patch("app.QSystemTrayIcon.isSystemTrayAvailable", return_value=True):
            self.controller.start()
        self.controller.selection_service = Mock()
        self.controller.selection_service.get_selected_text.return_value = "selected text"

    def tearDown(self):
        self.controller.shutdown()
        for window in list(self.controller.toolbar._chat_windows):
            window.close()
        self.controller.toolbar.close()
        self.application.processEvents()

    def wait_for(self, condition):
        deadline = time.monotonic() + 2
        while not condition() and time.monotonic() < deadline:
            QTest.qWait(10)
        self.assertTrue(condition())

    def drag(self):
        return Drag(self.controller.mouse.detector.generation, 10, (0, 0, 100, 100))

    def test_mouse_capture_is_delayed_and_does_not_call_ai(self):
        c = self.controller
        with patch.object(c.toolbar._translator, "translate") as translate, patch.object(c.toolbar._llm_service, "ask") as ask:
            c._schedule_auto(self.drag())
            c.selection_service.get_selected_text.assert_not_called()
            self.wait_for(lambda: c.toolbar.selected_text == "selected text")
            self.assertTrue(c.toolbar.isVisible())
            translate.assert_not_called()
            ask.assert_not_called()

    def test_double_click_uses_delayed_capture_pipeline(self):
        c = self.controller
        detector = c.mouse.detector
        for event, stamp in ((WM_LBUTTONDOWN, 100), (WM_LBUTTONUP, 120), (WM_LBUTTONDOWN, 200)):
            self.assertFalse(detector.feed(event, 10, 10, time_ms=stamp, target=42))
        c.selection_service.get_selected_text.assert_not_called()
        self.assertTrue(detector.feed(WM_LBUTTONUP, 10, 10, time_ms=220))
        c.mouse.dragged.emit(self.drag())
        c.selection_service.get_selected_text.assert_not_called()
        self.wait_for(lambda: c.toolbar.selected_text == "selected text")
        c.selection_service.get_selected_text.assert_called_once()

    def test_pause_cancels_pending_auto_but_keeps_manual_shortcut(self):
        c = self.controller
        c._schedule_auto(self.drag())
        c.toggle_auto(False)
        QTest.qWait(150)
        c.selection_service.get_selected_text.assert_not_called()
        self.assertFalse(c.mouse.running)
        c._capture_manual(10)
        self.wait_for(lambda: c.toolbar.selected_text == "selected text")

    def test_changed_foreground_discards_capture(self):
        c = self.controller
        request = CaptureRequest(10, c._epoch, self.drag())
        c.mouse.window = 20
        c._deliver_capture("stale", request)
        self.assertFalse(c.toolbar.isVisible())

    def test_auto_empty_text_does_not_replace_existing_selection(self):
        c = self.controller
        c.toolbar.show_for_selection("previous")
        c._deliver_capture("", CaptureRequest(10, c._epoch, self.drag()))
        self.assertEqual(c.toolbar.selected_text, "previous")
        self.assertTrue(c.toolbar.isVisible())

    def test_latest_capture_waits_for_busy_worker_and_drops_old_result(self):
        c = self.controller
        started, release = threading.Event(), threading.Event()
        calls = []
        def capture():
            calls.append(1)
            if len(calls) == 1:
                started.set()
                release.wait(2)
                return "old result"
            return "new result"
        c.selection_service.get_selected_text.side_effect = capture
        try:
            c._capture_manual(10)
            self.assertTrue(started.wait(1))
            c._capture_manual(10)
            release.set()
            self.wait_for(lambda: c.toolbar.selected_text == "new result")
            self.assertEqual(len(calls), 2)
        finally:
            release.set()

    def test_failed_save_rolls_back_hotkey_mouse_and_services(self):
        c = self.controller
        previous = c.settings
        translator = c.toolbar._translator
        self.store.save.side_effect = OSError("disk full")
        with self.assertRaises(OSError):
            c.apply_settings(replace(previous, hotkey="ctrl+f8", model="new", auto_select=False))
        self.assertEqual(c.settings, previous)
        self.assertEqual(c.hotkey.hotkey, previous.hotkey)
        self.assertTrue(c.mouse.running)
        self.assertIs(c.toolbar._translator, translator)

    def test_hotkey_conflict_does_not_save_settings(self):
        c = self.controller
        with self.assertRaises(RuntimeError):
            c.apply_settings(replace(c.settings, hotkey="ctrl+f10"))
        self.store.save.assert_not_called()
        self.assertEqual(c.hotkey.hotkey, c.settings.hotkey)

    def test_settings_update_new_services_and_preserve_existing_chat(self):
        c = self.controller
        c.toolbar.show_for_selection("context")
        c.toolbar._open_chat()
        old_service = c.toolbar._chat_windows[0]._session._llm_service
        c.apply_settings(replace(c.settings, model="new", stream=False, thinking="enabled"))
        self.assertEqual(c.toolbar._llm_service._model, "new")
        self.assertFalse(c.toolbar._llm_service._stream)
        self.assertEqual(c.toolbar._llm_service._thinking, "enabled")
        self.assertEqual(old_service._model, "old")
        self.store.save.assert_called_once()

    def test_dialog_rejects_invalid_shortcut_without_saving(self):
        c = self.controller
        c.open_settings()
        c.dialog.hotkey.setText("ctrl+")
        c.dialog._save()
        self.assertTrue(c.dialog.isVisible())
        self.assertTrue(c.dialog.error.text())
        self.store.save.assert_not_called()
