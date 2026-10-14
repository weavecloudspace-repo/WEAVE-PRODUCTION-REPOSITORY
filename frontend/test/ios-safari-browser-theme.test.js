import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  isIosBrowserMode,
  isIosLikePlatform,
  selectThemeBackgroundChannels,
} from "../src/utils/iosBrowserThemeChrome.js";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("iOS browser detection excludes Android and every standalone PWA", () => {
  const iphone = {
    userAgent:
      "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1",
    platform: "iPhone",
    maxTouchPoints: 5,
  };
  const ipadDesktopMode = {
    userAgent:
      "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1",
    platform: "MacIntel",
    maxTouchPoints: 5,
  };
  const android = {
    userAgent:
      "Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 Chrome/131.0 Mobile Safari/537.36",
    platform: "Linux armv8l",
    maxTouchPoints: 5,
  };

  assert.equal(isIosLikePlatform(iphone), true);
  assert.equal(isIosLikePlatform(ipadDesktopMode), true);
  assert.equal(isIosLikePlatform(android), false);
  assert.equal(
    isIosBrowserMode({ navigatorLike: iphone, displayModeStandalone: false }),
    true,
  );
  assert.equal(
    isIosBrowserMode({ navigatorLike: iphone, displayModeStandalone: true }),
    false,
  );
  assert.equal(
    isIosBrowserMode({
      navigatorLike: { ...iphone, standalone: true },
      displayModeStandalone: false,
    }),
    false,
  );
  assert.equal(
    isIosBrowserMode({ navigatorLike: android, displayModeStandalone: false }),
    false,
  );
});

test("iOS browser canvas uses the dashboard shell background as its authority", () => {
  assert.equal(
    selectThemeBackgroundChannels({
      rootChannels: "248 250 252",
      dashboardChannels: "247 244 238",
      iosBrowser: true,
    }),
    "247 244 238",
  );
  assert.equal(
    selectThemeBackgroundChannels({
      rootChannels: "15 23 42",
      dashboardChannels: "",
      iosBrowser: true,
    }),
    "15 23 42",
  );
  assert.equal(
    selectThemeBackgroundChannels({
      rootChannels: "248 250 252",
      dashboardChannels: "247 244 238",
      iosBrowser: false,
    }),
    "248 250 252",
  );
});

test("iOS Safari browser uses one document canvas for live theme switching", async () => {
  const html = await read("index.html");
  const startup = await read("public/theme-init.js");
  const runtime = await read("src/utils/themeChromeSync.js");
  const css = await read("src/styles/iosSafariBrowserTheme.css");
  const main = await read("src/main.jsx");

  const colorSchemePosition = html.indexOf('id="weave-color-scheme"');
  const themeColorPosition = html.indexOf('id="weave-theme-color"');
  const startupScriptPosition = html.indexOf('<script src="/theme-init.js"></script>');

  assert.ok(colorSchemePosition >= 0);
  assert.ok(themeColorPosition >= 0);
  assert.ok(colorSchemePosition < startupScriptPosition);
  assert.ok(themeColorPosition < startupScriptPosition);

  assert.match(startup, /dataset\.iosBrowser/);
  assert.match(startup, /getElementById\(id\)/);
  assert.match(startup, /syncStableMetas/);
  assert.doesNotMatch(
    startup,
    /querySelectorAll\('meta\[name="theme-color"\], meta\[name="color-scheme"\]'\)/,
  );

  assert.match(runtime, /isIosBrowserMode/);
  assert.match(runtime, /selectThemeBackgroundChannels/);
  assert.match(runtime, /document\.querySelector\("\[data-dashboard-role\]"\)/);
  assert.match(runtime, /applyIosBrowserCanvas/);
  assert.match(
    runtime,
    /style\.setProperty\(\s*IOS_BROWSER_CANVAS_PROPERTY,\s*background,\s*\)/,
  );
  assert.match(
    runtime,
    /document\.documentElement\.style\.backgroundColor = background/,
  );
  assert.match(runtime, /document\.body\.style\.backgroundColor = background/);
  assert.match(runtime, /root\.style\.backgroundColor = "transparent"/);
  assert.match(runtime, /document\.documentElement\.style\.backgroundImage = "none"/);
  assert.match(runtime, /updateStableIosBrowserMetas/);
  assert.match(runtime, /syncIosBrowserDrawerCanvas/);
  assert.match(runtime, /getComputedStyle\(drawer\)\.backgroundColor/);
  assert.match(runtime, /drawer\.getBoundingClientRect\(\)\.width/);
  assert.match(runtime, /dataset\.iosBrowserDrawerOpen = "true"/);
  assert.match(runtime, /removeAttribute\("data-ios-browser-drawer-open"\)/);
  assert.match(runtime, /window\.addEventListener\("resize", scheduleThemeChromeSync\)/);
  assert.match(runtime, /THEME_COLOR_META_ID = "weave-theme-color"/);
  assert.match(runtime, /COLOR_SCHEME_META_ID = "weave-color-scheme"/);
  assert.match(runtime, /replaceBrowserMetas: !standalone && !iosBrowser/);
  assert.match(runtime, /if \(standalone\) return;/);

  assert.match(css, /data-ios-browser="true"/);
  assert.match(css, /--weave-ios-browser-canvas/);
  assert.match(css, /background-repeat: no-repeat !important/);
  assert.match(css, /data-ios-browser-drawer-open="true"/);
  assert.match(css, /--weave-ios-browser-drawer-color/);
  assert.match(css, /--weave-ios-browser-drawer-width/);
  assert.match(css, /linear-gradient\(/);
  assert.match(css, /#root[\s\S]*background-color: transparent !important/);
  assert.match(css, /\[data-dashboard-role\][\s\S]*background-color: transparent !important/);
  assert.match(css, /\[data-dashboard-role\]:not\(\[data-guide-page="true"\]\)/);
  assert.match(css, /position: relative !important/);
  assert.doesNotMatch(css, /position: absolute !important/);
  assert.match(css, /#dashboard-scroll-viewport[\s\S]*background-color: transparent !important/);
  assert.match(css, /body::before/);
  assert.match(css, /display: none/);
  assert.match(main, /iosSafariBrowserTheme\.css/);
});
