# 真实选区与唤醒交互优化

本次解决“选词后有时不出现”和“频繁发送 Ctrl+C”的共同原因：旧实现用拖动/双击猜测有选区，然后直接复制来试取文字。现在先读取真实选区，再按明确的策略决定是否允许复制兜底。

## 当前行为

| 场景 | 行为 |
| --- | --- |
| 默认自动划词 | UIA 读取，零模拟复制 |
| Alt+Q 或自定义快捷键 | UIA 优先；只有 unsupported 才允许一次兼容复制 |
| 设置为禁用模拟复制 | 自动及快捷键均只使用 UIA |
| 设置为指定应用自动兼容 | 快捷键保留兼容；自动划词仅对名单内进程允许复制 |
| 确认无选区、密码框、UIA 异常或超时 | 不触发复制 |
| 终端、常见 IDE 宿主 | 禁止模拟复制；UIA 可读时仍正常工作 |
| 托盘“使用剪贴板文字” | 只读取用户已复制的文字，不发送任何按键 |

设置里的应用名单使用 `acrobat.exe, reader.exe` 这样的进程文件名，忽略大小写；支持中文逗号和分号。原 JSON 配置无需手动迁移，新字段默认 `clipboard_fallback=manual`。`.env.example` 增加了对应环境变量，已有保存设置优先。

自动识别覆盖拖选、双击、三击、Shift 单击扩选、Shift 配合方向/Home/End/Page 键，以及 Ctrl+A。键盘监听只识别动作，不保存按键内容，始终转发原始输入。未订阅全桌面 UIA 事件，也没有持续扫描全部应用。

## 文件及作用

| 文件 | 作用 |
| --- | --- |
| `core/uia.py` | MTA 线程内创建 UIA 客户端，限时、限深度读取真实选区，返回状态、文字和物理坐标 |
| `core/selection.py` | 区分空选区与不支持；有限次数重读 UIA、复制资格检查、应用排除、耗时日志 |
| `core/clipboard.py` | 去掉随机哨兵；备份已支持格式，检测剪贴板更新并有条件地恢复 |
| `core/mouse.py` | 原生鼠标/键盘钩子、跨窗口开始拖选、系统拖动阈值、Shift/三击和键盘选区、过期输入版本 |
| `core/hotkey.py` | 在收到 WM_HOTKEY 时保存来源窗口，等待松键后继续使用原来源 |
| `app.py` | 候选合并、最新请求优先、受控复制、显式剪贴板入口、手动失败反馈 |
| `config/settings.py`、`ui/settings_dialog.py` | 复制范围、兼容应用和暂停应用；滚动设置区适应较小屏幕 |
| `ui/toolbar.py` | 选区末端/鼠标松开位置作为锚点；转换 Windows 物理坐标到 Qt 逻辑坐标 |
| `ui/tray.py` | 手动使用剪贴板文字的入口 |
| `requirements.txt`、`SelectionCopilot.spec` | 明确 comtypes/pywin32 依赖并打包生成的 UIA 类型库，移除 pyperclip |
| `tests/test_uia.py`、`tests/test_clipboard.py` | 新增选区真实性、范围约束、密码框、格式备份与竞争条件测试 |
| `tests/test_selection.py`、`tests/test_controller.py`、`tests/test_mouse.py`、`tests/test_hotkey.py`、`tests/test_settings.py` | 更新调用契约，覆盖复制策略、取消、手势、热键来源和旧配置迁移 |
| `scripts/smoke_selection.py`、`scripts/smoke_windows.py` | 原生取词验证及打包 exe 冒烟检查 |
| README、文档入口、Windows 使用说明、`.env.example` | 同步当前操作方式、配置与限制 |

## 关键调用链

```text
原生鼠标 / 键盘事件（只观察并转发）
  → Drag 候选，携带来源、输入版本及松开位置
  → Controller 合并等待 80ms
  → 后台 SelectionService.capture
  → UIASelectionReader.read：初始化 MTA → 创建 UIA → 校验窗口祖先链
    → TextPattern.GetSelection → 读取选区及矩形 → 释放 COM
      ├─ selected → 回到 Qt → 再校验版本/前台 → 定位工具栏
      ├─ empty / blocked / error / timeout → 结束
      └─ unsupported → 检查复制策略和应用 → 最多一次 Ctrl+C

快捷键 WM_HOTKEY → 保存原前台窗口 → 等待松键 → 共用捕获流程
托盘使用剪贴板 → 后台读取文字 → 工具栏（无模拟复制）
```

UIA 从鼠标下控件和焦点控件开始，在来源窗口内最多向上查找 16 层；不搜索整个桌面的子树。只用 TextPattern.GetSelection，不将 DocumentRange、Value 或控件名称当作选区。最多读取 64 段、100,000 个字符；读取不到选区矩形仍可使用文字。鼠标落在滚动条、滑块、按钮、标题栏等非文本控件时不重新弹出旧选区。

选择状态未就绪时，最多重读三次，间隔 35ms；不会重发复制。UIA ConnectionTimeout/TransactionTimeout 均为 200ms，遍历预算 400ms。这些设置限制正常调用等待，但不是可强制终止任意第三方 COM 调用的硬边界。

复制前仍等待鼠标和修饰键松开（最多 600ms）；窗口切换、更新输入、Esc、设置变化和退出都会使请求失效。钩子内不做 UIA、剪贴板或网络工作。

## 剪贴板保护与限制

兼容路径不写入哨兵。先备份当前格式并保存序号，发送一次复制，再等待剪贴板更新及约 40ms 稳定时间。只有所有者进程与来源相符时读取；恢复前在剪贴板锁内再检查序号、所有者及请求有效性，发现竞争就保留较新的内容。

支持备份 Unicode/ANSI/OEM 文本、Locale、HTML/RTF、DIB/DIBV5 和文件列表。对于位图句柄、OLE/私有格式、无法读取的格式或超过 16 MiB 的内容，整次复制跳过，保持原剪贴板。某些图片会同时包含位图句柄格式，因此也会跳过。

序号和所有者无法完全区分“同一应用多阶段写入”和“用户在同一应用主动复制”。极慢响应、第三方剪贴板管理器和延迟渲染也有边界；不承诺任意应用、任意格式下的无损事务。请求取消或发现竞争时，可能保留目标应用已复制的新内容。需要完全不接触剪贴板时，将复制兼容范围设为禁用。

## 运行与测试

```powershell
conda activate copilot
python -m pip install -r requirements.txt
python app.py
```

先从托盘退出旧版本，避免单实例机制继续使用旧进程。已有 API 设置无需重填。

```powershell
python -B -m unittest discover -s tests -q
python -B scripts/smoke_selection.py
python scripts/build_windows.py
python scripts/smoke_windows.py
```

`smoke_selection.py` 创建独立的临时 Qt 测试窗口，验证原生鼠标/键盘钩子的安装退出、真实选中文字、空光标和密码框；取词过程中核对剪贴板序号不变。它不会操作用户已有应用或请求 API。`smoke_windows.py` 使用临时设置和本地模拟 HTTP 服务验证 exe，不使用真实 API Key。

本轮在 Windows x64 / Python 3.10.20 环境通过 140 项自动测试及上述两个冒烟脚本。exe 已重新构建；日志断言实际取词使用 `method=uia` 且没有 `Copy shortcut sent`，并验证流式翻译、解释、SAPI 朗读、单实例退出和保存设置后的重启。可选 exe 冒烟依赖 `build/qa-deps` 中的 pywinauto/six，安装步骤见 [打包文档](Packaging.md)；主程序不依赖这些测试工具。

剪贴板格式恢复及并发写入通过模拟系统接口验证。本机不允许创建隔离窗口站，因此没有在用户的系统剪贴板上执行原生复制兜底测试；这部分不能等同于所有第三方应用的实机格式恢复验收。

人工验收建议按实际常用软件分别记录结果：

1. 短拖选、双击、三击、Shift 单击和 Shift+方向键、Ctrl+A；选区内容应准确。
2. 从其他窗口直接开始拖选；快速连选不同内容，结果只能对应最后一次选择。
3. 单击、拖滚动条、拖标题栏、拖文件；默认设置下不应发送 Ctrl+C。
4. 复制一张图片或富文本后自动划词，原剪贴板应不变；启用兼容后验证已支持格式与未知格式跳过。
5. 在捕获期间主动复制、切窗、按 Esc；旧结果不应回来，也不能无条件覆盖新剪贴板。
6. 终端运行任务时划选；若 UIA 不支持，使用终端自己的复制方式，再从托盘读取。
7. 不同缩放的显示器间使用，工具栏靠近选区末端并位于可见范围；设置页保存按钮可达。

自动测试和自有 Qt 窗口冒烟不代表 Chrome、Edge、VS Code、Word、Acrobat 等全部完成实机兼容验收。自绘控件、高权限窗口、扫描 PDF、任意程序化选区和特殊键位仍可能不支持；下一步应以实际使用软件的失败记录为依据补充适配，不通过增加全局复制次数解决。

## 值得阅读的函数

1. `UIASelectionReader._read`：理解如何把读取限制在原窗口内，以及为什么真实空选区不能进入复制兜底。
2. `SelectionService.capture`：整个策略入口，集中管理重读、请求有效性和复制资格。
3. `ClipboardService.get_text_after_copy`：理解剪贴板序号、所有者、竞争检查与保守恢复的边界。

实现依据：[Microsoft GetSelection](https://learn.microsoft.com/en-us/windows/win32/api/uiautomationclient/nf-uiautomationclient-iuiautomationtextpattern-getselection)、[UIA 线程模型](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-threading)、[剪贴板序号](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getclipboardsequencenumber)、[低级键盘钩子](https://learn.microsoft.com/en-us/windows/win32/winmsg/lowlevelkeyboardproc)。
