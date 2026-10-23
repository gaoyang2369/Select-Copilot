"""Read PowerPoint's actual text selection, never the selected shape's contents."""

from __future__ import annotations

import pywintypes
import win32gui
from win32com.client import GetActiveObject

from core.uia import SelectionResult


class PowerPointSelectionReader:
    @staticmethod
    def _matches_window(document, window: int) -> bool:
        try:
            value = document.HWND
            handle = int(value() if callable(value) else value) & 0xFFFFFFFF
            return (win32gui.GetAncestor(handle, 2) or handle) == window
        except (pywintypes.com_error, AttributeError, TypeError):
            # Some Office typelibs advertise HWND but the server rejects it.
            # Bind only an active document with a unique, exact window caption.
            # Never pick a different presentation merely because its PID matches.
            if not document.Active or win32gui.GetClassName(window) != "PPTFrameClass":
                return False
            caption = document.Caption
            title = win32gui.GetWindowText(window)
            if not caption or not (title == caption or title.startswith(caption + " - ")):
                return False
            matches = []

            def inspect(handle, _):
                if (win32gui.GetClassName(handle) == "PPTFrameClass"
                        and win32gui.GetWindowText(handle) == title):
                    matches.append(handle)

            win32gui.EnumWindows(inspect, None)
            return matches == [window]

    def read(self, window: int) -> SelectionResult:
        try:
            application = GetActiveObject("PowerPoint.Application")
            document = application.ActiveWindow
            if not self._matches_window(document, window):
                return SelectionResult("unsupported", method="powerpoint", reason="office_window_mismatch")
            selection = document.Selection
            if selection.Type != 3:  # ppSelectionText, not shapes or slides
                return SelectionResult("empty", method="powerpoint", reason="office_not_text_selection")
            text_range = selection.TextRange
            text = text_range.Text[:100_000] if text_range.Length > 0 else ""
            return SelectionResult("selected" if text.strip() else "empty", text,
                                   method="powerpoint", reason="office_text_selection")
        except (pywintypes.com_error, pywintypes.error, AttributeError, OSError):
            return SelectionResult("unsupported", method="powerpoint", reason="office_unavailable")
