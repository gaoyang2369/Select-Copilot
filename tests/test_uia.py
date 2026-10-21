from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from core.uia import SelectionResult, UIA, UIASelectionReader


def element(parent=None, pattern=None):
    value = Mock()
    value.parent = parent
    value.CurrentIsPassword = False
    value.GetCurrentPattern.return_value = pattern
    return value


def pattern_for(*texts):
    pattern = Mock()
    pattern.SupportedTextSelection = 1
    ranges = pattern.GetSelection.return_value
    ranges.Length = len(texts)
    values = []
    for text in texts:
        value = Mock()
        value.GetText.return_value = text
        value.GetBoundingRectangles.return_value = (10, 20, 100, 15)
        values.append(value)
    ranges.GetElement.side_effect = values
    unknown = Mock()
    unknown.QueryInterface.return_value = pattern
    return unknown


class UIASelectionTests(unittest.TestCase):
    def setUp(self):
        self.reader = UIASelectionReader()
        self.root = element()
        self.focus = element(self.root)
        self.automation = Mock()
        self.automation.ElementFromHandle.return_value = self.root
        self.automation.GetFocusedElement.return_value = self.focus
        self.automation.CompareElements.side_effect = lambda left, right: left is right
        self.automation.RawViewWalker.GetParentElement.side_effect = lambda value: value.parent
        patcher = patch("core.uia.CreateObject", return_value=self.automation)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_only_selected_ranges_are_read_and_position_is_returned(self):
        self.focus.GetCurrentPattern.return_value = pattern_for("first", "second")
        result = self.reader._read(10, None)
        self.assertEqual(result, SelectionResult("selected", "first\nsecond", (110, 35)))
        self.assertFalse(self.automation.AutoSetFocus)
        self.assertEqual(self.automation.TransactionTimeout, 200)

    def test_empty_caret_is_not_the_entire_document(self):
        unknown = pattern_for("")
        self.focus.GetCurrentPattern.return_value = unknown
        self.assertEqual(self.reader._read(10, None).status, "empty")
        pattern = unknown.QueryInterface.return_value
        pattern.DocumentRange.GetText.assert_not_called()

    def test_ancestor_document_is_checked_when_focused_container_is_unsupported(self):
        self.root.GetCurrentPattern.return_value = pattern_for("parent selection")
        self.assertEqual(self.reader._read(10, None).text, "parent selection")

    def test_point_provider_is_checked_even_if_focus_has_an_empty_selection(self):
        self.focus.GetCurrentPattern.return_value = pattern_for("")
        point = element(self.root, pattern_for("mouse selection"))
        self.automation.ElementFromPoint.return_value = point
        self.assertEqual(self.reader._read(10, (30, 40)).text, "mouse selection")

    def test_focused_selection_outside_source_window_is_ignored(self):
        other_root = element()
        self.focus.parent = other_root
        self.focus.GetCurrentPattern.return_value = pattern_for("wrong window")
        self.assertEqual(self.reader._read(10, None).status, "unsupported")
        self.focus.GetCurrentPattern.assert_not_called()

    def test_password_control_is_blocked(self):
        self.focus.CurrentIsPassword = True
        self.assertEqual(self.reader._read(10, None).status, "blocked")
        self.focus.GetCurrentPattern.assert_not_called()

    def test_scrollbar_does_not_recapture_old_document_selection(self):
        self.focus.GetCurrentPattern.return_value = pattern_for("old selection")
        scrollbar = element(self.root)
        scrollbar.CurrentControlType = UIA.UIA_ScrollBarControlTypeId
        self.automation.ElementFromPoint.return_value = scrollbar
        self.assertEqual(self.reader._read(10, (20, 20)).status, "blocked")
        self.focus.GetCurrentPattern.assert_not_called()

    def test_parent_walk_is_bounded(self):
        self.focus.parent = self.focus
        self.assertEqual(self.reader._read(10, None).status, "unsupported")
        self.assertEqual(self.automation.RawViewWalker.GetParentElement.call_count, 16)

    def test_worker_initializes_and_uninitializes_mta_even_on_error(self):
        with patch("core.uia.comtypes.CoInitializeEx") as initialize, \
                patch("core.uia.comtypes.CoUninitialize") as uninitialize, \
                patch.object(self.reader, "_read", side_effect=OSError()):
            self.assertEqual(self.reader.read(10).status, "error")
            initialize.assert_called_once_with(0)
            uninitialize.assert_called_once()
