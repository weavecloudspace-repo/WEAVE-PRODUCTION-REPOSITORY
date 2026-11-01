import assert from "node:assert/strict";
import test from "node:test";
import {
  aiDraftScope,
  createAIDraftController,
  validateAIQuestion,
} from "../../src/features/tma/aiDrafts.js";

const question = () => ({
  question_type: "single_choice",
  prompt: "What is 2 + 2?",
  options: [1, 2, 3, 4].map((n) => ({ text: String(n), is_correct: n === 4 })),
});
function fixture() {
  const data = new Map();
  const copy = (value) =>
    value === undefined ? undefined : structuredClone(value);
  const store = {
    get: async (id) => copy(data.get(id)),
    put: async (draft) => {
      data.set(draft.draft_id, copy(draft));
      return copy(draft);
    },
    delete: async (id) => {
      data.delete(id);
    },
    change: async (id, fn) => {
      const next = fn(copy(data.get(id)));
      data.set(id, copy(next));
      return copy(next);
    },
  };
  const calls = [];
  const service = {
    generate: async (...args) => {
      calls.push(["generate", ...args]);
      return { questions: [question(), question()] };
    },
    regenerate: async (...args) => {
      calls.push(["regenerate", ...args]);
      return { question: { ...question(), prompt: "Refined" } };
    },
    importQuestions: async (...args) => {
      calls.push(["save", ...args]);
      return { imported_count: 2 };
    },
  };
  let id = 0;
  const controller = createAIDraftController({
    store,
    service,
    assignmentId: "assignment",
    revisionNumber: 3,
    uuid: () => `operation-${++id}`,
  });
  return { data, store, calls, service, controller };
}
const input = {
  generation_prompt: "Arithmetic",
  question_count: 2,
  difficulty: "medium",
  visual_mode: "text_only",
};

test("generation and editing stay local until one explicit bulk save", async () => {
  const f = fixture();
  const draft = await f.controller.generate(input);
  assert.equal(draft.status, "review");
  const edited = [
    { ...draft.questions[0], prompt: "Edited" },
    draft.questions[1],
  ];
  await f.controller.update(draft.draft_id, edited);
  assert.deepEqual(
    f.calls.map((c) => c[0]),
    ["generate"],
  );
  await f.controller.save(draft.draft_id);
  assert.deepEqual(f.calls[1], [
    "save",
    "assignment",
    { draft_id: draft.draft_id, revision_number: 3, questions: edited },
  ]);
  assert.equal(await f.store.get(draft.draft_id), undefined);
});

test("generation is recorded before the call and recovers with its original identity", async () => {
  const f = fixture();
  const generate = f.service.generate;
  f.service.generate = async () => {
    assert.equal(f.data.get("operation-1").status, "generating");
    throw new Error("Lost response");
  };
  await assert.rejects(f.controller.generate(input), /Lost response/);
  f.service.generate = generate;
  await f.controller.recover("operation-1");
  assert.equal(f.calls[0][3], "operation-1");
  assert.equal(f.data.get("operation-1").status, "review");
});

test("storage failure prevents spending credits", async () => {
  const f = fixture();
  f.store.put = async () => {
    throw new Error("Storage full");
  };
  await assert.rejects(f.controller.generate(input), /Storage full/);
  assert.equal(f.calls.length, 0);
});

test("lost bulk responses freeze edits and retry the exact same payload", async () => {
  const f = fixture();
  const draft = await f.controller.generate(input);
  const bodies = [];
  f.service.importQuestions = async (id, body) => {
    bodies.push(structuredClone(body));
    throw new Error("Lost response");
  };
  await assert.rejects(f.controller.save(draft.draft_id));
  await assert.rejects(f.controller.update(draft.draft_id, []), /Recover/);
  await assert.rejects(f.controller.save(draft.draft_id));
  assert.deepEqual(bodies[0], bodies[1]);
  assert.equal(f.data.get(draft.draft_id).status, "saving");
});

test("pending regeneration blocks edits and recovers the same paid operation", async () => {
  const f = fixture();
  const draft = await f.controller.generate(input);
  const regen = f.service.regenerate;
  f.service.regenerate = async () => {
    throw new Error("Lost response");
  };
  await assert.rejects(f.controller.regenerate(draft.draft_id, 0, "Refine"));
  await assert.rejects(f.controller.update(draft.draft_id, []), /Recover/);
  f.service.regenerate = regen;
  const result = await f.controller.recover(draft.draft_id);
  assert.equal(result.questions[0].prompt, "Refined");
  assert.equal(f.calls[1][3], "operation-2");
  assert.equal(result.pending_regeneration, null);
});

test("known validation rejection unlocks the local batch and invalid options cannot save", async () => {
  const f = fixture();
  const draft = await f.controller.generate(input);
  f.service.importQuestions = async () => {
    throw Object.assign(new Error("Invalid"), { response: { status: 422 } });
  };
  await assert.rejects(f.controller.save(draft.draft_id));
  assert.equal(f.data.get(draft.draft_id).status, "review");
  await f.controller.update(draft.draft_id, [{ ...question(), options: [] }]);
  await assert.rejects(f.controller.save(draft.draft_id), /four/);
  assert.equal(validateAIQuestion(question()), "");
});

test("draft scopes distinguish school, membership, role, and assignment", () => {
  const user = { tenant_id: "school", membership_id: "teacher", id: "global" };
  const scope = aiDraftScope(user, "teacher", "a1");
  assert.notEqual(
    scope,
    aiDraftScope({ ...user, tenant_id: "other" }, "teacher", "a1"),
  );
  assert.notEqual(
    scope,
    aiDraftScope({ ...user, membership_id: "other" }, "teacher", "a1"),
  );
  assert.notEqual(scope, aiDraftScope(user, "admin", "a1"));
  assert.notEqual(scope, aiDraftScope(user, "teacher", "a2"));
  assert.equal(aiDraftScope(null, "teacher", "a1"), null);
});
