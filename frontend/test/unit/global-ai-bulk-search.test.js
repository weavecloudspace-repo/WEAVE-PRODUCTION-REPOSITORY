import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  BULK_IMPORT_HISTORY_PAGE_SIZE,
  createHistoryQuery,
  loadImportHistoryPage,
} from "../../src/pages/admin/bulkImportPageLogic.js";

const read = (path) => readFile(new URL(`../../src/${path}`, import.meta.url), "utf8");

test("history search includes the filename before paging, with correct total", async () => {
  const calls = [];
  let items;
  let total;
  await loadImportHistoryPage({
    listJobs: async (params) => {
      calls.push(params);
      return { items: [{ id: "later-record" }], total: 1 };
    },
    skip: 0,
    status: "completed",
    search: "later.csv",
    setJobs: (v) => { items = v; },
    setJobsTotal: (v) => { total = v; },
    setHistorySkip: () => {},
    setHistoryLoading: () => {},
  });
  assert.deepEqual(calls, [{
    skip: 0,
    limit: BULK_IMPORT_HISTORY_PAGE_SIZE,
    status: "completed",
    search: "later.csv",
  }]);
  assert.deepEqual(items, [{ id: "later-record" }]);
  assert.equal(total, 1);
  assert.deepEqual(createHistoryQuery({ skip: 20, status: "", search: "  " }), {
    skip: 20,
    limit: BULK_IMPORT_HISTORY_PAGE_SIZE,
    status: undefined,
  });
});

test("stale search responses cannot overwrite newer history pages", async () => {
  let updated = false;
  await loadImportHistoryPage({
    listJobs: async () => ({ items: [{ id: "stale" }], total: 99 }),
    skip: 20,
    status: "",
    search: "old",
    isCurrent: () => false,
    setJobs: () => { updated = true; },
    setJobsTotal: () => { updated = true; },
    setHistorySkip: () => { updated = true; },
    setHistoryLoading: () => {},
  });
  assert.equal(updated, false);
});

test("AI staff and request search use independent server pages", async () => {
  const ai = await read("features/ai/AIUsagePage.jsx");
  assert.match(ai, /offset: String\(staffPage \* PAGE_SIZE\)/);
  assert.match(ai, /offset: String\(requestPage \* PAGE_SIZE\)/);
  assert.match(ai, /params\.set\("search", staffQuery\)/);
  assert.match(ai, /params\.set\("search", requestQuery\)/);
  assert.match(ai, /weekly_used_credits_total/);
  assert.doesNotMatch(ai, /first 100 staff accounts/);
  const history = await read("pages/admin/BulkImportPage.jsx");
  assert.match(history, /setHistorySkip\(0\); setHistorySearch/);
  assert.doesNotMatch(history, /return jobs\.filter/);
});
