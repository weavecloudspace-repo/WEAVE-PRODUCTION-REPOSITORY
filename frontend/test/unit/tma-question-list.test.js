import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { runInNewContext } from "node:vm";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { transformWithOxc } from "vite";

const source = await readFile(
  new URL("../../src/features/tma/TmaQuestionList.jsx", import.meta.url),
  "utf8",
);
const { code } = await transformWithOxc(
  source
    .slice(source.indexOf("export default function"))
    .replace("export default ", ""),
  "TmaQuestionList.jsx",
  { jsx: { runtime: "classic" } },
);
const List = runInNewContext(`${code}\nTmaQuestionList`, {
  React,
  Link: ({ to, ...props }) => React.createElement("a", { href: to, ...props }),
  Button: (props) => {
    const buttonProps = { ...props };
    delete buttonProps.variant;
    return React.createElement("button", buttonProps);
  },
  ArrowUpRight: () => null,
  BookOpen: () => null,
  Image: () => null,
  Pencil: () => null,
  Trash2: () => null,
});
const question = {
  id: "q1",
  question_text: "Solve <script>alert(1)</script>",
  options: [
    {
      id: "o1",
      option_text: "Answer should only appear in preview",
      image_asset_id: "image",
    },
  ],
};
function render(props = {}) {
  return renderToStaticMarkup(
    React.createElement(List, {
      questions: [question],
      assignmentPath: "/teacher/tma/a1",
      editable: true,
      canEdit: () => true,
      ...props,
    }),
  );
}

test("compact rows link to the dedicated preview without expanding answer options", () => {
  const html = render();
  assert.match(html, /href="\/teacher\/tma\/a1\/questions\/q1"/);
  assert.match(html, /Includes media/);
  assert.match(html, /&lt;script&gt;/);
  assert.doesNotMatch(html, /<script>|Answer should only appear in preview/);
});

test("edit and delete are exposed only for editable questions the actor can manage", () => {
  assert.match(render(), /Edit question 1/);
  assert.match(render(), /Delete question 1/);
  for (const props of [{ editable: false }, { canEdit: () => false }]) {
    const html = render(props);
    assert.doesNotMatch(html, /Edit question 1|Delete question 1/);
    assert.match(html, /Preview question 1/);
  }
  assert.equal((render({ busy: true }).match(/disabled=""/g) || []).length, 2);
});

test("edit and delete callbacks receive the selected saved question", () => {
  const calls = [];
  const tree = List({
    questions: [question],
    assignmentPath: "/admin/tma/a1",
    editable: true,
    canEdit: () => true,
    onEdit: (q) => calls.push(["edit", q]),
    onDelete: (q) => calls.push(["delete", q]),
  });
  function visit(node) {
    if (!React.isValidElement(node)) return;
    if (
      node.props["aria-label"] === "Edit question 1" ||
      node.props["aria-label"] === "Delete question 1"
    ) {
      node.props.onClick();
    }
    React.Children.forEach(node.props.children, visit);
  }
  visit(tree);
  assert.deepEqual(calls, [
    ["edit", question],
    ["delete", question],
  ]);
});
