from pathlib import Path

import pytest

from dinbrief import cli


def test_output_is_sibling_without_configured_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(cli, "load_config", lambda: {})
    source = tmp_path / "folder" / "example.letter.md"
    assert cli._default_output(source) == source.with_name("example.pdf")


def test_output_uses_root_build_and_preserves_folders(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "letters"
    source = root / "tax" / "2026" / "example.letter.md"
    monkeypatch.setattr(cli, "load_config", lambda: {"roots": [str(root)]})
    assert cli._default_output(source) == root / "build" / "tax" / "2026" / "example.pdf"
