"""Optional desktop smoke test of the actual exe, using temporary API settings.

Requires pywinauto and six under build/qa-deps (see docs/Packaging.md).
Opens a test text field, briefly speaks 'Hello', and uses Ctrl+Shift+F12.
"""

from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'build/qa-deps'))
from pywinauto import Application

class Handler(BaseHTTPRequestHandler):
    requests = []

    def log_message(self, *args):
        pass

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        assert request['stream'] is True
        self.requests.append(request)
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.end_headers()
        for part in ['打包', '测试通过']:
            self.wfile.write(('data: ' + json.dumps({'choices': [{'delta': {'content': part}}]}) + '\n\n').encode())
            self.wfile.flush()
            time.sleep(0.05)
        self.wfile.write(b'data: [DONE]\n\n')

server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()

def verify_actions(ui, directory):
    code = "from PySide6.QtWidgets import QApplication, QLineEdit, QWidget, QVBoxLayout; from PySide6.QtCore import QTimer; a=QApplication([]); w=QWidget(); e=QLineEdit('Hello'); QVBoxLayout(w).addWidget(e); w.setWindowTitle('Selection Copilot smoke source'); w.resize(400,80); w.show(); e.selectAll(); e.setFocus(); QTimer.singleShot(30000,a.quit); a.exec()"
    helper = subprocess.Popen([sys.executable, '-c', code], cwd=directory, creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        source = Application(backend='uia').connect(process=helper.pid, timeout=10).window(title='Selection Copilot smoke source')
        source.wait('visible', timeout=10)
        source.set_focus()
        time.sleep(0.2)
        # The test instance reserves this shortcut; Alt+Q is left alone.
        source.type_keys('^+{F12}')
        toolbar = ui.window(auto_id='QApplication.floatingToolbar')
        toolbar.wait('visible', timeout=10)
        toolbar.child_window(title='译', control_type='Button').invoke()
        popup = ui.window(auto_id='QApplication.translationPopup')
        popup.wait('visible', timeout=10)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            result = popup.descendants(control_type='Edit')[0].get_value()
            if result == '打包测试通过':
                break
            time.sleep(0.1)
        assert result == '打包测试通过', result
        assert len(Handler.requests) == 1
        print('EXE_SELECTION_AND_STREAMING_HTTP_OK', flush=True)
        toolbar.child_window(title='解释', control_type='Button').invoke()
        time.sleep(1)
        assert len(Handler.requests) == 2, 'Explanation did not send a request'
        assert popup.descendants(control_type='Edit')[0].get_value() == '打包测试通过'
        print('EXE_EXPLANATION_OK', flush=True)
        speech = toolbar.descendants(control_type='Button')[1]
        speech.invoke()
        deadline = time.monotonic() + 15
        time.sleep(1)
        while not speech.is_enabled() and time.monotonic() < deadline:
            time.sleep(0.2)
        assert speech.is_enabled(), 'Speech did not finish'
        result = popup.descendants(control_type='Edit')[0].get_value()
        assert 'TTS failed' not in result, result
        print('EXE_SAPI_SPEECH_OK', flush=True)
    finally:
        if sys.exc_info()[0] is not None:
            print((Path(directory) / 'SelectionCopilot/logs/app.log').read_text(encoding='utf-8'), flush=True)
            print('APP_WINDOWS', [(w.window_text(), w.automation_id()) for w in ui.windows()], flush=True)
        helper.terminate()
        helper.wait(timeout=5)

exe = ROOT / 'dist/SelectionCopilot/SelectionCopilot.exe'
with tempfile.TemporaryDirectory(prefix='selection-copilot-smoke-') as directory:
    env = dict(os.environ)
    for key in ('API_KEY', 'BASE_URL', 'MODEL', 'HOTKEY', 'AUTO_SELECT', 'PYTHONPATH', 'PYTHONHOME', 'QT_PLUGIN_PATH', 'QT_QPA_PLATFORM', 'CONDA_PREFIX'):
        env.pop(key, None)
    env['LOCALAPPDATA'] = directory
    env['NO_PROXY'] = '127.0.0.1,localhost'
    env['PATH'] = str(Path(os.environ['SystemRoot']) / 'System32')
    log = Path(directory) / 'SelectionCopilot/logs/app.log'
    process = subprocess.Popen([str(exe)], cwd=directory, env=env, creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        ui = Application(backend='uia').connect(process=process.pid, timeout=15)
        dialog = ui.window(title='Selection Copilot 设置')
        dialog.wait('visible', timeout=15)
        print('FIRST_RUN_SETTINGS_VISIBLE', flush=True)
        edits = dialog.descendants(control_type='Edit')
        assert len(edits) == 4, len(edits)
        assert edits[0].get_value() == '', 'Unexpected embedded endpoint'
        assert edits[2].get_value() == '', 'Unexpected embedded model'
        assert edits[3].get_value() == 'alt+q'
        edits[3].set_edit_text('ctrl+shift+f12')
        edits[0].set_edit_text(f'http://127.0.0.1:{server.server_port}/v1')
        edits[1].set_edit_text('smoke-test-key')
        edits[2].set_edit_text('smoke-model')
        dialog.child_window(title='保存', control_type='Button').invoke()
        dialog.wait_not('visible', timeout=5)
        saved = json.loads((Path(directory) / 'SelectionCopilot/settings.json').read_text(encoding='utf-8'))
        assert saved['model'] == 'smoke-model'
        assert saved['hotkey'] == 'ctrl+shift+f12'
        print('SETTINGS_SAVED_AND_TRAY_LIFETIME_OK', flush=True)
        verify_actions(ui, directory)
        second = subprocess.run([str(exe)], cwd=directory, env=env, timeout=10)
        assert second.returncode == 0
        assert process.poll() is None
        dialog.wait('visible', timeout=5)
        print('SECOND_LAUNCH_REUSES_INSTANCE_AND_OPENS_SETTINGS', flush=True)
        subprocess.run([str(exe), '--quit'], cwd=directory, env=env, timeout=10, check=True)
        assert process.wait(timeout=10) == 0
        text = log.read_text(encoding='utf-8')
        assert 'started. Hotkey: alt+q' in text
        assert 'Selection Copilot stopped.' in text
        assert 'Traceback' not in text and 'ERROR' not in text, text
        assert 'smoke-test-key' not in text
        print('GRACEFUL_EXIT_AND_FILE_LOG_OK', flush=True)
        process = subprocess.Popen([str(exe), '--settings'], cwd=directory, env=env, creationflags=subprocess.CREATE_NO_WINDOW)
        ui = Application(backend='uia').connect(process=process.pid, timeout=15)
        dialog = ui.window(title='Selection Copilot 设置')
        dialog.wait('visible', timeout=15)
        assert dialog.descendants(control_type='Edit')[2].get_value() == 'smoke-model'
        subprocess.run([str(exe), '--quit'], cwd=directory, env=env, timeout=10, check=True)
        assert process.wait(timeout=10) == 0
        print('RESTART_AND_SAVED_SETTINGS_OK', flush=True)
    finally:
        if process.poll() is None:
            subprocess.run([str(exe), '--quit'], cwd=directory, env=env, timeout=10)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=5)
