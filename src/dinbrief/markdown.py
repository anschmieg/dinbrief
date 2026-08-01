from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from markdown_it import MarkdownIt


def escape_typst(value: str) -> str:
    for old, new in (("\\", "\\\\"), ("#", "\\#"), ("$", "\\$"), ("@", "\\@"), ("[", "\\["), ("]", "\\]")):
        value = value.replace(old, new)
    return value


def escape_typst_string(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r", "\\r")
        .replace("\n", "\\n")
    )


def markdown_to_typst(source: str) -> str:
    """Convert the deliberately small supported Markdown subset to Typst markup."""
    tokens = MarkdownIt("commonmark").parse(source)
    output: list[str] = []
    lists: list[dict[str, int | str]] = []
    for token in tokens:
        if token.type in {"paragraph_open", "paragraph_close"}:
            if token.type == "paragraph_close":
                output.append("\n\n")
        elif token.type == "heading_open":
            output.append('#text(weight: "bold")[')
        elif token.type == "heading_close":
            output.append("]\n\n")
        elif token.type == "bullet_list_open":
            lists.append({"type": "bullet", "next": 1})
        elif token.type == "bullet_list_close":
            lists.pop()
            output.append("\n")
        elif token.type == "ordered_list_open":
            start = int(token.attrGet("start") or 1)
            lists.append({"type": "ordered", "next": start})
        elif token.type == "ordered_list_close":
            lists.pop()
            output.append("\n")
        elif token.type == "list_item_open":
            current = lists[-1]
            marker = "-"
            if current["type"] == "ordered":
                marker = f"{current['next']}."
                current["next"] = int(current["next"]) + 1
            output.append("  " * max(0, len(lists) - 1) + f"{marker} ")
        elif token.type == "blockquote_open":
            output.append("#quote(block: true)[")
        elif token.type == "blockquote_close":
            output.append("]\n\n")
        elif token.type in {"fence", "code_block"}:
            output.append(f'#raw("{escape_typst_string(token.content)}", block: true)\n\n')
        elif token.type == "hr":
            output.append("#line(length: 100%)\n\n")
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
            output.append(f'#link("{escape_typst_string(attrs.get("href", ""))}")[')
        elif token_type == "link_close":
            output.append("]")
        elif token_type == "image":
            attrs = dict(getattr(token, "attrs", {}) or {})
            output.append(
                f'#link("{escape_typst_string(attrs.get("src", ""))}")'
                f'[{escape_typst(getattr(token, "content", ""))}]'
            )
        elif token_type == "html_inline":
            output.append(content)
    return "".join(output)
