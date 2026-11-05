import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const ui = await readFile(new URL("../../src/features/tma/TmaPage.jsx", import.meta.url), "utf8");
const client = await readFile(new URL("../../src/services/tmaService.js", import.meta.url), "utf8");
const panel = await readFile(new URL("../../src/features/tma/TmaReconciliationPanel.jsx", import.meta.url), "utf8");
const results = await readFile(new URL("../../src/features/academic-admin/ResultsWorkspace.jsx", import.meta.url), "utf8");

test("missed-zero reconciliation exposes student reasons and audited admin-only exemptions", () => {
  assert.match(ui, /Inspect missed-deadline grading conflicts/);
  assert.match(ui, /service\.zeroConflicts\(assignmentId\)/);
  assert.match(ui, /role === "admin"/);
  assert.match(panel, /Exempt with reason/);
  assert.match(ui, /service\.exemptZero\(assignmentId, zeroExemptTarget, reason\)/);
  assert.match(panel, /Exemptions require a reason, are audited/);
  assert.match(client, /deadline-zeros\/exempt/);
});

test("conflicts identify students and link administrators to filtered academic results", () => {
  assert.match(panel, /issue\.student_name/);
  assert.match(panel, /issue\.admission_number/);
  assert.match(panel, /issue\.reason/);
  assert.match(panel, /role === "admin"/);
  assert.match(panel, /academic_session_id: assignment\.academic_session_id/);
  assert.match(results, /searchParams\.get\("search"\)/);
  assert.match(results, /searchParams\.get\("class_id"\)/);
  assert.doesNotMatch(panel, /Student \{issue\.student_id\}/);
});
