export function appendToast(current, nextToast) {
  const next = [...current, nextToast];
  // Limit transient notifications without evicting errors awaiting dismissal.
  const transientToasts = next.filter((toast) => toast.type !== "error").slice(-4);
  const retained = new Set(transientToasts);
  return next.filter((toast) => toast.type === "error" || retained.has(toast));
}
