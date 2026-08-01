from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from markdown_it import MarkdownIt


def escape_typst(value: str) -> str:
    for old, new in (("\\", "\\\\"), ("#", "\\#"), ("$", "\\$"), ("@", "\\@"), ("[", "\\["), ("]", "\\]")):
        value = value.replace(old, new)
    return value


def markdown_to_typst(source: str) -> str:
    """Convert the deliberately small supported Markdown subset to Typst markup."""
    tokens = MarkdownIt("commonmark").parse(source)
    output: list[str] = []
    list_depth = 0
    for token in tokens:
        if token.type in {"paragraph_open", "paragraph_close"}:
            if token.type == "paragraph_close":
                output.append("\n\n")
        elif token.type == "bullet_list_open":
            list_depth += 1
        elif token.type == "bullet_list_close":
            list_depth -= 1
            output.append("\n")
        elif token.type == "list_item_open":
            output.append("  " * max(0, list_depth - 1) + "- ")
        elif token.type == "inline":
            output.append(_inline_to_typst(token.children or []))
        elif token.type == "softbreak":
            output.append(" ")
    return "".join(output).strip()


def _inline_to_typst(tokens: Sequence[Any]) -> str:
    output: list[str] = []
    for token in tokens:
        token_type = getattr(token, "type", "")
        content = escape_typst(getattr(token, "content", ""))
        if token_type == "text":
            output.append(content)
        elif token_type == "softbreak":
            output.append(" ")
        elif token_type == "hardbreak":
            output.append("\\\n")
        elif token_type == "strong_open" or token_type == "strong_close":
            output.append("*")
        elif token_type == "em_open" or token_type == "em_close":
            output.append("_")
        elif token_type == "code_inline":
            output.append(f"`{content}`")
        elif token_type == "link_open":
            attrs = dict(getattr(token, "attrs", {}) or {})
            output.append(f'#link("{escape_typst(attrs.get("href", ""))}")[')
        elif token_type == "link_close":
            output.append("]")
    return "".join(output)
