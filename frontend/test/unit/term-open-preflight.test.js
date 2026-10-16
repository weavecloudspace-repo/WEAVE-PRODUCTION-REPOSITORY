import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  activeTermOpenBlocker,
  dependencyOpenBlocker,
  termOpenPreflightBlocker,
} from "../../src/services/termOpenPreflight.js";

const frontendRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../..",
);

const readSource = (...segments) =>
  fs.readFileSync(path.join(frontendRoot, "src", ...segments), "utf8");

test("a paid future draft term is blocked while another term is still active", () => {
  const blocker = activeTermOpenBlocker(
    {
      items: [
        {
          id: "first-term",
          name: "first_term",
          status: "open",
          is_current: true,
        },
        {
          id: "second-term",
          name: "second_term",
          status: "draft",
          is_current: false,
        },
      ],
    },
    "second-term",
  );

  assert.equal(
    blocker,
    "First Term is currently active. Close it before opening another academic term.",
  );
});

test("a school can start with second term when no other term is active", () => {
  assert.equal(
    activeTermOpenBlocker(
      {
        items: [
          {
            id: "second-term",
            name: "second_term",
            status: "draft",
            is_current: false,
          },
        ],
      },
      "second-term",
    ),
    null,
  );
});

test("existing readiness blockers stop opening before the lifecycle request", () => {
  const preview = {
    can_open: false,
    blocker_messages: [
      "Assign departments to the affected classes before opening this term.",
    ],
  };

  assert.equal(
    dependencyOpenBlocker(preview),
    "Assign departments to the affected classes before opening this term.",
  );
  assert.equal(
    termOpenPreflightBlocker({
      currentTerms: { items: [] },
      targetTermId: "second-term",
      dependencyPreview: preview,
    }),
    preview.blocker_messages[0],
  );
});

test("openTerm rechecks the preflight before posting the open transition", () => {
  const service = readSource("services", "academicService.js");

  assert.match(service, /const preflightOpenTerm = async \(termId\) =>/);
  assert.match(service, /is_current: true, limit: 100/);
  assert.match(service, /await preflightOpenTerm\(termId\);/);
  assert.match(
    service,
    /await preflightOpenTerm\(termId\);\s*return api\.post\(`\/tenant-admin\/academics\/terms\/\$\{termId\}\/open`/,
  );
});

test("academic hub checks a draft term before showing its opening confirmation", () => {
  const workspace = readSource(
    "features",
    "academic-admin",
    "AcademicSetupWorkspace.jsx",
  );

  assert.match(workspace, /const prepareTermTransition = async \(item, transition\) =>/);
  assert.match(
    workspace,
    /academicService\.listTerms\(\{ is_current: true, limit: 100 \}\)/,
  );
  assert.match(workspace, /termOpenPreflightBlocker\(\{/);
  assert.match(workspace, /showError\(blocker\);\s*return;/);
  assert.match(workspace, /prepareTermTransition\(item, transition\);/);
  assert.match(workspace, /checkingTermId === item\.id\s*\? "Checking\.\.\."/);
});

test("missing Second Term calendar blocks opening in every frontend entry point", () => {
  const preview = {
    can_open: false,
    blocker_messages: ["Generate and activate a calendar for this term."],
    dependency_counts: { calendar_days: 0 },
  };
  assert.equal(
    termOpenPreflightBlocker({
      currentTerms: { items: [] },
      targetTermId: "second-term",
      dependencyPreview: preview,
    }),
    "Generate and activate a calendar for this term.",
  );
});
