from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from dinbrief import cli

runner = CliRunner()


def test_setup_vscode_preserves_unrelated_workspace_configuration(tmp_path: Path) -> None:
    vscode = tmp_path / ".vscode"
    vscode.mkdir()
    (vscode / "tasks.json").write_text(
        json.dumps(
            {
                "version": "2.0.0",
                "tasks": [
                    {"label": "My task", "type": "shell", "command": "echo preserved"},
                    {"label": "DIN-Brief: Prüfen", "command": "obsolete"},
                ],
            }
        ),
        encoding="utf-8",
    )
    (vscode / "settings.json").write_text(
        json.dumps({"editor.wordWrap": "on", "files.associations": {"*.foo": "text"}}),
        encoding="utf-8",
    )
    (vscode / "extensions.json").write_text(
        json.dumps({"recommendations": ["example.existing"]}), encoding="utf-8"
    )

    result = runner.invoke(cli.app, ["setup", "vscode", str(tmp_path)])

    assert result.exit_code == 0, result.output
    tasks = json.loads((vscode / "tasks.json").read_text(encoding="utf-8"))
    assert [task["label"] for task in tasks["tasks"]].count("DIN-Brief: Prüfen") == 1
    assert any(task["label"] == "My task" for task in tasks["tasks"])
    settings = json.loads((vscode / "settings.json").read_text(encoding="utf-8"))
    assert settings["editor.wordWrap"] == "on"
    assert settings["files.associations"] == {"*.letter.md": "markdown", "*.foo": "text"}
    extensions = json.loads((vscode / "extensions.json").read_text(encoding="utf-8"))
    assert extensions["recommendations"] == ["example.existing", "dinbrief.dinbrief-vscode"]


def test_setup_vscode_never_overwrites_invalid_existing_json(tmp_path: Path) -> None:
    vscode = tmp_path / ".vscode"
    vscode.mkdir()
    original = "{ this is JSONC or invalid JSON }\n"
    tasks = vscode / "tasks.json"
    tasks.write_text(original, encoding="utf-8")

    result = runner.invoke(cli.app, ["setup", "vscode", str(tmp_path)])

    assert result.exit_code == 2
    assert "Cannot safely update" in result.output
    assert tasks.read_text(encoding="utf-8") == original


def test_setup_vscode_is_transactional_when_a_later_file_is_invalid(tmp_path: Path) -> None:
    vscode = tmp_path / ".vscode"
    vscode.mkdir()
    tasks = vscode / "tasks.json"
    original = json.dumps({"version": "2.0.0", "tasks": [{"label": "Preserve me"}]})
    tasks.write_text(original, encoding="utf-8")
    (vscode / "settings.json").write_text("invalid", encoding="utf-8")

    result = runner.invoke(cli.app, ["setup", "vscode", str(tmp_path)])

    assert result.exit_code == 2
    assert tasks.read_text(encoding="utf-8") == original
