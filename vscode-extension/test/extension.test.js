const assert = require("node:assert/strict");
const test = require("node:test");

const { _test } = require("../extension.js");

function document(text, fileName = "/tmp/example.letter.md") {
  const lines = text.split("\n");
  return {
    fileName,
    lineCount: lines.length,
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
  const source = "---\nformat: dinbrief/v2\nrecipient:\n  name: Example\n---\nBody";
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

test("subject quick fix promotes the first content line", () => {
  const source = "---\n# YAML comment\nformat: dinbrief/v2\n---\n\nSubject\n\nBody\n";
  const insertion = _test.subjectHeadingEdit(document(source));

  assert.deepEqual(insertion.position, { line: 5, character: 0 });
  assert.equal(insertion.text, "# ");
});

test("subject quick fix supports empty CRLF documents", () => {
  const source = "---\r\nformat: dinbrief/v2\r\n---\r\n";
  const insertion = _test.subjectHeadingEdit(document(source));

  assert.equal(insertion.text, "\r\n# Subject\r\n");
});

test("nested schema diagnostics point to the exact field or its parent", () => {
  const source = "---\nformat: dinbrief/v2\nrecipient:\n  address:\n    city: Berlin\n---\n# Subject\n";
  const doc = document(source);

  assert.equal(_test.lineForField(doc, "recipient.address.city"), 4);
  assert.equal(_test.lineForField(doc, "recipient.address.postal_code"), 3);
  assert.equal(_test.lineForField(doc, "subject"), 6);
});

test("missing nested fields get a targeted quick fix", () => {
  const source = "---\nformat: dinbrief/v2\nrecipient:\n  address:\n    city: Berlin\n---\n# Subject\n";
  const diagnostic = {
    source: "dinbrief",
    code: "field-missing",
    message: "Required field `recipient.address.postal_code` is missing."
  };

  const [action] = _test.missingFieldAction(document(source), diagnostic);

  assert.equal(action.title, "Add required field recipient.address.postal_code");
  assert.equal(action.edit.insertions[0].position.line, 3);
  assert.equal(action.edit.insertions[0].position.character, 10);
  assert.equal(action.edit.insertions[0].text, "\n    postal_code: TODO");
});

test("missing top-level fields get a targeted quick fix", () => {
  const source = "---\nformat: dinbrief/v2\n---\n# Subject\n";
  const diagnostic = {
    source: "dinbrief",
    code: "field-missing",
    message: "Required field `sender` is missing."
  };

  const [action] = _test.missingFieldAction(document(source), diagnostic);

  assert.equal(action.title, "Add required field sender");
  assert.equal(action.edit.insertions[0].text, "\nsender:\n  TODO");
});
