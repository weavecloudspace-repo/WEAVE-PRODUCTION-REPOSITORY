// Keep stored text intact. Normalize delimiters and common commands for display.
export function splitMathSegments(value) {
  const input = String(value || "");
  const pattern =
    /(\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\)|\$\$[\s\S]*?\$\$|\$[^\n$]+?\$|\\(?:dfrac|tfrac|frac)\{[^{}]*\}\{[^{}]*\}|\\sqrt(?:\[[^\]]+\])?\{[^{}]*\}|\\(?:pi|theta|alpha|beta|times|div|pm|leq|geq|neq|infty)\b)/g;
  const parts = [];
  let last = 0;
  for (const match of input.matchAll(pattern)) {
    if (match.index > last)
      parts.push({ text: input.slice(last, match.index), math: false });
    const raw = match[0];
    let text = raw;
    let display = false;
    if (raw.startsWith("\\[")) {
      text = raw.slice(2, -2);
      display = true;
    } else if (raw.startsWith("\\(")) text = raw.slice(2, -2);
    else if (raw.startsWith("$$")) {
      text = raw.slice(2, -2);
      display = true;
    } else if (raw.startsWith("$")) text = raw.slice(1, -1);
    const currency =
      raw.startsWith("$") &&
      !raw.startsWith("$$") &&
      !/[=+*/^_{}\\]|^[a-zA-Z]$/.test(text);
    parts.push({ text: currency ? raw : text, math: !currency, display });
    last = match.index + raw.length;
  }
  if (last < input.length) parts.push({ text: input.slice(last), math: false });
  return parts;
}
