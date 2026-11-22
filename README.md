# dinbrief

`dinbrief` turns searchable `*.letter.md` source files into DIN 5008 PDFs.

## Start writing now

Copy [`examples/de/example.letter.md`](examples/de/example.letter.md), keep the YAML
frontmatter between the `---` lines, write the subject as the first level-one heading, and
continue with the letter body as normal Markdown.

```bash
uv tool install .
dinbrief --version
dinbrief check examples/de/example.letter.md
dinbrief render examples/de/example.letter.md
```

Search is an optional feature because its embedded LanceDB engine adds a larger binary
dependency. Install and activate it explicitly:

```bash
uv tool install 'dinbrief[search]'
dinbrief setup search --enable
dinbrief index
dinbrief search "Steuerbescheit"
```

Search is disabled by default even when the extra is installed. `dinbrief setup search` reports
both installation and activation state; `--disable` turns it off without deleting the rebuildable
cache. `uv tool install` is already global; it has no `--global` flag. Reinstalling plain
`dinbrief` omits the optional engine again. Letter sources remain the sole source of truth. Search
automatically refreshes its cache when a letter is created, edited, moved, or deleted.

Without a configured archive root, the PDF is written directly beside the source. For sources
inside a configured `roots` entry, output is collected below `<root>/build/` while preserving
the relative folder structure. Sender defaults and search roots can be configured later; an
inline sender keeps a letter self-contained.

The resulting default path is `<root>/build/<relative path>/<name>.pdf` inside an explicitly
configured root and `<source folder>/<name>.pdf` elsewhere. An optional top-level `location`
field overrides the sender city in the localized date line, for example
`Berlin, den 1. August 2026`, `London, 1 August 2026`, or `New York, August 1, 2026`.

## Commands

- `dinbrief new correspondence/example.letter.md`
- `dinbrief check correspondence/example.letter.md`
- `dinbrief render correspondence/example.letter.md`
- `dinbrief open correspondence/example.letter.md`
- `dinbrief watch correspondence/example.letter.md`
- `dinbrief explain correspondence/example.letter.md`
- `dinbrief email correspondence/example.letter.md`
- `dinbrief list --tag contract`
- `dinbrief list --sort date-desc`
- `dinbrief search termination`
- `dinbrief search --refresh termination`
- `dinbrief search termination --tag contract --sort date-desc`
- `dinbrief search --interactive`
- `dinbrief shell`
- `dinbrief index`
- `dinbrief setup search --enable`
- `dinbrief setup search --disable`
- `dinbrief setup vscode .`

`list` can additionally filter by language, sender, recipient, delivery method, folder and an
ISO date range. When installed and enabled, `search` uses a rebuildable LanceDB full-text index
with BM25 ranking and typo tolerance. Source files are never moved, copied or linked. The index
schema deliberately leaves room for an optional vector column and hybrid semantic search later.

Run `dinbrief search` without a query, use `--interactive`, or open `dinbrief shell` for styled
inline prompts with autocomplete and selectable filters. Scripts can use the equivalent flags:
`--tag`, `--language`, `--sender`, `--recipient`, `--delivery`, `--date-from`, `--date-to`, and
`--folder`. Sort with `--sort relevance|date-desc|date-asc|recipient|subject|path`; control typo
tolerance with `--fuzziness 0|1|2`.

`setup vscode` merges the dinbrief tasks, settings, and extension recommendation with existing
JSON workspace files. It refuses malformed or JSONC files instead of overwriting them; convert
those files to standard JSON or add the documented tasks manually. The update is transactional,
so a validation error leaves every existing workspace file unchanged.

The subject is the first and only level-one heading (`# Subject`) and is not repeated in YAML.
The remaining source body supports CommonMark paragraphs, emphasis, strong text, links, inline
and block code, lower-level headings, block quotes, horizontal rules, and nested ordered or
unordered lists. Unknown frontmatter fields are errors rather than being silently ignored, which
catches misspellings in layout and address fields early.

Letters remain in VS Code's standard Markdown language mode, so highlighting, links, Outline,
Markdownlint, and editor commands work without file-local exceptions. The dinbrief extension
reports missing, unknown, and invalid YAML fields at the closest relevant line. It also validates
the subject heading and offers quick fixes for missing fields and a missing H1.

## Language server

Install the optional editor dependencies with `uv tool install '.[lsp]'` from this checkout.
Configure your editor's LSP client to launch `dinbrief lsp` over stdio for Markdown.
The server handles `*.letter.md` documents. It checks unsaved edits for YAML syntax errors,
duplicate or unknown keys, missing metadata, invalid values, and subject heading problems.
Validation uses your dinbrief configuration, including sender profiles and defaults. Layout
warnings are estimates. Use `dinbrief render` to compile and check the actual PDF.

Press your editor's completion shortcut in the frontmatter for schema fields, allowed values,
and configured sender IDs. Field-name completion works in block-style YAML. Hover over a field
for its schema documentation. Your editor's Quick Fix menu can add missing fields, correct
unambiguous misspellings, and repair subject headings. Review any inserted placeholder before
rendering. An editor needs an LSP client to show these features.

Typora 2 Beta can use the [DIN Letter extension](typora-extension/) to show live diagnostics
in its detail panel.

## Configuration

The optional user configuration is `config.toml` in the platform configuration directory
reported by `python -c "from platformdirs import user_config_dir; print(user_config_dir('dinbrief'))"`.

```toml
roots = ["~/Documents/Letters", "~/Nextcloud/Correspondence"]

[defaults]
language = "de-DE"

[defaults.layout]
standard = "din-5008"
form = "B"
window_envelope = true
fold_marks = true
hole_mark = true

[senders.personal]
name = "Max Mustermann"
email = "max@example.com"

[senders.personal.address]
street = "Musterstraße 1"
postal_code = "12345"
city = "Musterstadt"
country = "DE"
```

## Status

This is an early implementation. Always inspect the PDF preview before sending or printing a
letter. DIN layout tests are included, but this software is not a certification of compliance.
