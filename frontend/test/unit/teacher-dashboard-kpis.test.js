import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { runInNewContext } from "node:vm";
import test from "node:test";
import { parse } from "espree";
import { transformWithOxc } from "vite";

const source = await readFile(
  new URL("../../src/pages/teacher/TeacherDashboardPage.jsx", import.meta.url),
  "utf8",
);
const ast = parse(source, {
  ecmaVersion: "latest",
  sourceType: "module",
  ecmaFeatures: { jsx: true },
  range: true,
});
function find(node) {
  if (!node || typeof node !== "object") return null;
  if (
    node.type === "ConditionalExpression" &&
    node.test.name === "hasClassTeacherClasses" &&
    source.slice(...node.consequent.range).includes("dashboard-kpi-grid-four")
  )
    return node;
  for (const value of Object.values(node)) {
    for (const child of Array.isArray(value) ? value : [value]) {
      const match = find(child);
      if (match) return match;
    }
  }
  return null;
}
const expression = find(ast);
assert.ok(
  expression,
  "the teacher dashboard must provide its KPI row for both teacher roles",
);
const { code } = await transformWithOxc(
  "function renderKpis(){ return (" +
    source.slice(...expression.range) +
    "); }",
  "TeacherDashboardKpis.jsx",
  { jsx: { runtime: "classic" } },
);
function render(values = {}) {
  const context = {
    React: {
      createElement: (type, props, ...children) => ({ type, props, children }),
    },
    DashboardMetricCard: "MetricCard",
    BookOpen: "BookOpen",
    Users: "Users",
    CheckCircle2: "CheckCircle2",
    FilePenLine: "FilePenLine",
    CheckSquare: "CheckSquare",
    MessageSquareText: "MessageSquareText",
    hasClassTeacherClasses: false,
    subjectNames: ["Biology"],
    subjectClasses: ["SS1 A", "SS2 A", "SS3 A"],
    metrics: { stats: { result_rows_submitted: 18, pending_score_rows: 7 } },
    classTeacherCount: 1,
    requiringComments: 5,
    draftComments: 2,
    submittedComments: 8,
    completion: 80,
    ...values,
  };
  return runInNewContext(code + "\nrenderKpis()", context);
}
const cards = (tree) =>
  tree.children.flat().filter((node) => node?.type === "MetricCard");

test("subject teachers see four useful KPI cards even without class-teacher duties", () => {
  const row = render();
  assert.match(row.props.className, /grid-cols-2.*xl:grid-cols-4/);
  assert.deepEqual(
    cards(row).map((card) => [card.props.label, card.props.value]),
    [
      ["Assigned subjects", 1],
      ["Subject classes", 3],
      ["Finalized results", 18],
      ["Pending results", 7],
    ],
  );
  assert.ok(
    cards(row).every(
      (card) =>
        !card.props.to.includes("student-comments") &&
        !card.props.to.includes("/classes"),
    ),
  );
});

test("class teachers retain their four existing report-comment KPIs", () => {
  assert.deepEqual(
    cards(render({ hasClassTeacherClasses: true })).map((card) => [
      card.props.label,
      card.props.value,
    ]),
    [
      ["Class teacher classes", 1],
      ["Require comments", 5],
      ["Draft comments", 2],
      ["Submitted comments", 8],
    ],
  );
});

test("empty and unavailable values do not hide the row or invent result counts", () => {
  const empty = cards(
    render({
      subjectNames: [],
      subjectClasses: [],
      metrics: { stats: { result_rows_submitted: 0, pending_score_rows: 0 } },
    }),
  );
  assert.deepEqual(
    empty.map((card) => card.props.value),
    [0, 0, 0, 0],
  );
  const unavailable = cards(render({ metrics: null }));
  assert.deepEqual(
    unavailable.slice(2).map((card) => card.props.value),
    ["—", "—"],
  );
});
