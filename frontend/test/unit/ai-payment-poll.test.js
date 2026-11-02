import assert from "node:assert/strict";
import test from "node:test";
import { startPaymentVerificationPoll } from "../../src/features/ai/paymentVerificationPoll.js";

function clock() {
  let time = 0;
  let id = 0;
  const tasks = new Map();
  return {
    schedule(fn, ms) {
      const key = ++id;
      tasks.set(key, { fn, at: time + ms });
      return key;
    },
    cancel(key) {
      tasks.delete(key);
    },
    async advance(ms) {
      const end = time + ms;
      while (true) {
        const next = [...tasks]
          .filter(([, task]) => task.at <= end)
          .sort((a, b) => a[1].at - b[1].at)[0];
        if (!next) break;
        time = next[1].at;
        tasks.delete(next[0]);
        next[1].fn();
        for (let i = 0; i < 6; i++) await Promise.resolve();
      }
      time = end;
    },
  };
}
function fixture(verify) {
  const time = clock();
  const statuses = [];
  const errors = [];
  const successes = [];
  const target = new EventTarget();
  const poll = startPaymentVerificationPoll({
    verify,
    onStatus: (s) => statuses.push(s),
    onError: (e) => errors.push(e),
    onSuccess: async (result) => {
      successes.push(result);
    },
    intervalMs: 10,
    durationMs: 35,
    target,
    schedule: time.schedule,
    cancel: time.cancel,
  });
  return { time, poll, statuses, errors, successes, target };
}

test("pending payments poll automatically and settle only after backend success", async () => {
  let calls = 0;
  const f = fixture(async () => ({
    status: ++calls === 2 ? "success" : "pending",
  }));
  await f.time.advance(20);
  assert.equal(calls, 2);
  assert.equal(f.successes.length, 1);
  assert.equal(f.statuses.at(-1), "success");
  await f.time.advance(100);
  f.target.dispatchEvent(new Event("focus"));
  assert.equal(calls, 2);
  f.poll.dispose();
});

test("focus and manual checks cannot overlap an in-flight verification", async () => {
  let calls = 0;
  let finish;
  const f = fixture(() => {
    calls++;
    return new Promise((resolve) => {
      finish = resolve;
    });
  });
  await f.time.advance(10);
  f.target.dispatchEvent(new Event("focus"));
  await f.poll.checkNow();
  assert.equal(calls, 1);
  finish({ status: "success" });
  await f.time.advance(1);
  await Promise.resolve();
  f.poll.dispose();
});

test("temporary provider errors retry silently, then pause at the deadline", async () => {
  let calls = 0;
  const f = fixture(async () => {
    calls++;
    throw Object.assign(new Error("Not paid yet"), {
      response: { status: 400 },
    });
  });
  await f.time.advance(100);
  assert.equal(calls, 3);
  assert.equal(f.errors.length, 0);
  assert.equal(f.statuses.at(-1), "timed_out");
  assert.equal(f.successes.length, 0);
  await f.poll.checkNow();
  assert.equal(calls, 4);
  assert.equal(f.errors.length, 1);
  f.poll.dispose();
});

test("returning from a long checkout restarts a bounded confirmation window", async () => {
  let calls = 0;
  const f = fixture(async () => ({
    status: ++calls === 4 ? "success" : "pending",
  }));
  await f.time.advance(100);
  assert.equal(f.statuses.at(-1), "timed_out");
  f.target.dispatchEvent(new Event("focus"));
  await f.time.advance(1);
  assert.equal(f.successes.length, 1);
  f.poll.dispose();
});

test("closing checkout aborts verification and ignores late results", async () => {
  let signal;
  let finish;
  const f = fixture((value) => {
    signal = value;
    return new Promise((resolve) => {
      finish = resolve;
    });
  });
  await f.time.advance(10);
  f.poll.dispose();
  assert.equal(signal.aborted, true);
  finish({ status: "success" });
  await f.time.advance(100);
  assert.equal(f.successes.length, 0);
  assert.equal(f.statuses.at(-1), "checking");
});

test("definitive failure and permission errors stop automatic requests", async () => {
  for (const status of ["failed", "cancelled"]) {
    let calls = 0;
    const f = fixture(async () => {
      calls++;
      return { status };
    });
    await f.time.advance(100);
    assert.equal(calls, 1);
    assert.equal(f.statuses.at(-1), status);
    assert.equal(f.successes.length, 0);
    f.poll.dispose();
  }
  const f = fixture(async () => {
    throw Object.assign(new Error("Wrong owner"), {
      response: { status: 403 },
    });
  });
  await f.time.advance(100);
  assert.equal(f.statuses.at(-1), "stopped");
  assert.equal(f.errors.length, 1);
  f.target.dispatchEvent(new Event("focus"));
  assert.equal(f.errors.length, 1);
  f.poll.dispose();
});
