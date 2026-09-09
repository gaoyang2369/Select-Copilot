from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget

from ui.translation_popup import TranslationPopup


class TranslationPopupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_long_result_uses_a_bounded_scrollable_popup(self) -> None:
        toolbar = QWidget()
        toolbar.resize(100, 30)
        popup = TranslationPopup()

        popup.show_message("long result " * 1000, toolbar)

        self.assertLessEqual(popup.width(), popup._MAX_WIDTH)
        self.assertLessEqual(popup.height(), popup._MAX_HEIGHT)
        self.assertIn("long result", popup._text.toPlainText())
        popup.close()
