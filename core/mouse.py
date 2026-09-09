"""Observe Windows drags and double-clicks without consuming input."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import logging
import os
import threading
import time

from PySide6.QtCore import QObject, Signal

logger = logging.getLogger(__name__)
WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP = 0x0200, 0x0201, 0x0202
WM_QUIT = 0x0012
HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)


class MouseData(ctypes.Structure):
    _fields_ = [("pt", wintypes.POINT), ("mouseData", wintypes.DWORD),
                ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


@dataclass(frozen=True)
class Drag:
    generation: int
    window: int
    bounds: tuple[int, int, int, int]


class DragDetector:
    """Recognize drags and double-clicks, emitting only after button release."""

    def __init__(
        self, threshold: int = 8, *, double_click_ms: int = 500,
        double_click_size: tuple[int, int] = (4, 4),
    ) -> None:
        self.threshold = threshold
        self.double_click_ms = double_click_ms
        self.double_click_size = double_click_size
        self.generation = 0
        self._origin: tuple[int, int] | None = None
        self._moved = False
        self._down: tuple[int, int, int, int | None] | None = None
        self._previous_click: tuple[int, int, int, int | None] | None = None
        self._double_click = False

    def feed(
        self, event: int, x: int, y: int, *,
        time_ms: int | None = None, target: int | None = None,
    ) -> bool:
        if event == WM_LBUTTONDOWN:
            timestamp = int(time.monotonic() * 1000) if time_ms is None else time_ms
            self._double_click = False
            if self._previous_click is not None:
                previous_time, previous_x, previous_y, previous_target = self._previous_click
                # MSLLHOOKSTRUCT.time is a DWORD and wraps after ~49.7 days.
                elapsed = (timestamp - previous_time) & 0xFFFFFFFF
                width, height = self.double_click_size
                self._double_click = (
                    elapsed <= self.double_click_ms and target == previous_target
                    and -width // 2 <= x - previous_x < width // 2
                    and -height // 2 <= y - previous_y < height // 2
                )
            self._previous_click = None
            self._down = (timestamp, x, y, target)
            self.generation += 1
            self._origin = (x, y)
            self._moved = False
        elif event in (WM_MOUSEMOVE, WM_LBUTTONUP) and self._origin is not None:
            dx, dy = x - self._origin[0], y - self._origin[1]
            self._moved |= dx * dx + dy * dy >= self.threshold * self.threshold
            if event == WM_LBUTTONUP:
                result = self._moved or self._double_click
                # Consume a recognized pair; do not pair its second click again.
                self._previous_click = None if result else self._down
                self._origin = None
                self._down = None
                return result
        return False

    def reset(self) -> None:
        self.generation += 1
        self._origin = None
        self._moved = False
        self._down = None
        self._previous_click = None
        self._double_click = False


class MouseSelectionListener(QObject):
    dragged = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        api = self._user32
        signatures = {
            "SetWindowsHookExW": ([ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD], wintypes.HANDLE),
            "CallNextHookEx": ([wintypes.HANDLE, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM], ctypes.c_ssize_t),
            "UnhookWindowsHookEx": ([wintypes.HANDLE], wintypes.BOOL),
            "GetMessageW": ([ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT], ctypes.c_int),
            "PeekMessageW": ([ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT], wintypes.BOOL),
            "TranslateMessage": ([ctypes.POINTER(wintypes.MSG)], wintypes.BOOL),
            "DispatchMessageW": ([ctypes.POINTER(wintypes.MSG)], ctypes.c_ssize_t),
            "PostThreadMessageW": ([wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM], wintypes.BOOL),
            "GetForegroundWindow": ([], wintypes.HWND),
            "WindowFromPoint": ([wintypes.POINT], wintypes.HWND),
            "GetAncestor": ([wintypes.HWND, wintypes.UINT], wintypes.HWND),
            "GetWindowThreadProcessId": ([wintypes.HWND, ctypes.POINTER(wintypes.DWORD)], wintypes.DWORD),
            "GetWindowRect": ([wintypes.HWND, ctypes.POINTER(wintypes.RECT)], wintypes.BOOL),
            "GetAsyncKeyState": ([ctypes.c_int], ctypes.c_short),
            "GetDoubleClickTime": ([], wintypes.UINT),
            "GetSystemMetrics": ([ctypes.c_int], ctypes.c_int),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(api, name)
            function.argtypes, function.restype = arguments, result
        self._kernel32.GetCurrentThreadId.restype = wintypes.DWORD
        self._kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        self._kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        self.detector = DragDetector()
        self._candidate: Drag | None = None
        self._callback = HOOKPROC(self._hook_callback)  # Keep alive until unhooked.
        self._handle = None
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._ready = threading.Event()
        self._stopping = threading.Event()
        self._error: Exception | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and self._handle is not None

    def foreground(self) -> int:
        return self._user32.GetForegroundWindow() or 0

    def bounds(self, window: int) -> tuple[int, int, int, int]:
        rect = wintypes.RECT()
        if not self._user32.GetWindowRect(window, ctypes.byref(rect)):
            return (0, 0, 0, 0)
        return rect.left, rect.top, rect.right, rect.bottom

    def external(self, window: int) -> bool:
        process = wintypes.DWORD()
        self._user32.GetWindowThreadProcessId(window, ctypes.byref(process))
        return bool(window and process.value and process.value != os.getpid())

    def can_capture(self, window: int) -> bool:
        return (
            self.foreground() == window and self.external(window)
            and not any(self._user32.GetAsyncKeyState(key) & 0x8000 for key in (1, 2, 0x10, 0x11, 0x12, 0x5B, 0x5C, 0x1B))
        )

    def is_current(self, drag: Drag) -> bool:
        return (
            self.running and drag.generation == self.detector.generation
            and self.bounds(drag.window) == drag.bounds and self.can_capture(drag.window)
        )

    def _hook_callback(self, code: int, event: int, pointer: int) -> int:
        try:
            if code >= 0 and event in (WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP) and not self._stopping.is_set():
                data = MouseData.from_address(pointer)
                if not data.flags & 1:  # Ignore synthetic input.
                    target = self._user32.WindowFromPoint(data.pt) if event == WM_LBUTTONDOWN else None
                    selected = self.detector.feed(
                        event, data.pt.x, data.pt.y, time_ms=data.time, target=target,
                    )
                    if event == WM_LBUTTONDOWN:
                        window = self.foreground()
                        root = self._user32.GetAncestor(target, 2)
                        self._candidate = (
                            Drag(self.detector.generation, window, self.bounds(window))
                            if root == window and self.external(window) else None
                        )
                    elif event == WM_LBUTTONUP and selected and self._candidate is not None:
                        self.dragged.emit(self._candidate)
        except Exception:
            # A hook must always forward input even if observation fails.
            self._candidate = None
        return self._user32.CallNextHookEx(self._handle, code, event, pointer)

    def start(self) -> None:
        if self.running:
            return
        self._ready.clear()
        self._stopping.clear()
        self._error = None
        self.detector.reset()
        self.detector.double_click_ms = self._user32.GetDoubleClickTime()
        self.detector.double_click_size = (
            self._user32.GetSystemMetrics(36), self._user32.GetSystemMetrics(37),
        )
        self._thread = threading.Thread(target=self._run, name="selection-mouse", daemon=True)
        self._thread.start()
        if not self._ready.wait(3):
            self.stop()
            raise RuntimeError("鼠标监听启动超时。")
        if self._error is not None:
            self.stop()
            raise RuntimeError(f"鼠标监听启动失败：{self._error}") from self._error

    def _run(self) -> None:
        try:
            self._thread_id = self._kernel32.GetCurrentThreadId()
            message = wintypes.MSG()
            self._user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 0)
            self._handle = self._user32.SetWindowsHookExW(
                14, self._callback, self._kernel32.GetModuleHandleW(None), 0,
            )
            if not self._handle:
                raise ctypes.WinError(ctypes.get_last_error())
            self._ready.set()
            while not self._stopping.is_set():
                result = self._user32.GetMessageW(ctypes.byref(message), None, 0, 0)
                if result <= 0:
                    if result < 0:
                        logger.error("Mouse message loop failed")
                    break
                self._user32.TranslateMessage(ctypes.byref(message))
                self._user32.DispatchMessageW(ctypes.byref(message))
        except Exception as error:
            self._error = error
        finally:
            self._ready.set()
            if self._handle:
                self._user32.UnhookWindowsHookEx(self._handle)
                self._handle = None

    def stop(self) -> None:
        self._stopping.set()
        self.detector.reset()
        if self._thread is not None and self._thread.is_alive():
            self._user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
            self._thread.join()
