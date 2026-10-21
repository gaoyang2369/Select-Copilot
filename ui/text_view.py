"""Selectable rich text with safe Markdown and consistent paragraph spacing."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import (
    QColor, QTextBlockFormat, QTextCharFormat, QTextCursor, QTextDocument,
    QTextDocumentFragment, QTextOption,
)
from PySide6.QtWidgets import QTextBrowser

from ui.theme import ACCENT, ERROR, MUTED, TEXT


class TextView(QTextBrowser):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        self.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.document().setDocumentMargin(10)

    def loadResource(self, resource_type, name):  # type: ignore[no-untyped-def]
        # Model output is content, never a request to load local/remote images.
        return None

    def insert_body(self, cursor: QTextCursor, text: str, *, markdown: bool = False) -> None:
        block = QTextBlockFormat()
        block.setLineHeight(145, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
        cursor.setBlockFormat(block)
        body = QTextCharFormat()
        body.setForeground(QColor(TEXT))
        cursor.setCharFormat(body)
        if markdown:
            document = QTextDocument()
            document.setDefaultFont(self.font())
            document.setDefaultStyleSheet(
                f"body {{ color: {TEXT}; }} p, li {{ line-height: 145%; }}"
                "p { margin-top: 4px; margin-bottom: 10px; }"
                f"a {{ color: {ACCENT}; }} pre {{ background-color: #101620; }}"
                "code, pre { font-family: 'Cascadia Code', Consolas, monospace; }"
            )
            document.setMarkdown(
                text, QTextDocument.MarkdownFeature.MarkdownDialectGitHub
                | QTextDocument.MarkdownFeature.MarkdownNoHTML,
            )
            block = document.begin()
            while block.isValid():
                formatting = block.blockFormat()
                formatting.setNonBreakableLines(False)
                formatting.setLineHeight(145, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
                QTextCursor(block).setBlockFormat(formatting)
                block = block.next()
            cursor.insertFragment(QTextDocumentFragment(document))
        else:
            cursor.insertText(text)

    def insert_message(
        self, cursor: QTextCursor, author: str, text: str, *, markdown: bool = False,
    ) -> None:
        heading = QTextCharFormat()
        heading.setFontWeight(600)
        heading.setForeground(QColor(ERROR if author == "Error" else ACCENT if author == "AI" else MUTED))
        block = QTextBlockFormat()
        block.setTopMargin(12)
        block.setBottomMargin(6)
        cursor.setBlockFormat(block)
        cursor.setCharFormat(heading)
        cursor.insertText(f"{author}:")
        cursor.insertBlock()
        self.insert_body(cursor, text, markdown=markdown)
        cursor.insertBlock()

    def show_body(self, text: str, *, markdown: bool = False) -> None:
        self.clear()
        cursor = QTextCursor(self.document())
        self.insert_body(cursor, text, markdown=markdown)
        self.verticalScrollBar().setValue(0)
