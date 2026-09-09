# 双击选词与 Alt+Q

现在自动划词支持两种手势：拖动选择文字、双击选中单词。普通单击不触发。默认全局快捷键改为 **Alt+Q**。

## 修改文件

- `core/mouse.py`：扩展原有 DragDetector，以两次按下的时间、位置及目标控件判断双击；第二次松开后才发出候选通知。鼠标监听启动时读取 Windows 双击时间和矩形范围；暂停/重新开启时刷新。保留拖动、前台校验、自身窗口过滤及输入转发。
- `core/hotkey.py`：默认值和错误示例改为 alt+q；原来的其他组合仍可在设置中使用。
- `ui/settings_dialog.py`：更新快捷键提示及“拖动或双击”说明。
- `.env`、`.env.example`：HOTKEY 设置为 alt+q。本机修改仅针对 HOTKEY，不输出或改写其他凭据。修改时未发现已保存的 JSON 设置覆盖该值。
- `tests/test_mouse.py`：双击释放时机、超时、距离、不同目标、长按、时间戳回绕、拖动混合、重置及钩子转发测试。
- `tests/test_hotkey.py`、`tests/test_settings.py`：默认 Alt+Q 注册、Q 松开等待及语法测试。
- `tests/test_controller.py`：双击候选接入现有延迟捕获链路的回归测试。
- `docs/Phase7-8-implementation.md`、`artifacts/phase7-settings.png`：同步当前操作方式和界面。
- `docs/Double-click-and-hotkey.md`：本说明。

## 调用链与关键函数

```text
第一次按下/松开 -> 记录一次单击
第二次按下 -> 时间、位置、目标控件匹配
第二次松开 -> dragged 候选信号（复用原信号名称）
  -> 原有约 100ms 延迟 -> 后台复制并恢复剪贴板 -> 工具栏

Alt+Q -> 等待 Alt 和 Q 松开 -> 原有手动选区捕获链路
```

值得阅读 `DragDetector.feed`：双击仅有两次普通按下/松开，没有拖动距离，因此需要补充点击历史；同时不能把慢速或不同控件的两次单击混为双击。

另一个核心是 `MouseSelectionListener._hook_callback`：向判定器传入鼠标事件时间和实际目标控件，只发出候选通知，始终转发原鼠标事件。之后由已有控制器延迟读取，避免第二次按下时目标软件尚未完成选词。

Windows 使用双击时间和空间范围判定双击，依据 [Microsoft GetSystemMetrics](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getsystemmetrics) 与 [官方点击识别示例](https://devblogs.microsoft.com/oldnewthing/20041018-00/?p=37543)。

## 运行和验收

从托盘退出旧进程，然后运行：

```powershell
conda activate copilot
python app.py
```

1. 在浏览器或记事本双击英文单词，第二次松开后应出现工具栏。
2. 普通单击、间隔较长的两次单击、在相距明显的两个位置单击，不应触发。
3. 拖动选词仍应正常；助手设置、Chat、结果窗内部双击不应触发自动捕获。
4. 在托盘暂停自动划词后，拖动与双击均不自动弹出，但选词后按 Alt+Q 仍可触发。
5. 设置窗口应显示 alt+q；Alt+Q 被其他程序占用时仍会明确报错，可在设置中换键。

自动测试：

```powershell
python -m unittest discover -s tests -v
python -m compileall -q app.py core config ui services tests
```

回归测试使用合成鼠标事件和模拟选区，不调用真实 API，不代表所有外部软件已经通过实际双击验收。

## 限制与下一步

当前仍依赖目标软件的 Ctrl+C 复制行为。双击控件、文件或标题栏等非文本区域也是双击手势，只会尝试读取，不能保证有可用文本；无文字时不会弹出。自定义双击逻辑和三击选段暂不单独适配。剪贴板格式及应用权限的既有限制保留。

下一步可以按计划准备 exe 打包；常用软件的特殊选区兼容性继续单独改进。
