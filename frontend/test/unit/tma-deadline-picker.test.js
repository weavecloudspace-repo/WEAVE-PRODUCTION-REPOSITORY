import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
const picker = await readFile(new URL("../../src/features/tma/TmaDeadlinePicker.jsx", import.meta.url), "utf8");
const form = await readFile(new URL("../../src/features/tma/TmaPage.jsx", import.meta.url), "utf8");
test("TMA uses a branded calendar and time dropdown instead of native datetime-local", () => {
 assert.match(form, /<TmaDeadlinePicker/);
 assert.doesNotMatch(form, /type="datetime-local"/);
 assert.match(picker, /Submission deadline calendar/);
 assert.match(picker, /Previous month/);
 assert.match(picker, /Next month/);
 assert.match(picker, /Deadline hour/);
 assert.match(picker, /Deadline minute/);
 assert.match(picker, /formatDeadlineLocal/);
 assert.match(form, /deadlineTime <= Date.now\(\)/);
});
