import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = await readFile(
  new URL("../../src/features/ai/AIUsagePage.jsx", import.meta.url),
  "utf8",
);

test("admin AI searches names and emails globally through separate paginated endpoints", () => {
  assert.match(source, /aria-label="Search staff AI credits"/);
  assert.match(source, /aria-label="Search teacher credit requests"/);
  assert.match(source, /filteredActors\\.map/);
  assert.match(source, /filteredRequests\\.map/);
  assert.match(source, /\/ai\/admin\/quota\/actors\\?\\$\\{params\\}/);
  assert.match(source, /\/ai\/admin\/quota\/requests\\?\\$\\{params\\}/);
  assert.match(source, /params\\.set\\("search", staffQuery\\)/);
  assert.match(source, /params\\.set\\("search", requestQuery\\)/);
});
