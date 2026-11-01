import assert from "node:assert/strict";
import test from "node:test";
import { tmaReadRequest } from "../../src/services/tmaReadRequest.js";
import { installBrowserHarness } from "../support/browserHarness.js";

test("destination-page reads survive the route notification and abort only when leaving", async () => {
  const harness = installBrowserHarness();
  harness.window.location.href = "https://weave.test/admin/tma";
  let signal;
  let finish;
  const request = tmaReadRequest((value) => {
    signal = value;
    return new Promise((resolve) => { finish = resolve; });
  });
  await new Promise((resolve) => setImmediate(resolve));
  try {
    harness.window.dispatchEvent(new Event("weave:navigation-start"));
    assert.equal(signal.aborted, false);
    harness.window.location.href = "https://weave.test/admin/dashboard";
    harness.window.dispatchEvent(new Event("weave:navigation-start"));
    assert.equal(signal.aborted, true);
  } finally {
    finish([]);
    await request;
  }
});

test("an unfinished TMA read rejects and aborts instead of leaving the loader pending", async () => {
  let signal;
  const request = tmaReadRequest(
    (value) => {
      signal = value;
      return new Promise(() => {});
    },
    { timeoutMs: 10 },
  );
  await assert.rejects(request, /took too long to load/);
  assert.equal(signal.aborted, true);
});

test("successful reads, including an empty assignment page, retain their response", async () => {
  const page = { items: [], total: 0, offset: 0, limit: 24 };
  let signal;
  assert.equal(
    await tmaReadRequest((value) => {
      signal = value;
      return Promise.resolve(page);
    }),
    page,
  );
  assert.equal(signal.aborted, false);
});

test("backend errors are preserved and retry uses a fresh request signal", async () => {
  const backendError = new Error("Assignment list unavailable");
  await assert.rejects(
    tmaReadRequest(() => Promise.reject(backendError)),
    (error) => error === backendError,
  );
  let expired;
  await assert.rejects(
    tmaReadRequest(
      (signal) => {
        expired = signal;
        return new Promise(() => {});
      },
      { timeoutMs: 10 },
    ),
  );
  await tmaReadRequest((signal) => {
    assert.notEqual(signal, expired);
    assert.equal(signal.aborted, false);
    return [];
  });
});
