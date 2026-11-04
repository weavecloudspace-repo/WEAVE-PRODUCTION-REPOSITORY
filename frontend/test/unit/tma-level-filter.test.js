import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const page = await readFile(new URL("../../src/features/tma/TmaPage.jsx", import.meta.url), "utf8");
const service = await readFile(new URL("../../src/services/tmaService.js", import.meta.url), "utf8");

test("assignment search, level and status are sent to the server before pagination", () => {
  assert.match(page, /service\.list\(offset, termId, \{/);
  assert.match(page, /search: debouncedQuery/);
  assert.match(page, /status: statusFilter/);
  assert.match(page, /academic_level_id: levelFilter/);
  assert.match(page, /const visibleList = list;/);
  assert.doesNotMatch(page, /const visibleList = list\.filter/);
  assert.match(service, /params\.set\("search", filters\.search\.trim\(\)\)/);
  assert.match(service, /params\.set\("academic_level_id", filters\.academic_level_id\)/);
});

test("changing a filter resets the assignment offset and matches are counted across all pages", () => {
  assert.match(page, /setOffset\(0\);\s*\}, \[debouncedQuery, statusFilter, levelFilter\]\)/);
  assert.match(page, /Showing \{visibleList\.length\} of \{listTotal\} matching assignments/);
});
