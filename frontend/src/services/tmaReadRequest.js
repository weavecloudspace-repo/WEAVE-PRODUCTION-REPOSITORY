// Bound TMA reads, including response parsing and authentication retries.
// Reject explicitly as well as aborting: a refresh or custom transport may not
// settle immediately when its original request's signal is aborted.
export async function tmaReadRequest(read, { timeoutMs = 20000 } = {}) {
  const controller = new AbortController();
  const navigationTarget = typeof window === "undefined" ? null : window;
  const abortOnNavigation = () => controller.abort();
  navigationTarget?.addEventListener(
    "weave:navigation-start",
    abortOnNavigation,
    { once: true },
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
    navigationTarget?.removeEventListener(
      "weave:navigation-start",
      abortOnNavigation,
    );
  }
}
