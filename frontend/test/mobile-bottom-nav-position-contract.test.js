import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const readSource = (relativePath) =>
  readFileSync(new URL(relativePath, import.meta.url), "utf8");

const getStandaloneNavRules = (source) => {
  const rules = source.match(
    /html\[data-standalone-pwa="true"\]\s+\[data-mobile-bottom-nav="true"\]\s*\{([^}]*)\}/,
  );
  assert.ok(rules, "Standalone PWA bottom-nav styles must exist");
  return rules[1];
};

test("installed PWA bottom nav stays at the lower edge after launch and resume", () => {
  const stabilityCss = readSource("../src/styles/mobilePwaStability.css");
  const platformCss = readSource("../src/styles/mobilePlatformFixes.css");
  const mainSource = readSource("../src/main.jsx");

  const navAnchor = getStandaloneNavRules(stabilityCss);
  assert.match(navAnchor, /position:\s*fixed\s*!important;/);
  assert.match(navAnchor, /bottom:\s*max\(0\.5rem,\s*env\(safe-area-inset-bottom,\s*0px\)\)\s*!important;/);

  // One safe-area anchor owns the dock position; no platform-specific offset.
  const platformRules = getStandaloneNavRules(platformCss);
  assert.doesNotMatch(
    platformRules,
    /(?:^|;)\s*bottom\s*:/,
    "Platform-specific styles must not override the nav's bottom anchor",
  );

  assert.ok(
    mainSource.indexOf('import "./styles/mobilePlatformFixes.css"') <
      mainSource.indexOf('import "./styles/mobilePwaStability.css"'),
    "The positioning stylesheet must load after platform presentation styles",
  );
});

test("the iOS PWA dock uses one CSS viewport anchor across launch and login", () => {
  const css = readSource("../src/styles/mobilePwaStability.css");
  const runtime = readSource("../src/utils/mobilePwaStability.js");
  const navAnchor = getStandaloneNavRules(css);

  // The viewport height must follow iOS after an authentication transition.
  assert.match(css, /--pwa-layout-height:\s*100dvh/);
  assert.doesNotMatch(runtime, /root\.style\.setProperty\(["']--pwa-layout-height/);
  assert.match(runtime, /root\.style\.removeProperty\("--pwa-layout-height"\)/);
  assert.match(runtime, /const handleViewportResize = \(\) => \{[\s\S]*?setStableLayoutHeight\(\)/);

  // Only one CSS rule controls the dock's safe-area-aware position.
  assert.match(navAnchor, /bottom:\s*max\(0\.5rem,\s*env\(safe-area-inset-bottom,\s*0px\)\)\s*!important/);
  assert.doesNotMatch(css, /bottom:\s*calc\(0\.75rem \+ env\(safe-area-inset-bottom/);
  assert.doesNotMatch(css, /top:\s*calc\(var\(--pwa-device-screen-height/);
  assert.doesNotMatch(runtime, /resolvePwaScreenHeight|--pwa-device-screen-height/);

  const keyboardRules = css.match(
    /html\[data-standalone-pwa="true"\]\[data-keyboard-open="true"\]:not\(\[data-modal-open="true"\]\)\s+\[data-mobile-bottom-nav="true"\]\s*\{([^}]*)\}/,
  )?.[1];
  assert.ok(keyboardRules);
  assert.doesNotMatch(keyboardRules, /(?:^|;)\s*(?:top|bottom|translate|transform)\s*:/);
});
