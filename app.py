"""Selection Copilot desktop application entry point."""

from __future__ import annotations

import logging
import signal

import keyboard
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication

from core.clipboard import ClipboardService
from core.hotkey import HOTKEY, GlobalHotkey
from core.selection import SelectionService
from ui.toolbar import FloatingToolbar


class SelectionNotifier(QObject):
    """Relay results from the selection worker to the Qt GUI thread."""

    selection_ready = Signal(str)
    selection_missing = Signal()


def handle_hotkey(service: SelectionService, notifier: SelectionNotifier) -> None:
    """Read selected text in a worker thread, then notify the GUI safely."""
    selected_text = service.get_selected_text()
    if not selected_text:
        logging.warning(
            "No text captured. Select copyable text in the foreground app and retry."
        )
        notifier.selection_missing.emit()
        return

    print(f"Selected text captured ({len(selected_text)} characters).", flush=True)
    notifier.selection_ready.emit(selected_text)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    qt_app = QApplication([])
    qt_app.setQuitOnLastWindowClosed(False)
    signal_timer = QTimer(qt_app)
    signal_timer.timeout.connect(lambda: None)
    signal_timer.start(100)
    selection_service = SelectionService(ClipboardService(), lambda: keyboard.send("ctrl+c"))
    notifier = SelectionNotifier()
    toolbar = FloatingToolbar()
    notifier.selection_ready.connect(toolbar.show_for_selection)
    notifier.selection_missing.connect(toolbar.hide_for_missing_selection)
    hotkey = GlobalHotkey(lambda: handle_hotkey(selection_service, notifier))
    cleaned_up = False

    def cleanup() -> None:
        nonlocal cleaned_up
        if cleaned_up:
            return
        cleaned_up = True
        signal_timer.stop()
        hotkey.stop()
        toolbar.shutdown()

    qt_app.aboutToQuit.connect(cleanup)

    previous_handlers = {}
    try:
        # Python signals must request Qt shutdown, not raise inside a Qt slot.
        for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGBREAK):
            previous_handlers[signum] = signal.signal(signum, lambda *_: qt_app.quit())
        hotkey.start()
        print(f"Selection Copilot is running. Select text and press {HOTKEY}. Ctrl+C exits.", flush=True)
        qt_app.exec()
    finally:
        cleanup()
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
    print("Selection Copilot stopped.", flush=True)


if __name__ == "__main__":
    main()
