import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  CBT_DOCS,
  CLI_COMMANDS,
  CLI_GROUPS,
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
  const commands = new Set(CLI_COMMANDS.flatMap((item) => [item.command, ...item.examples.map((example) => example.command)]));
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
  assert.match(docs, /openTopic\(item\.topicId, item\.sectionId, item\.groupId\)/);
  assert.match(docs, /window\.addEventListener\("keydown"/);
  assert.match(docs, /role="group" aria-label="Select command platform"/);
});

test("CLI groups cover everyday tasks with complete usage details", () => {
  assert.deepEqual(CLI_GROUPS.map((group) => group.id), ["diagnostics", "installation", "services", "logs", "networking", "updates"]);
  const cli = CBT_DOCS.find((topic) => topic.id === "cli");
  for (const group of CLI_GROUPS) {
    assert.ok(cli.sections.some((section) => section.commandGroupId === group.id));
    const commands = CLI_COMMANDS.filter((command) => command.groupId === group.id);
    assert.ok(commands.length);
    for (const command of commands) {
      assert.ok(command.usage && command.explanation && command.platforms && command.access && command.outcome);
      assert.ok(command.examples.length);
    }
  }
});

test("documented example flags match the reviewed CBT CLI command signatures", () => {
  // Contract captured from weave_cbt deployment CLI at 03c3eb6.
  const supported = {
    release: [], status: ["--json"], doctor: [], start: [], stop: [], restart: [],
    install: ["--env-file", "--assets-dir", "--install-dir", "--data-dir", "--rootfs-archive", "--version", "--min-free-gib"],
    logs: ["--follow", "-f"], lan: ["--listen-address", "--client-subnet", "--refresh", "--remove"],
    tls: ["--dry-run", "--renew", "--activate"], "self-update": ["--check", "--yes", "-y"], update: ["--yes", "--image"],
  };
  for (const item of CLI_COMMANDS) {
    for (const example of item.examples) {
      const [, name] = example.command.match(/(?:sudo )?weave (\S+)/);
      if (name === "--help") continue;
      assert.ok(Object.hasOwn(supported, name), `Unsupported command: ${name}`);
      const flags = example.command.match(/--[a-z-]+|(?<=\s)-[a-z](?=\s|$)/g) || [];
      for (const flag of flags) assert.ok(flag === "--help" || supported[name].includes(flag), `${name} does not support ${flag}`);
      if (name === "tls") assert.ok(flags.filter((flag) => ["--dry-run", "--renew", "--activate"].includes(flag)).length <= 1);
      if (name === "logs") {
        const service = example.command.split(" ")[2];
        assert.ok(!service || service.startsWith("-") || ["api", "worker", "postgres", "redis", "nginx", "bootstrap"].includes(service));
      }
    }
  }
});

test("search indexes CLI flags and examples and routes results to their command group", () => {
  for (const [query, groupId] of [["--client-subnet", "networking"], ["--env-file", "installation"], ["weave logs worker --follow", "logs"], ["self-update --check", "updates"]]) {
    assert.ok(searchCbtDocs(query).some((result) => result.topicId === "cli" && result.groupId === groupId && result.sectionId === "cli-" + groupId));
  }
});

test("documentation does not expose deployment environment types", async () => {
  const readerContent = JSON.stringify([CBT_DOCS, CLI_COMMANDS]);
  assert.doesNotMatch(readerContent, /staging|production|release channel|selected environment/i);
  const docs = await source("src/pages/admin/CBTServerDocumentationPage.jsx");
  assert.doesNotMatch(docs, /Linux desktop \(\.deb\)|Linux CLI \(\.tar\.gz\)|staging|production|environment/i);
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
