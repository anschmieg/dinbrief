from pathlib import Path

from dinbrief.parser import parse_file
from dinbrief.render import _date_string, build_typst_source, render_pdf, render_preview

ROOT = Path(__file__).parents[1]


def test_render_pdf(tmp_path: Path) -> None:
    parsed = parse_file(ROOT / "examples" / "en" / "example.letter.md")
    output = tmp_path / "letter.pdf"
    diagnostics = render_pdf(parsed, output)
    assert output.read_bytes().startswith(b"%PDF")
    assert not [item for item in diagnostics if item.severity == "error"]


def test_render_preview(tmp_path: Path) -> None:
    parsed = parse_file(ROOT / "examples" / "en" / "example.letter.md")
    output = tmp_path / "preview.png"
    render_preview(parsed, output)
    assert output.read_bytes().startswith(b"\x89PNG")


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
