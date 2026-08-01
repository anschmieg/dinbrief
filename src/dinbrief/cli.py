from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from email.message import EmailMessage
from importlib.resources import as_file, files
from pathlib import Path
from typing import Annotated, Any

import frontmatter
import typer
from markdown_it import MarkdownIt
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table
from watchfiles import watch

from .config import load_config
from .diagnostics import Diagnostic, heuristic_diagnostics
from .model import Letter
from .parser import LetterParseError, parse_file, parse_text
from .render import render_pdf, render_preview

app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)
setup_app = typer.Typer(no_args_is_help=True)
app.add_typer(setup_app, name="setup")
console = Console()


def _default_output(path: Path) -> Path:
    source = path.resolve()
    configured_roots = [Path(item).expanduser().resolve() for item in load_config().get("roots", [])]
    for root in configured_roots:
        try:
            relative = source.relative_to(root)
        except ValueError:
            continue
        stem = relative.name.removesuffix(".letter.md") + ".pdf"
        return root / "build" / relative.parent / stem
    return source.with_name(source.name.removesuffix(".letter.md") + ".pdf")


def _show_diagnostic(path: str, diagnostic: Diagnostic) -> None:
    field = f" [{diagnostic.field}]" if diagnostic.field else ""
    console.print(f"{path}:1:1: {diagnostic.severity}: {diagnostic.message}{field} [{diagnostic.code}]")


def _load(path: Path) -> Any:
    try:
        return parse_file(path.resolve())
    except LetterParseError as exc:
        console.print(f"{path}:1:1: error: {exc} [parse]")
        raise typer.Exit(1) from exc


@app.command("check")
def check(path: Annotated[Path, typer.Argument(exists=True, dir_okay=False)]) -> None:
    """Validate a letter and print layout heuristics."""
    letter = _load(path)
    diagnostics = heuristic_diagnostics(letter)
    for diagnostic in diagnostics:
        _show_diagnostic(str(path), diagnostic)
    if not diagnostics:
        console.print(f"OK: {path}")


@app.command("render")
def render(
    path: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    output: Annotated[Path | None, typer.Option("--output", "-o")] = None,
    strict: bool = False,
) -> None:
    """Render a letter to a searchable PDF."""
    letter = _load(path)
    target = (output or _default_output(path)).resolve()
    try:
        diagnostics = render_pdf(letter, target)
    except Exception as exc:
        console.print(f"{path}:1:1: error: PDF compilation failed: {exc} [render]")
        raise typer.Exit(1) from exc
    for diagnostic in diagnostics:
        _show_diagnostic(str(path), diagnostic)
    console.print(str(target))
    if strict and any(item.severity == "warning" for item in diagnostics):
        raise typer.Exit(2)


def _open_file(path: Path) -> None:
    if sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=True)
    elif os.name == "nt":
        os.startfile(path)  # type: ignore[attr-defined]
    else:
        subprocess.run(["xdg-open", str(path)], check=True)


@app.command("open")
def render_and_open(path: Annotated[Path, typer.Argument(exists=True, dir_okay=False)]) -> None:
    """Render and open the PDF in the system viewer."""
    letter = _load(path)
    target = _default_output(path).resolve()
    render_pdf(letter, target)
    console.print(str(target))
    _open_file(target)


@app.command("watch")
def watch_letter(path: Annotated[Path, typer.Argument(exists=True, dir_okay=False)]) -> None:
    """Re-render whenever the source file is saved."""
    path = path.resolve()
    console.print("dinbrief watch ready")
    for _changes in watch(path):
        try:
            letter = parse_file(path)
            target = _default_output(path)
            render_pdf(letter, target)
            console.print(f"rendered {target}")
        except Exception as exc:
            console.print(f"{path}:1:1: error: {exc} [watch]")


@app.command("explain")
def explain(path: Annotated[Path, typer.Argument(exists=True, dir_okay=False)]) -> None:
    """Show effective metadata after defaults and sender profiles are applied."""
    letter = _load(path)
    console.print_json(letter.metadata.model_dump_json(indent=2))


@app.command("email")
def email_export(path: Annotated[Path, typer.Argument(exists=True, dir_okay=False)]) -> None:
    """Create HTML, plain text, PDF, and an EML draft."""
    letter = _load(path)
    target_dir = _default_output(path).parent
    target_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = target_dir / "letter.pdf"
    render_pdf(letter, pdf_path)
    html = MarkdownIt("commonmark").render(letter.body)
    (target_dir / "email.html").write_text(html, encoding="utf-8")
    (target_dir / "email.txt").write_text(letter.body + "\n", encoding="utf-8")
    message = EmailMessage()
    message["Subject"] = letter.metadata.subject
    if letter.metadata.recipient.email:
        message["To"] = letter.metadata.recipient.email
    message.set_content(letter.body)
    message.add_alternative(html, subtype="html")
    message.add_attachment(pdf_path.read_bytes(), maintype="application", subtype="pdf", filename="letter.pdf")
    (target_dir / "email.eml").write_bytes(message.as_bytes())
    console.print(str(target_dir))


def _roots() -> list[Path]:
    return [Path(item).expanduser() for item in load_config().get("roots", [Path.cwd()])]


def _letter_records() -> list[tuple[Path, Any]]:
    records: list[tuple[Path, Any]] = []
    for root in _roots():
        if root.exists():
            for path in root.rglob("*.letter.md"):
                try:
                    records.append((path, parse_file(path)))
                except LetterParseError:
                    continue
    return records


@app.command("list")
def list_letters(tag: str | None = None, language: str | None = None) -> None:
    """List letters in configured roots."""
    table = Table("Date", "Recipient", "Subject", "Tags", "Path")
    for path, letter in _letter_records():
        meta = letter.metadata
        if tag and tag.lower() not in meta.tags:
            continue
        if language and meta.language != language:
            continue
        table.add_row(
            str(meta.date),
            meta.recipient.display_name,
            meta.subject,
            ", ".join(meta.tags),
            str(path),
        )
    console.print(table)


@app.command("search")
def search(query: str) -> None:
    """Search metadata and body text across configured roots."""
    needle = query.casefold()
    for path, letter in _letter_records():
        haystack = " ".join(
            [
                letter.metadata.subject,
                letter.metadata.recipient.display_name,
                *letter.metadata.tags,
                letter.body,
            ]
        ).casefold()
        if needle in haystack:
            console.print(str(path))


@app.command("new")
def new(path: Path = Path("new.letter.md"), language: str = "de-DE") -> None:
    """Create a minimal self-contained letter source."""
    if path.exists():
        raise typer.BadParameter(f"File already exists: {path}")
    sample = _sample(language)
    path.write_text(sample, encoding="utf-8")
    console.print(str(path.resolve()))


def _sample(language: str) -> str:
    salutation = "Sehr geehrte Damen und Herren," if language.startswith("de") else "Dear Sir or Madam,"
    closing = "Mit freundlichen Grüßen" if language.startswith("de") else "Yours faithfully,"
    return f'''---
format: dinbrief/v1
language: {language}
sender:
  name: Your Name
  address:
    street: Your Street 1
    postal_code: "12345"
    city: Your City
    country: DE
recipient:
  name: Recipient Name
  address:
    street: Recipient Street 1
    postal_code: "54321"
    city: Recipient City
    country: DE
date: {time.strftime("%Y-%m-%d")}
subject: Subject
salutation: {salutation}
closing: {closing}
tags: []
---

Write your letter here.
'''


@setup_app.command("vscode")
def setup_vscode(
    folder: Annotated[Path | None, typer.Argument()] = None,
) -> None:
    """Install VS Code tasks for the active *.letter.md file."""
    vscode = (folder or Path.cwd()).resolve() / ".vscode"
    vscode.mkdir(parents=True, exist_ok=True)
    for name in ("tasks.json", "settings.json", "extensions.json"):
        resource = files("dinbrief").joinpath(f"resources/vscode/{name}")
        with as_file(resource) as candidate:
            (vscode / name).write_text(candidate.read_text(encoding="utf-8"), encoding="utf-8")
    console.print(str(vscode))


@app.command("schema")
def schema(output: Path | None = None) -> None:
    """Print or copy the bundled JSON Schema."""
    resource = files("dinbrief").joinpath("resources/schemas/letter.schema.json")
    with as_file(resource) as schema_path:
        data = schema_path.read_text(encoding="utf-8")
    if output:
        output.write_text(data, encoding="utf-8")
        console.print(str(output.resolve()))
    else:
        console.print(data)


@app.command("validate-json")
def validate_json() -> None:
    """Internal stdin JSON validation endpoint for editor integrations."""
    payload: dict[str, Any] = json.load(sys.stdin)
    try:
        post = frontmatter.loads(payload["text"])
        Letter.model_validate(post.metadata)
        parsed = parse_text(payload["text"])
        result = {"diagnostics": [item.__dict__ for item in heuristic_diagnostics(parsed)]}
    except (LetterParseError, ValidationError, KeyError) as exc:
        result = {"diagnostics": [{"severity": "error", "code": "parse", "message": str(exc)}]}
    json.dump(result, sys.stdout)


def _editor_response(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        parsed = parse_text(str(payload["text"]), str(payload.get("uri", "<editor>")))
        diagnostics = heuristic_diagnostics(parsed)
        response: dict[str, Any] = {"id": payload.get("id"), "diagnostics": [item.__dict__ for item in diagnostics]}
        if payload.get("render"):
            from .config import cache_dir

            target = cache_dir() / "preview.pdf"
            preview = cache_dir() / "preview.png"
            diagnostics = render_pdf(parsed, target)
            render_preview(parsed, preview)
            response["diagnostics"] = [item.__dict__ for item in diagnostics]
            response["preview"] = str(preview)
            response["pdf"] = str(target)
        return response
    except Exception as exc:
        return {"id": payload.get("id"), "diagnostics": [{"severity": "error", "code": "parse", "message": str(exc)}]}


@app.command("serve")
def serve(stdio: bool = typer.Option(False, "--stdio")) -> None:
    """Run the newline-delimited JSON editor service."""
    if not stdio:
        raise typer.BadParameter("Only --stdio transport is supported")
    for line in sys.stdin:
        try:
            payload = json.loads(line)
            response = _editor_response(payload)
        except Exception as exc:
            response = {"id": None, "diagnostics": [{"severity": "error", "code": "protocol", "message": str(exc)}]}
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    app()
