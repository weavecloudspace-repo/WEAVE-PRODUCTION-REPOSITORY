import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { runInNewContext } from "node:vm";
import test from "node:test";
import * as React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { parse } from "espree";
import { transformWithOxc } from "vite";

const source = await readFile(
  new URL("../../src/features/tma/student/StudentTmaView.jsx", import.meta.url),
  "utf8",
);
const ast = parse(source, {
  ecmaVersion: "latest",
  sourceType: "module",
  ecmaFeatures: { jsx: true },
  range: true,
});
const declaration = ast.body.find(
  (node) => node.type === "ExportDefaultDeclaration",
).declaration;
const { code } = await transformWithOxc(
  source.slice(...declaration.range),
  "StudentTmaView.jsx",
  { jsx: { runtime: "classic" } },
);
const context = {
  React,
  useRef: () => ({ current: null }),
  useLayoutEffect: () => {},
  useState: (value) => [value, () => {}],
  Button: ({ children, ...props }) =>
    React.createElement("button", props, children),
  Card: ({ children, ...props }) =>
    React.createElement("section", props, children),
  Link: ({ children, to, ...props }) =>
    React.createElement("a", { ...props, href: to }, children),
  Modal: ({ open, children }) =>
    open ? React.createElement("section", { role: "dialog" }, children) : null,
  MathText: ({ children }) => React.createElement("span", null, children),
  StudentImage: () => null,
};
for (const node of ast.body.filter(
  (node) =>
    node.type === "ImportDeclaration" && node.source.value === "lucide-react",
)) {
  for (const specifier of node.specifiers)
    context[specifier.local.name] = () => null;
}
const View = runInNewContext(code + "\nStudentTmaView", context);
const base = {
  back: "/student/subjects/math",
  subject: { subject_name: "Maths" },
  component: { name: "CA1" },
  assignment: { can_start_or_resume: true, component_maximum_score: 20 },
  questions: [],
  answers: {},
  answered: 0,
  saveState: { pending: [], error: null },
  questionHeading: { current: null },
  start: () => {},
  leave: () => {},
  go: () => {},
  choose: () => {},
  setReload: () => {},
  setConfirmation: () => {},
  submit: () => {},
};
const render = (overrides = {}) =>
  renderToStaticMarkup(React.createElement(View, { ...base, ...overrides }));

test("a new attempt has a direct Start TMA action and a separate guide button", () => {
  const html = render();
  assert.match(html, />Start TMA</);
  assert.match(html, /aria-haspopup="dialog"/);
  assert.match(html, /Before you start/);
  assert.match(html, /One attempt/);
  assert.doesNotMatch(html, /<form/);
  assert.doesNotMatch(html, />\s*\+\s*</);
});

test("a saved attempt offers Continue TMA instead of Start TMA", () => {
  const html = render({
    assignment: { ...base.assignment, attempt_status: "in_progress" },
  });
  assert.match(html, />Continue TMA</);
  assert.doesNotMatch(html, />Start TMA</);
});

test("submit confirmation shows unanswered work and does not submit without confirmation", () => {
  let submissions = 0;
  const questions = Array.from({ length: 3 }, (_, i) => ({
    id: "q" + i,
    question_text: "Question",
    options: [{ id: "a" + i, option_text: "Answer" }],
  }));
  const html = render({
    delivery: { attempt: { id: "attempt" } },
    questions,
    current: questions[0],
    position: 0,
    answers: { q0: "a0" },
    answered: 1,
    confirmation: true,
    submit: () => {
      ++submissions;
    },
  });
  assert.match(html, /role="dialog"/);
  assert.match(html, /2 questions are unanswered/);
  assert.match(html, /Confirm submission/);
  assert.match(html, /cannot change your answers/);
  assert.equal(submissions, 0);
});

test("submission is offered only at the last question and uses a neutral unanswered message", () => {
  const questions = Array.from({ length: 3 }, (_, i) => ({
    id: "q" + i,
    question_text: "Question",
    options: [{ id: "a" + i, option_text: "Answer" }],
  }));
  const attempt = {
    delivery: { attempt: { id: "attempt" } },
    questions,
    current: questions[0],
    position: 0,
  };
  assert.doesNotMatch(render(attempt), />Submit TMA</);
  assert.match(
    render({ ...attempt, current: questions[2], position: 2 }),
    />Submit TMA</,
  );
  const confirm = render({
    ...attempt,
    current: questions[2],
    position: 2,
    confirmation: true,
  });
  assert.match(confirm, /3 questions are unanswered/);
  assert.doesNotMatch(confirm, /bg-warning|Submitting is final/);
});

test("a submitted result displays the server score and removes question input", () => {
  const html = render({
    result: {
      component_score: "12.50",
      correct_answers: 5,
      total_questions: 8,
      submitted_at: "2026-11-01T10:00:00Z",
    },
  });
  assert.match(html, /12.50/);
  assert.match(html, /View subject assessments/);
  assert.doesNotMatch(html, /type="radio"|Start TMA|Continue TMA/);
});

test("saving feedback appears only for pending or failed saves", () => {
  const attempt = {
    delivery: { attempt: { id: "attempt" } },
    questions: [],
    current: null,
  };
  assert.doesNotMatch(render(attempt), /All answers saved|student-tma-topline/);
  assert.match(
    render({ ...attempt, saveState: { pending: ["q1"], error: null } }),
    /Saving/,
  );
  assert.match(
    render({
      ...attempt,
      saveState: { pending: ["q1"], error: new Error("Offline") },
    }),
    /Some answers are not saved/,
  );
});
