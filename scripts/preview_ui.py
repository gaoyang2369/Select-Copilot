"""Render the actual widgets with local sample content; no hooks or API calls."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SELECTION = "An event loop runs asynchronous tasks and callbacks."
ANSWER = """**事件循环**负责调度异步任务，让等待 I/O 的时间可以用于处理其他工作。

1. 遇到 `await` 时，当前任务可以让出执行权。
2. 事件循环继续运行其他已就绪的任务。
3. I/O 完成后，原任务恢复执行。

例如，下面的代码会并发等待两个请求：

```python
results = await asyncio.gather(fetch(url_a), fetch(url_b))
```

这适合网络请求等 **I/O 密集型任务**。CPU 密集型计算通常需要线程或进程配合。
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "build/ui-preview")
    parser.add_argument("--scale", choices=("1", "1.25", "1.5", "2"), default="1")
    parser.add_argument("--show", action="store_true", help="Open an interactive preview instead of using offscreen Qt")
    args = parser.parse_args()
    os.environ["QT_SCALE_FACTOR"] = args.scale
    if not args.show:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"

    from PySide6.QtGui import QFontDatabase, QTextCursor
    from PySide6.QtWidgets import QApplication
    from ui.chat_window import ChatWindow
    from ui.toolbar import FloatingToolbar

    class SampleService:
        async def chat(self, messages, *, on_delta=None):
            return ANSWER

        async def ask(self, prompt, *, on_delta=None):
            return ANSWER

        async def translate(self, text, *, on_delta=None):
            return "事件循环运行异步任务和回调。"

        def speak(self, text):
            pass  # Preview controls never invoke a real service.

    application = QApplication([])
    # Qt's Windows offscreen plugin has no system font discovery. Register the
    # local fonts for screenshots only; the normal desktop plugin discovers them.
    if not QFontDatabase.families():
        for name in ("segoeui.ttf", "seguisb.ttf", "msyh.ttc", "consola.ttf"):
            QFontDatabase.addApplicationFont(str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name))
    sample = SampleService()
    toolbar = FloatingToolbar(translator=sample, tts_service=sample, llm_service=sample)
    toolbar.show_for_selection(SELECTION)
    toolbar._dismiss_timer.stop()
    popup = toolbar._translation_popup
    popup.set_heading("解释")
    popup.show_message(ANSWER, toolbar, markdown=True)
    chat = ChatWindow(SELECTION, SampleService())
    chat._append_message("You", "如何理解事件循环？请给一个简单例子。")
    cursor = QTextCursor(chat._messages.document())
    cursor.movePosition(QTextCursor.MoveOperation.End)
    chat._messages.insert_message(cursor, "AI", ANSWER, markdown=True)
    chat._input.setPlainText("它与多线程有什么区别？")
    chat.show()
    application.processEvents()
    chat._messages.verticalScrollBar().setValue(0)
    args.output.mkdir(parents=True, exist_ok=True)
    for name, widget in (("toolbar", toolbar), ("result", popup), ("chat", chat)):
        widget.grab().save(str(args.output / f"{name}.png"))
        print(f"{name}: {widget.width()}x{widget.height()} logical px, DPR={widget.devicePixelRatioF():g}")
    if args.show:
        application.exec()
    toolbar.shutdown()
    toolbar.close()
    if not args.show:
        chat.close()


if __name__ == "__main__":
    main()
