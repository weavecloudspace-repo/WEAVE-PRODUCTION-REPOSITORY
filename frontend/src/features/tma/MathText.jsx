import katex from "katex";
import "katex/dist/katex.min.css";
import { splitMathSegments } from "./mathText.js";

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
          <span key={index}>{part.text}</span>
        ),
      )}
    </span>
  );
}
