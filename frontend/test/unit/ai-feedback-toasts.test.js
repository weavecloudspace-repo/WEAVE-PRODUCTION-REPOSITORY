import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { runInNewContext } from "node:vm";
import test from "node:test";
import { parse } from "espree";
import { toastBus } from "../../src/hooks/useToast.js";

const page = await readFile(
  new URL("../../src/features/ai/AIUsagePage.jsx", import.meta.url),
  "utf8",
);
const ast = parse(page, {
  ecmaVersion: "latest",
  sourceType: "module",
  ecmaFeatures: { jsx: true },
  range: true,
});
const component = ast.body.find(
  (n) => n.declaration?.id?.name === "AIUsagePage",
).declaration;
function callback(name, scope) {
  const variable = component.body.body
    .flatMap((n) => n.declarations || [])
    .find((n) => n.id.name === name);
  const expression =
    name === "reload" ? variable.init.arguments[0] : variable.init;
  return runInNewContext(`(${page.slice(...expression.range)})`, {
    showError: toastBus.error,
    showSuccess: toastBus.success,
    ...scope,
  });
}

test("AI actions send feedback through the existing toast bus and retain errors across refresh", async () => {
  const messages = [];
  const unsubscribe = toastBus.subscribe((toast) => messages.push(toast));
  const events = [];
  const act = callback("act", {
    activeRequest: { current: false },
    setBusy: (busy) => events.push(busy),
    setAction: (action) => events.push(action),
    errorText: (error) => error.message,
    reload: async () => {
      events.push("refreshed");
    },
  });
  try {
    await act(async () => {}, "Credits allocated successfully.");
    await act(async () => {
      throw new Error("Request could not be approved.");
    }, "Should not appear");
    assert.deepEqual(
      messages.map((m) => [m.type, m.message]),
      [
        ["success", "Credits allocated successfully."],
        ["error", "Request could not be approved."],
      ],
    );
    assert.equal(messages[1].duration, null);
    assert.equal(events.filter((event) => event === "refreshed").length, 2);
    assert.equal(events.at(-1), false);
  } finally {
    unsubscribe();
  }
});

test("background AI refresh does not repeat an unchanged error toast", async () => {
  const messages = [];
  const unsubscribe = toastBus.subscribe((toast) => messages.push(toast));
  let fail = true;
  const snapshots = [];
  const reload = callback("reload", {
    version: { current: 0 },
    lastLoadError: { current: "" },
    admin: true,
    page: 0,
    PAGE_SIZE: 20,
    setLoading() {},
    setData: (data) => snapshots.push(data),
    errorText: (error) => error.message,
    api: {
      get: async (path) => {
        if (path.startsWith("/ai/admin/quota/actors") && fail)
          throw new Error("Temporarily unavailable");
        return { items: [] };
      },
    },
  });
  try {
    await reload();
    await reload({ silent: true });
    assert.equal(messages.length, 1);
    assert.equal(messages[0].type, "error");
    assert.match(messages[0].message, /Staff usage: Temporarily unavailable/);
    assert.ok(snapshots[0].quota);
    await reload();
    assert.equal(messages.length, 2);
    fail = false;
    await reload({ silent: true });
    fail = true;
    await reload({ silent: true });
    assert.equal(messages.length, 3);
  } finally {
    unsubscribe();
  }
});

test("payment polling uses toasts for meaningful changes without notifying on every check", async () => {
  const source = await readFile(
    new URL("../../src/features/ai/AICreditPurchaseFlow.jsx", import.meta.url),
    "utf8",
  );
  const tree = parse(source, {
    ecmaVersion: "latest",
    sourceType: "module",
    ecmaFeatures: { jsx: true },
    range: true,
  });
  function find(node) {
    if (!node || typeof node !== "object") return null;
    if (
      node.type === "CallExpression" &&
      node.callee.name === "startPaymentVerificationPoll"
    )
      return node;
    return Object.values(node).flat().map(find).find(Boolean);
  }
  const options = find(tree).arguments[0];
  const status = options.properties.find(
    (p) => p.key.name === "onStatus",
  ).value;
  const onStatus = runInNewContext(`(${source.slice(...status.range)})`, {
    active: true,
    setVerificationStatus() {},
    showInfo: toastBus.info,
    showError: toastBus.error,
  });
  const messages = [];
  const unsubscribe = toastBus.subscribe((toast) => messages.push(toast));
  try {
    onStatus("waiting");
    onStatus("checking");
    onStatus("waiting");
    onStatus("checking");
    assert.equal(messages.length, 0);
    onStatus("timed_out");
    onStatus("failed");
    assert.deepEqual(
      messages.map((m) => m.type),
      ["info", "error"],
    );
  } finally {
    unsubscribe();
  }
});
