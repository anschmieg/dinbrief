from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import typst

from .diagnostics import Diagnostic, heuristic_diagnostics
from .markdown import escape_typst, markdown_to_typst
from .model import ParsedLetter, Party

COUNTRY_NAMES = {"DE": "Deutschland", "GB": "United Kingdom", "US": "United States"}
GERMAN_MONTHS = (
    "Januar",
    "Februar",
    "März",
    "April",
    "Mai",
    "Juni",
    "Juli",
    "August",
    "September",
    "Oktober",
    "November",
    "Dezember",
)
ENGLISH_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def _party_lines(party: Party, language: str) -> list[str]:
    lines: list[str] = []
    if party.name:
        lines.append(party.name)
    if party.organization and party.organization != party.name:
        lines.append(party.organization)
    if party.department:
        lines.append(party.department)
    lines.extend(party.address.extra)
    lines.append(party.address.street)
    if party.address.country == "US":
        lines.append(f"{party.address.city}, {party.address.postal_code}")
    else:
        lines.append(f"{party.address.postal_code} {party.address.city}")
    home_country = "DE" if language.startswith("de") else party.address.country
    if party.address.country != home_country:
        lines.append(COUNTRY_NAMES.get(party.address.country, party.address.country))
    return lines


def _date_string(letter: ParsedLetter) -> str:
    value = letter.metadata.date
    location = letter.metadata.location
    if not location and isinstance(letter.metadata.sender, Party):
        location = letter.metadata.sender.address.city
    if letter.metadata.language == "en-US":
        date_text = f"{ENGLISH_MONTHS[value.month - 1]} {value.day}, {value.year}"
        return f"{location}, {date_text}" if location else date_text
    if letter.metadata.language.startswith("en"):
        date_text = f"{value.day} {ENGLISH_MONTHS[value.month - 1]} {value.year}"
        return f"{location}, {date_text}" if location else date_text
    date_text = f"{value.day}. {GERMAN_MONTHS[value.month - 1]} {value.year}"
    return f"{location}, den {date_text}" if location else date_text


def _reference_markup(references: dict[str, str]) -> str:
    parts: list[str] = []
    for key, value in references.items():
        label = escape_typst(key.replace("_", " ").title())
        parts.append(
            f'#text(size: 7pt, fill: rgb("#555555"))[{label}]'
            + " \\\n"
            + escape_typst(value)
        )
    return "\n".join(parts)


def build_typst_source(letter: ParsedLetter) -> str:
    meta = letter.metadata
    assert isinstance(meta.sender, Party)
    recipient = " \\\n".join(
        escape_typst(line) for line in _party_lines(meta.recipient, meta.language)
    )
    sender_address = (
        f"{meta.sender.address.street}, {meta.sender.address.postal_code} "
        f"{meta.sender.address.city}"
    )
    sender_short = escape_typst(f"{meta.sender.display_name} · {sender_address}")
    sender_lines = " \\\n".join(
        escape_typst(line)
        for line in _party_lines(meta.sender, meta.language)
        if line != meta.sender.display_name
    )
    references = _reference_markup(meta.references)
    attachments_label = "Anlagen" if meta.language.startswith("de") else "Attachments"
    attachments = ""
    if meta.attachments:
        items = "\n".join(f"- {escape_typst(item)}" for item in meta.attachments)
        attachments = f"#v(8mm)\n*{attachments_label}:*\n{items}"
    # Typst placement is relative to the 20 mm top content edge, while DIN
    # coordinates are measured from the physical top edge of the sheet.
    address_offset = "7mm" if meta.layout.form == "A" else "25mm"
    information_offset = "12mm" if meta.layout.form == "A" else "30mm"
    content_offset = "64mm" if meta.layout.form == "A" else "72mm"
    fold_positions = ("67mm", "172mm") if meta.layout.form == "A" else ("85mm", "190mm")
    fold_marks = "\n#".join(
        f"place(left, dx: -22mm, dy: {position})"
        "[#line(length: 3mm, stroke: 0.4pt)]"
        for position in fold_positions
    )
    if not meta.layout.fold_marks:
        fold_marks = ""
    hole_mark = (
        "place(left, dx: -22mm, dy: 128.5mm)[#line(length: 5mm, stroke: 0.6pt)]"
        if meta.layout.hole_mark
        else ""
    )
    return f'''#set page(paper: "a4", margin: (left: 25mm, right: 20mm, top: 20mm, bottom: 20mm))
#let sans = ("New Computer Modern Sans", "Libertinus Sans", "Arial")
#let serif = ("New Computer Modern", "Libertinus Serif", "Times New Roman")
#set text(font: sans, size: 10pt, lang: "{meta.language.split('-')[0]}")
#set par(justify: false, leading: 0.65em)
#let address = block(width: 80mm)[
#text(size: 7pt)[#underline[{sender_short}]]
#v(3mm)
{recipient}
]
#let references = block(width: 65mm)[#align(right)[{references}]]
#let subject = block(width: 165mm)[#text(weight: "bold")[{escape_typst(meta.subject)}]]
#let sender-info = block(width: 65mm)[
  #align(right)[
    #text(weight: "bold")[{escape_typst(meta.sender.display_name)}] \\
    {sender_lines}
  ]
]
#context {{
  let address-size = measure(address)
  [#metadata((code: "address-overflow", overflow: address-size.height > 40mm, height: repr(address-size.height))) <layout-diagnostic>]
  let reference-size = measure(references)
  [#metadata((code: "references-overflow", overflow: reference-size.height > 28mm, height: repr(reference-size.height))) <layout-diagnostic>]
  let subject-size = measure(subject)
  [#metadata((code: "subject-overflow", overflow: subject-size.height > 28pt, height: repr(subject-size.height))) <layout-diagnostic>]
  let sender-size = measure(sender-info)
  [#metadata((code: "sender-info-overflow", overflow: sender-size.height > 65mm, height: repr(sender-size.height))) <layout-diagnostic>]
}}
#place(top + left, dx: 0mm, dy: {address_offset})[
  #box(width: 80mm, height: 40mm, clip: true)[#address]
]
#place(top + right, dx: 0mm, dy: -5mm)[
  #sender-info
]
#place(top + right, dx: 0mm, dy: {information_offset})[
  #block(width: 65mm)[#align(right)[#references]]
]
#{fold_marks}
#{hole_mark}
#v({content_offset})
#align(right)[#text(font: serif)[{escape_typst(_date_string(letter))}]]
#v(6mm)
#subject
#v(8mm)
#text(font: serif)[
{escape_typst(meta.salutation)}

{markdown_to_typst(letter.body)}

#v(6mm)
{escape_typst(meta.closing)}
#v(12mm)
{escape_typst(meta.sender.display_name)}
]
{attachments}
'''


def render_pdf(letter: ParsedLetter, output: Path) -> list[Diagnostic]:
    source = build_typst_source(letter).encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    typst.compile(cast(Any, source), output=str(output))
    diagnostics = heuristic_diagnostics(letter)
    try:
        raw = typst.query(source, "<layout-diagnostic>", field="value")
        values: list[dict[str, Any]] = json.loads(raw)
        fields = {
            "address-overflow": "recipient",
            "references-overflow": "references",
            "subject-overflow": "subject",
            "sender-info-overflow": "sender",
        }
        labels = {
            "address-overflow": "Address window",
            "references-overflow": "Reference block",
            "subject-overflow": "Subject",
            "sender-info-overflow": "Sender information",
        }
        for value in values:
            if value.get("overflow"):
                code = str(value["code"])
                diagnostics.append(
                    Diagnostic(
                        "warning",
                        code,
                        f"{labels.get(code, 'Layout region')} overflow detected "
                        f"(height {value.get('height')}).",
                        fields.get(code),
                        False,
                    )
                )
    except Exception:
        pass
    return diagnostics


def render_preview(letter: ParsedLetter, output: Path, ppi: float = 120.0) -> None:
    """Render the first page as PNG for editor previews."""
    source = build_typst_source(letter).encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    rendered = typst.compile(cast(Any, source), format="png", ppi=ppi)
    first_page = rendered[0] if isinstance(rendered, list) else rendered
    output.write_bytes(bytes(first_page))
