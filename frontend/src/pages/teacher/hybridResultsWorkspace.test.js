import assert from "node:assert/strict";
import test from "node:test";

import { buildManualScores, resultReadiness } from "./resultsWorkspace.js";

const manual = { id: "ca1", name: "CA1", maximum_score: 50, is_examinable: false };
const hybrid = { id: "exam", name: "Examination", maximum_score: 50, is_examinable: true, is_hybrid: true };

test("theory is locked until this student's CBT score has synchronized", () => {
  const drafts = { "student:ca1": "12", "student:exam": "25" };
  const absent = buildManualScores("student", [manual, hybrid], drafts, null);
  assert.deepEqual(absent, [{ assessment_component_id: "ca1", score: 12 }]);
  const result = { components: [
    { assessment_component_id: "exam", cbt_score: 16, cbt_maximum_score: 20, theory_maximum_score: 30, is_complete: false },
  ] };
  assert.deepEqual(buildManualScores("student", [manual, hybrid], drafts, result), [
    { assessment_component_id: "ca1", score: 12 },
    { assessment_component_id: "exam", theory_score: 25 },
  ]);
  assert.throws(() => buildManualScores("student", [hybrid], { "student:exam": "31" }, result), /between 0 and 30/);
});

test("CBT zero is valid but hybrid remains incomplete until theory exists", () => {
  const record = { components: [
    { assessment_component_id: "ca1", score: 10 },
    { assessment_component_id: "exam", score: 0, is_complete: false },
  ] };
  assert.equal(resultReadiness([manual, hybrid], record).ready, false);
  record.components[1].is_complete = true;
  assert.equal(resultReadiness([manual, hybrid], record).ready, true);
});
