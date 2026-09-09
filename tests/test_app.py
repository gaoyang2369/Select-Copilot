from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


class ApplicationLifecycleTests(unittest.TestCase):
    def test_sigint_exits_qt_and_cleans_up(self) -> None:
        script = textwrap.dedent('''
            import signal
            from unittest.mock import patch
            from PySide6.QtCore import QTimer
            from PySide6.QtWidgets import QApplication, QWidget
            import app

            original_handler = signal.getsignal(signal.SIGINT)
            timers = []
            windows = []
            def start():
                assert not QApplication.instance().quitOnLastWindowClosed()
                window = QWidget()
                windows.append(window)
                window.show()
                window.close()
                timer = QTimer()
                timer.setSingleShot(True)
                timer.timeout.connect(lambda: signal.raise_signal(signal.SIGINT))
                timers.append(timer)
                timer.start(100)
            with patch('app.GlobalHotkey') as hotkey, patch('app.FloatingToolbar') as toolbar:
                hotkey.return_value.start.side_effect = start
                app.main()
                assert hotkey.return_value.stop.called
                assert toolbar.return_value.shutdown.called
                assert signal.getsignal(signal.SIGINT) == original_handler
        ''')
        result = subprocess.run(
            [sys.executable, '-c', script],
            cwd=Path(__file__).resolve().parents[1],
            env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'},
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('Selection Copilot stopped.', result.stdout)
        self.assertNotIn('KeyboardInterrupt', result.stderr)
