"""Persistent tray entry for settings, automatic selection and shutdown."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon


class CopilotTray(QSystemTrayIcon):
    def __init__(self, open_settings: Callable, toggle_auto: Callable, quit_app: Callable) -> None:
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor("#2563eb"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(2, 2, 60, 60, 14, 14)
        painter.setPen(QColor("white"))
        painter.setFont(QFont("Segoe UI", 23, QFont.Weight.Bold))
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "SC")
        painter.end()
        super().__init__(QIcon(pixmap))
        self.menu = QMenu()
        self.status_action = self.menu.addAction("Selection Copilot")
        self.status_action.setEnabled(False)
        self.menu.addSeparator()
        self.settings_action = self.menu.addAction("设置…", open_settings)
        self.auto_action = self.menu.addAction("自动划词")
        self.auto_action.setCheckable(True)
        self.auto_action.toggled.connect(toggle_auto)
        self.menu.addSeparator()
        self.quit_action = self.menu.addAction("退出", quit_app)
        self.setContextMenu(self.menu)
        self.activated.connect(lambda reason: open_settings() if reason == self.ActivationReason.DoubleClick else None)

    def update_status(self, hotkey: str, auto_select: bool) -> None:
        self.auto_action.blockSignals(True)
        self.auto_action.setChecked(auto_select)
        self.auto_action.blockSignals(False)
        self.status_action.setText(f"快捷键：{hotkey}")
        self.setToolTip(f"Selection Copilot\n{hotkey}\n自动划词：{'开启' if auto_select else '暂停'}")
