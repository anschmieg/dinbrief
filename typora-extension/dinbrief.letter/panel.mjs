import { revealTarget, snapshot } from "./letter.mjs";
import { LetterClient } from "./lsp.mjs";

const view = window.typora.view;
const status = document.querySelector("#status");
const issues = document.querySelector("#issues");
const retry = document.querySelector("#retry");
const labels = { 1: "Error", 2: "Warning", 3: "Info", 4: "Hint" };
let current;
let client;
let queue = Promise.resolve();
let generation = 0;
let deadline;
let disposed = false;

function fail(message) {
  clearTimeout(deadline);
  client?.dispose();
  client = undefined;
  queue = Promise.resolve();
  issues.replaceChildren();
  if (disposed || !current) return;
  status.textContent = `Could not validate this letter. ${message} Check that dinbrief[lsp] is installed and that the executable is configured in Settings → Extensions.`;
  retry.hidden = false;
}

function render(diagnostics, version) {
  if (!current || version !== generation || disposed || !retry.hidden) return;
  clearTimeout(deadline);
  status.textContent = diagnostics.length
    ? `${diagnostics.length} ${diagnostics.length === 1 ? "issue" : "issues"} found.`
    : "No issues found.";
  const items = diagnostics.map((issue) => {
    const item = document.createElement("li");
    const target = revealTarget(current, issue.range);
    const content = document.createElement(target ? "button" : "div");
    content.className = "issue";
    if (target) {
      content.type = "button";
      content.addEventListener("click", async () => {
        if (version !== generation) return;
        try {
          await view.reveal(target);
        } catch (error) {
          view.log(error.message);
          if (version === generation) status.textContent = "Typora could not select that location. Check the field named in the issue.";
        }
      });
    }
    const severity = document.createElement("span");
    severity.className = "severity";
    severity.textContent = labels[issue.severity] ?? "Info";
    content.append(severity, issue.message);
    item.append(content);
    return item;
  });
  issues.replaceChildren(...items);
}

function validate(next) {
  current = next;
  const version = ++generation;
  issues.replaceChildren();
  retry.hidden = true;
  clearTimeout(deadline);
  status.textContent = next ? "Checking letter…" : "Open a letter with a dinbrief format field to check it.";
  if (next) {
    deadline = setTimeout(() => {
      if (version === generation) fail("The language server did not respond in time.");
    }, 10000);
  }
  queue = queue.then(async () => {
    if (version !== generation || disposed || !retry.hidden) return;
    if (!next) {
      client?.dispose();
      client = undefined;
      return;
    }
    if (!client) {
      const settings = await view.settings();
      if (version !== generation || disposed || !retry.hidden) return;
      const executable = settings.executable?.trim() || "dinbrief";
      const process = await view.process.spawn(executable, ["lsp"], { name: "DIN Letter language server" });
      if (version !== generation || disposed || !retry.hidden) {
        await process.kill();
        return;
      }
      client = new LetterClient(process, render, fail);
    }
    if (version === generation) await client.update(next.text, version);
  }).catch((error) => {
    if (version === generation && retry.hidden) fail(error.message);
  });
}

view.onDocument(({ blocks }) => validate(snapshot(blocks)));
retry.addEventListener("click", () => validate(current));
window.addEventListener("pagehide", () => {
  disposed = true;
  clearTimeout(deadline);
  client?.dispose();
});
