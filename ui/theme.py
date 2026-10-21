"""Shared colors, typography and screen geometry in Qt logical pixels."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPalette
from PySide6.QtWidgets import QWidget

BACKGROUND = "#151b24"
SURFACE = "#1e2734"
BORDER = "#354256"
TEXT = "#e7edf7"
MUTED = "#a5b3c7"
ACCENT = "#78aaff"
ERROR = "#ffaaa5"

STYLE = f"""
QWidget {{ color: {TEXT}; }}
QWidget#chatWindow, QFrame#floatingToolbar, QFrame#translationPopup {{
    background: {BACKGROUND};
}}
QFrame#floatingToolbar, QFrame#translationPopup {{
    border: 1px solid {BORDER}; border-radius: 10px;
}}
QLabel[muted="true"] {{ color: {MUTED}; }}
QLabel#windowHeading {{ font-weight: 600; }}
QPlainTextEdit, QTextEdit, QTextBrowser {{
    background: {SURFACE}; border: 1px solid {BORDER};
    border-radius: 8px; padding: 8px; selection-background-color: #365784;
    selection-color: {TEXT};
}}
QTextBrowser#conversation {{ background: transparent; border: 0; padding: 0; }}
QTextBrowser#resultText {{ background: transparent; border: 0; padding: 2px; }}
QPlainTextEdit:focus {{ border: 1px solid {ACCENT}; }}
QPushButton, QToolButton {{
    background: transparent; border: 1px solid transparent;
    border-radius: 6px; padding: 6px 12px;
}}
QPushButton:hover, QToolButton:hover {{ background: #2b394d; }}
QPushButton:pressed, QToolButton:pressed {{ background: #354962; }}
QPushButton:focus, QToolButton:focus {{ border: 1px solid {ACCENT}; }}
QPushButton:disabled, QToolButton:disabled {{ color: #7b899e; }}
QPushButton[primary="true"] {{ background: #447bd2; color: #ffffff; font-weight: 600; }}
QPushButton[primary="true"]:hover {{ background: #528be5; }}
QPushButton[primary="true"]:pressed {{ background: #3767b5; }}
QPushButton[primary="true"]:disabled {{ background: #2b3b54; color: {MUTED}; }}
QToolButton#contextToggle {{ text-align: left; padding: 2px 0; color: {MUTED}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #526178; border-radius: 3px; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: #70839f; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; }}
QScrollBar::handle:horizontal {{ background: #526178; border-radius: 3px; min-width: 24px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}
QSplitter::handle {{ background: transparent; height: 8px; }}
QSplitter::handle:hover {{ background: {BORDER}; border-radius: 3px; }}
QToolTip {{ color: {TEXT}; background: {SURFACE}; border: 1px solid {BORDER}; padding: 5px; }}
"""


def apply_theme(widget: QWidget) -> None:
    """Set an explicit palette so light/dark Windows themes remain consistent."""
    font = QFont()
    font.setFamilies(["Segoe UI", "Microsoft YaHei UI", "Noto Sans CJK SC"])
    font.setPointSizeF(10.5)
    widget.setFont(font)
    palette = widget.palette()
    for role, color in (
        (QPalette.ColorRole.Window, BACKGROUND),
        (QPalette.ColorRole.Base, SURFACE),
        (QPalette.ColorRole.Text, TEXT),
        (QPalette.ColorRole.WindowText, TEXT),
        (QPalette.ColorRole.ButtonText, TEXT),
        (QPalette.ColorRole.PlaceholderText, MUTED),
        (QPalette.ColorRole.Highlight, "#365784"),
        (QPalette.ColorRole.HighlightedText, TEXT),
    ):
        palette.setColor(role, QColor(color))
    widget.setPalette(palette)
    widget.setStyleSheet(STYLE)


def available_geometry(position: QPoint) -> QRect:
    screen = QGuiApplication.screenAt(position) or QGuiApplication.primaryScreen()
    return screen.availableGeometry() if screen else QRect(position, QSize(800, 600))


def bounded_position(position: QPoint, size: QSize, available: QRect) -> QPoint:
    """Clamp against one actual screen, including negative multi-monitor origins."""
    return QPoint(
        max(available.left(), min(position.x(), available.right() - size.width() + 1)),
        max(available.top(), min(position.y(), available.bottom() - size.height() + 1)),
    )


def fit_window(
    window: QWidget, position: QPoint, preferred: QSize, *, available: QRect | None = None,
) -> None:
    """Fit a decorated window on its launch screen without double-scaling DPI."""
    available = (available if available is not None else available_geometry(position)).adjusted(12, 12, -12, -12)
    decoration = window.frameGeometry().size() - window.size()
    client = available.size() - decoration
    window.setMinimumSize(min(420, client.width()), min(440, client.height()))
    window.resize(preferred.boundedTo(client))
    frame = window.frameGeometry()
    frame.moveCenter(position)
    window.move(bounded_position(frame.topLeft(), frame.size(), available))
