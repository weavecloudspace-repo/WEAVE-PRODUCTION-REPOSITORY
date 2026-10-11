const DEFAULT_NATURAL_SCROLL_DURATION_MS = 520;

export function shouldResetDashboardScroll(previousLocation, nextLocation) {
  // Documentation owns topic, command-group, and section navigation.
  if (nextLocation.pathname === "/admin/cbt/documentation") {
    if (previousLocation?.pathname === nextLocation.pathname || nextLocation.hash) return false;
  }
  return !previousLocation
    || previousLocation.pathname !== nextLocation.pathname
    || previousLocation.search !== nextLocation.search;
}

function easeOutCubic(progress) {
  return 1 - Math.pow(1 - progress, 3);
}

function getDashboardScrollTargets() {
  const scrollViewport = document.getElementById("dashboard-scroll-viewport");
  const dashboardContent = document.getElementById("dashboard-content");
  const scrollingElement =
    document.scrollingElement || document.documentElement || document.body;

  return [scrollViewport, dashboardContent, scrollingElement].filter(Boolean);
}

function getScrollTop(target) {
  if (target === document.scrollingElement || target === document.documentElement || target === document.body) {
    return target.scrollTop || window.scrollY || 0;
  }

  return target.scrollTop || 0;
}

function setScrollTop(target, top) {
  if (target && typeof target.scrollTo === "function") {
    target.scrollTo({ top, behavior: "auto" });
    return;
  }

  if (target) target.scrollTop = top;
}

function animateScrollTargetToTop(target, duration = DEFAULT_NATURAL_SCROLL_DURATION_MS) {
  if (!target || typeof window === "undefined") return;

  const startTop = getScrollTop(target);
  if (startTop <= 0) return;

  const startedAt = performance.now();

  const step = (timestamp) => {
    const elapsed = timestamp - startedAt;
    const progress = Math.min(elapsed / duration, 1);
    const nextTop = Math.round(startTop * (1 - easeOutCubic(progress)));

    setScrollTop(target, nextTop);

    if (progress < 1) {
      window.requestAnimationFrame(step);
    } else {
      setScrollTop(target, 0);
    }
  };

  window.requestAnimationFrame(step);
}

export function scrollDashboardViewportToTop(behavior = "smooth") {
  if (typeof window === "undefined") return;

  const targets = getDashboardScrollTargets();
  const primaryTarget = targets[0];
  const prefersReducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;

  if (behavior === "natural" && !prefersReducedMotion) {
    animateScrollTargetToTop(primaryTarget);
    return;
  }

  if (primaryTarget && typeof primaryTarget.scrollTo === "function") {
    primaryTarget.scrollTo({ top: 0, behavior: prefersReducedMotion ? "auto" : behavior });
    return;
  }

  for (const target of targets) {
    if (target && typeof target.scrollTo === "function") {
      target.scrollTo({ top: 0, behavior: prefersReducedMotion ? "auto" : behavior });
    } else if (target) {
      target.scrollTop = 0;
    }
  }

  if (typeof window.scrollTo === "function") {
    window.scrollTo({ top: 0, behavior: prefersReducedMotion ? "auto" : behavior });
  }
}
