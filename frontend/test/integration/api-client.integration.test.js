import assert from "node:assert/strict";
import test from "node:test";

import {
  importFreshApi,
  installBrowserHarness,
  jsonResponse,
} from "../support/browserHarness.js";

test("route notifications keep destination GETs alive but still cancel reads when leaving", async () => {
  let signal;
  let finish;
  const harness = installBrowserHarness({ fetchImpl: async (_url, init) => {
    signal = init.signal;
    return new Promise((resolve) => { finish = resolve; });
  } });
  harness.window.location.href = "https://weave.test/admin/ai-usage";
  const { api, NAVIGATION_ABORT_EVENT } = await importFreshApi();
  const request = api.get("/ai/admin/quota/actors");
  try {
    harness.window.dispatchEvent(new Event(NAVIGATION_ABORT_EVENT));
    assert.equal(signal.aborted, false);
    harness.window.location.href = "https://weave.test/admin/tma";
    harness.window.dispatchEvent(new Event(NAVIGATION_ABORT_EVENT));
    assert.equal(signal.aborted, true);
  } finally {
    finish(jsonResponse(200, { items: [] }));
    await request;
  }
});

test("an authenticated request refreshes once after 401 and retries with the new token", async () => {
  const calls = [];
  let profileRequestCount = 0;
  const fetchImpl = async (url, init = {}) => {
    calls.push({ url: String(url), init });

    if (String(url).endsWith("/auth/refresh")) {
      return jsonResponse(200, { access_token: "new-access-token" });
    }

    if (String(url).endsWith("/students/me")) {
      profileRequestCount += 1;
      return profileRequestCount === 1
        ? jsonResponse(401, { detail: "expired" })
        : jsonResponse(200, { id: "student-1", first_name: "Grace" });
    }

    throw new Error(`Unexpected request: ${url}`);
  };

  const harness = installBrowserHarness({ fetchImpl });
  const { api, authSession } = await importFreshApi();
  authSession.setToken("old-access-token", { remember: false });

  const profile = await api.get("/students/me");

  assert.deepEqual(profile, { id: "student-1", first_name: "Grace" });
  assert.equal(calls.length, 3);
  assert.equal(calls[0].init.headers.Authorization, "Bearer old-access-token");
  assert.equal(calls[0].init.credentials, "include");
  assert.equal(calls[1].url, "https://api.weave.test/api/v1/auth/refresh");
  assert.equal(calls[1].init.credentials, "include");
  assert.equal(calls[1].init.headers["x-weave-csrf"], "1");
  assert.equal(calls[2].init.headers.Authorization, "Bearer new-access-token");
  assert.equal(harness.sessionStorage.getItem("access_token"), "new-access-token");
});

test("concurrent 401 responses share one refresh request", async () => {
  const attempts = new Map();
  let refreshCalls = 0;
  let releaseRefresh;
  const refreshResponse = new Promise((resolve) => {
    releaseRefresh = () => resolve(jsonResponse(200, { access_token: "shared-token" }));
  });

  const fetchImpl = async (url) => {
    const pathname = new URL(String(url)).pathname;
    if (pathname.endsWith("/auth/refresh")) {
      refreshCalls += 1;
      return refreshResponse;
    }

    const count = (attempts.get(pathname) || 0) + 1;
    attempts.set(pathname, count);
    return count === 1
      ? jsonResponse(401, { detail: "expired" })
      : jsonResponse(200, { pathname });
  };

  installBrowserHarness({ fetchImpl });
  const { api, authSession } = await importFreshApi();
  authSession.setToken("expired-token", { remember: true });

  const first = api.get("/students/me");
  const second = api.get("/teachers/me");
  await new Promise((resolve) => setImmediate(resolve));
  releaseRefresh();

  const [student, teacher] = await Promise.all([first, second]);

  assert.equal(refreshCalls, 1);
  assert.equal(student.pathname, "/api/v1/students/me");
  assert.equal(teacher.pathname, "/api/v1/teachers/me");
});

test("JSON and multipart requests preserve the backend transport contract", async () => {
  const calls = [];
  const fetchImpl = async (url, init = {}) => {
    calls.push({ url: String(url), init });
    return jsonResponse(200, { ok: true });
  };

  installBrowserHarness({ fetchImpl });
  const { api } = await importFreshApi();

  await api.post(
    "/auth/login",
    { identifier: "admin@example.com", password: "secret" },
    { auth: false, skipAuthRefresh: true },
  );
  const formData = new FormData();
  formData.set("file", new Blob(["student data"]), "students.csv");
  await api.postForm("/tenant-admin/bulk-imports/students", formData);

  assert.equal(calls[0].init.method, "POST");
  assert.equal(calls[0].init.credentials, "include");
  assert.equal(calls[0].init.headers["Content-Type"], "application/json");
  assert.deepEqual(JSON.parse(calls[0].init.body), {
    identifier: "admin@example.com",
    password: "secret",
  });
  assert.equal(calls[1].init.body, formData);
  assert.equal(new Headers(calls[1].init.headers).has("content-type"), false);
});

test("request params are serialized into the fetch URL", async () => {
  let requestedUrl = "";
  const fetchImpl = async (url) => {
    requestedUrl = String(url);
    return jsonResponse(200, { ok: true });
  };

  installBrowserHarness({ fetchImpl });
  const { api } = await importFreshApi();

  await api.get("/tenant-admin/media/assets/current", {
    params: {
      owner_type: "tenant_admin",
      owner_id: "admin-123",
      purpose: "tenant_admin_passport",
    },
  });

  const url = new URL(requestedUrl);
  assert.equal(url.pathname, "/api/v1/tenant-admin/media/assets/current");
  assert.equal(url.searchParams.get("owner_type"), "tenant_admin");
  assert.equal(url.searchParams.get("owner_id"), "admin-123");
  assert.equal(url.searchParams.get("purpose"), "tenant_admin_passport");
});

test("blob responses use the same authenticated request pipeline", async () => {
  const calls = [];
  const expected = "spreadsheet-data";
  const fetchImpl = async (url, init = {}) => {
    calls.push({ url: String(url), init });
    return new Response(expected, {
      status: 200,
      headers: { "content-type": "application/octet-stream" },
    });
  };

  installBrowserHarness({ fetchImpl });
  const { api, authSession } = await importFreshApi();
  authSession.setToken("download-token", { remember: false });

  const blob = await api.getBlob("/tenant-admin/imports/template/download");

  assert.equal(await blob.text(), expected);
  assert.equal(calls[0].init.credentials, "include");
  assert.equal(calls[0].init.headers.Authorization, "Bearer download-token");
});

test("maintenance responses persist control state and navigate away from protected UI", async () => {
  const fetchImpl = async () =>
    jsonResponse(503, {
      maintenance_mode: true,
      detail: "Scheduled platform maintenance",
      maintenance_reason: "database-upgrade",
    });

  const harness = installBrowserHarness({ fetchImpl });
  const { api, APP_NAVIGATE_EVENT, getStoredMaintenanceState } = await importFreshApi();
  let navigation;
  harness.window.addEventListener(APP_NAVIGATE_EVENT, (event) => {
    navigation = event.detail;
  });

  await assert.rejects(() => api.get("/students/me"), /Scheduled platform maintenance/);

  assert.equal(getStoredMaintenanceState().reason, "database-upgrade");
  assert.deepEqual(navigation, { path: "/maintenance" });
});

test("a failed refresh clears the session and dispatches login navigation", async () => {
  const fetchImpl = async (url) => {
    if (String(url).endsWith("/auth/refresh")) {
      return jsonResponse(401, { detail: "refresh expired" });
    }
    return jsonResponse(401, { detail: "access expired" });
  };

  const harness = installBrowserHarness({ fetchImpl });
  const { api, authSession, APP_NAVIGATE_EVENT } = await importFreshApi();
  authSession.setToken("expired-token", { remember: false });
  authSession.setUser({ id: "student-1", role: "student" }, { remember: false });
  let navigation;
  harness.window.addEventListener(APP_NAVIGATE_EVENT, (event) => {
    navigation = event.detail;
  });

  await assert.rejects(() => api.get("/students/me"), /refresh expired/);

  assert.equal(authSession.getToken(), null);
  assert.equal(authSession.getUser(), null);
  assert.deepEqual(navigation, { path: "/login" });
});
