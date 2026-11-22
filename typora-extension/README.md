# DIN Letter for Typora 2 Beta

The **DIN Letter** tab in Typora’s right-hand detail panel checks the current draft as you edit.
It sends the draft to the local `dinbrief lsp` process and lists frontmatter and subject issues.
Click an issue to select its source in the editor. Typora supplies the live document as blocks,
so a diagnostic can select the whole block when an exact selection is unavailable.

## Install

1. From the dinbrief checkout, install the CLI with `uv tool install '.[lsp]'`.
2. In Typora, open **Settings → Extensions → Install from File…** and select the
   `dinbrief.letter` folder in this directory.
3. Select **Review Permissions…** and allow the extension to read the active document and start
   `dinbrief`. If Typora cannot find the command, run `command -v dinbrief` on macOS or Linux
   or `where.exe dinbrief` on Windows. Set **dinbrief executable** to the resulting path.
4. Open a letter with `format: dinbrief/v2` in its YAML frontmatter and select **DIN Letter** in
   the detail panel. The extension can also recognize a letter with a `recipient` and at least
   one other letter field after the format key is removed.

## Try live validation

Copy `examples/en/example.letter.md` to a scratch location and open the copy. In the frontmatter,
choose **Edit YAML source** and remove the quotes around the recipient’s `postal_code` after
setting it to `12345`. The panel should report that the value must be a string without waiting
for you to save. Click the issue to select it, then add the quotes back. The issue should clear.

For the local bridge tests, run this from the repo root after `uv sync --extra lsp`:

```sh
DINBRIEF_TEST_EXECUTABLE="$PWD/.venv/bin/dinbrief" node --test typora-extension/test/*.test.mjs
```
