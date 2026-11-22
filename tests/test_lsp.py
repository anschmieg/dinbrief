from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest


def test_letter_language_server_over_stdio() -> None:
    pytest.importorskip("pygls")
    path = Path(__file__).parents[1] / "examples" / "en" / "example.letter.md"
    text = path.read_text(encoding="utf-8")
    uri = path.as_uri()
    document = {"uri": uri}
    language_line = next(
        i for i, line in enumerate(text.splitlines()) if line.startswith("language:")
    )
    invalid = text.replace("language:", "langauge:", 1)
    key_range = {
        "start": {"line": language_line, "character": 0},
        "end": {"line": language_line, "character": len("langauge")},
    }
    action_params = {
        "textDocument": document,
        "range": key_range,
        "context": {
            "diagnostics": [
                {
                    "range": key_range,
                    "source": "dinbrief",
                    "code": "field-unknown",
                    "message": "Unknown field `langauge`. Remove it or check its spelling. Did you mean `language`?",
                }
            ]
        },
    }
    requests: list[tuple[str, dict[str, Any], int | None]] = [
        (
            "initialize",
            {
                "processId": None,
                "capabilities": {
                    "workspace": {"workspaceEdit": {"documentChanges": True}},
                },
            },
            1,
        ),
        ("initialized", {}, None),
        (
            "textDocument/didOpen",
            {
                "textDocument": {
                    **document,
                    "languageId": "markdown",
                    "version": 1,
                    "text": invalid,
                }
            },
            None,
        ),
        ("textDocument/codeAction", action_params, 5),
        (
            "textDocument/didChange",
            {
                "textDocument": {**document, "version": 2},
                "contentChanges": [{"text": invalid.replace("langauge:", "'langauge':", 1)}],
            },
            None,
        ),
        ("textDocument/codeAction", action_params, 6),
        (
            "textDocument/didChange",
            {
                "textDocument": {**document, "version": 3},
                "contentChanges": [{"text": text}],
            },
            None,
        ),
        (
            "textDocument/completion",
            {
                "textDocument": document,
                "position": {"line": language_line, "character": 13},
            },
            2,
        ),
        (
            "textDocument/hover",
            {
                "textDocument": document,
                "position": {"line": language_line, "character": 2},
            },
            3,
        ),
        ("textDocument/didClose", {"textDocument": document}, None),
        ("shutdown", {}, 4),
        ("exit", {}, None),
    ]
    wire = bytearray()
    for method, params, request_id in requests:
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method, "params": params}
        if request_id is not None:
            payload["id"] = request_id
        body = json.dumps(payload).encode()
        wire.extend(f"Content-Length: {len(body)}\r\n\r\n".encode() + body)
    process = subprocess.run(
        [sys.executable, "-m", "dinbrief.cli", "lsp"],
        input=wire,
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert process.returncode == 0, process.stderr.decode()

    stream = io.BytesIO(process.stdout)
    messages: list[dict[str, Any]] = []
    while header := stream.readline():
        length = int(header.split(b":", 1)[1])
        while stream.readline().strip():
            pass
        messages.append(json.loads(stream.read(length)))
    responses = {message["id"]: message["result"] for message in messages if "id" in message}
    assert responses[1]["capabilities"]["textDocumentSync"]["change"] == 1
    assert "en-GB" in [item["label"] for item in responses[2]]
    assert "BCP-47" in responses[3]["contents"]["value"]
    action = responses[5][0]
    assert action["title"] == "Rename field to language"
    edit = action["edit"]["documentChanges"][0]
    assert edit["textDocument"] == {"uri": uri, "version": 1}
    assert edit["edits"] == [{"range": key_range, "newText": "language"}]
    assert responses[6] == []
    published = [
        message["params"]
        for message in messages
        if message.get("method") == "textDocument/publishDiagnostics"
    ]
    assert published[0]["version"] == 1
    assert published[0]["diagnostics"][0]["range"]["start"]["line"] == language_line
    assert published[0]["diagnostics"][0]["code"] == "field-unknown"
    assert published[1]["version"] == 2
    assert published[1]["diagnostics"][0]["range"] != key_range
    assert published[2]["version"] == 3
    assert published[2]["diagnostics"] == published[3]["diagnostics"] == []


def test_yaml_diagnostic_ranges_and_subject_fixes() -> None:
    pytest.importorskip("pygls")
    from pygls.workspace import TextDocument

    from dinbrief.lsp import LetterSchema, _diagnostics, _quick_fix
    from dinbrief.lsp_frontmatter import Frontmatter

    root = Path(__file__).parents[1]
    schema = LetterSchema(
        json.loads((root / "schemas/letter.schema.json").read_text(encoding="utf-8"))
    )
    source = (
        "---\r\nformat: dinbrief/v2\r\n"
        'recipient: {name: "😀 Example", "adress": {city: London}}\r\n'
        "format: dinbrief/v2\r\ntags: [ok, 42]\r\n---\r\n\r\n# Subject\r\n\r\n# Extra\r\n"
    )
    document = TextDocument("file:///letter.letter.md", source)
    diagnostics = _diagnostics(document, schema)
    typo = next(item for item in diagnostics if item.code == "field-unknown")
    assert "Did you mean `address`?" in typo.message
    assert (typo.range.start.line, typo.range.start.character) == (2, 32)
    bad_tag = next(
        item
        for item in diagnostics
        if item.code == "field-invalid" and item.data and item.data["field"] == "tags.1"
    )
    assert document.text_in_client_range(bad_tag.range) == "42"
    assert (
        next(item for item in diagnostics if item.code == "yaml-duplicate-key").range.start.line
        == 3
    )
    extra = next(item for item in diagnostics if item.code == "subject-multiple")
    assert extra.range.start.line == 9
    fix = _quick_fix(Frontmatter(source), schema, "subject-multiple", ("subject",), 9)
    assert fix is not None
    assert (fix[1].line, fix[1].column, fix[2]) == (9, 1, "#")


def test_completion_respects_yaml_context_and_configured_senders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("pygls")
    from pygls.workspace import ServerTextPosition, TextDocument

    from dinbrief import lsp
    from dinbrief.lsp_frontmatter import Frontmatter

    root = Path(__file__).parents[1]
    schema = lsp.LetterSchema(
        json.loads((root / "schemas/letter.schema.json").read_text(encoding="utf-8"))
    )
    monkeypatch.setattr(lsp, "load_config", lambda: {"senders": {"123": {}}})
    source = (
        '---\nsender:  # profile\nlayout: {form: "B", fold_marks: true}\nclosing: |\n  prose\n---\n'
    )
    document = TextDocument("file:///letter.letter.md", source)
    frontmatter = Frontmatter(source)

    sender = lsp._completion(document, frontmatter, schema, ServerTextPosition(1, 9))
    assert [(item.label, item.text_edit.new_text) for item in sender if item.text_edit] == [
        ("123", '"123" ')
    ]
    layout = lsp._completion(document, frontmatter, schema, ServerTextPosition(2, 16))
    assert {item.label for item in layout} == {"A", "B"}
    assert lsp._completion(document, frontmatter, schema, ServerTextPosition(4, 4)) == []
    assert lsp._completion(document, frontmatter, schema, ServerTextPosition(1, 12)) == []


@pytest.mark.parametrize(
    ("recipient", "expected"),
    [
        (
            '"recipient": # keep this comment\r\n    name: Example',
            '"recipient": # keep this comment\r\n    address: {}\r\n    name: Example',
        ),
        (
            "recipient: {name: Example} # keep this comment",
            "recipient: {address: {}, name: Example} # keep this comment",
        ),
    ],
)
def test_missing_field_fix_preserves_frontmatter(recipient: str, expected: str) -> None:
    pytest.importorskip("pygls")
    from pygls.workspace import TextDocument

    from dinbrief.lsp import LetterSchema, _quick_fix, _range
    from dinbrief.lsp_frontmatter import Frontmatter

    root = Path(__file__).parents[1]
    schema = LetterSchema(
        json.loads((root / "schemas/letter.schema.json").read_text(encoding="utf-8"))
    )
    source = f"---\r\nformat: dinbrief/v2\r\n{recipient}\r\n---\r\n# Subject\r\n"
    document = TextDocument("file:///letter.letter.md", source)
    fix = _quick_fix(Frontmatter(source), schema, "field-missing", ("recipient", "address"), 2)
    assert fix is not None
    _, span, insertion = fix
    offset = document.offset_at_position(_range(document, Frontmatter(source), span).start)
    assert source[:offset] + insertion + source[offset:] == source.replace(recipient, expected)


@pytest.mark.parametrize(
    ("header", "replacement"),
    [
        ("format: # keep", "format: dinbrief/v2 # keep"),
        ("format: invalid", "format: dinbrief/v2"),
        ("format: &fmt invalid\nlocation: *fmt", None),
        ("location: &fmt invalid\nformat: *fmt", None),
        ("format: !!str invalid", None),
    ],
)
def test_format_fix_preserves_yaml_syntax_and_indirection(
    header: str, replacement: str | None
) -> None:
    pytest.importorskip("pygls")
    from pygls.workspace import TextDocument

    from dinbrief.lsp import LetterSchema, _quick_fix, _range
    from dinbrief.lsp_frontmatter import Frontmatter

    root = Path(__file__).parents[1]
    schema = LetterSchema(
        json.loads((root / "schemas/letter.schema.json").read_text(encoding="utf-8"))
    )
    text = f"---\n{header}\n---\n# Subject\n"
    source = Frontmatter(text)
    document = TextDocument("file:///letter.letter.md", text)
    fix = _quick_fix(source, schema, "field-invalid", ("format",), 1)
    if replacement is None:
        assert fix is None
    else:
        assert fix is not None
        _, span, new_text = fix
        edit_range = _range(document, source, span)
        start = document.offset_at_position(edit_range.start)
        end = document.offset_at_position(edit_range.end)
        assert text[:start] + new_text + text[end:] == text.replace(header, replacement)


def test_yaml_positions_follow_lsp_lines_after_unicode_separator() -> None:
    pytest.importorskip("pygls")
    from lsprotocol.types import TextEdit
    from pygls.workspace import ServerTextPosition, TextDocument

    from dinbrief.lsp import LetterSchema, _completion, _diagnostics
    from dinbrief.lsp_frontmatter import Frontmatter

    root = Path(__file__).parents[1]
    schema = LetterSchema(
        json.loads((root / "schemas/letter.schema.json").read_text(encoding="utf-8"))
    )
    text = '---\nclosing: "a\u2028b"\nlayout: {form: C}\n---\n# Subject\n'
    document = TextDocument("file:///letter.letter.md", text)
    error = next(
        item
        for item in _diagnostics(document, schema)
        if item.data and item.data["field"] == "layout.form"
    )
    assert (error.range.start.line, error.range.start.character, error.range.end.character) == (
        2,
        15,
        16,
    )
    completion = _completion(document, Frontmatter(text), schema, ServerTextPosition(2, 15))
    assert len(completion) == 2
    assert all(
        isinstance(item.text_edit, TextEdit) and item.text_edit.range == error.range
        for item in completion
    )


def test_subject_fix_preserves_markdown_reference_definitions() -> None:
    pytest.importorskip("pygls")
    from dinbrief.lsp import LetterSchema, _quick_fix
    from dinbrief.lsp_frontmatter import Frontmatter

    schema = LetterSchema({})
    header = "---\nformat: dinbrief/v2\n---\n"
    source = Frontmatter(header + "[reference]: https://example.com\n\nUse [reference].\n")
    fix = _quick_fix(source, schema, "subject-missing", ("subject",), 3)
    assert fix is not None
    assert (fix[1].line, fix[1].column, fix[2]) == (3, 0, "# Subject\n\n")
    setext = _quick_fix(
        Frontmatter(header + "A title\n=======\n\nBody\n"),
        schema,
        "subject-missing",
        ("subject",),
        3,
    )
    assert setext is not None
    assert (setext[1].line, setext[1].end_line, setext[2]) == (3, 4, "# A title")
