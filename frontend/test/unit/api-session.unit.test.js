import assert from "node:assert/strict";
import test from "node:test";

import {
  createJwt,
  importFreshApi,
  installBrowserHarness,
  jsonResponse,
} from "../support/browserHarness.js";

test("authSession normalizes tenant-admin identity and respects persistence choice", async () => {
  const harness = installBrowserHarness();
  const { authSession } = await importFreshApi();

  authSession.setUser(
    {
      id: "admin-1",
      first_name: "Ada",
      last_name: "Lovelace",
      actor_type: "tenant_admin",
    },
    { remember: false },
  );

  assert.deepEqual(authSession.getUser(), {
    id: "admin-1",
    first_name: "Ada",
    last_name: "Lovelace",
    firstname: "Ada",
    lastname: "Lovelace",
    actor_type: "tenant_admin",
    role: "admin",
  });
  assert.equal(harness.sessionStorage.getItem("auth_role"), "admin");
  assert.equal(harness.localStorage.getItem("auth_user"), null);
});

test("authSession keeps access tokens session-only and schedules proactive refresh", async () => {
  const harness = installBrowserHarness();
  const { authSession } = await importFreshApi();
  const token = createJwt({ exp: Math.floor(Date.now() / 1000) + 600 });

  authSession.setToken(token, { remember: true });

  assert.equal(harness.sessionStorage.getItem("access_token"), token);
  assert.equal(harness.localStorage.getItem("access_token"), null);
  assert.equal(harness.localStorage.getItem("auth_remember"), "true");
  assert.equal(harness.window.__timers.size, 1);
});

test("authSession notifies realtime consumers when tokens rotate or clear", async () => {
  installBrowserHarness();
  const { authSession } = await importFreshApi();
  const received = [];
  const unsubscribe = authSession.subscribeToken((token) => received.push(token));
  const token = createJwt({ exp: Math.floor(Date.now() / 1000) + 600 });

  authSession.setToken(token);
  authSession.clearToken();
  unsubscribe();
  authSession.setToken(token);

  assert.deepEqual(received, [token, null]);
});

test("cookie-auth refresh and logout requests include the CSRF protection header", async () => {
  const calls = [];
  installBrowserHarness({
    fetchImpl: async (url, options = {}) => {
      calls.push({ url, options });
      return jsonResponse(200, {});
    },
  });
  const { api } = await importFreshApi();

  await api.post("/auth/refresh", undefined, {
    auth: false,
    clearAuthOnUnauthorized: false,
    skipAuthRefresh: true,
  });
  await api.post("/auth/logout", undefined, {
    auth: false,
    clearAuthOnUnauthorized: false,
    skipAuthRefresh: true,
  });

  assert.equal(calls.length, 2);
  for (const call of calls) {
    assert.equal(call.options.credentials, "include");
    assert.equal(call.options.headers["x-weave-csrf"], "1");
  }
});

test("automatic access-token refresh includes the CSRF protection header", async () => {
  const calls = [];
  const refreshedToken = createJwt({ exp: Math.floor(Date.now() / 1000) + 600 });
  installBrowserHarness({
    fetchImpl: async (url, options = {}) => {
      calls.push({ url, options });
      if (url.endsWith("/auth/refresh")) {
        return jsonResponse(200, { access_token: refreshedToken });
      }
      if (calls.filter((call) => call.url.endsWith("/protected")).length === 1) {
        return jsonResponse(401, { detail: "expired" });
      }
      return jsonResponse(200, { ok: true });
    },
  });
  const { api, authSession } = await importFreshApi();
  authSession.setToken(createJwt({ exp: Math.floor(Date.now() / 1000) + 600 }));

  const response = await api.get("/protected");

  assert.deepEqual(response, { ok: true });
  const refreshCall = calls.find((call) => call.url.endsWith("/auth/refresh"));
  assert.ok(refreshCall);
  assert.equal(refreshCall.options.credentials, "include");
  assert.equal(refreshCall.options.headers["x-weave-csrf"], "1");
});

test("parseApiError maps FastAPI validation details and verification metadata", async () => {
  installBrowserHarness();
  const { parseApiError, remapFieldErrors } = await importFreshApi();

  const parsed = parseApiError({
    response: {
      status: 422,
      headers: {
        "x-verification-required": "true",
        "x-email": "admin@example.com",
      },
      data: {
        detail: [
          { loc: ["body", "new_password"], msg: "String is too short" },
          { loc: ["body", "new_password"], msg: "Must contain a number" },
        ],
      },
    },
  });

  assert.equal(parsed.status, 422);
  assert.equal(parsed.verificationRequired, true);
  assert.equal(parsed.email, "admin@example.com");
  assert.deepEqual(parsed.fieldErrors, {
    new_password: "String is too short, Must contain a number",
  });
  assert.deepEqual(remapFieldErrors(parsed.fieldErrors, { new_password: "password" }), {
    password: "String is too short, Must contain a number",
  });
});

test("parseApiError never exposes technical backend details to users", async () => {
  installBrowserHarness();
  const { parseApiError } = await importFreshApi();

  const parsed = parseApiError({
    message: "request failed",
    response: {
      status: 500,
      headers: {},
      data: { detail: "SQLAlchemy asyncpg traceback leaked from production" },
    },
  });

  assert.equal(
    parsed.message,
    "Something went wrong while processing your request. Please try again.",
  );
  assert.equal(parsed.technicalMessage, "request failed");
});

test("abort errors remain silent and are not classified as network failures", async () => {
  installBrowserHarness();
  const { parseApiError } = await importFreshApi();
  const abortError = new Error("The operation was aborted");
  abortError.name = "AbortError";

  const parsed = parseApiError(abortError);

  assert.equal(parsed.isAbortError, true);
  assert.equal(parsed.isNetworkError, false);
  assert.equal(parsed.message, "");
});

test("real HTTP 409 conflicts mentioning cancelled are not mistaken for request aborts", async () => {
  installBrowserHarness();
  const { getErrorMessage, isAbortError } = await importFreshApi();
  const error = new Error("TMA cannot be reopened while cancellation is pending.");
  error.response = {
    status: 409,
    headers: {},
    data: { detail: "TMA cannot be reopened while cancellation is pending." },
  };
  assert.equal(isAbortError(error), false);
  assert.equal(getErrorMessage(error), "TMA cannot be reopened while cancellation is pending.");
  assert.equal(isAbortError(new DOMException("The operation was aborted", "AbortError")), true);
});
