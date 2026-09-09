from __future__ import annotations

import unittest

from services.tts import TTSService


class FakeEngine:
    def __init__(self) -> None:
        self.properties: dict[str, object] = {}
        self.spoken_text = ""
        self.did_run = False

    def setProperty(self, name: str, value: object) -> None:
        self.properties[name] = value

    def say(self, text: str) -> None:
        self.spoken_text = text

    def runAndWait(self) -> None:
        self.did_run = True


class TTSServiceTests(unittest.TestCase):
    def test_speak_uses_local_engine_with_optional_voice_and_rate(self) -> None:
        engine = FakeEngine()
        service = TTSService(
            voice_id="english-voice",
            rate=180,
            engine_factory=lambda: engine,
        )

        service.speak("water")

        self.assertEqual(engine.spoken_text, "water")
        self.assertTrue(engine.did_run)
        self.assertEqual(engine.properties, {"voice": "english-voice", "rate": 180})

    def test_empty_text_does_not_create_engine(self) -> None:
        service = TTSService(engine_factory=lambda: self.fail("engine should not be created"))

        service.speak("   ")
