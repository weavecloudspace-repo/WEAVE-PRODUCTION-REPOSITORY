import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { installMobilePwaStability } from "../src/utils/mobilePwaStability.js";

const createEventTarget = (properties = {}) => {
  const listeners = new Map();

  return {
    ...properties,
    addEventListener(name, callback) {
      if (!listeners.has(name)) listeners.set(name, new Set());
      listeners.get(name).add(callback);
    },
    removeEventListener(name, callback) {
      listeners.get(name)?.delete(callback);
    },
    emit(name) {
      for (const callback of listeners.get(name) || []) callback();
    },
  };
};

const createPwaFixture = (platform) => {
  const originals = {
    window: globalThis.window,
    document: globalThis.document,
    Element: globalThis.Element,
  };
  const scrollCalls = [];
  const scheduledFrames = new Map();
  let nextFrameId = 0;
  const formScroller = {
    scrollBy(options) {
      scrollCalls.push(options);
    },
  };

  class MockEditableElement {
    matches(selector) {
      return selector.includes("input:");
    }

    closest(selector) {
      return selector.includes(".auth-surface") ? formScroller : null;
    }

    getBoundingClientRect() {
      return { top: 640, bottom: 688 };
    }
  }

  const root = {
    dataset: {},
    clientHeight: 844,
    scrollLeft: 0,
    style: {
      setProperty() {},
      removeProperty() {},
    },
  };
  const viewport = createEventTarget({ height: 470, offsetTop: 0 });
  const document = createEventTarget({
    documentElement: root,
    body: { scrollLeft: 0 },
    scrollingElement: { scrollLeft: 0 },
    activeElement: new MockEditableElement(),
    hidden: false,
  });
  const window = createEventTarget({
    innerHeight: 844,
    innerWidth: 390,
    navigator: {
      userAgent: platform === "ios" ? "iPhone" : "Android",
      platform: platform === "ios" ? "iPhone" : "Linux armv8",
      maxTouchPoints: 1,
    },
    visualViewport: viewport,
    matchMedia: () => ({
      matches: true,
      addEventListener() {},
      removeEventListener() {},
    }),
    requestAnimationFrame(callback) {
      const id = ++nextFrameId;
      scheduledFrames.set(id, callback);
      return id;
    },
    cancelAnimationFrame(id) {
      scheduledFrames.delete(id);
    },
    clearTimeout() {},
  });

  globalThis.window = window;
  globalThis.document = document;
  globalThis.Element = MockEditableElement;

  return {
    root,
    viewport,
    document,
    scrollCalls,
    flushFrames() {
      // A bounded drain catches accidental scroll-induced scheduling loops.
      for (let index = 0; index < 5 && scheduledFrames.size; index += 1) {
        const callbacks = [...scheduledFrames.values()];
        scheduledFrames.clear();
        callbacks.forEach((callback) => callback());
      }
      assert.equal(scheduledFrames.size, 0, "Animation frames must settle");
    },
    restore() {
      for (const [key, previous] of Object.entries(originals)) {
        if (previous === undefined) delete globalThis[key];
        else globalThis[key] = previous;
      }
    },
  };
};

test("iOS login form delegates focus scrolling to WebKit while keyboard is raised", () => {
  const fixture = createPwaFixture("ios");
  let cleanup;

  try {
    cleanup = installMobilePwaStability();
    fixture.flushFrames();
    assert.equal(fixture.root.dataset.pwaPlatform, "ios");
    assert.equal(fixture.root.dataset.keyboardOpen, "true");

    for (let index = 0; index < 6; index += 1) {
      fixture.viewport.emit("resize");
      fixture.viewport.emit("scroll");
      fixture.document.emit("focusin");
      fixture.flushFrames();
    }

    assert.equal(
      fixture.scrollCalls.length,
      0,
      "Native iOS keyboard scrolling must not compete with manual login-form scrolling",
    );
  } finally {
    cleanup?.();
    fixture.restore();
  }
});

test("non-iOS fields retain a synchronous visibility correction", () => {
  const fixture = createPwaFixture("android");
  let cleanup;

  try {
    cleanup = installMobilePwaStability();
    fixture.flushFrames();
    assert.equal(fixture.root.dataset.pwaPlatform, "android");
    assert.equal(fixture.root.dataset.keyboardOpen, "true");
    assert.ok(fixture.scrollCalls.length > 0);
    assert.ok(fixture.scrollCalls.every((call) => call.behavior === "auto"));
  } finally {
    cleanup?.();
    fixture.restore();
  }
});

test("installed iOS auth cards do not animate transforms beneath the keyboard", async () => {
  const css = await readFile(
    new URL("../src/styles/mobilePwaStability.css", import.meta.url),
    "utf8",
  );

  assert.match(
    css,
    /data-pwa-platform="ios"\][\s\S]*?\.auth-surface \.public-panel-reveal\s*\{\s*animation:\s*none\s*!important;[\s\S]*?transform:\s*none\s*!important;/,
  );
});
