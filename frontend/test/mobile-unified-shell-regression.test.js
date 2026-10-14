import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");

test("mobile Help & Support shares the drawer scroll; desktop footer remains intact", () => {
  const sidebar = read("../src/components/layout/Sidebar.jsx");
  const drawer = read("../src/components/layout/MobileDrawer.jsx");
  const css = read("../src/styles/mobileDashboard.css");
  assert.match(sidebar, /data-mobile-sidebar-support="true"/);
  assert.match(sidebar, /!collapsed && mobile \?/);
  assert.match(sidebar, /!collapsed && !mobile && \(/);
  assert.match(css, /\[data-mobile-drawer="true"\]\s*\{[^}]*border-bottom-right-radius:\s*0/s);
  assert.match(drawer, /min-h-0 w-\[min\(88vw,20rem\)\]/);
});

test("browser-only drawer sync preserves the original mobile drawer structure", () => {
  const drawer = read("../src/components/layout/MobileDrawer.jsx");
  const css = read("../src/styles/iosSafariBrowserTheme.css");
  assert.match(drawer, /scheduleThemeChromeSync\(\)/);
  assert.match(drawer, /\[open\]/);
  assert.match(drawer, /data-mobile-drawer="true"/);
  assert.match(css, /data-ios-browser="true"\]\[data-ios-browser-drawer-open="true"\]/);
  assert.doesNotMatch(css, /data-standalone-pwa="true"\]\[data-ios-browser-drawer-open/);
});

test("PWA navigation uses a single anchored shell and internal gesture clearance", () => {
  const styles = read("../src/styles/mobilePwaStability.css");
  const platform = read("../src/styles/mobilePlatformFixes.css");
  const nav = read("../src/components/layout/BottomNav.jsx");
  const geometry = styles.match(/html\[data-standalone-pwa="true"\]\s+\[data-mobile-bottom-nav="true"\]\s*\{([^}]*)\}/);
  assert.ok(geometry);
  assert.match(geometry[1], /bottom:\s*0\s*!important/);
  assert.match(geometry[1], /padding-bottom:\s*max\(\s*0\.375rem,\s*calc\(env\(safe-area-inset-bottom,\s*0px\)\s*-\s*0\.875rem\)/);
  assert.doesNotMatch(platform, /padding-bottom:\s*0\s*!important/);
  assert.doesNotMatch(nav, /border-t border-border\/70 bg-background px-2 pt-0\.5 pb-3/);
});

test("mobile drawer leaves its close button above the full-height opaque surface", () => {
  const drawer = read("../src/components/layout/MobileDrawer.jsx");
  const css = read("../src/styles/mobileDashboard.css");
  assert.doesNotMatch(drawer, /data-mobile-drawer-status-surface="true"/);
  assert.doesNotMatch(css, /data-mobile-drawer-status-surface/);
  assert.match(drawer, /className="relative z-10 flex h-12 shrink-0 items-center justify-end/);
  assert.match(drawer, /relative z-10 inline-flex h-11 w-11/);
  assert.match(drawer, /aria-label="Close navigation"/);
  assert.match(drawer, /pt-\[max\(0\.75rem,env\(safe-area-inset-top\)\)\]/);
  assert.match(css, /\[data-mobile-drawer="true"\]\s*\{[^}]*background-color:\s*rgb\(var\(--color-sidebar-background\)\)/s);
  assert.match(css, /\[data-mobile-drawer="true"\]\s*\{[^}]*backdrop-filter:\s*none\s*!important/s);
});

test("iOS home-screen install sees a non-translucent status bar before theme bootstrapping", () => {
  const html = read("../index.html");
  const statusMeta = '<meta name="apple-mobile-web-app-status-bar-style" content="default" />';
  assert.ok(html.includes(statusMeta));
  assert.ok(html.indexOf(statusMeta) < html.indexOf('<script src="/theme-init.js"></script>'));
  assert.doesNotMatch(html, /content="black-translucent"/);
});
