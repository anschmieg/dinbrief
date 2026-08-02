const assert = require("node:assert/strict");
const test = require("node:test");

const { _test } = require("../extension.js");

function document(text, fileName = "/tmp/example.letter.md") {
  const lines = text.split("\n");
  return {
    fileName,
    uri: { scheme: "file", toString: () => `file://${fileName}` },
    getText(range) {
      if (!range) return text;
      return lines.slice(0, range.end.line).join("\n") + "\n" + lines[range.end.line].slice(0, range.end.character);
    },
    positionAt(offset) {
      const before = text.slice(0, offset).split("\n");
      return { line: before.length - 1, character: before.at(-1).length };
    },
    lineAt(line) { return { text: lines[line] }; }
  };
}

test("frontmatter detection stops after the closing delimiter", () => {
  const source = "---\nformat: dinbrief/v1\nrecipient:\n  name: Example\n---\nBody";
  const doc = document(source);

  assert.equal(_test.inFrontmatter(doc, { line: 2, character: 3 }), true);
  assert.equal(_test.inFrontmatter(doc, { line: 5, character: 2 }), false);
});

test("yaml path follows nested frontmatter indentation", () => {
  const source = "---\nrecipient:\n  address:\n    city: Berlin\n    country: DE\n---";
  const doc = document(source);

  assert.deepEqual(_test.yamlPath(doc, { line: 4, character: 4 }), ["recipient", "address"]);
});

test("completion uses the nested schema", () => {
  const source = "---\nrecipient:\n  address:\n    \n---";
  const doc = document(source);
  const labels = _test.completionItems(doc, { line: 3, character: 4 }).map(item => item.label);

  assert.ok(labels.includes("postal_code"));
  assert.ok(labels.includes("country"));
});

test("only the newest response may update diagnostics", () => {
  assert.equal(_test.responseIsCurrent(9, 9), true);
  assert.equal(_test.responseIsCurrent(10, 9), false);
});

test("markdownlint profile is inserted after frontmatter exactly once", () => {
  const source = "---\nformat: dinbrief/v1\n---\n\nBody\n";
  const doc = document(source);
  const insertion = _test.markdownlintInsertion(doc);

  assert.deepEqual(insertion.position, { line: 2, character: 3 });
  assert.match(insertion.text, /markdownlint-disable-file MD013 MD041/);

  const offset = source.indexOf("\n", source.indexOf("format:"));
  const closingOffset = source.indexOf("\n", offset + 1);
  const configured = source.slice(0, closingOffset) + insertion.text + source.slice(closingOffset);
  assert.equal(_test.markdownlintInsertion(document(configured)), undefined);
});

test("markdownlint profile insertion supports CRLF frontmatter", () => {
  const source = "---\r\nformat: dinbrief/v1\r\n---\r\n\r\nBody\r\n";
  const insertion = _test.markdownlintInsertion(document(source));

  assert.deepEqual(insertion.position, { line: 2, character: 3 });
});
