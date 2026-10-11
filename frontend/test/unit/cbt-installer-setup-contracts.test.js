import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.resolve(__dirname, "../..");
const readSource = (relativePath) =>
  readFile(path.join(frontendRoot, relativePath), "utf8");

test("Pair Server opens installer setup before any pairing code is issued", async () => {
  const serversPage = await readSource("src/pages/admin/CBTServersPage.jsx");
  const setupPage = await readSource("src/pages/admin/CBTServerSetupPage.jsx");

  assert.match(serversPage, /navigate\("\/admin\/cbt\/setup-server"\)/);
  assert.doesNotMatch(
    serversPage,
    /const beginPairingSetup[\s\S]*createPairingCode\(/,
  );
  assert.match(setupPage, /cbtService\.createPairingCode\(\)/);
  assert.match(setupPage, /navigate\("\/admin\/cbt\/pairing-code"/);
});

test("CBT setup page downloads backend-selected release metadata", async () => {
  const service = await readSource("src/services/cbtService.js");
  const setupPage = await readSource("src/pages/admin/CBTServerSetupPage.jsx");

  assert.match(service, /getLatestRelease/);
  assert.match(service, /\/cbt\/releases\/latest/);
  assert.match(setupPage, /cbtService\.getLatestRelease\(\)/);
  assert.match(setupPage, /release\.installer_url/);
  assert.match(setupPage, /release\?\.manager_version/);
  assert.match(setupPage, /release\?\.cbt_version/);
  assert.match(setupPage, /Environment matched automatically/);
});

test("installer download is dispatched exactly once without opening or navigating to GitHub", async () => {
  const setupPage = await readSource("src/pages/admin/CBTServerSetupPage.jsx");

  assert.match(setupPage, /document\.createElement\("a"\)/);
  assert.match(setupPage, /downloadLink\.href = release\.installer_url/);
  assert.match(setupPage, /downloadLink\.click\(\)/);
  assert.doesNotMatch(setupPage, /window\.open\(/);
  assert.doesNotMatch(setupPage, /window\.location\.assign\(/);
});

test("CBT setup and pairing routes retain the subscription feature guard", async () => {
  const routes = await readSource("src/routes/adminRoutes.jsx");

  assert.match(routes, /path="\/admin\/cbt\/setup-server"/);
  assert.match(
    routes,
    /path="\/admin\/cbt\/setup-server"[\s\S]*SubscriptionFeatureRouteGuard featureCode=\{FEATURE_CODES\.CBT_PAIRING\}/,
  );
  assert.match(
    routes,
    /path="\/admin\/cbt\/pairing-code"[\s\S]*SubscriptionFeatureRouteGuard featureCode=\{FEATURE_CODES\.CBT_PAIRING\}/,
  );
});

test("CBT setup preserves pairing when official release metadata is unavailable", async () => {
  const setupPage = await readSource("src/pages/admin/CBTServerSetupPage.jsx");
  assert.match(setupPage, /disabled=\{creatingPairingCode\}/);
  assert.doesNotMatch(
    setupPage,
    /disabled=\{!release \|\| Boolean\(releaseError\) \|\| creatingPairingCode\}/,
  );
  assert.match(setupPage, /continueToPairing/);
});

test("CBT setup offers both Windows and Linux desktop plus CLI artifacts", async () => {
  const setupPage = await readSource("src/pages/admin/CBTServerSetupPage.jsx");
  assert.match(setupPage, /packageItem\.platform === "windows"/);
  assert.match(setupPage, /packageItem\.platform === "linux"/);
  assert.match(setupPage, /Download CLI/);
  assert.match(setupPage, /Linux Desktop \(\.deb\)/);
  assert.match(setupPage, /Linux CLI \(\.tar\.gz\)/);
});
