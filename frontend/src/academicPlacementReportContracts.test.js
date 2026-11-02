import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const sourceRoot = path.dirname(fileURLToPath(import.meta.url));
const readSource = (...segments) =>
  fs.readFileSync(path.join(sourceRoot, ...segments), "utf8");

test("student service uses only canonical placement contracts", () => {
  const service = readSource("services", "studentService.js");

  assert.match(service, /\/tenant-admin\/students\/class-placement/);
  assert.match(service, /\/placement-history/);
  assert.match(service, /\/placement-impact-preview/);
  assert.match(service, /\/reassign-class/);
  assert.match(service, /\/reassign-academic-level/);
  assert.doesNotMatch(service, /assignClassBatch/);
  assert.doesNotMatch(service, /changeStudentClass/);
  assert.doesNotMatch(service, /batch-class-assignment/);
  assert.doesNotMatch(service, /class-change/);
});

test("student self profile is hydrated from the derived term academic context", () => {
  const service = readSource("services", "studentService.js");

  assert.match(service, /\/students\/me\/academic-context/);
  assert.match(service, /department_name/);
  assert.match(service, /classArmWithDepartment/);
});

test("student directory keeps placement and reassignment responsibilities separate", () => {
  const directory = readSource("pages", "admin", "StudentDirectoryPage.jsx");
  const placementPage = readSource("pages", "admin", "StudentClassPlacementPage.jsx");

  assert.match(directory, /getPlacementHistory/);
  assert.match(directory, /previewPlacementImpact/);
  assert.match(directory, /reassignStudentClass/);
  assert.match(directory, /reassignStudentAcademicLevel/);
  assert.doesNotMatch(directory, /assignClassBatch/);
  assert.match(placementPage, /unassignedClass:\s*true/);
  assert.match(placementPage, /placeStudents/);
});

test("Edit Student offers safe first-class placement without using reassignment", () => {
  const directory = readSource("pages", "admin", "StudentDirectoryPage.jsx");

  assert.match(directory, /needsInitialClassPlacement\(editState\.student\)/);
  assert.match(directory, /eligibleInitialPlacementClasses\(classes, editState\?\.student\?\.academic_level_id\)/);
  assert.match(directory, /canPlaceStudentInClass\(student, initialPlacementSession\)/);
  assert.match(directory, /studentService\.placeStudents\(\{/);
  assert.match(directory, /student_ids:\s*\[student\.id\]/);
  assert.match(directory, /initialClassId:\s*""/);
  assert.match(directory, /profileChanged/);
  assert.match(directory, /Assign class \(optional\)/);
  assert.match(directory, /disabled=\{placementDisabled \|\| Boolean\(student\.upcoming_enrollment\) \|\| !student\.class_id\}/);
});

test("class placement UI exposes only the current open session and paginates the unassigned roster", () => {
  const source = readSource("pages", "admin", "StudentClassPlacementPage.jsx");

  assert.match(source, /item\.is_current/);
  assert.match(source, /toLowerCase\(\) === "open"/);
  assert.match(source, /const PAGE_SIZE = 100/);
  assert.match(source, /skip:\s*\(page - 1\) \* PAGE_SIZE/);
  assert.match(source, /limit:\s*PAGE_SIZE/);
  assert.match(source, /setPage\(1\)/);
  assert.match(source, /setTargetClassId\(""\)/);
  assert.match(source, /\[levelId, sessionId\]/);
  assert.match(source, /\[search\]/);
});

test("report-card workspace uses authoritative readiness and audited teacher overrides", () => {
  const workspace = readSource(
    "features",
    "academic-admin",
    "ReportCardsWorkspace.jsx",
  );

  assert.match(workspace, /report_readiness !== "ready"/);
  assert.match(workspace, /teacher_comment_status/);
  assert.match(workspace, /overrideTeacherComment/);
  assert.match(workspace, /Audit reason/);
  assert.match(workspace, /apply_default_principal_template/);
  assert.match(workspace, /principal_template_id/);
  assert.match(workspace, /Create editable revision/);
  assert.match(workspace, /Regenerate draft/);
  assert.doesNotMatch(workspace, /generate_for_class/);
});

test("class report generation uses the admins performance-range defaults", () => {
  const workspace = readSource(
    "features",
    "academic-admin",
    "ReportCardsWorkspace.jsx",
  );

  assert.match(workspace, /generationTarget === "class"/);
  assert.match(workspace, /payload\.apply_default_principal_template = true/);
  assert.match(
    workspace,
    /Each student receives your default active principal comment for the inclusive performance range/,
  );
});

test("individual principal comment choices are scoped to calculated performance", () => {
  const workspace = readSource(
    "features",
    "academic-admin",
    "ReportCardsWorkspace.jsx",
  );

  assert.match(workspace, /templatesForPerformance/);
  assert.match(workspace, /performance_percentage/);
  assert.match(workspace, /minimum_score/);
  assert.match(workspace, /maximum_score/);
  assert.match(workspace, /principalEditor\.card\.average_score/);
  assert.match(workspace, /Use my performance-range default/);
});

test("teacher navigation and guide expose comments but no score-entry authority", () => {
  const routes = readSource("routes", "teacherRoutes.jsx");
  const nav = readSource("components", "layout", "navConfig.js");
  const guide = readSource("features", "guides", "roleGuideConfig.js");

  assert.match(routes, /student-comments/);
  assert.match(routes, /comment-templates/);
  assert.match(nav, /Student Comments/);
  assert.match(nav, /My Comment Templates/);
  assert.match(guide, /Complete class-teacher comments/);
  assert.doesNotMatch(routes, /score-entry/);
  assert.doesNotMatch(nav, /Score Entry/);
  assert.doesNotMatch(guide, /entering attendance or scores/);
});

test("personal comment editors ask for text and one performance range", () => {
  const admin = readSource(
    "features",
    "academic-admin",
    "CommentTemplatesWorkspace.jsx",
  );
  const teacher = readSource(
    "pages",
    "teacher",
    "TeacherCommentTemplatesPage.jsx",
  );

  for (const source of [admin, teacher]) {
    assert.doesNotMatch(source, /Template name/);
    assert.match(source, /minimum_score/);
    assert.match(source, /maximum_score/);
    assert.match(source, /is_default/);
    assert.match(source, /New range comment/);
    assert.match(source, /Make default/);
    assert.match(source, /default for this exact range/i);
  }
});

test("teacher student-comment picker is scoped to calculated performance", () => {
  const source = readSource(
    "pages",
    "teacher",
    "TeacherStudentCommentsPage.jsx",
  );

  assert.match(source, /listTeacherTemplates/);
  assert.match(source, /overall_grade/);
  assert.match(source, /minimum_score/);
  assert.match(source, /maximum_score/);
  assert.match(source, /Default suggestion/);
  assert.match(source, /editor\.row\.average/);
  assert.doesNotMatch(source, /suggested_template\.name/);
});

test("teacher comment editor is read-only until academic results are ready", () => {
  const source = readSource(
    "pages",
    "teacher",
    "TeacherStudentCommentsPage.jsx",
  );

  assert.match(source, /disabled=\{!editor\.row\.academic_ready\}/);
  assert.match(source, /older draft is preserved for review but remains read-only/);
  assert.match(source, /!editor\.row\.academic_ready/);
  assert.match(source, /finalized and locked/);
});
