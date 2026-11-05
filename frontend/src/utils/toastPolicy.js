export function appendToast(current, nextToast) {
  // Replace an existing notification with the same ID (including persistent errors).
  const next = [...current.filter((toast) => toast.id !== nextToast.id), nextToast];
  // Limit transient notifications without evicting errors awaiting dismissal.
  const transientToasts = next.filter((toast) => toast.type !== "error").slice(-4);
  const retained = new Set(transientToasts);
  return next.filter((toast) => toast.type === "error" || retained.has(toast));
}
