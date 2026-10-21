"""Popup for displaying a translation below the floating toolbar."""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QKeyEvent, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from ui.text_view import TextView
from ui.theme import apply_theme, available_geometry, bounded_position


class TranslationPopup(QFrame):
    """A lightweight, read-only popup positioned below the toolbar."""

    _GAP = 6
    _MAX_WIDTH = 480
    _MAX_HEIGHT = 360

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setObjectName("translationPopup")
        apply_theme(self)
        self._source = ""
        self._heading = QLabel("翻译", self)
        self._heading.setObjectName("windowHeading")
        self._copy_button = QPushButton("复制", self)
        self._copy_button.setToolTip("复制完整的原始结果")
        self._copy_button.clicked.connect(self._copy_result)
        close_button = QPushButton("关闭", self)
        close_button.setToolTip("关闭结果（Esc）")
        close_button.clicked.connect(self.hide)
        header = QHBoxLayout()
        header.addWidget(self._heading)
        header.addStretch()
        header.addWidget(self._copy_button)
        header.addWidget(close_button)
        self._text = TextView(self)
        self._text.setObjectName("resultText")
        self._text.setAccessibleName("结果正文")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 12)
        layout.setSpacing(6)
        layout.addLayout(header)
        layout.addWidget(self._text, 1)

    def set_heading(self, title: str) -> None:
        self._heading.setText(title)

    def _copy_result(self) -> None:
        QApplication.clipboard().setText(self._source)

    def show_message(self, message: str, toolbar: QWidget, *, markdown: bool = False) -> None:
        """Show ``message`` directly below ``toolbar`` within screen bounds."""
        self._source = message
        scrollbar = self._text.verticalScrollBar()
        position = scrollbar.value()
        follow = position >= scrollbar.maximum()
        self._text.show_body(message, markdown=markdown)
        if self.isVisible():
            scrollbar.setValue(scrollbar.maximum() if follow else position)
        # Completion changes only the document; preserve the streaming window's
        # position and the reader's scroll position rather than raising it again.
        if not self.isVisible():
            self._resize_for_screen(toolbar)
            self.move(self._position_below(toolbar))
            self.show()
            self.raise_()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Allow Escape to dismiss a result popup that has focus."""
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            event.accept()
            return
        super().keyPressEvent(event)

    def append_text(self, text: str, *, clear: bool = False) -> None:
        """Append stream text without moving, raising or rebuilding the window."""
        if clear:
            self._text.clear()
            self._source = ""
        self._source += text
        scrollbar = self._text.verticalScrollBar()
        follow = scrollbar.value() >= scrollbar.maximum()
        cursor = QTextCursor(self._text.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self._text.insert_body(cursor, text)
        if follow:
            scrollbar.setValue(scrollbar.maximum())

    def _resize_for_screen(self, toolbar: QWidget) -> None:
        anchor = toolbar.frameGeometry()
        available = available_geometry(anchor.center())
        above = anchor.top() - available.top() - self._GAP
        below = available.bottom() - anchor.bottom() - self._GAP
        self.resize(
            min(self._MAX_WIDTH, available.width()),
            min(self._MAX_HEIGHT, available.height(), max(120, above, below)),
        )

    def _position_below(self, toolbar: QWidget) -> QPoint:
        anchor = toolbar.frameGeometry()
        available = available_geometry(anchor.center())
        x = anchor.left()
        y = anchor.bottom() + self._GAP
        if y + self.height() > available.bottom():
            y = anchor.top() - self.height() - self._GAP

        return bounded_position(QPoint(x, y), self.size(), available)
