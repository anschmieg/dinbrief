from pathlib import Path

import pytest

from dinbrief.parser import LetterParseError, parse_file, parse_text

ROOT = Path(__file__).parents[1]


@pytest.mark.parametrize("language", ["de", "en"])
def test_examples_parse(language: str) -> None:
    letter = parse_file(ROOT / "examples" / language / "example.letter.md")
    assert letter.metadata.format == "dinbrief/v1"
    assert letter.body


def test_rejects_missing_frontmatter() -> None:
    with pytest.raises(LetterParseError, match="Missing YAML frontmatter"):
        parse_text("Just text")


def test_normalizes_tags() -> None:
    text = (ROOT / "examples" / "de" / "example.letter.md").read_text(encoding="utf-8")
    parsed = parse_text(text.replace("[vertrag, kündigung]", "[Vertrag, vertrag, Kündigung]"))
    assert parsed.metadata.tags == ["vertrag", "kündigung"]


def test_organization_only_recipient_is_valid() -> None:
    text = (ROOT / "examples" / "de" / "example.letter.md").read_text(encoding="utf-8")
    text = text.replace("  name: Erika Beispiel\n", "  name:\n")
    parsed = parse_text(text)
    assert parsed.metadata.recipient.display_name == "Beispiel GmbH"


def test_rejects_unknown_frontmatter_fields_instead_of_ignoring_typos() -> None:
    text = (ROOT / "examples" / "de" / "example.letter.md").read_text(encoding="utf-8")

    with pytest.raises(LetterParseError, match="subject_typo"):
        parse_text(text.replace("subject:", "subject_typo:"))


def test_rejects_unknown_nested_layout_fields() -> None:
    text = (ROOT / "examples" / "de" / "example.letter.md").read_text(encoding="utf-8")

    with pytest.raises(LetterParseError, match="fold_marker"):
        parse_text(text.replace("tags:", "layout:\n  fold_marker: true\ntags:"))


def test_configured_sender_default_is_applied_before_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = (ROOT / "examples" / "de" / "example.letter.md").read_text(encoding="utf-8")
    sender_start = text.index("sender:\n")
    recipient_start = text.index("recipient:\n")
    text = text[:sender_start] + text[recipient_start:]
    monkeypatch.setattr(
        "dinbrief.config.load_config",
        lambda: {
            "defaults": {
                "sender": {
                    "name": "Configured Sender",
                    "address": {
                        "street": "Example 1",
                        "postal_code": "12345",
                        "city": "Berlin",
                        "country": "DE",
                    },
                }
            }
        },
    )

    parsed = parse_text(text)

    assert parsed.metadata.sender.display_name == "Configured Sender"  # type: ignore[union-attr]
