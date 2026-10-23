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
    "idea64.exe", "pycharm64.exe", "webstorm64.exe", "rider64.exe", "xshell.exe",
})

# Explicit compatibility profiles; never enable automatic copy for arbitrary apps.
AUTO_COPY_APPS = frozenset({"weixin.exe", "wechat.exe"})


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
                is_current: Callable[[], bool] = lambda: True,
                origin: tuple[int, int] | None = None) -> SelectionResult:
        if not self._capture_lock.acquire(blocking=False):
            return SelectionResult("cancelled")
        started = time.monotonic()
        result = SelectionResult("cancelled")
        copied = False
        attempts = 0
        try:
            # A bounded settling session, not a three-sample race against the app.
            # Fast providers return immediately. Slow selections get progressively
            # more time; the isolated reader enforces each COM call's hard deadline.
            for delay in (0, 0.04, 0.08, 0.12, 0.18, 0.24):
                if attempts and time.monotonic() - started >= 0.75:
                    break
                for _ in range(round(delay / 0.02)):
                    if not is_current():
                        result = SelectionResult("cancelled", reason="request_superseded")
                        return result
                    time.sleep(0.02)
                if attempts and time.monotonic() - started >= 0.75:
                    break
                if not is_current():
                    result = SelectionResult("cancelled", reason="request_superseded")
                    return result
                attempts += 1
                if isinstance(self._reader, UIASelectionReader):
                    result = self._reader.read(window, position, origin)
                else:
                    result = self._reader.read(window, position, origin=origin, program=program,
                                               is_current=is_current)
                logger.info("Read: app=%s attempt=%d status=%s reason=%s method=%s",
                            program or "unknown", attempts, result.status, result.reason, result.method)
                if result.status not in ("empty", "unsupported", "error", "timeout"):
                    break
                if result.reason in ("worker_deadline", "worker_startup", "office_not_text_selection"):
                    break
                if result.status == "unsupported" and allow_copy and attempts >= 3:
                    break
            if not is_current():
                result = SelectionResult("cancelled", reason="request_superseded")
            elif (result.status == "unsupported" and allow_copy and program
                  and program.casefold() not in NO_COPY_APPS):
                copied = True
                text = self._clipboard.get_text_after_copy(
                    self._send_copy, window=window, is_current=is_current,
                )
                result = SelectionResult("selected" if text.strip() else "empty",
                                         text, position, "clipboard", reason="copy_result" if text.strip() else "copy_no_text")
            return result
        finally:
            logger.info("Capture: app=%s status=%s method=%s copy_attempt=%s elapsed_ms=%d reason=%s attempts=%d",
                        program or "unknown", result.status, result.method, copied,
                        round((time.monotonic() - started) * 1000), result.reason, attempts)
            self._capture_lock.release()
