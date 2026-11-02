import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { runInNewContext } from "node:vm";
import test from "node:test";
import React from "react";
import { parse } from "espree";
import { transformWithOxc } from "vite";

const source = await readFile(new URL("../../src/features/tma/TmaPage.jsx", import.meta.url), "utf8");
const ast = parse(source, { ecmaVersion: "latest", sourceType: "module", ecmaFeatures: { jsx: true }, range: true });
let action;
function visit(node) {
  if (!node || typeof node !== "object") return;
  if (node.type === "ObjectExpression" && node.properties.some((p) => p.key?.name === "label" && p.value?.value === "Publish assignment")) action = node;
  for (const value of Object.values(node)) {
    if (Array.isArray(value)) value.forEach(visit);
    else if (value && typeof value === "object") visit(value);
  }
}
visit(ast);
assert.ok(action);
const onClick = action.properties.find((p) => p.key.name === "onClick").value;
const { code } = await transformWithOxc(`const publish = ${source.slice(...onClick.range)};`, "publication.jsx", { jsx: { runtime: "classic" } });

function setup(issues) {
  const toasts = [], dialogs = [];
  const publish = runInNewContext(`${code}\npublish`, {
    React, draft: null, assignmentId: "assignment-1",
    service: { readiness: async () => issues },
    run: (fn) => fn(), showError: (...args) => toasts.push(args),
    setDialog: (name) => dialogs.push(name), setTab() {},
  });
  return { publish, toasts, dialogs };
}

test("publication blockers use one dismissible global error toast and prevent confirmation", async () => {
  const issues = ["JSS1 A has no assigned subject teacher.", "JSS1 B has no assigned subject teacher."];
  const h = setup(issues);
  await h.publish();
  assert.equal(h.toasts.length, 1);
  assert.equal(h.toasts[0][1].id, "tma-publish-assignment-1");
  const message = h.toasts[0][0];
  assert.equal(message.props.children[1].length, 2);
  assert.equal(message.props.children[1][0].props.children[1], issues[0]);
  assert.deepEqual(h.dialogs, []);
  assert.doesNotMatch(source, /Publication checklist|setReadiness/);
});

test("ready publication retains the existing confirmation dialog without an error toast", async () => {
  const h = setup([]);
  await h.publish();
  assert.deepEqual(h.dialogs, ["activate"]);
  assert.deepEqual(h.toasts, []);
});
