class Range {
  constructor(startLine, startCharacter, endLine, endCharacter) {
    this.start = { line: startLine, character: startCharacter };
    this.end = { line: endLine, character: endCharacter };
  }
}

class Position {
  constructor(line, character) {
    this.line = line;
    this.character = character;
  }
}

class CodeAction {
  constructor(title, kind) {
    this.title = title;
    this.kind = kind;
  }
}

class WorkspaceEdit {
  constructor() {
    this.insertions = [];
  }

  insert(uri, position, text) {
    this.insertions.push({ uri, position, text });
  }
}

class CompletionItem {
  constructor(label, kind) {
    this.label = label;
    this.kind = kind;
  }
}

class SnippetString {
  constructor(value) {
    this.value = value;
  }
}

module.exports = {
  CodeAction,
  CodeActionKind: { QuickFix: "quickfix" },
  CompletionItem,
  CompletionItemKind: { Property: 1, Value: 2 },
  Position,
  Range,
  SnippetString,
  WorkspaceEdit
};
