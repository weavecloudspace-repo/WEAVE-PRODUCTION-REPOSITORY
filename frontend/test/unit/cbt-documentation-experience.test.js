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
  assert.ok(searchCbtDocs("weave-cbt-coredns.service").some((result) => result.topicId === "linux"));
  assert.deepEqual(searchCbtDocs("    "), []);
  assert.deepEqual(searchCbtDocs("phrase-unlikely-to-occur-here"), []);
});

test("native Linux CoreDNS and Windows elevation are documented", () => {
  const linux = CBT_DOCS.find((topic) => topic.id === "linux");
  assert.ok(linux.sections.some((section) => section.id === "linux-dns"));
  assert.ok(CLI_COMMANDS.find((item) => item.command === "weave network dns setup")
    .examples.some((example) => example.command.includes("--interface eth0")));
  const windows = CBT_DOCS.find((topic) => topic.id === "windows");
  assert.ok(windows.sections.some((section) => (section.paragraphs || []).join(" ").includes("native Windows UAC")));
});

test("manual Windows and Linux hosts-file mapping is the default documented CBT DNS path", async () => {
  const windows = CBT_DOCS.find((topic) => topic.id === "windows").sections
    .find((section) => section.id === "windows-hosts");
  const linux = CBT_DOCS.find((topic) => topic.id === "linux").sections
    .find((section) => section.id === "linux-hosts");
  const dns = CBT_DOCS.find((topic) => topic.id === "networking").sections
    .find((section) => section.id === "dns");
  assert.ok(windows);
  assert.ok(linux);
  assert.ok(dns);
  const commandsFor = (section) => section.commands.map((item) => item.command);
  assert.ok(commandsFor(windows).includes(String.raw`notepad C:\Windows\System32\drivers\etc\hosts`));
  assert.ok(commandsFor(windows).includes("ipconfig /flushdns"));
  assert.ok(commandsFor(linux).includes("sudo nano /etc/hosts"));
  assert.ok(commandsFor(linux).includes("getent hosts test-server1.testschool1.cbt.weavecloudspace.com"));
  assert.ok(commandsFor(linux).includes("sudo resolvectl flush-caches"));
  assert.ok(commandsFor(dns).includes("weave network dns setup"), "Optional CoreDNS must remain supported");
  assert.match(dns.paragraphs.join(" "), /CURRENT DEFAULT/);
  assert.match(dns.paragraphs.join(" "), /EACH Windows or Linux student computer/);
  assert.ok(searchCbtDocs("ipconfig /flushdns").some((result) => result.sectionId === "windows-hosts"));
  assert.ok(searchCbtDocs("/etc/hosts").some((result) => result.sectionId === "linux-hosts"));
  const setupPage = await source("src/pages/admin/CBTServerSetupPage.jsx");
  assert.match(setupPage, /Manual student DNS setup/);
  assert.match(setupPage, /topic: "networking"/);
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
    "weave network status",
    "weave network setup",
    "weave network trust",
    "weave network refresh",
    "weave network remove",
    "weave network dns status",
    "weave network dns setup",
    "weave network dns remove",
    "weave network url",
    "weave network doctor",
    "weave logs --errors",
    "weave reinstall",
    "weave rollback",
    "weave uninstall",
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

test("CLI reference covers every reviewed command and explains destructive recovery", () => {
  const expected = ["--help","install","start","stop","restart","reinstall","self-update","status","tls","logs","doctor","release","update","rollback","uninstall","network status","network setup","network trust","network refresh","network remove","network url","network doctor","network dns status","network dns setup","network dns remove"];
  assert.deepEqual(CLI_COMMANDS.map((item) => item.command.replace(/^weave /, "")).sort(), expected.sort());
  for (const name of ["reinstall", "rollback", "uninstall"]) {
    const command = CLI_COMMANDS.find((item) => item.command === `weave ${name}`);
    assert.match(command.note, /explicit.*authorization/i);
    assert.match(command.note, /lost|erases|data-loss/i);
  }
});

test("documented example flags match the reviewed CBT CLI command signatures", () => {
  // Reviewed against the unified CBT network CLI.
  const supported = {
    release: [], status: ["--json"], doctor: [], start: [], stop: [], restart: [],
    install: ["--env-file", "--assets-dir", "--install-dir", "--data-dir", "--rootfs-archive", "--version", "--min-free-gib"],
    logs: ["--follow", "-f", "--errors", "--date", "--last"],
    reinstall: ["--purge-data", "--yes", "-y"], rollback: [], uninstall: ["--purge-volumes", "--yes", "-y"],
    "network status": ["--json"], "network setup": ["--auto", "--listen-address", "--client-subnet", "--yes"],
    "network trust": ["--interface", "--yes"], "network refresh": [], "network remove": ["--yes"],
    "network url": ["--json"], "network doctor": [],
    "network dns status": ["--json"], "network dns setup": ["--interface"], "network dns remove": ["--yes"],
    tls: ["--dry-run", "--renew", "--activate"], "self-update": ["--check", "--yes", "-y"], update: ["--yes", "--image"],
  };
  for (const item of CLI_COMMANDS) {
    for (const example of item.examples) {
      const [, name] = example.command.match(/(?:sudo )?weave (network dns \S+|network \S+|\S+)/);
      if (name === "--help") continue;
      assert.ok(Object.hasOwn(supported, name), `Unsupported command: ${name}`);
      const flags = example.command.match(/--[a-z-]+|(?<=\s)-[a-z](?=\s|$)/g) || [];
      for (const flag of flags) assert.ok(flag === "--help" || supported[name].includes(flag), `${name} does not support ${flag}`);
      if (name === "tls") assert.ok(flags.filter((flag) => ["--dry-run", "--renew", "--activate"].includes(flag)).length <= 1);
      if (name === "logs") {
        assert.ok(!flags.includes("--errors") || !flags.some((flag) => ["--follow", "-f"].includes(flag)));
        if (flags.some((flag) => ["--date", "--last"].includes(flag))) assert.ok(flags.includes("--errors"));
        const service = example.command.split(" ")[2];
        assert.ok(!service || service.startsWith("-") || ["api", "worker", "postgres", "redis", "nginx", "bootstrap"].includes(service));
      }
    }
  }
});

test("search indexes CLI flags and examples and routes results to their command group", () => {
  for (const [query, groupId] of [["--client-subnet", "networking"], ["--env-file", "installation"], ["weave logs worker --follow", "logs"], ["self-update --check", "updates"], ["network setup --auto", "networking"], ["--errors", "logs"], ["--purge-data", "installation"], ["weave rollback", "updates"]]) {
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
