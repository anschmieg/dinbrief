from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from email.message import EmailMessage
from enum import StrEnum
from importlib.resources import as_file, files
from pathlib import Path
from typing import Annotated, Any

import typer
from markdown_it import MarkdownIt
from rich.console import Console
from rich.table import Table

from . import __version__
from .config import deep_merge, load_config, search_enabled, set_search_enabled
from .diagnostics import Diagnostic, heuristic_diagnostics
from .index import (
    IndexedLetter,
    SearchFilters,
    SearchSort,
    SearchUnavailableError,
    database_path,
    index_facets,
    index_is_stale,
    query_index,
    rebuild_index,
    search_available,
)
from .model import Party
from .parser import LetterParseError, parse_file, parse_text
from .render import render_pdf, render_preview

app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)
setup_app = typer.Typer(no_args_is_help=True)
app.add_typer(setup_app, name="setup")
console = Console()


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"dinbrief {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option("--version", callback=_version_callback, is_eager=True, help="Show version."),
    ] = False,
) -> None:
    """Create, validate, render, and find text-first DIN letters."""


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


def _resource_text(resource_path: str, source_fallback: Path) -> str:
    resource = files("dinbrief").joinpath(f"resources/{resource_path}")
    if resource.is_file():
        with as_file(resource) as candidate:
            return candidate.read_text(encoding="utf-8")
    return (Path(__file__).parents[2] / source_fallback).read_text(encoding="utf-8")


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
    render(path, None, False)
    target = _default_output(path).resolve()
    try:
        _open_file(target)
    except (OSError, subprocess.SubprocessError) as exc:
        console.print(f"error: Could not open {target}: {exc}", markup=False)
        raise typer.Exit(1) from exc


@app.command("watch")
def watch_letter(path: Annotated[Path, typer.Argument(exists=True, dir_okay=False)]) -> None:
    """Re-render whenever the source file is saved."""
    from watchfiles import watch

    path = path.resolve()
    render(path, None, False)
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
    roots = (Path(item).expanduser().resolve() for item in load_config().get("roots", [Path.cwd()]))
    return list(dict.fromkeys(roots))


def _letter_records() -> tuple[list[tuple[Path, Any]], list[tuple[Path, str]]]:
    records: list[tuple[Path, Any]] = []
    errors: list[tuple[Path, str]] = []
    seen: set[Path] = set()
    for root in _roots():
        if root.exists():
            for path in root.rglob("*.letter.md"):
                path = path.resolve()
                if path in seen:
                    continue
                seen.add(path)
                try:
                    records.append((path, parse_file(path)))
                except LetterParseError as exc:
                    errors.append((path, str(exc)))
    return sorted(records, key=lambda item: str(item[0]).casefold()), errors


def _sender_name(sender: str | Party) -> str:
    return sender.display_name if isinstance(sender, Party) else sender


class ArchiveSort(StrEnum):
    DATE_DESC = "date-desc"
    DATE_ASC = "date-asc"
    RECIPIENT = "recipient"
    SUBJECT = "subject"
    PATH = "path"


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
    sort: ArchiveSort = ArchiveSort.DATE_DESC,
) -> None:
    """List letters in configured roots."""
    table = Table("Date", "Recipient", "Subject", "Tags", "Path")
    rows: list[tuple[Path, Any]] = []
    filters = _validate_search_filters(
        SearchFilters(date_from=date_from, date_to=date_to, delivery=delivery)
    )
    records, errors = _letter_records()
    for path, letter in records:
        meta = letter.metadata
        if tag and tag.lower() not in meta.tags:
            continue
        if language and meta.language != language:
            continue
        if sender and sender.casefold() not in _sender_name(meta.sender).casefold():
            continue
        if recipient and recipient.casefold() not in meta.recipient.display_name.casefold():
            continue
        if filters.delivery and meta.delivery.method != filters.delivery:
            continue
        if filters.date_from and str(meta.date) < filters.date_from:
            continue
        if filters.date_to and str(meta.date) > filters.date_to:
            continue
        if folder and folder.casefold() not in str(path.parent).casefold():
            continue
        rows.append((path, letter))
    keys = {
        ArchiveSort.DATE_DESC: lambda item: (str(item[1].metadata.date), str(item[0]).casefold()),
        ArchiveSort.DATE_ASC: lambda item: (str(item[1].metadata.date), str(item[0]).casefold()),
        ArchiveSort.RECIPIENT: lambda item: (
            item[1].metadata.recipient.display_name.casefold(),
            str(item[0]).casefold(),
        ),
        ArchiveSort.SUBJECT: lambda item: (
            item[1].metadata.subject.casefold(),
            str(item[0]).casefold(),
        ),
        ArchiveSort.PATH: lambda item: (str(item[0]).casefold(),),
    }
    rows.sort(key=keys[sort], reverse=sort == ArchiveSort.DATE_DESC)
    for path, letter in rows:
        meta = letter.metadata
        table.add_row(
            str(meta.date),
            meta.recipient.display_name,
            meta.subject,
            ", ".join(meta.tags),
            str(path),
        )
    console.print(table)
    for path, message in errors:
        console.print(f"{path}:1:1: warning: {message} [list]")


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
        roots = _roots()
        if refresh or index_is_stale(roots):
            count, errors = rebuild_index(roots)
            console.print(f"Refreshed search index: {count} letters")
            for path, message in errors:
                console.print(f"{path}:1:1: warning: {message} [index]")
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
        query = query.strip()
        if not query:
            raise typer.BadParameter("QUERY must not be empty")
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
def new(
    path: Annotated[Path, typer.Argument()] = Path("new.letter.md"),
    language: Annotated[str, typer.Option("--language", "-l")] = "de-DE",
) -> None:
    """Create a minimal self-contained letter source."""
    path = path.expanduser()
    if path.exists():
        raise typer.BadParameter(f"File already exists: {path}")
    sample = _sample(language)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(sample, encoding="utf-8")
    console.print(str(path.resolve()))


def _sample(language: str) -> str:
    salutation = "Sehr geehrte Damen und Herren," if language.startswith("de") else "Dear Sir or Madam,"
    closing = "Mit freundlichen Grüßen" if language.startswith("de") else "Yours faithfully,"
    subject = "Betreff" if language.startswith("de") else "Subject"
    body = "Schreiben Sie hier Ihren Brief." if language.startswith("de") else "Write your letter here."
    return f'''---
format: dinbrief/v2
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
salutation: {salutation}
closing: {closing}
tags: []
---

# {subject}

{body}
'''


@setup_app.command("vscode")
def setup_vscode(
    folder: Annotated[Path | None, typer.Argument()] = None,
) -> None:
    """Install VS Code tasks for the active *.letter.md file."""
    vscode = (folder.expanduser() if folder else Path.cwd()).resolve() / ".vscode"
    vscode.mkdir(parents=True, exist_ok=True)
    updates: dict[Path, dict[str, Any]] = {}
    for name in ("tasks.json", "settings.json", "extensions.json"):
        bundled = json.loads(_resource_text(f"vscode/{name}", Path(".vscode") / name))
        destination = vscode / name
        current: dict[str, Any] = {}
        if destination.exists():
            try:
                current = json.loads(destination.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                raise typer.BadParameter(
                    f"Cannot safely update {destination}: {exc}. The file was left unchanged."
                ) from exc
        merged = _merge_vscode_file(name, current, bundled)
        updates[destination] = merged
    for destination, merged in updates.items():
        _write_json_atomic(destination, merged)
    console.print(str(vscode))


def _merge_vscode_file(
    name: str, current: dict[str, Any], bundled: dict[str, Any]
) -> dict[str, Any]:
    if name == "tasks.json":
        labels = {task.get("label") for task in bundled.get("tasks", [])}
        retained = [task for task in current.get("tasks", []) if task.get("label") not in labels]
        result = deep_merge(bundled, current)
        result["tasks"] = [*retained, *bundled.get("tasks", [])]
        return result
    if name == "extensions.json":
        result = deep_merge(bundled, current)
        result["recommendations"] = list(
            dict.fromkeys([*current.get("recommendations", []), *bundled.get("recommendations", [])])
        )
        return result
    return deep_merge(bundled, current)


def _write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            temporary = Path(handle.name)
        temporary.replace(path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


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
    data = _resource_text("schemas/letter.schema.json", Path("schemas/letter.schema.json"))
    if output:
        output = output.expanduser()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(data, encoding="utf-8")
        console.print(str(output.resolve()))
    else:
        console.print(data)


@app.command("validate-json")
def validate_json() -> None:
    """Internal stdin JSON validation endpoint for editor integrations."""
    payload: dict[str, Any] = json.load(sys.stdin)
    try:
        parsed = parse_text(payload["text"])
        result = {"diagnostics": [item.__dict__ for item in heuristic_diagnostics(parsed)]}
    except LetterParseError as exc:
        result = {"diagnostics": _parse_error_diagnostics(exc)}
    except KeyError as exc:
        result = {"diagnostics": [{"severity": "error", "code": "protocol", "message": f"Missing request property: {exc}"}]}
    json.dump(result, sys.stdout)


def _parse_error_diagnostics(exc: LetterParseError) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    for issue in exc.issues:
        item: dict[str, Any] = {"severity": "error", "code": issue.code, "message": issue.message}
        if issue.field:
            item["field"] = issue.field
        if issue.line is not None:
            item["line"] = issue.line
        if issue.column is not None:
            item["column"] = issue.column
        diagnostics.append(item)
    return diagnostics


def _editor_response(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        parsed = parse_text(str(payload["text"]), str(payload.get("uri", "<editor>")))
        diagnostics = heuristic_diagnostics(parsed)
        response: dict[str, Any] = {"id": payload.get("id"), "diagnostics": [item.__dict__ for item in diagnostics]}
        if payload.get("render"):
            import hashlib

            from .config import cache_dir

            document_key = hashlib.sha256(str(payload.get("uri", "<editor>")).encode()).hexdigest()[:16]
            target = cache_dir() / f"preview-{document_key}.pdf"
            preview = cache_dir() / f"preview-{document_key}.png"
            diagnostics = render_pdf(parsed, target)
            render_preview(parsed, preview)
            response["diagnostics"] = [item.__dict__ for item in diagnostics]
            response["preview"] = str(preview)
            response["pdf"] = str(target)
        return response
    except LetterParseError as exc:
        return {"id": payload.get("id"), "diagnostics": _parse_error_diagnostics(exc)}
    except Exception as exc:
        return {"id": payload.get("id"), "diagnostics": [{"severity": "error", "code": "internal", "message": f"Internal dinbrief error: {exc}"}]}


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
