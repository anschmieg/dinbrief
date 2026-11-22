from __future__ import annotations

import json
from pathlib import Path

from pytest import MonkeyPatch
from typer.testing import CliRunner

from dinbrief import cli, config
from dinbrief.diagnostics import Diagnostic
from dinbrief.model import ParsedLetter

ROOT = Path(__file__).parents[1]
runner = CliRunner()


def test_validate_json_uses_effective_config_defaults(monkeypatch: object) -> None:
    text = (ROOT / "examples" / "de" / "example.letter.md").read_text(encoding="utf-8")
    sender_start = text.index("sender:\n")
    recipient_start = text.index("recipient:\n")
    text = text[:sender_start] + text[recipient_start:]
    monkeypatch.setattr(  # type: ignore[attr-defined]
        config,
        "load_config",
        lambda: {
            "defaults": {
                "sender": {
                    "name": "Configured Sender",
                    "address": {
                        "street": "Example 1",
                        "postal_code": "12345",
                        "city": "Berlin",
                    },
                }
            }
        },
    )

    result = runner.invoke(cli.app, ["validate-json"], input=json.dumps({"text": text}))

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {"diagnostics": []}


def test_editor_previews_are_isolated_per_document(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    text = (ROOT / "examples" / "de" / "example.letter.md").read_text(encoding="utf-8")
    outputs: list[Path] = []

    def record_pdf(_letter: ParsedLetter, output: Path) -> list[Diagnostic]:
        outputs.append(output)
        return []

    def record_preview(_letter: ParsedLetter, output: Path) -> None:
        outputs.append(output)

    monkeypatch.setattr(config, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(cli, "render_pdf", record_pdf)
    monkeypatch.setattr(cli, "render_preview", record_preview)

    first = cli._editor_response({"id": 1, "uri": "file:///one.letter.md", "text": text, "render": True})
    second = cli._editor_response({"id": 2, "uri": "file:///two.letter.md", "text": text, "render": True})

    assert first["preview"] != second["preview"]
    assert first["pdf"] != second["pdf"]
    assert len(set(outputs)) == 4


def test_editor_returns_all_schema_errors_with_fields() -> None:
    text = (ROOT / "examples" / "de" / "example.letter.md").read_text(encoding="utf-8")
    text = text.replace("date: 2026-08-01\n", "unknown_field: value\n").replace(
        '    postal_code: "54321"\n', ""
    )

    response = cli._editor_response({"id": 3, "uri": "file:///invalid.letter.md", "text": text})

    diagnostics = response["diagnostics"]
    assert {item["field"] for item in diagnostics} >= {
        "unknown_field",
        "date",
        "recipient.address.postal_code",
    }
    assert {item["code"] for item in diagnostics} >= {"field-unknown", "field-missing"}


def test_editor_reports_subject_and_schema_errors_together() -> None:
    text = "---\nformat: dinbrief/v2\nrecipient:\n  organization: Example\n---\nBody without a heading\n"

    response = cli._editor_response({"id": 5, "uri": "file:///invalid.letter.md", "text": text})

    diagnostics = response["diagnostics"]
    assert {item.get("field") for item in diagnostics} >= {
        "subject",
        "recipient.address",
        "date",
        "salutation",
        "closing",
    }


def test_editor_reports_yaml_error_position() -> None:
    text = "---\nformat: [\n---\n# Subject\n"

    response = cli._editor_response({"id": 4, "uri": "file:///invalid.letter.md", "text": text})

    diagnostic = response["diagnostics"][0]
    assert diagnostic["code"] == "yaml-invalid"
    assert diagnostic["line"] >= 1
    assert diagnostic["column"] >= 0
