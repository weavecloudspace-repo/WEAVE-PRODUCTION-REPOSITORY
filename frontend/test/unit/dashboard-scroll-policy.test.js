import assert from "node:assert/strict";
import test from "node:test";
import { shouldResetDashboardScroll } from "../../src/utils/dashboardScroll.js";

const location = (pathname, search = "", hash = "") => ({ pathname, search, hash });
const docs = "/admin/cbt/documentation";

test("documentation topic and command-group navigation does not reset the dashboard", () => {
  const previous = location(docs, "?topic=cli&group=logs", "#cli-logs");
  for (const next of [
    location(docs, "?topic=windows"),
    location(docs, "?topic=cli&group=networking", "#cli-networking"),
    location(docs, "?topic=cli&group=logs", "#cli-intro"),
    previous,
  ]) assert.equal(shouldResetDashboardScroll(previous, next), false);
});

test("entering documentation resets normal entry but leaves deep links to the article", () => {
  for (const previous of [null, location("/admin/cbt/setup-server")]) {
    assert.equal(shouldResetDashboardScroll(previous, location(docs)), true);
    assert.equal(shouldResetDashboardScroll(previous, location(docs, "?topic=cli&group=logs", "#cli-logs")), false);
  }
});

test("other dashboard routes retain resets for page and query changes", () => {
  assert.equal(shouldResetDashboardScroll(location(docs), location("/admin/cbt/setup-server")), true);
  assert.equal(shouldResetDashboardScroll(location("/admin/students", "?page=1"), location("/admin/students", "?page=2")), true);
  assert.equal(shouldResetDashboardScroll(null, location("/admin/dashboard")), true);
  assert.equal(shouldResetDashboardScroll(location("/admin/students"), location("/admin/students", "", "#details")), false);
});
