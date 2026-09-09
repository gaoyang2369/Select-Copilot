请实现 Selection Copilot 的 Phase 1。

## 本阶段目标

实现：

用户在 Windows 任意软件中选中文字后，按：

Ctrl + Alt + Space

Python 程序能够获取当前选中的文字，并打印到控制台。

例如：

用户在浏览器中选中：

Wasserstein distance

按 Ctrl + Alt + Space。

控制台输出：

Selected text:
Wasserstein distance

---

# 实现要求

这一阶段优先使用 Clipboard fallback，不需要实现完整 UI Automation。

基本流程：

1. 注册全局快捷键 Ctrl + Alt + Space
2. 快捷键触发时：

   * 保存当前 clipboard 内容
   * 模拟 Ctrl+C
   * 等待一个很短的时间，让目标程序完成复制
   * 读取新的 clipboard 文本
   * 恢复原 clipboard
3. 返回选中的文本
4. 控制台打印

---

# 推荐模块

core/hotkey.py

负责：

* 注册全局快捷键
* 回调触发

core/clipboard.py

负责：

* 保存 clipboard
* 模拟 Ctrl+C
* 获取文本
* 恢复 clipboard

core/selection.py

提供统一接口，例如：

class SelectionService:
def get_selected_text(self) -> str:
...

app.py

启动程序并监听快捷键。

---

# 实现约束

优先选择简单可靠的 Windows 实现。

可以根据需要使用：

* pywin32
* keyboard
* ctypes
* PySide6 clipboard

但不要同时引入很多重复功能的依赖。

选择你认为最简单、稳定的方案。

特别注意：

1. 不要永久覆盖用户原来的 clipboard
2. Ctrl+C 后需要适当等待，但不要固定等待很久
3. 没有选中文字时应该返回空字符串，而不是报错
4. 程序应该长期运行，不是执行一次就结束
5. 捕获必要异常
6. 添加基础日志即可，不要引入复杂 logging 框架

---

# 暂时不要实现

不要实现：

* GUI
* 翻译
* LLM
* TTS
* 自动鼠标检测
* UI Automation
* SQLite
* 设置窗口
* 系统托盘

这一阶段只验证：

Global Hotkey → Selected Text

---

# 完成后请做这些事情

1. 告诉我安装哪些依赖
2. 给出运行命令
3. 给出测试步骤
4. 实际运行基本代码检查
5. 解释以下几个问题：

* 全局快捷键是如何实现的？
* Ctrl+C 是如何模拟的？
* Clipboard 为什么需要保存和恢复？
* 哪些 Windows 软件可能无法通过这种方式读取？
* 下一阶段如何把 selected text 传给 GUI？

不要为了未来需求提前重构。
