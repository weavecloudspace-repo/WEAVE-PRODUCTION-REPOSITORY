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
  assert.match(navAnchor, /bottom:\s*0\s*!important;/);

  // Safe-area offsets apply to content clearance, not to the capsule's anchor.
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

test("the iOS PWA dock uses one physical screen anchor across repeated launches", async () => {
  const { resolvePwaScreenHeight } = await import(
    "../src/utils/mobilePwaStability.js"
  );
  const css = readSource("../src/styles/mobilePwaStability.css");
  const runtime = readSource("../src/utils/mobilePwaStability.js");

  // Simulate the shorter viewport returned by WebKit after background/resume.
  const launchHeights = [926, 876, 926, 876];
  const resolved = launchHeights.map((fallbackHeight) =>
    resolvePwaScreenHeight({
      screenWidth: 428,
      screenHeight: 926,
      landscape: false,
      fallbackHeight,
    }),
  );

  assert.deepEqual(resolved, [926, 926, 926, 926]);
  assert.equal(
    resolvePwaScreenHeight({
      screenWidth: 428,
      screenHeight: 926,
      landscape: true,
      fallbackHeight: 428,
    }),
    428,
  );
  assert.equal(
    resolvePwaScreenHeight({
      screenWidth: undefined,
      screenHeight: undefined,
      landscape: false,
      fallbackHeight: 844,
    }),
    844,
  );

  assert.match(runtime, /--pwa-device-screen-height/);
  assert.match(runtime, /syncScreenAnchor\(\)/);
  assert.match(runtime, /window\.screen\?\.height/);

  const iosRules = css.match(
    /html\[data-standalone-pwa="true"\]\[data-pwa-platform="ios"\]\s+\[data-mobile-bottom-nav="true"\]\s*\{([^}]*)\}/,
  )?.[1];

  assert.ok(iosRules, "iOS navigation must have an explicit physical screen anchor");
  assert.match(iosRules, /top:\s*calc\(var\(--pwa-device-screen-height, 100dvh\) - 0\.5rem\)\s*!important/);
  assert.match(iosRules, /bottom:\s*auto\s*!important/);
  assert.match(iosRules, /padding-bottom:\s*0\s*!important/);
  assert.match(iosRules, /transform:\s*translate3d\(0, -100%, 0\)\s*!important/);
  assert.doesNotMatch(iosRules, /safe-area-inset-bottom|\bvh\b/);

  const keyboardRules = css.match(
    /html\[data-standalone-pwa="true"\]\[data-keyboard-open="true"\]:not\(\[data-modal-open="true"\]\)\s+\[data-mobile-bottom-nav="true"\]\s*\{([^}]*)\}/,
  )?.[1];

  assert.ok(keyboardRules);
  assert.doesNotMatch(keyboardRules, /(?:^|;)\s*(?:top|bottom|translate|transform)\s*:/);
});
