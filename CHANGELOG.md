# Changelog

All notable changes to dinbrief are recorded here.

## 0.6.0 — 2026-08-02

- Use the first Markdown H1 as the letter subject instead of duplicating content in YAML.
- Remove generated Markdownlint directives and their VS Code command.
- Report all schema violations with concise messages and field-aware editor locations.
- Add subject and missing-field Quick Fixes, including CRLF support.
- Advance the source schema to `dinbrief/v2` for the intentional format change.

## 0.5.4 — 2026-08-02

- Add a letter-local Markdownlint profile that disables only rules inappropriate for prose letters.
- Keep the standard Markdown language mode, syntax highlighting, links, and editor commands intact.
- Add a VS Code quick fix and command for applying the profile to existing letters.
- Exclude the configuration comment from rendered and indexed letter content.

## 0.5.3 — 2026-08-01

- Keep search indexes automatically synchronized with added, changed, moved, and deleted letters.
- Merge VS Code workspace files transactionally instead of overwriting existing configuration.
- Reject unknown frontmatter fields so misspellings cannot silently change a letter.
- Isolate editor previews per document and ignore stale language-service responses.
- Add request timeouts, process recovery, cross-platform extension tasks, and JavaScript tests.
- Preserve ordered lists, headings, quotes, code blocks, links, and additional CommonMark constructs.
- Correct international country handling and support state/region fields in postal addresses.
- Render immediately when `watch` starts and expose the installed version via `--version`.
- Expand CI coverage to Python 3.14 and verify the canonical schema before packaging the extension.

## 0.5.2 — 2026-08-01

- Expand `~` in interactive file paths before validation.
- Defer the native file-watcher import until the `watch` command is used.

## 0.5.1 — 2026-08-01

- Repair interactive path prompts and make Exit and Cancel terminate reliably.
- Guide disabled optional search through setup instead of an error loop.
- Add real-terminal regression coverage for common shell actions.

## 0.5.0 — 2026-08-01

- Add styled inline interaction with Questionary and prompt-toolkit.
- Add an interactive search builder with autocomplete and selectable filters.
- Add exact filters for tag, language, sender, recipient, delivery, date range and folder.
- Add relevance, date, recipient, subject and path sorting.
- Add a reusable interactive shell for common letter actions.
- Keep every interactive operation available as a non-interactive CLI command or option.

## 0.4.0 — 2026-08-01

- Replace the provisional SQLite search implementation with optional embedded LanceDB search.
- Keep search and its larger binary dependencies out of the default installation.
- Add explicit search activation, deactivation and status commands.
- Add BM25 ranking, accent normalization and configurable typo tolerance.
- Prepare the index model for optional vector and hybrid semantic search.
- Test both minimal and search-enabled installations in CI.

## 0.3.0 — 2026-08-01

- Add a rebuildable local SQLite search index without moving or copying source letters.
- Add metadata filters for language, sender, recipient, delivery method, folder and date range.
- Add cross-platform CI for Python 3.12/3.13 and VS Code extension packaging.
- Keep Unicode search case-insensitive, including German umlauts.

## 0.2.0 — 2026-08-01

- Add the VS Code extension with schema completions, live diagnostics and preview.
- Add exact in-memory layout checks and PNG preview generation.

## 0.1.0 — 2026-08-01

- Add the initial CLI, schema and DIN 5008 Typst renderer.
