import assert from "node:assert/strict";
import test from "node:test";
import { buildManualScores, currentAcademicContext, loadAllItems, resultReadiness } from "../../src/pages/teacher/resultsWorkspace.js";

test("current context ignores ordering and terms from another session", () => {
  assert.deepEqual(currentAcademicContext(
    [{ id: "old", is_current: false }, { id: "current", is_current: true }],
    [{ id: "wrong", is_current: true, academic_session_id: "old" }, { id: "term", is_current: true, academic_session_id: "current" }],
  ), {
    session: { id: "current", is_current: true },
    term: { id: "term", is_current: true, academic_session_id: "current" },
  });
  assert.deepEqual(currentAcademicContext([{ id: "old", is_current: false }], []), { session: null, term: null });
});

test("roster loading includes students beyond the first API page", async () => {
  const students = Array.from({ length: 225 }, (_, id) => ({ id }));
  const requests = [];
  const result = await loadAllItems(async ({ skip, limit }) => {
    requests.push({ skip, limit });
    return { items: students.slice(skip, skip + limit), total: students.length };
  });
  assert.deepEqual(result, students);
  assert.deepEqual(requests.map((request) => request.skip), [0, 100, 200]);
});

test("aborted assignment loads discard their response and request no further pages", async () => {
  const controller = new AbortController();
  let requests = 0;
  const result = await loadAllItems(async () => {
    requests += 1;
    controller.abort();
    return { items: [{ id: "stale" }], total: 200 };
  }, controller.signal);
  assert.deepEqual(result, []);
  assert.equal(requests, 1);
});

test("an empty API page cannot cause an infinite pagination loop", async () => {
  let requests = 0;
  assert.deepEqual(await loadAllItems(async () => {
    requests += 1;
    return { items: [], total: 200 };
  }), []);
  assert.equal(requests, 1);
});

const components = [
  { id: "manual", name: "CA", maximum_score: "10.00", is_examinable: false },
  { id: "exam", name: "Exam", maximum_score: "90.00", is_examinable: true },
];

test("saving sends only manual scores, including zero and explicit clearing", () => {
  assert.deepEqual(buildManualScores("student", components, { "student:manual": "0", "student:exam": "80" }), [
    { assessment_component_id: "manual", score: 0 },
  ]);
  assert.deepEqual(buildManualScores("student", components, { "student:manual": "" }), [
    { assessment_component_id: "manual", score: null },
  ]);
});

test("saving rejects invalid manual scores before contacting the API", () => {
  for (const score of ["-1", "11", "not-a-number", "Infinity"]) {
    assert.throws(() => buildManualScores("student", components, { "student:manual": score }), /CA must be between 0 and 10.00/);
  }
});

test("CBT completion alone does not mark a result ready for review", () => {
  assert.deepEqual(resultReadiness(components, {
    components: [{ assessment_component_id: "exam", score: "80" }],
  }), { manualEntered: 0, manualRequired: 1, examEntered: 1, examRequired: 1, ready: false });
});

test("readiness requires every lane, accepts zero, and excludes unrelated scores", () => {
  const result = { components: [
    { assessment_component_id: "manual", score: 0 },
    { assessment_component_id: "exam", score: "80" },
    { assessment_component_id: "other", score: "5" },
  ] };
  assert.equal(resultReadiness(components, result).ready, true);
  assert.equal(resultReadiness(components, { components: result.components.slice(0, 1) }).ready, false);
  assert.equal(resultReadiness([], result).ready, false);
});
