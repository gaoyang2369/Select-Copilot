"""Popup for displaying a translation below the floating toolbar."""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QGuiApplication, QKeyEvent, QTextCursor
from PySide6.QtWidgets import QPlainTextEdit, QVBoxLayout, QWidget


class TranslationPopup(QWidget):
    """A lightweight, read-only popup positioned below the toolbar."""

    _GAP = 6
    _MAX_WIDTH = 380
    _MAX_HEIGHT = 240

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setObjectName("translationPopup")
        self.setStyleSheet(
            "#translationPopup { background: #303030; border: 1px solid #505050;"
            " border-radius: 8px; } QPlainTextEdit { color: white; background: transparent;"
            " border: 0; padding: 8px; }"
        )
        self._text = QPlainTextEdit(self)
        self._text.setReadOnly(True)
        self._text.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._text)

    def show_message(self, message: str, toolbar: QWidget) -> None:
        """Show ``message`` directly below ``toolbar`` within screen bounds."""
        self._text.setPlainText(message)
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
        scrollbar = self._text.verticalScrollBar()
        follow = scrollbar.value() >= scrollbar.maximum()
        cursor = QTextCursor(self._text.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text)
        if follow:
            scrollbar.setValue(scrollbar.maximum())

    def _resize_for_screen(self, toolbar: QWidget) -> None:
        screen = QGuiApplication.screenAt(toolbar.frameGeometry().center())
        screen = screen or QGuiApplication.primaryScreen()
        if screen is None:
            self.resize(self._MAX_WIDTH, self._MAX_HEIGHT)
            return

        available = screen.availableGeometry()
        self.resize(
            min(self._MAX_WIDTH, available.width()),
            min(self._MAX_HEIGHT, available.height()),
        )

    def _position_below(self, toolbar: QWidget) -> QPoint:
        anchor = toolbar.frameGeometry()
        screen = QGuiApplication.screenAt(anchor.center()) or QGuiApplication.primaryScreen()
        if screen is None:
            return anchor.bottomLeft() + QPoint(0, self._GAP)

        available = screen.availableGeometry()
        x = anchor.left()
        y = anchor.bottom() + self._GAP
        if y + self.height() > available.bottom():
            y = anchor.top() - self.height() - self._GAP

        x = max(available.left(), min(x, available.right() - self.width() + 1))
        y = max(available.top(), min(y, available.bottom() - self.height() + 1))
        return QPoint(x, y)
