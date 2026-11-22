const encoder = new TextEncoder();
const decoder = new TextDecoder();
const maxMessage = 8 * 1024 * 1024;

export class LspFrames {
  bytes = new Uint8Array();

  push(chunk) {
    const bytes = new Uint8Array(this.bytes.length + chunk.length);
    bytes.set(this.bytes);
    bytes.set(chunk, this.bytes.length);
    this.bytes = bytes;
    const messages = [];
    while (this.bytes.length) {
      const header = decoder.decode(this.bytes.subarray(0, 4096));
      const boundary = header.indexOf("\r\n\r\n");
      if (boundary < 0) {
        if (this.bytes.length >= 4096) throw new Error("Invalid language server header.");
        break;
      }
      const match = /^Content-Length: *([0-9]+)\r?$/im.exec(header.slice(0, boundary));
      const length = Number(match?.[1]);
      if (!Number.isSafeInteger(length) || length < 1 || length > maxMessage) {
        throw new Error("Invalid language server response length.");
      }
      const start = boundary + 4;
      if (this.bytes.length < start + length) break;
      messages.push(JSON.parse(decoder.decode(this.bytes.subarray(start, start + length))));
      this.bytes = this.bytes.slice(start + length);
    }
    return messages;
  }
}

export function frame(message) {
  const body = JSON.stringify({ jsonrpc: "2.0", ...message });
  return `Content-Length: ${encoder.encode(body).length}\r\n\r\n${body}`;
}

export class LetterClient {
  constructor(process, diagnostics, failed) {
    this.process = process;
    this.diagnostics = diagnostics;
    this.failed = failed;
    this.version = 0;
    this.uri = "file:///dinbrief-typora.letter.md";
    this.open = false;
    this.stderr = "";
    this.frames = new LspFrames();
    this.ready = new Promise((resolve) => { this.resolve = resolve; });
    this.disposers = [
      process.onData((bytes, stream) => this.receive(bytes, stream)),
      process.onExit(({ code }) => this.fail(this.stderr.trim() || `dinbrief exited (${code ?? "no status"}).`)),
    ];
    void this.send({ id: 1, method: "initialize", params: { processId: null, capabilities: {} } });
  }

  send(message) {
    return Promise.resolve().then(() => {
      if (!this.closed) return this.process.write(frame(message));
    }).catch((error) => this.fail(error.message));
  }

  receive(bytes, stream) {
    if (this.closed) return;
    if (stream === "stderr") {
      this.stderr = (this.stderr + decoder.decode(bytes)).slice(-2000);
      return;
    }
    try {
      for (const message of this.frames.push(bytes)) {
        if (message.id === 1) {
          if (message.error) throw new Error(message.error.message);
          void this.send({ method: "initialized", params: {} }).then(() => this.resolve());
        } else if (message.method === "textDocument/publishDiagnostics") {
          const { uri, version, diagnostics } = message.params;
          if (this.open && uri === this.uri && version === this.version) this.diagnostics(diagnostics, version);
        }
      }
    } catch (error) {
      this.fail(error.message);
    }
  }

  async update(text, version) {
    await this.ready;
    if (this.closed) return;
    this.version = version;
    if (!this.open) {
      this.open = true;
      await this.send({ method: "textDocument/didOpen", params: {
        textDocument: { uri: this.uri, languageId: "markdown", version, text },
      } });
    } else {
      await this.send({ method: "textDocument/didChange", params: {
        textDocument: { uri: this.uri, version }, contentChanges: [{ text }],
      } });
    }
  }

  fail(message) {
    if (this.closed) return;
    this.dispose();
    this.failed(message);
  }

  dispose() {
    if (this.closed) return;
    this.closed = true;
    this.resolve();
    for (const dispose of this.disposers) dispose?.();
    void this.process.kill().catch(() => {});
  }
}
