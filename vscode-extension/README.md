# dinbrief for VS Code

This optional extension provides schema-driven completion, hover documentation, quick fixes,
status-bar diagnostics, and an embedded page preview for `*.letter.md`. Install the `dinbrief`
CLI first. During typing, inexpensive heuristics run immediately and an exact in-memory Typst
layout pass updates diagnostics and the preview after the configured debounce.

The service starts only when a letter is opened. Requests time out cleanly, stale responses cannot
overwrite newer diagnostics, and each open document uses an isolated preview. CLI commands run as
VS Code process tasks, so paths work consistently on macOS, Windows, and Linux.

Configure `dinbrief.executable` if `dinbrief` is not on VS Code's PATH. Service failures appear in
the **dinbrief** output channel and as editor diagnostics.

`*.letter.md` deliberately remains standard Markdown. The command **DIN-Brief: Markdownlint für
Brief konfigurieren** adds a file-local directive that disables only line-length (`MD013`) and
first-heading (`MD041`) checks. It does not change Markdownlint behavior for other files; useful
rules such as the final-newline check remain enabled.

For development, open this directory in VS Code and run the extension host. Packaging can be
done with `npx @vscode/vsce package`.
