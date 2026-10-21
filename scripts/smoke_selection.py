"""Read an owned Qt fixture through real Windows UIA, without copying or API calls.

The small fixture closes automatically. It does not read or change user apps.
Run with the same Windows Python environment as app.py.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.clipboard import clipboard
from core.mouse import MouseSelectionListener
from core.selection import SelectionService
from core.clipboard import ClipboardService
from PySide6.QtWidgets import QApplication

FIXTURE = r'''
import json, sys
from pathlib import Path
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication, QLineEdit, QVBoxLayout, QWidget
import win32gui
app = QApplication([])
window = QWidget()
window.setWindowTitle('Selection Copilot selection test')
window.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
window.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
edit = QLineEdit('alpha beta gamma')
QVBoxLayout(window).addWidget(edit)
window.resize(360, 70)
window.show()
path = Path(sys.argv[1])
last = None
def tick():
    global last
    state = path.read_text(encoding='utf-8')
    if state == last:
        return
    last = state
    edit.setEchoMode(QLineEdit.EchoMode.Password if state == 'password' else QLineEdit.EchoMode.Normal)
    edit.setSelection(6, 4)
    if state == 'empty':
        edit.deselect()
    rect = win32gui.GetWindowRect(int(edit.winId()))
    print(json.dumps({'window': int(window.winId()), 'point': [(rect[0]+rect[2])//2, (rect[1]+rect[3])//2]}), flush=True)
timer = QTimer()
timer.timeout.connect(tick)
timer.start(50)
QTimer.singleShot(12000, app.quit)
app.exec()
'''


def main() -> None:
    if sys.platform != "win32":
        raise SystemExit("This smoke test requires Windows.")
    # Match app.py's Qt DPI initialization before calling native screen APIs.
    application = QApplication([])
    listener = MouseSelectionListener()
    listener.start()
    try:
        assert listener.running and listener._keyboard_handle
        print("NATIVE_MOUSE_AND_KEYBOARD_HOOKS_OK")
    finally:
        listener.stop()
    with tempfile.TemporaryDirectory(prefix="selection-copilot-uia-") as directory:
        command = Path(directory) / "state.txt"
        command.write_text("selected", encoding="utf-8")
        environment = dict(os.environ)
        environment.pop("QT_QPA_PLATFORM", None)
        process = subprocess.Popen([sys.executable, "-u", "-c", FIXTURE, str(command)],
                                   env=environment, stdout=subprocess.PIPE, text=True,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        sequence = clipboard.GetClipboardSequenceNumber()
        try:
            with ThreadPoolExecutor(max_workers=1) as worker:
                for state in ("selected", "empty", "password"):
                    temporary = command.with_suffix(".tmp")
                    temporary.write_text(state, encoding="utf-8")
                    temporary.replace(command)
                    line = process.stdout.readline()
                    if not line:
                        raise RuntimeError("UIA fixture exited before responding")
                    source = json.loads(line)
                    service = SelectionService(ClipboardService(), lambda: False)
                    result = worker.submit(service.capture, source["window"],
                                           position=tuple(source["point"])).result(timeout=5)
                    expected = {"selected": "selected", "empty": "empty", "password": "blocked"}[state]
                    assert result.status == expected, (state, result.status)
                    if state == "selected":
                        assert result.text == "beta", "UIA returned something other than the selected range"
                    assert clipboard.GetClipboardSequenceNumber() == sequence, "UIA changed the clipboard"
                    print(f"UIA_{state.upper()}_OK (clipboard unchanged)")
        finally:
            process.terminate()
            process.wait(timeout=5)


if __name__ == "__main__":
    main()
