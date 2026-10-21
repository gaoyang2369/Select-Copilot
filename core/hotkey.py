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
HOTKEY = "alt+q"
_WM_HOTKEY = 0x0312
_HOTKEY_ID = 0x5343
_MODIFIERS = 0x0001 | 0x0002 | 0x4000  # ALT | CONTROL | NOREPEAT
_VK_SPACE = 0x20
_RELEASE_KEYS = (0x10, 0x11, 0x12, 0x20, 0x5B, 0x5C)  # Shift, Ctrl, Alt, Space, Win


def parse_hotkey(value: str) -> tuple[int, int]:
    """Accept modifiers plus one letter, digit, Space or F1-F24."""
    parts = [part.strip().lower() for part in value.split("+")]
    modifiers = {"alt": 1, "ctrl": 2, "shift": 4, "win": 8}
    if len(parts) < 2 or len(parts) != len(set(parts)):
        raise ValueError("快捷键需要修饰键和一个按键，例如 alt+q。")
    flags = 0x4000
    for part in parts[:-1]:
        if part not in modifiers:
            raise ValueError("修饰键支持 ctrl、alt、shift、win。")
        flags |= modifiers[part]
    key = parts[-1]
    if key == "space":
        code = 0x20
    elif len(key) == 1 and key in "abcdefghijklmnopqrstuvwxyz0123456789":
        code = ord(key.upper())
    elif key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        code = 0x70 + int(key[1:]) - 1
    else:
        raise ValueError("主键支持字母、数字、space 或 F1–F24。")
    return flags, code


class GlobalHotkey(QAbstractNativeEventFilter):
    """Keep the native event handler short; capture text in one background thread."""

    def __init__(self, callback: Callable[..., None], hotkey: str = HOTKEY,
                 context: Callable[[], object] | None = None) -> None:
        super().__init__()
        self._callback = callback
        self._context = context
        self.hotkey = hotkey
        self._modifiers, self._key = parse_hotkey(hotkey)
        self._hotkey_id = _HOTKEY_ID
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
        if not self._user32.RegisterHotKey(None, self._hotkey_id, self._modifiers, self._key):
            error = ctypes.WinError(ctypes.get_last_error())
            raise RuntimeError(
                f"Cannot register {self.hotkey}: {error}. "
                "Close another Selection Copilot instance or the app using this shortcut."
            ) from error
        self._stopping.clear()
        self._registered = True
        application.installNativeEventFilter(self)

    def reconfigure(self, hotkey: str) -> None:
        """Reserve the new combination before releasing the current shortcut."""
        modifiers, key = parse_hotkey(hotkey)
        if not self._registered:
            self.hotkey, self._modifiers, self._key = hotkey, modifiers, key
            self.start()
            return
        if (modifiers, key) == (self._modifiers, self._key):
            return
        new_id = _HOTKEY_ID + (self._hotkey_id == _HOTKEY_ID)
        if not self._user32.RegisterHotKey(None, new_id, modifiers, key):
            raise RuntimeError(f"快捷键 {hotkey} 注册失败，可能已被占用；原快捷键仍然有效。")
        self._user32.UnregisterHotKey(None, self._hotkey_id)
        self._hotkey_id = new_id
        self.hotkey, self._modifiers, self._key = hotkey, modifiers, key

    def nativeEventFilter(self, event_type, message):  # type: ignore[no-untyped-def]
        if bytes(event_type) not in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
            return False, 0
        event = wintypes.MSG.from_address(int(message))
        if event.message == _WM_HOTKEY and event.wParam == self._hotkey_id and self._registered:
            self._schedule_callback()
            return True, 0
        return False, 0

    def _schedule_callback(self) -> None:
        if self._stopping.is_set() or (self._worker is not None and self._worker.is_alive()):
            return
        logger.info("Hotkey received; waiting for keys to be released.")
        # Snapshot the source before waiting: releasing Alt may activate another app.
        context = self._context() if self._context is not None else None
        self._worker = threading.Thread(target=self._run_after_hotkey_release, args=(context,), daemon=True)
        self._worker.start()

    def _run_after_hotkey_release(self, context: object = None) -> None:
        """Never send Ctrl+C with held modifiers, including after a release timeout."""
        try:
            deadline = time.monotonic() + 2.0
            while not self._stopping.is_set():
                keys = (*_RELEASE_KEYS, self._key) if self._key not in _RELEASE_KEYS else _RELEASE_KEYS
                if not any(self._user32.GetAsyncKeyState(key) & 0x8000 for key in keys):
                    if not self._stopping.is_set():
                        if self._context is None:
                            self._callback()
                        else:
                            self._callback(context)
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
            self._user32.UnregisterHotKey(None, self._hotkey_id)
            application = QCoreApplication.instance()
            if application is not None:
                application.removeNativeEventFilter(self)
            self._registered = False
        if self._worker is not None and self._worker is not threading.current_thread():
            self._worker.join()
