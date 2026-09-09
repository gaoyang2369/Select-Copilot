实现 Phase 4：TTS。

点击 🔊 时，对当前 selected_text 发音。

优先使用 Windows 本地 TTS，不调用云 API。

要求：

1. 不阻塞 PySide6 GUI
2. 如果文本为空不执行
3. 重复点击时避免同时播放很多声音
4. 优先支持英文
5. 保留未来选择 voice / rate 的扩展空间，但本阶段不要做设置 UI

新增 services/tts.py：

class TTSService:
    def speak(self, text: str):
        ...

解释你选择的 Windows TTS 技术方案，以及 pyttsx3 / SAPI / WinRT 各自优缺点。

优先选依赖简单、稳定的实现。