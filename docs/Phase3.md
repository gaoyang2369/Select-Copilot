请实现 Phase 3：翻译功能。

当前系统已经可以：

选中文字
→ 快捷键
→ 悬浮工具栏
→ 点击“译”

现在点击“译”后：

1. 调用 OpenAI-compatible API
2. 把 selected_text 翻译成中文
3. 在 toolbar 下方弹出一个 translation popup
4. 显示翻译结果

配置：

BASE_URL
API_KEY
MODEL

从 .env 读取。

使用 httpx AsyncClient。

不要绑定某一家模型厂商，只实现 OpenAI-compatible Chat Completions 接口。

services/translator.py：

class Translator:
    async def translate(
        self,
        text: str,
        target_language: str = "Simplified Chinese"
    ) -> str

Prompt 应该简洁。

如果是单词：
除了中文意思，也返回词性和常见含义。

如果是句子/段落：
优先自然、准确翻译，不需要长篇解释。

输出不要 Markdown 大标题。

UI 调 API 时不能阻塞 Qt 主线程。

翻译过程中显示：
Translating...

调用失败显示清晰错误信息。

本阶段不要实现：
TTS
Chat
自动选择检测。