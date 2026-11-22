from pathlib import Path

import pytest

from dinbrief.parser import LetterParseError, parse_file, parse_text

ROOT = Path(__file__).parents[1]


@pytest.mark.parametrize("language", ["de", "en"])
def test_examples_parse(language: str) -> None:
    letter = parse_file(ROOT / "examples" / language / "example.letter.md")
    assert letter.metadata.format == "dinbrief/v2"
    assert letter.body


def test_subject_heading_is_extracted_from_rendered_body() -> None:
    source = (ROOT / "examples" / "de" / "example.letter.md").read_text(encoding="utf-8")
    parsed = parse_text(source)

    assert parsed.metadata.subject == "Kündigung meines Vertrags 12345"
    assert parsed.body.startswith("Hiermit kündige")


def test_rejects_missing_frontmatter() -> None:
    with pytest.raises(LetterParseError, match="Add YAML frontmatter"):
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
        parse_text(text.replace("date:", "subject_typo:"))


def test_rejects_subject_in_frontmatter() -> None:
    text = (ROOT / "examples" / "de" / "example.letter.md").read_text(encoding="utf-8")

    with pytest.raises(LetterParseError, match="Unknown field `subject`"):
        parse_text(text.replace("date:", "subject: Falsch\ndate:"))


def test_requires_exactly_one_subject_heading() -> None:
    text = (ROOT / "examples" / "de" / "example.letter.md").read_text(encoding="utf-8")

    with pytest.raises(LetterParseError, match="first content line"):
        parse_text(text.replace("# Kündigung", "Kündigung"))
    with pytest.raises(LetterParseError, match="exactly one"):
        parse_text(text.replace("Hiermit kündige", "# Zweiter Betreff\n\nHiermit kündige"))


def test_subject_heading_uses_plain_text_from_inline_markdown() -> None:
    text = (ROOT / "examples" / "de" / "example.letter.md").read_text(encoding="utf-8")

    parsed = parse_text(text.replace("# Kündigung meines Vertrags 12345", "# **Kündigung** von `12345`"))

    assert parsed.metadata.subject == "Kündigung von 12345"


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


def test_unknown_sender_does_not_hide_other_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("dinbrief.config.load_config", lambda: {"defaults": {"closing": "Thanks"}})
    with pytest.raises(LetterParseError) as error:
        parse_text("---\nsender: missing\nlayout: {form: X}\n---\n# Subject\n")
    issues = {(issue.code, issue.field) for issue in error.value.issues}
    assert ("sender-profile-unknown", "sender") in issues
    assert ("field-invalid", "layout.form") in issues
    assert ("field-missing", "recipient") in issues
    assert ("field-missing", "closing") not in issues


def test_malformed_config_has_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("dinbrief.config.load_config", lambda: {"defaults": [42]})
    with pytest.raises(LetterParseError, match="`defaults` must be a TOML table") as error:
        parse_text("---\nformat: dinbrief/v2\n---\n# Subject\n")
    assert error.value.code == "config-error"
