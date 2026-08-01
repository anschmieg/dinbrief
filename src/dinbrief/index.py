from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .config import cache_dir
from .model import ParsedLetter, Party
from .parser import LetterParseError, parse_file


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


def database_path() -> Path:
    return cache_dir() / "letters.sqlite3"


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(database_path())
    connection.row_factory = sqlite3.Row
    return connection


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


def rebuild_index(roots: Iterable[Path]) -> tuple[int, list[tuple[Path, str]]]:
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
    with _connect() as connection:
        connection.executescript(
            """
            DROP TABLE IF EXISTS letters;
            CREATE TABLE letters (
                path TEXT PRIMARY KEY,
                date TEXT NOT NULL,
                language TEXT NOT NULL,
                sender TEXT NOT NULL,
                recipient TEXT NOT NULL,
                subject TEXT NOT NULL,
                delivery TEXT NOT NULL,
                tags TEXT NOT NULL,
                body TEXT NOT NULL,
                search_text TEXT NOT NULL
            );
            CREATE INDEX letters_date ON letters(date);
            CREATE INDEX letters_language ON letters(language);
            CREATE INDEX letters_delivery ON letters(delivery);
            """
        )
        connection.executemany(
            "INSERT INTO letters VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    str(item.path),
                    item.date,
                    item.language,
                    item.sender,
                    item.recipient,
                    item.subject,
                    item.delivery,
                    json.dumps(item.tags, ensure_ascii=False),
                    item.body,
                    "\n".join(
                        (
                            str(item.path),
                            item.sender,
                            item.recipient,
                            item.subject,
                            *item.tags,
                            item.body,
                        )
                    ).casefold(),
                )
                for item in records
            ],
        )
    return len(records), errors


def query_index(query: str) -> list[IndexedLetter]:
    if not database_path().exists():
        return []
    needle = f"%{query.casefold()}%"
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT * FROM letters
            WHERE search_text LIKE ?
            ORDER BY date DESC, path
            """,
            (needle,),
        ).fetchall()
    return [
        IndexedLetter(
            path=Path(row["path"]),
            date=row["date"],
            language=row["language"],
            sender=row["sender"],
            recipient=row["recipient"],
            subject=row["subject"],
            delivery=row["delivery"],
            tags=tuple(json.loads(row["tags"])),
            body=row["body"],
        )
        for row in rows
    ]
