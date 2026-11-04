// Bound TMA reads, including response parsing and authentication retries.
// Reject explicitly as well as aborting: a refresh or custom transport may not
// settle immediately when its original request's signal is aborted.
export async function tmaReadRequest(read, { timeoutMs = 20000, signal } = {}) {
  const controller = new AbortController();
  const abortOnCaller = () => controller.abort();
  if (signal?.aborted) controller.abort();
  signal?.addEventListener("abort", abortOnCaller, { once: true });
  const navigationTarget = typeof window === "undefined" ? null : window;
  const requestLocation = navigationTarget?.location.href;
  const abortOnNavigation = () => {
    if (navigationTarget?.location.href !== requestLocation) controller.abort();
  };
  navigationTarget?.addEventListener(
    "weave:navigation-start",
    abortOnNavigation,
  );
  let timer;
  try {
    return await Promise.race([
      Promise.resolve().then(() => read(controller.signal)),
      new Promise((_, reject) => {
        timer = setTimeout(() => {
          reject(
            new Error("Assignments took too long to load. Please try again."),
          );
          controller.abort();
        }, timeoutMs);
      }),
    ]);
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", abortOnCaller);
    navigationTarget?.removeEventListener(
      "weave:navigation-start",
      abortOnNavigation,
    );
  }
}
