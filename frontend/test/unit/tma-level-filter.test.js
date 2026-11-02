import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { runInNewContext } from "node:vm";
import test from "node:test";
import { parse } from "espree";

const source = await readFile(new URL("../../src/features/tma/TmaPage.jsx", import.meta.url), "utf8");
const ast = parse(source, { ecmaVersion: "latest", sourceType: "module", ecmaFeatures: { jsx: true }, range: true });
const component = ast.body.find((n) => n.declaration?.id?.name === "TmaPage").declaration;
const declaration = component.body.body.flatMap((n) => n.declarations || []).find((n) => n.id.name === "visibleList");
const list = [
  { id: "math-ss1", academic_level_id: "ss1", status: "draft", label: "Mathematics · SS1" },
  { id: "math-ss2", academic_level_id: "ss2", status: "active", label: "Mathematics · SS2" },
  { id: "physics-ss1", academic_level_id: "ss1", status: "active", label: "Physics · SS1" },
];
function filter({ levelFilter = "", statusFilter = "", query = "" } = {}) {
  return Array.from(runInNewContext(source.slice(...declaration.init.range), {
    list, levelFilter, statusFilter, query, scopeLabel: (assignment) => assignment.label,
  }), (a) => a.id);
}

test("level selection filters by academic level ID and combines with status and search", () => {
  assert.deepEqual(filter({ levelFilter: "ss1" }), ["math-ss1", "physics-ss1"]);
  assert.deepEqual(filter({ levelFilter: "ss1", statusFilter: "active" }), ["physics-ss1"]);
  assert.deepEqual(filter({ levelFilter: "ss2", query: "mathematics" }), ["math-ss2"]);
  assert.deepEqual(filter({ levelFilter: "ss2", statusFilter: "draft" }), []);
});

test("All levels restores the existing page filtering behavior", () => {
  assert.deepEqual(filter(), list.map((a) => a.id));
  assert.deepEqual(filter({ query: "mathematics" }), ["math-ss1", "math-ss2"]);
});
