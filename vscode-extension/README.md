# dinbrief for VS Code

This optional extension provides schema-driven completion, hover documentation, quick fixes,
status-bar diagnostics, and an embedded page preview for `*.letter.md`. Install the `dinbrief`
CLI first. During typing, inexpensive heuristics run immediately and an exact in-memory Typst
layout pass updates diagnostics and the preview after the configured debounce.

The service starts only when a letter is opened. Requests time out cleanly, stale responses cannot
overwrite newer diagnostics, and each open document uses an isolated preview. CLI commands save
pending edits and launch the configured executable directly, including when a standalone letter
is open without a workspace folder or the preview has focus. CLI failures appear as notifications
with details in the dinbrief output channel.

Configure `dinbrief.executable` if `dinbrief` is not on VS Code's PATH. Service failures appear in
the **dinbrief** output channel and as editor diagnostics.

`*.letter.md` deliberately remains standard Markdown. Its first and only level-one heading is the
printed subject, so standard Markdown tools work without file-local lint exceptions. Schema
diagnostics point to the relevant nested YAML field or subject heading. Quick fixes can add
missing required metadata and promote the first content line to the subject heading.

For development, open this directory in VS Code and run the extension host. Packaging can be
done with `npx @vscode/vsce package`.
