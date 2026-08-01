# dinbrief for VS Code

This optional extension provides schema-driven completion, hover documentation, quick fixes,
status-bar diagnostics, and an embedded page preview for `*.letter.md`. Install the `dinbrief`
CLI first. During typing, inexpensive heuristics run immediately and an exact in-memory Typst
layout pass updates diagnostics and the preview after the configured debounce.

For development, open this directory in VS Code and run the extension host. Packaging can be
done with `npx @vscode/vsce package`.
