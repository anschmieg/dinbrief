from pathlib import Path

import pytest

from dinbrief import index


def _letter(
    subject: str,
    body: str,
    tags: list[str] | None = None,
    *,
    date: str = "2026-08-01",
    recipient: str = "Finanzamt Köln",
    language: str = "de-DE",
    delivery: str = "both",
) -> str:
    rendered_tags = "\n".join(f"  - {tag}" for tag in (tags or []))
    return f"""---
format: dinbrief/v2
language: {language}
sender:
  name: Erika Mustermann
  address:
    street: Musterstraße 1
    postal_code: "12345"
    city: Berlin
recipient:
  organization: {recipient}
  address:
    street: Amtsweg 2
    postal_code: "50667"
    city: Köln
date: {date}
salutation: Sehr geehrte Damen und Herren,
closing: Mit freundlichen Grüßen
tags:
{rendered_tags}
delivery:
  method: {delivery}
---

# {subject}

{body}
"""


@pytest.mark.skipif(not index.search_available(), reason="optional search extra is not installed")
def test_rebuild_and_unicode_search(tmp_path: Path, monkeypatch: object) -> None:
    database = tmp_path / "cache" / "search-v1.lance"
    monkeypatch.setattr(index, "database_path", lambda: database)  # type: ignore[attr-defined]
    database.parent.mkdir()
    source = tmp_path / "steuer" / "erklärung.letter.md"
    source.parent.mkdir()
    source.write_text(
        _letter("Änderung des Steuerbescheids", "Bitte prüfen Sie die Schätzung.", ["steuer"]),
        encoding="utf-8",
    )

    count, errors = index.rebuild_index([tmp_path, source.parent])

    assert count == 1
    assert errors == []
    assert index.index_is_stale([tmp_path]) is False
    assert [item.path for item in index.query_index("änderung")] == [source]
    assert [item.path for item in index.query_index("KÖLN")] == [source]
    assert [item.path for item in index.query_index("schätzung")] == [source]
    assert [item.path for item in index.query_index("Steuerbescheits")] == [source]

    source.write_text(
        _letter("Änderung des Steuerbescheids", "Geänderter Inhalt.", ["steuer"]),
        encoding="utf-8",
    )
    assert index.index_is_stale([tmp_path]) is True
    index.rebuild_index([tmp_path])
    assert index.index_is_stale([tmp_path]) is False
    source.unlink()
    assert index.index_is_stale([tmp_path]) is True


@pytest.mark.skipif(not index.search_available(), reason="optional search extra is not installed")
def test_rebuild_reports_invalid_letters(tmp_path: Path, monkeypatch: object) -> None:
    database = tmp_path / "search-v1.lance"
    monkeypatch.setattr(index, "database_path", lambda: database)  # type: ignore[attr-defined]
    (tmp_path / "invalid.letter.md").write_text("not frontmatter", encoding="utf-8")

    count, errors = index.rebuild_index([tmp_path])

    assert count == 0
    assert len(errors) == 1


def test_missing_optional_package_has_actionable_error(monkeypatch: object) -> None:
    monkeypatch.setattr(index, "search_available", lambda: False)  # type: ignore[attr-defined]

    with pytest.raises(index.SearchUnavailableError, match=r"dinbrief\[search\]"):
        index.query_index("example")


@pytest.mark.skipif(not index.search_available(), reason="optional search extra is not installed")
def test_filters_and_sorting(tmp_path: Path, monkeypatch: object) -> None:
    database = tmp_path / "search-v2.lance"
    monkeypatch.setattr(index, "database_path", lambda: database)  # type: ignore[attr-defined]
    german = tmp_path / "tax" / "german.letter.md"
    english = tmp_path / "contracts" / "english.letter.md"
    german.parent.mkdir()
    english.parent.mkdir()
    german.write_text(
        _letter(
            "Tax matter",
            "Please review this matter.",
            ["tax"],
            date="2025-01-02",
            delivery="print",
        ),
        encoding="utf-8",
    )
    english.write_text(
        _letter(
            "Contract matter",
            "Please review this matter.",
            ["contract"],
            date="2026-03-04",
            recipient="Jane Example",
            language="en-GB",
            delivery="email",
        ),
        encoding="utf-8",
    )
    index.rebuild_index([tmp_path])

    facets = index.index_facets()
    assert facets.tags == ("contract", "tax")
    assert facets.languages == ("de-DE", "en-GB")
    assert facets.deliveries == ("email", "print")

    assert [
        item.path for item in index.query_index("matter", sort=index.SearchSort.DATE_DESC)
    ] == [
        english,
        german,
    ]
    assert [
        item.path
        for item in index.query_index(
            "matter", filters=index.SearchFilters(tag="contract", language="en-GB")
        )
    ] == [english]
    assert [
        item.path
        for item in index.query_index(
            "matter",
            filters=index.SearchFilters(
                recipient="jane",
                delivery="email",
                date_from="2026-01-01",
                date_to="2026-12-31",
                folder="contracts",
            ),
        )
    ] == [english]
