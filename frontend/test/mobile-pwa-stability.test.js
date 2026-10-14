import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("mobile PWA stability is initialized after the interaction-only styles", async () => {
  const mainSource = await read("src/main.jsx");

  const interactionStyleIndex = mainSource.indexOf("./styles/pwaInteractions.css");
  const stabilityStyleIndex = mainSource.indexOf("./styles/mobilePwaStability.css");

  assert.ok(interactionStyleIndex >= 0);
  assert.ok(stabilityStyleIndex > interactionStyleIndex);
  assert.match(mainSource, /installMobilePwaStability\(\)/);
});

test("the runtime separates platform, keyboard, and stable layout state without pricing DOM patching", async () => {
  const source = await read("src/utils/mobilePwaStability.js");

  assert.match(source, /dataset\.pwaPlatform/);
  assert.match(source, /dataset\.keyboardOpen/);
  assert.match(source, /--pwa-layout-height/);
  assert.match(source, /--virtual-keyboard-height/);
  assert.match(source, /visualViewport/);
  assert.match(source, /orientationchange/);
  assert.match(source, /visibilitychange/);
  assert.match(source, /focusin/);
  assert.match(source, /focusout/);
  assert.doesNotMatch(source, /pricingCardCarousel/);
  assert.doesNotMatch(source, /pricingTabsScroll/);
  assert.doesNotMatch(source, /MutationObserver/);
  assert.doesNotMatch(source, /pushState/);
  assert.doesNotMatch(source, /replaceState/);
});

test("the stable layout uses the visible PWA viewport instead of the larger document viewport", async () => {
  const source = await read("src/utils/mobilePwaStability.js");

  assert.match(source, /const getLayoutViewportHeight = \(\) =>/);
  assert.match(source, /const innerHeight = Number\(window\.innerHeight \|\| 0\)/);
  assert.match(source, /if \(innerHeight > 0\) return Math\.round\(innerHeight\)/);
  assert.match(source, /window\.visualViewport\?\.height/);
  assert.doesNotMatch(
    source,
    /Math\.max\([\s\S]{0,100}window\.innerHeight[\s\S]{0,100}document\.documentElement\.clientHeight/,
  );
  assert.doesNotMatch(source, /root\.style\.setProperty\(["']--pwa-layout-height/);
  assert.match(source, /root\.style\.removeProperty\("--pwa-layout-height"\)/);
});

test("the PWA navbar geometry remains frozen while scroll ownership changes", async () => {
  const css = await read("src/styles/mobilePwaStability.css");

  assert.match(
    css,
    /padding-bottom:\s*max\(\s*0\.375rem,\s*calc\(env\(safe-area-inset-bottom,\s*0px\)\s*-\s*0\.875rem\)/,
  );
  assert.match(
    css,
    /data-mobile-bottom-nav="true"[\s\S]*?bottom:\s*0\s*!important/,
  );
  assert.doesNotMatch(css, /transform:\s*translate3d\(0, -100%, 0\)\s*!important/);
  assert.doesNotMatch(css, /calc\(env\(safe-area-inset-bottom, 0px\) - 1\.8rem\)/);
  assert.match(
    css,
    /data-keyboard-open="true"[\s\S]*?transform:\s*translate3d\(0, 0, 0\)\s*!important/,
  );
  assert.doesNotMatch(css, /var\(--virtual-keyboard-height\)/);
  assert.match(
    css,
    /data-mobile-bottom-nav="true"[\s\S]*?position:\s*fixed\s*!important/,
  );
  assert.match(
    css,
    /data-mobile-bottom-nav="true"[\s\S]*?z-index:\s*70\s*!important/,
  );
  assert.match(
    css,
    /data-mobile-bottom-nav="true"[\s\S]*?pointer-events:\s*none/,
  );
  assert.match(
    css,
    /data-mobile-bottom-nav="true"\]\s*>\s*div[\s\S]*?pointer-events:\s*auto/,
  );
  assert.match(
    css,
    /data-modal-open="true"[\s\S]*?data-mobile-bottom-nav="true"[\s\S]*?visibility:\s*hidden\s*!important/,
  );
});

test("every actor dashboard uses the shared vertically scrollable viewport and navbar clearance", async () => {
  const [css, shellSource] = await Promise.all([
    read("src/styles/mobilePwaStability.css"),
    read("src/components/layout/DashboardLayout.jsx"),
  ]);
  const routeFiles = [
    "src/routes/adminRoutes.jsx",
    "src/routes/teacherRoutes.jsx",
    "src/routes/studentRoutes.jsx",
    "src/routes/parentRoutes.jsx",
    "src/routes/superadminRoutes.jsx",
  ];

  assert.match(css, /--mobile-bottom-nav-clearance/);
  assert.match(
    css,
    /#dashboard-scroll-viewport[\s\S]*?flex:\s*1 1 0%\s*!important[\s\S]*?height:\s*auto\s*!important[\s\S]*?overflow-y:\s*auto\s*!important/,
  );
  assert.match(
    css,
    /#dashboard-scroll-viewport[\s\S]*?scroll-padding-bottom:\s*var\(--mobile-bottom-nav-clearance\)/,
  );
  assert.match(
    css,
    /#dashboard-content[\s\S]*?height:\s*auto\s*!important[\s\S]*?overflow:\s*visible\s*!important[\s\S]*?padding-bottom:\s*var\(--mobile-bottom-nav-clearance\)\s*!important/,
  );
  assert.match(shellSource, /id="dashboard-scroll-viewport"/);
  assert.match(shellSource, /min-h-0 flex-1 overflow-y-auto/);
  assert.match(shellSource, /id="dashboard-content"/);

  for (const path of routeFiles) {
    const source = await read(path);
    assert.match(source, /DashboardShell/);
  }
});

test("installed bottom navigation publishes its measured obstruction as shared clearance", async () => {
  const [navSource, platformCss, interactionCss] = await Promise.all([
    read("src/components/layout/BottomNav.jsx"),
    read("src/styles/mobilePlatformFixes.css"),
    read("src/styles/pwaInteractions.css"),
  ]);

  assert.match(navSource, /BOTTOM_NAV_CONTENT_GAP_PX/);
  assert.match(navSource, /getBoundingClientRect\(\)/);
  assert.match(navSource, /obstructionHeight/);
  assert.match(navSource, /--mobile-bottom-nav-clearance/);
  assert.match(navSource, /ResizeObserver/);
  assert.match(
    platformCss,
    /data-mobile-billing-action="true"[\s\S]*?bottom:\s*var\(--mobile-bottom-nav-clearance\)\s*!important/,
  );
  assert.match(
    platformCss,
    /data-mobile-billing-page="true"[\s\S]*?padding-bottom:\s*calc\(var\(--mobile-bottom-nav-clearance\) \+ 9rem\)\s*!important/,
  );
  assert.match(
    interactionCss,
    /data-academic-workflow-navigator="true"[\s\S]*?bottom:\s*var\(--mobile-bottom-nav-clearance\)/,
  );
});

test("all role guide pages own a full visible-height PWA scroll surface", async () => {
  const [css, shellSource, roleGuideSource, adminGuideSource] = await Promise.all([
    read("src/styles/mobilePwaStability.css"),
    read("src/components/layout/DashboardLayout.jsx"),
    read("src/pages/shared/RoleGettingStartedPage.jsx"),
    read("src/pages/admin/AdminGettingStartedPage.jsx"),
  ]);

  assert.match(shellSource, /data-guide-page="true"/);
  assert.match(roleGuideSource, /DashboardLayout/);
  assert.match(adminGuideSource, /DashboardLayout/);
  assert.match(
    css,
    /\[data-guide-page="true"\][\s\S]*?position:\s*fixed\s*!important[\s\S]*?inset:\s*0\s*!important/,
  );
  assert.match(
    css,
    /\[data-guide-page="true"\][\s\S]*?height:\s*var\(--pwa-layout-height\)\s*!important[\s\S]*?overflow-y:\s*auto\s*!important/,
  );
  assert.match(
    css,
    /\[data-guide-page="true"\]\s*>\s*main[\s\S]*?height:\s*auto\s*!important[\s\S]*?max-height:\s*none\s*!important[\s\S]*?overflow:\s*visible\s*!important/,
  );
  assert.doesNotMatch(
    css,
    /#dashboard-scroll-viewport,\s*[\s\S]{0,300}\[data-guide-page="true"\][\s\S]{0,300}height:\s*100%\s*!important/,
  );
});

test("public, authentication, nested, and modal surfaces each retain a valid scroll owner", async () => {
  const [css, modalSource] = await Promise.all([
    read("src/styles/mobilePwaStability.css"),
    read("src/components/ui/Modal.jsx"),
  ]);

  assert.match(
    css,
    /\[data-pwa-scroll-root="true"\][\s\S]*?height:\s*100%\s*!important[\s\S]*?overflow-y:\s*auto\s*!important/,
  );
  assert.match(
    css,
    /\.public-page-shell,[\s\S]*?\.auth-surface[\s\S]*?height:\s*100%\s*!important[\s\S]*?overflow-y:\s*auto\s*!important/,
  );
  assert.match(modalSource, /z-\[100\]/);
  assert.match(modalSource, /data-modal-panel="true"/);
  assert.match(modalSource, /data-modal-header="true"/);
  assert.match(modalSource, /data-modal-scroll-container="true"/);
  assert.match(modalSource, /data-modal-footer="true"/);
  assert.match(modalSource, /min-h-0 flex-1 overflow-y-auto/);
  assert.match(
    css,
    /data-modal-scroll-container="true"[\s\S]*?min-height:\s*0[\s\S]*?overflow-y:\s*auto\s*!important/,
  );
});

test("mobile billing is an explicit mobile-first view while desktop retains the existing page", async () => {
  const [routeSource, billingSource] = await Promise.all([
    read("src/routes/adminRoutes.jsx"),
    read("src/pages/admin/ResponsiveSubscriptionOptionsPage.jsx"),
  ]);

  assert.match(routeSource, /ResponsiveSubscriptionOptionsPage/);
  assert.match(billingSource, /MobileSubscriptionOptionsPage/);
  assert.match(billingSource, /SubscriptionOptionsPage/);
  assert.match(billingSource, /data-mobile-billing-page="true"/);
  assert.match(billingSource, /data-mobile-billing-action="true"/);
  assert.match(billingSource, /Everything included/);
  assert.match(billingSource, /Plan capacity/);
  assert.doesNotMatch(billingSource, /grid-flow-col/);
  assert.doesNotMatch(billingSource, /overflow-x-auto/);
});

test("superadmin bottom navigation has a valid verification route", async () => {
  const routes = await read("src/routes/superadminRoutes.jsx");
  assert.match(routes, /path="\/superadmin\/verification"/);
});
