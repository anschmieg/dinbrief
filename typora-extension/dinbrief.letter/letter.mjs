const delimiter = /^---+[ \t]*$/;
const letterFormat = /^(?:format|"format"|'format')[ \t]*:[ \t]*["']?dinbrief\//m;
const letterFields = /^(?:sender|recipient|salutation|closing):/gm;

export function snapshot(blocks) {
  const topLevel = blocks.filter((block) => block.depth === 0 || block.parent == null);
  const first = topLevel.find((block) => block.text?.trim());
  if (!first) return null;

  const original = first.text.replace(/\r\n?/g, "\n").trimEnd();
  const lines = original.split("\n");
  const hasDelimiters = delimiter.test(lines[0]);
  const end = hasDelimiters ? lines.findIndex((line, index) => index > 0 && delimiter.test(line)) : -1;
  const isFrontmatterBlock = /^(?:yaml|front[-_ ]?matter|properties)$/i.test(first.type);
  const yaml = hasDelimiters ? lines.slice(1, end < 0 ? undefined : end).join("\n") : original;
  if (!hasDelimiters && !isFrontmatterBlock) return null;
  const fields = new Set(yaml.match(letterFields));
  if (!letterFormat.test(yaml) && !(fields.has("recipient:") && fields.size > 1)) return null;

  const rawHeader = hasDelimiters ? original : `---\n${original}\n---`;
  const offset = hasDelimiters ? 0 : -1;
  const headerLines = rawHeader.split("\n");
  const locations = headerLines.map((_, line) => ({ block: first, line: line + offset }));
  const content = [...headerLines];
  for (const block of topLevel.slice(topLevel.indexOf(first) + 1)) {
    const text = block.text?.replace(/\r\n?/g, "\n").trimEnd();
    if (!text) continue;
    content.push("");
    locations.push(null);
    for (const [line, textLine] of text.split("\n").entries()) {
      content.push(textLine);
      locations.push({ block, line });
    }
  }
  return { text: content.join("\n"), locations };
}

export function revealTarget(document, range) {
  const start = document.locations[range.start.line];
  if (!start?.block.id) return null;
  const target = { blockId: start.block.id };
  const end = document.locations[range.end.line];
  if (start.line < 0 || end?.block !== start.block || end.line < start.line) return target;
  const lines = start.block.text.match(/[^\r\n]*(?:\r\n|\n|\r|$)/g);
  const offset = (line, column) => lines.slice(0, line).reduce((total, text) => total + text.length, 0) + column;
  if (start.line < lines.length && end.line < lines.length) {
    target.from = offset(start.line, range.start.character);
    target.to = offset(end.line, range.end.character);
  }
  return target;
}
