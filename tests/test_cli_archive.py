from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from dinbrief import cli

ROOT = Path(__file__).parents[1]
runner = CliRunner()


def test_list_is_sorted_and_reports_invalid_letters(
    tmp_path: Path, monkeypatch: object
) -> None:
    older = tmp_path / "older.letter.md"
    newer = tmp_path / "newer.letter.md"
    source = (ROOT / "examples" / "de" / "example.letter.md").read_text(encoding="utf-8")
    older.write_text(source.replace("2026-08-01", "2025-01-01"), encoding="utf-8")
    newer.write_text(source.replace("Kündigung meines", "Neuerer Brief über"), encoding="utf-8")
    invalid = tmp_path / "invalid.letter.md"
    invalid.write_text("invalid", encoding="utf-8")
    monkeypatch.setattr(cli, "load_config", lambda: {"roots": [str(tmp_path)]})  # type: ignore[attr-defined]

    result = runner.invoke(cli.app, ["list", "--sort", "date-desc"])

    assert result.exit_code == 0
    assert result.stdout.index("2026-08-01") < result.stdout.index("2025-01-01")
    assert invalid.name in result.stdout
    assert "warning:" in result.stdout


def test_watch_renders_once_before_waiting(monkeypatch: object, tmp_path: Path) -> None:
    source = tmp_path / "example.letter.md"
    source.write_text("placeholder", encoding="utf-8")
    rendered: list[Path] = []
    monkeypatch.setattr(  # type: ignore[attr-defined]
        cli, "render", lambda path, output, strict: rendered.append(path)
    )
    monkeypatch.setattr("watchfiles.watch", lambda path: iter(()))  # type: ignore[attr-defined]

    cli.watch_letter(source)

    assert rendered == [source]
