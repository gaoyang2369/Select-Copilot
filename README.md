# Selection Copilot

一个 Windows 桌面划词助手，让翻译、朗读和 AI 问答随选随用。

在浏览器、IDE、Word 或支持复制文本的 PDF 阅读器中选中文字，即可在鼠标附近打开悬浮工具栏，直接翻译、听发音、查看解释，或围绕选区继续追问。适合阅读英文资料、论文和代码时使用。

```text
选中文字 → 自动弹出工具栏 / 按 Alt+Q → 翻译 · 朗读 · 解释 · Chat
```

## 已实现功能

- **自动划词**：拖动或双击选中文字后尝试显示工具栏，也可使用全局快捷键，默认 `Alt+Q`。
- **划词翻译**：将选区翻译为中文，单词可返回词性和常见含义；支持流式显示和内存缓存。
- **本地朗读**：使用 Windows 系统语音朗读选中的文本，无需调用在线 TTS 服务。
- **AI 解释**：对选中的词句、概念或代码进行解释。
- **多轮聊天**：以选区为上下文打开 Chat 窗口，继续提问。
- **统一界面**：工具栏、结果窗口与 Chat 共用深色配色和字体；支持 Markdown 结果排版、复制、引用折叠、可调整布局和高 DPI 缩放。
- **托盘与设置**：配置 API 地址、API Key、模型、快捷键和流式输出；可暂停自动划词，设置保存在本机。
- **Windows 便携版**：支持打包为 exe，包含单实例运行与本地日志。

## 技术栈

| 用途 | 技术 |
| --- | --- |
| 开发语言 | Python（建议 3.11+） |
| 桌面界面 | PySide6 / Qt |
| 全局快捷键与鼠标监听 | Windows API、`ctypes`、`keyboard` |
| 选区读取 | 模拟 `Ctrl+C` + 剪贴板读取与纯文本恢复 |
| 翻译与 AI 问答 | `httpx` + OpenAI-compatible Chat Completions API，支持 SSE 流式响应 |
| 本地语音 | `pyttsx3` + Windows SAPI5 |
| 配置 | `python-dotenv` + 本地 JSON |
| 打包与测试 | PyInstaller、`unittest` |

## 快速开始

### 从源码运行

在 Windows 上进入项目根目录，创建虚拟环境并安装依赖：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

首次运行会打开设置窗口，填写服务商提供的 **API 地址、API Key 和模型名称** 后保存。接口需兼容 Chat Completions；API 地址填写基础地址，程序会追加 `/chat/completions`。

也可以复制配置样例并修改其中的值：

```powershell
Copy-Item .env.example .env
```

配置优先级：**已保存的设置 > 环境变量 > `.env` > 默认值**。

### 日常使用

1. 在支持复制文本的软件中拖动或双击选中文字；自动弹出失败时，可按 `Alt+Q`。
2. 点击工具栏中的「翻译」「朗读」「解释」或「Chat」。翻译、解释和聊天需要有效的 API 配置；结果窗口可一键复制原始结果。
3. 通过系统托盘中的 **SC** 图标打开设置、暂停自动划词或退出。关闭设置与 Chat 窗口后，程序继续驻留。
4. Chat 中按 `Enter` 换行、`Ctrl+Enter` 发送；点击「引用的选区」可折叠上下文，拖动引用区与对话之间的分隔条可调整高度。窗口较矮时默认收起引用。

### 构建 Windows 便携版

使用 Windows x64 和 64 位 Python，在项目根目录执行：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe scripts/build_windows.py
```

输出为 `dist/SelectionCopilot/SelectionCopilot.exe` 和 `dist/SelectionCopilot-win64.zip`。分发时保留整个目录，完整解压后运行，目标电脑无需安装 Python。详细说明见 [打包文档](docs/Packaging.md)。

## 后续计划

以下功能尚未实现：

- [ ] **划词收藏 / 碎片知识记录**：保存选中的文本、译文或解释，逐步支持来源、标签、搜索与导出，帮助用户积累和回顾阅读中的碎片化知识。
- [ ] **取词兼容性优化**：优先通过 Windows UI Automation 获取真实选区，剪贴板作为后备，并改进富文本、图片等剪贴板格式的保护。
- [ ] **使用体验完善**：按需增加开机启动、安装器和自动更新等功能。

## 当前限制与数据说明

- 当前仅面向 Windows。取词依赖目标软件能复制选区，尚未支持 OCR；部分控件和高权限程序可能无法取词。
- 自动划词仍可能误触发；可在托盘中暂停，改用快捷键。剪贴板目前仅恢复纯文本，不能完整保留图片、文件列表或富文本。
- 选区捕获在本地完成；主动点击翻译、解释或发送聊天消息时，相关文本会发送给配置的 API 服务。朗读使用本机语音，可用语言取决于已安装的语音。
- 收藏尚未实现；翻译缓存与聊天记录只保留在内存中。
- API Key 随设置以明文保存在 `%LOCALAPPDATA%\SelectionCopilot\settings.json`。请勿分享个人设置或 `.env`。

## 项目结构与开发

```text
app.py        # 程序入口与交互调度
core/         # 快捷键、鼠标监听、选区与剪贴板、运行管理
ui/           # 悬浮工具栏、结果窗口、Chat、设置与托盘
services/     # 翻译、LLM、聊天与本地 TTS
config/       # 配置读写与路径管理
scripts/      # Windows 打包与冒烟验证
tests/        # 自动化测试
docs/         # 阶段记录与使用说明
```

运行自动化测试：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
```

无需配置 API 即可预览新界面：`python scripts/preview_ui.py --show`。截图、缩放验证和实现说明见 [UI 优化](docs/UI-Optimization.md)。

更多说明见 [文档入口](docs/README.md) 和 [Windows 使用说明](docs/Windows使用说明.txt)。
