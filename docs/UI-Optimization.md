# 工具栏、结果窗口与 Chat UI 优化

本次统一三个窗口的配色、字体、边框、按钮状态、滚动条与留白。工具栏改用「翻译 / 朗读 / 解释 / Chat」文字，避免 emoji 在不同字体、缩放下显示不一致。设置窗口继续使用原有系统样式。

结果窗口新增标题、复制与关闭按钮，最大尺寸为 480 × 360 Qt 逻辑像素；根据工具栏上下方的实际空间调整高度，优先避免遮挡工具栏。复制保留完整原始 Markdown，拖选正文复制则使用 Qt 的文本选择行为。

Chat 默认 660 × 720 逻辑像素，启动时按鼠标所在屏幕的工作区缩小并限制位置，保留原生标题栏、缩放和移动。引用可折叠，也可拖动分隔条调整高度；窗口高度不足 560 时默认折叠。输入区按显式换行自动增长，最多五行，超出后滚动。`Enter` 换行，`Ctrl+Enter` 发送；空输入与生成期间禁用发送。

用户输入和选区始终按纯文本显示。流式回复仍增量追加纯文本，完成后仅替换本轮回答并渲染 Markdown，支持粗体、列表及代码。长单词和代码行可折行。阅读历史时保留滚动位置，滚动在底部时跟随最新内容；Markdown 转换可能改变段落高度，原滚动值会被新的可用范围限制。

Markdown 使用 Qt 的 `MarkdownNoHTML`，忽略原始 HTML；结果视图不打开链接或加载图片。该实现没有额外的 Markdown 或图像依赖。

## 文件与职责

| 文件 | 作用 |
| --- | --- |
| `ui/theme.py` | 共用色板、字号、QSS，以及屏幕工作区和窗口边界计算。主题局部应用于三个窗口。 |
| `ui/text_view.py` | 统一正文行距、作者标签、Markdown 文档插入与只读文本交互。 |
| `ui/toolbar.py` | 接入样式、文字按钮和提示，区分翻译 / 解释标题，完成时切换 Markdown。 |
| `ui/translation_popup.py` | 标题、复制、关闭、空间自适应及保留滚动位置的结果更新。 |
| `ui/chat_window.py` | 引用折叠、分隔布局、输入框高度、发送快捷键、屏幕适配与本轮回复替换。 |
| `scripts/preview_ui.py` | 使用本地样例生成实际 Qt 窗口截图，或打开可交互预览；不调用 API，不启动全局监听。 |
| `scripts/smoke_windows.py` | 适配新的翻译按钮、朗读错误文案和只读正文的 UIA Text 接口。需要重新打包后运行。 |
| `tests/test_ui_layout.py` | 在独立进程中检查 100%、125%、150%、200% 缩放下窗口边界、按钮宽度、正文空间与长输入。 |
| `tests/test_chat.py` | 补充 Enter / Ctrl+Enter、空输入状态和引用折叠回归测试。 |
| `tests/test_translation_popup.py` | 补充 Markdown 粗体、长代码折行、原始结果保存和滚动位置回归测试。 |
| `README.md`、`docs/README.md` | 更新已实现功能、日常操作与文档导航。 |
| `artifacts/ui-*.png` | 从实际 Qt 控件生成的样例截图。 |

## 调用链与建议阅读

```text
选区 -> FloatingToolbar.show_for_selection -> apply_theme + 屏幕边界限制
点击翻译 / 解释 -> AsyncTextWorker -> progress -> TranslationPopup.append_text
  -> completed -> show_message(markdown=True) -> TextView.insert_body
点击 Chat -> ChatWindow -> fit_window -> 引用 / 对话分隔布局
发送问题 -> ChatSession.send -> progress -> _append_reply
  -> completed -> _replace_reply -> TextView.insert_message -> Markdown 排版
点击复制 -> 将原始结果写入剪贴板
```

建议亲自阅读三个函数：

1. `TextView.insert_body`：流式纯文本与最终 Markdown 共用入口，统一行距、正文颜色与长行折行。
2. `ChatWindow._replace_reply`：用文档位置只替换当前回答，避免多轮历史丢失或流式答案重复，同时保留阅读位置。
3. `fit_window`：考虑原生窗口边框、工作区、最小尺寸和负坐标屏幕，控制 Chat 的初始大小与位置。

## 运行与验证

在项目根目录、已安装依赖的 Python 环境中运行：

```powershell
python app.py
python scripts/preview_ui.py --show
python scripts/preview_ui.py --scale 1 --output build/ui-preview/100
python scripts/preview_ui.py --scale 1.5 --output build/ui-preview/150
python scripts/preview_ui.py --scale 2 --output build/ui-preview/200
python -m unittest discover -s tests -q
python -m compileall -q app.py core ui services tests scripts
```

截图命令使用 offscreen Qt，不需要 API 配置；交互预览的 Chat 仅返回本地样例。Windows offscreen 插件无法自动发现字体时，预览脚本显式注册本机 Segoe UI、微软雅黑和 Consolas；正常桌面程序由 Qt 自动发现字体。

本次全量测试 101 项通过；独立进程的布局测试覆盖四档缩放，并生成、检查了 100%、150%、200% 的控件截图。截图测试无法替代真实桌面的多显示器验收。

手动验收：

1. 在 Windows 100%、125%、150%、200% 缩放下启动，检查按钮、中文、输入光标和滚动条是否清晰、无裁切。
2. 在屏幕四角取词，打开翻译与解释，检查结果窗边界；长回答可滚动，复制保留原始内容，Esc 或关闭后流式内容不重新弹出。
3. Chat 中收起 / 展开引用、拖动分隔条、缩小窗口，检查输入和发送按钮始终可操作。
4. 输入多行文字，验证 Enter 换行、Ctrl+Enter 发送、生成中禁用发送、完成后不重复回答；阅读上方历史时流式输出不强制拉到底部。
5. 将 Chat 在不同缩放的显示器间移动，检查文本和边界；确认选区、用户输入中的 HTML 标记仍是原文。

高 DPI 采用 Qt 6 原生缩放、逻辑像素布局和 point 字号，不手动乘设备像素比。参考 [Qt High DPI](https://doc.qt.io/qt-6/highdpi.html) 与 [QTextDocument Markdown](https://doc.qt.io/qt-6/qtextdocument.html#setMarkdown)。

## 限制与下一步

- 当前固定深色主题，未增加浅色主题选择；原生标题栏颜色仍由 Windows / Qt 决定。
- Markdown 在回复完成后渲染；生成期间仍会看到 Markdown 符号。原始 HTML 被忽略，不提供图片、链接跳转或代码语法高亮。
- 窗口布局测试基于 offscreen，真实混合 DPI 多显示器切换和 Windows 独立文字缩放仍需要人工验收；没有重新构建或验证便携 exe。
- 结果窗口保持轻量、随工具栏关闭，尚未支持固定、拖动和用户自定义尺寸；聊天仍仅保留在当前窗口内存。
- 下一阶段最自然的目标是划词收藏 / 碎片知识记录，复用当前结果展示与复制入口，增加保存、来源和检索。
