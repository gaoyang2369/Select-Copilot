from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QFont, QTextCursor
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

    def test_markdown_formats_bold_and_wraps_long_code(self) -> None:
        toolbar = QWidget()
        popup = TranslationPopup()
        source = "**important**\n\n```python\n" + "very_long_identifier_" * 50 + "\n```"
        popup.show_message(source, toolbar, markdown=True)
        self.application.processEvents()
        self.assertIn("important", popup._text.toPlainText())
        self.assertNotIn("**important**", popup._text.toPlainText())
        cursor = QTextCursor(popup._text.document())
        cursor.setPosition(1)
        self.assertGreaterEqual(cursor.charFormat().fontWeight(), QFont.Weight.Bold)
        self.assertEqual(popup._text.horizontalScrollBar().maximum(), 0)
        self.assertEqual(popup._source, source)
        popup.close()

    def test_completion_preserves_position_and_readers_scroll(self) -> None:
        toolbar = QWidget()
        popup = TranslationPopup()
        popup.show_message("waiting", toolbar)
        source = "line\n\n" * 400
        popup.append_text(source, clear=True)
        self.application.processEvents()
        scrollbar = popup._text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum() // 3)
        position, scroll = popup.pos(), scrollbar.value()
        popup.show_message(source, toolbar, markdown=True)
        self.assertEqual(popup.pos(), position)
        self.assertEqual(scrollbar.value(), scroll)
        popup.close()
