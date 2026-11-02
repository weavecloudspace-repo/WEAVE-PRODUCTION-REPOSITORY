import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const ui = await readFile(new URL("../../src/features/tma/TmaPage.jsx", import.meta.url), "utf8");
const client = await readFile(new URL("../../src/services/tmaService.js", import.meta.url), "utf8");

test("missed-zero reconciliation exposes student reasons and audited admin-only exemptions", () => {
  assert.match(ui, /Inspect missed-deadline grading conflicts/);
  assert.match(ui, /service\.zeroConflicts\(assignmentId\)/);
  assert.match(ui, /role === "admin"/);
  assert.match(ui, /Exempt with reason/);
  assert.match(ui, /service\.exemptZero\(assignmentId, zeroExemptTarget, reason\)/);
  assert.match(ui, /Exemptions are audited and do not modify marks/);
  assert.match(client, /deadline-zeros\/exempt/);
});
