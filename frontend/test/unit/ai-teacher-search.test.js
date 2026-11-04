import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = await readFile(
  new URL("../../src/features/ai/AIUsagePage.jsx", import.meta.url),
  "utf8",
);

test("admin AI searches names and emails globally through separate paginated endpoints", () => {
  for (const expected of [
    'aria-label="Search staff AI credits"',
    'aria-label="Search teacher credit requests"',
    "filteredActors.map",
    "filteredRequests.map",
    "/ai/admin/quota/actors?",
    "/ai/admin/quota/requests?",
    'params.set("search", staffQuery)',
    'params.set("search", requestQuery)',
  ]) {
    assert.ok(source.includes(expected), `Missing AI search contract: ${expected}`);
  }
});
