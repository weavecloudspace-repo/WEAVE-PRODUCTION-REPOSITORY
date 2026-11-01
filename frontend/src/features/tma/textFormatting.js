// Same plain-text formatting conventions as the CBT question builder.
export function formatSelection(value, start, end, kind) {
  const selected = value.slice(start, end);
  const inline = {
    bold: ["**", "**", "bold text"],
    italic: ["*", "*", "italic text"],
    underline: ["__", "__", "underlined text"],
    superscript: ["^", "^", "superscript"],
  };
  let replacement;
  if (inline[kind]) {
    const [before, after, fallback] = inline[kind];
    replacement = before + (selected || fallback) + after;
  } else if (kind === "link")
    replacement = `[${selected || "link text"}](https://)`;
  else if (kind === "bullet" || kind === "number")
    replacement = (selected || "List item")
      .split("\n")
      .map((line, i) => `${kind === "number" ? `${i + 1}.` : "-"} ${line}`)
      .join("\n");
  else replacement = kind;
  return {
    value: value.slice(0, start) + replacement + value.slice(end),
    start,
    end: start + replacement.length,
  };
}
