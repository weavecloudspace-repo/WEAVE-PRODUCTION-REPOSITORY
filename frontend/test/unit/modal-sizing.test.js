import assert from "node:assert/strict";
import test from "node:test";
import { modalWidthClass } from "../../src/utils/modalSizing.js";

test("standard dialogs retain their default width", () => {
  assert.equal(modalWidthClass(), "max-w-lg");
  assert.equal(modalWidthClass("rounded-xl min-w-0"), "max-w-lg");
});

test("explicit dialog widths never compete with the default", () => {
  for (const width of ["max-w-sm", "max-w-3xl", "max-w-6xl", "max-w-none", "max-w-[92vw]", "!max-w-4xl"]) {
    assert.equal(modalWidthClass(`shadow-sm ${width} p-0`), "", width);
  }
});

test("responsive width overrides keep the base width below their breakpoint", () => {
  assert.equal(modalWidthClass("md:max-w-6xl lg:max-w-7xl"), "max-w-lg");
  assert.equal(modalWidthClass("max-w-md md:max-w-6xl"), "");
});
