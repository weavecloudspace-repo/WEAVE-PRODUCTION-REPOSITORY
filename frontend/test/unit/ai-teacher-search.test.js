import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = await readFile(
  new URL("../../src/features/ai/AIUsagePage.jsx", import.meta.url),
  "utf8",
);

test("admin AI dashboard provides teacher name and email searches", () => {
  assert.match(source, /aria-label="Search staff AI credits"/);
  assert.match(source, /aria-label="Search teacher credit requests"/);
  assert.match(source, /filteredActors\.map/);
  assert.match(source, /filteredRequests\.map/);
  assert.match(source, /staffSearch, item\.display_name, item\.email/);
  assert.match(source, /requestSearch, item\.requester_name, item\.requester_email/);
  assert.match(source, /toLocaleLowerCase\(\)\.includes\(term\)/);
});
