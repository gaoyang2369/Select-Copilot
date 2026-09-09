"""Desktop lifecycle, settings and safe selection capture scheduling."""
from __future__ import annotations

import logging
import signal
import sys
import threading
from dataclasses import dataclass, replace

import keyboard
from PySide6.QtCore import QObject, QTimer, Signal, Slot
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from config.settings import Settings, SettingsStore
from core.clipboard import ClipboardService
from core.hotkey import GlobalHotkey
from core.mouse import Drag, MouseSelectionListener
from core.selection import SelectionService
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


class CopilotController(QObject):
    manual_requested = Signal(object)
    capture_completed = Signal(str, object)

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
        self.hotkey = GlobalHotkey(lambda: self.manual_requested.emit(self.mouse.foreground()), self.settings.hotkey)
        self.dialog = SettingsDialog(self.apply_settings)
        self.tray = CopilotTray(self.open_settings, self.toggle_auto, application.quit)
        self._stopping = threading.Event()
        self._epoch = 0
        self._worker: threading.Thread | None = None
        self._current_request: CaptureRequest | None = None
        self._pending_drag: Drag | None = None
        self._auto_timer = QTimer(self)
        self._auto_timer.setSingleShot(True)
        self._auto_timer.setInterval(100)
        self._auto_timer.timeout.connect(self._capture_auto)
        self.selection_service = SelectionService(ClipboardService(), self._send_copy)
        self.mouse.dragged.connect(self._schedule_auto)
        self.manual_requested.connect(self._capture_manual)
        self.capture_completed.connect(self._deliver_capture)

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
        self._auto_timer.stop()

    @Slot(object)
    def _schedule_auto(self, drag: Drag) -> None:
        if not self.settings.auto_select or not self.mouse.is_current(drag) or self._stopping.is_set():
            return
        self._invalidate_capture()
        self._pending_drag = drag
        self._auto_timer.start()

    @Slot()
    def _capture_auto(self) -> None:
        drag = self._pending_drag
        self._pending_drag = None
        if drag is not None:
            self._start_capture(CaptureRequest(drag.window, self._epoch, drag))

    @Slot(object)
    def _capture_manual(self, window: int) -> None:
        self._invalidate_capture()
        self._start_capture(CaptureRequest(window, self._epoch))

    def _valid_request(self, request: CaptureRequest) -> bool:
        if self._stopping.is_set() or request.epoch != self._epoch:
            return False
        if request.drag is not None:
            return self.settings.auto_select and self.mouse.is_current(request.drag)
        return self.mouse.can_capture(request.window)

    def _start_capture(self, request: CaptureRequest) -> None:
        if not self._valid_request(request):
            return
        if self._worker is not None and self._worker.is_alive():
            QTimer.singleShot(25, lambda: self._start_capture(request))
            return
        self._current_request = request
        self._worker = threading.Thread(target=self._read_selection, args=(request,), daemon=True)
        self._worker.start()

    def _send_copy(self) -> None:
        if self._current_request is None or not self._valid_request(self._current_request):
            raise RuntimeError("Selection changed before copying")
        keyboard.send("ctrl+c")

    def _read_selection(self, request: CaptureRequest) -> None:
        try:
            if self._valid_request(request):
                text = self.selection_service.get_selected_text()
                self.capture_completed.emit(text, request)
        except Exception:
            logger.exception("Selection capture failed")

    @Slot(str, object)
    def _deliver_capture(self, text: str, request: CaptureRequest) -> None:
        if not self._valid_request(request):
            return
        if text.strip():
            logger.info("Selected text captured (%s characters, %s).", len(text), "mouse" if request.drag else "hotkey")
            self.toolbar.show_for_selection(text)
        elif request.drag is None:
            logger.warning("No text captured. Select copyable text in the foreground app and retry.")
            self.toolbar.hide_for_missing_selection()

    def shutdown(self) -> None:
        if self._stopping.is_set():
            return
        self._stopping.set()
        self._invalidate_capture()
        self.mouse.stop()
        self.hotkey.stop()
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
