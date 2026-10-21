"""UIA-first selection capture with explicit, bounded clipboard fallback."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from core.clipboard import ClipboardService
from core.uia import SelectionResult, UIASelectionReader


logger = logging.getLogger(__name__)

# Terminals may be embedded in IDEs. Do not inject shortcuts into these hosts
# when accessibility could not confirm a selection; use the clipboard entry.
NO_COPY_APPS = frozenset({
    "cmd.exe", "powershell.exe", "pwsh.exe", "windowsterminal.exe", "conhost.exe",
    "openconsole.exe", "mintty.exe", "wezterm-gui.exe", "alacritty.exe", "wsl.exe",
    "code.exe", "code - insiders.exe", "cursor.exe", "windsurf.exe", "devenv.exe",
    "idea64.exe", "pycharm64.exe", "webstorm64.exe", "rider64.exe",
})


class SelectionService:
    """Treat an empty selection differently from an unsupported provider."""

    def __init__(
        self,
        clipboard: ClipboardService,
        send_copy: Callable[[], bool | None],
        reader: UIASelectionReader | None = None,
    ) -> None:
        self._clipboard = clipboard
        self._send_copy = send_copy
        self._reader = reader or UIASelectionReader()
        self._capture_lock = threading.Lock()

    def capture(self, window: int, *, position: tuple[int, int] | None = None,
                allow_copy: bool = False, program: str = "",
                is_current: Callable[[], bool] = lambda: True) -> SelectionResult:
        if not self._capture_lock.acquire(blocking=False):
            return SelectionResult("cancelled")
        started = time.monotonic()
        result = SelectionResult("cancelled")
        copied = False
        try:
            # Retry reads only; never send another shortcut to improve sensitivity.
            for attempt in range(3):
                if not is_current():
                    result = SelectionResult("cancelled")
                    return result
                result = self._reader.read(window, position)
                if result.status not in ("empty", "unsupported") or attempt == 2:
                    break
                time.sleep(0.035)
            if not is_current():
                result = SelectionResult("cancelled")
            elif (result.status == "unsupported" and allow_copy and program
                  and program.casefold() not in NO_COPY_APPS):
                copied = True
                text = self._clipboard.get_text_after_copy(
                    self._send_copy, window=window, is_current=is_current,
                )
                result = SelectionResult("selected" if text.strip() else "empty",
                                         text, position, "clipboard")
            return result
        finally:
            logger.info("Capture: app=%s status=%s method=%s copy_attempt=%s elapsed_ms=%d",
                        program or "unknown", result.status, result.method, copied,
                        round((time.monotonic() - started) * 1000))
            self._capture_lock.release()
