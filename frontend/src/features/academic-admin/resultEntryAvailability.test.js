import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  assignmentsAvailableForEntry,
  buildResultSubjectOptions,
  componentScoresForAssignment,
  loadClassTeacherAssignments,
} from "./resultEntryAvailability.js";

const assignments = [
  { id: "math-assignment", class_id: "class-a", curriculum_subject_id: "math" },
  { id: "english-assignment", class_id: "class-a", curriculum_subject_id: "english" },
  { id: "science-assignment", class_id: "class-b", curriculum_subject_id: "science" },
];

test("result creation hides fully scored subjects and keeps partial subjects", () => {
  const results = [
    {
      curriculum_subject_id: "math",
      components: [
        { assessment_component_id: "ca-1", score: "15", is_complete: true },
        { assessment_component_id: "ca-2", score: "20", is_complete: true },
        { assessment_component_id: "exam", score: "55", is_complete: true },
      ],
    },
    {
      curriculum_subject_id: "english",
      components: [
        { assessment_component_id: "ca-1", score: "12", is_complete: true },
        { assessment_component_id: "ca-2", score: "18", is_complete: true },
        { assessment_component_id: "exam", score: null, is_complete: false },
      ],
    },
  ];

  assert.deepEqual(
    assignmentsAvailableForEntry(assignments, results, "class-a").map((item) => item.id),
    ["english-assignment"],
  );
  assert.deepEqual(componentScoresForAssignment(results, assignments[1]), {
    "ca-1": "12",
    "ca-2": "18",
    exam: "",
  });
});

test("result creation keeps subjects with no result yet", () => {
  assert.deepEqual(
    assignmentsAvailableForEntry(assignments, [], "class-a").map((item) => item.id),
    ["math-assignment", "english-assignment"],
  );
});

test("create-result UI loads student-period availability and keeps editing in results", () => {
  const workspace = readFileSync(new URL("./ResultsWorkspace.jsx", import.meta.url), "utf8");

  assert.match(workspace, /student_id: form\.student_id/);
  assert.match(workspace, /academic_session_id: filters\.academic_session_id/);
  assert.match(workspace, /academic_term_id: filters\.academic_term_id/);
  assert.match(workspace, /assignmentsAvailableForEntry/);
  assert.match(workspace, /componentScoresForAssignment/);
  assert.match(workspace, /Use Back to\s+results to\s+edit or reopen an existing result deliberately/);
  assert.match(workspace, /setForm\(\{ \.\.\.BLANK_FORM, student_id: form\.student_id \}\)/);
});

test("the selected class loads all current assignments beyond the school-wide first page", async () => {
  const assignmentRows = Array.from({ length: 137 }, (_, n) => ({
    id: `assignment-${n}`,
    class_id: "jss1-b",
  }));
  const calls = [];
  const actual = await loadClassTeacherAssignments(async (params) => {
    calls.push(params);
    return {
      items: assignmentRows.slice(params.skip, params.skip + params.limit),
      total: assignmentRows.length,
    };
  }, "jss1-b");

  assert.equal(actual.length, 137);
  assert.deepEqual(calls.map(({ class_id, status, skip }) => ({ class_id, status, skip })), [
    { class_id: "jss1-b", status: "current", skip: 0 },
    { class_id: "jss1-b", status: "current", skip: 100 },
  ]);
  assert.deepEqual(await loadClassTeacherAssignments(() => {
    throw new Error("should not run");
  }, ""), []);
});

test("overview filters include class curriculum and recorded subjects after staffing changes", () => {
  const options = buildResultSubjectOptions(
    [{ subject_id: "math", subject_name: "Mathematics" },
      { subject_id: "english", subject_name: "English" }],
    [{ id: "social", name: "Social and Citizenship Studies" },
      { id: "math", name: "Mathematics" }],
  );
  assert.deepEqual(options.map(({ value }) => value), ["english", "math", "social"]);
});

test("hybrid CBT scores without theory are not considered complete", () => {
  const results = [{
    curriculum_subject_id: "math",
    components: [
      { assessment_component_id: "ca1", score: "15", is_complete: true },
      { assessment_component_id: "hybrid", score: "25", is_hybrid: true, is_complete: false },
    ],
  }];
  assert.deepEqual(
    assignmentsAvailableForEntry(assignments, results, "class-a").map(({ id }) => id),
    ["math-assignment", "english-assignment"],
  );
});
