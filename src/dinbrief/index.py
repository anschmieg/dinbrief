from __future__ import annotations

import json
import unicodedata
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import timedelta
from enum import StrEnum
from functools import lru_cache
from importlib.util import find_spec
from pathlib import Path
from typing import Any, cast

from .config import cache_dir
from .model import ParsedLetter, Party
from .parser import LetterParseError, parse_file

INDEX_VERSION = 2
TABLE_NAME = "letters"


class SearchSort(StrEnum):
    RELEVANCE = "relevance"
    DATE_DESC = "date-desc"
    DATE_ASC = "date-asc"
    RECIPIENT = "recipient"
    SUBJECT = "subject"
    PATH = "path"


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
    score: float | None = None


@dataclass(frozen=True)
class SearchFilters:
    tag: str | None = None
    language: str | None = None
    sender: str | None = None
    recipient: str | None = None
    delivery: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    folder: str | None = None


@dataclass(frozen=True)
class SearchFacets:
    tags: tuple[str, ...] = ()
    languages: tuple[str, ...] = ()
    senders: tuple[str, ...] = ()
    recipients: tuple[str, ...] = ()
    deliveries: tuple[str, ...] = ()


def search_available() -> bool:
    return find_spec("lancedb") is not None


def database_path() -> Path:
    return cache_dir() / f"search-v{INDEX_VERSION}.lance"


def index_state_path() -> Path:
    database = database_path()
    return database.with_name(f"{database.name}.sources.json")


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
    record.pop("score")
    record["path"] = str(item.path)
    record["tags"] = list(item.tags)
    record["search_text"] = "\n".join(
        (str(item.path), item.sender, item.recipient, item.subject, *item.tags, item.body)
    )
    record["sender_key"] = _normalize(item.sender)
    record["recipient_key"] = _normalize(item.recipient)
    record["path_key"] = _normalize(str(item.path))
    record["tags_key"] = "|" + "|".join(_normalize(tag) for tag in item.tags) + "|"
    return record


def _normalize(value: str) -> str:
    return "".join(
        character
        for character in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(character)
    ).casefold()


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
            pa.field("sender_key", pa.string(), nullable=False),
            pa.field("recipient_key", pa.string(), nullable=False),
            pa.field("path_key", pa.string(), nullable=False),
            pa.field("tags_key", pa.string(), nullable=False),
        ]
    )


def _letter_paths(roots: Iterable[Path]) -> list[Path]:
    paths: set[Path] = set()
    for root in roots:
        expanded = root.expanduser()
        if not expanded.exists() or not expanded.is_dir():
            continue
        paths.update(path.resolve() for path in expanded.rglob("*.letter.md") if path.is_file())
    return sorted(paths, key=lambda path: str(path).casefold())


def _source_snapshot(paths: Iterable[Path]) -> list[list[str | int]]:
    snapshot: list[list[str | int]] = []
    for path in paths:
        try:
            stat = path.stat()
        except OSError:
            continue
        snapshot.append([str(path), stat.st_mtime_ns, stat.st_size])
    return snapshot


def index_is_stale(roots: Iterable[Path]) -> bool:
    state = index_state_path()
    if not database_path().exists() or not state.exists():
        return True
    paths = _letter_paths(roots)
    try:
        previous = cast(list[list[str | int]], json.loads(state.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError):
        return True
    return previous != _source_snapshot(paths)


def rebuild_index(roots: Iterable[Path]) -> tuple[int, list[tuple[Path, str]]]:
    _require_search()

    records: list[IndexedLetter] = []
    errors: list[tuple[Path, str]] = []
    paths = _letter_paths(roots)
    for path in paths:
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
    state = index_state_path()
    state.write_text(json.dumps(_source_snapshot(paths), ensure_ascii=False), encoding="utf-8")
    return len(records), errors


def _quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _where(filters: SearchFilters) -> str | None:
    clauses: list[str] = []
    if filters.tag:
        clauses.append(f"tags_key LIKE {_quote(f'%|{_normalize(filters.tag)}|%')}")
    if filters.language:
        clauses.append(f"language = {_quote(filters.language)}")
    if filters.sender:
        clauses.append(f"sender_key LIKE {_quote(f'%{_normalize(filters.sender)}%')}")
    if filters.recipient:
        clauses.append(f"recipient_key LIKE {_quote(f'%{_normalize(filters.recipient)}%')}")
    if filters.delivery:
        clauses.append(f"delivery = {_quote(filters.delivery)}")
    if filters.date_from:
        clauses.append(f"date >= {_quote(filters.date_from)}")
    if filters.date_to:
        clauses.append(f"date <= {_quote(filters.date_to)}")
    if filters.folder:
        clauses.append(f"path_key LIKE {_quote(f'%{_normalize(filters.folder)}%')}")
    return " AND ".join(clauses) or None


def _sort_results(items: list[IndexedLetter], order: SearchSort) -> list[IndexedLetter]:
    if order == SearchSort.RELEVANCE:
        return items
    if order in {SearchSort.DATE_DESC, SearchSort.DATE_ASC}:
        path_sorted = sorted(items, key=lambda item: str(item.path).casefold())
        return sorted(
            path_sorted,
            key=lambda item: item.date,
            reverse=order == SearchSort.DATE_DESC,
        )
    key = {
        SearchSort.RECIPIENT: lambda item: (
            item.recipient.casefold(),
            item.date,
            str(item.path),
        ),
        SearchSort.SUBJECT: lambda item: (item.subject.casefold(), item.date, str(item.path)),
        SearchSort.PATH: lambda item: (str(item.path).casefold(),),
    }[order]
    return sorted(items, key=key)


def query_index(
    query: str,
    *,
    filters: SearchFilters | None = None,
    sort: SearchSort = SearchSort.RELEVANCE,
    fuzziness: int = 1,
    limit: int = 50,
) -> list[IndexedLetter]:
    _require_search()
    if not database_path().exists():
        return []

    from lancedb.query import MatchQuery  # type: ignore[import-untyped]

    normalized_query = _normalize(query)
    table = _connect(database_path()).open_table(TABLE_NAME)
    builder = table.search(MatchQuery(normalized_query, "search_text", fuzziness=fuzziness))
    expression = _where(filters or SearchFilters())
    if expression:
        builder = builder.where(expression, prefilter=True)
    rows = (
        builder.select(
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
        .limit(limit if sort == SearchSort.RELEVANCE else 10_000)
        .to_list()
    )
    results = [
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
            score=float(row["_score"]) if row.get("_score") is not None else None,
        )
        for row in rows
    ]
    return _sort_results(results, sort)[:limit]


def index_facets() -> SearchFacets:
    _require_search()
    if not database_path().exists():
        return SearchFacets()
    table = _connect(database_path()).open_table(TABLE_NAME)
    rows = table.search().select(
        ["tags", "language", "sender", "recipient", "delivery"]
    ).limit(10_000).to_list()
    return SearchFacets(
        tags=tuple(sorted({tag for row in rows for tag in row["tags"]}, key=str.casefold)),
        languages=tuple(sorted({row["language"] for row in rows})),
        senders=tuple(sorted({row["sender"] for row in rows}, key=str.casefold)),
        recipients=tuple(sorted({row["recipient"] for row in rows}, key=str.casefold)),
        deliveries=tuple(sorted({row["delivery"] for row in rows})),
    )
