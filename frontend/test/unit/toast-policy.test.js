import assert from "node:assert/strict";
import test from "node:test";
import { toastBus } from "../../src/hooks/useToast.js";
import { appendToast } from "../../src/utils/toastPolicy.js";

test("errors require dismissal even when a caller supplies a duration", () => {
  const emitted = [];
  const unsubscribe = toastBus.subscribe((toast) => emitted.push(toast));
  try {
    toastBus.error("Failed to save");
    toastBus.error("Failed to load", { duration: 50 });
    toastBus.show("Invalid selection", "error", { duration: 3200 });
    assert.equal(emitted.length, 3);
    assert.ok(emitted.every((toast) => toast.duration === null));
  } finally {
    unsubscribe();
  }
});

test("confirmation notifications retain default and custom expiry", () => {
  const emitted = [];
  const unsubscribe = toastBus.subscribe((toast) => emitted.push(toast));
  try {
    toastBus.success("Saved");
    toastBus.success("Uploaded", { duration: 5000 });
    toastBus.info("Updated");
    toastBus.warning("Check your selection");
    assert.deepEqual(emitted.map((toast) => toast.duration), [3200, 5000, 3200, 3200]);
  } finally {
    unsubscribe();
  }
});

test("new notifications never evict errors and retain only four transient toasts", () => {
  let toasts = [];
  for (let index = 0; index < 6; index += 1) {
    toasts = appendToast(toasts, { id: `error-${index}`, type: "error" });
    toasts = appendToast(toasts, { id: `success-${index}`, type: "success" });
  }
  assert.deepEqual(
    toasts.filter((toast) => toast.type === "error").map((toast) => toast.id),
    Array.from({ length: 6 }, (_, index) => `error-${index}`),
  );
  assert.deepEqual(
    toasts.filter((toast) => toast.type === "success").map((toast) => toast.id),
    ["success-2", "success-3", "success-4", "success-5"],
  );
});
