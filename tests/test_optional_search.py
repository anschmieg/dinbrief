import subprocess
import sys
from pathlib import Path

from typer.testing import CliRunner

from dinbrief import cli, config

runner = CliRunner()


def test_core_cli_does_not_import_optional_engine() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import dinbrief.cli; "
            "assert 'lancedb' not in sys.modules; assert 'pyarrow' not in sys.modules",
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
