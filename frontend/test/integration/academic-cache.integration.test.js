import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { importFreshApi, installBrowserHarness, jsonResponse } from "../support/browserHarness.js";

async function setup() {
  const harness = installBrowserHarness();
  harness.window.sessionStorage = harness.sessionStorage;
  const { api } = await importFreshApi();
  const source = (await readFile(new URL("../../src/services/dashboardSessionCache.js", import.meta.url), "utf8"))
    .replace('import { authSession } from "./api";', 'const authSession = { getUser: () => ({ role: "admin", tenant_id: "school-1", id: "admin-1" }) };');
  const cache = await import(`data:text/javascript;base64,${Buffer.from(`${source}\n// ${Math.random()}`).toString("base64")}`);
  return { ...harness, api, cache };
}

test("academic edits and lifecycle writes invalidate cached summaries before notifying visible consumers", async () => {
  const { api, cache, window, sessionStorage } = await setup();
  let count = 1;
  const loader = () => cache.getCachedDashboardBundle("metrics:tenant-admin", async () => ({ count }));
  let visible;
  let refresh;
  await cache.getCachedDashboardBundle("hub", loader);
  window.addEventListener("weave:dashboard-cache-invalidated", () => {
    assert.equal(sessionStorage.length, 0);
    refresh = cache.getCachedDashboardBundle("hub", loader).then(data => { visible = data; });
  });
  for (const [method, endpoint] of [
    ["patch", "/academic-levels/level-1"],
    ["post", "/classes/class-1/archive"],
    ["delete", "/subjects/subject-1"],
    ["put", "/tenant-admin/academics/classes/class-1/terms/term-1/departments"],
    ["post", "/tenant-admin/academics/sessions/session-1/open"],
    ["post", "/tenant-admin/setup-assistant/levels/level-1/remove"],
  ]) {
    count++;
    await api[method](endpoint);
    await refresh;
    assert.equal(visible.count, count);
    assert.equal((await cache.getCachedDashboardBundle("hub", loader)).count, count);
  }
});

test("reads, failed writes and unrelated writes do not invalidate academic summaries", async () => {
  const { api, cache, window, setFetch } = await setup();
  await cache.getCachedDashboardBundle("hub", async () => ({ count: 1 }));
  let notifications = 0;
  window.addEventListener("weave:dashboard-cache-invalidated", () => notifications++);
  await api.get("/academic-levels");
  await api.post("/auth/logout");
  await api.patch("/subjects-other/1");
  setFetch(async () => jsonResponse(422, { detail: "Invalid update" }));
  await assert.rejects(api.patch("/academic-levels/1", {}));
  assert.equal(notifications, 0);
  assert.equal((await cache.getCachedDashboardBundle("hub", async () => ({ count: 2 }))).count, 1);
});

test("a pre-mutation request cannot overwrite fresh memory or session snapshots", async () => {
  const { api, cache } = await setup();
  let resolveOld;
  const pending = cache.getCachedDashboardBundle("hub", () => new Promise(resolve => { resolveOld = resolve; }));
  await Promise.resolve();
  await api.post("/subjects/1/restore", {});
  await cache.getCachedDashboardBundle("hub", async () => ({ count: 2 }));
  resolveOld({ count: 1 });
  await pending;
  assert.equal((await cache.getCachedDashboardBundle("hub", () => assert.fail("fresh snapshot expected"))).count, 2);
});


test("student score events evict persisted dashboard bundles on subject pages", async () => {
  const { cache, sessionStorage } = await setup();
  let latestMark = 12;
  const loadDashboard = () =>
    cache.getCachedDashboardBundle("student:dashboard", async () => ({ mark: latestMark }));

  assert.equal((await loadDashboard()).mark, 12);
  assert.ok(sessionStorage.length > 0, "dashboard snapshot should be persisted");

  // Both pages can be active while the dashboard's own WebSocket subscription is unmounted.
  for (const page of ["StudentSubjectsPage.jsx", "StudentSubjectDetailsPage.jsx"]) {
    const source = await readFile(
      new URL(`../../src/pages/student/${page}`, import.meta.url),
      "utf8",
    );
    assert.match(source, /import \{ invalidateDashboardSessionCache \} from "\.\.\/\.\.\/services\/dashboardSessionCache"/);
    assert.match(source, /"academic\.component_score\.updated"/);
    assert.match(source, /const refreshScores = [\s\S]*?invalidateDashboardSessionCache\(\);/);

    latestMark += 1;
    cache.invalidateDashboardSessionCache();
    assert.equal(sessionStorage.length, 0, "old snapshot must be removed");
    assert.equal((await loadDashboard()).mark, latestMark);
  }
});
