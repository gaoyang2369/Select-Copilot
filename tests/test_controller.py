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
from core.uia import SelectionResult


class FakeMouse(QObject):
    dragged = Signal(object)
    cancelled = Signal()

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

    def can_copy(self, window):
        return self.can_capture(window)

    def cursor_position(self):
        return (50, 50)

    def program_name(self, window):
        return "source.exe"

    def is_console(self, window):
        return False

    def is_current(self, drag):
        return self.running and drag.generation == self.detector.generation and self.can_capture(drag.window)


class FakeHotkey:
    def __init__(self, callback, hotkey, context=None):
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
        with patch("app.MouseSelectionListener", FakeMouse), patch("app.GlobalHotkey", FakeHotkey), \
                patch("app.CopilotTray"), patch("app.ReaderProcess"):
            self.controller = CopilotController(self.application, self.store)
        with patch("app.QSystemTrayIcon.isSystemTrayAvailable", return_value=True):
            self.controller.start()
        self.controller.selection_service = Mock()
        self.controller.selection_service.capture.return_value = SelectionResult("selected", "selected text")

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
            c.selection_service.capture.assert_not_called()
            self.wait_for(lambda: c.toolbar.selected_text == "selected text")
            self.assertTrue(c.toolbar.isVisible())
            translate.assert_not_called()
            ask.assert_not_called()

    def test_double_click_uses_delayed_capture_pipeline(self):
        c = self.controller
        detector = c.mouse.detector
        for event, stamp in ((WM_LBUTTONDOWN, 100), (WM_LBUTTONUP, 120), (WM_LBUTTONDOWN, 200)):
            self.assertFalse(detector.feed(event, 10, 10, time_ms=stamp, target=42))
        c.selection_service.capture.assert_not_called()
        self.assertTrue(detector.feed(WM_LBUTTONUP, 10, 10, time_ms=220))
        c.mouse.dragged.emit(self.drag())
        c.selection_service.capture.assert_not_called()
        self.wait_for(lambda: c.toolbar.selected_text == "selected text")
        c.selection_service.capture.assert_called_once()

    def test_pause_cancels_pending_auto_but_keeps_manual_shortcut(self):
        c = self.controller
        c._schedule_auto(self.drag())
        c.toggle_auto(False)
        QTest.qWait(150)
        c.selection_service.capture.assert_not_called()
        self.assertFalse(c.mouse.running)
        c._capture_manual(10)
        self.wait_for(lambda: c.toolbar.selected_text == "selected text")

    def test_auto_copy_policy_requires_an_explicit_matching_app(self):
        c = self.controller
        for mode, apps, expected in (("manual", "source.exe", False),
                                     ("never", "source.exe", False),
                                     ("allowlist", "other.exe", False),
                                     ("allowlist", "SOURCE.exe", True)):
            with self.subTest(mode=mode, apps=apps):
                c.settings = replace(c.settings, clipboard_fallback=mode, clipboard_apps=apps)
                c.selection_service.reset_mock()
                request = CaptureRequest(10, c._epoch, self.drag())
                c._read_selection(request)
                self.assertEqual(c.selection_service.capture.call_args.kwargs["allow_copy"], expected)

    def test_manual_copy_policy_and_console_exclusion(self):
        c = self.controller
        request = CaptureRequest(10, c._epoch)
        c._read_selection(request)
        self.assertTrue(c.selection_service.capture.call_args.kwargs["allow_copy"])
        c.settings = replace(c.settings, clipboard_fallback="never")
        c._read_selection(request)
        self.assertFalse(c.selection_service.capture.call_args.kwargs["allow_copy"])
        c.settings = replace(c.settings, clipboard_fallback="manual")
        c.mouse.is_console = lambda window: True
        c._read_selection(request)
        self.assertFalse(c.selection_service.capture.call_args.kwargs["allow_copy"])

    def test_compatibility_profile_is_scoped_to_wechat_and_user_gestures(self):
        c = self.controller
        c.settings = replace(c.settings, clipboard_fallback="compatible")
        for program, source, expected in (("weixin.exe", "mouse", True),
                                           ("wechat.exe", "keyboard", True),
                                           ("weixin.exe", "uia_event", False),
                                           ("other.exe", "mouse", False)):
            c.mouse.program_name = lambda _, name=program: name
            c._read_selection(CaptureRequest(10, c._epoch, self.drag(), source=source))
            self.assertEqual(c.selection_service.capture.call_args.kwargs["allow_copy"], expected)

    def test_selection_event_does_not_cancel_active_settling_session(self):
        c = self.controller
        c._schedule_auto(self.drag())
        epoch = c._epoch
        c._selection_changed(10, time.monotonic())
        self.assertEqual(c._epoch, epoch)

    def test_repeated_selection_event_does_not_reopen_dismissed_toolbar(self):
        c = self.controller
        result = SelectionResult("selected", "same selection")
        c._deliver_capture(result, CaptureRequest(10, c._epoch, self.drag()))
        c.toolbar.hide()
        c._deliver_capture(result, CaptureRequest(10, c._epoch, self.drag(), source="uia_event"))
        self.assertFalse(c.toolbar.isVisible())

    def test_excluded_app_does_not_read_selection(self):
        c = self.controller
        c.settings = replace(c.settings, excluded_apps="SOURCE.exe")
        c._read_selection(CaptureRequest(10, c._epoch, self.drag()))
        c.selection_service.capture.assert_not_called()

    def test_manual_capture_is_invalidated_by_new_input(self):
        c = self.controller
        request = CaptureRequest(10, c._epoch, generation=c.mouse.detector.generation)
        self.assertTrue(c._valid_request(request))
        c.mouse.detector.generation += 1
        self.assertFalse(c._valid_request(request))

    def test_escape_cancels_pending_capture_and_hides_toolbar(self):
        c = self.controller
        c.toolbar.show_for_selection("old")
        c._schedule_auto(self.drag())
        c.mouse.cancelled.emit()
        QTest.qWait(120)
        c.selection_service.capture.assert_not_called()
        self.assertFalse(c.toolbar.isVisible())

    def test_explicit_clipboard_entry_does_not_read_selection_or_synthesize_keys(self):
        c = self.controller
        c.clipboard_service = Mock()
        c.clipboard_service.read_text.return_value = "manually copied"
        with patch("app.keyboard.send") as send:
            c._capture_clipboard()
            self.wait_for(lambda: c.toolbar.selected_text == "manually copied")
        send.assert_not_called()
        c.selection_service.capture.assert_not_called()

    def test_copy_wait_timeout_never_sends_shortcut(self):
        c = self.controller
        c._current_request = CaptureRequest(10, c._epoch)
        c.mouse.can_copy = lambda window: False
        with patch("app.time.monotonic", side_effect=[0, 1]), patch("app.keyboard.send") as send:
            self.assertFalse(c._send_copy())
        send.assert_not_called()

    def test_changed_foreground_discards_capture(self):
        c = self.controller
        request = CaptureRequest(10, c._epoch, self.drag())
        c.mouse.window = 20
        c._deliver_capture(SelectionResult("selected", "stale"), request)
        self.assertFalse(c.toolbar.isVisible())

    def test_auto_empty_text_does_not_replace_existing_selection(self):
        c = self.controller
        c.toolbar.show_for_selection("previous")
        c._deliver_capture(SelectionResult("empty"), CaptureRequest(10, c._epoch, self.drag()))
        self.assertEqual(c.toolbar.selected_text, "previous")
        self.assertTrue(c.toolbar.isVisible())

    def test_latest_capture_waits_for_busy_worker_and_drops_old_result(self):
        c = self.controller
        started, release = threading.Event(), threading.Event()
        calls = []
        def capture(*args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                started.set()
                release.wait(2)
                return SelectionResult("selected", "old result")
            return SelectionResult("selected", "new result")
        c.selection_service.capture.side_effect = capture
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
