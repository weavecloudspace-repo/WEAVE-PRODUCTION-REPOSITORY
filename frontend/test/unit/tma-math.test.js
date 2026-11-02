import assert from "node:assert/strict";
import test from "node:test";
import { splitMathSegments } from "../../src/features/tma/mathText.js";

test("TMA handles inline, display and undelimited CBT equations without changing source", () => {
  const source = "Solve \\(x^2\\) then $$y=2$$ and \\frac{1}{2}.";
  const parts = splitMathSegments(source);
  assert.deepEqual(parts.filter((p) => p.math).map((p) => [p.text, Boolean(p.display)]), [["x^2", false], ["y=2", true], ["\\frac{1}{2}", false]]);
  assert.equal(source, "Solve \\(x^2\\) then $$y=2$$ and \\frac{1}{2}.");
});

test("currency, Unicode symbols and HTML remain literal text", () => {
  for (const text of ["Pay $10 and $20", "π × 2 ≤ √9", "<img onerror=alert(1)>"]) {
    assert.equal(splitMathSegments(text).map((p) => p.text).join(""), text);
    assert.equal(splitMathSegments(text).some((p) => p.math), false);
  }
});
