import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { runInNewContext } from "node:vm";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { transformWithOxc } from "vite";

const source = await readFile(
  new URL("../../src/features/tma/TmaQuestionPreviewPage.jsx", import.meta.url),
  "utf8",
);
const { code } = await transformWithOxc(
  source.slice(source.indexOf("function QuestionPreview(")),
  "QuestionPreview.jsx",
  { jsx: { runtime: "classic" } },
);
function render({
  questions = null,
  questionId = "q1",
  error = "",
  role = "teacher",
} = {}) {
  let cursor = 0;
  const state = [questions, error, 0];
  const Preview = runInNewContext(`${code}\nQuestionPreview`, {
    React,
    useToast: () => ({ showError() {} }),
    useState: () => [state[cursor++], () => {}],
    useRef: () => ({ current: null }),
    useEffect: () => {},
    Link: ({ to, ...props }) =>
      React.createElement("a", { href: to, ...props }),
    Button: ({ children }) => React.createElement("button", null, children),
    ArrowLeft: () => null,
    ChevronLeft: () => null,
    ChevronRight: () => null,
    MathText: ({ children }) => React.createElement("span", null, children),
    TmaAssetImage: ({ alt }) => React.createElement("span", null, alt),
  });
  return renderToStaticMarkup(
    React.createElement(Preview, { role, assignmentId: "a1", questionId }),
  );
}
const questions = ["q1", "q2", "q3"].map((id) => ({
  id,
  question_text: "Saved question",
  image_asset_id: "image",
  options: [
    { id: "a", option_text: "First answer", is_correct: false },
    {
      id: "b",
      option_text: "Second answer",
      is_correct: true,
      image_asset_id: "option-image",
    },
  ],
}));

test("dedicated preview shows complete options, media, answer key, and scoped navigation", () => {
  for (const role of ["admin", "teacher"]) {
    const html = render({ questions, questionId: "q2", role });
    assert.match(html, /Question 2 of 3/);
    assert.match(html, /First answer/);
    assert.match(html, /Second answer/);
    assert.match(html, /Question illustration/);
    assert.match(html, /Option 2/);
    assert.match(html, /Answer key: <\/strong>B/);
    assert.ok(html.includes(`href="/${role}/tma/a1/questions/q1"`));
    assert.ok(html.includes(`href="/${role}/tma/a1/questions/q3"`));
    assert.ok(html.includes(`href="/${role}/tma/a1"`));
  }
});

test("preview handles loading, missing questions, failed loads, and navigation boundaries", () => {
  assert.match(render(), /Loading question preview/);
  assert.match(render({ questions: [] }), /no longer available/);
  assert.match(render({ error: "Unavailable" }), /Try again/);
  assert.doesNotMatch(
    render({ questions, questionId: "q1" }),
    /Previous question/,
  );
  assert.doesNotMatch(render({ questions, questionId: "q3" }), /Next question/);
});
