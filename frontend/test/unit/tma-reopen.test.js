import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { runInNewContext } from "node:vm";
import test from "node:test";
import { parse } from "espree";

const source = await readFile(new URL("../../src/features/tma/TmaPage.jsx", import.meta.url), "utf8");
const ast = parse(source, {
  ecmaVersion: "latest", sourceType: "module", ecmaFeatures: { jsx: true }, range: true,
});
function find(node, predicate) {
  if (!node || typeof node !== "object") return undefined;
  if (predicate(node)) return node;
  return Object.values(node).flat().map((child) => find(child, predicate)).find(Boolean);
}
const action = find(ast, (node) => node.type === "ObjectExpression" && node.properties.some(
  (p) => p.key?.name === "label" && p.value.value === "Reopen assignment",
));
const property = (name) => action.properties.find((p) => p.key.name === name).value;

test("reopen action is limited to managers of closed assignments and opens confirmation", () => {
  for (const status of ["draft", "active", "closed", "cancelling", "cancelled"]) {
    for (const canManage of [false, true]) {
      assert.equal(runInNewContext(source.slice(...property("visible").range), {
        canManage, assignment: { status },
      }), canManage && status === "closed");
    }
  }
  let dialog;
  runInNewContext(`(${source.slice(...property("onClick").range)})()`, {
    setDialog: (value) => { dialog = value; },
    setReopenDeadline: () => {},
    assignment: { status: "closed", closes_at: null },
    dateInput: (value) => value,
  });
  assert.equal(dialog, "reopen");
});

test("confirming reopen calls its service and reloads after success", async () => {
  const handler = find(ast, (node) => node.type === "JSXAttribute" && node.name.name === "onClick"
    && source.slice(...node.range).includes('dialog === "reopen"'));
  const events = [];
  await runInNewContext(`(${source.slice(...handler.value.expression.range)})()`, {
    dialog: "reopen", assignmentId: "assignment-1", run: (fn) => fn(),
    reopenDeadline: "2099-11-06T17:00", Date,
    service: { reopen: async (id, deadline) => { events.push(["reopen", id, deadline]); } },
    showError: (message) => { events.push(["error", message]); },
    setDialog: (value) => { events.push(["dialog", value]); },
    load: async () => { events.push(["load"]); },
    showSuccess: (message) => { events.push(["success", message]); },
  });
  assert.deepEqual(events, [["reopen", "assignment-1", new Date("2099-11-06T17:00").toISOString()], ["success", "Assignment reopened."], ["dialog", null], ["load"]]);
});

const confirmHandler = find(ast, (node) => node.type === "JSXAttribute" && node.name.name === "onClick"
  && source.slice(...node.range).includes('dialog === "reopen"'));

async function attemptReopen(deadline, reopen) {
  const events = [];
  await runInNewContext(`(${source.slice(...confirmHandler.value.expression.range)})()`, {
    dialog: "reopen", assignmentId: "assignment-1", run: (fn) => fn(),
    reopenDeadline: deadline, Date,
    service: { reopen: async (...args) => { events.push(["reopen", ...args]); return reopen?.(); } },
    getErrorMessage: (error) => error.message,
    showError: (message, options) => { events.push(["error", message, options.id]); },
    setDialog: (value) => { events.push(["dialog", value]); },
    load: async () => { events.push(["load"]); },
    showSuccess: (message) => { events.push(["success", message]); },
  });
  return events;
}

test("reopen validation failures display a global error toast without dismissing the modal", async () => {
  for (const deadline of ["", "2020-01-01T00:00"]) {
    const events = await attemptReopen(deadline);
    assert.deepEqual(events, [
      ["error", "Choose a valid future deadline before reopening this TMA.", "tma-reopen-assignment-1"],
    ]);
  }
});

test("reopen API failures display the backend error via a toast without closing the modal", async () => {
  const events = await attemptReopen("2099-11-06T17:00", () => {
    throw new Error("Cannot reopen while relevant academic results are finalized.");
  });
  assert.deepEqual(events, [
    ["reopen", "assignment-1", new Date("2099-11-06T17:00").toISOString()],
    ["error", "Cannot reopen while relevant academic results are finalized.", "tma-reopen-assignment-1"],
  ]);
});
