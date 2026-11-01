import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { runInNewContext } from "node:vm";
import test from "node:test";
import * as React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import katex from "katex";
import { parse } from "espree";
import { transformWithOxc } from "vite";
import { splitMathSegments } from "../../src/features/tma/mathText.js";

const source = await readFile(
  new URL("../../src/features/tma/MathText.jsx", import.meta.url),
  "utf8",
);
const ast = parse(source, {
  ecmaVersion: "latest",
  sourceType: "module",
  ecmaFeatures: { jsx: true },
  range: true,
});
const functions = ast.body
  .filter(
    (n) =>
      n.type === "FunctionDeclaration" || n.type === "ExportDefaultDeclaration",
  )
  .map((n) => source.slice(...(n.declaration || n).range))
  .join("\n");
const { code } = await transformWithOxc(functions, "MathText.jsx", {
  jsx: { runtime: "classic" },
});
const MathText = runInNewContext(code + "\nMathText", {
  React,
  katex,
  splitMathSegments,
});
const render = (children) =>
  renderToStaticMarkup(React.createElement(MathText, { children }));

test("the actual TMA renderer typesets fractions, roots and powers with KaTeX", () => {
  const html = render("\\(\\frac{1}{2} + \\sqrt{x} + x^2\\)");
  for (const element of ["mfrac", "msqrt", "msup"])
    assert.match(html, new RegExp("<" + element + ">"));
  assert.match(html, /katex-html/);
});

test("Unicode stays readable and untrusted text or math cannot inject executable links", () => {
  const text = render("π × 2 ≤ √9 <img src=x onerror=alert(1)>");
  assert.match(text, /π × 2 ≤ √9/);
  assert.match(text, /&lt;img/);
  assert.doesNotMatch(text, /<img/);
  assert.doesNotMatch(
    render("\\(\\href{javascript:alert(1)}{x}\\)"),
    /href="javascript:/,
  );
});
