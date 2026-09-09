请继续开发 Selection Copilot，当前 Phase 1 已经能够：

选中文字
→ Ctrl + Alt + Space
→ 获取 selected_text

现在实现 Phase 2：悬浮工具栏。

## 本阶段目标

用户：

1. 在任意软件选中文字
2. 按 Ctrl + Alt + Space
3. 获取 selected_text
4. 在当前鼠标附近显示一个小型悬浮工具栏

工具栏暂时显示四个按钮：

译
🔊
解释
Chat

但这一阶段按钮暂时不需要实现实际功能。

点击按钮只需要打印：

translate clicked
tts clicked
explain clicked
chat clicked

---

# UI 技术

使用 PySide6。

悬浮工具栏建议：

* QWidget
* 无边框
* Always on top
* Qt.Tool
* 尽可能不出现在 Windows 任务栏
* 在鼠标附近显示
* 简单圆角
* 水平排列按钮

例如：

[ 译 ] [ 🔊 ] [ 解释 ] [ Chat ]

不要制作复杂动画。

---

# 位置

获取当前鼠标位置。

悬浮条默认出现在：

鼠标右下方约 8~15 像素。

需要考虑屏幕边缘：

如果右侧空间不足，则向左显示。

如果底部空间不足，则显示在鼠标上方。

支持多显示器时，尽量根据鼠标所在屏幕进行边界计算。

---

# 生命周期

按一次快捷键：

如果获取到 selected_text：

显示 toolbar。

如果没有文本：

不显示。

再次选词并触发：

更新 selected_text
并把 toolbar 移动到新的鼠标位置。

点击界面外部或者按 Esc：

隐藏 toolbar。

---

# 线程问题

特别注意：

全局快捷键回调可能不运行在 Qt 主线程。

所有 QWidget 操作必须回到 Qt GUI 主线程。

请选择清晰、简单的 Qt Signal/Slot 或其他安全方式处理。

不要从 keyboard hook 线程直接修改 QWidget。

---

# 代码组织

建议新增：

ui/toolbar.py

例如：

class FloatingToolbar(QWidget):
...

SelectionService 继续只负责获取文字。

不要把：

clipboard
hotkey
GUI

全部写到 toolbar.py。

---

# 暂时不要实现

不要实现：

* 翻译
* TTS
* LLM API
* Chat 窗口
* 鼠标自动划词检测
* UI Automation

按钮只打印日志。

---

# 完成以后

请：

1. 运行程序做基础验证
2. 给出人工测试步骤
3. 解释为什么 Qt GUI 只能在主线程操作
4. 说明 toolbar 如何接收到 selected_text
5. 说明鼠标坐标和屏幕边界是如何处理的

继续保持代码简单。
