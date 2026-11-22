"""Locate YAML keys and values in a letter, including partially edited frontmatter."""

from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass

import yaml
from yaml.error import Mark
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

KEY = re.compile(r""" *(?P<quote>['"]?)(?P<name>[\w-]+)(?P=quote):(?=\s|$)""")
_BOUNDARY = re.compile(r"-{3,}[ \t]*\r?$")
FieldPath = tuple[str, ...]


@dataclass(frozen=True)
class Span:
    line: int
    column: int
    end_line: int
    end_column: int

    def contains(self, line: int, column: int) -> bool:
        return (self.line, self.column) <= (line, column) <= (self.end_line, self.end_column)


@dataclass(frozen=True)
class Field:
    key: Span | None
    value: Span
    scalar: bool = True
    alias: bool = False


class Frontmatter:
    def __init__(self, text: str) -> None:
        self.lines = [line.removesuffix("\r") for line in text.split("\n")]
        self.newline = "\r\n" if "\r\n" in text else "\n"
        self.opening = next((i for i, line in enumerate(self.lines) if line.strip()), 0)
        self.present = bool(_BOUNDARY.fullmatch(self.lines[self.opening]))
        self.end = len(self.lines)
        self.fields: dict[FieldPath, Field] = {}
        self.parents: dict[int, FieldPath] = {}
        self.yaml_error: Span | None = None
        self.duplicates: list[tuple[FieldPath, Span]] = []
        if not self.present:
            return
        self.end = next(
            (
                i
                for i in range(self.opening + 1, len(self.lines))
                if _BOUNDARY.fullmatch(self.lines[i])
            ),
            len(self.lines),
        )
        self._index_block_lines()
        # PyYAML counts Unicode separators as line breaks. Map its character offsets
        # back to the document's physical lines before creating LSP ranges.
        self._yaml_offsets = [0]
        for line in self.lines[self.opening + 1 : self.end]:
            self._yaml_offsets.append(self._yaml_offsets[-1] + len(line) + 1)
        try:
            root = yaml.compose(
                "\n".join(self.lines[self.opening + 1 : self.end]), Loader=yaml.SafeLoader
            )
        except yaml.MarkedYAMLError as exc:
            if mark := exc.problem_mark:
                row, column = self._position(mark)
                self.yaml_error = Span(row, column, row, min(column + 1, len(self.lines[row])))
            return
        except (yaml.YAMLError, RecursionError):
            return
        if isinstance(root, MappingNode):
            self.fields.clear()
            self._index_node(root, (), set())

    def _index_block_lines(self) -> None:
        stack: list[tuple[int, str]] = []
        for line_number in range(self.opening + 1, self.end):
            line = self.lines[line_number]
            indent = len(line) - len(line.lstrip(" "))
            parent = tuple(key for level, key in stack if level < indent)
            self.parents[line_number] = parent
            if match := KEY.match(line):
                key = match["name"]
                value = line[match.end() :].lstrip()
                self.fields[(*parent, key)] = Field(
                    Span(
                        line_number,
                        match.start("quote"),
                        line_number,
                        match.end("name") + len(match["quote"]),
                    ),
                    Span(line_number, len(line) - len(value), line_number, len(line)),
                )
                stack = stack[: len(parent)]
                if not value or value.startswith("#"):
                    stack.append((indent, key))

    def _position(self, mark: Mark) -> tuple[int, int]:
        row = bisect_right(self._yaml_offsets, mark.index) - 1
        line = min(self.opening + 1 + row, len(self.lines) - 1)
        return line, min(mark.index - self._yaml_offsets[row], len(self.lines[line]))

    def _span(self, node: Node) -> Span:
        return Span(*self._position(node.start_mark), *self._position(node.end_mark))

    def _index_node(self, node: Node, path: FieldPath, seen: set[int]) -> None:
        # Aliases point at their original node. Visit it once to avoid cycles and false ranges.
        if id(node) in seen:
            return
        seen.add(id(node))
        if isinstance(node, MappingNode):
            for key, value in node.value:
                if not isinstance(key, ScalarNode):
                    continue
                child = (*path, key.value)
                key_span = self._span(key)
                if child in self.fields:
                    self.duplicates.append((child, key_span))
                    # A duplicate mapping replaces the earlier value and its descendants.
                    for old in [item for item in self.fields if item[: len(child)] == child]:
                        del self.fields[old]
                alias = id(value) in seen
                value_span = key_span if alias else self._span(value)
                self.fields[child] = Field(
                    key_span, value_span, isinstance(value, ScalarNode), alias
                )
                self._index_node(value, child, seen)
        elif isinstance(node, SequenceNode):
            for index, child_node in enumerate(node.value):
                if id(child_node) in seen:
                    continue
                child = (*path, str(index))
                self.fields[child] = Field(
                    None, self._span(child_node), isinstance(child_node, ScalarNode)
                )
                self._index_node(child_node, child, seen)

    @property
    def closed(self) -> bool:
        return self.present and self.end < len(self.lines)

    @property
    def body_start(self) -> int:
        start = self.end + 1 if self.closed else 0
        return next(
            (i for i in range(start, len(self.lines)) if self.lines[i].strip()), len(self.lines) - 1
        )

    def line_span(self, line: int) -> Span:
        line = min(line, len(self.lines) - 1)
        text = self.lines[line]
        return Span(line, len(text) - len(text.lstrip()), line, len(text))
