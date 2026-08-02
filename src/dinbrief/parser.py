from __future__ import annotations

from pathlib import Path
from typing import Any

import frontmatter
from pydantic import ValidationError

from .config import effective_metadata
from .model import Letter, ParsedLetter

MARKDOWNLINT_DIRECTIVE = "<!-- markdownlint-disable-file MD013 MD041 -->"


class LetterParseError(ValueError):
    pass


def parse_text(text: str, source: str = "<memory>") -> ParsedLetter:
    try:
        post = frontmatter.loads(text)
    except Exception as exc:
        raise LetterParseError(f"Invalid YAML frontmatter: {exc}") from exc
    if not post.metadata:
        raise LetterParseError("Missing YAML frontmatter")
    raw: dict[str, Any] = dict(post.metadata)
    try:
        merged = effective_metadata(raw)
        metadata = Letter.model_validate(merged)
    except (ValidationError, ValueError) as exc:
        raise LetterParseError(str(exc)) from exc
    body = post.content.strip()
    if body.startswith(MARKDOWNLINT_DIRECTIVE):
        body = body.removeprefix(MARKDOWNLINT_DIRECTIVE).lstrip()
    return ParsedLetter(source=source, metadata=metadata, body=body, raw_metadata=raw)


def parse_file(path: Path) -> ParsedLetter:
    if not path.name.endswith(".letter.md"):
        raise LetterParseError("Letter files must end in .letter.md")
    return parse_text(path.read_text(encoding="utf-8"), str(path))
