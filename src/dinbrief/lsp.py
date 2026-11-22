"""Language Server Protocol support for Markdown letters."""

from __future__ import annotations

import json
import re
from difflib import get_close_matches
from typing import Any, cast
from urllib.parse import unquote, urlsplit

from lsprotocol import types
from markdown_it import MarkdownIt
from pygls.lsp.server import LanguageServer
from pygls.workspace import ServerTextPosition, TextDocument

from . import __version__
from .config import load_config
from .diagnostics import heuristic_diagnostics
from .lsp_frontmatter import KEY, Field, FieldPath, Frontmatter, Span
from .parser import LetterParseError, parse_text

_SEVERITIES = {
    "error": types.DiagnosticSeverity.Error,
    "warning": types.DiagnosticSeverity.Warning,
    "information": types.DiagnosticSeverity.Information,
}


def _range(document: TextDocument, source: Frontmatter, span: Span) -> types.Range:
    convert = document.position_codec.position_to_client_units
    return types.Range(
        convert(source.lines, ServerTextPosition(span.line, span.column)),
        convert(source.lines, ServerTextPosition(span.end_line, span.end_column)),
    )


def _point(line: int, column: int = 0) -> Span:
    return Span(line, column, line, column)


def _later_headings(source: Frontmatter) -> list[tuple[int, int]]:
    start = source.body_start
    body = "\n".join(source.lines[start:])
    return [
        (start + token.map[0], start + token.map[1])
        for token in MarkdownIt().parse(body)
        if token.type == "heading_open" and token.tag == "h1" and token.map and token.map[0] > 0
    ]


class LetterSchema:
    def __init__(self, schema: dict[str, Any]) -> None:
        self.schema = schema

    def resolve(self, node: dict[str, Any]) -> dict[str, Any]:
        if "oneOf" in node:
            branch = next((item for item in node["oneOf"] if "$ref" in item), node["oneOf"][0])
            return {**self.resolve(branch), **node}
        if "$ref" in node:
            return {**self.schema["$defs"][node["$ref"].rsplit("/", 1)[-1]], **node}
        return node

    def at(self, path: FieldPath) -> dict[str, Any]:
        node = self.schema
        for key in path:
            if node.get("type") == "array" and key.isdecimal():
                node = self.resolve(node.get("items", {}))
            else:
                fallback = node.get("additionalProperties")
                node = self.resolve(
                    node.get("properties", {}).get(
                        key, fallback if isinstance(fallback, dict) else {}
                    )
                )
        return node

    def values(self, path: FieldPath) -> dict[str, str]:
        node = self.at(path)
        if path == ("sender",):
            try:
                profiles = load_config().get("senders", {})
            except (OSError, ValueError):
                return {}
            if isinstance(profiles, dict):
                # Quote profile IDs so YAML treats even IDs like 'yes' and '123' as strings.
                return {name: json.dumps(name, ensure_ascii=False) for name in sorted(profiles)}
        if "const" in node:
            return {str(node["const"]): str(node["const"])}
        if node.get("type") == "boolean":
            return {"true": "true", "false": "false"}
        values = node.get("enum", node.get("examples", []))
        if "default" in node:
            values = [node["default"], *values]
        return {str(value): str(value) for value in values}

    def replacement_key(self, source: Frontmatter, path: FieldPath) -> str | None:
        names = self.at(path[:-1]).get("properties", {})
        available = [key for key in names if (*path[:-1], key) not in source.fields]
        matches = get_close_matches(path[-1], available, n=2, cutoff=0.75)
        return matches[0] if len(matches) == 1 else None

    def starter(self, path: FieldPath) -> str:
        node = self.at(path)
        if "const" in node:
            return f" {node['const']}"
        if node.get("type") == "object":
            return " {}"
        if node.get("type") == "array":
            return " []"
        if node.get("format") == "date":
            return " YYYY-MM-DD"
        return ' ""'


def _diagnostics(document: TextDocument, schema: LetterSchema) -> list[types.Diagnostic]:
    source = Frontmatter(document.source)
    try:
        letter = parse_text(document.source, document.uri)
        issues = [vars(issue) for issue in heuristic_diagnostics(letter)]
    except LetterParseError as exc:
        issues = [{**vars(issue), "severity": "error"} for issue in exc.issues]

    diagnostics = []
    for issue in issues:
        field = issue.get("field")
        path = issue.get("path") or (tuple(field.split(".")) if field else ())
        code = issue["code"]
        message = issue["message"]
        span = source.line_span(0)
        field_entry = source.fields.get(path)
        suggestion = None
        if code == "frontmatter-missing" and source.present:
            span = source.line_span(source.opening)
            if source.closed:
                message = "Add YAML key–value pairs between the frontmatter delimiters."
            else:
                message = "Close the YAML frontmatter with a line containing `---`."
                code = "frontmatter-unclosed"
        elif code == "yaml-invalid" and source.yaml_error is not None:
            span = source.yaml_error
        elif code == "field-unknown" and field_entry and field_entry.key:
            span = field_entry.key
            suggestion = schema.replacement_key(source, path)
            if suggestion:
                message += f" Did you mean `{suggestion}`?"
        elif field == "subject" and len(path) == 1:
            span = source.line_span(source.body_start)
        elif field_entry:
            span = (
                field_entry.value
                if field_entry.scalar and code in {"field-invalid", "sender-profile-unknown"}
                else field_entry.key or field_entry.value
            )
        elif path:
            parent = next(
                (
                    source.fields[path[:length]]
                    for length in range(len(path) - 1, 0, -1)
                    if path[:length] in source.fields
                ),
                None,
            )
            span = (parent.key or parent.value) if parent else source.line_span(source.end)
        spans = (
            [source.line_span(start) for start, _ in _later_headings(source)]
            if code == "subject-multiple"
            else [span]
        )
        for position in spans:
            diagnostics.append(
                types.Diagnostic(
                    range=_range(document, source, position),
                    message=message,
                    severity=_SEVERITIES[issue["severity"]],
                    code=code,
                    source="dinbrief",
                    data={"field": field, "path": list(path)},
                )
            )
    for path, span in source.duplicates:
        diagnostics.append(
            types.Diagnostic(
                range=_range(document, source, span),
                message=f"`{'.'.join(path)}` is defined more than once. YAML uses the last value.",
                severity=types.DiagnosticSeverity.Warning,
                code="yaml-duplicate-key",
                source="dinbrief",
            )
        )
    return diagnostics


def _scalar_spacing(source: Frontmatter, span: Span, value: str) -> str:
    line = source.lines[span.line]
    prefix = " " if span.column and line[span.column - 1] == ":" else ""
    suffix = " " if line[span.end_column :].startswith("#") else ""
    return prefix + value + suffix


def _scalar_edit(source: Frontmatter, field: Field, value: str) -> str | None:
    span = field.value
    if not field.scalar or field.alias or span.line != span.end_line:
        return None
    original = source.lines[span.line][span.column : span.end_column]
    if original.startswith(("&", "*", "!")):
        return None  # Preserve anchors, aliases, and explicit YAML type tags.
    return _scalar_spacing(source, span, value)


def _completion(
    document: TextDocument, source: Frontmatter, schema: LetterSchema, position: ServerTextPosition
) -> list[types.CompletionItem]:
    line, column = position.line, position.character
    if line not in source.parents:
        return []
    text = source.lines[line]
    parent = source.parents[line]
    for path, field in source.fields.items():
        span = field.value
        if field.alias or not field.scalar or not span.contains(line, column):
            continue
        if span.end_line != span.line:
            if (line, column) < (span.end_line, span.end_column):
                return []
            continue
        # The indentation of a mapping is not a value completion site.
        if field.key is not None and span.line != field.key.line:
            continue
        if source.yaml_error and not re.fullmatch(r"[\w-]*", text[span.column : span.end_column]):
            continue
        values = schema.values(path)
        if values and _scalar_edit(source, field, "") is not None:
            return [
                types.CompletionItem(
                    label,
                    kind=types.CompletionItemKind.Value,
                    text_edit=types.TextEdit(
                        _range(document, source, span), _scalar_spacing(source, span, value)
                    ),
                )
                for label, value in values.items()
            ]

    match = KEY.match(text)
    if match and column >= match.end():
        # An empty YAML value can be indexed at the colon even if the cursor is after a space.
        value = text[match.end() :].lstrip()
        start = len(text) - len(value)
        if (not value or value.startswith("#")) and column <= start:
            space = " " if column == match.end() else ""
            suffix = " " if value else ""
            return [
                types.CompletionItem(
                    label,
                    kind=types.CompletionItemKind.Value,
                    text_edit=types.TextEdit(
                        _range(document, source, Span(line, column, line, start)),
                        space + rendered + suffix,
                    ),
                )
                for label, rendered in schema.values((*parent, match["name"])).items()
            ]
    key = re.fullmatch(r"( *)([\w-]*)[ \t]*", text)
    if not key or column < len(key[1]) or text.lstrip().startswith("#"):
        return []
    node = schema.at(parent)
    edit_range = _range(document, source, Span(line, len(key[1]), line, len(text)))
    required = node.get("required", [])
    return [
        types.CompletionItem(
            name,
            kind=types.CompletionItemKind.Property,
            detail=schema.resolve(property_schema).get("description"),
            sort_text=f"{int(name not in required)}-{name}",
            text_edit=types.TextEdit(
                edit_range,
                name + ":" + schema.starter((*parent, name))
                if "const" in property_schema
                else name + ": ",
            ),
        )
        for name, property_schema in node.get("properties", {}).items()
        if (*parent, name) not in source.fields
    ]


def _hover(
    document: TextDocument, source: Frontmatter, schema: LetterSchema, position: ServerTextPosition
) -> types.Hover | None:
    for path, field in source.fields.items():
        if field.key is None or not field.key.contains(position.line, position.character):
            continue
        node = schema.at(path)
        if not node:
            return None
        details = [f"`{'.'.join(path)}`"]
        if description := node.get("description"):
            details.append(description)
        if path[-1] in schema.at(path[:-1]).get("required", ()):
            details.append("Required field.")
        elif path == ("sender",):
            details.append(
                "Use a configured profile ID or provide an inline sender. You can omit this field when a default sender is configured."
            )
        if "const" in node:
            details.append(f"Required value is `{node['const']}`.")
        elif choices := node.get("enum"):
            details.append(
                "Allowed values are " + ", ".join(f"`{choice}`" for choice in choices) + "."
            )
        elif kind := node.get("type"):
            details.append(f"Type is `{kind}`.")
        if "format" in node:
            details.append(f"Format is `{node['format']}`.")
        if "default" in node:
            details.append(f"Default is `{node['default']}`.")
        return types.Hover(
            types.MarkupContent(types.MarkupKind.Markdown, "\n\n".join(details)),
            _range(document, source, field.key),
        )
    return None


def _quick_fix(
    source: Frontmatter, schema: LetterSchema, code: str, path: FieldPath, line: int
) -> tuple[str, Span, str] | None:
    newline = source.newline
    if code == "subject-missing" and source.closed:
        body_line = source.body_start
        text = source.lines[body_line]
        if re.fullmatch(r" {0,3}#(?:[ \t]+#*)?[ \t]*", text):
            return "Replace the empty subject heading", source.line_span(body_line), "# Subject"
        body = "\n".join(source.lines[body_line:])
        tokens = MarkdownIt().parse(body)
        headings = [token for token in tokens if token.type == "heading_open" and token.tag == "h1"]
        if headings:
            if len(headings) == 1 and headings[0].map == [0, 2]:
                underline = source.lines[body_line + 1]
                if re.fullmatch(r" {0,3}=+\s*", underline):
                    span = Span(body_line, 0, body_line + 1, len(underline))
                    return "Convert the subject to a # heading", span, "# " + text.strip()
            return None
        if tokens and tokens[0].type == "paragraph_open" and tokens[0].map == [0, 1]:
            return "Use the first line as the letter subject", _point(body_line), "# "
        needs_newline = body_line == source.end
        return (
            "Insert a letter subject heading",
            _point(body_line, len(text) if needs_newline else 0),
            (newline if needs_newline else "") + "# Subject" + newline * 2,
        )
    if code == "subject-empty" and source.closed:
        return "Replace the empty subject heading", source.line_span(source.body_start), "# Subject"
    if code == "subject-multiple":
        for start, end in _later_headings(source):
            if start != line:
                continue
            text = source.lines[start]
            if match := re.match(r" {0,3}#(?=\s|$)", text):
                return "Demote this heading to level two", _point(start, match.end()), "#"
            underline = source.lines[end - 1]
            if re.fullmatch(r" {0,3}=+\s*", underline):
                return (
                    "Demote this heading to level two",
                    source.line_span(end - 1),
                    "-" * len(underline.strip()),
                )
    if not path:
        return None
    field = source.fields.get(path)
    if (
        code == "field-unknown"
        and field
        and field.key
        and (replacement := schema.replacement_key(source, path))
    ):
        return f"Rename field to {replacement}", field.key, replacement
    if code == "field-invalid" and field and "const" in (node := schema.at(path)):
        value = str(node["const"])
        if (edit := _scalar_edit(source, field, value)) is not None:
            return f"Set {'.'.join(path)} to {value}", field.value, edit
    if code != "field-missing" or field or not source.closed or not schema.at(path):
        return None
    if len(path) == 1:
        insert = _point(source.end)
        indent = ""
    else:
        parent = source.fields.get(path[:-1])
        if not parent or not parent.key:
            return None
        parent_line = parent.key.line
        value_line = source.lines[parent.value.line]
        if not parent.scalar and value_line[parent.value.column :].startswith("{"):
            title = f"Add required field {'.'.join(path)}"
            child_present = any(key[:-1] == path[:-1] for key in source.fields)
            suffix = ", " if child_present else ""
            return (
                title,
                _point(parent.value.line, parent.value.column + 1),
                path[-1] + ":" + schema.starter(path) + suffix,
            )
        parent_text = source.lines[parent_line]
        tail = parent_text[parent.key.end_column :].lstrip()
        if not tail.startswith(":"):
            return None
        inline_value = tail[1:].strip()
        if inline_value and not inline_value.startswith("#"):
            return None
        child_columns = [
            entry.key.column
            for key, entry in source.fields.items()
            if key[:-1] == path[:-1] and entry.key is not None
        ]
        indent = " " * min(child_columns, default=parent.key.column + 2)
        insert = _point(parent_line + 1)
    return (
        f"Add required field {'.'.join(path)}",
        insert,
        indent + path[-1] + ":" + schema.starter(path) + newline,
    )


def create_server(schema_data: dict[str, Any]) -> LanguageServer:
    schema = LetterSchema(schema_data)
    # Full snapshots keep editor offsets independent of pygls's splitlines-based
    # incremental edits, which treat Unicode separators inside a line as editor newlines.
    server = LanguageServer(
        "dinbrief", __version__, text_document_sync_kind=types.TextDocumentSyncKind.Full
    )

    def is_letter(uri: str) -> bool:
        return unquote(urlsplit(uri).path).endswith(".letter.md")

    def document_for(uri: str) -> TextDocument | None:
        if is_letter(uri):
            return cast(TextDocument | None, server.workspace.text_documents.get(unquote(uri)))
        return None

    def publish(uri: str) -> None:
        if document := document_for(uri):
            server.text_document_publish_diagnostics(
                types.PublishDiagnosticsParams(
                    uri=uri,
                    version=document.version,
                    diagnostics=_diagnostics(document, schema),
                )
            )

    @server.feature(types.TEXT_DOCUMENT_DID_OPEN)
    def did_open(params: types.DidOpenTextDocumentParams) -> None:
        publish(params.text_document.uri)

    @server.feature(types.TEXT_DOCUMENT_DID_CHANGE)
    def did_change(params: types.DidChangeTextDocumentParams) -> None:
        publish(params.text_document.uri)

    @server.feature(types.TEXT_DOCUMENT_DID_CLOSE)
    def did_close(params: types.DidCloseTextDocumentParams) -> None:
        uri = params.text_document.uri
        if is_letter(uri):
            server.text_document_publish_diagnostics(types.PublishDiagnosticsParams(uri, []))

    @server.feature(
        types.TEXT_DOCUMENT_COMPLETION, types.CompletionOptions(trigger_characters=[":"])
    )
    def completion(params: types.CompletionParams) -> list[types.CompletionItem]:
        if document := document_for(params.text_document.uri):
            source = Frontmatter(document.source)
            if params.position.line in source.parents:
                position = document.position_codec.position_from_client_units(
                    source.lines, params.position
                )
                return _completion(document, source, schema, position)
        return []

    @server.feature(types.TEXT_DOCUMENT_HOVER)
    def hover(params: types.HoverParams) -> types.Hover | None:
        if document := document_for(params.text_document.uri):
            source = Frontmatter(document.source)
            if params.position.line in source.parents:
                position = document.position_codec.position_from_client_units(
                    source.lines, params.position
                )
                return _hover(document, source, schema, position)
        return None

    @server.feature(
        types.TEXT_DOCUMENT_CODE_ACTION,
        types.CodeActionOptions(code_action_kinds=[types.CodeActionKind.QuickFix]),
    )
    def code_actions(params: types.CodeActionParams) -> list[types.CodeAction]:
        document = document_for(params.text_document.uri)
        if document is None or (
            params.context.only and types.CodeActionKind.QuickFix not in params.context.only
        ):
            return []
        source = Frontmatter(document.source)
        requested = [item for item in params.context.diagnostics if item.source == "dinbrief"]
        actions = []
        for diagnostic in _diagnostics(document, schema):
            line = diagnostic.range.start.line
            if requested:
                if not any(
                    item.code == diagnostic.code
                    and item.range == diagnostic.range
                    and item.message == diagnostic.message
                    for item in requested
                ):
                    continue
            elif not params.range.start.line <= line <= params.range.end.line:
                continue
            path = tuple((diagnostic.data or {}).get("path", ()))
            fix = _quick_fix(source, schema, str(diagnostic.code), path, line)
            if fix is None:
                continue
            title, span, text = fix
            edit = types.TextEdit(_range(document, source, span), text)
            capabilities = server.client_capabilities.workspace
            if (
                capabilities
                and capabilities.workspace_edit
                and capabilities.workspace_edit.document_changes
            ):
                edit_document = types.OptionalVersionedTextDocumentIdentifier(
                    document.uri, document.version
                )
                workspace_edit = types.WorkspaceEdit(
                    document_changes=[types.TextDocumentEdit(edit_document, [edit])]
                )
            else:
                workspace_edit = types.WorkspaceEdit(changes={document.uri: [edit]})
            actions.append(
                types.CodeAction(
                    title,
                    kind=types.CodeActionKind.QuickFix,
                    diagnostics=[diagnostic],
                    edit=workspace_edit,
                )
            )
        return actions

    return server
