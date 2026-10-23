"""Small settings form; validation and applying changes belong to the controller."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel,
    QApplication, QFrame, QLineEdit, QScrollArea, QVBoxLayout, QWidget,
)

from config.settings import Settings


class SettingsDialog(QDialog):
    def __init__(self, apply_settings: Callable[[Settings], None]) -> None:
        super().__init__()
        self._apply = apply_settings
        self.setWindowTitle("Selection Copilot 设置")
        self.setMinimumWidth(480)
        self.base_url = QLineEdit()
        self.base_url.setPlaceholderText("https://api.deepseek.com/v1")
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.model = QLineEdit()
        self.hotkey = QLineEdit()
        self.hotkey.setPlaceholderText("alt+q")
        self.auto_select = QCheckBox("鼠标或键盘选中文字后自动弹出工具栏")
        self.clipboard_fallback = QComboBox()
        for label, value in (("快捷键及微信自动兼容（推荐）", "compatible"),
                             ("仅按快捷键时允许", "manual"),
                             ("快捷键及指定应用自动划词", "allowlist"), ("禁用模拟复制", "never")):
            self.clipboard_fallback.addItem(label, value)
        self.clipboard_apps = QLineEdit()
        self.clipboard_apps.setPlaceholderText("例如 acrobat.exe，用逗号分隔")
        self.clipboard_apps.setEnabled(False)
        self.clipboard_fallback.currentIndexChanged.connect(
            lambda: self.clipboard_apps.setEnabled(self.clipboard_fallback.currentData() == "allowlist")
        )
        self.excluded_apps = QLineEdit()
        self.excluded_apps.setPlaceholderText("在这些应用内暂停取词，例如 game.exe")
        self.stream = QCheckBox("边生成边显示答案")
        self.thinking = self._thinking_combo()
        self.translation_thinking = self._thinking_combo()
        form = QFormLayout()
        for label, widget in (
            ("API 地址", self.base_url), ("API Key（保存在本机）", self.api_key),
            ("模型", self.model), ("全局快捷键", self.hotkey),
            ("自动划词", self.auto_select), ("流式显示", self.stream),
            ("复制兼容范围", self.clipboard_fallback),
            ("自动复制兼容应用", self.clipboard_apps), ("暂停取词的应用", self.excluded_apps),
            ("DeepSeek 解释 / Chat 思考", self.thinking),
            ("DeepSeek 翻译思考", self.translation_thinking),
        ):
            form.addRow(label, widget)
        note = QLabel("默认优先直接读取选区；微信无法读取时允许一次兼容复制。可选择仅快捷键或禁用复制。终端及常见 IDE 不模拟复制。设置保存后立即生效。")
        note.setWordWrap(True)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #b42318")
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        content = QWidget()
        body = QVBoxLayout(content)
        body.addLayout(form)
        body.addWidget(note)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)
        layout.addWidget(scroll)
        layout.addWidget(self.error)
        layout.addWidget(buttons)
        screen = QApplication.primaryScreen()
        if screen:
            available = screen.availableGeometry()
            self.setMinimumWidth(min(480, available.width() - 40))
            self.resize(min(560, available.width() - 40), min(560, available.height() - 60))
        else:
            self.resize(560, 560)

    @staticmethod
    def _thinking_combo() -> QComboBox:
        combo = QComboBox()
        for label, value in (("关闭（更快）", "disabled"), ("开启", "enabled"), ("使用服务商默认值", "default")):
            combo.addItem(label, value)
        return combo

    def load(self, settings: Settings) -> None:
        for name in ("base_url", "api_key", "model", "hotkey", "clipboard_apps", "excluded_apps"):
            getattr(self, name).setText(getattr(settings, name))
        self.auto_select.setChecked(settings.auto_select)
        self.stream.setChecked(settings.stream)
        self.clipboard_fallback.setCurrentIndex(self.clipboard_fallback.findData(settings.clipboard_fallback))
        for name in ("thinking", "translation_thinking"):
            combo = getattr(self, name)
            combo.setCurrentIndex(combo.findData(getattr(settings, name)))
        self.error.clear()

    def _save(self) -> None:
        settings = Settings(
            base_url=self.base_url.text().strip().rstrip("/"), api_key=self.api_key.text().strip(),
            model=self.model.text().strip(), hotkey=self.hotkey.text().strip().lower(),
            auto_select=self.auto_select.isChecked(), stream=self.stream.isChecked(),
            thinking=self.thinking.currentData(), translation_thinking=self.translation_thinking.currentData(),
            clipboard_fallback=self.clipboard_fallback.currentData(),
            clipboard_apps=self.clipboard_apps.text().strip(), excluded_apps=self.excluded_apps.text().strip(),
        )
        try:
            settings.validate()
            self._apply(settings)
        except (ValueError, OSError, RuntimeError) as error:
            self.error.setText(str(error))
            return
        self.accept()
