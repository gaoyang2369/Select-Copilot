import unittest
from unittest.mock import Mock, patch

from core.powerpoint import PowerPointSelectionReader


class PowerPointTests(unittest.TestCase):
    def setUp(self):
        self.application = Mock()
        self.document = self.application.ActiveWindow
        self.document.HWND = 10
        self.document.Selection.Type = 3
        self.document.Selection.TextRange.Length = 4
        self.document.Selection.TextRange.Text = "word"
        self.reader = PowerPointSelectionReader()
        active = patch("core.powerpoint.GetActiveObject", return_value=self.application)
        ancestor = patch("core.powerpoint.win32gui.GetAncestor", side_effect=lambda handle, _: handle)
        active.start()
        ancestor.start()
        self.addCleanup(active.stop)
        self.addCleanup(ancestor.stop)

    def test_only_actual_selected_text_is_read(self):
        result = self.reader.read(10)
        self.assertEqual((result.status, result.text, result.method), ("selected", "word", "powerpoint"))

    def test_shape_and_slide_selection_never_become_whole_text(self):
        for kind in (0, 1, 2):
            self.document.Selection.Type = kind
            self.assertEqual(self.reader.read(10).status, "empty")
        self.document.Selection.ShapeRange.assert_not_called()

    def test_other_presentation_window_is_not_used(self):
        self.assertEqual(self.reader.read(20).reason, "office_window_mismatch")

    def test_caret_is_empty_even_if_office_returns_text(self):
        self.document.Selection.TextRange.Length = 0
        self.assertEqual(self.reader.read(10).text, "")

    def test_dynamic_office_dispatch_exposes_hwnd_as_method(self):
        self.document.HWND = Mock(return_value=10)
        self.assertEqual(self.reader.read(10).text, "word")

    def test_office_without_hwnd_requires_unambiguous_caption(self):
        self.document.HWND = Mock(side_effect=AttributeError())
        self.document.Active = True
        self.document.Caption = "fixture.pptx"
        with patch("core.powerpoint.win32gui.GetClassName", return_value="PPTFrameClass"), \
                patch("core.powerpoint.win32gui.GetWindowText", return_value="fixture.pptx - PowerPoint"), \
                patch("core.powerpoint.win32gui.EnumWindows", side_effect=lambda callback, data: callback(10, data)):
            self.assertEqual(self.reader.read(10).text, "word")
        with patch("core.powerpoint.win32gui.GetClassName", return_value="PPTFrameClass"), \
                patch("core.powerpoint.win32gui.GetWindowText", return_value="fixture.pptx - PowerPoint"), \
                patch("core.powerpoint.win32gui.EnumWindows", side_effect=lambda callback, data: [callback(h, data) for h in (10, 20)]):
            self.assertEqual(self.reader.read(10).status, "unsupported")
