import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");

test("Safari browser dashboards follow the document instead of a fixed PWA shell", () => {
  const css = read("../src/styles/iosSafariBrowserTheme.css");
  assert.match(css, /data-ios-browser="true"\] \[data-dashboard-role\]:not\(\[data-guide-page="true"\]\)/);
  assert.match(css, /position: relative !important/);
  assert.match(css, /#dashboard-scroll-viewport\s*\{[^}]*overflow: visible !important/s);
  assert.doesNotMatch(css, /position: absolute !important/);
});

test("PWA nav has one safe-area anchor and no fake footer/status strips", () => {
  const css = read("../src/styles/mobilePwaStability.css");
  const platform = read("../src/styles/mobilePlatformFixes.css");
  const shell = read("../src/components/layout/DashboardLayout.jsx");
  assert.match(css, /bottom: max\(0\.5rem, env\(safe-area-inset-bottom, 0px\)\) !important/);
  assert.doesNotMatch(platform, /--mobile-bottom-nav-clearance:/);
  assert.doesNotMatch(shell, /data-pwa-safe-area-fill/);
  assert.doesNotMatch(shell, /data-pwa-status-fill/);
});

test("iOS status bar and theme follow effective user appearance", () => {
  const prefs = read("../src/utils/accessibilityPreferences.js");
  const startup = read("../../public/theme-init.js");
  const html = read("../../index.html");
  assert.match(prefs, /resolvedTheme === "dark" \? "black" : "default"/);
  assert.match(startup, /resolvedTheme === "dark" \? "black" : "default"/);
  assert.match(html, /apple-mobile-web-app-status-bar-style" content="default"/);
});

test("replaying tour keeps existing controls and does not deadlock on entitlements or drawer geometry", () => {
  const jsx = read("../src/components/guides/WorkspaceTour.jsx");
  assert.match(jsx, /const subscriptionReady = configuredItems\.length > 0/);
  assert.match(jsx, /!rendered\.size \|\| rendered\.has/);
  assert.match(jsx, /disabled=\{busy \|\| \(welcome && !steps\.length\)\}/);
  assert.match(jsx, /"Show me around"/);
  assert.match(jsx, /setIndex\(index \+ 1\)/);
});
