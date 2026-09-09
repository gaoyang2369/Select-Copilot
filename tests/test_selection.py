from __future__ import annotations

import unittest
from unittest.mock import patch

from core.clipboard import ClipboardService
from core.selection import SelectionService


class FakeClipboard:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls = 0

    def get_text_after_copy(self, send_copy) -> str:
        self.calls += 1
        send_copy()
        return self.text


class SelectionServiceTests(unittest.TestCase):
    def test_returns_text_from_clipboard_fallback(self) -> None:
        clipboard = FakeClipboard("Wasserstein distance")
        copy_calls = 0

        def send_copy() -> None:
            nonlocal copy_calls
            copy_calls += 1

        service = SelectionService(clipboard, send_copy)

        self.assertEqual(service.get_selected_text(), "Wasserstein distance")
        self.assertEqual(clipboard.calls, 1)
        self.assertEqual(copy_calls, 1)

    def test_returns_empty_string_when_clipboard_has_no_selection(self) -> None:
        service = SelectionService(FakeClipboard(""), lambda: None)

        self.assertEqual(service.get_selected_text(), "")


class ClipboardServiceTests(unittest.TestCase):
    def test_reads_new_text_and_restores_plain_text_clipboard(self) -> None:
        clipboard_text = "previous text"

        def paste() -> str:
            return clipboard_text

        def copy(text: str) -> None:
            nonlocal clipboard_text
            clipboard_text = text

        def send_copy() -> None:
            copy("selected text")

        service = ClipboardService()
        with patch("core.clipboard.pyperclip.paste", paste), patch(
            "core.clipboard.pyperclip.copy", copy
        ):
            self.assertEqual(service.get_text_after_copy(send_copy), "selected text")

        self.assertEqual(clipboard_text, "previous text")

    def test_returns_empty_text_when_copy_does_not_replace_sentinel(self) -> None:
        clipboard_text = "previous text"

        def paste() -> str:
            return clipboard_text

        def copy(text: str) -> None:
            nonlocal clipboard_text
            clipboard_text = text

        service = ClipboardService(copy_wait_seconds=0)
        with patch("core.clipboard.pyperclip.paste", paste), patch(
            "core.clipboard.pyperclip.copy", copy
        ):
            self.assertEqual(service.get_text_after_copy(lambda: None), "")

        self.assertEqual(clipboard_text, "previous text")


if __name__ == "__main__":
    unittest.main()
