import { useCallback, useEffect, useState } from "react";
import { AlertCircle, AlertTriangle, CheckCircle2, Info, X } from "lucide-react";
import { cn } from "../../utils/cn";
import { toastBus } from "../../hooks/useToast";
import { appendToast } from "../../utils/toastPolicy";

const toneClasses = {
  info: "border-primary/25 bg-surface text-text",
  success: "border-success/25 bg-surface text-text",
  warning: "border-warning/30 bg-surface text-text",
  error: "border-error/25 bg-surface text-text",
};

const iconClasses = {
  info: "text-primary",
  success: "text-success",
  warning: "text-amber-500",
  error: "text-error",
};

const icons = {
  info: Info,
  success: CheckCircle2,
  warning: AlertTriangle,
  error: AlertCircle,
};

function ToastCard({ toast, onClose }) {
  const Icon = icons[toast.type] || icons.info;

  useEffect(() => {
    if (toast.duration == null || toast.duration <= 0) return;
    const timeoutId = window.setTimeout(() => onClose(toast.id), toast.duration);
    return () => window.clearTimeout(timeoutId);
  }, [onClose, toast.duration, toast.id]);

  return (
    <div
      className={cn(
        "pointer-events-auto flex w-full items-start gap-3 rounded-2xl border px-4 py-3 shadow-premium animate-fadein sm:max-w-sm",
        toneClasses[toast.type] || toneClasses.info
      )}
      role={toast.type === "error" ? "alert" : "status"}
      aria-live={toast.type === "error" ? "assertive" : "polite"}
    >
      <Icon className={cn("mt-0.5 h-5 w-5 shrink-0", iconClasses[toast.type] || iconClasses.info)} />
      <p className="min-w-0 flex-1 text-sm font-medium leading-6 text-text-soft">{toast.message}</p>
      <button
        type="button"
        onClick={() => onClose(toast.id)}
        className="rounded-lg p-1 text-text-faint transition hover:bg-surface-muted hover:text-text"
        aria-label="Dismiss notification"
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  );
}

export default function ToastHost() {
  const [toasts, setToasts] = useState([]);

  useEffect(() => {
    return toastBus.subscribe((nextToast) => {
      setToasts((current) => appendToast(current, nextToast));
    });
  }, []);

  const closeToast = useCallback((id) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  if (toasts.length === 0) return null;

  return (
    <div className="pointer-events-auto fixed inset-x-3 bottom-[calc(5.75rem+env(safe-area-inset-bottom))] z-[90] flex max-h-[calc(100dvh-7rem-env(safe-area-inset-bottom)-env(safe-area-inset-top))] flex-col-reverse gap-3 overflow-y-auto overscroll-contain sm:inset-x-auto sm:bottom-6 sm:right-6 sm:w-[24rem] sm:max-h-[calc(100dvh-3rem-env(safe-area-inset-top))] md:bottom-6">
      {toasts.map((toast) => (
        <ToastCard key={toast.id} toast={toast} onClose={closeToast} />
      ))}
    </div>
  );
}
