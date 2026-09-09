from __future__ import annotations

import asyncio
import os
import threading
import time
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QSignalSpy, QTest
from ui.workers import AsyncTextWorker


class AsyncTextWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_cancel_interrupts_inflight_operation_and_runs_cleanup(self) -> None:
        started = threading.Event()
        cleaned = threading.Event()
        async def operation():
            started.set()
            try:
                await asyncio.sleep(60)
                return 'late result'
            finally:
                cleaned.set()
        worker = AsyncTextWorker(operation)
        try:
            worker.start()
            self.assertTrue(started.wait(2))
            worker.cancel()
            self.assertTrue(worker.wait(2000))
            self.assertTrue(cleaned.is_set())
        finally:
            worker.cancel()
            worker.wait()

    def test_cancel_before_start_does_not_invoke_operation(self) -> None:
        called = threading.Event()
        async def operation():
            called.set()
            return "result"
        worker = AsyncTextWorker(operation)
        worker.cancel()
        worker.start()
        self.assertTrue(worker.wait(2000))
        self.assertFalse(called.is_set())

    def test_buffered_text_is_flushed_while_server_is_idle(self) -> None:
        async def operation(emit):
            emit("first")
            emit(" second")
            await asyncio.sleep(60)
            return "first second"
        worker = AsyncTextWorker(streaming_operation=operation)
        spy = QSignalSpy(worker.progress)
        try:
            worker.start()
            deadline = time.monotonic() + 2
            while spy.count() < 2 and time.monotonic() < deadline:
                QTest.qWait(10)
            self.assertEqual(spy.count(), 2)
            self.assertEqual(spy.at(0), ["first"])
            self.assertEqual(spy.at(1), [" second"])
            self.assertTrue(worker.isRunning())
        finally:
            worker.cancel()
            worker.wait()
