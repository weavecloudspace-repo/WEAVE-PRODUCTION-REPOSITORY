import assert from "node:assert/strict";
import test from "node:test";

import {
  canPlaceStudentInClass,
  eligibleInitialPlacementClasses,
  needsInitialClassPlacement,
} from "../../src/pages/admin/studentInitialPlacement.js";

const openSession = { id: "session-1", is_current: true, status: "open" };
const classlessStudent = {
  id: "student-1",
  academic_level_id: "level-1",
  class_id: null,
  status: "active",
  is_archived: false,
  upcoming_enrollment: null,
};

test("initial placement is offered only for students with a level and no class", () => {
  assert.equal(needsInitialClassPlacement(classlessStudent), true);
  assert.equal(needsInitialClassPlacement({ ...classlessStudent, class_id: "class-1" }), false);
  assert.equal(needsInitialClassPlacement({ ...classlessStudent, academic_level_id: null }), false);
  assert.equal(needsInitialClassPlacement(null), false);
});

test("initial placement respects session, lifecycle and scheduled-enrollment guards", () => {
  assert.equal(canPlaceStudentInClass(classlessStudent, openSession), true);
  assert.equal(canPlaceStudentInClass({ ...classlessStudent, status: "suspended" }, openSession), true);
  assert.equal(canPlaceStudentInClass({ ...classlessStudent, status: "withdrawn" }, openSession), false);
  assert.equal(canPlaceStudentInClass({ ...classlessStudent, is_archived: true }, openSession), false);
  assert.equal(canPlaceStudentInClass({ ...classlessStudent, class_id: "class-1" }, openSession), false);
  assert.equal(canPlaceStudentInClass({ ...classlessStudent, upcoming_enrollment: { id: "future" } }, openSession), false);
  assert.equal(canPlaceStudentInClass(classlessStudent, { ...openSession, status: "closed" }), false);
  assert.equal(canPlaceStudentInClass(classlessStudent, { ...openSession, is_current: false }), false);
  assert.equal(canPlaceStudentInClass(classlessStudent, null), false);
});

test("initial class options cannot contain another level or an inactive/archived class", () => {
  const classes = [
    { id: "valid-a", academic_level_id: "level-1", is_active: true, archived_at: null },
    { id: "valid-b", academic_level_id: "level-1", is_active: true },
    { id: "other-level", academic_level_id: "level-2", is_active: true },
    { id: "inactive", academic_level_id: "level-1", is_active: false },
    { id: "archived", academic_level_id: "level-1", is_active: true, archived_at: "2026-11-01" },
  ];
  assert.deepEqual(
    eligibleInitialPlacementClasses(classes, "level-1").map(({ id }) => id),
    ["valid-a", "valid-b"],
  );
  assert.deepEqual(eligibleInitialPlacementClasses(null, "level-1"), []);
});
