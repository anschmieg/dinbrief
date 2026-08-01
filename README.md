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
- `dinbrief index`
- `dinbrief setup vscode .`

`list` can additionally filter by language, sender, recipient, delivery method, folder and an
ISO date range. `search` uses a rebuildable SQLite index in the user cache; source files remain
the sole source of truth and are never moved, copied or linked.

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
