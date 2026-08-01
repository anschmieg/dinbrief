from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .model import ParsedLetter


@dataclass(frozen=True)
class Diagnostic:
    severity: Literal["error", "warning", "information"]
    code: str
    message: str
    field: str | None = None
    provisional: bool = False


def heuristic_diagnostics(letter: ParsedLetter) -> list[Diagnostic]:
    meta = letter.metadata
    result: list[Diagnostic] = []
    address = meta.recipient.address
    address_lines = 3 + len(address.extra)
    if meta.recipient.organization:
        address_lines += 1
    if meta.recipient.department:
        address_lines += 1
    if address_lines > 6:
        result.append(Diagnostic("warning", "address-lines", "The address may exceed the envelope window (more than 6 lines).", "recipient", True))
    if len(meta.subject) > 90:
        result.append(Diagnostic("warning", "subject-length", "The subject is unusually long and may wrap to three lines.", "subject", True))
    if len(meta.references) > 4:
        result.append(Diagnostic("warning", "references-count", "More than four reference fields may overflow the information block.", "references", True))
    if len(letter.body) > 5000:
        result.append(Diagnostic("information", "long-letter", "This is a long letter; verify page breaks in the preview.", None, True))
    return result

