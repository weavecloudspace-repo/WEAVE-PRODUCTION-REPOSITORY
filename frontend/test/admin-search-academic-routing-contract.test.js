import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const searchServiceSource = fs.readFileSync(
  new URL("../../backend/app/modules/search/service.py", import.meta.url),
  "utf8",
);
const workspaceSearchSource = fs.readFileSync(
  new URL("../src/components/layout/WorkspaceSearch.jsx", import.meta.url),
  "utf8",
);
const detailPageSource = fs.readFileSync(
  new URL("../src/pages/admin/AdminSearchDetailPage.jsx", import.meta.url),
  "utf8",
);

test("tenant-admin search routes academic entities into current Academic Hub workspaces", () => {
  const expectedRoutes = [
    "/admin/academic/classes?view=overview",
    "/admin/academic/subjects?view=overview",
    "/admin/academic/levels?view=overview",
    "/admin/academic/arm-labels?view=overview",
    "/admin/academic/departments?view=pool",
    "/admin/academic/departments?view=availability",
    "/admin/academic/departments?view=placements",
    "/admin/academic/curriculum?view=subjects",
    "/admin/academic/sessions?view=overview",
    "/admin/academic/terms?view=overview",
  ];

  for (const route of expectedRoutes) {
    assert.match(searchServiceSource, new RegExp(route.replace(/[?]/g, "\\?")));
  }

  assert.doesNotMatch(searchServiceSource, /href=f?["'`]\/admin\/classes/);
  assert.doesNotMatch(searchServiceSource, /href=f?["'`]\/admin\/subjects/);
});

test("tenant-admin search covers the refactored academic entity set", () => {
  for (const role of [
    "academic level",
    "arm label",
    "department",
    "level department",
    "curriculum subject",
    "academic session",
    "academic term",
    "class placement",
  ]) {
    assert.match(searchServiceSource, new RegExp(`role=["']${role}["']`));
  }

  assert.match(searchServiceSource, /_balanced_results/);
  assert.match(workspaceSearchSource, /Search people, classes, subjects, departments/);
  assert.match(workspaceSearchSource, /searchWorkspace\(searchRole, trimmed, 16\)/);
});

test("admin search preview opens the owning workspace", () => {
  assert.match(detailPageSource, /Open in workspace/);
  assert.match(detailPageSource, /avatarSrc=\{getAvatarSrcFromRecord\(item\)\}/);
  assert.match(detailPageSource, /size="large"/);
  assert.doesNotMatch(detailPageSource, /Open source page/);
});
