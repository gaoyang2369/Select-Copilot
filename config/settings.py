"""Small validated settings model, loaded from .env and a local JSON file."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values

from config.paths import application_dir, data_dir
from core.hotkey import HOTKEY, parse_hotkey


@dataclass(frozen=True)
class Settings:
    base_url: str = ""
    api_key: str = field(default="", repr=False)
    model: str = ""
    hotkey: str = HOTKEY
    auto_select: bool = True
    stream: bool = True
    thinking: str = "disabled"
    translation_thinking: str = "disabled"

    def validate(self) -> None:
        for item in fields(self):
            value = getattr(self, item.name)
            expected = bool if item.name in ("auto_select", "stream") else str
            if type(value) is not expected:
                raise ValueError(f"设置 {item.name} 的类型不正确。")
        parse_hotkey(self.hotkey)
        if self.base_url:
            url = urlsplit(self.base_url)
            if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password or url.query or url.fragment:
                raise ValueError("API 地址需要是 http/https 地址，不包含账号、查询参数或片段。")
        if any(value not in ("enabled", "disabled", "default") for value in (self.thinking, self.translation_thinking)):
            raise ValueError("思考模式需要是 enabled、disabled 或 default。")


class SettingsStore:
    def __init__(self, path: Path | None = None, env_path: Path | None = None) -> None:
        self.path = path or data_dir() / "settings.json"
        self.env_path = env_path or application_dir() / ".env"

    def defaults(self) -> Settings:
        values = {**dotenv_values(self.env_path), **os.environ}
        return Settings(
            base_url=values.get("BASE_URL", ""), api_key=values.get("API_KEY", ""),
            model=values.get("MODEL", ""), hotkey=values.get("HOTKEY", HOTKEY),
            auto_select=str(values.get("AUTO_SELECT", "true")).lower() != "false",
            stream=str(values.get("LLM_STREAM", "true")).lower() != "false",
            thinking=values.get("DEEPSEEK_THINKING", "disabled"),
            translation_thinking=values.get("DEEPSEEK_TRANSLATION_THINKING", "disabled"),
        )

    def load(self) -> Settings:
        values = asdict(self.defaults())
        if self.path.exists():
            saved = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(saved, dict):
                raise ValueError("设置文件需要是 JSON 对象。")
            values.update({key: value for key, value in saved.items() if key in values})
        settings = Settings(**values)
        settings.validate()
        return settings

    def save(self, settings: Settings) -> None:
        """Replace atomically; a failed write must leave the previous file intact."""
        settings.validate()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        try:
            temporary.write_text(json.dumps(asdict(settings), ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)
