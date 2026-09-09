# 快捷键和退出问题修复

## 原因

1. 原代码使用 `keyboard.add_hotkey(..., trigger_on_release=True)`，且没有启用 suppress。当前安装的 keyboard 实现在 `direct_callback` 中先从 `_pressed_events` 删除松开的键，再由 `pre_process_event` 按当前按键集合寻找非拦截回调。因此松键事件处理时，组合键可能已经不完整，回调不会执行。旧测试仅检查注册参数，不能发现这个问题。
2. `_run_after_hotkey_release` 最多等 0.2 秒，然后不论修饰键是否松开都复制。用户还按着 Alt 时，发送的 Ctrl+C 不能可靠完成复制。
3. Qt 定时器让 Python 有机会处理 SIGINT，但默认 SIGINT 处理器会抛出 KeyboardInterrupt。异常发生在 Qt 调用的 Python slot 中，不会按预期传播到 `qt_app.exec()` 外层的 except，所以反复打印 traceback，Qt 仍在运行。
4. QApplication 默认在最后一个普通窗口关闭时退出，不适合常驻助手。原先的线程清理方法没有接入应用退出，Chat 窗口也可能在请求未结束时销毁 QThread。

## 修改文件

| 文件 | 作用 |
| --- | --- |
| `app.py` | SIGINT/SIGTERM/SIGBREAK 主动请求 Qt 退出；关闭最后一个窗口后继续驻留；统一退出清理；捕获为空时输出提示。 |
| `core/hotkey.py` | ctypes 调用 RegisterHotKey，以 Qt native event filter 接收 WM_HOTKEY；后台等待实际松键；超时取消；防止重复捕获；停止时注销并等待剪贴板恢复；注册冲突明确报错。 |
| `ui/toolbar.py` | 显示时不抢焦点；可见期间每 50ms 检查 Esc/外部左键点击；焦点转到结果窗时不误隐藏；隐藏后忽略迟到结果；退出时清理网络、聊天及朗读线程。 |
| `ui/translation_popup.py` | 结果显示时不抢焦点，移除容易误关闭结果的 focusOutEvent；隐藏由工具栏统一管理。 |
| `ui/workers.py` | 通过工作线程自己的 asyncio loop 取消异步请求；处理启动前取消及资源清理。 |
| `ui/chat_window.py` | 关闭前取消并等待请求结束；聊天内容按纯文本显示，避免 HTML 字符串被 QTextEdit 当成富文本。 |
| `tests/test_app.py` | 子进程验证 SIGINT 可以离开真实 Qt 事件循环、恢复信号处理器并执行清理；验证常驻设置。 |
| `tests/test_hotkey.py` | 验证原生消息分发、注册失败、后台回调、超时不复制、延迟松键、重复触发、停止和异常日志。 |
| `tests/test_toolbar.py` | 新增隐藏后迟到结果、清除旧选区、无焦点时 Esc/外部点击及结果内点击回归测试。 |
| `tests/test_chat.py` | 新增关闭进行中的聊天请求及纯文本显示回归测试。 |
| `tests/test_workers.py` | 验证异步操作取消后执行 finally，以及启动前取消。 |
| `docs/Bugfix-hotkey-and-exit.md` | 本次修复说明和验收步骤。 |

未新增依赖。keyboard 继续用于发送 Ctrl+C，快捷键注册使用 Python 标准库 ctypes 和已有的 PySide6。

## 调用链

```text
Ctrl+Alt+Space
  -> Windows RegisterHotKey / WM_HOTKEY
  -> GlobalHotkey.nativeEventFilter（Qt 主线程，仅调度）
  -> _run_after_hotkey_release（后台线程，等待松键，最多 2 秒）
  -> handle_hotkey
  -> SelectionService.get_selected_text
  -> ClipboardService.get_text_after_copy（保存文本、哨兵、Ctrl+C、轮询、恢复）
  -> SelectionNotifier.selection_ready
  -> FloatingToolbar.show_for_selection（Qt 主线程）

终端 Ctrl+C -> Python SIGINT 处理器 -> QApplication.quit
  -> aboutToQuit -> 注销快捷键、等待选区线程、取消网络请求、等待工作线程
```

RegisterHotKey 把指定组合键注册给当前线程，Windows 将触发消息投递给该线程的消息循环；MOD_NOREPEAT 避免长按重复消息。Qt 已有 Windows 消息循环，无需再加一套键盘监听循环。参见 [Microsoft RegisterHotKey 文档](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-registerhotkey)。

退出清理连接 aboutToQuit，并保留 finally 作为启动失败的清理路径；通过标记保证只执行一次。参见 [Qt QCoreApplication 文档](https://doc.qt.io/qtforpython-6/PySide6/QtCore/QCoreApplication.html)。

## 运行和测试

在项目根目录运行：

```powershell
conda activate copilot
python -m pip install -r requirements.txt
python app.py
```

依赖已经安装时可以省略 pip 命令。弹出工具栏不需要 API 配置；翻译、解释和 Chat 使用已有 `.env` 中的 BASE_URL、API_KEY、MODEL。

自动测试：

```powershell
python -m unittest discover -s tests -v
python -m compileall -q app.py core ui services tests
```

手动验收：

1. 先在记事本输入并选中一段普通文字，按 Ctrl+Alt+Space 后松开全部按键。鼠标附近应显示工具栏，源窗口保持焦点。
2. 终端应依次出现 `Hotkey received` 和 `Selected text captured`。只出现前者时，查看是否有松键超时、空选区或剪贴板错误提示。没有前者说明触发消息未到达，检查是否运行新版进程、快捷键是否注册成功。
3. 再选另一段文字并触发，确认内容更新。试着按住修饰键约半秒后松开，仍应成功；超过 2 秒则应取消并提示，不应错误发送复制。
4. 点击译/解释，结果应显示；点结果内部可以操作文本。按 Esc 或点击外部，应隐藏工具栏和结果。
5. 请求未返回时隐藏工具栏，迟到结果不应让结果窗重新出现。
6. 打开 Chat 并发送请求，然后关闭 Chat；应用应继续驻留，请求应被取消。再次选词仍能显示工具栏。
7. 回到启动程序的终端按 Ctrl+C，应输出 `Selection Copilot stopped.` 并回到 PowerShell 提示符。再次启动应能注册同一快捷键。
8. 再分别测试浏览器、PDF 阅读器和 IDE。某些编辑器无选区时 Ctrl+C 会复制整行，不能以它们验证“空选区”。

本次在 copilot 环境运行自动测试，并额外做了原生消息冒烟验证：真实 RegisterHotKey 注册 -> 向当前线程投递 WM_HOTKEY -> 后台返回测试文本 -> 真实 Qt 工具栏可见 -> SIGINT 正常退出。该验证未模拟实体按键，也未从外部应用抓取真实选区，不等同于上述手动兼容性测试。没有调用真实 LLM API。

## 已知限制和后续目标

- 当前仍是剪贴板 fallback，只保存和恢复纯文本；不能完整保留图片、文件列表、HTML 等格式。并发剪贴板写入及极慢复制仍有竞争风险。
- 不支持复制的控件、扫描版 PDF、受保护输入框、部分管理员程序可能无法读取。某些 IDE 无选区时复制整行，当前无法区分这是否是真实选区。
- 网络请求支持取消；本地 TTS 仍使用同步 runAndWait，退出时会等待当前朗读结束。
- 工具栏外部点击采用短周期状态轮询，极短点击可能漏检；可用 Esc 隐藏。
- 下一步自然是 Phase 7 的系统托盘和快捷键设置，提供可见的退出入口及冲突后的改键能力。剪贴板/UI Automation 双通道属于后续兼容性阶段；本次没有实现自动划词。

建议亲自阅读这三个函数：

1. `GlobalHotkey._run_after_hotkey_release`：理解为什么“收到快捷键”不等于“可以立即模拟 Ctrl+C”，以及如何处理停止和超时。
2. `app.main`：理解 Python 信号、Qt 主循环、跨线程 Signal/Slot 和退出清理的连接方式。
3. `AsyncTextWorker.cancel`：理解如何把取消操作安全投递到另一个线程的 asyncio loop，避免窗口关闭后线程仍被销毁。
