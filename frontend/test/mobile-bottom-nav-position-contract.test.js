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
