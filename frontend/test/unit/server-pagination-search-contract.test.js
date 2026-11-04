import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(`../../src/${path}`, import.meta.url), "utf8");

test("Academic Hub RecordList does not filter a server-paginated slice", async () => {
  const shared = await read("features/academic-admin/AcademicWorkspacePrimitives.jsx");
  assert.match(shared, /if \(serverSearch\) return records;/);
  for (const path of [
    "features/academic-admin/ResultsWorkspace.jsx",
    "features/academic-admin/ReportCardsWorkspace.jsx",
    "features/academic-admin/TeacherAssignmentsWorkspace.jsx",
  ]) {
    const source = await read(path);
    assert.match(source, /onSearchChange=\{/);
    assert.match(source, /searchValue=\{/);
  }
});

test("search and pagination use the same backend result set", async () => {
  const tma = await read("features/tma/TmaPage.jsx");
  const api = await read("services/tmaService.js");
  assert.match(tma, /search: debouncedQuery/);
  assert.match(tma, /academic_level_id: levelFilter/);
  assert.match(api, /params\.set\("status", filters\.status\)/);
  assert.doesNotMatch(tma, /const visibleList = list\.filter/);

  const results = await read("features/academic-admin/ResultsWorkspace.jsx");
  const cards = await read("features/academic-admin/ReportCardsWorkspace.jsx");
  const teacher = await read("features/academic-admin/TeacherAssignmentsWorkspace.jsx");
  assert.match(results, /search: appliedResultSearch/);
  assert.match(cards, /search: appliedCardSearch/);
  assert.match(teacher, /search: appliedAssignmentSearch/);
});

test("invitations and conversations search before backend pagination", async () => {
  const invitations = await read("pages/admin/MembershipDirectoryPage.jsx");
  assert.match(invitations, /search: appliedSearch\.trim\(\)/);
  assert.doesNotMatch(invitations, /nextItems = nextItems\.filter/);
  const messages = await read("pages/shared/MessagesPage.jsx");
  assert.match(messages, /search: appliedSidebarSearch/);
  assert.match(messages, /counterpart_type: sidebarRole/);
  assert.doesNotMatch(messages, /return conversations\.filter/);
});
