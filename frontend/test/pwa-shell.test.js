import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");
const readBytes = (path) => readFile(new URL(`../${path}`, import.meta.url));

const readPngDimensions = (buffer) => {
  assert.deepEqual(
    [...buffer.subarray(0, 8)],
    [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a],
  );
  assert.equal(buffer.subarray(12, 16).toString("ascii"), "IHDR");
  return {
    width: buffer.readUInt32BE(16),
    height: buffer.readUInt32BE(20),
    bitDepth: buffer[24],
    colorType: buffer[25],
  };
};

test("the mobile bottom navigation renders only in installed app context", async () => {
  const source = await read("src/components/layout/BottomNav.jsx");

  assert.doesNotMatch(source, /onTouchMove\s*=/);
  assert.doesNotMatch(source, /\btouch-none\b/);
  assert.doesNotMatch(source, /\boverscroll-none\b/);
  assert.match(source, /display-mode:\s*standalone/);
  assert.match(source, /if\s*\(!isPwaDisplay\)\s*return\s+null/);
  assert.match(source, /data-mobile-bottom-nav="true"/);
  assert.match(source, /aria-label="Primary mobile app navigation"/);
});

test("mobile bottom navigation uses live inbox routes and keeps Home centered", async () => {
  const [source, adminRoutes, teacherRoutes, studentRoutes, parentRoutes, superadminRoutes, interactionsCss] = await Promise.all([
    read("src/components/layout/BottomNav.jsx"),
    read("src/routes/adminRoutes.jsx"),
    read("src/routes/teacherRoutes.jsx"),
    read("src/routes/studentRoutes.jsx"),
    read("src/routes/parentRoutes.jsx"),
    read("src/routes/superadminRoutes.jsx"),
    read("src/styles/pwaInteractions.css"),
  ]);
  const routeSource = [
    adminRoutes,
    teacherRoutes,
    studentRoutes,
    parentRoutes,
    superadminRoutes,
  ].join("\n");

  assert.doesNotMatch(source, /\/admin\/announcements|\/superadmin\/announcements/);
  assert.doesNotMatch(source, /label: "Notices"/);
  assert.match(source, /label: "Inbox", to: "\/admin\/inbox"/);
  assert.match(source, /label: "Inbox", to: "\/teacher\/inbox"/);
  assert.match(source, /label: "Inbox", to: "\/student\/inbox"/);
  assert.match(source, /label: "Inbox", to: "\/parent\/inbox"/);
  assert.match(source, /label: "Inbox", to: "\/superadmin\/inbox"/);
  assert.doesNotMatch(interactionsCss, /\/admin\/announcements|\/admin\/messages/);
  assert.match(interactionsCss, /Academics, Inbox, Home, Calendar, Menu/);

  const roleBlocks = [
    ...source.matchAll(/\s{2}(admin|teacher|student|parent|superadmin): \[([\s\S]*?)\n\s{2}\]/g),
  ];
  assert.equal(roleBlocks.length, 5);

  for (const [, role, block] of roleBlocks) {
    const labels = [...block.matchAll(/label: "([^"]+)"/g)].map((match) => match[1]);
    const paths = [...block.matchAll(/to: "([^"]+)"/g)].map((match) => match[1]);
    assert.equal(labels.length, 4, `${role} should expose four links plus Menu`);
    assert.equal(labels[2], "Home", `${role} Home should be the centered third link`);
    assert.equal((labels.length + 1) % 2, 1, `${role} link count plus Menu should be odd`);

    for (const routePath of paths) {
      assert.match(
        routeSource,
        new RegExp(`path="${routePath.replaceAll("/", "\\/")}"`),
        `${routePath} should be a real route`,
      );
    }
  }
});

test("standalone PWA scrolling and floating dock geometry have one final authority", async () => {
  const [stabilityCss, interactionCss, directoryCss, mainSource] = await Promise.all([
    read("src/styles/mobilePwaStability.css"),
    read("src/styles/pwaInteractions.css"),
    read("src/styles/mobileDirectoryCards.css"),
    read("src/main.jsx"),
  ]);

  assert.match(
    stabilityCss,
    /data-mobile-bottom-nav="true"[\s\S]*?position:\s*fixed\s*!important/,
  );
  assert.match(stabilityCss, /transform:\s*translate3d\(0, 0, 0\)\s*!important/);
  assert.doesNotMatch(stabilityCss, /var\(--virtual-keyboard-height\)/);
  assert.match(
    stabilityCss,
    /data-mobile-bottom-nav="true"[\s\S]*?background:\s*transparent\s*!important/,
  );
  assert.match(
    stabilityCss,
    /data-mobile-bottom-nav="true"[\s\S]*?pointer-events:\s*none/,
  );
  assert.match(
    stabilityCss,
    /data-mobile-bottom-nav="true"\]\s*>\s*div[\s\S]*?pointer-events:\s*auto/,
  );
  assert.match(
    stabilityCss,
    /data-pwa-platform="ios"[\s\S]*?--pwa-device-screen-height/,
  );
  assert.doesNotMatch(stabilityCss, /safe-area-inset-bottom, 0px\) - 1\.8rem/);
  assert.match(
    stabilityCss,
    /#dashboard-scroll-viewport[\s\S]*?overflow-y:\s*auto\s*!important/,
  );
  assert.match(stabilityCss, /touch-action:\s*pan-y pinch-zoom\s*!important/);
  assert.doesNotMatch(
    interactionCss,
    /data-mobile-bottom-nav="true"[\s\S]*?position:\s*fixed/,
  );
  assert.doesNotMatch(
    directoryCss,
    /data-mobile-bottom-nav="true"[\s\S]*?position:\s*absolute\s*!important/,
  );

  const dashboardIndex = mainSource.indexOf("./styles/mobileDashboard.css");
  const directoryIndex = mainSource.indexOf("./styles/mobileDirectoryCards.css");
  const interactionIndex = mainSource.indexOf("./styles/pwaInteractions.css");
  const stabilityIndex = mainSource.indexOf("./styles/mobilePwaStability.css");
  assert.ok(
    dashboardIndex >= 0
      && directoryIndex >= 0
      && interactionIndex >= 0
      && stabilityIndex >= 0,
  );
  assert.ok(stabilityIndex > dashboardIndex && stabilityIndex > directoryIndex);
  assert.ok(stabilityIndex > interactionIndex);
});

test("Android and iOS receive versioned installable app metadata", async () => {
  const [manifestSource, html] = await Promise.all([
    read("public/manifest.json"),
    read("index.html"),
  ]);
  const manifest = JSON.parse(manifestSource);

  assert.equal(manifest.id, "/");
  assert.equal(manifest.start_url, "/");
  assert.equal(manifest.scope, "/");
  assert.equal(manifest.display, "standalone");
  assert.equal(manifest.prefer_related_applications, false);
  assert.ok(
    manifest.icons.some(
      (icon) =>
        icon.type === "image/png"
        && icon.sizes === "192x192"
        && icon.purpose === "any"
        && icon.src.includes("weave-pwa-3"),
    ),
  );
  assert.ok(
    manifest.icons.some(
      (icon) =>
        icon.type === "image/png"
        && icon.sizes === "512x512"
        && icon.purpose === "any"
        && icon.src.includes("weave-pwa-3"),
    ),
  );
  assert.ok(
    manifest.icons.some(
      (icon) =>
        icon.type === "image/png"
        && icon.sizes === "512x512"
        && icon.purpose === "maskable"
        && icon.src.includes("weave-pwa-3"),
    ),
  );
  assert.match(html, /rel="manifest"[^>]+manifest\.json\?v=weave-pwa-3/);
  assert.match(html, /rel="apple-touch-icon"[^>]+weave-180\.png\?v=weave-pwa-3/);
  assert.match(html, /rel="icon"[^>]+image\/png[^>]+weave-192\.png\?v=weave-pwa-3/);
  assert.match(html, /name="mobile-web-app-capable" content="yes"/);
  assert.match(html, /name="apple-mobile-web-app-capable" content="yes"/);
});

test("generated Android and iOS app icons are valid opaque PNGs", async () => {
  const expectedIcons = [
    ["public/icons/weave-180.png", 180],
    ["public/icons/weave-192.png", 192],
    ["public/icons/weave-512.png", 512],
    ["public/icons/weave-maskable-512.png", 512],
  ];

  for (const [path, expectedSize] of expectedIcons) {
    const dimensions = readPngDimensions(await readBytes(path));
    assert.equal(dimensions.width, expectedSize);
    assert.equal(dimensions.height, expectedSize);
    assert.equal(dimensions.bitDepth, 8);
    assert.equal(dimensions.colorType, 2);
  }
});

test("the service worker enables detection without caching or intercepting the app", async () => {
  const [mainSource, serviceWorker, vercelSource] = await Promise.all([
    read("src/main.jsx"),
    read("public/sw.js"),
    read("vercel.json"),
  ]);
  const vercelConfig = JSON.parse(vercelSource);

  assert.match(mainSource, /import\.meta\.env\.PROD/);
  assert.match(mainSource, /serviceWorker[\s\S]*?register\("\/sw\.js"/);
  assert.match(serviceWorker, /addEventListener\("install"/);
  assert.match(serviceWorker, /addEventListener\("activate"/);
  assert.match(serviceWorker, /addEventListener\("fetch"/);
  assert.doesNotMatch(serviceWorker, /respondWith\s*\(/);
  assert.doesNotMatch(serviceWorker, /caches\.open\s*\(/);

  const manifestHeaders = vercelConfig.headers.find(
    (entry) => entry.source === "/manifest.json",
  );
  const serviceWorkerHeaders = vercelConfig.headers.find(
    (entry) => entry.source === "/sw.js",
  );
  assert.ok(manifestHeaders);
  assert.ok(serviceWorkerHeaders);
  assert.ok(
    manifestHeaders.headers.some(
      (header) =>
        header.key === "Content-Type"
        && header.value.startsWith("application/manifest+json"),
    ),
  );
  assert.ok(
    serviceWorkerHeaders.headers.some(
      (header) =>
        header.key === "Service-Worker-Allowed" && header.value === "/",
    ),
  );
});
