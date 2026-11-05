import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";

import { resultLifecycleOptions } from "../../src/features/academic-admin/resultLifecycleOptions.js";

const menuSource = await readFile(
  new URL("../../src/features/academic-admin/ResultLifecycleMenu.jsx", import.meta.url),
  "utf8",
);
const workspaceSource = await readFile(
  new URL("../../src/features/academic-admin/ResultsWorkspace.jsx", import.meta.url),
  "utf8",
);
const dropdownSource = await readFile(
  new URL("../../src/components/ui/Dropdown.jsx", import.meta.url),
  "utf8",
);

test("result lifecycle options expose legal forward or corrective transitions", () => {
  const keys = (status) => resultLifecycleOptions(status).map((action) => action.key);
  assert.deepEqual(keys("draft"), ["edit", "submitted"]);
  assert.deepEqual(keys("submitted"), ["approved", "return_to_draft"]);
  assert.deepEqual(keys("approved"), ["locked", "return_to_draft"]);
  assert.deepEqual(keys("locked"), ["return_to_draft"]);
  assert.deepEqual(keys("unknown"), []);
});

test("lifecycle uses existing overflow menu with viewport-aware flip and keyboard support", () => {
  assert.match(menuSource, /<Dropdown[\s\S]*strategy="fixed"/);
  assert.match(menuSource, /<MoreHorizontal/);
  assert.match(menuSource, /aria-label=\{`Manage result for/);
  assert.match(menuSource, /aria-haspopup="menu"/);
  assert.match(menuSource, /role="menu"/);
  assert.match(menuSource, /ArrowDown/);
  assert.match(menuSource, /Escape/);
  assert.match(dropdownSource, /shouldOpenUp/);
  assert.match(dropdownSource, /window.addEventListener\("scroll", updateFixedPosition, true\)/);
  assert.match(workspaceSource, /<ResultLifecycleMenu/);
  assert.doesNotMatch(workspaceSource, /function ResultActions\(/);
});

test("return to draft always requires a reason and reuses audit-safe reopen API", () => {
  assert.match(workspaceSource, /reopenReason\.trim\(\)\.length < 3/);
  assert.match(workspaceSource, /academicService\.reopenResult\(reopenTarget\.id/);
  assert.match(workspaceSource, /title=\{reopenTarget\?\.status === "locked"/);
  assert.match(menuSource, /onReturnToDraft\(\)/);
  assert.match(menuSource, /disabled=\{!periodEditable \|\| busy\}/);
});
