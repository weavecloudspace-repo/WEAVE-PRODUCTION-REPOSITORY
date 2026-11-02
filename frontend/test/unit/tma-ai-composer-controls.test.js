import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = await readFile(
  new URL("../../src/features/tma/TmaAIComposer.jsx", import.meta.url),
  "utf8",
);

test("TMA AI composer uses a CBT-style difficulty slider and image options", () => {
  assert.match(source, /difficultyOptions = \["easy", "medium", "difficult"\]/);
  assert.match(source, /type="range"/);
  assert.match(source, /aria-valuetext=\{difficulty\}/);
  assert.match(source, /setDifficulty\(difficultyOptions\[Number\(e\.target\.value\)\]\)/);
  assert.match(source, /\["text_only", "Text only"\]/);
  assert.match(source, /\["auto", "Allow images"\]/);
  assert.match(source, /visual_mode: visuals/);
  assert.doesNotMatch(source, /name="tma-difficulty"/);
});
