"""Small, temporary multi-turn chat window for one text selection."""

from __future__ import annotations

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from services.chat import ChatSession
from services.llm import LLMService
from ui.workers import AsyncTextWorker


class ChatWindow(QWidget):
    """Show context and retain a conversation only for this window's lifetime."""

    def __init__(self, selection: str, llm_service: LLMService) -> None:
        super().__init__()
        self._session = ChatSession(selection, llm_service)
        self._worker: AsyncTextWorker | None = None
        self._reply_start = 0
        self._reply_started = False
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle("Selection Copilot Chat")
        self.resize(460, 420)

        context_label = QLabel("Quoted context:", self)
        context_label.setStyleSheet("color: #555; padding: 4px;")
        self._context = QPlainTextEdit(self)
        self._context.setPlainText(selection)
        self._context.setReadOnly(True)
        self._context.setFixedHeight(72)

        self._messages = QTextEdit(self)
        self._messages.setReadOnly(True)
        self._messages.setPlaceholderText("Ask a question about the selected text.")

        self._input = QPlainTextEdit(self)
        self._input.setPlaceholderText("Ask about the selected text...")
        self._input.setFixedHeight(64)
        self._send_button = QPushButton("Send", self)
        self._send_button.clicked.connect(self._send_message)

        input_layout = QHBoxLayout()
        input_layout.addWidget(self._input)
        input_layout.addWidget(self._send_button)
        layout = QVBoxLayout(self)
        layout.addWidget(context_label)
        layout.addWidget(self._context)
        layout.addWidget(self._messages)
        layout.addLayout(input_layout)

    def _send_message(self) -> None:
        user_message = self._input.toPlainText().strip()
        if not user_message or self._worker is not None:
            return

        self._append_message("You", user_message)
        self._reply_start = self._messages.document().characterCount() - 1
        self._reply_started = False
        self._append_message("AI", "Waiting for reply...")
        self._input.clear()
        self._input.setEnabled(False)
        self._send_button.setEnabled(False)
        worker = AsyncTextWorker(streaming_operation=lambda emit: self._session.send(user_message, on_delta=emit))
        self._worker = worker
        worker.progress.connect(self._append_reply)
        worker.completed.connect(self._show_reply)
        worker.failed.connect(self._show_error)
        worker.finished.connect(self._finish_request)
        worker.start()

    @Slot(str)
    def _show_reply(self, reply: str) -> None:
        self._replace_reply(f"AI:\n{reply}\n\n")
        self._worker.mark_displayed()

    def _replace_reply(self, text: str) -> None:
        scrollbar = self._messages.verticalScrollBar()
        position = scrollbar.value()
        follow = position >= scrollbar.maximum()
        cursor = QTextCursor(self._messages.document())
        cursor.setPosition(self._reply_start)
        cursor.movePosition(QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(text)
        scrollbar.setValue(scrollbar.maximum() if follow else position)

    @Slot(str)
    def _append_reply(self, text: str) -> None:
        if not self._reply_started:
            self._replace_reply("AI:\n")
            self._reply_started = True
        scrollbar = self._messages.verticalScrollBar()
        follow = scrollbar.value() >= scrollbar.maximum()
        cursor = QTextCursor(self._messages.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text)
        if follow:
            scrollbar.setValue(scrollbar.maximum())
        self._worker.mark_displayed()

    @Slot(str)
    def _show_error(self, error: str) -> None:
        self._replace_reply(f"Error:\nChat request failed: {error}\n\n")

    @Slot()
    def _finish_request(self) -> None:
        worker = self._worker
        if worker is not None:
            self._worker = None
            self._input.setEnabled(True)
            self._send_button.setEnabled(True)
            self._input.setFocus()
            worker.deleteLater()

    def _append_message(self, author: str, content: str) -> None:
        cursor = self._messages.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(f"{author}:\n{content}\n\n")
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
