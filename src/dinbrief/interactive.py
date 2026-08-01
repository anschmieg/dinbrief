from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import questionary
from prompt_toolkit.styles import Style
from questionary import Choice

from .index import SearchFacets, SearchFilters, SearchSort

STYLE = Style.from_dict(
    {
        "qmark": "fg:#6c71c4 bold",
        "question": "bold",
        "answer": "fg:#2aa198 bold",
        "pointer": "fg:#d33682 bold",
        "highlighted": "fg:#d33682 bold",
        "selected": "fg:#2aa198",
        "instruction": "fg:#839496",
    }
)


@dataclass(frozen=True)
class InteractiveSearch:
    query: str
    filters: SearchFilters
    sort: SearchSort
    fuzziness: int
    limit: int


def ask_action() -> str | None:
    answer = questionary.select(
        "What would you like to do?",
        choices=[
            Choice("Search letters", "search"),
            Choice("Check a letter", "check"),
            Choice("Create PDF", "render"),
            Choice("Create and open PDF", "open"),
            Choice("Create a new letter", "new"),
            Choice("Configure optional search", "setup-search"),
            Choice("Exit", "exit"),
        ],
        style=STYLE,
    ).ask()
    return str(answer) if answer is not None else None


def ask_letter_path(message: str = "Letter file") -> str | None:
    answer = questionary.path(
        message,
        validate=lambda value: (
            (value.endswith(".letter.md") and Path(value).is_file())
            or "Select an existing *.letter.md file"
        ),
        style=STYLE,
    ).ask()
    return str(answer) if answer is not None else None


def ask_new_letter() -> tuple[str, str] | None:
    path = questionary.path(
        "New letter file",
        default="new.letter.md",
        validate=lambda value: value.endswith(".letter.md") or "Use the .letter.md suffix",
        style=STYLE,
    ).ask()
    if path is None:
        return None
    language = questionary.select(
        "Language",
        choices=["de-DE", "en-GB", "en-US"],
        style=STYLE,
    ).ask()
    return (str(path), str(language)) if language is not None else None


def _date_or_empty(value: str) -> bool | str:
    if not value:
        return True
    try:
        date.fromisoformat(value)
    except ValueError:
        return "Use an ISO date such as 2026-08-01"
    return True


def _number_in_range(value: str) -> bool | str:
    if value.isdigit() and 1 <= int(value) <= 500:
        return True
    return "Enter a number between 1 and 500"


def _optional_autocomplete(message: str, choices: tuple[str, ...]) -> str | None:
    if not choices:
        answer = questionary.text(message, style=STYLE).ask()
    else:
        answer = questionary.autocomplete(
            message,
            choices=list(choices),
            match_middle=True,
            ignore_case=True,
            style=STYLE,
        ).ask()
    return (str(answer).strip() or None) if answer is not None else None


def ask_search(facets: SearchFacets) -> InteractiveSearch | None:
    query = questionary.text(
        "Search letters",
        validate=lambda value: bool(value.strip()) or "Enter at least one search term",
        style=STYLE,
    ).ask()
    if query is None:
        return None

    selected = questionary.checkbox(
        "Add filters",
        choices=[
            Choice("Tag", "tag"),
            Choice("Language", "language"),
            Choice("Sender", "sender"),
            Choice("Recipient", "recipient"),
            Choice("Delivery method", "delivery"),
            Choice("Date range", "date"),
            Choice("Folder", "folder"),
        ],
        instruction="Space selects, Enter continues",
        style=STYLE,
    ).ask()
    if selected is None:
        return None

    values: dict[str, str | None] = {}
    if "tag" in selected:
        values["tag"] = _optional_autocomplete("Tag", facets.tags)
    if "language" in selected:
        values["language"] = _optional_autocomplete("Language", facets.languages)
    if "sender" in selected:
        values["sender"] = _optional_autocomplete("Sender", facets.senders)
    if "recipient" in selected:
        values["recipient"] = _optional_autocomplete("Recipient", facets.recipients)
    if "delivery" in selected:
        values["delivery"] = _optional_autocomplete("Delivery method", facets.deliveries)
    if "date" in selected:
        date_from = questionary.text("From date", validate=_date_or_empty, style=STYLE).ask()
        if date_from is None:
            return None
        date_to = questionary.text("To date", validate=_date_or_empty, style=STYLE).ask()
        if date_to is None:
            return None
        values["date_from"] = date_from or None
        values["date_to"] = date_to or None
    if "folder" in selected:
        folder = questionary.path("Folder contains", style=STYLE).ask()
        if folder is None:
            return None
        values["folder"] = folder or None

    sort = questionary.select(
        "Sort results",
        choices=[
            Choice("Relevance", "relevance"),
            Choice("Newest first", "date-desc"),
            Choice("Oldest first", "date-asc"),
            Choice("Recipient", "recipient"),
            Choice("Subject", "subject"),
            Choice("Path", "path"),
        ],
        style=STYLE,
    ).ask()
    if sort is None:
        return None
    fuzziness = questionary.select(
        "Typo tolerance",
        choices=[
            Choice("Balanced — one edit", 1),
            Choice("Exact", 0),
            Choice("Tolerant — two edits", 2),
        ],
        style=STYLE,
    ).ask()
    if fuzziness is None:
        return None
    limit = questionary.text("Maximum results", default="25", validate=_number_in_range, style=STYLE).ask()
    if limit is None:
        return None

    return InteractiveSearch(
        query=str(query).strip(),
        filters=SearchFilters(**values),
        sort=SearchSort(str(sort)),
        fuzziness=int(fuzziness),
        limit=int(limit),
    )


def ask_search_activation(enabled: bool) -> bool | None:
    answer = questionary.select(
        "Optional search",
        choices=[
            Choice("Keep enabled" if enabled else "Enable", "enable"),
            Choice("Disable" if enabled else "Keep disabled", "disable"),
            Choice("Cancel", "cancel"),
        ],
        style=STYLE,
    ).ask()
    if answer == "enable":
        return True
    if answer == "disable":
        return False
    return None
