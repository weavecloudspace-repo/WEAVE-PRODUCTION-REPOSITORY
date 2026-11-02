import assert from "node:assert/strict";
import test from "node:test";
import { createAnswerQueue } from "../../src/features/tma/student/answerQueue.js";
import {
  answeredCount,
  savedSelections,
  subjectAssignments,
} from "../../src/features/tma/student/attemptState.js";

const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
};

test("subject entry only offers assignments for the displayed curriculum subject and term", () => {
  const matches = {
    curriculum_subject_id: "math",
    academic_term_id: "current",
  };
  assert.deepEqual(
    subjectAssignments(
      [
        { ...matches, assignment_id: "wanted" },
        { ...matches, academic_term_id: "previous" },
        { ...matches, curriculum_subject_id: "biology" },
      ],
      matches,
    ).map((a) => a.assignment_id),
    ["wanted"],
  );
  assert.deepEqual(subjectAssignments([{ ...matches }], {}), []);
});

test("resume restores valid answers by stable IDs, regardless of shuffled display order", () => {
  const questions = [
    { id: "q2", options: [{ id: "b" }] },
    { id: "q1", options: [{ id: "a" }] },
  ];
  const restored = savedSelections({
    questions,
    saved_answers: [
      { question_id: "q1", selected_option_id: "a" },
      { question_id: "q2", selected_option_id: "a" },
      { question_id: "foreign", selected_option_id: "b" },
    ],
  });
  assert.deepEqual(restored, { q1: "a" });
  assert.equal(
    answeredCount(questions, { ...restored, foreign: "x", q2: null }),
    1,
  );
});

test("rapid answer changes serialize, coalesce and clear without an older response overwriting the latest", async () => {
  const first = deferred();
  const writes = [];
  const queue = createAnswerQueue(async (q, option) => {
    writes.push([q, option]);
    if (writes.length === 1) await first.promise;
  });
  queue.select("q1", "old");
  queue.select("q1", "middle");
  queue.select("q2", "other");
  queue.select("q1", null);
  assert.deepEqual(writes, [["q1", "old"]]);
  let finished = false;
  const flush = queue.flush().then(() => {
    finished = true;
  });
  await Promise.resolve();
  assert.equal(finished, false, "submission must wait for pending answers");
  first.resolve();
  await flush;
  assert.deepEqual(writes, [
    ["q1", "old"],
    ["q1", null],
    ["q2", "other"],
  ]);
  assert.deepEqual(queue.snapshot(), {
    pending: [],
    saving: false,
    error: null,
  });
});

test("a failed save remains pending and blocks submission until an explicit retry succeeds", async () => {
  const failure = deferred();
  let calls = 0;
  const queue = createAnswerQueue(async () => {
    if (++calls === 1) await failure.promise;
  });
  queue.select("q1", "a");
  const attemptSubmit = queue.flush();
  failure.reject(new Error("Offline"));
  await assert.rejects(attemptSubmit, /Offline/);
  assert.deepEqual(queue.snapshot().pending, ["q1"]);
  assert.match(queue.snapshot().error.message, /Offline/);
  await queue.flush();
  assert.equal(calls, 2);
  assert.deepEqual(queue.snapshot().pending, []);
});

test("detaching a page stops UI callbacks while an already requested answer still saves", async () => {
  const pending = deferred();
  let changes = 0;
  const queue = createAnswerQueue(
    () => pending.promise,
    () => ++changes,
  );
  queue.select("q1", "a");
  queue.detach();
  const before = changes;
  pending.resolve();
  await queue.flush();
  assert.equal(changes, before);
  assert.equal(queue.snapshot().pending.length, 0);
});
