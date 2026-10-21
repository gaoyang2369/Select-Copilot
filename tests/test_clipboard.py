"""Clipboard transactions against a fake OS; never alter the user's clipboard."""

from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from core.clipboard import ClipboardService


class FakeClipboard:
    def __init__(self):
        self.data = {13: "previous"}
        self.sequence = 1
        self.owner = 100
        self.after_close = None
        self.restores = 0

    def OpenClipboard(self, owner):
        pass

    def CloseClipboard(self):
        if self.after_close:
            callback, self.after_close = self.after_close, None
            callback()

    def EnumClipboardFormats(self, previous):
        ids = sorted(self.data)
        return next((value for value in ids if value > previous), 0)

    def GetClipboardFormatName(self, value):
        return {50000: "HTML Format", 50001: "Opaque private format"}[value]

    def GetClipboardData(self, format_id):
        return self.data[format_id]

    def IsClipboardFormatAvailable(self, value):
        return value in self.data

    def GetClipboardSequenceNumber(self):
        return self.sequence

    def GetClipboardOwner(self):
        return self.owner

    def EmptyClipboard(self):
        self.data = {}
        self.sequence += 1
        self.owner = 999
        self.restores += 1

    def SetClipboardData(self, format_id, value):
        self.data[format_id] = value
        self.sequence += 1

    def write(self, data, owner=10):
        self.data, self.owner = data, owner
        self.sequence += 1


class ClipboardTests(unittest.TestCase):
    def setUp(self):
        self.api = FakeClipboard()
        self.now = 0
        self.service = ClipboardService()
        for patcher in (
            patch("core.clipboard.clipboard", self.api),
            patch("core.clipboard.win32gui.CreateWindowEx", return_value=999),
            patch("core.clipboard.win32gui.DestroyWindow"),
            patch("core.clipboard.win32process.GetWindowThreadProcessId", side_effect=lambda window: (1, window)),
            patch("core.clipboard.time.monotonic", side_effect=lambda: self.now),
            patch("core.clipboard.time.sleep", side_effect=self.advance),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def advance(self, seconds):
        self.now += seconds

    def capture(self, send_copy, **kwargs):
        return self.service.get_text_after_copy(send_copy, window=10, **kwargs)

    def test_copy_restores_text_rich_text_and_image_formats_without_sentinel(self):
        before = {13: "previous", 50000: b"<b>previous</b>", 8: b"DIB bytes"}
        self.api.data = dict(before)
        send = Mock(side_effect=lambda: self.api.write({13: "selected"}))
        self.assertEqual(self.capture(send), "selected")
        self.assertEqual(self.api.data, before)
        send.assert_called_once()

    def test_no_copy_response_does_not_write_or_restore(self):
        send = Mock()
        self.assertEqual(self.capture(send), "")
        self.assertEqual(self.api.data, {13: "previous"})
        self.assertEqual(self.api.sequence, 1)
        self.assertEqual(self.api.restores, 0)

    def test_unknown_format_and_bitmap_handle_skip_copy(self):
        for format_id in (50001, 2):
            self.api.data = {format_id: b"opaque"}
            send = Mock()
            self.assertEqual(self.capture(send), "")
            send.assert_not_called()
            self.assertEqual(self.api.data, {format_id: b"opaque"})

    def test_change_from_another_app_is_not_captured_or_overwritten(self):
        self.assertEqual(self.capture(lambda: self.api.write({13: "user copy"}, owner=20)), "")
        self.assertEqual(self.api.data, {13: "user copy"})
        self.assertEqual(self.api.restores, 0)

    def test_user_copy_between_read_and_restore_is_preserved(self):
        original_get = self.api.GetClipboardData
        def get_data(format_id):
            value = original_get(format_id)
            if value == "selected":
                self.api.after_close = lambda: self.api.write({13: "new user copy"})
            return value
        self.api.GetClipboardData = get_data
        self.assertEqual(self.capture(lambda: self.api.write({13: "selected"})), "selected")
        self.assertEqual(self.api.data, {13: "new user copy"})
        self.assertEqual(self.api.restores, 0)

    def test_cancelled_request_does_not_send_copy(self):
        send = Mock()
        self.assertEqual(self.capture(send, is_current=lambda: False), "")
        send.assert_not_called()

    def test_explicit_clipboard_entry_is_read_only(self):
        self.assertEqual(self.service.read_text(), "previous")
        self.assertEqual(self.api.sequence, 1)

    def test_snapshot_reconstructs_file_drop_as_unicode_dropfiles(self):
        self.api.data = {15: ("C:\\first.txt", "C:\\second.txt")}
        result = self.service._snapshot()[0][1]
        self.assertEqual(result[:4], (20).to_bytes(4, "little"))
        self.assertEqual(result[20:].decode("utf-16-le"), "C:\\first.txt\0C:\\second.txt\0\0")
