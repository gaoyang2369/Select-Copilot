"""Windows local text-to-speech service."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class TTSError(RuntimeError):
    """Raised when the local speech engine cannot play text."""


class TTSService:
    """Speak text through pyttsx3's Windows SAPI5 driver."""

    def __init__(
        self,
        voice_id: str | None = None,
        rate: int | None = None,
        engine_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._voice_id = voice_id
        self._rate = rate
        self._engine_factory = engine_factory

    def speak(self, text: str) -> None:
        """Synchronously speak non-empty text; callers should use a worker thread."""
        if not text.strip():
            return

        try:
            engine = self._create_engine()
            if self._voice_id:
                engine.setProperty("voice", self._voice_id)
            if self._rate is not None:
                engine.setProperty("rate", self._rate)
            engine.say(text)
            engine.runAndWait()
        except Exception as error:
            raise TTSError(f"Local TTS failed: {error}") from error

    def _create_engine(self) -> Any:
        if self._engine_factory is not None:
            return self._engine_factory()

        import pyttsx3

        return pyttsx3.init(driverName="sapi5")
