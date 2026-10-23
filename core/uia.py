"""Read actual text ranges without changing focus, selection or the clipboard."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
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
    reason: str = field(default="", compare=False)
    control_type: int = field(default=0, compare=False)
    rectangles: tuple = field(default=(), compare=False, repr=False)


class UIASelectionReader:
    """COM objects live entirely inside the capture thread's MTA apartment."""

    def __init__(self, automation=None) -> None:
        self.automation = automation

    @staticmethod
    def create_automation():
        automation = CreateObject(UIA.CUIAutomation8, interface=UIA.IUIAutomation2)
        automation.ConnectionTimeout = 200
        automation.TransactionTimeout = 200
        automation.AutoSetFocus = False
        return automation

    def read(self, window: int, position: tuple[int, int] | None = None,
             origin: tuple[int, int] | None = None) -> SelectionResult:
        comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
        try:
            return self._read(window, position, origin)
        except (comtypes.COMError, OSError, ValueError):
            return SelectionResult("error", reason="uia_call_failed")
        finally:
            comtypes.CoUninitialize()

    def _read(self, window: int, position: tuple[int, int] | None,
              origin: tuple[int, int] | None = None) -> SelectionResult:
        automation = self.automation or self.create_automation()
        root = automation.ElementFromHandle(window)
        if not root:
            return SelectionResult("unsupported", reason="window_unavailable")
        walker = automation.RawViewWalker
        deadline = time.monotonic() + 0.4
        anchor = origin or position
        pointed = automation.ElementFromPoint(UIA.tagPOINT(*anchor)) if anchor else None
        # Classify the gesture's START, not its release over an unrelated button.
        if pointed and pointed.CurrentControlType in (
                UIA.UIA_ScrollBarControlTypeId, UIA.UIA_SliderControlTypeId,
                UIA.UIA_ThumbControlTypeId, UIA.UIA_TitleBarControlTypeId,
                UIA.UIA_ButtonControlTypeId, UIA.UIA_MenuItemControlTypeId,
        ):
            return SelectionResult("blocked", reason="non_text_gesture")
        focused = automation.GetFocusedElement()
        starts = [pointed] if anchor else []
        if origin and position and origin != position:
            starts.append(automation.ElementFromPoint(UIA.tagPOINT(*position)))
        starts.append(focused)
        primary_empty = False
        failed = False
        primary_chain = []
        visited = []
        for source_index, start in enumerate(starts):
            # Validate ancestry before using text: focus may be in another window
            # of the same process. Never search descendants of the desktop.
            chain = []
            element = start
            for _ in range(128):
                if time.monotonic() >= deadline:
                    return SelectionResult("timeout", reason="ancestry_budget")
                if not element:
                    break
                if any(automation.CompareElements(element, previous) for previous in chain):
                    break
                chain.append(element)
                if automation.CompareElements(element, root):
                    break
                element = walker.GetParentElement(element)
            else:
                return SelectionResult("timeout", reason="ancestry_limit")
            if not chain or not automation.CompareElements(chain[-1], root):
                continue
            if any(element.CurrentIsPassword for element in chain):
                return SelectionResult("blocked", reason="password")
            if source_index == 0:
                primary_chain = chain
            for element in chain:
                if time.monotonic() >= deadline:
                    return SelectionResult("timeout", reason="provider_budget")
                if any(automation.CompareElements(element, old) for old in visited):
                    continue
                visited.append(element)
                try:
                    result = self._read_element(element)
                except comtypes.COMError as error:
                    if error.hresult & 0xFFFFFFFF not in (0x80040204, 0x80004002):
                        failed = True
                    continue
                if result.status == "selected":
                    related = (not anchor or source_index == 0
                               or any(automation.CompareElements(element, p) for p in primary_chain)
                               or self._contains_selection(result, anchor)
                               or (position and self._contains_selection(result, position)))
                    if related:
                        return replace(result, reason="target_selection")
                # An empty, unrelated focused editor says nothing about the mouse target.
                if source_index == 0:
                    primary_empty |= result.status == "empty"

        # Providers can be descendants of the hit-tested pane (Office/web content).
        # Search only the visible branch containing the gesture, never the desktop.
        if anchor and primary_chain:
            queue = [primary_chain[0]]
            inspected = 0
            while queue and inspected < 96:
                if time.monotonic() >= deadline:
                    return SelectionResult("timeout", reason="subtree_budget")
                element = queue.pop(0)
                inspected += 1
                if element.CurrentIsPassword:
                    return SelectionResult("blocked", reason="password")
                if not any(automation.CompareElements(element, old) for old in visited):
                    visited.append(element)
                    try:
                        result = self._read_element(element)
                        if result.status == "selected":
                            return replace(result, reason="local_subtree_selection")
                        primary_empty |= result.status == "empty"
                    except comtypes.COMError:
                        failed = True
                child = walker.GetFirstChildElement(element)
                siblings = 0
                while child and siblings < 96 and len(queue) < 96:
                    if time.monotonic() >= deadline:
                        return SelectionResult("timeout", reason="subtree_budget")
                    siblings += 1
                    rect = child.CurrentBoundingRectangle
                    if (not child.CurrentIsOffscreen and rect.left <= anchor[0] <= rect.right
                            and rect.top <= anchor[1] <= rect.bottom):
                        queue.append(child)
                    child = walker.GetNextSiblingElement(child)
                if child:
                    return SelectionResult("timeout", reason="subtree_limit")
            if queue:
                return SelectionResult("timeout", reason="subtree_limit")
        status = "error" if failed else "empty" if primary_empty else "unsupported"
        return SelectionResult(status, reason={"error": "provider_failed", "empty": "target_empty",
                                               "unsupported": "target_provider_missing"}[status])

    @staticmethod
    def _contains_selection(result: SelectionResult, point: tuple[int, int]) -> bool:
        return any(x - 3 <= point[0] <= x + w + 3 and y - 3 <= point[1] <= y + h + 3
                   for x, y, w, h in result.rectangles)

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
        bounds = []
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
                        bounds.extend(tuple(rectangles[i:i + 4])
                                      for i in range(0, min(len(rectangles), 4096) - 3, 4))
                        x, y, width, height = rectangles[-4:]
                        if width > 0 and height > 0:
                            position = (round(x + width), round(y + height))
                except comtypes.COMError:
                    pass
            if remaining <= 0:
                break
        text = "\n".join(texts)
        return SelectionResult("selected" if text.strip() else "empty", text, position,
                               rectangles=tuple(bounds))
