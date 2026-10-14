# Selection Copilot 文档

Selection Copilot 是一个 Windows 桌面划词助手，支持自动划词、全局快捷键、翻译、本地朗读、AI 解释和基于选区的多轮聊天。

项目使用 Python、PySide6、Windows API、httpx 与 OpenAI-compatible Chat Completions API；本地朗读采用 pyttsx3 / SAPI5，便携版通过 PyInstaller 打包。

完整的功能介绍、安装步骤、技术栈与开发方式见 [项目 README](../README.md)。该文件位于仓库根目录，用于 GitHub 首页展示。

## 后续计划（尚未实现）

- **划词收藏**：记录选区、译文或解释，帮助用户保存和回顾碎片化知识，逐步支持来源、标签、搜索与导出。
- **UI 优化**：统一视觉风格，改善排版、窗口布局及高 DPI 显示体验。
- **取词兼容性**：引入 UI Automation，改进剪贴板格式保护和跨软件取词表现。
- **使用体验**：按需增加开机启动、安装器与自动更新。

## 文档导航

- [Windows 使用说明](Windows使用说明.txt)：便携版的运行、配置与日常操作。
- [打包与验证](Packaging.md)：构建命令、输出文件与验证方法。
- [托盘、设置与自动划词](Phase7-8-implementation.md)：功能实现与交互流程。
- [双击划词与快捷键](Double-click-and-hotkey.md)：相关交互改进。
- [性能优化](Performance.md)：响应速度与流式输出的实现记录。

`Phase*.md` 保留了各阶段的原始开发需求，部分描述属于当时的规划；当前功能与限制以根目录 README 和现有代码为准。
