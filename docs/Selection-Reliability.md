# Windows 取词可靠性

2026-10-23：本轮处理微信聊天正文、输入框，PowerPoint 编辑模式文本框，以及浏览器等应用偶发漏触发。当前默认行为以本文和代码为准。

## 根因与对应解决

| 根因 | 证据与表现 | 实现 |
| --- | --- | --- |
| 把输入手势当成唯一选区通知，读取窗口过短 | 原逻辑只有鼠标/键盘候选，80 ms 防抖后仅短间隔读取三次；目标应用晚更新选区就漏掉 | 前台 UIA TextSelectionChanged 事件与输入候选共同触发；一次有界会话逐步等待，快接口立即返回 |
| 查找路径不等于目标真实选区 | 原先主要沿落点/焦点祖先查找；深层提供者、焦点与鼠标目标不同、拖动终点落在按钮等会造成误判 | 保存鼠标起点，验证源窗口和范围；有界查找目标局部子树，区分目标空选区与无关焦点，禁止读全文冒充选区 |
| 应用提供的接口不同 | 原日志中微信主要为 unsupported；PPT 同样无法稳定通过 UIA 获取编辑文字 | PPT 读取原生 TextRange，拒绝幻灯片/形状选择；微信仅在 unsupported 且策略允许时受控复制一次 |
| 同一进程中的 COM 调用缺少强制截止 | 单个提供者卡住，会阻塞后续所有取词 | 持久独立进程负责只读 COM；读取超时终止重建，心跳监控覆盖事件订阅卡住的情况 |
| 剪贴板内容与 OLE 传输元数据混为一谈 | 微信首次成功后，后续日志反复出现 clipboard_format_unsupported；只读格式检查发现文本旁伴随 DataObject / Ole Private Data | 备份实际可恢复内容，不重放指向旧所有者的传输元数据；未知实际内容仍拒绝复制 |
| 选区请求有效性与剪贴板事务恢复绑定 | 新请求取消旧请求时，已经完成的临时复制可能遗留 | 已确认复制的恢复只看剪贴板序列号和所有者；请求过期不再阻止恢复，较新的剪贴板写入仍保留 |

这不是增加一个全局 Ctrl+C 或单纯延长延迟：输入候选、真实选区提供者、进程故障恢复、复制事务和 UI 交付分别承担明确职责。

## 当前调用链与触发条件

```text
鼠标拖动 / 多击 / Shift 扩选 / 键盘选区 / Alt+Q
                    或前台 UIA 选区变化事件
  → Controller 验证前台窗口与输入代次，合并候选
  → SelectionService.capture：有界等待选区就绪
  → ReaderProcess：只读子进程
      → UIASelectionReader：目标、祖先、局部子树真实选区
      → PowerPointSelectionReader：PPT 原生文本选区
  → 仅 unsupported 且策略允许：ClipboardService 一次受控复制
  → Controller 校验请求未过期、事件去重 → 工具栏
```

- 鼠标候选保留 80 ms 防抖；读取之间等待 0 / 40 / 80 / 120 / 180 / 240 ms，发起下一次尝试前检查 750 ms 会话预算。该预算不是整个操作的绝对截止：已发出的提供者调用由 1.2 s 硬截止约束，进程冷启动最多另等 4 s。
- UIA 局部查找有时间和节点上限。工作进程每 0.5 s 发送心跳，超过 4 s 无响应会被回收；控制器每秒维护观察进程。
- 已有待处理或执行中的候选不会被同一选区事件不断取消；只保留最新待处理请求。普通取消保留观察进程，迟到结果按请求编号丢弃。
- 新输入、前台窗口变化等会使旧请求失效；重复的选区事件不会反复打开刚关闭的同一选区工具栏。
- 密码框及明确非文本目标受阻；空选区、错误和超时不进入自动复制。事件本身从不触发复制。

## 复制策略与迁移

默认 `compatible`：快捷键保留复制兼容；自动复制只对 `weixin.exe` / `wechat.exe` 的用户输入候选开放。默认值适用于新配置和没有保存该字段的旧配置；明确保存的 `manual`、`never`、`allowlist` 不被覆盖。

`allowlist` 可由用户指定其他进程；终端和常见 IDE 宿主仍禁止模拟复制。`never` 完全禁止模拟复制。托盘「使用剪贴板文字」始终是显式只读入口。

复制前备份所有已支持内容，等待目标进程完成写入，再读取文本。已确认事务只在序列号与所有者仍相同的情况下恢复。OLE 的 DataObject / Ole Private Data 只携带传输与所有权信息，不应跨所有者重放；只有这些元数据、没有可恢复内容时仍跳过复制。

## 文件职责

| 文件 | 职责 |
| --- | --- |
| `app.py` | 事件接入、最新请求队列、交付验证、去重和进程生命周期 |
| `core/mouse.py` | 在候选中保留鼠标起点 |
| `core/uia.py` | UIA 真实选区、窗口归属、局部查找、结果原因 |
| `core/powerpoint.py`（新增） | PowerPoint 原生文本选区，拒绝形状/幻灯片与错误窗口 |
| `core/reader_process.py`（新增） | 独立 COM 工作进程、事件订阅、IPC、超时、心跳及恢复 |
| `core/selection.py` | 就绪等待、取消检查、提供者结果与复制策略衔接 |
| `core/clipboard.py` | 内容快照、OLE 元数据分类、复制和条件恢复 |
| `config/settings.py`、`ui/settings_dialog.py`、`.env.example` | 默认兼容策略、配置兼容与可见说明 |
| `tests/test_uia.py`、`test_mouse.py`、`test_selection.py` | 查找范围、手势来源、延迟与取消回归 |
| `tests/test_powerpoint.py`、`test_reader_process.py`（新增） | Office 选区类型/窗口匹配、真实 spawn 进程故障恢复 |
| `tests/test_clipboard.py`、`test_controller.py`、`test_app.py`、`test_settings.py` | 剪贴板事务、事件合并、生命周期和默认值回归 |
| `scripts/probe_selection.py`（新增） | 真实窗口只读诊断，输出状态、方法、原因、长度与事件数，不输出选区内容 |
| `scripts/smoke_selection.py`、`scripts/smoke_windows.py` | 原生 UIA 与隔离进程检查、可指定 exe 的 Windows 冒烟验证 |
| `README.md`、`docs/README.md`、`docs/Windows使用说明.txt`、本文 | 当前行为与操作说明；`Selection-Experience.md` 标明为历史记录 |

最值得阅读的三个函数：

1. `UIASelectionReader._read`：如何判断“目标没有选区”和“接口没有提供选区”，这决定是否会误取或错误进入复制。
2. `ReaderProcess.read`：请求编号、取消与硬截止如何让一个应用的故障不再拖垮所有取词。
3. `ClipboardService.get_text_after_copy`：复制事务为什么必须独立于 UI 请求生命周期，以及怎样保留新的剪贴板写入。

## 运行与测试

```powershell
python app.py
python -B -m unittest discover -s tests -q
python scripts/smoke_selection.py
python scripts/build_windows.py
python scripts/smoke_windows.py
# 选中文字后只读探测前台窗口；需要事件观察时增加 --watch 5
python scripts/probe_selection.py --delay 3 --watch 5
```

便携版入口：`dist/SelectionCopilot/SelectionCopilot.exe`；分发包：`dist/SelectionCopilot-win64.zip`。Windows 冒烟脚本所需 QA 依赖见 [打包说明](Packaging.md)，也可传入其他 exe 路径作为第一个参数。冒烟使用临时设置和本地模拟 API，不调用用户的外部模型服务。

本轮验证记录：

- 全量 164 项自动化测试通过，覆盖真实 spawn/IPC 的卡死、取消、迟到结果隔离及崩溃恢复。
- 原生 UIA 与独立进程的文本选区、空选区、密码框冒烟通过。
- 实机 PowerPoint 文本选择返回 `powerpoint / office_text_selection`，选择形状返回空，观察到真实 UIA 选区事件。当前 Office 的 HWND 属性不可用，验证过活动文档与唯一窗口标题的受限回退。
- 用户实机确认微信聊天正文和输入框均能弹出；对应连续多次日志为 `clipboard / selected`，捕获约 281–313 ms，随后交付 `shown=true`。此前失败的当前剪贴板，经只读快照检查确认可备份实际内容。
- 用户正常使用期间的 ChatGPT 日志记录到一次 UIA 选区读取成功：47 ms、未模拟复制、工具栏已交付。该记录仅证明这一次路径正常，不代表所有页面和交互均已覆盖。
- Windows exe 冒烟覆盖设置、选区弹出、流式翻译、解释、SAPI、单实例、退出与重启。浏览器与 ChatGPT 的所有版本/页面尚未逐一实机覆盖，不据此声称全应用兼容。

诊断日志记录候选、读取、捕获与交付阶段的应用名、状态、原因、耗时和字符数，不记录选区正文。提供者异常仅输出异常类型及代码位置，不输出应用提供的异常消息。

## 已知边界与下一步

- 无障碍接口和事件由目标控件提供；没有事件时保留手势路径。没有 UIA/原生接口、又不允许复制的控件仍不能自动读取；不支持 OCR。
- PowerPoint 原生接口 HWND 不可用时，仅接受活动文档与唯一匹配标题的前台 PPT 窗口；同名文档等歧义场景拒绝猜测。
- 未知实际剪贴板内容格式或超过 16 MiB 时不复制。跨应用新写入受保护；同一目标进程中的并发手动复制、取消前未能确认的迟到复制仍有识别边界。此实现不是通用 OLE 对象克隆。
- 高权限窗口、目标进程忙碌、冷启动或提供者挂起可能造成单次失败；独立进程保证随后可以恢复，不保证每次都成功。
- 下一步自然目标是建立按控件类型划分的实机回归矩阵：微信正文/输入、PPT 文本/形状、多种浏览器网页与 ChatGPT 文本区，覆盖快速连续选择、拖回、切换前台、剪贴板富文本及提供者恢复。依据状态日志完善提供者边界，而不是扩大无条件复制范围。
