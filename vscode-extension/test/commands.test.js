const assert = require("node:assert/strict");
const { EventEmitter } = require("node:events");
const test = require("node:test");
const { setImmediate } = require("node:timers");
const vscode = require("vscode");
const { _test } = require("../extension.js");

test("PDF commands work with preview focus, save edits, and preserve paths with spaces", async () => {
  const fileName = "/tmp/My letters/example.letter.md";
  let saved = false;
  const document = {
    fileName, uri: { scheme: "file", toString: () => `file://${fileName}` },
    isDirty: true, async save() { saved = true; return true; }
  };
  const messages = [];
  vscode.window = {
    activeTextEditor: undefined,
    showInformationMessage: message => messages.push(message),
    showErrorMessage: message => assert.fail(message)
  };
  vscode.workspace = {
    textDocuments: [document],
    getConfiguration: () => ({ get: () => "/tmp/CLI tools/dinbrief" })
  };
  _test.setOutput({ appendLine() {}, append() {}, show() {} });
  for (const command of ["render", "open"]) {
    await _test.runTask(command, (executable, args, options) => {
      assert.equal(saved, true);
      assert.equal(executable, "/tmp/CLI tools/dinbrief");
      assert.deepEqual(args, [command, fileName]);
      assert.equal(options.cwd, "/tmp/My letters");
      const child = new EventEmitter();
      child.stdout = new EventEmitter();
      child.stderr = new EventEmitter();
      setImmediate(() => child.emit("close", 0));
      return child;
    });
  }
  assert.equal(messages.length, 2);
});

test("CLI launch failures are visible instead of becoming unhandled rejections", async () => {
  const errors = [];
  vscode.window.showErrorMessage = message => errors.push(message);
  let shown = false;
  _test.setOutput({ appendLine() {}, append() {}, show() { shown = true; } });
  await _test.runTask("render", () => {
    const child = new EventEmitter();
    child.stdout = new EventEmitter();
    child.stderr = new EventEmitter();
    setImmediate(() => child.emit("error", new Error("spawn ENOENT")));
    return child;
  });
  assert.equal(shown, true);
  assert.match(errors[0], /ENOENT/);
});
