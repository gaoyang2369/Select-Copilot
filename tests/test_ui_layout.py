"""Layout regression checks in fresh Qt processes at fractional DPI scales."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


class DpiLayoutTests(unittest.TestCase):
    def test_widgets_fit_the_screen_at_common_scales(self) -> None:
        script = textwrap.dedent('''
            import os
            from pathlib import Path
            from PySide6.QtCore import QPoint
            from PySide6.QtGui import QFontDatabase
            from PySide6.QtWidgets import QApplication
            from ui.chat_window import ChatWindow
            from ui.toolbar import FloatingToolbar
            app = QApplication([])
            if not QFontDatabase.families():
                for name in ("segoeui.ttf", "msyh.ttc"):
                    QFontDatabase.addApplicationFont(str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name))
            available = app.primaryScreen().availableGeometry()
            toolbar = FloatingToolbar()
            toolbar.show_for_selection("context")
            toolbar._dismiss_timer.stop()
            toolbar.move(toolbar._position_near(available.bottomRight()))
            popup = toolbar._translation_popup
            popup.show_message("A long explanation. " * 500, toolbar)
            chat = ChatWindow("context", object())
            chat.show()
            app.processEvents()
            for window in (toolbar, popup, chat):
                assert available.contains(window.frameGeometry()), (window.objectName(), window.frameGeometry(), available)
            assert not popup.frameGeometry().intersects(toolbar.frameGeometry())
            assert chat._messages.viewport().height() >= 40
            assert chat.rect().contains(chat._send_button.mapTo(chat, QPoint(0, 0)))
            assert chat._input.height() >= chat.fontMetrics().lineSpacing() * 2
            for button in (toolbar._translate_button, toolbar._tts_button, toolbar._explain_button, toolbar._chat_button, chat._send_button):
                assert button.width() >= button.fontMetrics().horizontalAdvance(button.text()) + 12
            if chat.height() < 560:
                assert not chat._context.isVisible()
            chat._input.setPlainText("line\\n" * 20)
            chat._context_toggle.setChecked(True)
            app.processEvents()
            assert available.contains(chat.frameGeometry()), (chat.frameGeometry(), available)
            assert chat._messages.viewport().height() >= 40
            toolbar.shutdown()
            toolbar.close()
            chat.close()
        ''')
        for scale in ("1", "1.25", "1.5", "2"):
            with self.subTest(scale=scale):
                result = subprocess.run(
                    [sys.executable, "-c", script],
                    cwd=Path(__file__).resolve().parents[1],
                    env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_SCALE_FACTOR": scale},
                    capture_output=True, text=True, timeout=20,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
