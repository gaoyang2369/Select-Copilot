from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from config.paths import application_dir
from config.settings import SettingsStore


class RuntimeTests(unittest.TestCase):
    def test_frozen_env_is_next_to_executable_and_settings_in_user_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(sys, "frozen", True, create=True), patch.object(sys, "executable", str(root / "SelectionCopilot.exe")), patch.dict(os.environ, {"LOCALAPPDATA": str(root / "user")}):
                self.assertEqual(application_dir(), root.resolve())
                store = SettingsStore()
                self.assertEqual(store.env_path, root / ".env")
                self.assertEqual(store.path, root / "user" / "SelectionCopilot" / "settings.json")

    def test_file_logging_without_console(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, "-c", '''
import logging, sys
from core.runtime import configure_logging
sys.stdout = sys.stderr = None
configure_logging()
logging.getLogger('test').info('windowed logging works')
logging.shutdown()
'''], env={**os.environ, "LOCALAPPDATA": directory}, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("windowed logging works", (Path(directory) / "SelectionCopilot/logs/app.log").read_text(encoding="utf-8"))

    def test_second_instance_delivers_commands_and_lock_is_released(self):
        script = '''
import os, subprocess, sys
from PySide6.QtCore import QCoreApplication, QTimer
from core.runtime import SingleInstance
application = QCoreApplication([])
instance = SingleInstance()
assert instance.start()
commands = []
instance.requested.connect(commands.append)
client_code = "from PySide6.QtCore import QCoreApplication; from core.runtime import SingleInstance; a=QCoreApplication([]); s=SingleInstance(); assert not s.start('show')"
child = subprocess.Popen([sys.executable, '-c', client_code], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
instance.requested.connect(lambda _: QTimer.singleShot(50, application.quit))
QTimer.singleShot(5000, application.quit)
application.exec()
stdout, stderr = child.communicate(timeout=5)
assert child.returncode == 0, stderr
assert commands == ['show'], commands
instance.close()
replacement = SingleInstance()
assert replacement.start()
replacement.close()
assert not SingleInstance().start('quit')
'''
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, "-c", script], env={**os.environ, "LOCALAPPDATA": directory}, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
