你现在要协助我开发一个 Windows 本地桌面工具，暂定名为 `Selection Copilot`。

## 项目目标

这是一个 Windows 系统级“划词助手”。

核心交互：

1. 用户在任意软件中鼠标选中文字
2. 通过全局快捷键或后续的鼠标自动检测触发
3. 程序读取当前选中的文本
4. 在鼠标附近弹出一个轻量悬浮窗口
5. 用户可以执行：

   * 翻译
   * TTS 发音
   * AI 解释
   * 开启多轮聊天

典型使用场景包括：

* 阅读英文论文
* 浏览网页
* 阅读 PDF
* 阅读源码
* VS Code
* Word
* 浏览器
* 普通 Windows 软件

---

# 技术栈

第一版固定使用：

* Python 3.11+
* PySide6：GUI
* Windows API / UI Automation：获取选中文本
* Clipboard + 模拟 Ctrl+C：作为 fallback
* httpx：HTTP 请求
* OpenAI-compatible API：LLM
* Windows 本地 TTS：优先使用系统语音
* PyInstaller：后续打包 exe

目前只针对 Windows，不考虑 macOS 和 Linux。

---

# 开发原则

这是一个个人工具和学习项目，因此请严格避免过度设计。

不要主动引入：

* Clean Architecture
* DDD
* Event Bus
* Repository Pattern
* Dependency Injection Framework
* Agent Framework
* MCP
* LangChain
* LangGraph
* 微服务
* 插件系统
* 复杂配置框架

除非后续我明确要求。

优先使用：

* 简单类
* 简单函数
* 清晰目录
* 少量依赖
* 可读代码

代码应该让我这个 Python 开发者能够比较容易读懂。

---

# 开发方式

不要一次实现全部功能。

我们采用逐阶段开发：

Phase 1：
全局快捷键 + 获取当前选中的文本

Phase 2：
鼠标附近显示悬浮工具栏

Phase 3：
翻译功能

Phase 4：
TTS 发音

Phase 5：
LLM Quick Ask

Phase 6：
多轮 Chat

Phase 7：
系统托盘、配置、缓存

Phase 8：
鼠标选中文字后自动检测并弹出工具栏

Phase 9：
改进 UI Automation / Clipboard 双通道兼容性

Phase 10：
PyInstaller 打包 exe

每次我让你实现某个 Phase 时：

1. 先阅读当前项目代码
2. 说明你准备修改哪些文件
3. 只实现当前 Phase
4. 不要提前实现后续功能
5. 尽量避免大规模重构
6. 修改完成后运行基本测试
7. 给出明确的手动测试步骤
8. 简单解释本阶段的关键代码和 Windows API 原理

如果发现设计需要调整，可以提出，但不要擅自扩大项目范围。

---

# 推荐目录

初期可以采用：

selection-copilot/

```
app.py

core/
    selection.py
    clipboard.py
    hotkey.py

ui/
    toolbar.py
    chat_window.py

services/
    translator.py
    llm.py
    tts.py

config/
    settings.py

utils/
    logger.py
```

目录允许随着开发稍微调整，但不要为了“架构漂亮”拆出大量文件。

---

# 重要设计原则

获取选中文本最终采用双通道：

第一优先级：

Windows UI Automation

尝试获取当前 focused element / text selection。

如果无法获取：

使用 Clipboard fallback：

1. 保存原 clipboard
2. 模拟 Ctrl+C
3. 等待很短时间
4. 读取 clipboard
5. 恢复原 clipboard

但在 Phase 1 可以先实现更简单可靠的 Clipboard 方案，把完整 UI Automation 放到后面的兼容性优化阶段。

---

# UI 原则

悬浮 UI 应该：

* 小
* 快
* 不遮挡内容
* 尽量不抢当前软件焦点
* 鼠标附近显示
* 无边框
* Always on top
* 后续支持失去焦点自动隐藏

不要一开始制作复杂动画或复杂主题。

---

# 安全原则

LLM API Key：

第一版允许从 `.env` 或本地配置读取。

绝对不要硬编码进源码。

只有用户主动点击 AI 功能时，才把选中的文字发送给 LLM。

不要在后台自动上传用户选中的所有内容。

---

在后续开发过程中，请始终遵守以上约束。
