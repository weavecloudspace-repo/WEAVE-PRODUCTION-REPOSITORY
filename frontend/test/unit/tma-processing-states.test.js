import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const page = await readFile(new URL("../../src/features/tma/TmaPage.jsx", import.meta.url), "utf8");
const card = await readFile(new URL("../../src/features/tma/TmaAssignmentCard.jsx", import.meta.url), "utf8");
const actions = await readFile(new URL("../../src/features/tma/TmaActions.jsx", import.meta.url), "utf8");

test("worker progress is shown and auto-refreshed", () => {
  assert.match(page, /Finalizing scores/);
  assert.match(page, /Grading needs attention/);
  assert.match(page, /Missed-deadline grading completed/);
  assert.match(page, /service\.get\(assignmentId\)/);
  assert.match(page, /window\.clearTimeout\(timer\)/);
  assert.match(card, /Closed · Ready/);
});
test("conflicting lifecycle actions remain discoverable but are disabled", () => {
  assert.match(page, /label: "Reopen assignment",[\s\S]*?disabled: gradingPending/);
  assert.match(page, /label: "Cancel and reverse scores",[\s\S]*?disabled: gradingPending/);
  assert.match(actions, /disabled={disabled}/);
});
test("worker SQL errors are not displayed verbatim", () => {
  assert.doesNotMatch(page, /\{assignment\.zero_grading_error\}/);
  assert.doesNotMatch(page, /\{issue\.reason\}/);
});
