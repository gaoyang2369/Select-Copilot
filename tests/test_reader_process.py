"""Use real spawn/IPC so a stuck provider cannot pass as a mocked timeout."""
import threading
import time
import unittest

from core.reader_process import ReaderProcess
from core.uia import SelectionResult


def fixture_worker(connection, parent_pid):
    connection.send(("ready",))
    while True:
        command = connection.recv()
        if command[0] != "read":
            continue
        _, identity, window, *_ = command
        if window == 1:
            time.sleep(30)
        elif window == 3:
            connection.close()
            return
        else:
            if window == 4:
                time.sleep(0.08)
            connection.send(("result", identity, SelectionResult("selected", "new selection")))


class ReaderProcessTests(unittest.TestCase):
    def setUp(self):
        self.reader = ReaderProcess(timeout=0.15, worker_target=fixture_worker)
        self.addCleanup(self.reader.close)

    def test_hung_provider_is_terminated_and_next_request_succeeds(self):
        result = self.reader.read(1)
        self.assertEqual((result.status, result.reason), ("timeout", "worker_deadline"))
        self.assertEqual(self.reader.read(2).text, "new selection")

    def test_cancelled_call_does_not_block_shutdown_or_next_request(self):
        self.assertEqual(self.reader.read(2).status, "selected")
        process = self.reader._process
        current = threading.Event()
        current.set()
        timer = threading.Timer(0.02, current.clear)
        timer.start()
        try:
            self.assertEqual(self.reader.read(4, is_current=current.is_set).status, "cancelled")
            self.assertEqual(self.reader.read(2).status, "selected")
            self.assertIs(self.reader._process, process)
        finally:
            timer.join()

    def test_cancelled_hung_call_remains_bounded_for_next_request(self):
        self.assertEqual(self.reader.read(2).status, "selected")
        current = threading.Event()
        current.set()
        timer = threading.Timer(0.02, current.clear)
        timer.start()
        try:
            self.assertEqual(self.reader.read(1, is_current=current.is_set).status, "cancelled")
            self.assertEqual(self.reader.read(2).reason, "worker_deadline")
            self.assertEqual(self.reader.read(2).status, "selected")
        finally:
            timer.join()

    def test_crashed_provider_is_reported_and_recovered(self):
        self.assertEqual(self.reader.read(3).reason, "worker_disconnected")
        self.assertEqual(self.reader.read(2).status, "selected")
