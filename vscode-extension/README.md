# dinbrief for VS Code

This optional extension provides unsaved-buffer diagnostics and completion for `*.letter.md`.
Install the `dinbrief` CLI first. During typing, inexpensive heuristics run immediately and an
exact in-memory Typst layout pass follows after the configured debounce.

For development, open this directory in VS Code and run the extension host. Packaging can be
done with `npx @vscode/vsce package`.
