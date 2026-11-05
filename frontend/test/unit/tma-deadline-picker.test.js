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

test("TMA deadline popup escapes scroll clipping without breaking modal interactions", async () => {
 const modal = await readFile(new URL("../../src/components/ui/Modal.jsx", import.meta.url), "utf8");
 const css = await readFile(new URL("../../src/features/tma/tma-deadline-picker.css", import.meta.url), "utf8");
 assert.match(picker, /createPortal\(/);
 assert.match(picker, /closest\('\[data-modal-overlay="true"\]'\)/);
 assert.match(picker, /positionDeadlinePopover/);
 assert.match(picker, /popover\.current\?\.contains\(event\.target\)/);
 assert.match(picker, /event\.stopPropagation\(\)/);
 assert.match(picker, /visibility: placement \? "visible" : "hidden"/);
 assert.match(modal, /querySelector\("\[data-modal-popover\]"\)/);
 assert.match(css, /\.tma-deadline-popover\{position:fixed;/);
 assert.match(css, /overflow-y:auto/);
});
