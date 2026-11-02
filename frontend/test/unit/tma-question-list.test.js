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
  source.slice(source.indexOf("export default function")).replace("export default ", ""),
  "TmaQuestionList.jsx",
  { jsx: { runtime: "classic" } },
);
const Icon = () => null;
let stateUpdates = [];
const List = runInNewContext(`${code}\nTmaQuestionList`, {
  React,
  useState: (initial) => [initial, (value) => stateUpdates.push(value)],
  useEffect: () => {},
  Link: ({ to, ...props }) => React.createElement("a", { href: to, ...props }),
  Button: (props) => {
    const buttonProps = { ...props };
    delete buttonProps.variant;
    delete buttonProps.size;
    return React.createElement("button", buttonProps);
  },
  MathText: ({ children }) => React.createElement("span", {}, children),
  TmaAssetImage: ({ alt }) => React.createElement("img", { alt }),
  ArrowUpRight: Icon,
  BookOpen: Icon,
  CheckCircle2: Icon,
  Eye: Icon,
  EyeOff: Icon,
  Image: Icon,
  Pencil: Icon,
  Trash2: Icon,
});
const question = {
  id: "q1",
  assignment_id: "a1",
  question_text: "Solve <script>alert(1)</script>",
  options: [
    { id: "o1", option_text: "Correct answer", is_correct: true, image_asset_id: "image" },
    { id: "o2", option_text: "Wrong answer", is_correct: false },
    { id: "o3", option_text: "Other answer", is_correct: false },
    { id: "o4", option_text: "Last answer", is_correct: false },
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

test("mobile question picker selects a question and restores answer-key review", () => {
  stateUpdates = [];
  const tree = List({
    questions: [question, { ...question, id: "q2", question_text: "Second question" }],
    assignmentPath: "/teacher/tma/a1",
    editable: false,
  });
  let picker;
  function visit(element) {
    if (!React.isValidElement(element)) return;
    if (element.type === "select") picker = element;
    React.Children.forEach(element.props.children, visit);
  }
  visit(tree);
  assert.ok(picker, "question navigation has a native mobile selector");
  assert.equal(picker.props.value, "q1");
  assert.equal(React.Children.count(picker.props.children), 2);
  picker.props.onChange({ target: { value: "q2" } });
  assert.deepEqual(stateUpdates, ["q2", false]);
});

test("question audit shows answer key, options, and dedicated full preview", () => {
  const html = render();
  assert.match(html, /href="\/teacher\/tma\/a1\/questions\/q1"/);
  assert.match(html, /Answer key review/);
  assert.match(html, /Correct answer/);
  assert.match(html, /Wrong answer/);
  assert.match(html, /Answer key:/);
  assert.match(html, /&lt;script&gt;/);
  assert.doesNotMatch(html, /<script>/);
});

test("edit and delete are exposed only for editable questions the actor can manage", () => {
  assert.match(render(), /aria-label="Edit question 1"/);
  assert.match(render(), /aria-label="Delete question 1"/);
  for (const props of [{ editable: false }, { canEdit: () => false }]) {
    const html = render(props);
    assert.doesNotMatch(html, /Edit question 1|Delete question 1/);
    assert.match(html, /Full preview/);
  }
  assert.equal((render({ busy: true }).match(/disabled=""/g) || []).length, 4);
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
    if (["Edit question 1", "Delete question 1"].includes(node.props["aria-label"]))
      node.props.onClick();
    React.Children.forEach(node.props.children, visit);
  }
  visit(tree);
  assert.deepEqual(calls, [["edit", question], ["delete", question]]);
});
