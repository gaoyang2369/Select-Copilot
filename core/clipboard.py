"""Bounded copy transactions without sentinels or unconditional restoration."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
import logging
import struct
import time

import pywintypes
import win32clipboard as clipboard
import win32con
import win32gui
import win32process

logger = logging.getLogger(__name__)
_ERRORS = (OSError, pywintypes.error, ValueError)
_MEMORY_FORMATS = {1, 7, 8, 13, 15, 16, 17}  # text, DIB, files, locale, DIBV5
_NAMED_FORMATS = {"HTML Format", "Rich Text Format", "Rich Text Format Without Objects"}


class ClipboardUnavailable(ValueError):
    """A fixed diagnostic code, safe to log without clipboard contents."""


class ClipboardService:
    def __init__(self, copy_wait_seconds: float = 0.5, poll_seconds: float = 0.01) -> None:
        self.copy_wait_seconds = copy_wait_seconds
        self.poll_seconds = poll_seconds

    @contextmanager
    def _open(self, owner: int = 0):
        deadline = time.monotonic() + 0.08
        while True:
            try:
                clipboard.OpenClipboard(owner)
                break
            except pywintypes.error:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(self.poll_seconds)
        try:
            yield
        finally:
            clipboard.CloseClipboard()

    @staticmethod
    def _snapshot() -> list[tuple[int, str | bytes]]:
        formats = []
        format_id = 0
        while format_id := clipboard.EnumClipboardFormats(format_id):
            if format_id not in _MEMORY_FORMATS:
                if format_id < 0xC000 or clipboard.GetClipboardFormatName(format_id) not in _NAMED_FORMATS:
                    raise ClipboardUnavailable("clipboard_format_unsupported")
            formats.append(format_id)
        saved = []
        size = 0
        for format_id in formats:
            data = clipboard.GetClipboardData(format_id)
            if format_id == win32con.CF_HDROP:
                # GetClipboardData returns filenames; SetClipboardData needs DROPFILES.
                names = ("\0".join(data) + "\0\0").encode("utf-16-le")
                data = struct.pack("<IiiII", 20, 0, 0, 0, 1) + names
            if not isinstance(data, (str, bytes)):
                raise ClipboardUnavailable("clipboard_format_unsupported")
            size += len(data) * (2 if isinstance(data, str) else 1)
            if size > 16 * 1024 * 1024:
                raise ClipboardUnavailable("clipboard_backup_too_large")
            saved.append((format_id, data))
        return saved

    @staticmethod
    def _from_target(owner: int, window: int) -> bool:
        if not owner:
            return False
        return (win32process.GetWindowThreadProcessId(owner)[1]
                == win32process.GetWindowThreadProcessId(window)[1])

    def read_text(self) -> str:
        """Explicit clipboard entry: read only; never synthesize a copy."""
        try:
            with self._open():
                if clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                    return clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
        except _ERRORS:
            logger.info("Clipboard text unavailable")
        return ""

    def get_text_after_copy(self, send_copy: Callable[[], bool | None], *, window: int,
                            is_current: Callable[[], bool] = lambda: True) -> str:
        owner_window = 0
        captured_sequence = None
        captured_owner = 0
        previous = []
        try:
            # A real HWND is required when EmptyClipboard transfers ownership.
            owner_window = win32gui.CreateWindowEx(
                0, "STATIC", "", 0, 0, 0, 0, 0, -3, 0, 0, None,
            )
            with self._open(owner_window):
                previous = self._snapshot()
                before = clipboard.GetClipboardSequenceNumber()
            if not is_current() or clipboard.GetClipboardSequenceNumber() != before:
                return ""
            if send_copy() is False:
                return ""
            deadline = time.monotonic() + self.copy_wait_seconds
            stable_since = time.monotonic()
            last_sequence = before
            while time.monotonic() < deadline and is_current():
                sequence = clipboard.GetClipboardSequenceNumber()
                if sequence != last_sequence:
                    last_sequence = sequence
                    stable_since = time.monotonic()
                # Wait for multi-stage writes, without modifying clipboard contents.
                if sequence != before and time.monotonic() - stable_since >= 0.04:
                    with self._open(owner_window):
                        if clipboard.GetClipboardSequenceNumber() != sequence:
                            continue
                        owner = clipboard.GetClipboardOwner()
                        if not self._from_target(owner, window):
                            logger.info("Copy skipped: clipboard changed by another application")
                            return ""
                        captured_sequence, captured_owner = sequence, owner
                        if clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                            return clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
                        return ""
                time.sleep(self.poll_seconds)
            logger.info("Copy cancelled or clipboard response timed out")
            # A late response may arrive near the deadline without becoming stable
            # long enough to return. Restore it only if it is still from our target.
            if is_current():
                with self._open(owner_window):
                    sequence = clipboard.GetClipboardSequenceNumber()
                    owner = clipboard.GetClipboardOwner()
                    if sequence != before and self._from_target(owner, window):
                        captured_sequence, captured_owner = sequence, owner
        except _ERRORS as error:
            # Do not include clipboard data or application-provided error messages.
            logger.info("Copy unavailable: %s", str(error) if isinstance(error, ClipboardUnavailable)
                        else type(error).__name__)
        finally:
            if captured_sequence is not None:
                try:
                    with self._open(owner_window):
                        if (is_current() and clipboard.GetClipboardSequenceNumber() == captured_sequence
                                and clipboard.GetClipboardOwner() == captured_owner):
                            clipboard.EmptyClipboard()
                            for format_id, data in previous:
                                clipboard.SetClipboardData(format_id, data)
                        else:
                            logger.info("Clipboard restore skipped: request or clipboard changed")
                except _ERRORS:
                    logger.warning("Clipboard restoration failed")
            if owner_window:
                win32gui.DestroyWindow(owner_window)
        return ""
