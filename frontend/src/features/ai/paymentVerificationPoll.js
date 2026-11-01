// One authenticated verification request at a time, with a bounded lifetime.
export function startPaymentVerificationPoll({
  verify,
  onSuccess,
  onStatus,
  onError,
  intervalMs = 5000,
  durationMs = 180000,
  target = typeof window === "undefined" ? null : window,
  schedule = setTimeout,
  cancel = clearTimeout,
}) {
  let disposed = false;
  let finished = false;
  let paused = false;
  let timedOut = false;
  let checking = false;
  let timer;
  let deadline;
  let controller;

  const clearTimers = () => {
    cancel(timer);
    cancel(deadline);
  };
  const expire = () => {
    if (disposed || finished) return;
    paused = true;
    timedOut = true;
    clearTimers();
    controller?.abort();
    onStatus("timed_out");
  };
  const check = async (manual = false) => {
    if (disposed || finished || checking || (paused && !manual)) return;
    if (paused) {
      paused = false;
      timedOut = false;
      deadline = schedule(expire, durationMs);
    }
    cancel(timer);
    checking = true;
    controller = new AbortController();
    const signal = controller.signal;
    onStatus("checking");
    try {
      const result = await verify(signal);
      if (disposed || signal.aborted) return;
      if (result.status === "success") {
        finished = true;
        clearTimers();
        onStatus("success");
        await onSuccess(result);
      } else if (["failed", "cancelled"].includes(result.status)) {
        finished = true;
        clearTimers();
        onStatus(result.status);
      } else {
        onStatus("waiting");
      }
    } catch (error) {
      if (disposed || signal.aborted) return;
      const status = error.response?.status || error.status;
      if ([401, 403, 404].includes(status)) {
        paused = true;
        clearTimers();
        onStatus("stopped");
        onError(error);
      } else if (manual) {
        onStatus("waiting");
        onError(error);
      } else {
        // Paystack may still be processing, or a webhook may be in flight.
        onStatus("waiting");
      }
    } finally {
      checking = false;
      if (!disposed && !finished && !paused)
        timer = schedule(() => void check(), intervalMs);
    }
  };
  const focus = () => {
    if (!paused || timedOut) void check(timedOut);
  };
  target?.addEventListener("focus", focus);
  deadline = schedule(expire, durationMs);
  timer = schedule(() => void check(), intervalMs);
  onStatus("waiting");
  return {
    checkNow: () => check(true),
    dispose() {
      disposed = true;
      clearTimers();
      controller?.abort();
      target?.removeEventListener("focus", focus);
    },
  };
}
