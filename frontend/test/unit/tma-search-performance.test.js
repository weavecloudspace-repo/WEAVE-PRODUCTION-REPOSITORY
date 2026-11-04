import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { tmaReadRequest } from "../../src/services/tmaReadRequest.js";

const source = (file) => readFile(new URL(`../../src/${file}`, import.meta.url), "utf8");

test("TMA search retains its controls while independently fetching result pages", async () => {
  const page = await source("features/tma/TmaPage.jsx");
  const bootstrap = page.slice(page.indexOf("const load = useCallback("), page.indexOf("// Searching updates only results"));
  const results = page.slice(page.indexOf("// Searching updates only results"), page.indexOf("setDraft(null);"));
  assert.match(bootstrap, /service\.configuration\(\)/);
  assert.match(bootstrap, /service\.terms\(\)/);
  assert.doesNotMatch(bootstrap, /service\.list\(/);
  assert.match(results, /service\.list\(offset, termId/);
  assert.doesNotMatch(results, /setLoading\(true\)/);
  assert.match(results, /setListLoading\(true\)/);
  assert.match(page, /\{listLoading && <p role="status"/);
  assert.match(page, /!visibleList\.length && !listLoading/);
});

test("TMA submissions are debounced, cancellable and retain previous results while loading", async () => {
  const page = await source("features/tma/TmaPage.jsx");
  const service = await source("services/tmaService.js");
  assert.match(page, /setDebouncedSubmissionQuery\(search\.trim\(\)\), 300/);
  assert.match(page, /search: debouncedSubmissionQuery/);
  assert.match(page, /setSubmissionLoading\(true\)/);
  assert.match(page, /controller\.abort\(\)/);
  assert.doesNotMatch(page, /setReport\(null\);\s*service\s*\.submissions/);
  assert.match(service, /submissions: \(id, params, options = \{\}\)/);
});

test("read wrapper relays caller cancellation into its transport and rejects", async () => {
  const caller = new AbortController();
  let downstream;
  const request = tmaReadRequest((signal) => {
    downstream = signal;
    return new Promise((_, reject) =>
      signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true }),
    );
  }, { signal: caller.signal });
  await new Promise((resolve) => setImmediate(resolve));
  caller.abort();
  await assert.rejects(request, { name: "AbortError" });
  assert.equal(downstream.aborted, true);
});
