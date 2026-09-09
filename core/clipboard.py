"""Simple clipboard fallback for reading the current text selection."""

from __future__ import annotations

import logging
import time
import uuid
from typing import Callable

import pyperclip


logger = logging.getLogger(__name__)


class ClipboardService:
    """Use Ctrl+C and a temporary sentinel to retrieve selected plain text."""

    def __init__(self, copy_wait_seconds: float = 0.5, poll_seconds: float = 0.01) -> None:
        self.copy_wait_seconds = copy_wait_seconds
        self.poll_seconds = poll_seconds

    def get_text_after_copy(self, send_copy: Callable[[], None]) -> str:
        """Copy selected text, then restore the previous plain-text clipboard value."""
        try:
            previous_text = pyperclip.paste()
            sentinel = f"__selection_copilot_{uuid.uuid4()}__"
            pyperclip.copy(sentinel)
        except pyperclip.PyperclipException as error:
            logger.warning("Could not access the clipboard: %s", error)
            return ""

        try:
            send_copy()
            deadline = time.monotonic() + self.copy_wait_seconds
            while time.monotonic() < deadline:
                copied_text = pyperclip.paste()
                if copied_text != sentinel:
                    return copied_text
                time.sleep(self.poll_seconds)
            return ""
        except pyperclip.PyperclipException as error:
            logger.warning("Could not read copied text: %s", error)
            return ""
        finally:
            try:
                pyperclip.copy(previous_text)
            except pyperclip.PyperclipException as error:
                logger.error("Could not restore the clipboard: %s", error)
