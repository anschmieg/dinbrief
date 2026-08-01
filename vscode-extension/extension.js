const vscode = require("vscode");
const { spawn } = require("child_process");
const path = require("path");
const schema = require("./letter.schema.json");

let service;
let buffer = "";
let sequence = 0;
let previewPanel;
let lastPreview;
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
  service.stderr.setEncoding("utf8");
  service.stderr.on("data", message => console.error(`dinbrief: ${message}`));
  service.on("error", error => vscode.window.showErrorMessage(`dinbrief service: ${error.message}`));
}

function request(document, render = false) {
  if (!service || service.killed) startService();
  const id = ++sequence;
  const payload = { id, uri: document.uri.toString(), text: document.getText(), render };
  service.stdin.write(JSON.stringify(payload) + "\n");
  return new Promise(resolve => pending.set(id, resolve));
}

function lineForField(document, field) {
  if (!field) return 0;
  const escaped = field.split(".").at(-1).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = new RegExp(`^\\s*${escaped}:`, "m").exec(document.getText());
  return match ? document.positionAt(match.index).line : 0;
}

function publish(collection, status, document, items) {
  const diagnostics = items.map(item => {
    const line = lineForField(document, item.field);
    const severity = item.severity === "error"
      ? vscode.DiagnosticSeverity.Error
      : item.severity === "warning"
        ? vscode.DiagnosticSeverity.Warning
        : vscode.DiagnosticSeverity.Information;
    const range = new vscode.Range(line, 0, line, document.lineAt(line).text.length);
    const diagnostic = new vscode.Diagnostic(range, item.message, severity);
    diagnostic.code = item.provisional ? `${item.code} (provisional)` : item.code;
    diagnostic.source = "dinbrief";
    return diagnostic;
  });
  collection.set(document.uri, diagnostics);
  const errors = diagnostics.filter(item => item.severity === vscode.DiagnosticSeverity.Error).length;
  const warnings = diagnostics.filter(item => item.severity === vscode.DiagnosticSeverity.Warning).length;
  status.text = errors ? `$(error) dinbrief ${errors}` : warnings ? `$(warning) dinbrief ${warnings}` : "$(check) dinbrief";
  status.tooltip = errors || warnings ? `${errors} errors, ${warnings} warnings` : "Letter is valid";
  status.show();
}

function schedule(collection, status, document) {
  if (!isLetter(document)) return;
  clearTimeout(timers.get(document.uri.toString()));
  request(document, false).then(response => publish(collection, status, document, response.diagnostics));
  if (!vscode.workspace.getConfiguration("dinbrief").get("exactDiagnostics", true)) return;
  const delay = vscode.workspace.getConfiguration("dinbrief").get("renderDebounceMs", 350);
  timers.set(document.uri.toString(), setTimeout(() => {
    request(document, true).then(response => {
      publish(collection, status, document, response.diagnostics);
      if (response.preview) {
        lastPreview = response.preview;
        if (previewPanel) updatePreview(previewPanel, response.preview);
      }
    });
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

function inFrontmatter(document, position) {
  const before = document.getText(new vscode.Range(0, 0, position.line, position.character));
  return (before.match(/^---\s*$/gm) || []).length === 1;
}

function resolveSchema(node) {
  if (!node) return {};
  if (node.$ref?.startsWith("#/$defs/")) return schema.$defs[node.$ref.split("/").at(-1)] || {};
  if (node.oneOf) return resolveSchema(node.oneOf.find(entry => entry.$ref) || node.oneOf[0]);
  return node;
}

function yamlPath(document, position) {
  const stack = [];
  for (let line = 1; line < position.line; line += 1) {
    const text = document.lineAt(line).text;
    const match = /^(\s*)([\w-]+):(?:\s.*)?$/.exec(text);
    if (!match) continue;
    const indent = match[1].length;
    while (stack.length && stack.at(-1).indent >= indent) stack.pop();
    if (text.trimEnd().endsWith(":")) stack.push({ indent, key: match[2] });
  }
  const currentIndent = document.lineAt(position.line).text.match(/^\s*/)[0].length;
  while (stack.length && stack.at(-1).indent >= currentIndent) stack.pop();
  return stack.map(item => item.key);
}

function schemaAtPath(keys) {
  let current = schema;
  for (const key of keys) current = resolveSchema(resolveSchema(current).properties?.[key]);
  return resolveSchema(current);
}

function valueSnippet(name, node) {
  const resolved = resolveSchema(node);
  if (resolved.const !== undefined) return `${name}: ${resolved.const}`;
  if (resolved.default !== undefined) return `${name}: ${resolved.default}`;
  if (resolved.enum) return `${name}: \${1|${resolved.enum.join(",")}|}`;
  if (resolved.type === "object" || resolved.properties) return `${name}:\n  \${1}`;
  if (resolved.type === "array") return `${name}: [\${1}]`;
  if (resolved.type === "boolean") return `${name}: \${1|true,false|}`;
  return `${name}: \${1}`;
}

function completionItems(document, position) {
  if (!inFrontmatter(document, position)) return [];
  const line = document.lineAt(position.line).text;
  const valueMatch = /^\s*([\w-]+):\s*[^#]*$/.exec(line);
  const parent = schemaAtPath(yamlPath(document, position));
  if (valueMatch) {
    const node = resolveSchema(parent.properties?.[valueMatch[1]]);
    const values = node.enum || node.examples || (node.const !== undefined ? [node.const] : []);
    return values.map(value => new vscode.CompletionItem(String(value), vscode.CompletionItemKind.Value));
  }
  return Object.entries(parent.properties || {}).map(([name, node]) => {
    const item = new vscode.CompletionItem(name, vscode.CompletionItemKind.Property);
    item.detail = resolveSchema(node).description || schema.title;
    item.insertText = new vscode.SnippetString(valueSnippet(name, node));
    return item;
  });
}

function updatePreview(panel, previewPath) {
  const fileUri = panel.webview.asWebviewUri(vscode.Uri.file(previewPath));
  panel.webview.html = `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src ${panel.webview.cspSource}; style-src 'unsafe-inline';"><style>body{margin:0;padding:18px;background:#303030;display:flex;justify-content:center}img{width:min(100%,900px);height:auto;box-shadow:0 4px 22px #0008;background:white}</style></head><body><img src="${fileUri}" alt="dinbrief preview"></body></html>`;
}

async function showPreview(context) {
  const editor = vscode.window.activeTextEditor;
  if (editor && isLetter(editor.document)) {
    const response = await request(editor.document, true);
    if (response.preview) lastPreview = response.preview;
  }
  if (!lastPreview) return;
  if (!previewPanel) {
    const cacheRoot = vscode.Uri.file(path.dirname(lastPreview));
    previewPanel = vscode.window.createWebviewPanel("dinbriefPreview", "DIN-Brief Vorschau", vscode.ViewColumn.Beside, { enableScripts: false, localResourceRoots: [cacheRoot] });
    previewPanel.onDidDispose(() => { previewPanel = undefined; }, null, context.subscriptions);
  }
  updatePreview(previewPanel, lastPreview);
}

function missingFieldAction(document) {
  const required = schema.required.filter(name => !new RegExp(`^${name}:`, "m").test(document.getText()));
  if (!required.length) return [];
  const closing = document.getText().indexOf("\n---", 4);
  if (closing < 0) return [];
  const action = new vscode.CodeAction("Add missing required letter fields", vscode.CodeActionKind.QuickFix);
  const lines = required.map(name => valueSnippet(name, schema.properties[name]).replace(/\$\{1[^}]*\}/g, "TODO"));
  action.edit = new vscode.WorkspaceEdit();
  action.edit.insert(document.uri, document.positionAt(closing), `\n${lines.join("\n")}`);
  return [action];
}

function activate(context) {
  const selector = { language: "markdown", pattern: "**/*.letter.md" };
  const diagnostics = vscode.languages.createDiagnosticCollection("dinbrief");
  const status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 50);
  status.command = "dinbrief.preview";
  startService();
  context.subscriptions.push(
    diagnostics,
    status,
    vscode.workspace.onDidOpenTextDocument(document => schedule(diagnostics, status, document)),
    vscode.workspace.onDidChangeTextDocument(event => schedule(diagnostics, status, event.document)),
    vscode.languages.registerCompletionItemProvider(selector, { provideCompletionItems: completionItems }, ":", " "),
    vscode.languages.registerHoverProvider(selector, {
      provideHover(document, position) {
        if (!inFrontmatter(document, position)) return undefined;
        const range = document.getWordRangeAtPosition(position);
        const word = range ? document.getText(range) : "";
        const parent = schemaAtPath(yamlPath(document, position));
        const description = resolveSchema(parent.properties?.[word]).description;
        return description ? new vscode.Hover(description, range) : undefined;
      }
    }),
    vscode.languages.registerCodeActionsProvider(selector, { provideCodeActions: missingFieldAction }, { providedCodeActionKinds: [vscode.CodeActionKind.QuickFix] }),
    vscode.commands.registerCommand("dinbrief.check", () => runTerminal("check")),
    vscode.commands.registerCommand("dinbrief.render", () => runTerminal("render")),
    vscode.commands.registerCommand("dinbrief.open", () => runTerminal("open")),
    vscode.commands.registerCommand("dinbrief.preview", () => showPreview(context))
  );
  vscode.workspace.textDocuments.forEach(document => schedule(diagnostics, status, document));
}

function deactivate() {
  if (service) service.kill();
}

module.exports = { activate, deactivate };
