"""Small QThread helpers for non-blocking text requests."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Awaitable, Callable

from PySide6.QtCore import QThread, Signal

logger = logging.getLogger(__name__)


class AsyncTextWorker(QThread):
    """Run one async text operation outside the Qt GUI thread."""

    completed = Signal(str)
    progress = Signal(str)
    failed = Signal(str)

    def __init__(
        self, operation: Callable[[], Awaitable[str]] | None = None, *,
        streaming_operation: Callable[[Callable[[str], None]], Awaitable[str]] | None = None,
    ) -> None:
        super().__init__()
        if (operation is None) == (streaming_operation is None):
            raise ValueError("Provide exactly one operation")
        self._operation = operation
        self._streaming_operation = streaming_operation
        self._pending: list[str] = []
        self._last_emit = 0.0
        self._flush_handle: asyncio.TimerHandle | None = None
        self._created = time.perf_counter()
        self._displayed = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task | None = None
        self._state_lock = threading.Lock()
        self._cancelled = threading.Event()

    def mark_displayed(self) -> None:
        """Called by the GUI when it inserts the first answer text."""
        if not self._displayed:
            self._displayed = True
            logger.info("UI first_visible_s=%.3f", time.perf_counter() - self._created)

    def _on_delta(self, text: str) -> None:
        if self._cancelled.is_set():
            return
        self._pending.append(text)
        if time.perf_counter() - self._last_emit >= 0.03:
            self._flush()
        elif self._flush_handle is None:
            self._flush_handle = asyncio.get_running_loop().call_later(0.03, self._flush)

    def _flush(self) -> None:
        if self._flush_handle is not None:
            self._flush_handle.cancel()
            self._flush_handle = None
        if self._pending and not self._cancelled.is_set():
            self.progress.emit("".join(self._pending))
            self._pending.clear()
            self._last_emit = time.perf_counter()

    def cancel(self) -> None:
        """Cancel HTTP work on its own asyncio loop, including before startup."""
        self._cancelled.set()
        with self._state_lock:
            if self._loop is not None and self._task is not None:
                self._loop.call_soon_threadsafe(self._task.cancel)

    async def _execute(self) -> None:
        with self._state_lock:
            self._loop = asyncio.get_running_loop()
            self._task = asyncio.current_task()
        try:
            if not self._cancelled.is_set():
                if self._streaming_operation is not None:
                    result = await self._streaming_operation(self._on_delta)
                else:
                    result = await self._operation()
                if not self._cancelled.is_set():
                    self._flush()
                    self.completed.emit(result)
        finally:
            if self._flush_handle is not None:
                self._flush_handle.cancel()
                self._flush_handle = None
            with self._state_lock:
                self._task = None
                self._loop = None

    def run(self) -> None:
        try:
            asyncio.run(self._execute())
        except asyncio.CancelledError:
            pass
        except Exception as error:
            self._flush()
            self.failed.emit(str(error))
