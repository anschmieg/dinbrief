from __future__ import annotations

import unicodedata
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import timedelta
from functools import lru_cache
from importlib.util import find_spec
from pathlib import Path
from typing import Any

from .config import cache_dir
from .model import ParsedLetter, Party
from .parser import LetterParseError, parse_file

INDEX_VERSION = 1
TABLE_NAME = "letters"


class SearchUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class IndexedLetter:
    path: Path
    date: str
    language: str
    sender: str
    recipient: str
    subject: str
    delivery: str
    tags: tuple[str, ...]
    body: str


def search_available() -> bool:
    return find_spec("lancedb") is not None


def database_path() -> Path:
    return cache_dir() / f"search-v{INDEX_VERSION}.lance"


def _require_search() -> None:
    if not search_available():
        raise SearchUnavailableError(
            "Optional search support is not installed. "
            "Install it with: uv tool install 'dinbrief[search]'"
        )


@lru_cache(maxsize=4)
def _connect(path: Path) -> Any:
    import lancedb  # type: ignore[import-untyped]

    return lancedb.connect(path, read_consistency_interval=timedelta(0))


def _record(path: Path, letter: ParsedLetter) -> IndexedLetter:
    sender = letter.metadata.sender
    sender_name = sender.display_name if isinstance(sender, Party) else sender
    return IndexedLetter(
        path=path.resolve(),
        date=str(letter.metadata.date),
        language=letter.metadata.language,
        sender=sender_name,
        recipient=letter.metadata.recipient.display_name,
        subject=letter.metadata.subject,
        delivery=letter.metadata.delivery.method,
        tags=tuple(letter.metadata.tags),
        body=letter.body,
    )


def _lance_record(item: IndexedLetter) -> dict[str, object]:
    record = asdict(item)
    record["path"] = str(item.path)
    record["tags"] = list(item.tags)
    record["search_text"] = "\n".join(
        (str(item.path), item.sender, item.recipient, item.subject, *item.tags, item.body)
    )
    return record


def _schema() -> object:
    import pyarrow as pa  # type: ignore[import-untyped]

    return pa.schema(
        [
            pa.field("path", pa.string(), nullable=False),
            pa.field("date", pa.string(), nullable=False),
            pa.field("language", pa.string(), nullable=False),
            pa.field("sender", pa.string(), nullable=False),
            pa.field("recipient", pa.string(), nullable=False),
            pa.field("subject", pa.string(), nullable=False),
            pa.field("delivery", pa.string(), nullable=False),
            pa.field("tags", pa.list_(pa.string()), nullable=False),
            pa.field("body", pa.string(), nullable=False),
            pa.field("search_text", pa.string(), nullable=False),
        ]
    )


def rebuild_index(roots: Iterable[Path]) -> tuple[int, list[tuple[Path, str]]]:
    _require_search()

    records: list[IndexedLetter] = []
    errors: list[tuple[Path, str]] = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.letter.md"):
            try:
                records.append(_record(path, parse_file(path)))
            except LetterParseError as exc:
                errors.append((path, str(exc)))

    database = _connect(database_path())
    table = database.create_table(
        TABLE_NAME,
        schema=_schema(),
        mode="overwrite",
    )
    if records:
        table.add([_lance_record(item) for item in records])
    from lancedb.index import FTS  # type: ignore[import-untyped]

    table.create_index(
        "search_text",
        config=FTS(stem=False, remove_stop_words=False, ascii_folding=True),
        replace=True,
    )
    return len(records), errors


def query_index(query: str, *, fuzziness: int = 1, limit: int = 50) -> list[IndexedLetter]:
    _require_search()
    if not database_path().exists():
        return []

    from lancedb.query import MatchQuery  # type: ignore[import-untyped]

    normalized_query = "".join(
        character
        for character in unicodedata.normalize("NFKD", query)
        if not unicodedata.combining(character)
    ).casefold()
    table = _connect(database_path()).open_table(TABLE_NAME)
    rows = (
        table.search(MatchQuery(normalized_query, "search_text", fuzziness=fuzziness))
        .select(
            [
                "path",
                "date",
                "language",
                "sender",
                "recipient",
                "subject",
                "delivery",
                "tags",
                "body",
                "_score",
            ]
        )
        .limit(limit)
        .to_list()
    )
    return [
        IndexedLetter(
            path=Path(row["path"]),
            date=row["date"],
            language=row["language"],
            sender=row["sender"],
            recipient=row["recipient"],
            subject=row["subject"],
            delivery=row["delivery"],
            tags=tuple(row["tags"]),
            body=row["body"],
        )
        for row in rows
    ]
