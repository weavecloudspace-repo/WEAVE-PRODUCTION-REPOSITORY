import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const page = await readFile(new URL("../../src/features/tma/TmaPage.jsx", import.meta.url), "utf8");
const client = await readFile(new URL("../../src/services/tmaService.js", import.meta.url), "utf8");

test("draft-only first revision delete action requires management permission", () => {
  assert.match(page, /label: "Delete draft assignment"/);
  assert.match(page, /canManage && editable && assignment\?\.current_revision_number === 1/);
  assert.match(page, /assignment\?\.activated_at/);
  assert.match(page, /onClick: \(\) => setDialog\("deleteAssignment"\)/);
});

test("deletion confirms permanence, waits for backend, then returns to overview", () => {
  assert.match(page, /Permanently delete draft assignment\?/);
  assert.match(page, /cannot be undone/);
  assert.match(page, /await service\.deleteDraft\(assignmentId\)/);
  assert.match(page, /navigate\(base, \{ replace: true \}\)/);
  assert.match(client, /deleteDraft: \(id\) => api\.delete\(path\(id\)\)/);
});
