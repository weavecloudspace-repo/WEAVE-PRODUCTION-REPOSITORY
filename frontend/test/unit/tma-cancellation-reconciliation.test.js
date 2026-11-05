import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const ui = await readFile(new URL("../../src/features/tma/TmaPage.jsx", import.meta.url), "utf8");
const api = await readFile(new URL("../../src/services/tmaService.js", import.meta.url), "utf8");
const panel = await readFile(new URL("../../src/features/tma/TmaReconciliationPanel.jsx", import.meta.url), "utf8");

test("failed cancellation exposes audited conflict details rather than auto-overriding", () => {
  assert.match(ui, /Inspect cancellation conflicts/);
  assert.match(ui, /service\.cancellationConflicts\(assignmentId\)/);
  assert.match(panel, /Resolve the affected results using the normal academic approval\/reopen workflow/);
  assert.match(api, /cancellationConflicts/);
});
