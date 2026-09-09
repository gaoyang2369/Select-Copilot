"""Selection service exposed to the application."""

from __future__ import annotations

import logging
import threading
from typing import Callable

from core.clipboard import ClipboardService


logger = logging.getLogger(__name__)


class SelectionService:
    """Read the current text selection through the clipboard fallback."""

    def __init__(
        self,
        clipboard: ClipboardService,
        send_copy: Callable[[], None],
    ) -> None:
        self._clipboard = clipboard
        self._send_copy = send_copy
        self._capture_lock = threading.Lock()

    def get_selected_text(self) -> str:
        """Return selected text, or an empty string when no text can be read."""
        if not self._capture_lock.acquire(blocking=False):
            logger.debug("Ignoring a hotkey while another selection is being captured")
            return ""
        try:
            return self._clipboard.get_text_after_copy(self._send_copy)
        finally:
            self._capture_lock.release()
