from pathlib import Path

from dinbrief.model import Party
from dinbrief.parser import parse_file
from dinbrief.render import (
    _date_string,
    _party_lines,
    _phone_uri,
    build_typst_source,
    render_pdf,
    render_preview,
)

ROOT = Path(__file__).parents[1]


def test_render_pdf(tmp_path: Path) -> None:
    parsed = parse_file(ROOT / "examples" / "en" / "example.letter.md")
    output = tmp_path / "letter.pdf"
    diagnostics = render_pdf(parsed, output)
    assert output.read_bytes().startswith(b"%PDF")
    assert not [item for item in diagnostics if item.severity == "error"]


def test_sender_contacts_render_as_clickable_mailto_and_tel_links(tmp_path: Path) -> None:
    parsed = parse_file(ROOT / "examples" / "de" / "example.letter.md")
    sender = parsed.metadata.sender
    assert isinstance(sender, Party)
    updated_sender = sender.model_copy(
        update={"email": "julia.mueller+brief@example.de", "phone": "+49 (0) 30 / 123-45 67 ext. 89"}
    )
    parsed = parsed.model_copy(update={"metadata": parsed.metadata.model_copy(update={"sender": updated_sender})})
    source = build_typst_source(parsed)
    assert '#link("mailto:julia.mueller+brief@example.de")' in source
    assert '#link("tel:+49301234567;ext=89")' in source
    assert "+49 (0) 30 / 123-45 67 ext. 89" in source

    output = tmp_path / "letter-with-contacts.pdf"
    render_pdf(parsed, output)
    assert output.read_bytes().startswith(b"%PDF")


def test_phone_uri_normalizes_common_international_prefixes_and_extensions() -> None:
    assert _phone_uri("0049 (0)30 123-45 67") == "tel:+49301234567"
    assert _phone_uri("+1 (212) 555 0100 x42") == "tel:+12125550100;ext=42"
    assert _phone_uri("(030) 123 45 67") == "tel:0301234567"
    assert _phone_uri("---") is None


def test_render_preview(tmp_path: Path) -> None:
    parsed = parse_file(ROOT / "examples" / "en" / "example.letter.md")
    output = tmp_path / "preview.png"
    render_preview(parsed, output)
    assert output.read_bytes().startswith(b"\x89PNG")


def test_render_pdf_with_supported_commonmark_blocks(tmp_path: Path) -> None:
    parsed = parse_file(ROOT / "examples" / "en" / "example.letter.md")
    parsed = parsed.model_copy(
        update={
            "body": (
                "## Details\n\n3. Third\n4. Fourth\n\n> Quoted text\n\n"
                '```text\nvalue = "quoted"\n```\n\n[Link](https://example.com)'
            )
        }
    )
    output = tmp_path / "commonmark.pdf"

    render_pdf(parsed, output)

    assert output.read_bytes().startswith(b"%PDF")


def test_german_date_uses_sender_city_and_localized_month() -> None:
    parsed = parse_file(ROOT / "examples" / "de" / "example.letter.md")
    assert _date_string(parsed) == "Musterstadt, den 1. August 2026"


def test_british_date_is_localized() -> None:
    parsed = parse_file(ROOT / "examples" / "en" / "example.letter.md")
    assert _date_string(parsed) == "London, 1 August 2026"


def test_form_b_offsets_compensate_for_twenty_mm_page_margin() -> None:
    parsed = parse_file(ROOT / "examples" / "de" / "example.letter.md")
    source = build_typst_source(parsed)
    # Typst adds the 20 mm page margin to these placement offsets.
    assert "dy: 85mm" in source  # 105 mm from the physical sheet edge
    assert "dy: 190mm" in source  # 210 mm from the physical sheet edge
    assert "length: 3mm, stroke: 0.4pt" in source
    assert "dy: 128.5mm" in source  # 148.5 mm from the physical sheet edge
    assert "length: 5mm, stroke: 0.6pt" in source
    assert "dy: 25mm" in source  # Address field starts at physical 45 mm
    assert "dy: 30mm" in source  # Information block starts at physical 50 mm
    assert "block(width: 65mm)" in source  # x=125 mm through x=190 mm
    assert "#block(breakable: false)" in source  # Closing and signature stay together.


def test_foreign_country_is_based_on_sender_country_not_letter_language() -> None:
    recipient = Party.model_validate(
        {
            "organization": "Example Ltd",
            "address": {
                "street": "12 Example Street",
                "postal_code": "SW1A 1AA",
                "city": "London",
                "country": "GB",
            },
        }
    )

    assert _party_lines(recipient, "DE")[-1] == "United Kingdom"
    assert _party_lines(recipient, "GB")[-1] == "SW1A 1AA London"


def test_us_address_includes_region_when_provided() -> None:
    recipient = Party.model_validate(
        {
            "name": "Jane Example",
            "address": {
                "street": "1 Main Street",
                "postal_code": "10001",
                "city": "New York",
                "region": "NY",
                "country": "US",
            },
        }
    )

    assert "New York, NY 10001" in _party_lines(recipient, "DE")
