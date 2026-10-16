import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const frontendRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../..",
);

const readSource = (relativePath) =>
  readFile(path.join(frontendRoot, relativePath), "utf8");

test("wide-screen rules load after existing mobile and PWA styles", async () => {
  const main = await readSource("src/main.jsx");
  const cssImports = [...main.matchAll(/^import "\.\/styles\/[^"]+\.css";$/gm)].map(
    ([line]) => line,
  );

  assert.equal(
    cssImports.at(-1),
    'import "./styles/largeScreens.css";',
    "Wide-screen CSS must be the last stylesheet so its scoped sizing wins.",
  );
  assert.match(main, /import "\.\/styles\/mobilePwaStability\.css";/);
  assert.match(main, /import "\.\/styles\/iosSafariBrowserTheme\.css";/);
});

test("wide-screen changes apply only above 1600px outside installed PWAs", async () => {
  const source = await readSource("src/styles/largeScreens.css");
  const css = source.replace(/\/\*[\s\S]*?\*\//g, "");

  assert.match(css, /^\s*@media screen and \(min-width: 1600px\)\s*\{/);
  assert.equal((css.match(/@media\b/g) || []).length, 1);
  assert.equal((css.match(/@import\b/g) || []).length, 0);

  const selectors = [...css.matchAll(/(?:^|\})\s*([^{}]+)\{/gm)]
    .map((match) => match[1].trim())
    .filter((selector) => !selector.startsWith("@media"));

  assert.ok(selectors.length > 5);
  for (const selector of selectors) {
    for (const segment of selector.split(/,\s*(?=html:not\()/)) {
      assert.match(
        segment.trim(),
        /^html:not\(\[data-standalone-pwa="true"\]\)/,
        `Unscoped wide-screen selector: ${segment.trim()}`,
      );
    }
  }

  for (const expected of [
    ".section-container",
    ".dashboard-topbar > div",
    "#dashboard-content",
    '[data-guide-page="true"]',
    ".auth-surface main > div",
    ".public-page-shell #home h1",
  ]) {
    assert.ok(css.includes(expected), `Missing shared surface: ${expected}`);
  }

  assert.doesNotMatch(
    css,
    /(?:bottom-nav|mobile-drawer|dashboard-main-frame|dashboard-scroll-viewport|safe-area-inset)/,
    "Protected mobile/PWA shell elements must not be targeted.",
  );
  assert.doesNotMatch(
    css,
    /(?:^|[;\n])\s*(?:position|display|visibility|overflow|pointer-events|touch-action|z-index|height|min-height|bottom|top|left|right|inset)\s*:/m,
    "Wide-screen CSS may adjust dimensions and spacing, not shell behavior.",
  );
});
