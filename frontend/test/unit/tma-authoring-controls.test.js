import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { runInNewContext } from "node:vm";
import test from "node:test";
import React from "react";
import katex from "katex";
import { parse } from "espree";
import { transformWithOxc } from "vite";
import { formatSelection } from "../../src/features/tma/textFormatting.js";

const source = await readFile(
  new URL("../../src/features/tma/TmaQuestionEditor.jsx", import.meta.url),
  "utf8",
);
const ast = parse(source, {
  ecmaVersion: "latest",
  sourceType: "module",
  ecmaFeatures: { jsx: true },
  range: true,
});
const field = ast.body.find(
  (n) => n.declaration?.id?.name === "TextField",
).declaration;
const { code } = await transformWithOxc(
  source.slice(...field.range),
  "TextField.jsx",
  { jsx: { runtime: "classic" } },
);
function visit(node, fn) {
  if (!React.isValidElement(node)) return;
  fn(node);
  React.Children.forEach(node.props.children, (child) => visit(child, fn));
}

test("math picker inserts renderable matrices and determinants in answer fields", () => {
  for (const label of ["Matrix 2 × 2", "Matrix 3 × 3", "Determinant"]) {
    let value;
    const details = { open: true };
    const Field = runInNewContext(`${code}\nTextField`, {
      React,
      formatSelection,
      useRef: () => ({
        current: {
          selectionStart: 0,
          selectionEnd: 0,
          focus() {},
          setSelectionRange() {},
        },
      }),
      requestAnimationFrame: (fn) => fn(),
    });
    const tree = Field({
      label: "Option A",
      compact: true,
      value: "",
      onChange: (next) => {
        value = next;
      },
    });
    visit(tree, (node) => {
      if (node.type === "button" && node.props.children === label)
        node.props.onClick({ currentTarget: { closest: () => details } });
    });
    assert.ok(value?.includes("matrix}"));
    assert.equal(details.open, false);
    const html = katex.renderToString(value.slice(2, -2), {
      throwOnError: true,
    });
    assert.match(html, /mtable/);
  }
});

test("creation back actions use the dedicated leave dialog without browser confirmation", async () => {
  const page = await readFile(
    new URL("../../src/features/tma/TmaPage.jsx", import.meta.url),
    "utf8",
  );
  assert.doesNotMatch(page, /window\.confirm/);
  assert.match(page, /title="Leave question editor\?"/);
  assert.match(page, /Keep editing/);
  assert.match(page, /Leave without saving/);
  assert.doesNotMatch(
    page,
    /label: "Assignment images"|label: "Refresh assignment"|label: "AI assistant"/,
  );
});
