import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("subscription pricing is hydrated from the public backend catalogue", async () => {
  const service = await read("src/services/subscriptionService.js");
  const runtime = await read(
    "src/features/subscriptions/pricingCatalogueRuntime.js",
  );
  const main = await read("src/main.jsx");
  const landing = await read("src/pages/public/LandingPage.jsx");
  const pricingHook = await read(
    "src/features/subscriptions/usePublicPricingCatalogue.js",
  );

  assert.match(service, /getPublicPlans/);
  assert.match(service, /\/subscriptions\/plans/);
  assert.match(service, /If-None-Match/);
  assert.match(service, /status === 304/);
  assert.match(runtime, /Pricing unavailable/);
  assert.match(runtime, /backendPlan\.amount/);
  assert.match(runtime, /backendPlan\.features/);
  assert.match(runtime, /backendPlan\.limits/);
  assert.match(main, /subscriptionService[\s\S]*\.getPublicPlans/);
  assert.match(main, /applyPublicPricingCatalogue/);
  assert.match(main, /settlePublicPricingCatalogue/);
  assert.match(landing, /usePublicPricingCatalogue/);
  assert.match(pricingHook, /CATALOGUE_CHANGED_EVENT/);
});

test("pricing surfaces show three paid cards and keep Free outside checkout cards", async () => {
  const landing = await read("src/pages/public/LandingPage.jsx");
  const pricing = await read("src/pages/public/PricingPage.jsx");
  const desktopPlans = await read(
    "src/pages/admin/SubscriptionOptionsPage.jsx",
  );
  const mobilePlans = await read(
    "src/pages/admin/ResponsiveSubscriptionOptionsPage.jsx",
  );

  assert.match(landing, /plan\.planCode !== "free"/);
  assert.match(pricing, /plan\.planCode !== "free"/);
  assert.match(desktopPlans, /option\.plan_code !== "free"/);
  assert.match(mobilePlans, /option\.plan_code !== "free"/);
  assert.match(desktopPlans, /freeOption\?\.eligible/);
  assert.match(desktopPlans, /Continue with Free/);
  assert.match(mobilePlans, /Continue on Free/);
});

test("installed PWA nav floats above the safe area and iOS header stays crisp", async () => {
  const css = await read("src/styles/mobilePlatformFixes.css");
  assert.match(css, /data-standalone-pwa="true"\] \[data-mobile-bottom-nav="true"\]/);
  assert.match(css, /bottom: calc\(1rem \+ env\(safe-area-inset-bottom, 0px\)\) !important/);
  assert.match(css, /data-pwa-platform="ios"/);
  assert.match(css, /\.dashboard-topbar/);
  assert.match(css, /transform: none !important/);
  assert.match(css, /--mobile-bottom-nav-clearance/);
  assert.match(css, /-webkit-backdrop-filter: none !important/);
  assert.match(css, /backdrop-filter: none !important/);
  assert.match(css, /data-mobile-billing-action/);
  assert.match(css, /position: fixed/);
  assert.match(css, /safe-area-inset-top/);
});

test("dark payment and dashboard hero cards keep brand colour as a strip only", async () => {
  const [
    themeCss,
    primitives,
    billingPage,
    mobilePlans,
    desktopPlans,
    publicCard,
  ] = await Promise.all([
    read("src/index.css"),
    read("src/components/dashboard/DashboardPrimitives.jsx"),
    read("src/pages/admin/BillingPage.jsx"),
    read("src/pages/admin/ResponsiveSubscriptionOptionsPage.jsx"),
    read("src/pages/admin/SubscriptionOptionsPage.jsx"),
    read("src/components/subscriptions/PublicPricingCard.jsx"),
  ]);

  assert.match(primitives, /brand-strip-card dashboard-welcome-blue/);
  assert.match(billingPage, /brand-strip-card dashboard-welcome-blue/);
  assert.match(mobilePlans, /payment-plan-card-selected brand-strip-card/);
  assert.match(desktopPlans, /payment-plan-card-selected brand-strip-card/);
  assert.match(publicCard, /payment-plan-card-selected brand-strip-card/);
  assert.match(
    themeCss,
    /:root\[data-theme="dark"\] \.brand-strip-card::before[\s\S]*?background:\s*rgb\(var\(--color-primary\)\)/,
  );
  assert.match(
    themeCss,
    /:root\[data-theme="dark"\] \.dashboard-welcome-blue,[\s\S]*?background:\s*rgb\(var\(--color-surface-raised\)\)\s*!important/,
  );
  assert.match(
    themeCss,
    /:root\[data-theme="dark"\] \.payment-plan-card-selected,[\s\S]*?background:\s*rgb\(var\(--color-surface-raised\)\)\s*!important/,
  );
  assert.doesNotMatch(
    themeCss,
    /dashboard-welcome-blue[\s\S]{0,220}box-shadow:\s*inset 0 3px 0/,
  );
});

test("theme chrome follows the resolved application theme", async () => {
  const source = await read("src/utils/themeChromeSync.js");
  assert.match(source, /style\.colorScheme/);
  assert.match(source, /meta\[name="theme-color"\]/);
  assert.match(source, /meta\[name="color-scheme"\]/);
  assert.match(source, /MutationObserver/);
  assert.match(source, /weave:accessibility-preferences-changed/);
});

test("mobile browser uses one authoritative theme-color while PWA stays isolated", async () => {
  const runtime = await read("src/utils/themeChromeSync.js");
  const startup = await read("public/theme-init.js");
  const preferences = await read("src/utils/accessibilityPreferences.js");
  const html = await read("index.html");

  assert.match(runtime, /display-mode: standalone/);
  assert.match(runtime, /isStandalonePwa/);
  assert.match(runtime, /replaceMeta/);
  assert.match(runtime, /requestAnimationFrame/);
  assert.match(runtime, /BROWSER_THEME_RECHECK_DELAY_MS/);
  assert.match(runtime, /content: "light dark"/);
  assert.doesNotMatch(runtime, /oppositeTheme|not all/);
  assert.match(startup, /data-weave-theme/);
  assert.match(
    startup,
    /colorSchemeMeta\.setAttribute\("content", "light dark"\)/,
  );
  assert.doesNotMatch(startup, /oppositeTheme|not all/);
  assert.match(preferences, /scheduleThemeChromeSync\(\)/);
  assert.doesNotMatch(preferences, /themeColorMeta/);
  assert.doesNotMatch(html, /<meta name="theme-color" content="#0F172A"\s*\/>/);
  assert.ok(
    html.indexOf('<script src="/theme-init.js"></script>') <
      html.indexOf('<link rel="manifest"'),
  );
});
