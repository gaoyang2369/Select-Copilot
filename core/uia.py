"""Read actual text ranges without changing focus, selection or the clipboard."""

from __future__ import annotations

from dataclasses import dataclass
import time

import comtypes
from comtypes.client import CreateObject, GetModule

try:
    from comtypes.gen import UIAutomationClient as UIA
except ImportError:
    UIA = GetModule("UIAutomationCore.dll")


@dataclass(frozen=True)
class SelectionResult:
    status: str  # selected, empty, unsupported, blocked, error, timeout, cancelled
    text: str = ""
    position: tuple[int, int] | None = None  # Native physical screen coordinates.
    method: str = "uia"


class UIASelectionReader:
    """COM objects live entirely inside the capture thread's MTA apartment."""

    def read(self, window: int, position: tuple[int, int] | None = None) -> SelectionResult:
        comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
        try:
            return self._read(window, position)
        except (comtypes.COMError, OSError, ValueError):
            return SelectionResult("error")
        finally:
            comtypes.CoUninitialize()

    def _read(self, window: int, position: tuple[int, int] | None) -> SelectionResult:
        automation = CreateObject(UIA.CUIAutomation8, interface=UIA.IUIAutomation2)
        automation.ConnectionTimeout = 200
        automation.TransactionTimeout = 200
        automation.AutoSetFocus = False
        root = automation.ElementFromHandle(window)
        if not root:
            return SelectionResult("unsupported")
        walker = automation.RawViewWalker
        deadline = time.monotonic() + 0.4
        starts = []
        if position is not None:
            pointed = automation.ElementFromPoint(UIA.tagPOINT(*position))
            if pointed and pointed.CurrentControlType in (
                UIA.UIA_ScrollBarControlTypeId, UIA.UIA_SliderControlTypeId,
                UIA.UIA_ThumbControlTypeId, UIA.UIA_TitleBarControlTypeId,
                UIA.UIA_ButtonControlTypeId, UIA.UIA_MenuItemControlTypeId,
            ):
                return SelectionResult("blocked")
            starts.append(pointed)
        starts.append(automation.GetFocusedElement())
        empty = False
        failed = False
        for start in starts:
            # Validate ancestry before using text: focus may be in another window
            # of the same process. Never search descendants of the desktop.
            chain = []
            element = start
            for _ in range(16):
                if time.monotonic() >= deadline:
                    return SelectionResult("timeout")
                if not element:
                    break
                chain.append(element)
                if automation.CompareElements(element, root):
                    break
                element = walker.GetParentElement(element)
            else:
                continue
            if not chain or not automation.CompareElements(chain[-1], root):
                continue
            for element in chain:
                if time.monotonic() >= deadline:
                    return SelectionResult("timeout")
                if element.CurrentIsPassword:
                    return SelectionResult("blocked")
                try:
                    result = self._read_element(element)
                except comtypes.COMError as error:
                    if error.hresult & 0xFFFFFFFF not in (0x80040204, 0x80004002):
                        failed = True
                    continue
                if result.status == "selected":
                    return result
                empty |= result.status == "empty"
        return SelectionResult("empty" if empty else "error" if failed else "unsupported")

    @staticmethod
    def _read_element(element) -> SelectionResult:
        unknown = element.GetCurrentPattern(UIA.UIA_TextPatternId)
        if not unknown:
            return SelectionResult("unsupported")
        pattern = unknown.QueryInterface(UIA.IUIAutomationTextPattern)
        if pattern.SupportedTextSelection == UIA.SupportedTextSelection_None:
            return SelectionResult("unsupported")
        ranges = pattern.GetSelection()
        if not ranges:
            return SelectionResult("empty")
        texts = []
        position = None
        remaining = 100_000
        for index in range(min(ranges.Length, 64)):
            text_range = ranges.GetElement(index)
            text = text_range.GetText(remaining)
            if text:
                texts.append(text)
                remaining -= len(text)
                try:
                    rectangles = text_range.GetBoundingRectangles()
                    if rectangles and len(rectangles) >= 4:
                        x, y, width, height = rectangles[-4:]
                        if width > 0 and height > 0:
                            position = (round(x + width), round(y + height))
                except comtypes.COMError:
                    pass
            if remaining <= 0:
                break
        text = "\n".join(texts)
        return SelectionResult("selected" if text.strip() else "empty", text, position)
