import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { runInNewContext } from "node:vm";
import test from "node:test";
import { parse } from "espree";

const source = await readFile(
  new URL("../../src/components/layout/DashboardLayout.jsx", import.meta.url),
  "utf8",
);
const ast = parse(source, {
  ecmaVersion: "latest",
  sourceType: "module",
  ecmaFeatures: { jsx: true },
  range: true,
});
const shell = ast.body.find(
  (n) =>
    n.type === "FunctionDeclaration" && n.id.name === "DashboardShellFrame",
);
const call = shell.body.body.find(
  (n) =>
    n.type === "ExpressionStatement" &&
    n.expression.callee?.name === "useEffect" &&
    source.slice(...n.range).includes("weave:tma-attempt-opened"),
).expression;
const callback = source.slice(...call.arguments[0].range);

test("opening a student attempt collapses the existing sidebar, closes the drawer and cleans up its listener", () => {
  const target = new EventTarget(),
    changes = [];
  const effect = runInNewContext(`(${callback})`, {
    role: "student",
    window: target,
    setSidebarCollapsed: (value) => changes.push(["sidebar", value]),
    setMobileNavOpen: (value) => changes.push(["drawer", value]),
  });
  const cleanup = effect();
  target.dispatchEvent(new Event("weave:tma-attempt-opened"));
  assert.deepEqual(changes, [
    ["sidebar", true],
    ["drawer", false],
  ]);
  cleanup();
  target.dispatchEvent(new Event("weave:tma-attempt-opened"));
  assert.equal(changes.length, 2);
});

test("the student attempt event cannot change admin or teacher navigation", () => {
  for (const role of ["admin", "teacher", "parent"]) {
    const target = new EventTarget();
    const effect = runInNewContext(`(${callback})`, {
      role,
      window: target,
      setSidebarCollapsed: () => assert.fail("unrelated sidebar changed"),
      setMobileNavOpen: () => assert.fail("unrelated drawer changed"),
    });
    assert.equal(effect(), undefined);
    target.dispatchEvent(new Event("weave:tma-attempt-opened"));
  }
});
