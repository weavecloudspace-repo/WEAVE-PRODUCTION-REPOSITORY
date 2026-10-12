import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import * as React from "react";
import { transformWithOxc } from "vite";
import { cleanText } from "../../src/utils/academicDashboard.js";
import {
  displayStatusLabel,
  hasValue,
  scoreDisplayValue,
  statusVariant,
} from "../../src/pages/student/studentPageUtils.js";

// Exercise real handlers and JSX without a DOM dependency. Hook state is retained between renders.
async function loadComponent(path, name, bindings) {
  const source = (await readFile(new URL(path, import.meta.url), "utf8"))
    .trimStart()
    .replace(/^import[\s\S]*?;\s*/gm, "")
    .replace(/export default function /, "function ")
    .replace(/export default \w+;/, "");
  const { code } = await transformWithOxc(source, `${name}.jsx`, {
    jsx: { runtime: "classic" },
  });
  return new Function(...Object.keys(bindings), `${code}\nreturn ${name};`)(
    ...Object.values(bindings),
  );
}

function elements(node) {
  if (!node || typeof node !== "object") return [];
  if (Array.isArray(node)) return node.flatMap(elements);
  if (typeof node.type === "function") return elements(node.type(node.props));
  return [node, ...elements(node.props?.children)];
}

const icon = () => null;
const cardComponent = await loadComponent(
  "../../src/components/student/StudentSubjectPerformanceCard.jsx",
  "StudentSubjectPerformanceCard",
  {
    React,
    ArrowUpRight: icon,
    BookOpen: icon,
    UserRound: icon,
    Link: "a",
    Badge: "span",
    Card: "article",
    cleanText,
    displayStatusLabel,
    hasValue,
    scoreDisplayValue,
    statusVariant,
    cn: (...values) => values.filter(Boolean).join(" "),
  },
);
const ring = (score, maximum) =>
  elements(
    cardComponent({
      card: { id: "subject", total_score: score, maximum_score: maximum },
    }),
  ).find((node) => ["meter", "img"].includes(node.props.role));

test("score ring uses total divided by the configured maximum, including decimal marks", () => {
  const meter = ring("37.5", "50");
  assert.equal(meter.props["aria-valuenow"], 37.5);
  assert.equal(meter.props["aria-valuemax"], 50);
  assert.match(meter.props.style.background, /270deg/);
});

test("missing marks and a recorded zero have distinct accessible states", () => {
  assert.equal(ring(null, 100).props.role, "img");
  assert.match(ring(null, 100).props["aria-label"], /awaiting marks/);
  assert.equal(ring(0, 100).props.role, "meter");
  assert.equal(ring(0, 100).props["aria-valuenow"], 0);
});

test("ring handles missing limits and clamps visual fill to its range", () => {
  assert.equal(ring(10, 0).props.role, "img");
  assert.equal(ring(10, null).props.role, "img");
  assert.match(ring(120, 100).props.style.background, /360deg/);
  assert.match(ring(-2, 100).props.style.background, /0deg/);
});

async function panelHarness(workspace, onSave) {
  const state = [];
  let cursor = 0;
  let status;
  const Panel = await loadComponent(
    "../../src/components/student/StudentElectiveSelectionPanel.jsx",
    "StudentElectiveSelectionPanel",
    {
      React,
      Check: icon,
      CheckCircle2: icon,
      LockKeyhole: icon,
      Button: "button",
      useMemo: (calculate) => calculate(),
      useEffect: (effect) => effect(),
      useState: (initial) => {
        const index = cursor++;
        if (!(index in state))
          state[index] = typeof initial === "function" ? initial() : initial;
        return [
          state[index],
          (next) => {
            state[index] =
              typeof next === "function" ? next(state[index]) : next;
          },
        ];
      },
    },
  );
  const render = (nextWorkspace = workspace) => {
    workspace = nextWorkspace;
    cursor = 0;
    return elements(
      Panel({
        workspace,
        onSave,
        onStateChange: (next) => {
          status = next;
        },
      }),
    );
  };
  return { render, status: () => status };
}

const group = (id, selected = [], options = {}) => ({
  elective_group_id: id,
  name: id,
  minimum_choices: 1,
  maximum_choices: 2,
  locked: false,
  subjects: [1, 2, 3].map((number) => ({
    curriculum_subject_id: `${id}${number}`,
    subject_name: `${id}${number}`,
    selected: selected.includes(number),
  })),
  ...options,
});
const option = (tree, name) =>
  tree.find(
    (node) =>
      node.type === "button" &&
      elements(node.props.children).some(
        (child) => child.props?.children === name,
      ),
  );
const save = (tree, name) =>
  tree.find((node) => node.props["aria-label"] === `Save choices for ${name}`);

test("saving one elective group preserves another group's unsaved choices", async () => {
  const workspace = { groups: [group("a"), group("b", [1])] };
  const updated = { groups: [group("a", [1]), group("b", [1])] };
  const writes = [];
  const panel = await panelHarness(workspace, async (...args) => {
    writes.push(args);
    return updated;
  });
  option(panel.render(), "b2").props.onClick();
  option(panel.render(), "a1").props.onClick();
  await save(panel.render(), "a").props.onClick();
  const refreshed = panel.render(updated);
  assert.deepEqual(writes, [["a", ["a1"]]]);
  assert.equal(option(refreshed, "b2").props["aria-pressed"], true);
  assert.equal(panel.status().dirty, true);
  assert.equal(save(refreshed, "a").props.disabled, true);
});

test("elective minimum, maximum and locked groups prevent invalid changes", async () => {
  let writes = 0;
  const panel = await panelHarness(
    { groups: [group("a", [1, 2]), group("b", [1], { locked: true })] },
    async () => {
      writes++;
    },
  );
  assert.equal(option(panel.render(), "a3").props.disabled, true);
  option(panel.render(), "a3").props.onClick();
  assert.equal(option(panel.render(), "a3").props["aria-pressed"], false);
  option(panel.render(), "b2").props.onClick();
  assert.equal(option(panel.render(), "b2").props["aria-pressed"], false);
  assert.equal(save(panel.render(), "b"), undefined);
  option(panel.render(), "a1").props.onClick();
  option(panel.render(), "a2").props.onClick();
  await save(panel.render(), "a").props.onClick();
  assert.equal(writes, 0);
  assert.ok(panel.render().some((node) => node.props.role === "alert"));
});

test("failed elective saves retain drafts and expose a retryable error", async () => {
  const panel = await panelHarness({ groups: [group("a", [1])] }, async () => {
    throw new Error("School choices changed; try again.");
  });
  option(panel.render(), "a2").props.onClick();
  await save(panel.render(), "a").props.onClick();
  const tree = panel.render();
  assert.equal(option(tree, "a2").props["aria-pressed"], true);
  assert.equal(save(tree, "a").props.disabled, false);
  assert.equal(panel.status().saving, false);
  assert.ok(
    tree.some(
      (node) =>
        node.props.role === "alert" &&
        node.props.children.includes("try again"),
    ),
  );
});
