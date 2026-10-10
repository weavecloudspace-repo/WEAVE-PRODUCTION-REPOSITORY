import { useCallback } from "react";

const listeners = new Set();

const emitToast = (toast) => {
  listeners.forEach((listener) => listener(toast));
};

export const toastBus = {
  subscribe(listener) {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },
  show(message, type = "info", options = {}) {
    const normalizedMessage = typeof message === "string" ? message.trim() : message;
    if (!normalizedMessage) return null;

    const id =
      options.id ||
      `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    emitToast({
      id,
      message: normalizedMessage,
      type,
      duration: type === "error" ? null : (options.duration ?? 3200),
    });
    return id;
  },
  info(message, options) {
    return toastBus.show(message, "info", options);
  },
  success(message, options) {
    return toastBus.show(message, "success", options);
  },
  warning(message, options) {
    return toastBus.show(message, "warning", options);
  },
  error(message, options) {
    return toastBus.show(message, "error", options);
  },
};

export function useToast() {
  const showToast = useCallback((message, type = "info", options = {}) => {
    return toastBus.show(message, type, options);
  }, []);

  const showSuccess = useCallback((message, options = {}) => {
    return toastBus.success(message, options);
  }, []);

  const showError = useCallback((message, options = {}) => {
    return toastBus.error(message, options);
  }, []);

  const showWarning = useCallback((message, options = {}) => {
    return toastBus.warning(message, options);
  }, []);

  const showInfo = useCallback((message, options = {}) => {
    return toastBus.info(message, options);
  }, []);

  return { showToast, showSuccess, showError, showWarning, showInfo };
}
