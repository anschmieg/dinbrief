from pathlib import Path

from dinbrief.diagnostics import heuristic_diagnostics
from dinbrief.parser import parse_file, parse_text

ROOT = Path(__file__).parents[1]


def test_normal_example_has_no_heuristic_warnings() -> None:
    parsed = parse_file(ROOT / "examples" / "de" / "example.letter.md")
    assert heuristic_diagnostics(parsed) == []


def test_long_subject_warns() -> None:
    source = (ROOT / "examples" / "de" / "example.letter.md").read_text(encoding="utf-8")
    parsed = parse_text(source.replace("Kündigung meines Vertrags 12345", "X" * 100))
    assert {item.code for item in heuristic_diagnostics(parsed)} == {"subject-length"}

