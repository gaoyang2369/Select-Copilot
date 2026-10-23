from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from core.selection import SelectionService
from core.uia import SelectionResult


class SelectionServiceTests(unittest.TestCase):
    def setUp(self):
        self.clipboard = Mock()
        self.reader = Mock()
        self.send_copy = Mock()
        self.service = SelectionService(self.clipboard, self.send_copy, self.reader)
        self.sleep = patch("core.selection.time.sleep")
        self.sleep.start()
        self.addCleanup(self.sleep.stop)

    def test_uia_selection_never_touches_clipboard(self):
        self.reader.read.return_value = SelectionResult("selected", "word", (10, 20))
        result = self.service.capture(1, allow_copy=True, program="source.exe")
        self.assertEqual(result.text, "word")
        self.clipboard.get_text_after_copy.assert_not_called()
        self.send_copy.assert_not_called()

    def test_empty_blocked_errors_and_timeouts_never_copy(self):
        for status in ("empty", "blocked", "error", "timeout"):
            with self.subTest(status=status):
                self.reader.read.return_value = SelectionResult(status)
                self.assertEqual(self.service.capture(1, allow_copy=True, program="source.exe").status, status)
                self.clipboard.get_text_after_copy.assert_not_called()

    def test_unsupported_does_not_copy_by_default_or_in_terminal_hosts(self):
        self.reader.read.return_value = SelectionResult("unsupported")
        self.service.capture(1, program="source.exe")
        for program in ("pwsh.exe", "WindowsTerminal.exe", "code.exe", "idea64.exe", ""):
            self.service.capture(1, allow_copy=True, program=program)
        self.clipboard.get_text_after_copy.assert_not_called()

    def test_explicit_fallback_runs_once_after_read_retries(self):
        self.reader.read.return_value = SelectionResult("unsupported")
        self.clipboard.get_text_after_copy.return_value = "copied text"
        result = self.service.capture(10, allow_copy=True, program="source.exe")
        self.assertEqual((result.text, result.method), ("copied text", "clipboard"))
        self.assertEqual(self.reader.read.call_count, 3)
        self.clipboard.get_text_after_copy.assert_called_once()

    def test_late_selection_is_retried_without_copying(self):
        self.reader.read.side_effect = [SelectionResult("empty"), SelectionResult("selected", "ready")]
        self.assertEqual(self.service.capture(1).text, "ready")
        self.clipboard.get_text_after_copy.assert_not_called()

    def test_changed_request_cannot_fall_back_or_return_old_text(self):
        self.reader.read.return_value = SelectionResult("selected", "old")
        result = self.service.capture(1, allow_copy=True, program="source.exe",
                                      is_current=Mock(side_effect=[True, False]))
        self.assertEqual(result.status, "cancelled")
        self.clipboard.get_text_after_copy.assert_not_called()

    def test_diagnostics_do_not_log_selected_text(self):
        self.reader.read.return_value = SelectionResult("selected", "private selection")
        with self.assertLogs("core.selection", level="INFO") as logs:
            self.service.capture(1, program="source.exe")
        self.assertNotIn("private selection", " ".join(logs.output))
        self.assertIn("method=uia", " ".join(logs.output))

    def test_selection_that_settles_after_180ms_is_captured(self):
        clock = [0.08]
        self.reader.read.side_effect = lambda *a, **k: (
            SelectionResult("selected", "late selection") if clock[0] >= 0.18 else SelectionResult("empty"))
        with patch("core.selection.time.monotonic", side_effect=lambda: clock[0]), \
                patch("core.selection.time.sleep", side_effect=lambda delay: clock.__setitem__(0, clock[0] + delay)):
            result = self.service.capture(1)
        self.assertEqual(result.text, "late selection")
        self.assertGreaterEqual(clock[0], 0.18)
        self.send_copy.assert_not_called()

    def test_cancel_during_settling_stops_without_copy(self):
        self.reader.read.return_value = SelectionResult("unsupported")
        current = [True]
        with patch("core.selection.time.sleep", side_effect=lambda _: current.__setitem__(0, False)):
            result = self.service.capture(1, allow_copy=True, program="weixin.exe", is_current=lambda: current[0])
        self.assertEqual(result.status, "cancelled")
        self.clipboard.get_text_after_copy.assert_not_called()

    def test_hard_worker_timeout_is_not_retried_or_copied(self):
        self.reader.read.return_value = SelectionResult("timeout", reason="worker_deadline")
        self.service.capture(1, allow_copy=True, program="weixin.exe")
        self.reader.read.assert_called_once()
        self.clipboard.get_text_after_copy.assert_not_called()
