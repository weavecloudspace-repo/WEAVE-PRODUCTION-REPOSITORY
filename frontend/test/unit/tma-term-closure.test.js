import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { subjectAssignments } from "../../src/features/tma/student/attemptState.js";

const tmaPage = await readFile(new URL("../../src/features/tma/TmaPage.jsx", import.meta.url), "utf8");
const subjectCard = await readFile(new URL("../../src/features/tma/student/StudentSubjectTma.jsx", import.meta.url), "utf8");
const view = await readFile(new URL("../../src/features/tma/student/StudentTmaView.jsx", import.meta.url), "utf8");
const client = await readFile(new URL("../../src/services/tmaService.js", import.meta.url), "utf8");

test("current-term subject cards omit historical TMAs while preserving closed current ones", () => {
  const subject = { academic_term_id: "current", curriculum_subject_id: "math" };
  const assignments = [
    { academic_term_id: "current", curriculum_subject_id: "math", status: "active" },
    { academic_term_id: "current", curriculum_subject_id: "math", status: "closed" },
    { academic_term_id: "past", curriculum_subject_id: "math", status: "closed" },
    { academic_term_id: "current", curriculum_subject_id: "biology", status: "closed" },
  ];
  assert.deepEqual(subjectAssignments(assignments, subject), assignments.slice(0, 2));
});

test("closed TMA cards remain visible but unsubmitted students get no start link", () => {
  assert.match(subjectCard, /item\.status === "closed"/);
  assert.match(subjectCard, /Closed · submissions are no longer accepted/);
  assert.match(subjectCard, /item\.attempt_status === "submitted"/);
  assert.match(subjectCard, /item\.can_start_or_resume/);
  assert.match(view, /assignment\.status === "closed"/);
  assert.match(view, /disabled=\{busy \|\| !assignment\.can_start_or_resume \|\| assignment\.status === "closed"\}/);
});

test("teacher and admin overview share the active-term default and historical term selector", () => {
  assert.match(tmaPage, /service\.terms\(\)/);
  assert.match(tmaPage, /termOptions\.find\(\(term\) => term\.is_current\)/);
  assert.match(tmaPage, /label="Academic term"/);
  assert.match(tmaPage, /setTermId\(value\)/);
  assert.match(tmaPage, /service\.list\(offset, selected, \{/);
  assert.match(client, /academic_term_id/);
});

test("deadline is described as enforced, not informational", () => {
  assert.match(tmaPage, /Submission deadline \(required\)/);
  assert.match(view, /closes automatically at this time/);
});
