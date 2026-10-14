import {
  BookOpen,
  CalendarDays,
  ClipboardList,
  FileText,
  Home,
  Inbox,
  Menu,
  Settings,
} from "lucide-react";
import {
  memo,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { Link, useLocation } from "react-router-dom";
import { useRuntimeConfig } from "../../hooks/useRuntimeConfig";
import { useTeacherClassDutyAccess } from "../../features/teachers/TeacherClassDutyAccessContext";
import { authSession, NAVIGATION_ABORT_EVENT } from "../../services/api";
import { cn } from "../../utils/cn";
import { scrollDashboardViewportToTop } from "../../utils/dashboardScroll";

const NAV_INDICATOR_COMMIT_DELAY_MS = 350;
const NAV_LOADING_SHOW_DELAY_MS = 80;
const NAV_LOADING_MIN_VISIBLE_MS = 300;
const NAV_LOADING_MAX_MS = 1200;
const BOTTOM_NAV_CONTENT_GAP_PX = 12;

const isStandalonePwaDisplay = () => {
  if (typeof window === "undefined") return false;

  return Boolean(
    window.matchMedia?.("(display-mode: standalone)")?.matches ||
      window.navigator?.standalone === true,
  );
};

const bottomNavConfig = {
  admin: [
    { label: "Academic", to: "/admin/academic", icon: ClipboardList },
    { label: "Inbox", to: "/admin/inbox", icon: Inbox },
    { label: "Home", to: "/admin/dashboard", icon: Home, isHome: true },
    { label: "Calendar", to: "/admin/calendar", icon: CalendarDays },
  ],
  teacher: [
    { label: "Rosters", to: "/teacher/students", icon: BookOpen },
    { label: "Inbox", to: "/teacher/inbox", icon: Inbox },
    { label: "Home", to: "/teacher/dashboard", icon: Home, isHome: true },
    { label: "Calendar", to: "/teacher/calendar", icon: CalendarDays },
  ],
  student: [
    { label: "Subjects", to: "/student/subjects", icon: BookOpen },
    { label: "Inbox", to: "/student/inbox", icon: Inbox },
    { label: "Home", to: "/student/dashboard", icon: Home, isHome: true },
    { label: "Reports", to: "/student/report-cards", icon: FileText },
  ],
  parent: [
    { label: "Results", to: "/parent/results", icon: BookOpen },
    { label: "Inbox", to: "/parent/inbox", icon: Inbox },
    { label: "Home", to: "/parent/dashboard", icon: Home, isHome: true },
    { label: "Calendar", to: "/parent/calendar", icon: CalendarDays },
  ],
  superadmin: [
    { label: "Verify", to: "/superadmin/verification", icon: BookOpen },
    { label: "Inbox", to: "/superadmin/inbox", icon: Inbox },
    { label: "Home", to: "/superadmin/dashboard", icon: Home, isHome: true },
    { label: "Settings", to: "/superadmin/settings", icon: Settings },
  ],
};

const isRouteActive = (pathname, itemPath) =>
  pathname === itemPath ||
  (itemPath !== "/" && pathname.startsWith(`${itemPath}/`));

const getIndicatorStyleForElement = (element) => ({
  width: element.offsetWidth,
  transform: `translateX(${element.offsetLeft}px)`,
  opacity: 1,
});

function BottomNav({ role, onOpenMenu }) {
  const location = useLocation();
  const runtimeConfig = useRuntimeConfig();
  const { hasClassTeacherDuties } = useTeacherClassDutyAccess();
  const user = authSession.getUser() || {};
  const actorType = String(user?.actor_type || "").toLowerCase();
  const isAccountScope =
    ["parent_account", "teacher_account"].includes(actorType) &&
    !user?.tenant_id;
  const [indicatorStyle, setIndicatorStyle] = useState({
    width: 0,
    transform: "translateX(0px)",
    opacity: 0,
  });
  const [loadingVisible, setLoadingVisible] = useState(false);
  const [isPwaDisplay, setIsPwaDisplay] = useState(() =>
    isStandalonePwaDisplay(),
  );
  const shellRef = useRef(null);
  const navRef = useRef(null);
  const itemRefs = useRef({});
  const indicatorTimerRef = useRef(null);
  const loadingShowTimerRef = useRef(null);
  const loadingHideTimerRef = useRef(null);
  const loadingMaxTimerRef = useRef(null);
  const loadingStartedAtRef = useRef(0);
  const isTransitioningRef = useRef(false);
  const hasMountedRef = useRef(false);
  const lastViewportWidth = useRef(
    typeof window === "undefined" ? 0 : window.innerWidth,
  );
  const configuredItems = bottomNavConfig[role] || bottomNavConfig.admin;
  const items = (
    isAccountScope
      ? configuredItems.filter((item) => item.accountScope)
      : configuredItems
  ).filter(
    (item) =>
      (!item.requiresClassTeacher || hasClassTeacherDuties) &&
      (!item.runtimeFeature ||
        runtimeConfig?.features?.[item.runtimeFeature] !== false),
  );

  const clearTimer = useCallback((timerRef) => {
    if (!timerRef.current) return;
    window.clearTimeout(timerRef.current);
    timerRef.current = null;
  }, []);

  const clearLoadingTimers = useCallback(() => {
    clearTimer(loadingShowTimerRef);
    clearTimer(loadingHideTimerRef);
    clearTimer(loadingMaxTimerRef);
  }, [clearTimer]);

  useEffect(() => {
    const syncStandalonePwaMode = () => {
      setIsPwaDisplay(isStandalonePwaDisplay());
    };

    const standaloneQuery = window.matchMedia?.("(display-mode: standalone)");

    syncStandalonePwaMode();
    standaloneQuery?.addEventListener?.("change", syncStandalonePwaMode);
    window.addEventListener("pageshow", syncStandalonePwaMode);
    window.addEventListener("resize", syncStandalonePwaMode);
    document.addEventListener("visibilitychange", syncStandalonePwaMode);

    return () => {
      standaloneQuery?.removeEventListener?.("change", syncStandalonePwaMode);
      window.removeEventListener("pageshow", syncStandalonePwaMode);
      window.removeEventListener("resize", syncStandalonePwaMode);
      document.removeEventListener("visibilitychange", syncStandalonePwaMode);
    };
  }, []);

  useLayoutEffect(() => {
    if (!isPwaDisplay) return undefined;

    const navElement = shellRef.current;
    if (!navElement) return undefined;

    const root = document.documentElement;
    let frameId = 0;

    const syncBottomNavClearance = () => {
      window.cancelAnimationFrame(frameId);
      frameId = window.requestAnimationFrame(() => {
        // A login or keyboard dismissal can change iOS window.innerHeight
        // before the fixed dashboard shell settles. Measuring from viewport
        // height minus rect.top mixes coordinate systems and creates unstable
        // page clearance between authentication sessions. The actual dock
        // height is stable and is all we need to reserve scrollable space.
        const rect = navElement.getBoundingClientRect();
        const obstructionHeight = Math.max(0, rect.height);
        if (obstructionHeight <= 0) return;

        root.style.setProperty(
          "--mobile-bottom-nav-clearance",
          `${Math.ceil(obstructionHeight + BOTTOM_NAV_CONTENT_GAP_PX)}px`,
        );
      });
    };

    syncBottomNavClearance();

    const resizeObserver = window.ResizeObserver
      ? new window.ResizeObserver(syncBottomNavClearance)
      : null;
    resizeObserver?.observe(navElement);
    window.addEventListener("resize", syncBottomNavClearance);
    window.addEventListener("orientationchange", syncBottomNavClearance);
    window.addEventListener("pageshow", syncBottomNavClearance);

    return () => {
      resizeObserver?.disconnect();
      window.removeEventListener("resize", syncBottomNavClearance);
      window.removeEventListener("orientationchange", syncBottomNavClearance);
      window.removeEventListener("pageshow", syncBottomNavClearance);
      window.cancelAnimationFrame(frameId);
      root.style.removeProperty("--mobile-bottom-nav-clearance");
    };
  }, [isPwaDisplay]);

  const abortStalePageRequests = useCallback(() => {
    window.dispatchEvent(new CustomEvent(NAVIGATION_ABORT_EVENT));
  }, []);

  const updateIndicator = useCallback(() => {
    const navElement = navRef.current;
    const activeItem = items.find((item) =>
      isRouteActive(location.pathname, item.to),
    );

    const activeElement = activeItem ? itemRefs.current[activeItem.to] : null;

    if (!navElement || !activeElement) {
      setIndicatorStyle((current) => ({ ...current, opacity: 0 }));
      return;
    }

    setIndicatorStyle(getIndicatorStyleForElement(activeElement));
  }, [items, location.pathname]);

  const scheduleIndicatorUpdate = useCallback(() => {
    if (typeof window === "undefined") return;

    window.requestAnimationFrame(() => {
      updateIndicator();
    });
  }, [updateIndicator]);

  const finishNavigationFeedback = useCallback(() => {
    if (!isTransitioningRef.current) return;

    clearTimer(loadingShowTimerRef);
    clearTimer(loadingHideTimerRef);
    clearTimer(loadingMaxTimerRef);

    const elapsed = Date.now() - loadingStartedAtRef.current;
    const hideDelay = Math.max(NAV_LOADING_MIN_VISIBLE_MS - elapsed, 0);

    loadingHideTimerRef.current = window.setTimeout(() => {
      isTransitioningRef.current = false;
      setLoadingVisible(false);
      loadingHideTimerRef.current = null;
    }, hideDelay);
  }, [clearTimer]);

  const startNavigationFeedback = useCallback(() => {
    clearLoadingTimers();
    isTransitioningRef.current = true;
    loadingStartedAtRef.current = Date.now();

    loadingShowTimerRef.current = window.setTimeout(() => {
      if (!isTransitioningRef.current) return;
      setLoadingVisible(true);
      loadingShowTimerRef.current = null;
    }, NAV_LOADING_SHOW_DELAY_MS);

    loadingMaxTimerRef.current = window.setTimeout(() => {
      isTransitioningRef.current = false;
      setLoadingVisible(false);
      loadingMaxTimerRef.current = null;
    }, NAV_LOADING_MAX_MS);
  }, [clearLoadingTimers]);

  useLayoutEffect(() => {
    clearTimer(indicatorTimerRef);

    if (!hasMountedRef.current) {
      hasMountedRef.current = true;
      scheduleIndicatorUpdate();
      return undefined;
    }

    indicatorTimerRef.current = window.setTimeout(() => {
      scheduleIndicatorUpdate();
      finishNavigationFeedback();
      indicatorTimerRef.current = null;
    }, NAV_INDICATOR_COMMIT_DELAY_MS);

    return () => {
      clearTimer(indicatorTimerRef);
    };
  }, [
    clearTimer,
    finishNavigationFeedback,
    location.pathname,
    scheduleIndicatorUpdate,
  ]);

  useLayoutEffect(() => {
    const handleResize = () => {
      if (window.innerWidth === lastViewportWidth.current) return;
      lastViewportWidth.current = window.innerWidth;
      scheduleIndicatorUpdate();
    };
    const handleOrientationChange = () => {
      lastViewportWidth.current = window.innerWidth;
      scheduleIndicatorUpdate();
    };
    const handleVisibilityChange = () => {
      if (!document.hidden) scheduleIndicatorUpdate();
    };

    window.addEventListener("resize", handleResize);
    window.addEventListener("orientationchange", handleOrientationChange);
    window.addEventListener("pageshow", handleVisibilityChange);
    document.addEventListener("visibilitychange", handleVisibilityChange);

    return () => {
      window.removeEventListener("resize", handleResize);
      window.removeEventListener("orientationchange", handleOrientationChange);
      window.removeEventListener("pageshow", handleVisibilityChange);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [scheduleIndicatorUpdate]);

  useEffect(() => {
    return () => {
      clearTimer(indicatorTimerRef);
      clearLoadingTimers();
    };
  }, [clearLoadingTimers, clearTimer]);

  const handleClick = useCallback(
    (event, item) => {
      if (isRouteActive(location.pathname, item.to)) {
        event.preventDefault();
        clearLoadingTimers();
        isTransitioningRef.current = false;
        setLoadingVisible(false);
        scrollDashboardViewportToTop("natural");
        return;
      }

      abortStalePageRequests();
      startNavigationFeedback();
    },
    [
      abortStalePageRequests,
      clearLoadingTimers,
      location.pathname,
      startNavigationFeedback,
    ],
  );

  if (!isPwaDisplay) return null;

  return (
    <>
      {loadingVisible ? (
        <div
          className="pointer-events-none fixed inset-0 z-30 flex items-center justify-center bg-background/55 px-4 md:hidden"
          aria-hidden="true"
        >
          <div className="flex items-center gap-2 rounded-full bg-surface/95 px-4 py-2 text-xs font-semibold text-text-muted shadow-premium">
            <span className="h-4 w-4 animate-spin rounded-full border-2 border-primary/20 border-t-primary" />
            <span>Loading...</span>
          </div>
        </div>
      ) : null}

      <nav
        ref={shellRef}
        data-mobile-bottom-nav="true"
        className="fixed inset-x-0 bottom-0 z-40 bg-transparent px-2 md:hidden"
        aria-label="Primary mobile app navigation"
      >
        <div
          ref={navRef}
          className="relative mx-auto flex w-full max-w-[30rem] flex-row items-center gap-1.5 rounded-[2.1rem] bg-surface p-1.5 shadow-sm"
        >
          <span
            aria-hidden="true"
            className="bottom-nav-indicator pointer-events-none absolute bottom-2 left-0 top-2 z-0 rounded-[1.65rem] bg-primary shadow-sm shadow-primary/20"
            style={indicatorStyle}
          />

          {items.map((item) => {
            const Icon = item.icon;
            const isActive = isRouteActive(location.pathname, item.to);
            return (
              <Link
                key={item.label}
                to={item.to}
                ref={(node) => {
                  itemRefs.current[item.to] = node;
                }}
                onClick={(event) => handleClick(event, item)}
                aria-current={isActive ? "page" : undefined}
                aria-label={item.label}
                className={cn(
                  "relative z-10 flex min-h-[3.45rem] flex-1 touch-manipulation select-none flex-col items-center justify-center gap-1 rounded-[1.75rem] px-1.5 py-1.5 text-center transition-colors duration-150 ease-out",
                  isActive
                    ? "text-primary-foreground"
                    : "text-text-muted hover:text-text",
                )}
              >
                <span className="flex h-6 w-6 items-center justify-center">
                  <Icon
                    className={cn(
                      "h-[1.35rem] w-[1.35rem] shrink-0 transition-transform duration-150",
                      isActive && "scale-110",
                    )}
                  />
                </span>
                <span
                  className={cn(
                    "max-w-full truncate text-[10.5px] font-semibold leading-none transition-colors duration-150",
                    isActive ? "text-primary-foreground" : "text-text-muted",
                  )}
                >
                  {item.label}
                </span>
              </Link>
            );
          })}

          <button
            type="button"
            onClick={onOpenMenu}
            className="relative z-10 flex min-h-[3.45rem] flex-1 touch-manipulation select-none flex-col items-center justify-center gap-1 rounded-[1.75rem] px-1.5 py-1.5 text-text-muted transition-colors duration-150 ease-out hover:text-text"
            aria-label="Open full navigation menu"
          >
            <Menu className="h-[1.35rem] w-[1.35rem] shrink-0" />
            <span className="max-w-full truncate text-[10.5px] font-semibold leading-none">
              Menu
            </span>
          </button>
        </div>
      </nav>
    </>
  );
}

export default memo(BottomNav);
