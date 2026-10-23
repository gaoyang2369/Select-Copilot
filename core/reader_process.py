"""A restartable, read-only COM worker. Clipboard transactions stay in the parent."""

from __future__ import annotations

import ctypes
import logging
import multiprocessing
import os
import queue
import sys
import threading
import time

from core.uia import SelectionResult

logger = logging.getLogger(__name__)


def _worker_entry(connection, parent_pid: int) -> None:
    # comtypes may initialize the spawn entry thread as STA. Own a fresh MTA.
    # pythoncom's first import must use the same apartment as this worker.
    sys.coinit_flags = 0
    thread = threading.Thread(target=_worker_loop, args=(connection, parent_pid))
    thread.start()
    thread.join()


def _worker_loop(connection, parent_pid: int) -> None:
    import comtypes
    comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
    import win32gui
    import win32process
    from core.uia import UIA, UIASelectionReader
    from core.powerpoint import PowerPointSelectionReader

    # UIA and low-level input both use physical screen coordinates.
    ctypes.windll.user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    automation = UIASelectionReader.create_automation()
    reader = UIASelectionReader(automation)
    office = PowerPointSelectionReader()
    notifications = queue.SimpleQueue()
    watched = 0
    watching = False
    handler = None
    root = None
    heartbeat = time.monotonic()

    class SelectionChanged(comtypes.COMObject):
        _com_interfaces_ = [UIA.IUIAutomationEventHandler]

        def __init__(self, window):
            super().__init__()
            self.window = window

        def HandleAutomationEvent(self, sender, event_id):
            # Never query a provider inside its callback or send IPC concurrently.
            notifications.put((self.window, time.monotonic()))
            return 0

    def unwatch():
        nonlocal handler, root, watched
        if handler is not None:
            try:
                automation.RemoveAutomationEventHandler(UIA.UIA_Text_TextSelectionChangedEventId, root, handler)
            except (comtypes.COMError, OSError):
                pass
        handler, root, watched = None, None, 0

    try:
        connection.send(("ready",))
        while True:
            if connection.poll(0.04):
                command = connection.recv()
                if command[0] == "stop":
                    break
                if command[0] == "watch":
                    watching = command[1]
                elif command[0] == "read":
                    _, identity, window, position, origin, program = command
                    try:
                        result = reader._read(window, position, origin)
                        if program == "powerpnt.exe" and result.status != "blocked":
                            native = office.read(window)
                            if native.status != "unsupported":
                                result = native
                    except Exception as error:
                        # Keep provider-supplied messages/text out of diagnostics.
                        import traceback
                        frame = traceback.extract_tb(error.__traceback__)[-1]
                        result = SelectionResult("error", reason=f"provider_{type(error).__name__}_{frame.name}_{frame.lineno}")
                    connection.send(("result", identity, result))

            window = win32gui.GetForegroundWindow() if watching else 0
            if window and win32process.GetWindowThreadProcessId(window)[1] in (parent_pid, os.getpid()):
                window = 0
            if window != watched:
                unwatch()
                if window:
                    try:
                        root = automation.ElementFromHandle(window)
                        handler = SelectionChanged(window)
                        automation.AddAutomationEventHandler(
                            UIA.UIA_Text_TextSelectionChangedEventId, root,
                            UIA.TreeScope_Subtree, None, handler,
                        )
                        watched = window
                    except (comtypes.COMError, OSError):
                        handler, root = None, None
                        # Retry when the next foreground window is observed.
                        watched = window
            changed = None
            while not notifications.empty():
                changed = notifications.get()
            if changed and changed[0] == watched:
                connection.send(("event", *changed))
            if time.monotonic() - heartbeat >= 0.5:
                connection.send(("heartbeat",))
                heartbeat = time.monotonic()
    except (EOFError, BrokenPipeError, OSError):
        pass
    finally:
        unwatch()
        connection.close()
        comtypes.CoUninitialize()


class ReaderProcess:
    """One persistent provider process with a hard deadline and cooperative cancellation."""

    def __init__(self, on_selection_changed=None, *, timeout: float = 1.2,
                 worker_target=_worker_entry) -> None:
        self.on_selection_changed = on_selection_changed
        self.timeout = timeout
        self._target = worker_target
        self._lock = threading.RLock()
        self._read_lock = threading.Lock()
        self._process = None
        self._connection = None
        self._ready = threading.Event()
        self._received = threading.Event()
        self._result = None
        self._identity = 0
        self._watching = False
        self._closed = False

    def _start(self) -> None:
        with self._lock:
            if self._closed or (self._process is not None and self._process.is_alive()):
                return
            self._dispose()
            context = multiprocessing.get_context("spawn")
            connection, child = context.Pipe()
            process = context.Process(target=self._target, args=(child, os.getpid()), daemon=True,
                                      name="selection-reader")
            self._ready.clear()
            process.start()
            child.close()
            self._process, self._connection = process, connection
            threading.Thread(target=self._receive, args=(connection,), daemon=True,
                             name="selection-events").start()
            connection.send(("watch", self._watching))

    def _receive(self, connection) -> None:
        last_seen = time.monotonic()
        try:
            while True:
                if not connection.poll(0.25):
                    with self._lock:
                        if connection is not self._connection:
                            return
                        if time.monotonic() - last_seen > 4:
                            self._dispose()
                            self._received.set()
                            logger.info("Reader reset: reason=worker_heartbeat")
                            return
                    continue
                message = connection.recv()
                last_seen = time.monotonic()
                with self._lock:
                    if connection is not self._connection:
                        return
                    if message[0] == "ready":
                        self._ready.set()
                    elif message[0] == "result" and message[1] == self._identity:
                        self._result = message[2]
                        self._received.set()
                    elif message[0] == "event" and self._watching and self.on_selection_changed:
                        self.on_selection_changed(message[1], message[2])
        except (EOFError, OSError):
            with self._lock:
                if connection is self._connection:
                    self._received.set()

    def watch(self, enabled: bool) -> None:
        with self._lock:
            self._watching = enabled
            if enabled:
                self._start()
            if self._connection:
                try:
                    self._connection.send(("watch", enabled))
                except (OSError, EOFError):
                    self._dispose()

    def read(self, window: int, position=None, *, origin=None, program="",
             is_current=lambda: True) -> SelectionResult:
        with self._read_lock:
            self._start()
            # Spawn/import time is separate from the provider transaction deadline.
            startup = time.monotonic() + 4
            while not self._ready.wait(0.02):
                if self._closed or not is_current():
                    return SelectionResult("cancelled", reason="request_superseded")
                if time.monotonic() >= startup:
                    return self._abort("timeout", "worker_startup")
            with self._lock:
                if self._closed or not is_current():
                    return SelectionResult("cancelled", reason="request_superseded")
                if self._connection is None:
                    return self._abort("error", "worker_disconnected")
                self._identity += 1
                self._received.clear()
                self._result = None
                try:
                    self._connection.send(("read", self._identity, window, position, origin, program))
                except (OSError, EOFError):
                    return self._abort("error", "worker_disconnected")
            deadline = time.monotonic() + self.timeout
            while not self._received.wait(0.02):
                if self._closed or not is_current():
                    # Keep the observer alive during normal typing/rapid selections.
                    # Its late reply is ignored by identity; a hung call is bounded
                    # by the next read's deadline or the idle heartbeat watchdog.
                    return SelectionResult("cancelled", reason="request_superseded")
                if time.monotonic() >= deadline:
                    return self._abort("timeout", "worker_deadline")
            if self._closed or not is_current():
                return SelectionResult("cancelled", reason="request_superseded")
            return self._result or self._abort("error", "worker_disconnected")

    def _abort(self, status: str, reason: str) -> SelectionResult:
        with self._lock:
            self._dispose()
        logger.info("Reader reset: reason=%s", reason)
        return SelectionResult(status, reason=reason)

    def _dispose(self) -> None:
        connection, process = self._connection, self._process
        self._connection = self._process = None
        if process is not None:
            if process.is_alive():
                process.terminate()
            process.join(0.3)
            if not process.is_alive():
                process.close()
        if connection is not None:
            connection.close()

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._received.set()
            self._dispose()
