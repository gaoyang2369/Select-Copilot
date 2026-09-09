# Phase 7 / Phase 8 实现说明

## 已实现

Phase 7：系统托盘、设置窗口、`.env` 与 JSON 配置、模型/API 设置、快捷键设置、自动划词开关，以及已有流式/思考选项的界面设置。关闭设置或 Chat 窗口后继续驻留；托盘菜单提供明确的退出入口。

Phase 8：Windows 全局鼠标左键拖动结束后自动尝试读取文本并弹出工具栏。普通点击和小幅抖动不触发。保留默认 Alt+Q，也允许修改快捷键。

文档中“开机启动”是可选项，本次未添加，不修改开机启动项。自动划词只在本地读取选区，翻译、解释和 Chat 仍需要主动点击才会请求 API。

## 文件清单

| 文件 | 作用 |
| --- | --- |
| `config/__init__.py`、`config/settings.py` | 简单的 Settings 数据类和 SettingsStore；校验配置、读取 .env / 环境变量 / JSON、原子保存。 |
| `core/hotkey.py` | 支持设置快捷键；先注册新组合再注销旧组合，冲突不丢失旧快捷键；等待所配置的主键松开。 |
| `core/mouse.py` | 纯拖动判定器、WH_MOUSE_LL 钩子、独立消息循环、前台窗口和自身进程过滤、取消过期拖动。 |
| `app.py` | CopilotController 连接托盘、设置、鼠标与快捷键；延迟和串行捕获选区；设置失败回滚；统一清理。 |
| `ui/settings_dialog.py` | API 地址、Key、模型、快捷键、自动划词、流式和思考模式的设置表单。 |
| `ui/tray.py` | SC 托盘图标、状态、设置、自动划词开关、退出及双击打开设置。 |
| `ui/toolbar.py` | 应用新的服务设置；取消旧的工具栏请求，现有 Chat 保留原来的服务。 |
| `services/llm.py`、`services/translator.py` | 支持显式传入 stream/thinking，不再仅依赖环境变量，便于设置即时生效。 |
| `tests/test_settings.py` | 配置优先级、格式校验、失败写入保护、快捷键语法。 |
| `tests/test_mouse.py` | 点击/抖动/拖动判定、负坐标、自身窗口与注入事件过滤、钩子异常仍转发、前台和按键校验。 |
| `tests/test_controller.py` | 延迟捕获、暂停后快捷键可用、空选区、连续请求、设置回滚、模型更新及表单验证。 |
| `tests/test_hotkey.py` | 新增快捷键冲突保护及先注册再注销的回归测试。 |
| `tests/test_app.py` | 保留 SIGINT 退出测试，并隔离测试中的真实托盘和鼠标监听。 |
| `.env.example`、`.gitignore` | 初始配置示例，忽略本地密钥和 Python 缓存。 |
| `artifacts/phase7-settings.png` | 使用演示配置生成的设置窗口截图，不包含真实密钥。 |
| `docs/Phase7-8-implementation.md` | 本说明。 |

## 运行与配置

无需安装新依赖。在项目根目录运行：

```powershell
conda activate copilot
python app.py
```

启动后在 Windows 通知区域找到蓝色 **SC** 图标；图标可能在折叠菜单中。右键可以打开设置、暂停/恢复自动划词或退出；双击图标打开设置。没有可用托盘或监听启动失败时，程序会打开设置窗口。

配置优先级是 **保存的 JSON > 进程环境变量 > 项目 .env > 默认值**。`.env` 始终按项目绝对路径读取，与启动时工作目录无关。

JSON 保存位置：

```text
%LOCALAPPDATA%\SelectionCopilot\settings.json
```

设置窗口保存及托盘自动划词开关都会保存当前配置。API Key 使用密码框显示，并随设置保存在上述本机 JSON 中；该文件是普通本地文件，不做加密。已有 `.env` 不会被改写。读取损坏的 JSON 时会提示并使用初始配置，只有再次保存时才替换文件。

快捷键支持 ctrl、alt、shift、win 中一个或多个修饰键，加一个字母、数字、space 或 F1–F24。例如 `alt+q`、`ctrl+shift+f9`。操作系统保留或已被其他程序注册的组合可能失败，设置窗口会显示错误；正常情况下原快捷键保留。

保存设置后，新的翻译、解释及新开的 Chat 使用新配置，翻译缓存随新服务实例清空。已打开的 Chat 保留原模型及对话；要使用新模型请重新打开 Chat。DeepSeek 思考选项仍只对官方 V4 接口生效。

## 调用链

```text
鼠标左键按下 -> 记录起点、前台窗口和窗口位置
  -> MouseMove：累计判断是否超过 8 个物理像素
  -> 左键松开 -> dragged 信号 -> Qt 主线程
  -> 单次定时器等待约 100ms
  -> 检查窗口、按键、拖动版本和开关
  -> 后台线程读取选区（保存文本剪贴板 -> Ctrl+C -> 轮询 -> 恢复）
  -> capture_completed -> 再次校验请求 -> 工具栏显示

全局快捷键 -> 等待所有组合键松开 -> manual_requested
  -> 共用后台选区捕获流程 -> 工具栏显示

设置保存 -> 校验 -> 注册新快捷键 -> 开关鼠标监听
  -> 原子保存 JSON -> 应用新服务 -> 更新托盘

托盘退出 / Ctrl+C -> 停止定时器 -> 注销鼠标/快捷键
  -> 等待选区复制恢复 -> 取消网络请求并清理工作线程 -> 退出
```

新鼠标点击会改变拖动版本；前台窗口切换、窗口本身被移动、助手自身窗口、按键仍按住以及已经暂停时，不使用该拖动。复制前和结果显示前都会检查状态。快速连续选择时最新有效请求等待前一个捕获结束，旧结果会被丢弃。

## Windows Hook 原理

`SetWindowsHookExW(WH_MOUSE_LL, ...)` 安装低级鼠标钩子；Windows 会把鼠标事件回调到安装它的线程，因此该线程必须持续运行消息循环。本实现使用独立线程和 GetMessage/DispatchMessage，保留 ctypes 回调引用直到注销。

回调只处理左键按下、移动、松开，做轻量坐标/窗口检查并发出候选通知；不等待、不复制、不请求网络、不访问 QWidget。无论是否识别到拖动，始终返回 CallNextHookEx 的结果，让鼠标事件继续传递。程序不会拦截原始点击或拖动。详见 [Microsoft LowLevelMouseProc](https://learn.microsoft.com/zh-cn/windows/win32/winmsg/lowlevelmouseproc)。

托盘使用已有 PySide6 的 QSystemTrayIcon，无需新依赖。详见 [Qt 文档](https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QSystemTrayIcon.html)。

## 测试和验收

```powershell
python -m unittest discover -s tests -v
python -m compileall -q app.py core config ui services tests
```

测试不请求真实 API。额外做过真实 Windows 钩子安装、托盘显示和快捷键更换的冒烟验证；用模拟拖动完成通知和测试选区验证延迟弹窗、暂停后的手动回退及退出清理。这不等同于对所有外部软件做了真实拖选测试。

手动步骤：

1. 启动一个新版进程，在记事本输入几句文字，拖动选择后松开。无需快捷键，工具栏应在鼠标附近出现。普通点击和小抖动不应弹出。
2. 分别在浏览器、IDE、可复制文本的 PDF 中测试；先确认这些程序支持 Ctrl+C 复制选区。
3. 在助手设置、Chat 或结果文本内部拖选，不应触发自动划词。
4. 在托盘取消“自动划词”，拖选不再弹出，但 Alt+Q 仍然有效。重新勾选应恢复。
5. 打开设置，修改模型和快捷键并保存。新快捷键应立即可用，旧组合不再触发；退出并重启后仍保留新值。
6. 尝试一个已被占用的快捷键；应显示错误，配置不保存，原快捷键仍可用。
7. 快速连续拖选不同内容或拖选后立即切换程序，旧选区不应弹出到新程序上。
8. 关闭设置和 Chat，应用仍驻留；从托盘退出或回终端按 Ctrl+C，程序应结束并释放快捷键。再次启动应成功。

## 已知限制与下一阶段

- 当前仍使用 Clipboard fallback，没有实现 Phase 9 的 UI Automation，因此“拖动”只是候选信号。拖滚动条、拖文件或某些 IDE 无选区复制整行可能产生误判；可从托盘暂停自动划词，使用快捷键。
- 不支持复制的控件、扫描 PDF、受保护输入框或不同权限的应用可能无法获取文字。自动读取期间会模拟一次 Ctrl+C，虽然钩子不拦截鼠标，复制动作仍可能触发目标程序对该快捷键的行为。
- 剪贴板仍只恢复纯文本，不完整保留图片、文件列表和富文本，也不能完全避免其他程序同时写剪贴板的竞争。自动划词更依赖这条链路，兼容性优化应优先处理。
- 窗口在同一前台程序内切换内部页签、复制前极短时刻发生焦点变化等情况仍可能无法完全识别。
- 各进程之间不共享捕获锁，应只启动一个助手进程；已有实例占用快捷键时会提示。
- 本地 TTS 退出时仍可能等待当前朗读结束；开机启动是可选项，本次未实现。
- 下一阶段最自然是 Phase 9：UI Automation 优先读取真实选区，Clipboard 作为后备，并改进剪贴板格式保护与应用兼容性。

建议阅读三个核心函数：`MouseSelectionListener._hook_callback`（如何观察而不阻塞输入）、`CopilotController._start_capture`（如何延后和串行读取选区）、`CopilotController.apply_settings`（设置即时应用与失败回滚）。
