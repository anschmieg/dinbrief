import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { readFileSync } from "node:fs";
import test from "node:test";

import { revealTarget, snapshot } from "../dinbrief.letter/letter.mjs";
import { frame, LetterClient, LspFrames } from "../dinbrief.letter/lsp.mjs";

const example = readFileSync(new URL("../../examples/en/example.letter.md", import.meta.url), "utf8");
const delimiterEnd = example.indexOf("\n---", 4);
const yaml = example.slice(4, delimiterEnd);
const heading = example.match(/^# .+$/m)[0];

function blocks(header, type = "frontmatter") {
  return [{ id: "properties", type, text: header, depth: 0 }, { id: "subject", type: "heading", text: heading, depth: 0 }];
}

test("partial and adjacent LSP frames count UTF-8 bytes", () => {
  const a = { id: 1, result: "Grüße 😀" };
  const b = { id: 2, result: [] };
  const bytes = new TextEncoder().encode(frame(a) + frame(b));
  const reader = new LspFrames();
  const messages = [];
  for (const byte of bytes) messages.push(...reader.push(Uint8Array.of(byte)));
  assert.deepEqual(messages, [{ jsonrpc: "2.0", ...a }, { jsonrpc: "2.0", ...b }]);
});

test("preserves YAML and maps diagnostics to original UTF-16 block offsets", () => {
  const header = `---\r\n${yaml.replaceAll("\n", "\r\n")}\r\n---`;
  for (const text of [header, yaml]) {
    const letter = snapshot(blocks(text));
    assert.ok(letter);
    assert.ok(letter.text.startsWith(`---\n${yaml}\n---\n\n${heading}`));
    const line = letter.text.split("\n").findIndex((line) => line.includes("  postal_code:"));
    const original = text.indexOf("postal_code:");
    assert.deepEqual(revealTarget(letter, {
      start: { line, character: 4 }, end: { line, character: 15 },
    }), { blockId: "properties", from: original, to: original + 11 });
  }
  assert.equal(snapshot(blocks("---\ntitle: An ordinary note\n---")), null);
  assert.ok(snapshot(blocks(yaml.replace(/^format:.*\n/m, ""))));
});

test("native process bridge validates an unsaved edit, locates the field and clears the issue", {
  timeout: 10000,
  skip: !process.env.DINBRIEF_TEST_EXECUTABLE,
}, async (t) => {
  const child = spawn(process.env.DINBRIEF_TEST_EXECUTABLE, ["lsp"], { stdio: ["pipe", "pipe", "pipe"] });
  const publish = new EventTarget();
  function subscribe(emitter, event, handler) {
    emitter.on(event, handler);
    return () => emitter.off(event, handler);
  }
  const host = {
    onData(handler) {
      const out = subscribe(child.stdout, "data", (bytes) => handler(bytes, "stdout"));
      const err = subscribe(child.stderr, "data", (bytes) => handler(bytes, "stderr"));
      return () => { out(); err(); };
    },
    onExit: (handler) => subscribe(child, "close", (code) => handler({ code })),
    write: (data) => new Promise((resolve, reject) => child.stdin.write(data, (error) => error ? reject(error) : resolve())),
    kill: async () => { child.kill(); },
  };
  const client = new LetterClient(host,
    (diagnostics, version) => publish.dispatchEvent(new CustomEvent("result", { detail: { diagnostics, version } })),
    (message) => publish.dispatchEvent(new CustomEvent("error", { detail: message })),
  );
  t.after(() => client.dispose());
  async function update(letter, version) {
    const response = once(publish, "result", { signal: AbortSignal.timeout(5000) });
    await client.update(letter.text, version);
    return (await response)[0].detail;
  }
  const good = snapshot(blocks(yaml));
  const bad = snapshot(blocks(yaml.replace(/(recipient:[\s\S]*?postal_code:) .+/, "$1 12345")));
  const invalid = await update(bad, 1);
  const issue = invalid.diagnostics.find((item) => item.data?.field === "recipient.address.postal_code");
  assert.ok(issue, JSON.stringify(invalid));
  const target = revealTarget(bad, issue.range);
  assert.equal(target.blockId, "properties");
  assert.equal(bad.locations[issue.range.start.line].block.text.slice(target.from, target.to), "12345");
  assert.deepEqual(await update(good, 2), { diagnostics: [], version: 2 });
});
