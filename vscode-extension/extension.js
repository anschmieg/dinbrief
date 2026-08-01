const vscode = require("vscode");
const { spawn } = require("child_process");

let service;
let buffer = "";
let sequence = 0;
const pending = new Map();
const timers = new Map();

function isLetter(document) {
  return document.uri.scheme === "file" && document.fileName.endsWith(".letter.md");
}

function startService() {
  const executable = vscode.workspace.getConfiguration("dinbrief").get("executable", "dinbrief");
  service = spawn(executable, ["serve", "--stdio"]);
  service.stdout.setEncoding("utf8");
  service.stdout.on("data", chunk => {
    buffer += chunk;
    let end;
    while ((end = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, end);
      buffer = buffer.slice(end + 1);
      if (!line) continue;
      const response = JSON.parse(line);
      const callback = pending.get(response.id);
      if (callback) {
        pending.delete(response.id);
        callback(response);
      }
    }
  });
  service.on("error", error => vscode.window.showErrorMessage(`dinbrief service: ${error.message}`));
}

function request(document, render = false) {
  if (!service || service.killed) startService();
  const id = ++sequence;
  service.stdin.write(JSON.stringify({ id, uri: document.uri.toString(), text: document.getText(), render }) + "\n");
  return new Promise(resolve => pending.set(id, resolve));
}

function lineForField(document, field) {
  if (!field) return 0;
  const match = new RegExp(`^\\s*${field.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}:`, "m").exec(document.getText());
  return match ? document.positionAt(match.index).line : 0;
}

function publish(collection, document, items) {
  const diagnostics = items.map(item => {
    const line = lineForField(document, item.field);
    const severity = item.severity === "error" ? vscode.DiagnosticSeverity.Error : item.severity === "warning" ? vscode.DiagnosticSeverity.Warning : vscode.DiagnosticSeverity.Information;
    const diagnostic = new vscode.Diagnostic(new vscode.Range(line, 0, line, document.lineAt(line).text.length), item.message, severity);
    diagnostic.code = item.provisional ? `${item.code} (provisional)` : item.code;
    diagnostic.source = "dinbrief";
    return diagnostic;
  });
  collection.set(document.uri, diagnostics);
}

function schedule(collection, document) {
  if (!isLetter(document)) return;
  clearTimeout(timers.get(document.uri.toString()));
  request(document, false).then(response => publish(collection, document, response.diagnostics));
  if (!vscode.workspace.getConfiguration("dinbrief").get("exactDiagnostics", true)) return;
  const delay = vscode.workspace.getConfiguration("dinbrief").get("renderDebounceMs", 350);
  timers.set(document.uri.toString(), setTimeout(() => {
    request(document, true).then(response => publish(collection, document, response.diagnostics));
  }, delay));
}

function runTerminal(command) {
  const editor = vscode.window.activeTextEditor;
  if (!editor || !isLetter(editor.document)) return;
  const terminal = vscode.window.createTerminal("dinbrief");
  terminal.show();
  const file = editor.document.fileName.replace(/'/g, "'\\''");
  terminal.sendText(`dinbrief ${command} '${file}'`);
}

const frontmatterFields = [
  ["format", "dinbrief/v1", "Source format version"],
  ["language", "de-DE", "BCP-47 document language"],
  ["sender", "personal", "Sender profile ID or inline sender"],
  ["recipient", "\n  name: Recipient Name\n  address:\n    street: Street 1\n    postal_code: \"12345\"\n    city: City\n    country: DE", "Postal recipient"],
  ["date", new Date().toISOString().slice(0, 10), "ISO letter date"],
  ["location", "Berlin", "Optional place shown before the localized date"],
  ["subject", "", "Printed subject"],
  ["salutation", "Sehr geehrte Damen und Herren,", "Explicit salutation"],
  ["closing", "Mit freundlichen Grüßen", "Explicit closing"],
  ["references", "\n  customer_number: \"\"", "Reference fields"],
  ["delivery", "\n  method: both", "print, email, or both"],
  ["layout", "\n  standard: din-5008\n  form: B\n  window_envelope: true", "Layout overrides"],
  ["tags", "[]", "Searchable archive tags"],
  ["attachments", "[]", "Attachment labels"]
];

function inFrontmatter(document, position) {
  const before = document.getText(new vscode.Range(0, 0, position.line, position.character));
  return (before.match(/^---\s*$/gm) || []).length === 1;
}

function activate(context) {
  const diagnostics = vscode.languages.createDiagnosticCollection("dinbrief");
  startService();
  context.subscriptions.push(
    diagnostics,
    vscode.workspace.onDidOpenTextDocument(document => schedule(diagnostics, document)),
    vscode.workspace.onDidChangeTextDocument(event => schedule(diagnostics, event.document)),
    vscode.languages.registerCompletionItemProvider(
      { language: "markdown", pattern: "**/*.letter.md" },
      {
        provideCompletionItems(document, position) {
          if (!inFrontmatter(document, position)) return [];
          return frontmatterFields.map(([name, value, detail]) => {
            const item = new vscode.CompletionItem(name, vscode.CompletionItemKind.Property);
            item.detail = detail;
            item.insertText = new vscode.SnippetString(`${name}: ${value}`);
            return item;
          });
        }
      },
      ":"
    ),
    vscode.commands.registerCommand("dinbrief.check", () => runTerminal("check")),
    vscode.commands.registerCommand("dinbrief.render", () => runTerminal("render")),
    vscode.commands.registerCommand("dinbrief.open", () => runTerminal("open")),
    vscode.commands.registerCommand("dinbrief.preview", async () => {
      const editor = vscode.window.activeTextEditor;
      if (!editor || !isLetter(editor.document)) return;
      const response = await request(editor.document, true);
      publish(diagnostics, editor.document, response.diagnostics);
      if (response.preview) await vscode.env.openExternal(vscode.Uri.file(response.preview));
    })
  );
  vscode.workspace.textDocuments.forEach(document => schedule(diagnostics, document));
}

function deactivate() {
  if (service) service.kill();
}

module.exports = { activate, deactivate };
