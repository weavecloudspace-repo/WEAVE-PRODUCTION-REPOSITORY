import { HelpCircle, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";

import { isFeatureAvailable } from "../../features/navigation/featureAvailability";
import useCbtHistoricalAccess from "../../features/cbt/useCbtHistoricalAccess";
import { FEATURE_CODES } from "../../features/subscriptions/subscriptionConfig";
import { useSubscription } from "../../features/subscriptions/useSubscription";
import { useRuntimeConfig } from "../../hooks/useRuntimeConfig";
import { useTeacherClassDutyAccess } from "../../features/teachers/TeacherClassDutyAccessContext";
import { authSession } from "../../services/api";
import { cn } from "../../utils/cn";
import WeaveIcon from "../brand/WeaveIcon";
import { navGroups, roleLabels } from "./navConfig";

function isRouteActive(pathname, itemPath) {
  return pathname === itemPath || (itemPath !== "/" && pathname.startsWith(`${itemPath}/`));
}

function resolveWorkspaceLogo(user) {
  return (
    user?.tenant_logo_url ||
    user?.tenant?.logo_url ||
    user?.logo_url ||
    null
  );
}

export default function SidebarContent({
  role,
  collapsed,
  onNavigate,
  mobile = false,
  schoolName,
  schoolLogoUrl,
  onToggleSidebar,
}) {
  const location = useLocation();
  const subscription = useSubscription();
  const cbtAccess = useCbtHistoricalAccess({ enabled: role === "admin" });
  const runtimeConfig = useRuntimeConfig();
  const { hasClassTeacherDuties } = useTeacherClassDutyAccess();
  const user = authSession.getUser() || {};
  const actorType = String(user?.actor_type || "").toLowerCase();
  const isAccountScope =
    ["parent_account", "teacher_account"].includes(actorType) &&
    !user?.tenant_id;
  const workspaceLogo = schoolLogoUrl || resolveWorkspaceLogo(user);
  const [failedWorkspaceLogo, setFailedWorkspaceLogo] = useState(null);
  const hasCustomWorkspaceLogo = Boolean(workspaceLogo) && failedWorkspaceLogo !== workspaceLogo;
  const workspaceLogoAlt = `${schoolName || "School"} logo`;
  const availabilityContext = {
    subscription,
    runtimeFeatures: runtimeConfig?.features || {},
    isAccountScope,
    hasClassTeacherDuties,
    historicalFeatures: {
      [FEATURE_CODES.CBT_PAIRING]:
        cbtAccess.source === "history" && cbtAccess.allowed,
    },
  };
  const groups = (navGroups[role] || navGroups.admin)
    .map((group) => ({
      ...group,
      items: group.items.filter((item) =>
        isFeatureAvailable(item, availabilityContext),
      ),
    }))
    .filter((group) => group.items.length > 0);
  const navRef = useRef(null);
  const scrollStorageKey = `weave-sidebar-scroll:${role}:${mobile ? "mobile" : "desktop"}`;

  useEffect(() => {
    if (typeof window === "undefined") return undefined;

    const navElement = navRef.current;
    if (!navElement) return undefined;

    const savedScroll = Number(window.sessionStorage.getItem(scrollStorageKey) || 0);
    const frameId = window.requestAnimationFrame(() => {
      navElement.scrollTop = savedScroll;
    });

    return () => window.cancelAnimationFrame(frameId);
  }, [scrollStorageKey, collapsed]);

  const persistSidebarScroll = () => {
    if (typeof window === "undefined") return;

    const navElement = navRef.current;
    if (!navElement) return;

    window.sessionStorage.setItem(scrollStorageKey, String(navElement.scrollTop));
  };

  const logoMark = hasCustomWorkspaceLogo ? (
    <img
      src={workspaceLogo}
      alt={workspaceLogoAlt}
      className={cn(
        "h-10 w-10 shrink-0 rounded-xl border border-border/70 bg-surface object-contain p-1 shadow-sm",
        collapsed && "h-11 w-11"
      )}
      onError={() => setFailedWorkspaceLogo(workspaceLogo)}
    />
  ) : (
    <WeaveIcon className={cn("h-11 w-11 shrink-0", collapsed && "h-12 w-12")} />
  );

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div
        data-sidebar-brand="true"
        className={cn(
          "relative flex h-[4.5rem] shrink-0 items-center border-b border-border/60 transition-all duration-300",
          mobile && "h-[5rem]",
          collapsed ? "justify-center px-2" : mobile ? "gap-2 px-4" : "gap-2 px-3"
        )}
      >
        {collapsed && onToggleSidebar ? (
          <button
            type="button"
            className="group relative flex h-11 w-11 items-center justify-center overflow-hidden rounded-xl border border-border/70 bg-surface text-text-muted shadow-sm transition hover:border-primary/35 hover:bg-surface-muted focus:outline-none focus:ring-4 focus:ring-primary/15"
            onClick={onToggleSidebar}
            aria-label="Expand sidebar"
            title="Expand sidebar"
          >
            <span className="pointer-events-none absolute inset-0 flex items-center justify-center transition duration-150 group-hover:scale-75 group-hover:opacity-0">
              {logoMark}
            </span>
            <PanelLeftOpen className="h-4 w-4 opacity-0 transition duration-150 group-hover:opacity-100" />
          </button>
        ) : (
          <Link
            to={isAccountScope ? `/${role}/schools` : "/"}
            className="flex min-w-0 flex-1 items-center gap-2.5"
            onClick={() => {
              persistSidebarScroll();
              onNavigate?.();
            }}
          >
            {logoMark}
            <span className="min-w-0">
              <span className={cn("block truncate text-[15px] font-bold leading-tight", isAccountScope ? "text-sidebar-text" : "tenant-school-name-sidebar")}>
                {isAccountScope ? "Your schools" : schoolName || "Weave"}
              </span>
              <span className="block truncate text-[11px] font-medium text-sidebar-text/65">School Management</span>
            </span>
          </Link>
        )}
        {!collapsed && !mobile && onToggleSidebar ? (
          <button
            type="button"
            className="ml-auto flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-border/70 bg-surface text-text-muted shadow-sm transition hover:border-primary/35 hover:bg-primary/10 hover:text-primary focus:outline-none focus:ring-4 focus:ring-primary/15"
            onClick={onToggleSidebar}
            aria-label="Collapse sidebar"
            title="Collapse sidebar"
          >
            <PanelLeftClose className="h-3.5 w-3.5" />
          </button>
        ) : null}
      </div>

      {!collapsed && (
        <div data-sidebar-workspace="true" className="mx-3 mt-3 rounded-xl border border-border/60 bg-surface-muted/40 px-3 py-2.5">
          <p className="truncate text-[11px] font-semibold uppercase tracking-[0.08em] text-sidebar-text/55">Workspace</p>
          <p className="mt-1 truncate text-[13px] font-semibold text-sidebar-text">
            {isAccountScope ? "Select a school" : schoolName || "School workspace"}
          </p>
          <span className="mt-2 inline-flex items-center rounded-md bg-primary/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-primary">
            {roleLabels[role] || "Workspace"}
          </span>
        </div>
      )}

      <nav
        ref={navRef}
        onScroll={persistSidebarScroll}
        className="min-h-0 flex-1 space-y-4 overflow-y-auto overscroll-contain px-2.5 py-3 pb-[max(1rem,env(safe-area-inset-bottom))]"
      >
        {groups.map((group) => (
          <div key={group.label}>
            {!collapsed && (
              <p className="mb-1.5 px-2.5 text-[10px] font-bold uppercase tracking-[0.1em] text-sidebar-text/55">{group.label}</p>
            )}
            <div className="space-y-1">
              {group.items.map((item) => {
                const Icon = item.icon;
                const isActive = isRouteActive(location.pathname, item.to);

                return (
                  <Link
                    key={`${group.label}-${item.label}`}
                    to={item.to}
                    data-tour-target={item.to}
                    onClick={() => {
                      persistSidebarScroll();
                      onNavigate?.();
                    }}
                    title={collapsed ? item.label : undefined}
                    className={cn(
                      "group relative flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-[13px] font-medium transition-all duration-150",
                      isActive
                        ? "bg-sidebar-active text-sidebar-active-text shadow-sm"
                        : "text-sidebar-text/80 hover:bg-sidebar-active/10 hover:text-sidebar-text",
                      collapsed && "justify-center px-2"
                    )}
                  >
                    <Icon className="h-4 w-4 shrink-0" />
                    {collapsed && (
                      <span className="pointer-events-none absolute left-full top-1/2 z-50 ml-3 -translate-y-1/2 whitespace-nowrap rounded-lg border border-border bg-surface px-2.5 py-1 text-xs font-semibold text-text opacity-0 shadow-premium transition-opacity duration-150 group-hover:opacity-100">
                        {item.label}
                      </span>
                    )}
                    {!collapsed && <span className="truncate">{item.label}</span>}
                    {!collapsed && isActive && <span className="ml-auto h-1.5 w-1.5 rounded-full bg-sidebar-active-text/70" />}
                  </Link>
                );
              })}
            </div>
          </div>
        ))}
        {!collapsed && mobile ? (
          <div data-mobile-sidebar-support="true" className="pt-2">
            <div className="flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-[12px] text-sidebar-text/65">
              <HelpCircle className="h-4 w-4" />
              Help & Support
            </div>
          </div>
        ) : null}
      </nav>

      {!collapsed && !mobile && (
        <div className="shrink-0 border-t border-border/60 p-2.5">
          <div className="flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-[12px] text-sidebar-text/65">
            <HelpCircle className="h-4 w-4" />
            Help & Support
          </div>
        </div>
      )}
    </div>
  );
}
