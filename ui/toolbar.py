"""A small toolbar shown next to the mouse after text is selected."""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from PySide6.QtCore import QPoint, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QCursor, QKeyEvent
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QPushButton

from services.llm import LLMService
from services.prompts import build_quick_ask_prompt
from services.translator import Translator
from services.tts import TTSService
from ui.chat_window import ChatWindow
from ui.theme import apply_theme, available_geometry, bounded_position
from ui.translation_popup import TranslationPopup
from ui.workers import AsyncTextWorker


class MonitorInfo(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("monitor", wintypes.RECT),
                ("work", wintypes.RECT), ("flags", wintypes.DWORD),
                ("device", wintypes.WCHAR * 32)]


def native_screen_point(position: tuple[int, int]) -> QPoint:
    """Map UIA/hook physical coordinates to Qt's per-monitor logical coordinates."""
    api = ctypes.WinDLL("user32")
    api.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
    api.MonitorFromPoint.restype = wintypes.HANDLE
    api.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
    info = MonitorInfo(size=ctypes.sizeof(MonitorInfo))
    monitor = api.MonitorFromPoint(wintypes.POINT(*position), 2)
    if api.GetMonitorInfoW(monitor, ctypes.byref(info)):
        for screen in QApplication.screens():
            if screen.name() == info.device:
                ratio = screen.devicePixelRatio()
                origin = screen.geometry().topLeft()
                return origin + QPoint(round((position[0] - info.monitor.left) / ratio),
                                       round((position[1] - info.monitor.top) / ratio))
    return QCursor.pos()


class TTSWorker(QThread):
    """Run local speech outside the Qt GUI thread."""

    failed = Signal(str)

    def __init__(self, tts_service: TTSService, text: str) -> None:
        super().__init__()
        self._tts_service = tts_service
        self._text = text

    def run(self) -> None:
        try:
            self._tts_service.speak(self._text)
        except Exception as error:
            self.failed.emit(str(error))


class FloatingToolbar(QFrame):
    """Display actions for the currently selected text."""

    _OFFSET = 12

    def __init__(
        self,
        translator: Translator | None = None,
        tts_service: TTSService | None = None,
        llm_service: LLMService | None = None,
    ) -> None:
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.selected_text = ""
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._translator = translator or Translator()
        self._tts_service = tts_service or TTSService()
        self._llm_service = llm_service or LLMService()
        self._translation_popup = TranslationPopup()
        self._translation_worker: AsyncTextWorker | None = None
        self._translation_source = ""
        self._tts_worker: TTSWorker | None = None
        self._llm_worker: AsyncTextWorker | None = None
        self._explanation_source = ""
        self._result_worker: AsyncTextWorker | None = None
        self._result_started = False
        self._chat_windows: list[ChatWindow] = []
        # A non-activating toolbar cannot rely on focusOutEvent for outside clicks
        # or Escape. Poll only these states, and only while the toolbar is visible.
        self._key_state = ctypes.WinDLL("user32").GetAsyncKeyState
        self._key_state.argtypes = [ctypes.c_int]
        self._key_state.restype = ctypes.c_short
        self._left_button_down = False
        self._dismiss_timer = QTimer(self)
        self._dismiss_timer.setInterval(50)
        self._dismiss_timer.timeout.connect(self._check_dismissal)
        self.setObjectName("floatingToolbar")
        apply_theme(self)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)
        self._translate_button = QPushButton("翻译", self)
        self._translate_button.setToolTip("将选中文字翻译为中文")
        self._translate_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._translate_button.clicked.connect(self._start_translation)
        layout.addWidget(self._translate_button)
        self._tts_button = QPushButton("朗读", self)
        self._tts_button.setToolTip("使用本机语音朗读选中文字")
        self._tts_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._tts_button.clicked.connect(self._start_tts)
        layout.addWidget(self._tts_button)
        self._explain_button = QPushButton("解释", self)
        self._explain_button.setToolTip("解释选中的词句、概念或代码")
        self._explain_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._explain_button.clicked.connect(self._start_explanation)
        layout.addWidget(self._explain_button)
        self._chat_button = QPushButton("Chat", self)
        self._chat_button.setToolTip("围绕选中文字继续追问")
        self._chat_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._chat_button.clicked.connect(self._open_chat)
        layout.addWidget(self._chat_button)

    def show_for_selection(self, selected_text: str, position: tuple[int, int] | None = None) -> None:
        """Update the selected text and show the toolbar near the cursor."""
        if not selected_text:
            self.hide_for_missing_selection()
            return

        self.selected_text = selected_text
        self._result_worker = None
        self._translation_popup.hide()
        self.adjustSize()
        self.move(self._position_near(native_screen_point(position) if position is not None else QCursor.pos()))
        self._left_button_down = bool(self._key_state(0x01) & 0x8000)
        self.show()
        self.raise_()
        self._dismiss_timer.start()

    def set_services(self, translator: Translator, llm_service: LLMService) -> None:
        """Apply settings to new actions; existing chat windows keep their service."""
        self.hide()
        for worker in (self._translation_worker, self._llm_worker):
            if worker is not None:
                worker.cancel()
        self._translator = translator
        self._llm_service = llm_service

    def _check_dismissal(self) -> None:
        left_down = bool(self._key_state(0x01) & 0x8000)
        clicked = left_down and not self._left_button_down
        self._left_button_down = left_down
        if self._key_state(0x1B) & 0x8000:  # Escape, even with focus in the source app
            self.hide()
        elif clicked:
            position = QCursor.pos()
            if not any(
                window.isVisible() and window.frameGeometry().contains(position)
                for window in (self, self._translation_popup)
            ):
                self.hide()

    @Slot()
    def hide_for_missing_selection(self) -> None:
        """Discard stale text when a later hotkey press captures nothing."""
        self.selected_text = ""
        self.hide()

    def shutdown(self) -> None:
        """Wait for active workers before Python destroys their QThread objects."""
        self._dismiss_timer.stop()
        for worker in (self._translation_worker, self._llm_worker):
            if worker is not None:
                worker.cancel()
        for window in list(self._chat_windows):
            window.shutdown()
        for worker in (self._translation_worker, self._tts_worker, self._llm_worker):
            if worker is not None and worker.isRunning():
                worker.wait()

    def focusOutEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        """Hide when a click moves focus back to another application."""
        super().focusOutEvent(event)
        QTimer.singleShot(0, self._hide_if_focus_left)

    def _hide_if_focus_left(self) -> None:
        if QApplication.activeWindow() not in (self, self._translation_popup):
            self.hide()

    def hideEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        """Hide any result popup together with its toolbar."""
        self._dismiss_timer.stop()
        self._translation_popup.hide()
        self._result_worker = None
        super().hideEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Allow Escape to dismiss the toolbar."""
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            event.accept()
            return
        super().keyPressEvent(event)

    def _start_translation(self) -> None:
        if not self.selected_text or (
            self._translation_worker is not None
        ):
            return

        source_text = self.selected_text
        self._translation_source = source_text
        self._translate_button.setEnabled(False)
        self._translation_popup.set_heading("翻译")
        self._translation_popup.show_message("正在翻译…", self)
        worker = AsyncTextWorker(streaming_operation=lambda emit: self._translator.translate(source_text, on_delta=emit))
        self._translation_worker = worker
        self._result_worker = worker
        self._result_started = False
        worker.progress.connect(self._append_result)
        worker.completed.connect(self._show_translation)
        worker.failed.connect(self._show_translation_error)
        worker.finished.connect(self._finish_translation)
        worker.start()

    def _start_explanation(self) -> None:
        if not self.selected_text or (
            self._llm_worker is not None
        ):
            return

        source_text = self.selected_text
        self._explanation_source = source_text
        self._explain_button.setEnabled(False)
        self._translation_popup.set_heading("解释")
        self._translation_popup.show_message("正在解释…", self)
        prompt = build_quick_ask_prompt(source_text)
        worker = AsyncTextWorker(streaming_operation=lambda emit: self._llm_service.ask(prompt, on_delta=emit))
        self._llm_worker = worker
        self._result_worker = worker
        self._result_started = False
        worker.progress.connect(self._append_result)
        worker.completed.connect(self._show_explanation)
        worker.failed.connect(self._show_explanation_error)
        worker.finished.connect(self._finish_explanation)
        worker.start()

    def _open_chat(self) -> None:
        if not self.selected_text:
            return

        window = ChatWindow(self.selected_text, self._llm_service)
        self._chat_windows.append(window)
        window.destroyed.connect(lambda: self._remove_chat_window(window))
        window.show()
        window.raise_()
        window.activateWindow()

    def _remove_chat_window(self, window: ChatWindow) -> None:
        if window in self._chat_windows:
            self._chat_windows.remove(window)

    def _start_tts(self) -> None:
        if not self.selected_text or (
            self._tts_worker is not None and self._tts_worker.isRunning()
        ):
            return

        self._tts_button.setEnabled(False)
        worker = TTSWorker(self._tts_service, self.selected_text)
        self._tts_worker = worker
        worker.failed.connect(self._show_tts_error)
        worker.finished.connect(self._finish_tts)
        worker.start()

    @Slot(str)
    def _append_result(self, text: str) -> None:
        if self._accept_result():
            self._translation_popup.append_text(text, clear=not self._result_started)
            self._result_started = True
            self._result_worker.mark_displayed()

    def _accept_result(self) -> bool:
        return (
            self.isVisible() and self._translation_popup.isVisible()
            and self._result_worker is not None and self.sender() is self._result_worker
        )

    @Slot(str)
    def _show_translation(self, result: str) -> None:
        if self._accept_result():
            self._result_worker.mark_displayed()
            self._translation_popup.show_message(result, self, markdown=True)

    @Slot(str)
    def _show_translation_error(self, error: str) -> None:
        if self._accept_result():
            self._translation_popup.show_message(f"翻译失败：{error}", self)

    @Slot()
    def _finish_translation(self) -> None:
        worker = self._translation_worker
        if worker is not None:
            self._translation_worker = None
            self._translate_button.setEnabled(True)
            worker.deleteLater()

    @Slot(str)
    def _show_explanation(self, result: str) -> None:
        if self._accept_result():
            self._result_worker.mark_displayed()
            self._translation_popup.show_message(result, self, markdown=True)

    @Slot(str)
    def _show_explanation_error(self, error: str) -> None:
        if self._accept_result():
            self._translation_popup.show_message(f"解释失败：{error}", self)

    @Slot()
    def _finish_explanation(self) -> None:
        worker = self._llm_worker
        if worker is not None:
            self._llm_worker = None
            self._explain_button.setEnabled(True)
            worker.deleteLater()

    @Slot(str)
    def _show_tts_error(self, error: str) -> None:
        if self.isVisible():
            self._result_worker = None
            self._translation_popup.set_heading("朗读")
            self._translation_popup.show_message(f"朗读失败：{error}", self)

    @Slot()
    def _finish_tts(self) -> None:
        worker = self._tts_worker
        if worker is not None:
            self._tts_worker = None
            self._tts_button.setEnabled(True)
            worker.deleteLater()

    def _position_near(self, cursor_position: QPoint) -> QPoint:
        """Return a toolbar origin that stays inside the cursor's screen."""
        available = available_geometry(cursor_position)
        x = cursor_position.x() + self._OFFSET
        y = cursor_position.y() + self._OFFSET

        if x + self.width() > available.right():
            x = cursor_position.x() - self.width() - self._OFFSET
        if y + self.height() > available.bottom():
            y = cursor_position.y() - self.height() - self._OFFSET

        return bounded_position(QPoint(x, y), self.size(), available)
