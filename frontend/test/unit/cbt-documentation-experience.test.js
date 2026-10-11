import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  CBT_DOCS,
  CLI_COMMANDS,
  searchCbtDocs,
} from "../../src/features/cbt/cbtDocumentationContent.js";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const source = (relativePath) => readFile(path.join(root, relativePath), "utf8");

test("CBT documentation covers the install-to-exam lifecycle", () => {
  const categories = CBT_DOCS.map((topic) => topic.id);
  assert.deepEqual(categories, [
    "quick-start",
    "windows",
    "linux",
    "cli",
    "pairing",
    "networking",
    "troubleshooting",
    "updates",
    "faq",
  ]);
  for (const topic of CBT_DOCS) {
    assert.ok(topic.sections.length, `No sections for ${topic.id}`);
    assert.equal(new Set(topic.sections.map((section) => section.id)).size, topic.sections.length);
  }
});

test("documentation search locates command syntax, CLI and LAN guidance", () => {
  assert.ok(searchCbtDocs("weave logs").some((result) => result.topicId === "cli"));
  assert.ok(searchCbtDocs("WSL2").some((result) => result.topicId === "windows"));
  assert.ok(searchCbtDocs("pairing").some((result) => result.topicId === "pairing"));
  assert.ok(searchCbtDocs("certificate").some((result) => result.topicId === "networking"));
  assert.deepEqual(searchCbtDocs("    "), []);
  assert.deepEqual(searchCbtDocs("phrase-unlikely-to-occur-here"), []);
});

test("CLI examples align with the actual management commands", () => {
  const commands = new Set(CLI_COMMANDS.map((item) => item.command));
  for (const command of [
    "weave --help",
    "weave release",
    "weave status --json",
    "weave doctor",
    "weave logs",
    "weave logs --follow",
    "weave start",
    "weave stop",
    "weave restart",
  ]) {
    assert.ok(commands.has(command), `Missing documented command: ${command}`);
  }
  assert.ok(CLI_COMMANDS.every((item) => item.description && item.category));
});

test("new documentation UI includes working navigation, copy actions and search", async () => {
  const docs = await source("src/pages/admin/CBTServerDocumentationPage.jsx");
  assert.match(docs, /searchCbtDocs\(query\)/);
  assert.match(docs, /navigator\.clipboard\.writeText\(command\)/);
  assert.match(docs, /aria-label="Search CBT documentation"/);
  assert.match(docs, /On this page/);
  assert.match(docs, /openTopic\(item\.topicId, item\.sectionId\)/);
  assert.match(docs, /window\.addEventListener\("keydown"/);
  assert.match(docs, /role="group" aria-label="Select command platform"/);
});

test("setup cards use verified release metadata and preserve pairing independence", async () => {
  const setup = await source("src/pages/admin/CBTServerSetupPage.jsx");
  assert.match(setup, /release\?\.packages\?\.find/);
  assert.match(setup, /release\.installer_url/);
  assert.match(setup, /packageItem\.sha256/);
  assert.doesNotMatch(setup, /Download checksums|release\?\.release_notes/);
  assert.match(setup, /Continue to pairing/);
  assert.match(setup, /disabled=\{creatingPairingCode\}/);
  assert.match(setup, /topic \? "\/admin\/cbt\/documentation\?topic="/);
  assert.doesNotMatch(setup, /window\.open\(/);
});
