# Changelog

All notable changes to dinbrief are recorded here.

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
