from pathlib import Path

from dinbrief import index


def _letter(subject: str, body: str, tags: list[str] | None = None) -> str:
    rendered_tags = "\n".join(f"  - {tag}" for tag in (tags or []))
    return f"""---
format: dinbrief/v1
language: de-DE
sender:
  name: Erika Mustermann
  address:
    street: Musterstraße 1
    postal_code: "12345"
    city: Berlin
recipient:
  organization: Finanzamt Köln
  address:
    street: Amtsweg 2
    postal_code: "50667"
    city: Köln
date: 2026-08-01
subject: {subject}
salutation: Sehr geehrte Damen und Herren,
closing: Mit freundlichen Grüßen
tags:
{rendered_tags}
---

{body}
"""


def test_rebuild_and_unicode_search(tmp_path: Path, monkeypatch: object) -> None:
    database = tmp_path / "cache" / "letters.sqlite3"
    monkeypatch.setattr(index, "database_path", lambda: database)  # type: ignore[attr-defined]
    database.parent.mkdir()
    source = tmp_path / "steuer" / "erklärung.letter.md"
    source.parent.mkdir()
    source.write_text(
        _letter("Änderung des Steuerbescheids", "Bitte prüfen Sie die Schätzung.", ["steuer"]),
        encoding="utf-8",
    )

    count, errors = index.rebuild_index([tmp_path])

    assert count == 1
    assert errors == []
    assert [item.path for item in index.query_index("änderung")] == [source]
    assert [item.path for item in index.query_index("KÖLN")] == [source]
    assert [item.path for item in index.query_index("schätzung")] == [source]


def test_rebuild_reports_invalid_letters(tmp_path: Path, monkeypatch: object) -> None:
    database = tmp_path / "letters.sqlite3"
    monkeypatch.setattr(index, "database_path", lambda: database)  # type: ignore[attr-defined]
    (tmp_path / "invalid.letter.md").write_text("not frontmatter", encoding="utf-8")

    count, errors = index.rebuild_index([tmp_path])

    assert count == 0
    assert len(errors) == 1
