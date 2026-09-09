"""Small settings form; validation and applying changes belong to the controller."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel,
    QLineEdit, QVBoxLayout,
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
        self.auto_select = QCheckBox("拖动或双击选中文字后自动弹出工具栏")
        self.stream = QCheckBox("边生成边显示答案")
        self.thinking = self._thinking_combo()
        self.translation_thinking = self._thinking_combo()
        form = QFormLayout()
        for label, widget in (
            ("API 地址", self.base_url), ("API Key（保存在本机）", self.api_key),
            ("模型", self.model), ("全局快捷键", self.hotkey),
            ("自动划词", self.auto_select), ("流式显示", self.stream),
            ("DeepSeek 解释 / Chat 思考", self.thinking),
            ("DeepSeek 翻译思考", self.translation_thinking),
        ):
            form.addRow(label, widget)
        note = QLabel("设置保存后立即生效；已打开的 Chat 窗口继续使用打开时的模型。")
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
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addWidget(self.error)
        layout.addWidget(buttons)

    @staticmethod
    def _thinking_combo() -> QComboBox:
        combo = QComboBox()
        for label, value in (("关闭（更快）", "disabled"), ("开启", "enabled"), ("使用服务商默认值", "default")):
            combo.addItem(label, value)
        return combo

    def load(self, settings: Settings) -> None:
        for name in ("base_url", "api_key", "model", "hotkey"):
            getattr(self, name).setText(getattr(settings, name))
        self.auto_select.setChecked(settings.auto_select)
        self.stream.setChecked(settings.stream)
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
        )
        try:
            settings.validate()
            self._apply(settings)
        except (ValueError, OSError, RuntimeError) as error:
            self.error.setText(str(error))
            return
        self.accept()
