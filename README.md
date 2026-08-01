# dinbrief

`dinbrief` turns searchable `*.letter.md` source files into DIN 5008 PDFs.

## Start writing now

Copy [`examples/de/example.letter.md`](examples/de/example.letter.md), keep the YAML
frontmatter between the `---` lines, and write the letter body as normal Markdown.

```bash
uv tool install .
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
cache. Reinstalling plain `dinbrief` omits the optional engine again. Letter sources remain the
sole source of truth.

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
