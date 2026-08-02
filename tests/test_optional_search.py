import subprocess
import sys
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from dinbrief import cli, config
from dinbrief.index import SearchFilters
from dinbrief.parser import parse_text

runner = CliRunner()


def test_cli_reports_installed_version() -> None:
    result = runner.invoke(cli.app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout.startswith("dinbrief 0.5.")


def test_new_letter_uses_subject_heading(tmp_path: Path) -> None:
    target = tmp_path / "new.letter.md"

    result = runner.invoke(cli.app, ["new", str(target)])

    assert result.exit_code == 0
    source = target.read_text(encoding="utf-8")
    assert "\n# Betreff\n" in source
    assert parse_text(source).metadata.subject == "Betreff"


def test_core_cli_does_not_import_optional_engine() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import dinbrief.cli; "
            "assert 'lancedb' not in sys.modules; assert 'pyarrow' not in sys.modules; "
            "assert 'watchfiles' not in sys.modules",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_setup_search_requires_installed_extra(tmp_path: Path, monkeypatch: object) -> None:
    monkeypatch.setattr(config, "config_dir", lambda: tmp_path)  # type: ignore[attr-defined]
    monkeypatch.setattr(cli, "search_available", lambda: False)  # type: ignore[attr-defined]

    result = runner.invoke(cli.app, ["setup", "search", "--enable"])

    assert result.exit_code == 2
    assert "dinbrief[search]" in result.stdout
    assert config.search_enabled() is False


def test_setup_search_can_enable_and_disable(tmp_path: Path, monkeypatch: object) -> None:
    monkeypatch.setattr(config, "config_dir", lambda: tmp_path)  # type: ignore[attr-defined]
    monkeypatch.setattr(cli, "search_available", lambda: True)  # type: ignore[attr-defined]

    enabled = runner.invoke(cli.app, ["setup", "search", "--enable"])
    assert enabled.exit_code == 0
    assert config.search_enabled() is True

    disabled = runner.invoke(cli.app, ["setup", "search", "--disable"])
    assert disabled.exit_code == 0
    assert config.search_enabled() is False


def test_search_filter_validation() -> None:
    with pytest.raises(typer.BadParameter, match="date-from"):
        cli._validate_search_filters(
            SearchFilters(date_from="2026-08-02", date_to="2026-08-01")
        )
    with pytest.raises(typer.BadParameter, match="delivery"):
        cli._validate_search_filters(SearchFilters(delivery="carrier-pigeon"))
