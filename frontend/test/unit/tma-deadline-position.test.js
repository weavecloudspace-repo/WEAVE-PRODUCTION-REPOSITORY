import assert from "node:assert/strict";
import test from "node:test";
import { positionDeadlinePopover } from "../../src/features/tma/deadlinePopoverPosition.js";

const viewport = { top: 0, left: 0, width: 1200, height: 800 };
const popup = { width: 342, height: 460 };

test("calendar opens below a trigger when there is room", () => {
  const position = positionDeadlinePopover(
    { top: 90, bottom: 140, left: 120 }, popup, viewport,
  );
  assert.equal(position.top, 148);
  assert.equal(position.left, 120);
  assert.equal(position.maxHeight, 460);
});

test("calendar flips above a low trigger without clipping its bottom", () => {
  const position = positionDeadlinePopover(
    { top: 690, bottom: 740, left: 900 }, popup, viewport,
  );
  assert.equal(position.top, 222);
  assert.equal(position.maxHeight, 460);
  assert.equal(position.left, 846);
});

test("calendar fits a short modal viewport and stays scrollable", () => {
  const position = positionDeadlinePopover(
    { top: 380, bottom: 430, left: 320 },
    popup,
    { top: 0, left: 0, width: 800, height: 580 },
  );
  assert.equal(position.top, 12);
  assert.equal(position.maxHeight, 360);
  assert.ok(position.top + position.maxHeight < 380);
});

test("very short mobile viewport keeps usable calendar inside visible area", () => {
  const v = { top: 64, left: 0, width: 320, height: 330 };
  const position = positionDeadlinePopover(
    { top: 180, bottom: 230, left: 280 }, popup, v,
  );
  assert.equal(position.maxHeight, 306);
  assert.ok(position.top >= v.top + 12);
  assert.ok(position.top + position.maxHeight <= v.top + v.height - 12);
  assert.ok(position.left >= 12);
  assert.ok(position.left + 296 <= v.width - 12);
});

test("calendar stays aligned when the visual viewport is offset", () => {
  const position = positionDeadlinePopover(
    { top: 220, bottom: 266, left: 35 }, popup,
    { top: 80, left: 16, width: 350, height: 450 },
  );
  assert.ok(position.top >= 92);
  assert.ok(position.top + position.maxHeight <= 518);
  assert.ok(position.left >= 28);
});
