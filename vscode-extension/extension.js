const vscode = require("vscode");
const { spawn } = require("child_process");
const path = require("path");
const schema = require("./letter.schema.json");

const MARKDOWNLINT_DIRECTIVE = "<!-- markdownlint-disable-file MD013 MD041 -->";

let service;
let buffer = "";
let sequence = 0;
let previewPanel;
let lastPreview;
let output;
const pending = new Map();
const timers = new Map();
const latest = new Map();

function isLetter(document) {
  return document.uri.scheme === "file" && document.fileName.endsWith(".letter.md");
}

function startService() {
  if (service && !service.killed) return;
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
      let response;
      try {
        response = JSON.parse(line);
      } catch (error) {
        output.appendLine(`Invalid service response: ${error.message}: ${line}`);
        continue;
      }
      const callback = pending.get(response.id);
      if (callback) {
        pending.delete(response.id);
        clearTimeout(callback.timeout);
        callback.resolve(response);
      }
    }
  });
  service.stderr.setEncoding("utf8");
  service.stderr.on("data", message => output.append(`dinbrief: ${message}`));
  service.on("error", error => output.appendLine(`dinbrief service: ${error.message}`));
  service.on("close", (code, signal) => {
    for (const [id, callback] of pending.entries()) {
      clearTimeout(callback.timeout);
      const error = new Error(`dinbrief service stopped (${signal || code})`);
      error.requestId = id;
      callback.reject(error);
    }
    pending.clear();
    service = undefined;
  });
}

function request(document, render = false) {
  if (!service || service.killed) startService();
  const id = ++sequence;
  const uri = document.uri.toString();
  latest.set(uri, id);
  const payload = { id, uri: document.uri.toString(), text: document.getText(), render };
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      pending.delete(id);
      const error = new Error("dinbrief service request timed out");
      error.requestId = id;
      reject(error);
    }, 15000);
    pending.set(id, { resolve, reject, timeout });
    service.stdin.write(JSON.stringify(payload) + "\n", error => {
      if (!error) return;
      clearTimeout(timeout);
      pending.delete(id);
      error.requestId = id;
      reject(error);
    });
  });
}

function isCurrent(document, response) {
  return responseIsCurrent(latest.get(document.uri.toString()), response.id);
}

function responseIsCurrent(latestId, responseId) {
  return latestId === responseId;
}

function serviceDiagnostic(error) {
  return [{ severity: "error", code: "service", message: error.message }];
}

function publishServiceError(collection, status, document, error) {
  if (latest.get(document.uri.toString()) === error.requestId) {
    publish(collection, status, document, serviceDiagnostic(error));
  }
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
  const uri = document.uri.toString();
  clearTimeout(timers.get(uri));
  request(document, false)
    .then(response => {
      if (isCurrent(document, response)) publish(collection, status, document, response.diagnostics);
    })
    .catch(error => publishServiceError(collection, status, document, error));
  if (!vscode.workspace.getConfiguration("dinbrief").get("exactDiagnostics", true)) return;
  const delay = vscode.workspace.getConfiguration("dinbrief").get("renderDebounceMs", 350);
  timers.set(uri, setTimeout(() => {
    request(document, true)
      .then(response => {
        if (!isCurrent(document, response)) return;
        publish(collection, status, document, response.diagnostics);
        if (response.preview) {
          lastPreview = response.preview;
          if (previewPanel) updatePreview(previewPanel, response.preview);
        }
      })
      .catch(error => publishServiceError(collection, status, document, error));
  }, delay));
}

function runTask(command) {
  const editor = vscode.window.activeTextEditor;
  if (!editor || !isLetter(editor.document)) return;
  const executable = vscode.workspace.getConfiguration("dinbrief").get("executable", "dinbrief");
  const execution = new vscode.ProcessExecution(executable, [command, editor.document.fileName]);
  const definition = { type: "dinbrief", command };
  const scope = vscode.workspace.getWorkspaceFolder(editor.document.uri) || vscode.TaskScope.Global;
  const task = new vscode.Task(
    definition,
    scope,
    `DIN-Brief: ${command}`,
    "dinbrief",
    execution
  );
  vscode.tasks.executeTask(task);
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
    try {
      const response = await request(editor.document, true);
      if (isCurrent(editor.document, response) && response.preview) lastPreview = response.preview;
    } catch (error) {
      vscode.window.showErrorMessage(`dinbrief preview: ${error.message}`);
      return;
    }
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

function markdownlintInsertion(document) {
  const text = document.getText();
  if (text.includes(MARKDOWNLINT_DIRECTIVE)) return undefined;
  const frontmatter = /^---[ \t]*\r?\n[\s\S]*?\r?\n---[ \t]*/.exec(text);
  if (!frontmatter) return undefined;
  return {
    position: document.positionAt(frontmatter[0].length),
    text: `\n\n${MARKDOWNLINT_DIRECTIVE}`
  };
}

function markdownlintAction(document) {
  const insertion = markdownlintInsertion(document);
  if (!insertion) return [];
  const action = new vscode.CodeAction(
    "Use letter-friendly Markdown lint rules",
    vscode.CodeActionKind.QuickFix
  );
  action.edit = new vscode.WorkspaceEdit();
  action.edit.insert(document.uri, insertion.position, insertion.text);
  return [action];
}

function letterCodeActions(document) {
  return [...missingFieldAction(document), ...markdownlintAction(document)];
}

async function configureMarkdownlint() {
  const editor = vscode.window.activeTextEditor;
  if (!editor || !isLetter(editor.document)) return;
  const insertion = markdownlintInsertion(editor.document);
  if (!insertion) {
    vscode.window.showInformationMessage("This letter already uses the letter-friendly Markdown lint profile.");
    return;
  }
  const edit = new vscode.WorkspaceEdit();
  edit.insert(editor.document.uri, insertion.position, insertion.text);
  await vscode.workspace.applyEdit(edit);
}

function activate(context) {
  const selector = { language: "markdown", pattern: "**/*.letter.md" };
  const diagnostics = vscode.languages.createDiagnosticCollection("dinbrief");
  const status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 50);
  output = vscode.window.createOutputChannel("dinbrief");
  status.command = "dinbrief.preview";
  context.subscriptions.push(
    diagnostics,
    status,
    output,
    vscode.workspace.onDidOpenTextDocument(document => schedule(diagnostics, status, document)),
    vscode.workspace.onDidChangeTextDocument(event => schedule(diagnostics, status, event.document)),
    vscode.workspace.onDidCloseTextDocument(document => {
      const uri = document.uri.toString();
      clearTimeout(timers.get(uri));
      timers.delete(uri);
      latest.delete(uri);
      diagnostics.delete(document.uri);
    }),
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
    vscode.languages.registerCodeActionsProvider(selector, { provideCodeActions: letterCodeActions }, { providedCodeActionKinds: [vscode.CodeActionKind.QuickFix] }),
    vscode.commands.registerCommand("dinbrief.check", () => runTask("check")),
    vscode.commands.registerCommand("dinbrief.render", () => runTask("render")),
    vscode.commands.registerCommand("dinbrief.open", () => runTask("open")),
    vscode.commands.registerCommand("dinbrief.configureMarkdownlint", configureMarkdownlint),
    vscode.commands.registerCommand("dinbrief.preview", () => showPreview(context))
  );
  vscode.workspace.textDocuments.forEach(document => schedule(diagnostics, status, document));
}

function deactivate() {
  if (service) service.kill();
}

module.exports = {
  activate,
  deactivate,
  _test: { completionItems, inFrontmatter, markdownlintInsertion, responseIsCurrent, yamlPath }
};
