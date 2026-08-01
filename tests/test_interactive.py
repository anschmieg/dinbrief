from __future__ import annotations

from typing import Any

import questionary
from questionary.question import Question

from dinbrief import cli
from dinbrief import interactive as ui


class _Answer:
    def __init__(self, value: object) -> None:
        self.value = value

    def ask(self) -> object:
        return self.value


def test_letter_path_uses_questionary_supported_arguments(monkeypatch: Any) -> None:
    """Construct the real path prompt so unsupported kwargs fail this test."""
    monkeypatch.setattr(Question, "ask", lambda self: None)

    assert ui.ask_letter_path() is None


def test_exit_choice_has_an_explicit_value(monkeypatch: Any) -> None:
    def select(message: str, *, choices: list[questionary.Choice], **kwargs: Any) -> _Answer:
        assert message == "What would you like to do?"
        assert choices[-1].value == "exit"
        return _Answer(choices[-1].value)

    monkeypatch.setattr(questionary, "select", select)

    assert ui.ask_action() == "exit"


def test_search_cancel_has_an_explicit_value(monkeypatch: Any) -> None:
    def select(message: str, *, choices: list[questionary.Choice], **kwargs: Any) -> _Answer:
        assert message == "Optional search"
        assert choices[-1].value == "cancel"
        return _Answer(choices[-1].value)

    monkeypatch.setattr(questionary, "select", select)

    assert ui.ask_search_activation(False) is None


def test_shell_exits_after_one_exit_selection(monkeypatch: Any) -> None:
    actions = iter(["exit"])
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr(ui, "ask_action", lambda: next(actions))

    cli.interactive_shell()

    try:
        next(actions)
    except StopIteration:
        pass
    else:
        raise AssertionError("the shell requested another action after Exit")


def test_shell_routes_each_letter_action(monkeypatch: Any) -> None:
    calls: list[str] = []
    actions = iter(["check", "render", "open", "exit"])
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr(ui, "ask_action", lambda: next(actions))
    monkeypatch.setattr(ui, "ask_letter_path", lambda: "example.letter.md")
    monkeypatch.setattr(cli, "check", lambda path: calls.append(f"check:{path}"))
    monkeypatch.setattr(
        cli, "render", lambda path, output, watch: calls.append(f"render:{path}")
    )
    monkeypatch.setattr(cli, "render_and_open", lambda path: calls.append(f"open:{path}"))

    cli.interactive_shell()

    assert calls == [
        "check:example.letter.md",
        "render:example.letter.md",
        "open:example.letter.md",
    ]


def test_shell_offers_search_setup_instead_of_an_error(monkeypatch: Any) -> None:
    actions = iter(["search", "exit"])
    setup_calls: list[tuple[bool, bool]] = []
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr(ui, "ask_action", lambda: next(actions))
    monkeypatch.setattr(cli, "search_enabled", lambda: False)
    monkeypatch.setattr(cli, "setup_search", lambda enable, disable: setup_calls.append((enable, disable)))
    monkeypatch.setattr(
        cli,
        "search",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("search should remain disabled")),
    )

    cli.interactive_shell()

    assert setup_calls == [(False, False)]
