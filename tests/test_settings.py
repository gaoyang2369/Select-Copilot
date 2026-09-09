from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from config.settings import Settings, SettingsStore
from core.hotkey import parse_hotkey


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.store = SettingsStore(root / "settings.json", root / ".env")

    def test_json_overrides_environment_and_dotenv(self):
        self.store.env_path.write_text("MODEL=dotenv-model\nAPI_KEY=local-test\n", encoding="utf-8")
        with patch.dict(os.environ, {"MODEL": "environment-model"}, clear=True):
            self.assertEqual(self.store.load().model, "environment-model")
            settings = Settings(model="saved-model", api_key="test", hotkey="ctrl+shift+f9", auto_select=False)
            self.store.save(settings)
            self.assertEqual(self.store.load(), settings)

    def test_atomic_save_failure_keeps_previous_file(self):
        previous = Settings(model="old")
        self.store.save(previous)
        with patch("pathlib.Path.replace", side_effect=OSError("disk error")):
            with self.assertRaises(OSError):
                self.store.save(Settings(model="new"))
        self.assertEqual(json.loads(self.store.path.read_text())["model"], "old")
        self.assertFalse(self.store.path.with_suffix(".tmp").exists())

    def test_invalid_json_and_wrong_types_are_rejected(self):
        for content in ('broken', '[]', '{"auto_select":"false"}', '{"hotkey":"ctrl+ctrl+a"}'):
            self.store.path.write_text(content, encoding="utf-8")
            with self.assertRaises(ValueError):
                self.store.load()

    def test_supported_hotkeys_and_invalid_shortcuts(self):
        self.assertEqual(Settings().hotkey, "alt+q")
        self.assertEqual(parse_hotkey("alt+q"), (0x4001, ord("Q")))
        self.assertEqual(parse_hotkey("CTRL+Alt+Space"), (0x4003, 0x20))
        self.assertEqual(parse_hotkey("ctrl+shift+f12"), (0x4006, 0x7B))
        for value in ("a", "ctrl+a+b", "ctrl+ctrl+a", "ctrl+f25", "ctrl+", "foo+a"):
            with self.assertRaises(ValueError):
                parse_hotkey(value)

    def test_credentials_are_not_in_settings_repr(self):
        self.assertNotIn("private-key", repr(Settings(api_key="private-key")))
