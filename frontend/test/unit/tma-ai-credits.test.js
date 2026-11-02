import assert from "node:assert/strict";
import test from "node:test";
import {
  canRequestAICredits,
  paystackCheckoutUrl,
  pendingCreditRequests,
  purchasePath,
} from "../../src/features/tma/aiCredits.js";

const exhausted = {
  actor_type: "teacher",
  total_available_credits: 0,
  weekly: { available_credits: 0, reserved_credits: 0 },
  extra: { available_credits: 0, reserved_credits: 0 },
};
test("school requests appear only for an exhausted teacher with no pending reservations", () => {
  assert.equal(canRequestAICredits(exhausted), true);
  for (const quota of [
    null,
    {},
    { ...exhausted, actor_type: "tenant_admin" },
    { ...exhausted, total_available_credits: 1 },
    { ...exhausted, weekly: { available_credits: 0, reserved_credits: 1 } },
    { ...exhausted, extra: { available_credits: 0, reserved_credits: 1 } },
  ]) {
    assert.equal(canRequestAICredits(quota), false);
  }
});

test("purchase routes retain separate school and personal ownership", () => {
  assert.equal(purchasePath(exhausted), "/ai/teacher/purchases");
  assert.equal(
    purchasePath({ actor_type: "tenant_admin" }),
    "/ai/admin/quota/purchases",
  );
  assert.throws(() => purchasePath({ actor_type: "student" }));
});

test("checkout accepts only HTTPS Paystack provider links", () => {
  assert.equal(
    paystackCheckoutUrl("https://checkout.paystack.com/example"),
    "https://checkout.paystack.com/example",
  );
  for (const url of [
    "javascript:alert(1)",
    "http://checkout.paystack.com/example",
    "https://checkout.paystack.com.evil.test/example",
    "/redirect",
  ]) {
    assert.throws(() => paystackCheckoutUrl(url));
  }
});

test("request lookup checks later pages before allowing another request", async () => {
  const paths = [];
  const requests = await pendingCreditRequests({
    get: async (path) => {
      paths.push(path);
      return paths.length === 1
        ? { items: [{ status: "approved" }], total: 2 }
        : { items: [{ status: "pending", requested_credits: 20 }], total: 2 };
    },
  });
  assert.equal(requests.length, 1);
  assert.deepEqual(paths, [
    "/ai/quota/requests?offset=0&limit=100",
    "/ai/quota/requests?offset=1&limit=100",
  ]);
});
