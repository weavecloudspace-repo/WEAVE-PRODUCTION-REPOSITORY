import { ArrowLeft, ArrowRight, Check, Compass, X } from "lucide-react";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { tourContentForItem } from "../../features/guides/workspaceTourContent";
import { filterAvailableItems } from "../../features/navigation/featureAvailability";
import { useSubscription } from "../../features/subscriptions/useSubscription";
import { useTeacherClassDutyAccess } from "../../features/teachers/TeacherClassDutyAccessContext";
import { useRuntimeConfig } from "../../hooks/useRuntimeConfig";
import { authSession, getErrorMessage } from "../../services/api";
import { navGroups } from "../layout/navConfig";
import Button from "../ui/Button";
import WorkspaceTourSnapshot from "./WorkspaceTourSnapshot";
import "./workspaceTour.css";

const focusable = 'button:not([disabled]), a[href], [tabindex="0"]';
const clamp = (value, min, max) =>
  Math.max(min, Math.min(value, Math.max(min, max)));

function connectorGeometry(card, target) {
  if (!card || !target) return null;
  const targetX = target.left + target.width + 2;
  const targetY = target.top + target.height / 2;
  const targetIsLeft = targetX < card.left;
  const startX = targetIsLeft ? card.left - 10 : card.left + card.width + 10;
  const startY = clamp(targetY, card.top + 42, card.top + card.height - 42);
  return {
    path: `M ${startX} ${startY} L ${targetX} ${targetY}`,
  };
}

export default function WorkspaceTour({
  role,
  onClose,
  onSetup,
  initialIndex = -1,
  focusTo = null,
  focusRoutes = null,
  dedicated = false,
  dedicatedKind = null,
}) {
  const subscription = useSubscription();
  const runtimeConfig = useRuntimeConfig();
  const { hasClassTeacherDuties } = useTeacherClassDutyAccess();
  const user = authSession.getUser() || {};
  const actorType = String(user?.actor_type || "").toLowerCase();
  const isAccountScope =
    ["parent_account", "teacher_account"].includes(actorType) &&
    !user?.tenant_id;
  const manifestKey = [
    role,
    dedicated ? "dedicated" : "standard",
    dedicatedKind || "",
    focusTo || "",
    ...(focusRoutes || []),
  ].join("|");
  const configuredItems = useMemo(() => {
    const availableItems = filterAvailableItems(
      (navGroups[role] || []).flatMap((group) => group.items),
      {
        subscription,
        runtimeFeatures: runtimeConfig?.features || {},
        isAccountScope,
        hasClassTeacherDuties,
      },
    );
    if (focusRoutes?.length) {
      const focusedRoutes = new Set(focusRoutes);
      return availableItems.filter((item) => focusedRoutes.has(item.to));
    }
    if (!focusTo) return availableItems;
    const settingsItem = availableItems.find(
      (item) => item.to === "/admin/settings",
    );
    const focusedItem = availableItems.find((item) => item.to === focusTo);
    if (focusedItem) return [focusedItem];
    if (!settingsItem) return availableItems;
    return [
      {
        ...settingsItem,
        to: focusTo,
        tourTarget: settingsItem.to,
        label: focusTo.endsWith("/branding")
          ? "School branding"
          : settingsItem.label,
      },
    ];
  }, [
    focusRoutes,
    focusTo,
    hasClassTeacherDuties,
    isAccountScope,
    role,
    runtimeConfig,
    subscription,
  ]);
  // The sidebar already filters pending and denied features. A replay should
  // never wait indefinitely for *all* subscription entitlements to load.
  const subscriptionReady = configuredItems.length > 0;
  const [steps, setSteps] = useState([]);
  const [index, setIndex] = useState(-1);
  const [geometry, setGeometry] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [confirmDismiss, setConfirmDismiss] = useState(false);
  const overlayRef = useRef(null);
  const cardRef = useRef(null);
  const headingRef = useRef(null);
  const actionLock = useRef(false);
  const restoredIndex = useRef(false);
  const manifestKeyRef = useRef(null);
  const step = steps[index];
  const welcome = index < 0;
  const last = index === steps.length - 1;
  const Icon = step?.icon || Compass;
  const visibleRoutes = steps.map((item) => item.to);

  useLayoutEffect(() => {
    if (!subscriptionReady) return;
    if (manifestKeyRef.current === manifestKey && steps.length) return;

    const rendered = new Set(
      Array.from(document.querySelectorAll("[data-tour-target]"))
        .filter((node) => node.getBoundingClientRect().width > 0)
        .map((node) => node.dataset.tourTarget),
    );
    const nextSteps = configuredItems
      // On iOS the drawer may not have a measurable rect on the first frame.
      // Reuse the already access-filtered navigation rather than disabling the
      // welcome action when WebKit temporarily reports no visible targets.
      .filter((item) => !rendered.size || rendered.has(item.tourTarget || item.to))
      .map((item) => ({
        ...tourContentForItem(role, item, { dedicated, dedicatedKind }),
        targetTo: item.tourTarget || item.to,
      }));

    if (!nextSteps.length) return;

    manifestKeyRef.current = manifestKey;
    restoredIndex.current = false;
    setSteps(nextSteps);
    setIndex(-1);
  }, [
    configuredItems,
    dedicated,
    dedicatedKind,
    manifestKey,
    role,
    steps.length,
    subscriptionReady,
  ]);

  useEffect(() => {
    if (restoredIndex.current || !steps.length) return;
    restoredIndex.current = true;
    if (Number.isInteger(initialIndex) && initialIndex >= 0) {
      setIndex(Math.min(initialIndex, steps.length - 1));
    } else if (dedicated) {
      setIndex(0);
    }
  }, [dedicated, initialIndex, steps.length]);

  useEffect(() => {
    const previousFocus = document.activeElement;
    const siblings = Array.from(document.body.children)
      .filter(
        (node) => node !== overlayRef.current && node instanceof HTMLElement,
      )
      .map((node) => [node, node.inert]);
    siblings.forEach(([node]) => {
      node.inert = true;
    });
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    headingRef.current?.focus({ preventScroll: true });
    return () => {
      siblings.forEach(([node, inert]) => {
        node.inert = inert;
      });
      document.body.style.overflow = previousOverflow;
      if (previousFocus?.isConnected)
        previousFocus.focus({ preventScroll: true });
    };
  }, []);

  useLayoutEffect(() => {
    headingRef.current?.focus({ preventScroll: true });
    let frame;
    const getTarget = () =>
      step &&
      Array.from(document.querySelectorAll("[data-tour-target]")).find(
        (node) =>
          node.dataset.tourTarget === (step.targetTo || step.to) &&
          node.getBoundingClientRect().width > 0,
      );
    const target = getTarget();
    const nav = target?.closest("nav");
    const originalScroll = nav?.scrollTop;
    if (target && nav) {
      nav.scrollTop +=
        target.getBoundingClientRect().top -
        nav.getBoundingClientRect().top -
        12;
    }

    const measure = () => {
      const rect = getTarget()?.getBoundingClientRect();
      const viewport = window.visualViewport;
      const width = viewport?.width || window.innerWidth;
      const height = viewport?.height || window.innerHeight;
      const top = viewport?.offsetTop || 0;
      const mobile = width < 768;
      const navRect = nav?.parentElement?.getBoundingClientRect();
      const usableLeft = mobile
        ? 0
        : Math.max(16, Math.min(navRect?.right || 0, width * 0.34) + 20);
      const availableWidth = Math.max(320, width - usableLeft - 32);
      const cardWidth = Math.min(440, availableWidth);
      const cardHeight = cardRef.current?.offsetHeight || 520;
      const mobileCardWidth = Math.min(300, Math.max(0, width - 24));
      const mobileGutter = Math.max(10, viewport?.offsetTop ? 10 : 18);
      const hasTarget = Boolean(
        rect && rect.bottom > top && rect.top < top + height,
      );
      const cardLeft = mobile
        ? 0
        : clamp(
            usableLeft + (width - usableLeft - cardWidth) / 2,
            usableLeft + 16,
            width - cardWidth - 16,
          );
      const targetBox = hasTarget
        ? {
            left: rect.left - 5,
            top: rect.top - 5,
            width: rect.width + 10,
            height: rect.height + 10,
          }
        : null;
      const targetCenter = targetBox
        ? targetBox.top + targetBox.height / 2
        : top + height / 2;
      const cardTop = mobile
        ? 0
        : clamp(
            targetCenter - cardHeight / 2,
            top + 20,
            top + height - cardHeight - 20,
          );
      const desktopCardLeft = targetBox
        ? clamp(
            targetBox.left + targetBox.width + 44,
            usableLeft + 16,
            width - cardWidth - 16,
          )
        : cardLeft;
      const mobileCandidates = targetBox
        ? [
            {
              placement: "right",
              left: targetBox.left + targetBox.width + mobileGutter,
              top: targetCenter - cardHeight / 2,
            },
            {
              placement: "left",
              left: targetBox.left - mobileCardWidth - mobileGutter,
              top: targetCenter - cardHeight / 2,
            },
            {
              placement: "bottom",
              left: targetCenter - mobileCardWidth / 2,
              top: targetBox.top + targetBox.height + mobileGutter,
            },
            {
              placement: "top",
              left: targetCenter - mobileCardWidth / 2,
              top: targetBox.top - cardHeight - mobileGutter,
            },
          ]
        : [
            {
              placement: "bottom",
              left: (width - mobileCardWidth) / 2,
              top: height - cardHeight - mobileGutter,
            },
          ];
      const mobileCandidate =
        mobileCandidates.find((candidate) => {
          const left = candidate.left;
          const right = left + mobileCardWidth;
          const bottom = candidate.top + cardHeight;
          const insideViewport =
            left >= mobileGutter &&
            right <= width - mobileGutter &&
            candidate.top >= top + mobileGutter &&
            bottom <= top + height - mobileGutter;
          const overlapsTarget =
            targetBox &&
            left < targetBox.left + targetBox.width &&
            right > targetBox.left &&
            candidate.top < targetBox.top + targetBox.height &&
            bottom > targetBox.top;
          return insideViewport && !overlapsTarget;
        }) || mobileCandidates[0];
      const mobileCardLeft = clamp(
        mobileCandidate.left,
        mobileGutter,
        width - mobileCardWidth - mobileGutter,
      );
      const mobileCardTop = clamp(
        mobileCandidate.top,
        top + mobileGutter,
        top + height - cardHeight - mobileGutter,
      );
      const mobilePlacement = mobileCandidate.placement;
      const cardBox = mobile
        ? null
        : {
            left: desktopCardLeft,
            top: cardTop,
            width: cardWidth,
            height: cardHeight,
          };
      const next = {
        mobile,
        viewport: { width, height },
        target: targetBox,
        card: mobile
          ? {
              width: mobileCardWidth,
              left: mobileCardLeft,
              top: mobileCardTop,
              "--workspace-tour-pointer-top": `${clamp(
                targetCenter - mobileCardTop,
                28,
                Math.max(28, cardHeight - 28),
              )}px`,
              "--workspace-tour-pointer-left": `${clamp(
                targetCenter - mobileCardLeft,
                28,
                Math.max(28, mobileCardWidth - 28),
              )}px`,
            }
          : { width: cardWidth, left: desktopCardLeft, top: cardTop },
        placement: mobilePlacement,
        connector:
          !mobile && targetBox && !welcome
            ? connectorGeometry(cardBox, targetBox)
            : null,
      };
      setGeometry((current) =>
        JSON.stringify(current) === JSON.stringify(next) ? current : next,
      );
    };

    const schedule = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(measure);
    };
    measure();
    const observer = new ResizeObserver(schedule);
    if (cardRef.current) observer.observe(cardRef.current);
    if (target) observer.observe(target);
    window.addEventListener("resize", schedule);
    window.addEventListener("scroll", schedule, true);
    window.visualViewport?.addEventListener("resize", schedule);
    window.visualViewport?.addEventListener("scroll", schedule);
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      window.removeEventListener("resize", schedule);
      window.removeEventListener("scroll", schedule, true);
      window.visualViewport?.removeEventListener("resize", schedule);
      window.visualViewport?.removeEventListener("scroll", schedule);
      if (nav) nav.scrollTop = originalScroll;
    };
  }, [step, welcome]);

  const finish = async (outcome = "paused", setup = false) => {
    if (actionLock.current) return;
    actionLock.current = true;
    setBusy(true);
    setError("");
    try {
      await onClose({ outcome, index });
      if (setup) onSetup?.();
    } catch (err) {
      setError(
        getErrorMessage(
          err,
          "Could not save your tour preference. Please try again.",
        ),
      );
    } finally {
      actionLock.current = false;
      setBusy(false);
    }
  };

  const onKeyDown = (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      if (confirmDismiss) setConfirmDismiss(false);
      else finish("paused");
    }
    if (event.key !== "Tab") return;
    const controls = Array.from(
      cardRef.current?.querySelectorAll(focusable) || [],
    );
    const first = controls[0];
    const final = controls.at(-1);
    if (
      event.shiftKey &&
      (document.activeElement === first ||
        document.activeElement === headingRef.current)
    ) {
      event.preventDefault();
      final?.focus();
    } else if (!event.shiftKey && document.activeElement === final) {
      event.preventDefault();
      first?.focus();
    }
  };

  return createPortal(
    <div ref={overlayRef} className="workspace-tour" onKeyDown={onKeyDown}>
      {geometry?.target && !welcome ? (
        <div
          aria-hidden="true"
          className="workspace-tour-spotlight"
          style={geometry.target}
        />
      ) : (
        <div className="workspace-tour-dimmer" />
      )}
      {geometry?.connector ? (
        <svg
          aria-hidden="true"
          className="workspace-tour-connector"
          width={geometry.viewport.width}
          height={geometry.viewport.height}
          viewBox={`0 0 ${geometry.viewport.width} ${geometry.viewport.height}`}
        >
          <defs>
            <marker
              id="workspace-tour-arrowhead"
              markerWidth="12"
              markerHeight="12"
              refX="9"
              refY="6"
              orient="auto"
              markerUnits="strokeWidth"
            >
              <path
                d="M 0 0 L 10 6 L 0 12 z"
                className="workspace-tour-arrowhead"
              />
            </marker>
          </defs>
          <path
            className="workspace-tour-connector-shadow"
            d={geometry.connector.path}
          />
          <path
            className="workspace-tour-connector-line"
            d={geometry.connector.path}
            markerEnd="url(#workspace-tour-arrowhead)"
          />
        </svg>
      ) : null}
      <section
        ref={cardRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="workspace-tour-title"
        aria-describedby="workspace-tour-description"
        className={`workspace-tour-card workspace-tour-card-${geometry?.placement || "right"}${dedicated ? " workspace-tour-card-upgrade" : ""}`}
        style={geometry?.card}
      >
        <div className="workspace-tour-body">
          <div className="flex items-center justify-between gap-4">
            <span className="text-xs font-semibold uppercase tracking-widest text-text-muted">
              {dedicated
                ? dedicatedKind === "class-duties"
                  ? `New responsibility · ${index + 1} of ${steps.length}`
                  : `What's new · ${index + 1} of ${steps.length}`
                : welcome
                  ? "Welcome to Weave"
                  : `Your workspace · ${index + 1} of ${steps.length}`}
            </span>
            <button
              type="button"
              disabled={busy}
              onClick={() => finish("paused")}
              aria-label="Close tour and finish later"
              className="workspace-tour-close"
            >
              <X className="h-5 w-5" />
            </button>
          </div>
          {!welcome ? (
            <div
              className="mt-4 h-1 overflow-hidden rounded-full bg-surface-muted"
              role="progressbar"
              aria-label="Tour progress"
              aria-valuemin={0}
              aria-valuemax={steps.length}
              aria-valuenow={index + 1}
            >
              <div
                className="h-full bg-primary motion-safe:transition-[width]"
                style={{ width: `${((index + 1) / steps.length) * 100}%` }}
              />
            </div>
          ) : null}
          <div className="mt-6 flex items-center gap-3 text-primary">
            <span className="grid h-11 w-11 place-items-center rounded-xl bg-primary-soft">
              <Icon className="h-5 w-5" />
            </span>
            <span className="text-sm font-semibold">
              {step?.label || "A little guidance, a confident start"}
            </span>
          </div>
          <h2
            ref={headingRef}
            tabIndex={-1}
            id="workspace-tour-title"
            className="mt-4 text-2xl font-semibold leading-tight tracking-tight text-text outline-none"
          >
            {step?.title ||
              (dedicatedKind === "class-duties"
                ? "Your class-teacher tools are ready"
                : dedicated
                  ? "New features are ready"
                  : "Find your way around.")}
          </h2>
          <p
            id="workspace-tour-description"
            className="mt-3 text-sm leading-7 text-text-muted"
          >
            {step?.description ||
              (dedicated
                ? dedicatedKind === "class-duties"
                  ? "You have been assigned as a class teacher. This quick guide introduces the duties now available in your workspace."
                  : "These plan features are now available for your school. This quick update points out where admins can find them."
                : onSetup
                  ? "Take a quick look around your workspace. Then we’ll help you prepare your session, first term, and calendar."
                  : "Get to know the places you’ll use in your school workspace. There’s nothing to fill in—just take a look around.")}
          </p>
          {step ? (
            <div className="workspace-tour-preview">
              <p className="text-xs font-semibold uppercase tracking-wide text-text-muted">
                {dedicated
                  ? dedicatedKind === "class-duties"
                    ? `Available for ${step.label}`
                    : `What's new in ${step.label}`
                  : `A quick look inside ${step.label}`}
              </p>
              <WorkspaceTourSnapshot
                step={step}
                visibleRoutes={visibleRoutes}
              />
              <ul className="mt-4 grid gap-2 sm:grid-cols-3">
                {step.preview.map((label) => (
                  <li
                    key={label}
                    className="flex items-center gap-2 text-xs font-medium text-text"
                  >
                    <Check className="h-3.5 w-3.5 shrink-0 text-primary" />
                    {label}
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <p className="mt-6 text-sm font-medium text-text">
              Skip for now and Weave will keep a Resume tour reminder on your
              dashboard. You can also replay the tour later from Settings.
            </p>
          )}
          {error ? (
            <p role="alert" className="mt-4 text-sm text-error">
              {error}
            </p>
          ) : null}
        </div>
        <footer className="workspace-tour-footer">
          {confirmDismiss ? (
            <div className="rounded-xl border border-border bg-surface-muted/45 p-4">
              <p className="text-sm font-semibold text-text">
                Stop showing the workspace tour?
              </p>
              <p className="mt-1 text-xs leading-5 text-text-muted">
                Weave will remove the incomplete reminder and will not open this
                tour automatically again. You can still replay it manually from
                Settings.
              </p>
              <div className="mt-4 flex justify-end gap-2">
                <Button
                  variant="ghost"
                  size="small"
                  disabled={busy}
                  onClick={() => setConfirmDismiss(false)}
                >
                  Cancel
                </Button>
                <Button
                  variant="outline"
                  size="small"
                  disabled={busy}
                  onClick={() => finish("dismissed")}
                >
                  {busy ? "Saving..." : "Don't show again"}
                </Button>
              </div>
            </div>
          ) : (
            <>
              <div className="flex items-center justify-between gap-2">
                <Button
                  variant="ghost"
                  disabled={busy}
                  onClick={() =>
                    welcome
                      ? finish("paused", Boolean(onSetup))
                      : setIndex(index - 1)
                  }
                >
                  {welcome ? (
                    onSetup ? (
                      "Skip to setup"
                    ) : (
                      "Skip for now"
                    )
                  ) : (
                    <>
                      <ArrowLeft className="h-4 w-4" />
                      Back
                    </>
                  )}
                </Button>
                <Button
                  disabled={busy || (welcome && !steps.length)}
                  onClick={() =>
                    last && !welcome
                      ? finish("completed", Boolean(onSetup))
                      : setIndex(index + 1)
                  }
                >
                  {busy
                    ? "Saving…"
                    : welcome
                      ? "Show me around"
                      : last
                        ? onSetup
                          ? "Set up school year"
                          : dedicated
                            ? "Done"
                            : "Go to dashboard"
                        : "Next"}
                  <ArrowRight className="h-4 w-4" />
                </Button>
              </div>
              {!welcome ? (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => finish("paused", Boolean(onSetup))}
                  className="workspace-tour-secondary-action"
                >
                  {dedicated
                    ? dedicatedKind === "class-duties"
                      ? "Close guide"
                      : "Close update"
                    : onSetup
                      ? "Skip to school setup"
                      : "Skip for now"}
                </button>
              ) : null}
              {!dedicated ? (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => setConfirmDismiss(true)}
                  className="workspace-tour-dismiss-action"
                >
                  Don't show this tour again
                </button>
              ) : null}
            </>
          )}
        </footer>
      </section>
    </div>,
    document.body,
  );
}
