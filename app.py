"""Desktop lifecycle, settings and safe selection capture scheduling."""
from __future__ import annotations

import logging
import multiprocessing
import signal
import sys
import threading
import time
from dataclasses import dataclass, replace

import keyboard
from PySide6.QtCore import QObject, QTimer, Signal, Slot
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from config.settings import Settings, SettingsStore, app_names
from core.clipboard import ClipboardService
from core.hotkey import GlobalHotkey
from core.mouse import Drag, MouseSelectionListener
from core.selection import AUTO_COPY_APPS, SelectionService
from core.reader_process import ReaderProcess
from core.uia import SelectionResult
from core.runtime import SingleInstance, configure_logging
from services.llm import LLMService
from services.translator import Translator
from ui.settings_dialog import SettingsDialog
from ui.toolbar import FloatingToolbar
from ui.tray import CopilotTray

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CaptureRequest:
    window: int
    epoch: int
    drag: Drag | None = None
    generation: int | None = None
    position: tuple[int, int] | None = None
    source: str = "hotkey"


class CopilotController(QObject):
    manual_requested = Signal(object)
    capture_completed = Signal(object, object)
    selection_changed = Signal(object, float)

    def __init__(self, application: QApplication, store: SettingsStore | None = None) -> None:
        super().__init__(application)
        self.application = application
        self.store = store or SettingsStore()
        self._startup_error = ""
        try:
            self.settings = self.store.load()
        except (OSError, ValueError) as error:
            self._startup_error = f"无法读取设置，将使用默认值：{error}"
            self.settings = self.store.defaults()
            try:
                self.settings.validate()
            except ValueError:
                self.settings = Settings()
        self.toolbar = FloatingToolbar()
        self.toolbar.set_services(*self._services(self.settings))
        self.mouse = MouseSelectionListener()
        self.hotkey = GlobalHotkey(self.manual_requested.emit, self.settings.hotkey, context=self.mouse.foreground)
        self.dialog = SettingsDialog(self.apply_settings)
        self.tray = CopilotTray(self.open_settings, self.toggle_auto, application.quit, self._capture_clipboard)
        self._stopping = threading.Event()
        self._epoch = 0
        self._worker: threading.Thread | None = None
        self._current_request: CaptureRequest | None = None
        self._pending_drag: Drag | None = None
        self._queued_request: CaptureRequest | None = None
        self._last_delivery = None
        self._retry_timer = QTimer(self)
        self._retry_timer.setSingleShot(True)
        self._retry_timer.setInterval(20)
        self._retry_timer.timeout.connect(self._drain_capture)
        self._auto_timer = QTimer(self)
        self._auto_timer.setSingleShot(True)
        self._auto_timer.setInterval(80)
        self._auto_timer.timeout.connect(self._capture_auto)
        self.clipboard_service = ClipboardService()
        self.reader = ReaderProcess(self.selection_changed.emit)
        self._reader_timer = QTimer(self)
        self._reader_timer.setInterval(1000)
        self._reader_timer.timeout.connect(lambda: self.reader.watch(self.settings.auto_select))
        self.selection_service = SelectionService(self.clipboard_service, self._send_copy, self.reader)
        self.mouse.dragged.connect(self._schedule_auto)
        self.mouse.cancelled.connect(self._cancel_capture)
        self.manual_requested.connect(self._capture_manual)
        self.capture_completed.connect(self._deliver_capture)
        self.selection_changed.connect(self._selection_changed)

    @staticmethod
    def _services(settings: Settings) -> tuple[Translator, LLMService]:
        options = dict(base_url=settings.base_url, api_key=settings.api_key,
                       model=settings.model, stream=settings.stream)
        return (Translator(**options, thinking=settings.translation_thinking),
                LLMService(**options, thinking=settings.thinking))

    def start(self) -> None:
        try:
            self.hotkey.start()
        except RuntimeError as error:
            self._startup_error += f"\n{error}"
        if self.settings.auto_select:
            try:
                self.mouse.start()
            except RuntimeError as error:
                self.settings = replace(self.settings, auto_select=False)
                self._startup_error += f"\n{error}"
        self.reader.watch(self.settings.auto_select)
        self._reader_timer.start()
        self._update_tray()
        self.tray.show()
        if self._startup_error or not all((self.settings.base_url, self.settings.api_key, self.settings.model)) or not QSystemTrayIcon.isSystemTrayAvailable():
            QTimer.singleShot(0, self.open_settings)

    def _update_tray(self) -> None:
        hotkey = self.settings.hotkey if self.hotkey._registered else "未注册，请打开设置"
        self.tray.update_status(hotkey, self.settings.auto_select)

    @Slot()
    def open_settings(self) -> None:
        self._invalidate_capture()
        self.toolbar.hide()
        if not self.dialog.isVisible():
            self.dialog.load(self.settings)
        if self._startup_error:
            self.dialog.error.setText(self._startup_error.strip())
            self._startup_error = ""
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()

    def apply_settings(self, settings: Settings) -> None:
        """Apply a valid configuration, rolling back runtime changes on failure."""
        settings.validate()
        previous = self.settings
        services = self._services(settings)
        was_registered = self.hotkey._registered
        try:
            self.hotkey.reconfigure(settings.hotkey)
            if settings.auto_select:
                self.mouse.start()
            else:
                self.mouse.stop()
            self.store.save(settings)
        except (OSError, RuntimeError):
            if was_registered:
                self.hotkey.reconfigure(previous.hotkey)
            else:
                self.hotkey.stop()
            if previous.auto_select:
                self.mouse.start()
            else:
                self.mouse.stop()
            raise
        self._invalidate_capture()
        self.settings = settings
        self.reader.watch(settings.auto_select)
        self.toolbar.set_services(*services)
        self._update_tray()

    @Slot(bool)
    def toggle_auto(self, enabled: bool) -> None:
        try:
            self.apply_settings(replace(self.settings, auto_select=enabled))
        except (ValueError, OSError, RuntimeError) as error:
            self._update_tray()
            self.open_settings()
            self.dialog.error.setText(str(error))

    def _invalidate_capture(self) -> None:
        self._epoch += 1
        self._pending_drag = None
        self._queued_request = None
        self._retry_timer.stop()
        self._auto_timer.stop()

    @Slot()
    def _cancel_capture(self) -> None:
        self._invalidate_capture()
        self.toolbar.hide()

    @Slot(object)
    def _schedule_auto(self, drag: Drag) -> None:
        if not self.settings.auto_select or not self.mouse.is_current(drag) or self._stopping.is_set():
            return
        logger.info("Candidate: source=%s window=%s generation=%s", drag.kind, drag.window, drag.generation)
        self._invalidate_capture()
        self._pending_drag = drag
        self._auto_timer.start()

    @Slot(object, float)
    def _selection_changed(self, window: int, timestamp: float) -> None:
        if (not self.settings.auto_select or self._stopping.is_set()
                or time.monotonic() - timestamp > 0.5 or not self.mouse.can_capture(window)):
            return
        # Input gestures own a pending session. Events supplement them, never cancel
        # their settling reads, and never initiate automatic clipboard operations.
        if self._auto_timer.isActive() or (self._worker and self._worker.is_alive()):
            return
        if not self.mouse.can_copy(window):  # Wait until buttons/modifiers are up.
            return
        drag = Drag(self.mouse.detector.generation, window, self.mouse.bounds(window), kind="uia_event")
        self._schedule_auto(drag)

    def _drain_capture(self) -> None:
        request, self._queued_request = self._queued_request, None
        if request is not None:
            self._start_capture(request)

    @Slot()
    def _capture_auto(self) -> None:
        drag = self._pending_drag
        self._pending_drag = None
        if drag is not None:
            self._start_capture(CaptureRequest(drag.window, self._epoch, drag, source=drag.kind))

    @Slot(object)
    def _capture_manual(self, window: int) -> None:
        self._invalidate_capture()
        generation = self.mouse.detector.generation if self.mouse.running else None
        self._start_capture(CaptureRequest(window, self._epoch, generation=generation,
                                           position=self.mouse.cursor_position()))

    @Slot()
    def _capture_clipboard(self) -> None:
        self._invalidate_capture()
        self._start_capture(CaptureRequest(0, self._epoch, source="clipboard"))

    def _valid_request(self, request: CaptureRequest) -> bool:
        if self._stopping.is_set() or request.epoch != self._epoch:
            return False
        if request.source == "clipboard":
            return True  # The tray menu temporarily owns foreground focus.
        if request.drag is not None:
            return self.settings.auto_select and self.mouse.is_current(request.drag)
        return (self.mouse.can_capture(request.window) and
                (request.generation is None or request.generation == self.mouse.detector.generation))

    def _start_capture(self, request: CaptureRequest) -> None:
        if not self._valid_request(request):
            logger.info("Capture filtered: source=%s reason=stale_or_inactive epoch=%s", request.source, request.epoch)
            return
        if self._worker is not None and self._worker.is_alive():
            self._queued_request = request
            self._retry_timer.start()
            return
        self._current_request = request
        self._worker = threading.Thread(target=self._read_selection, args=(request,), daemon=True)
        self._worker.start()

    def _send_copy(self) -> bool:
        request = self._current_request
        if request is None:
            return False
        deadline = time.monotonic() + 0.6
        while self._valid_request(request) and not self.mouse.can_copy(request.window):
            if time.monotonic() >= deadline or self._stopping.wait(0.01):
                logger.info("Copy cancelled: keys are still held")
                return False
        if not self._valid_request(request):
            return False
        keyboard.send("ctrl+c")
        logger.info("Copy shortcut sent: source=%s", request.source)
        return True

    def _read_selection(self, request: CaptureRequest) -> None:
        try:
            if self._valid_request(request):
                if request.source == "clipboard":
                    text = self.clipboard_service.read_text()
                    result = SelectionResult("selected" if text.strip() else "empty", text, method="clipboard")
                else:
                    program = self.mouse.program_name(request.window)
                    if program in app_names(self.settings.excluded_apps):
                        logger.info("Capture filtered: app=%s excluded", program)
                        result = SelectionResult("blocked")
                    else:
                        manual = request.drag is None
                        allow_copy = (self.settings.clipboard_fallback != "never" and
                                      (manual or (request.source != "uia_event" and (
                                          (self.settings.clipboard_fallback == "compatible" and program in AUTO_COPY_APPS)
                                          or (self.settings.clipboard_fallback == "allowlist" and
                                              program in app_names(self.settings.clipboard_apps))))))
                        result = self.selection_service.capture(
                            request.window, position=request.drag.position if request.drag else None,
                            program=program, allow_copy=allow_copy and not self.mouse.is_console(request.window),
                            is_current=lambda: self._valid_request(request),
                            origin=request.drag.origin if request.drag else None,
                        )
                self.capture_completed.emit(result, request)
        except Exception:
            logger.exception("Selection capture failed")

    @Slot(object, object)
    def _deliver_capture(self, result: SelectionResult, request: CaptureRequest) -> None:
        if not self._valid_request(request):
            logger.info("Delivery discarded: reason=stale_or_inactive epoch=%s", request.epoch)
            return
        if result.status == "selected" and result.text.strip():
            identity = (request.window, self.mouse.detector.generation, result.text)
            if request.source == "uia_event" and identity == self._last_delivery:
                return
            self._last_delivery = identity
            logger.info("Selected text captured (%s characters, %s).", len(result.text), request.source)
            position = result.position or (request.drag.position if request.drag else request.position)
            self.toolbar.show_for_selection(result.text, position)
            logger.info("Delivery: source=%s method=%s epoch=%s shown=true", request.source, result.method, request.epoch)
        elif request.drag is None:
            logger.info("No text captured: %s", result.status)
            self.toolbar.hide_for_missing_selection()
            self.tray.showMessage("未读取到选中文字", "请确认已选中文字；也可手动复制后，从托盘选择“使用剪贴板文字”。", msecs=2500)

    def shutdown(self) -> None:
        if self._stopping.is_set():
            return
        self._stopping.set()
        self._reader_timer.stop()
        self._invalidate_capture()
        self.mouse.stop()
        self.hotkey.stop()
        self.reader.close()
        if self._worker is not None:
            self._worker.join()
        self.toolbar.shutdown()
        self.tray.hide()
        self.dialog.close()


def main() -> None:
    application = QApplication([])
    application.setApplicationName("SelectionCopilot")
    application.setQuitOnLastWindowClosed(False)
    instance = SingleInstance(parent=application)
    if not instance.start("quit" if "--quit" in sys.argv else "show"):
        return
    controller = None
    signal_timer = QTimer(application)
    signal_timer.timeout.connect(lambda: None)
    signal_timer.start(100)
    previous_handlers = {}
    try:
        configure_logging()
        controller = CopilotController(application)
        application.setWindowIcon(controller.tray.icon())
        application.aboutToQuit.connect(controller.shutdown)
        instance.requested.connect(lambda command: application.quit() if command == "quit" else controller.open_settings())
        for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGBREAK):
            previous_handlers[signum] = signal.signal(signum, lambda *_: application.quit())
        controller.start()
        if "--settings" in sys.argv:
            QTimer.singleShot(0, controller.open_settings)
        logger.info("Selection Copilot started. Hotkey: %s; automatic selection: %s", controller.settings.hotkey, controller.settings.auto_select)
        if sys.stdout is not None:
            print(f"Selection Copilot is running. Hotkey: {controller.settings.hotkey}. Settings and Exit are in the system tray. Ctrl+C exits.", flush=True)
        application.exec()
    finally:
        signal_timer.stop()
        if controller is not None:
            controller.shutdown()
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
        instance.close()
        logger.info("Selection Copilot stopped.")
        logging.shutdown()
    if sys.stdout is not None:
        print("Selection Copilot stopped.", flush=True)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    try:
        main()
    except Exception as error:
        if not logging.getLogger().handlers:
            try:
                configure_logging()
            except OSError:
                pass  # Still display the error if the user data directory is unwritable.
        logger.exception("Application startup or shutdown failed")
        if QApplication.instance() is not None:
            QMessageBox.critical(None, "Selection Copilot", f"启动或退出失败：{error}\n\n日志位置：%LOCALAPPDATA%/SelectionCopilot/logs/app.log")
        sys.exit(1)
