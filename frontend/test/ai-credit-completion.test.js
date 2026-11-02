import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("AI completion is public and cannot trigger payment verification or settlement", async () => {
  const routes = await read("src/routes/publicRoutes.jsx");
  const page = await read("src/pages/public/AICreditCompletePage.jsx");
  assert.match(routes, /path="\/payments\/ai-credits\/complete" element={<AICreditCompletePage \/>}/);
  // Keep this informational page independent of authenticated payment code.
  assert.deepEqual([...page.matchAll(/from "([^"]+)"/g)].map((match) => match[1]), ["../../components/brand/WeaveIcon"]);
  assert.doesNotMatch(page, /\bfetch\s*\(|\buseEffect\b|localStorage|sessionStorage/);
  assert.doesNotMatch(page, /SubscriptionVerify|verifyTermPayment|authorization|access_token/);
  assert.doesNotMatch(page, /Payment successful|Payment confirmed|Credits added/i);
  assert.match(page, /Return to Weave/);
  assert.doesNotMatch(page, /window\.close|handleCloseTab|<Button/);
  assert.match(page, /You can close this tab and return to Weave/);
});
