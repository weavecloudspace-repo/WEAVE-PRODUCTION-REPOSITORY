import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { runInNewContext } from "node:vm";
import test from "node:test";
import { parse } from "espree";

const source = await readFile(new URL("../../src/features/tma/TmaPage.jsx", import.meta.url), "utf8");
const ast = parse(source, {
  ecmaVersion: "latest",
  sourceType: "module",
  ecmaFeatures: { jsx: true },
  range: true,
});
const page = ast.body.find(
  (node) => node.type === "ExportDefaultDeclaration"
    && node.declaration?.id?.name === "TmaPage",
).declaration;
const management = page.body.body
  .flatMap((node) => node.declarations || [])
  .find((node) => node.id.name === "canManage");
assert.ok(management, "The TMA page must expose manager-aware actions.");

function canManage({ role = "teacher", assignment, actorId }) {
  return runInNewContext(source.slice(...management.init.range), {
    role,
    assignment,
    actorId,
  });
}

test("admin retains supreme management, regardless of assigned lead", () => {
  const assignment = {
    created_by_actor_type: "tenant_admin",
    created_by_actor_id: "admin-1",
    lead_teacher_membership_id: "teacher-1",
  };
  assert.equal(canManage({ role: "admin", assignment, actorId: "admin-2" }), true);
});

test("only assigned lead gets lifecycle controls on an admin-authored TMA", () => {
  const assignment = {
    created_by_actor_type: "tenant_admin",
    created_by_actor_id: "admin-1",
    lead_teacher_membership_id: "teacher-1",
  };
  assert.equal(canManage({ assignment, actorId: "teacher-1" }), true);
  assert.equal(canManage({ assignment, actorId: "teacher-2" }), false);
});

test("legacy teacher-created assignments retain the creator as lead", () => {
  const assignment = {
    created_by_actor_type: "teacher",
    created_by_actor_id: "teacher-1",
    lead_teacher_membership_id: null,
  };
  assert.equal(canManage({ assignment, actorId: "teacher-1" }), true);
  assert.equal(canManage({ assignment, actorId: "teacher-2" }), false);
  assignment.lead_teacher_membership_id = "teacher-2";
  assert.equal(canManage({ assignment, actorId: "teacher-1" }), false);
  assert.equal(canManage({ assignment, actorId: "teacher-2" }), true);
});

test("admin assignment form selects an eligible teacher and submits the chosen ID", () => {
  assert.match(source, /label="Lead teacher"/);
  assert.match(source, /config\.lead_teachers/);
  assert.match(source, /teacher\.academic_level_id === level|item\.academic_level_id === level/);
  assert.match(source, /item\.curriculum_subject_id === subject/);
  assert.match(source, /lead_teacher_membership_id: lead \|\| null/);
  assert.match(source, /visible: canManage && \["draft", "active", "closed"\]/);
});
