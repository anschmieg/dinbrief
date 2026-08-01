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

from .config import load_config, search_enabled, set_search_enabled
from .diagnostics import Diagnostic, heuristic_diagnostics
from .index import (
    IndexedLetter,
    SearchFilters,
    SearchSort,
    SearchUnavailableError,
    database_path,
    index_facets,
    query_index,
    rebuild_index,
    search_available,
)
from .model import Letter, Party
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


def _sender_name(sender: str | Party) -> str:
    return sender.display_name if isinstance(sender, Party) else sender


@app.command("list")
def list_letters(
    tag: str | None = None,
    language: str | None = None,
    sender: str | None = None,
    recipient: str | None = None,
    delivery: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    folder: str | None = None,
) -> None:
    """List letters in configured roots."""
    table = Table("Date", "Recipient", "Subject", "Tags", "Path")
    for path, letter in _letter_records():
        meta = letter.metadata
        if tag and tag.lower() not in meta.tags:
            continue
        if language and meta.language != language:
            continue
        if sender and sender.casefold() not in _sender_name(meta.sender).casefold():
            continue
        if recipient and recipient.casefold() not in meta.recipient.display_name.casefold():
            continue
        if delivery and meta.delivery.method != delivery:
            continue
        if date_from and str(meta.date) < date_from:
            continue
        if date_to and str(meta.date) > date_to:
            continue
        if folder and folder.casefold() not in str(path.parent).casefold():
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
def search(
    query: Annotated[str | None, typer.Argument()] = None,
    refresh: bool = False,
    fuzziness: Annotated[int, typer.Option(min=0, max=2)] = 1,
    tag: str | None = None,
    language: str | None = None,
    sender: str | None = None,
    recipient: str | None = None,
    delivery: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    folder: str | None = None,
    sort: SearchSort = SearchSort.RELEVANCE,
    limit: Annotated[int, typer.Option(min=1, max=500)] = 50,
    interactive: Annotated[bool, typer.Option("--interactive", "-i")] = False,
) -> None:
    """Search letters with typo tolerance, filters, and sorting."""
    _ensure_search_ready()
    try:
        if refresh or not database_path().exists():
            rebuild_index(_roots())
        filters = SearchFilters(
            tag=tag,
            language=language,
            sender=sender,
            recipient=recipient,
            delivery=delivery,
            date_from=date_from,
            date_to=date_to,
            folder=folder,
        )
        if interactive or query is None:
            if not sys.stdin.isatty():
                raise typer.BadParameter("QUERY is required outside an interactive terminal")
            from .interactive import ask_search

            request = ask_search(index_facets())
            if request is None:
                raise typer.Exit()
            query = request.query
            filters = request.filters
            sort = request.sort
            fuzziness = request.fuzziness
            limit = request.limit
        filters = _validate_search_filters(filters)
        results = query_index(
            query,
            filters=filters,
            sort=sort,
            fuzziness=fuzziness,
            limit=limit,
        )
        _print_search_results(results)
    except SearchUnavailableError as exc:
        console.print(f"error: {exc}", markup=False)
        raise typer.Exit(2) from exc


def _print_search_results(results: list[IndexedLetter]) -> None:
    if not results:
        console.print("No matching letters.", style="yellow")
        return
    table = Table("Score", "Date", "Recipient", "Subject", "Tags", "Path")
    for item in results:
        score = f"{item.score:.2f}" if item.score is not None else ""
        table.add_row(
            score,
            item.date,
            item.recipient,
            item.subject,
            ", ".join(item.tags),
            str(item.path),
        )
    console.print(table)


def _validate_search_filters(filters: SearchFilters) -> SearchFilters:
    for value in (filters.date_from, filters.date_to):
        if value is None:
            continue
        try:
            time.strptime(value, "%Y-%m-%d")
        except ValueError as exc:
            raise typer.BadParameter(f"Invalid ISO date: {value}") from exc
    if filters.date_from and filters.date_to and filters.date_from > filters.date_to:
        raise typer.BadParameter("--date-from must not be later than --date-to")
    if filters.delivery and filters.delivery not in {"print", "email", "both"}:
        raise typer.BadParameter("--delivery must be print, email, or both")
    return filters


@app.command("index")
def index_letters() -> None:
    """Rebuild the optional search index from configured roots."""
    _ensure_search_ready()
    try:
        count, errors = rebuild_index(_roots())
    except SearchUnavailableError as exc:
        console.print(f"error: {exc}", markup=False)
        raise typer.Exit(2) from exc
    console.print(f"Indexed {count} letters in {database_path()}")
    for path, message in errors:
        console.print(f"{path}:1:1: warning: {message} [index]")


def _ensure_search_ready() -> None:
    if not search_enabled():
        console.print("error: Optional search is disabled. Enable it with: dinbrief setup search --enable")
        raise typer.Exit(2)
    if not search_available():
        console.print(
            "error: Optional search support is not installed. "
            "Install it with: uv tool install 'dinbrief[search]'",
            markup=False,
        )
        raise typer.Exit(2)


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


@setup_app.command("search")
def setup_search(enable: bool = False, disable: bool = False) -> None:
    """Enable, disable, or show the status of optional search support."""
    if enable and disable:
        raise typer.BadParameter("Choose either --enable or --disable")
    if not enable and not disable:
        state = "enabled" if search_enabled() else "disabled"
        installed = "installed" if search_available() else "not installed"
        console.print(f"Search is {state}; optional package is {installed}.")
        if not search_available():
            console.print("Install it with: uv tool install 'dinbrief[search]'", markup=False)
        if sys.stdin.isatty() and search_available():
            from .interactive import ask_search_activation

            choice = ask_search_activation(search_enabled())
            if choice is not None and choice != search_enabled():
                path = set_search_enabled(choice)
                console.print(f"Search {'enabled' if choice else 'disabled'}: {path}")
        return
    if enable and not search_available():
        console.print(
            "error: Install search support first with: uv tool install 'dinbrief[search]'",
            markup=False,
        )
        raise typer.Exit(2)
    path = set_search_enabled(enable)
    console.print(f"Search {'enabled' if enable else 'disabled'}: {path}")


@app.command("shell")
def interactive_shell() -> None:
    """Open an inline interactive menu for common dinbrief actions."""
    if not sys.stdin.isatty():
        raise typer.BadParameter("The interactive shell requires a terminal")
    from .interactive import ask_action, ask_letter_path, ask_new_letter

    while True:
        action = ask_action()
        if action in {None, "exit"}:
            return
        try:
            if action == "search":
                if not search_enabled():
                    setup_search(False, False)
                    if not search_enabled():
                        continue
                search(query=None, interactive=True)
            elif action in {"check", "render", "open"}:
                selected = ask_letter_path()
                if selected is None:
                    continue
                path = Path(selected)
                if action == "check":
                    check(path)
                elif action == "render":
                    render(path, None, False)
                else:
                    render_and_open(path)
            elif action == "new":
                details = ask_new_letter()
                if details is not None:
                    new(Path(details[0]), details[1])
            elif action == "setup-search":
                setup_search(False, False)
        except typer.Exit:
            continue


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
