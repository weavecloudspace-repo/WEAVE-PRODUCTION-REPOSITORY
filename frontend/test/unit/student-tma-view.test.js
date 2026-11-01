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
const pickerSource = await readFile(
  new URL("../../src/features/tma/student/QuestionPicker.jsx", import.meta.url),
  "utf8",
);
const pickerAst = parse(pickerSource, {
  ecmaVersion: "latest",
  sourceType: "module",
  ecmaFeatures: { jsx: true },
  range: true,
});
const pickerFunctions = pickerAst.body
  .filter((node) => node.declaration?.type === "FunctionDeclaration")
  .map((node) => pickerSource.slice(...node.declaration.range))
  .join("\n");
const { code: pickerCode } = await transformWithOxc(
  pickerFunctions,
  "QuestionPicker.jsx",
  { jsx: { runtime: "classic" } },
);
Object.assign(
  context,
  runInNewContext(
    pickerCode + "\n({QuestionPicker,QuestionPickerActions})",
    context,
  ),
);
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

test("the desktop picker collapses without hiding the question", () => {
  const original = context.useState;
  const state = [];
  let cursor = 0;
  context.useState = (initial) => {
    const index = cursor++;
    if (!(index in state)) state[index] = initial;
    return [
      state[index],
      (value) => {
        state[index] =
          typeof value === "function" ? value(state[index]) : value;
      },
    ];
  };
  const props = {
    ...base,
    delivery: { attempt: { id: "attempt" } },
    questions: [{ id: "q", question_text: "Still visible", options: [] }],
    current: { id: "q", question_text: "Still visible", options: [] },
    position: 0,
  };
  const draw = () => {
    cursor = 0;
    return View(props);
  };
  const nodes = (node) =>
    !node || typeof node !== "object"
      ? []
      : [node, ...React.Children.toArray(node.props?.children).flatMap(nodes)];
  try {
    const first = nodes(draw());
    const toggle = first.find(
      (node) => node.props?.["aria-controls"] === "student-tma-desktop-picker",
    );
    assert.equal(toggle.props["aria-expanded"], true);
    toggle.props.onClick();
    const second = nodes(draw());
    assert.equal(
      second.find((node) => node.props?.id === "student-tma-desktop-picker")
        .props.hidden,
      true,
    );
    assert.ok(
      second.some((node) => node.props?.className === "student-tma-question"),
    );
    second
      .find(
        (node) =>
          node.props?.["aria-controls"] === "student-tma-desktop-picker",
      )
      .props.onClick();
    assert.equal(
      nodes(draw()).find(
        (node) => node.props?.id === "student-tma-desktop-picker",
      ).props.hidden,
      false,
    );
  } finally {
    context.useState = original;
  }
});

test("mobile picker opens from its launcher and closes after choosing a question", () => {
  const state = [];
  let cursor = 0,
    selected = null,
    focusCount = 0;
  const brandScope = {};
  let portalTarget = null;
  const mobileContext = {
    ...context,
    document: { body: {}, querySelector: () => brandScope },
    createPortal: (child, target) => {
      portalTarget = target;
      return child;
    },
    window: {
      matchMedia: () => ({ matches: true }),
      requestAnimationFrame: (fn) => fn(),
    },
    useState(initial) {
      const index = cursor++;
      if (!(index in state)) state[index] = initial;
      return [
        state[index],
        (value) => {
          state[index] =
            typeof value === "function" ? value(state[index]) : value;
        },
      ];
    },
  };
  const MobileView = runInNewContext(code + "\nStudentTmaView", mobileContext);
  const questions = [
    { id: "one", question_text: "Question one", options: [] },
    { id: "two", question_text: "Question two", options: [] },
  ];
  const props = {
    ...base,
    delivery: { attempt: { id: "attempt" } },
    questions,
    current: questions[0],
    position: 0,
    go: (index) => {
      selected = index;
    },
    questionHeading: { current: { focus: () => ++focusCount } },
  };
  const nodes = (node) =>
    !node || typeof node !== "object"
      ? []
      : [node, ...React.Children.toArray(node.props?.children).flatMap(nodes)];
  const draw = () => {
    cursor = 0;
    return nodes(MobileView(props));
  };
  draw();
  assert.equal(
    portalTarget,
    brandScope,
    "floating controls inherit the school's theme",
  );
  draw()
    .find((node) => node.props?.["aria-label"] === "Open question picker")
    .props.onClick();
  const open = draw();
  const sheet = open.find(
    (node) =>
      node.type === context.Modal && node.props.title === "Your questions",
  );
  assert.equal(sheet.props.open, true);
  assert.equal(
    open.find((node) => node.props?.["aria-label"] === "Open question picker")
      .props["aria-expanded"],
    true,
  );
  nodes(sheet.props.children)
    .find((node) => node.type === context.QuestionPicker)
    .props.onPick(1);
  assert.equal(selected, 1);
  assert.equal(focusCount, 1);
  assert.equal(
    draw().find(
      (node) =>
        node.type === context.Modal && node.props.title === "Your questions",
    ).props.open,
    false,
  );
});

test("Review & submit and the picker Submit TMA use the same confirmation action", () => {
  let confirmationValue = false;
  const props = {
    ...base,
    delivery: { attempt: { id: "attempt" } },
    questions: [{ id: "one", question_text: "Last", options: [] }],
    current: { id: "one", question_text: "Last", options: [] },
    position: 0,
    setConfirmation: (value) => {
      confirmationValue = value;
    },
  };
  const nodes = (node) =>
    !node || typeof node !== "object"
      ? []
      : [node, ...React.Children.toArray(node.props?.children).flatMap(nodes)];
  const tree = nodes(View(props));
  const review = tree.find(
    (node) =>
      node.type === context.Button &&
      React.Children.toArray(node.props.children).includes("Review & submit"),
  );
  const picker = tree.find(
    (node) => node.type === context.QuestionPickerActions,
  );
  assert.equal(review.props.onClick, picker.props.onSubmit);
  review.props.onClick();
  assert.equal(confirmationValue, true);
});
