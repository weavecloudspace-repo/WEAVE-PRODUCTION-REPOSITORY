import { useEffect } from "react";
import { X } from "lucide-react";

import { scheduleThemeChromeSync } from "../../utils/themeChromeSync";

import SidebarContent from "./Sidebar";

export default function MobileDrawer({ open, role, schoolName, schoolLogoUrl, onClose, tourMode = false }) {
  // Safari's native bottom toolbar samples the document canvas. Keep its
  // colors in sync with this drawer while preserving the PWA's separate shell.
  useEffect(() => {
    scheduleThemeChromeSync();
  }, [open]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[90] md:hidden">
      <div className="absolute inset-0 bg-black/35" onClick={onClose} />
      <aside
        data-mobile-drawer="true"
        data-tour-navigation={tourMode ? "true" : undefined}
        className="absolute inset-y-0 left-0 flex h-full min-h-0 w-[min(88vw,20rem)] flex-col overflow-hidden border-r border-sidebar-border bg-sidebar-background text-sidebar-text pt-[max(0.75rem,env(safe-area-inset-top))] shadow-2xl"
      >
        {/* The opaque drawer itself already paints the safe area. Do not add
            an absolutely positioned overlay: it can cover the close button. */}
        <div className="relative z-10 flex h-12 shrink-0 items-center justify-end px-4">
          <button
            type="button"
            className="relative z-10 inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-surface-muted/60 text-text-muted transition hover:bg-surface-muted hover:text-text"
            onClick={onClose}
            aria-label="Close navigation"
          >
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="min-h-0 flex-1">
          <SidebarContent
            role={role}
            mobile
            collapsed={false}
            onNavigate={onClose}
            schoolName={schoolName}
            schoolLogoUrl={schoolLogoUrl}
          />
        </div>
      </aside>
    </div>
  );
}
