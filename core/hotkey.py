"""Windows global hotkey registration, delivered through Qt's message loop."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import logging
import threading
import time
from collections.abc import Callable

from PySide6.QtCore import QAbstractNativeEventFilter, QCoreApplication


logger = logging.getLogger(__name__)
HOTKEY = "ctrl+alt+space"
_WM_HOTKEY = 0x0312
_HOTKEY_ID = 0x5343
_MODIFIERS = 0x0001 | 0x0002 | 0x4000  # ALT | CONTROL | NOREPEAT
_VK_SPACE = 0x20
_RELEASE_KEYS = (0x10, 0x11, 0x12, 0x20, 0x5B, 0x5C)  # Shift, Ctrl, Alt, Space, Win


class GlobalHotkey(QAbstractNativeEventFilter):
    """Keep the native event handler short; capture text in one background thread."""

    def __init__(self, callback: Callable[[], None]) -> None:
        super().__init__()
        self._callback = callback
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        self._user32.RegisterHotKey.restype = wintypes.BOOL
        self._user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        self._user32.UnregisterHotKey.restype = wintypes.BOOL
        self._user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
        self._user32.GetAsyncKeyState.restype = ctypes.c_short
        self._registered = False
        self._stopping = threading.Event()
        self._worker: threading.Thread | None = None

    def start(self) -> None:
        """Register on the Qt GUI thread; report conflicts instead of failing silently."""
        if self._registered:
            return
        application = QCoreApplication.instance()
        if application is None:
            raise RuntimeError("Create QApplication before starting the hotkey")
        if not self._user32.RegisterHotKey(None, _HOTKEY_ID, _MODIFIERS, _VK_SPACE):
            error = ctypes.WinError(ctypes.get_last_error())
            raise RuntimeError(
                f"Cannot register {HOTKEY}: {error}. "
                "Close another Selection Copilot instance or the app using this shortcut."
            ) from error
        self._stopping.clear()
        self._registered = True
        application.installNativeEventFilter(self)

    def nativeEventFilter(self, event_type, message):  # type: ignore[no-untyped-def]
        if bytes(event_type) not in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
            return False, 0
        event = wintypes.MSG.from_address(int(message))
        if event.message == _WM_HOTKEY and event.wParam == _HOTKEY_ID and self._registered:
            self._schedule_callback()
            return True, 0
        return False, 0

    def _schedule_callback(self) -> None:
        if self._stopping.is_set() or (self._worker is not None and self._worker.is_alive()):
            return
        logger.info("Hotkey received; waiting for keys to be released.")
        self._worker = threading.Thread(target=self._run_after_hotkey_release, daemon=True)
        self._worker.start()

    def _run_after_hotkey_release(self) -> None:
        """Never send Ctrl+C with held modifiers, including after a release timeout."""
        try:
            deadline = time.monotonic() + 2.0
            while not self._stopping.is_set():
                if not any(self._user32.GetAsyncKeyState(key) & 0x8000 for key in _RELEASE_KEYS):
                    if not self._stopping.is_set():
                        self._callback()
                    return
                if time.monotonic() >= deadline:
                    logger.warning("Selection cancelled: release all shortcut keys and try again.")
                    return
                self._stopping.wait(0.01)
        except Exception:
            logger.exception("Selection capture failed")

    def stop(self) -> None:
        """Unregister on the GUI thread and finish clipboard restoration before exit."""
        self._stopping.set()
        if self._registered:
            self._user32.UnregisterHotKey(None, _HOTKEY_ID)
            application = QCoreApplication.instance()
            if application is not None:
                application.removeNativeEventFilter(self)
            self._registered = False
        if self._worker is not None and self._worker is not threading.current_thread():
            self._worker.join()
