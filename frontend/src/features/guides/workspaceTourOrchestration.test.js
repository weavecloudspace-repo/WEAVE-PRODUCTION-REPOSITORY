import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { didCompleteInitialOnboarding } from "../../components/layout/onboardingOrchestration.js";
import {
  canAutoShowTour,
  queueInitialTour,
  TOUR_QUEUED_STEP,
} from "./workspaceTourState.js";

const sourceRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const readSource = (...segments) =>
  fs.readFileSync(path.join(sourceRoot, ...segments), "utf8").replace(/\r\n/g, "\n");

test("explicit first-workspace eligibility is persisted only from a fresh guide", async () => {
  const updates = [];
  const service = {
    getState: async () => ({ status: "not_started", sync_pending: false }),
    updateState: async (_key, payload) => {
      updates.push(payload);
      return { ...payload, sync_pending: false };
    },
  };

  const queued = await queueInitialTour("admin", true, service);
  assert.equal(queued, true);
  assert.deepEqual(updates, [
    {
      status: "in_progress",
      current_step: TOUR_QUEUED_STEP,
      remind_after: null,
    },
  ]);
});

test("completed or dismissed users are never automatically requeued", async () => {
  for (const status of ["completed", "dismissed"]) {
    let writes = 0;
    const service = {
      getState: async () => ({ status, sync_pending: false }),
      updateState: async () => {
        writes += 1;
        return {};
      },
    };
    assert.equal(await queueInitialTour("teacher", true, service), false);
    assert.equal(writes, 0);
  }
});

test("non-terminal guide state can still be explicitly requeued when a caller opts in", async () => {
  const updates = [];
  const service = {
    getState: async () => ({
      status: "in_progress",
      current_step: "welcome_seen",
      sync_pending: false,
    }),
    updateState: async (_key, payload) => {
      updates.push(payload);
      return { ...payload, sync_pending: false };
    },
  };

  const queued = await queueInitialTour("admin", true, service, {
    requeueNonTerminal: true,
  });
  assert.equal(queued, true);
  assert.deepEqual(updates, [
    {
      status: "in_progress",
      current_step: TOUR_QUEUED_STEP,
      remind_after: null,
    },
  ]);
});

test("explicit requeue never reopens terminal workspace tours", async () => {
  for (const status of ["completed", "dismissed"]) {
    let writes = 0;
    const service = {
      getState: async () => ({ status, sync_pending: false }),
      updateState: async () => {
        writes += 1;
        return {};
      },
    };
    assert.equal(
      await queueInitialTour("admin", true, service, {
        requeueNonTerminal: true,
      }),
      false,
    );
    assert.equal(writes, 0);
  }
});

test("first-run onboarding completion is an explicit required-to-complete transition", () => {
  assert.equal(
    didCompleteInitialOnboarding({
      profileMode: "onboarding",
      wasRequired: true,
      nextStatus: { onboarding_required: false },
    }),
    true,
  );
  assert.equal(
    didCompleteInitialOnboarding({
      profileMode: "edit",
      wasRequired: true,
      nextStatus: { onboarding_required: false },
    }),
    false,
  );
  assert.equal(
    didCompleteInitialOnboarding({
      profileMode: "onboarding",
      wasRequired: false,
      nextStatus: { onboarding_required: false },
    }),
    false,
  );
  assert.equal(
    didCompleteInitialOnboarding({
      profileMode: "onboarding",
      wasRequired: true,
      nextStatus: { onboarding_required: true },
    }),
    false,
  );
});

test("only a durably queued welcome is eligible for automatic display", () => {
  assert.equal(
    canAutoShowTour({
      status: "in_progress",
      current_step: TOUR_QUEUED_STEP,
      sync_pending: false,
    }),
    true,
  );
  assert.equal(
    canAutoShowTour({
      status: "in_progress",
      current_step: TOUR_QUEUED_STEP,
      sync_pending: true,
    }),
    false,
  );
  assert.equal(canAutoShowTour({ status: "not_started", sync_pending: false }), false);
});

test("first-entry actor boundaries queue the workspace tour before guided setup", () => {
  const onboardingGate = readSource("components", "layout", "useOnboardingGate.js");
  const adminGettingStartedRoute = readSource("routes", "AdminGettingStartedRoute.jsx");
  const invitation = readSource("pages", "public", "InvitationAcceptancePage.jsx");
  const studentPassword = readSource("pages", "student", "StudentChangePasswordPage.jsx");
  const tourHook = readSource("features", "guides", "useWorkspaceTour.js");
  const teacherRoutes = readSource("routes", "teacherRoutes.jsx");
  const parentRoutes = readSource("routes", "parentRoutes.jsx");

  assert.match(onboardingGate, /onboardingWasRequiredRef/);
  assert.match(onboardingGate, /didCompleteInitialOnboarding/);
  assert.match(
    onboardingGate,
    /queueInitialTour\(\s*normalizedRole,\s*true,\s*guideService,\s*\{ requeueNonTerminal: true \},\s*\)/,
  );
  assert.doesNotMatch(
    onboardingGate,
    /profileMode === "onboarding" && onboardingState\.required && !required/,
  );
  assert.doesNotMatch(onboardingGate, /normalizedRole !== "admin"/);
  assert.doesNotMatch(adminGettingStartedRoute, /queueInitialTour/);
  assert.match(invitation, /queueInitialTour\(role, true, guideService\)/);
  assert.match(studentPassword, /queueInitialTour\("student", true, guideService\)/);
  assert.match(tourHook, /pathname !== `\/\$\{role\}\/dashboard`/);
  assert.match(tourHook, /TOUR_QUEUED_EVENT/);
  assert.match(tourHook, /const queuedWelcomeRef = useRef\(null\)/);
  assert.doesNotMatch(teacherRoutes, /\/teacher\/schools[\s\S]{0,180}onboardingModalEnabled=\{false\}/);
  assert.doesNotMatch(parentRoutes, /\/parent\/schools[\s\S]{0,180}onboardingModalEnabled=\{false\}/);
});

test("automatic welcome opens before persistence and becomes resumable", () => {
  const tourHook = readSource("features", "guides", "useWorkspaceTour.js");
  const start = tourHook.indexOf("const presentInitialWelcome = useCallback(");
  const end = tourHook.indexOf("const checkWelcome = useCallback", start);
  const welcomeClaim = tourHook.slice(start, end);
  const openAt = welcomeClaim.indexOf("setOpen(true)");
  const persistedAt = welcomeClaim.indexOf("current_step: pausedTourStep(-1)");

  assert.ok(start >= 0 && end > start);
  assert.ok(openAt >= 0);
  assert.ok(persistedAt > openAt);
  assert.doesNotMatch(welcomeClaim, /TOUR_SEEN_STEP/);
  assert.doesNotMatch(
    tourHook,
    /useEffect\(\(\) => \{\s*if \(!enabled \|\| !key\) return;\s*refreshState\(\)\.catch/,
  );
});

test("a queued first-run welcome is consumed directly in the current dashboard session", () => {
  const tourHook = readSource("features", "guides", "useWorkspaceTour.js");
  const queuedHandlerStart = tourHook.indexOf("const queued = (event) => {");
  const queuedHandlerEnd = tourHook.indexOf("const changed = (event) => {", queuedHandlerStart);
  const queuedHandler = tourHook.slice(queuedHandlerStart, queuedHandlerEnd);

  assert.ok(queuedHandlerStart >= 0 && queuedHandlerEnd > queuedHandlerStart);
  assert.match(queuedHandler, /queuedWelcomeRef\.current = canAutoShowTour\(queuedState\)/);
  assert.match(queuedHandler, /setQueueVersion/);

  const directConsumeStart = tourHook.indexOf("const queuedState = queuedWelcomeRef.current;");
  const directConsumeEnd = tourHook.indexOf("useEffect(() => {\n    if (!pendingRequest", directConsumeStart);
  const directConsume = tourHook.slice(directConsumeStart, directConsumeEnd);

  assert.ok(directConsumeStart >= 0 && directConsumeEnd > directConsumeStart);
  assert.match(directConsume, /if \(!canAutoShowTour\(queuedState\)\) return/);
  assert.match(directConsume, /presentInitialWelcome\(queuedState\)/);
  assert.doesNotMatch(directConsume, /refreshState\(/);
});

test("unknown onboarding status remains fail-closed", () => {
  const onboardingGate = readSource("components", "layout", "useOnboardingGate.js");
  const catchAt = onboardingGate.indexOf("} catch {");
  const failureBlock = onboardingGate.slice(catchAt, catchAt + 420);

  assert.ok(catchAt >= 0);
  assert.match(failureBlock, /loading: true/);
  assert.doesNotMatch(failureBlock, /loading: false/);
});

test("superadmin never receives a workspace tour key", () => {
  assert.equal(canAutoShowTour(null), false);
  const source = readSource("features", "guides", "workspaceTourState.js");
  assert.doesNotMatch(source, /\["admin", "teacher", "student", "parent", "superadmin"\]/);
});
