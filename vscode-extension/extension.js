const vscode = require("vscode");
const { spawn } = require("child_process");
const path = require("path");
const schema = require("./letter.schema.json");

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
  if (field === "subject") {
    const text = document.getText();
    const frontmatter = /^---[ \t]*\r?\n[\s\S]*?\r?\n---[ \t]*(?:\r?\n)?/.exec(text);
    const contentOffset = frontmatter?.[0].length || 0;
    const heading = /^#\s+/m.exec(text.slice(contentOffset));
    if (heading) return document.positionAt(contentOffset + heading.index).line;
  }
  const wanted = field.split(".");
  const stack = [];
  let closingLine = 0;
  for (let line = 1; line < document.lineCount; line += 1) {
    const text = document.lineAt(line).text;
    if (/^---\s*$/.test(text)) {
      closingLine = line;
      break;
    }
    const match = /^(\s*)([\w-]+):(?:\s.*)?$/.exec(text);
    if (!match) continue;
    const indent = match[1].length;
    while (stack.length && stack.at(-1).indent >= indent) stack.pop();
    const current = [...stack.map(item => item.key), match[2]];
    if (current.join(".") === wanted.join(".")) return line;
    if (text.trimEnd().endsWith(":")) stack.push({ indent, key: match[2], line });
  }
  for (let length = wanted.length - 1; length > 0; length -= 1) {
    const parent = wanted.slice(0, length).join(".");
    const line = lineForField(document, parent);
    if (line > 0) return line;
  }
  return closingLine;
}

function publish(collection, status, document, items) {
  const diagnostics = items.map(item => {
    const line = Number.isInteger(item.line) ? Math.min(item.line, document.lineCount - 1) : lineForField(document, item.field);
    const column = Number.isInteger(item.column) ? Math.min(item.column, document.lineAt(line).text.length) : 0;
    const severity = item.severity === "error"
      ? vscode.DiagnosticSeverity.Error
      : item.severity === "warning"
        ? vscode.DiagnosticSeverity.Warning
        : vscode.DiagnosticSeverity.Information;
    const range = new vscode.Range(line, column, line, Math.max(column, document.lineAt(line).text.length));
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

function lineEnding(document) {
  return document.getText().includes("\r\n") ? "\r\n" : "\n";
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

function missingFieldAction(document, diagnostic) {
  if (diagnostic.source !== "dinbrief" || diagnostic.code !== "field-missing") return [];
  const field = /`([^`]+)`/.exec(diagnostic.message)?.[1];
  const parts = field?.split(".") || [];
  if (!parts.length) return [];
  const name = parts.at(-1);
  const node = schemaAtPath(parts.slice(0, -1)).properties?.[name];
  if (!node) return [];
  const value = valueSnippet(name, node).replace(/\$\{1[^}]*\}/g, "TODO");
  const action = new vscode.CodeAction(`Add required field ${field}`, vscode.CodeActionKind.QuickFix);
  action.diagnostics = [diagnostic];
  action.edit = new vscode.WorkspaceEdit();
  if (parts.length === 1) {
    const frontmatter = /^---[ \t]*\r?\n[\s\S]*?\r?\n---[ \t]*/.exec(document.getText());
    if (!frontmatter) return [];
    const closing = frontmatter.index + frontmatter[0].length;
    action.edit.insert(document.uri, document.positionAt(closing), `${lineEnding(document)}${value}`);
    return [action];
  }
  const parentPath = parts.slice(0, -1);
  const parentLine = lineForField(document, parentPath.join("."));
  if (parentLine <= 0) return [];
  const parentSchema = schemaAtPath(parentPath);
  if (!parentSchema.properties?.[name]) return [];
  const parentText = document.lineAt(parentLine).text;
  if (!parentText.trimEnd().endsWith(":")) return [];
  const indent = parentText.match(/^\s*/)[0].length + 2;
  action.edit.insert(document.uri, new vscode.Position(parentLine, parentText.length), `${lineEnding(document)}${" ".repeat(indent)}${value}`);
  return [action];
}

function subjectHeadingEdit(document) {
  const text = document.getText();
  const frontmatter = /^---[ \t]*\r?\n[\s\S]*?\r?\n---[ \t]*(?:\r?\n)?/.exec(text);
  if (!frontmatter) return undefined;
  const contentOffset = frontmatter[0].length;
  const remainder = text.slice(contentOffset);
  if (/^#\s+\S/m.test(remainder)) return undefined;
  const firstContent = /\S/.exec(remainder);
  if (firstContent) {
    const offset = contentOffset + firstContent.index;
    return { position: document.positionAt(offset), text: "# " };
  }
  return {
    position: document.positionAt(contentOffset),
    text: `${lineEnding(document)}# Subject${lineEnding(document)}`
  };
}

function subjectHeadingAction(document) {
  const insertion = subjectHeadingEdit(document);
  if (!insertion) return [];
  const action = new vscode.CodeAction("Use the first content line as the letter subject", vscode.CodeActionKind.QuickFix);
  action.edit = new vscode.WorkspaceEdit();
  action.edit.insert(document.uri, insertion.position, insertion.text);
  return [action];
}

function letterCodeActions(document, context) {
  const missing = context.diagnostics.flatMap(diagnostic => missingFieldAction(document, diagnostic));
  return [...subjectHeadingAction(document), ...missing];
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
  _test: { completionItems, inFrontmatter, lineForField, missingFieldAction, responseIsCurrent, subjectHeadingEdit, yamlPath }
};
