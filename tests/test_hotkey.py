from __future__ import annotations

import ctypes
from ctypes import wintypes
import threading
import unittest
from unittest.mock import Mock, patch

from core.hotkey import GlobalHotkey, _HOTKEY_ID, _WM_HOTKEY


class GlobalHotkeyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.callback = Mock()
        self.hotkey = GlobalHotkey(self.callback)
        self.api = Mock()
        self.api.GetAsyncKeyState.return_value = 0
        self.hotkey._user32 = self.api

    def tearDown(self) -> None:
        self.hotkey.stop()

    def test_registration_failure_is_reported(self) -> None:
        self.api.RegisterHotKey.return_value = False
        with patch('core.hotkey.QCoreApplication') as application:
            with self.assertRaisesRegex(RuntimeError, 'Cannot register ctrl\\+alt\\+space'):
                self.hotkey.start()
            application.instance.return_value.installNativeEventFilter.assert_not_called()

    def test_native_hotkey_message_runs_callback_off_gui_thread(self) -> None:
        calls = []
        self.hotkey._callback = lambda: calls.append(threading.get_ident())
        self.hotkey._registered = True
        message = wintypes.MSG()
        message.message = _WM_HOTKEY
        message.wParam = _HOTKEY_ID
        handled, _ = self.hotkey.nativeEventFilter(b'windows_dispatcher_MSG', ctypes.addressof(message))
        self.hotkey._worker.join(timeout=1)
        self.assertTrue(handled)
        self.assertEqual(len(calls), 1)
        self.assertNotEqual(calls[0], threading.get_ident())

    def test_unrelated_native_message_is_ignored(self) -> None:
        self.hotkey._registered = True
        message = wintypes.MSG()
        message.message = _WM_HOTKEY
        message.wParam = _HOTKEY_ID + 1
        self.assertEqual(self.hotkey.nativeEventFilter(b'windows_generic_MSG', ctypes.addressof(message)), (False, 0))
        self.callback.assert_not_called()

    def test_held_modifiers_timeout_never_copies(self) -> None:
        self.api.GetAsyncKeyState.return_value = 0x8000
        with patch('core.hotkey.time.monotonic', side_effect=[0, 3]):
            with self.assertLogs('core.hotkey', level='WARNING'):
                self.hotkey._run_after_hotkey_release()
        self.callback.assert_not_called()

    def test_waits_longer_than_old_timeout_then_copies_after_release(self) -> None:
        self.api.GetAsyncKeyState.side_effect = [0x8000, 0x8000] + [0] * 6
        with patch('core.hotkey.time.monotonic', side_effect=[0, 0.1, 0.4]):
            self.hotkey._run_after_hotkey_release()
        self.callback.assert_called_once()

    def test_stop_cancels_release_wait(self) -> None:
        self.api.GetAsyncKeyState.return_value = 0x8000
        self.hotkey._schedule_callback()
        self.hotkey.stop()
        self.assertFalse(self.hotkey._worker.is_alive())
        self.callback.assert_not_called()

    def test_repeated_hotkey_does_not_overlap_captures(self) -> None:
        started = threading.Event()
        release = threading.Event()
        def capture():
            self.callback()
            started.set()
            release.wait(1)
        self.hotkey._callback = capture
        try:
            self.hotkey._schedule_callback()
            self.assertTrue(started.wait(1))
            self.hotkey._schedule_callback()
            self.callback.assert_called_once()
        finally:
            release.set()

    def test_callback_failure_is_logged(self) -> None:
        self.callback.side_effect = RuntimeError('copy failed')
        with self.assertLogs('core.hotkey', level='ERROR') as logs:
            self.hotkey._run_after_hotkey_release()
        self.assertIn('copy failed', '\n'.join(logs.output))
