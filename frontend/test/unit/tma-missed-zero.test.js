import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const card = await readFile(new URL("../../src/features/tma/student/StudentSubjectTma.jsx", import.meta.url), "utf8");
const view = await readFile(new URL("../../src/features/tma/student/StudentTmaView.jsx", import.meta.url), "utf8");
const author = await readFile(new URL("../../src/features/tma/TmaPage.jsx", import.meta.url), "utf8");

test("missed deadlines show a zero rather than suggesting a submission was made", () => {
  assert.match(card, /Missed deadline · zero recorded/);
  assert.match(view, /missedZero \? "Missed deadline"/);
  assert.match(view, /result\?\.auto_zeroed_at && !result\?\.auto_zero_resolved_at/);
  assert.match(card, /item\.auto_zeroed_at && !item\.auto_zero_resolved_at/);
  assert.match(view, /a zero was recorded/);
  assert.match(author, /"submitted", "missed"/);
  assert.match(author, /Deadline grading needs reconciliation/);
});
