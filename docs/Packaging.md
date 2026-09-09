# Windows exe 打包与验证

本阶段生成 Windows x64 便携版：

- `dist/SelectionCopilot/SelectionCopilot.exe`：双击运行。
- `dist/SelectionCopilot-win64.zip`：用于复制到其他电脑，完整解压后运行。
- exe 同目录的 `_internal` 保存 Python、Qt 和其他运行依赖，必须一起保留。

使用 PyInstaller 的目录模式，避免单文件模式每次启动时解压依赖。不需要目标机器预装 Python。本次使用 Windows x64、Python 3.10.20、PySide6 6.11.2 和 PyInstaller 6.22.2 构建。

## 使用

1. 如果旧的 `python app.py` 仍在运行，先从它的托盘菜单退出，否则会占用 Alt+Q。
2. 双击 exe。未配置 API 时会自动打开设置；填写 API 地址、API Key 和模型并保存。
3. 拖动、双击选中文字，或选中后按 Alt+Q，再选择操作。
4. 关闭设置后程序继续在系统托盘运行；右键 SC 图标可以打开设置或退出。重复双击 exe 会打开已有实例的设置。

已有 `%LOCALAPPDATA%/SelectionCopilot/settings.json` 会继续使用。分发包不会复制项目的 `.env`；如果此前只用 `.env`，可以在设置窗口重新填写，或自行放置一份 `.env` 到 exe 同目录。

配置优先级为：保存的 JSON > 环境变量 > exe 同目录 `.env` > 默认值。API Key 保存在本机配置中，不要将个人配置一起分发。

日志位于 `%LOCALAPPDATA%/SelectionCopilot/logs/app.log`，每个文件最大 2 MiB，最多保留 3 个历史文件。无控制台版本不依赖标准输出；日志记录运行状态、错误与响应耗时，不主动记录 API Key 或所选文本。

## 文件与调用链

| 文件 | 作用 |
| --- | --- |
| `SelectionCopilot.spec` | windowed 目录式打包、图标、依赖元数据、SAPI5 动态导入；通过明确清单收集文件 |
| `requirements-build.txt` | 独立的构建依赖，固定 PyInstaller 版本 |
| `scripts/build_windows.py` | 生成 SC 图标、构建 exe、复制公开说明与配置样例、检查敏感配置文件名、压缩 |
| `config/paths.py` | 区分源码目录、exe 目录和用户数据目录 |
| `config/settings.py` | 通过统一路径读取 `.env` 与用户设置 |
| `services/llm.py`、`services/translator.py` | 明确 `.env` 路径，防止打包后错误地搜索当前工作目录 |
| `core/runtime.py` | 轮转文件日志、实例锁与本地窗口唤起/退出消息 |
| `app.py` | 首次设置、无终端启动、单实例接入、应用图标及异常提示 |
| `tests/test_runtime.py`、`tests/test_app.py` | frozen 路径、无终端日志、进程间通知与锁释放、隔离的 SIGINT 生命周期验证 |
| `scripts/smoke_windows.py` | 操作真实 exe 的可选桌面冒烟测试，使用临时配置与本地模拟 API |
| `docs/Windows使用说明.txt` | 随压缩包附带的最终用户说明 |
| `.gitignore` | 忽略 `build/` 与 `dist/` |

构建链：`build_windows.main()` → 生成图标 → PyInstaller/spec → `dist/SelectionCopilot` → 压缩包。

运行链：`app.main()` → `SingleInstance.start()` → 文件日志 → 加载设置 → 控制器启动托盘、快捷键和鼠标监听 → 进入 Qt 事件循环 → 退出时释放监听、后台任务及实例锁。第二个进程通过本地消息唤起第一个进程的设置窗口，随后退出。

## 重新构建

在项目根目录的 PowerShell 中执行，使用 Windows x64 的 Python 环境：

```powershell
conda activate copilot
python -m pip install -r requirements-build.txt
python -m unittest discover -s tests -q
python scripts/build_windows.py
```

重新构建前请退出正在运行的分发版 exe，以便替换文件。项目 `.env` 不在 spec 的收集清单里。

## 验证结果与复测

本次通过 96 项自动测试，并实际运行目录中的 windowed exe 验证：

- 空配置自动打开设置，默认 Alt+Q；快捷键冲突能显示错误。
- 保存设置后继续驻留，重复启动唤起已有窗口，正常退出、重新启动后加载保存的设置。
- 从测试文本框选区复制文本，临时快捷键唤起工具栏。
- 翻译和解释通过本地 HTTP/SSE 模拟接口返回完整文本；没有消耗真实 API 配额。
- SAPI5 朗读完成，动态语音模块能正常加载。
- exe 从项目外的临时工作目录运行，PATH 仅保留 Windows System32，使用临时 LOCALAPPDATA；验证没有依赖项目 `.env` 或 PATH 中的 Conda/Python。
- 日志中有启动/退出记录，没有测试 API Key 或错误堆栈。

可选的 exe 自动冒烟测试需要桌面会话，会打开测试窗口、使用 Ctrl+Shift+F12 并短暂朗读 Hello；如该快捷键被其他软件占用，应先解决冲突。测试配置和日志位于临时目录，不会修改日常设置。

```powershell
python -m pip install --target build/qa-deps --no-deps pywinauto==0.6.9 six==1.17.0
python scripts/smoke_windows.py
```

也可以手动按“首次设置 → 划词 → 翻译/解释/朗读/Chat → 重复启动 → 托盘退出”的顺序检查。真实 DeepSeek 连接与跨软件拖选/双击行为需要使用自己的配置再验证。

## 限制和下一步

这是便携版，并非安装器；尚未做代码签名，也尚未在全新 Windows 虚拟机验证。不同机器的 SAPI 语言取决于已安装语音。当前依然使用 Ctrl+C 取词，图片/OCR、不能复制的控件和高权限程序不在此次扩展范围内；剪贴板恢复仍以纯文本为限。暂未加入开机启动或自动更新。

下一步最自然的是在一台没有 Python 的 Windows 电脑上做验收，再决定是否增加安装器、开机启动和代码签名。

建议阅读三个函数：`scripts/build_windows.py` 的 `main()` 展示完整构建与分发流程；`core/runtime.py` 的 `SingleInstance.start()` 解释多个进程如何避免重复监听；`app.py` 的 `main()` 展示桌面程序从启动到退出的资源管理。

实现参考：[PyInstaller 运行时路径](https://pyinstaller.org/en/stable/runtime-information.html)、[无控制台模式注意事项](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html)、[Qt QLockFile](https://doc.qt.io/qtforpython-6/PySide6/QtCore/QLockFile.html)。
