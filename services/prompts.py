"""Prompt definitions kept outside UI code."""

from __future__ import annotations


def build_quick_ask_prompt(selection: str) -> str:
    """Build the default concise explanation prompt for one text selection."""
    return f"""请解释下面内容。目标用户是计算机专业硕士。
优先用直白的话说明：
1. 它是什么
2. 在当前语境下是什么意思
3. 为什么重要
4. 必要时给一个简单例子
不要无意义扩展。

内容：
{selection}"""


def build_chat_context_message(selection: str) -> str:
    """Build the system message that anchors one temporary chat session."""
    return f"""The user selected the following content:

<selection>
{selection}
</selection>

Please answer questions primarily around this context."""
