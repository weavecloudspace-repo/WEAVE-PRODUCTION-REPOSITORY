import katex from "katex";
import "katex/dist/katex.min.css";
import { splitMathSegments } from "./mathText.js";

// CBT's plain-text inline conventions; React escapes all non-math content.
function formatted(text) {
  return text
    .split(
      /(\*\*[^*]+\*\*|__[^_]+__|\*[^*]+\*|\^[^^]+\^|\[[^\]]+\]\(https?:\/\/[^)]+\))/g,
    )
    .map((part, i) => {
      if (part.length > 4 && part.startsWith("**") && part.endsWith("**"))
        return <strong key={i}>{part.slice(2, -2)}</strong>;
      if (part.length > 4 && part.startsWith("__") && part.endsWith("__"))
        return <u key={i}>{part.slice(2, -2)}</u>;
      if (part.length > 2 && part.startsWith("*") && part.endsWith("*"))
        return <em key={i}>{part.slice(1, -1)}</em>;
      if (part.length > 2 && part.startsWith("^") && part.endsWith("^"))
        return <sup key={i}>{part.slice(1, -1)}</sup>;
      const link = part.match(/^\[([^\]]+)\]\((https?:\/\/[^)]+)\)$/);
      if (link)
        return (
          <a
            className="text-primary underline"
            key={i}
            href={link[2]}
            target="_blank"
            rel="noreferrer"
          >
            {link[1]}
          </a>
        );
      return <span key={i}>{part}</span>;
    });
}

export default function MathText({ children }) {
  return (
    <span className="block max-w-full overflow-x-auto whitespace-pre-wrap break-words">
      {splitMathSegments(children).map((part, index) =>
        part.math ? (
          <span
            key={index}
            dangerouslySetInnerHTML={{
              __html: katex.renderToString(part.text, {
                throwOnError: false,
                trust: false,
                strict: "ignore",
                displayMode: part.display,
                maxExpand: 200,
                maxSize: 20,
              }),
            }}
          />
        ) : (
          <span key={index}>{formatted(part.text)}</span>
        ),
      )}
    </span>
  );
}
