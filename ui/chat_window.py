"""Small, temporary multi-turn chat window for one text selection."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QSize, Qt, Slot
from PySide6.QtGui import QCursor, QTextCursor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from services.chat import ChatSession
from services.llm import LLMService
from ui.text_view import TextView
from ui.theme import apply_theme, fit_window
from ui.workers import AsyncTextWorker


class ChatWindow(QWidget):
    """Show context and retain a conversation only for this window's lifetime."""

    def __init__(self, selection: str, llm_service: LLMService) -> None:
        super().__init__()
        self._session = ChatSession(selection, llm_service)
        self._worker: AsyncTextWorker | None = None
        self._reply_start = 0
        self._reply_started = False
        self._first_show = True
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle("Selection Copilot Chat")
        self.setObjectName("chatWindow")
        apply_theme(self)

        heading = QLabel("Selection Copilot", self)
        heading.setObjectName("windowHeading")
        title_font = heading.font()
        title_font.setPointSizeF(13)
        heading.setFont(title_font)
        self._context_toggle = QToolButton(self)
        self._context_toggle.setObjectName("contextToggle")
        self._context_toggle.setText("引用的选区")
        self._context_toggle.setCheckable(True)
        self._context_toggle.setChecked(True)
        self._context_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._context_toggle.setArrowType(Qt.ArrowType.DownArrow)
        self._context_toggle.setToolTip("展开或收起引用；拖动下方分隔条调整高度")
        self._context_toggle.toggled.connect(self._toggle_context)
        self._context = QPlainTextEdit(self)
        self._context.setPlainText(selection)
        self._context.setReadOnly(True)
        self._context.setAccessibleName("引用的选区")
        self._context.setMinimumHeight(self.fontMetrics().lineSpacing() * 2 + 20)

        self._messages = TextView(self)
        self._messages.setObjectName("conversation")
        self._messages.setAccessibleName("对话记录")
        self._messages.setMinimumHeight(60)
        self._messages.setPlaceholderText("选区已引用。输入问题，开始对话。")
        self._splitter = QSplitter(Qt.Orientation.Vertical, self)
        self._splitter.setChildrenCollapsible(False)
        self._splitter.addWidget(self._context)
        self._splitter.addWidget(self._messages)
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setSizes([100, 360])

        self._input = QPlainTextEdit(self)
        self._input.setAccessibleName("问题输入框")
        self._input.setPlaceholderText("围绕选中文字提问…")
        self._input.installEventFilter(self)
        self._input.textChanged.connect(self._update_composer)
        self._send_button = QPushButton("发送", self)
        self._send_button.setProperty("primary", True)
        self._send_button.setToolTip("发送问题（Ctrl+Enter）")
        self._send_button.clicked.connect(self._send_message)
        self._status = QLabel("Enter 换行 · Ctrl+Enter 发送", self)
        self._status.setProperty("muted", True)

        input_layout = QHBoxLayout()
        input_layout.addWidget(self._status, 1)
        input_layout.addWidget(self._send_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)
        layout.addWidget(heading)
        layout.addWidget(self._context_toggle, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self._splitter, 1)
        layout.addWidget(self._input)
        layout.addLayout(input_layout)
        self._update_composer()
        fit_window(self, QCursor.pos(), QSize(660, 720))

    def showEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().showEvent(event)
        if self._first_show:
            self._first_show = False
            # Frame margins are available after creating the native window.
            fit_window(self, QCursor.pos(), QSize(660, 720))
            if self.height() < 560:
                self._context_toggle.setChecked(False)
            self.windowHandle().screenChanged.connect(self._fit_to_screen)
            self._input.setFocus()

    def _fit_to_screen(self, screen) -> None:  # type: ignore[no-untyped-def]
        fit_window(self, self.frameGeometry().center(), self.size(), available=screen.availableGeometry())
        self._update_composer()

    def _toggle_context(self, expanded: bool) -> None:
        self._context.setVisible(expanded)
        self._context_toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)

    def _update_composer(self) -> None:
        # Font-relative height avoids clipping when DPI or system text size grows.
        lines = min(5, max(2, self._input.document().blockCount()))
        self._input.setFixedHeight(self.fontMetrics().lineSpacing() * lines + 24)
        self._send_button.setEnabled(bool(self._input.toPlainText().strip()) and self._worker is None)

    def eventFilter(self, watched, event) -> bool:  # type: ignore[no-untyped-def]
        if watched is self._input and event.type() == QEvent.Type.KeyPress:
            if (
                event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
                and event.modifiers() & Qt.KeyboardModifier.ControlModifier
            ):
                self._send_message()
                return True
        return super().eventFilter(watched, event)

    def _send_message(self) -> None:
        user_message = self._input.toPlainText().strip()
        if not user_message or self._worker is not None:
            return

        self._append_message("You", user_message)
        self._reply_start = self._messages.document().characterCount() - 1
        self._reply_started = False
        self._append_message("AI", "正在等待回复…")
        self._input.clear()
        self._input.setEnabled(False)
        self._send_button.setEnabled(False)
        self._status.setText("正在生成回复…")
        worker = AsyncTextWorker(streaming_operation=lambda emit: self._session.send(user_message, on_delta=emit))
        self._worker = worker
        worker.progress.connect(self._append_reply)
        worker.completed.connect(self._show_reply)
        worker.failed.connect(self._show_error)
        worker.finished.connect(self._finish_request)
        worker.start()

    @Slot(str)
    def _show_reply(self, reply: str) -> None:
        self._replace_reply(reply, markdown=True)
        self._worker.mark_displayed()

    def _replace_reply(self, text: str, *, author: str = "AI", markdown: bool = False) -> None:
        scrollbar = self._messages.verticalScrollBar()
        position = scrollbar.value()
        follow = position >= scrollbar.maximum()
        cursor = QTextCursor(self._messages.document())
        cursor.setPosition(self._reply_start)
        cursor.movePosition(QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor)
        cursor.removeSelectedText()
        self._messages.insert_message(cursor, author, text, markdown=markdown)
        scrollbar.setValue(scrollbar.maximum() if follow else position)

    @Slot(str)
    def _append_reply(self, text: str) -> None:
        if not self._reply_started:
            self._replace_reply("")
            self._reply_started = True
        scrollbar = self._messages.verticalScrollBar()
        follow = scrollbar.value() >= scrollbar.maximum()
        cursor = QTextCursor(self._messages.document())
        # Keep the separator paragraph after the streaming body.
        cursor.setPosition(self._messages.document().characterCount() - 2)
        self._messages.insert_body(cursor, text)
        if follow:
            scrollbar.setValue(scrollbar.maximum())
        self._worker.mark_displayed()

    @Slot(str)
    def _show_error(self, error: str) -> None:
        self._replace_reply(f"请求失败：{error}", author="Error")
        self._status.setText("请求失败，可重新提问")

    @Slot()
    def _finish_request(self) -> None:
        worker = self._worker
        if worker is not None:
            self._worker = None
            self._input.setEnabled(True)
            self._update_composer()
            self._status.setText("Enter 换行 · Ctrl+Enter 发送")
            self._input.setFocus()
            worker.deleteLater()

    def _append_message(self, author: str, content: str) -> None:
        cursor = self._messages.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self._messages.insert_message(cursor, author, content)
        self._messages.setTextCursor(cursor)
        self._messages.ensureCursorVisible()

    def shutdown(self) -> None:
        """Finish cancellation before this window's worker can be destroyed."""
        if self._worker is not None:
            self._worker.cancel()
            self._worker.wait()

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self.shutdown()
        super().closeEvent(event)
