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
