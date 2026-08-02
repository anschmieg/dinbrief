from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import frontmatter
from markdown_it import MarkdownIt
from pydantic import ValidationError

from .config import effective_metadata
from .model import Letter, ParsedLetter


@dataclass(frozen=True)
class ParseIssue:
    code: str
    message: str
    field: str | None = None
    line: int | None = None
    column: int | None = None


class LetterParseError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "parse",
        field: str | None = None,
        line: int | None = None,
        column: int | None = None,
        issues: list[ParseIssue] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.field = field
        self.issues = issues or [ParseIssue(code, message, field, line, column)]


def _subject_and_body(content: str) -> tuple[str, str]:
    body = content.strip()
    if not body:
        raise LetterParseError(
            "Add a level-one Markdown heading (`# Subject`) after the frontmatter.",
            code="subject-missing",
            field="subject",
        )
    first_line, _, remainder = body.partition("\n")
    if not re.fullmatch(r"#\s+.+", first_line.strip()):
        raise LetterParseError(
            "The first content line must be the subject as a level-one Markdown heading (`# Subject`).",
            code="subject-missing",
            field="subject",
        )
    tokens = MarkdownIt().parse(body)
    headings = [token for token in tokens if token.type == "heading_open" and token.tag == "h1"]
    if len(headings) != 1:
        raise LetterParseError(
            "A letter must contain exactly one level-one heading; use lower-level headings in the body.",
            code="subject-multiple",
            field="subject",
        )
    inline = next((token for token in tokens if token.type == "inline"), None)
    subject = "".join(
        " " if child.type in {"softbreak", "hardbreak"} else child.content
        for child in (inline.children or [] if inline else [])
        if child.type in {"text", "code_inline", "softbreak", "hardbreak", "image"}
    ).strip()
    if not subject:
        raise LetterParseError("The subject heading must not be empty.", code="subject-empty", field="subject")
    return subject, remainder.strip()


def _validation_error(exc: ValidationError) -> LetterParseError:
    issues: list[ParseIssue] = []
    errors = sorted(exc.errors(), key=lambda error: error["type"] != "extra_forbidden")
    for error in errors:
        field = ".".join(str(part) for part in error["loc"])
        kind = error["type"]
        if kind == "missing":
            message = f"Required field `{field}` is missing."
            code = "field-missing"
        elif kind == "extra_forbidden":
            message = f"Unknown field `{field}`. Remove it or check its spelling."
            code = "field-unknown"
        else:
            message = f"Invalid value for `{field}`: {error['msg']}."
            code = "field-invalid"
        issues.append(ParseIssue(code, message, field))
    first = issues[0]
    return LetterParseError(first.message, code=first.code, field=first.field, issues=issues)


def parse_text(text: str, source: str = "<memory>") -> ParsedLetter:
    try:
        post = frontmatter.loads(text)
    except Exception as exc:
        mark = getattr(exc, "problem_mark", None)
        raise LetterParseError(
            f"Invalid YAML frontmatter: {getattr(exc, 'problem', exc)}",
            code="yaml-invalid",
            line=getattr(mark, "line", 0) if mark else None,
            column=getattr(mark, "column", 0) if mark else None,
        ) from exc
    if not post.metadata:
        raise LetterParseError("Add YAML frontmatter at the start of the letter.", code="frontmatter-missing")
    raw: dict[str, Any] = dict(post.metadata)
    issues: list[ParseIssue] = []
    if "subject" in raw:
        issues.append(
            ParseIssue(
                "field-unknown",
                "Unknown field `subject`. Put the subject in the first Markdown H1 instead.",
                "subject",
            )
        )
    try:
        subject, body = _subject_and_body(post.content)
    except LetterParseError as exc:
        issues.extend(exc.issues)
        subject, body = "Missing subject", post.content.strip()
    try:
        merged = effective_metadata(raw)
        merged["subject"] = subject
        metadata = Letter.model_validate(merged)
    except ValidationError as exc:
        issues.extend(_validation_error(exc).issues)
        metadata = None
    except ValueError as exc:
        issues.append(ParseIssue("field-invalid", str(exc)))
        metadata = None
    if issues:
        first = issues[0]
        raise LetterParseError(
            first.message,
            code=first.code,
            field=first.field,
            issues=issues,
        )
    assert metadata is not None
    return ParsedLetter(source=source, metadata=metadata, body=body, raw_metadata=raw)


def parse_file(path: Path) -> ParsedLetter:
    if not path.name.endswith(".letter.md"):
        raise LetterParseError("Letter files must end in .letter.md")
    return parse_text(path.read_text(encoding="utf-8"), str(path))
