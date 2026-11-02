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
  });
  assert.equal(dialog, "reopen");
});

test("confirming reopen calls its service and reloads after success", async () => {
  const handler = find(ast, (node) => node.type === "JSXAttribute" && node.name.name === "onClick"
    && source.slice(...node.range).includes('dialog === "reopen"'));
  const events = [];
  await runInNewContext(`(${source.slice(...handler.value.expression.range)})()`, {
    dialog: "reopen", assignmentId: "assignment-1", run: (fn) => fn(),
    service: { reopen: async (id) => { events.push(["reopen", id]); } },
    setDialog: (value) => { events.push(["dialog", value]); },
    load: async () => { events.push(["load"]); },
    showSuccess: (message) => { events.push(["success", message]); },
  });
  assert.deepEqual(events, [["reopen", "assignment-1"], ["success", "Assignment reopened."], ["dialog", null], ["load"]]);
});
