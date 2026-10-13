const KEYBOARD_THRESHOLD_PX = 120;
const INSTALLATION_KEY = "__weaveMobilePwaStabilityCleanup";
const EDITABLE_SELECTOR = [
  "input:not([type='button']):not([type='checkbox']):not([type='file']):not([type='hidden']):not([type='radio']):not([type='reset']):not([type='submit'])",
  "textarea",
  "select",
  "[contenteditable='true']",
].join(",");
const INTERNAL_SCROLL_SELECTOR = [
  "[data-modal-scroll-container='true']",
  "#dashboard-scroll-viewport",
  "[data-pwa-scroll-root='true']",
  ".public-page-shell",
  ".auth-surface",
  "[data-guide-page='true']",
].join(",");

const isStandalonePwa = () => Boolean(
  window.matchMedia?.("(display-mode: standalone)")?.matches
    || window.navigator?.standalone === true,
);

const detectPwaPlatform = () => {
  const userAgent = window.navigator?.userAgent || "";
  const platform = window.navigator?.userAgentData?.platform
    || window.navigator?.platform
    || "";
  const iPadOsDesktopMode =
    platform === "MacIntel" && Number(window.navigator?.maxTouchPoints || 0) > 1;

  if (/iPad|iPhone|iPod/i.test(userAgent) || iPadOsDesktopMode) return "ios";
  if (/Android/i.test(userAgent) || /Android/i.test(platform)) return "android";
  return "other";
};

const getLayoutViewportHeight = () => {
  const innerHeight = Number(window.innerHeight || 0);
  if (innerHeight > 0) return Math.round(innerHeight);

  const visualHeight = Number(window.visualViewport?.height || 0)
    + Number(window.visualViewport?.offsetTop || 0);
  if (visualHeight > 0) return Math.round(visualHeight);

  return Math.round(Number(document.documentElement.clientHeight || 0));
};

/**
 * A standalone iOS PWA can expose a shorter layout viewport on a later launch
 * while the physical screen dimensions remain unchanged. Anchor its dock to
 * the physical screen height, not the transient visual/layout viewport height.
 */
export const resolvePwaScreenHeight = ({
  screenWidth,
  screenHeight,
  landscape,
  fallbackHeight,
}) => {
  const width = Number(screenWidth);
  const height = Number(screenHeight);
  if (width > 0 && height > 0) {
    return Math.round(landscape ? Math.min(width, height) : Math.max(width, height));
  }
  return Math.max(0, Math.round(Number(fallbackHeight) || 0));
};

const isEditableElement = (element) => Boolean(
  element instanceof Element && element.matches(EDITABLE_SELECTOR),
);

const resetHorizontalDocumentState = () => {
  const scrollingElement = document.scrollingElement;
  if (scrollingElement) {
    scrollingElement.scrollLeft = 0;
  }
  document.documentElement.scrollLeft = 0;
  document.body.scrollLeft = 0;
};

export const installMobilePwaStability = () => {
  if (typeof window === "undefined" || typeof document === "undefined") {
    return () => {};
  }

  if (window[INSTALLATION_KEY]) return window[INSTALLATION_KEY];

  const root = document.documentElement;
  const visualViewport = window.visualViewport;
  const standaloneQuery = window.matchMedia?.("(display-mode: standalone)");
  let stableLayoutHeight = 0;
  let stableViewportWidth = 0;
  let keyboardOpen = false;
  let frameId = 0;
  let orientationTimer = 0;

  const syncScreenAnchor = () => {
    if (!isStandalonePwa() || detectPwaPlatform() !== "ios") {
      root.style.removeProperty("--pwa-device-screen-height");
      return;
    }

    const orientationType = window.screen?.orientation?.type;
    const isLandscape = typeof orientationType === "string"
      ? orientationType.startsWith("landscape")
      : window.matchMedia?.("(orientation: landscape)")?.matches
        ?? window.innerWidth > window.innerHeight;
    const height = resolvePwaScreenHeight({
      screenWidth: window.screen?.width,
      screenHeight: window.screen?.height,
      landscape: isLandscape,
      fallbackHeight: getLayoutViewportHeight(),
    });

    if (height > 0) {
      root.style.setProperty("--pwa-device-screen-height", `${height}px`);
    }
  };

  const clearKeyboardState = () => {
    keyboardOpen = false;
    root.dataset.keyboardOpen = "false";
    root.style.setProperty("--virtual-keyboard-height", "0px");
  };

  const setStableLayoutHeight = ({ force = false } = {}) => {
    if (!isStandalonePwa() || (keyboardOpen && !force)) return;

    const nextHeight = getLayoutViewportHeight();
    if (nextHeight <= 0) return;

    stableLayoutHeight = nextHeight;
    stableViewportWidth = Number(window.innerWidth || 0);
    root.style.setProperty("--pwa-layout-height", `${nextHeight}px`);
  };

  const syncEnvironmentMarkers = () => {
    const standalone = isStandalonePwa();
    root.dataset.standalonePwa = String(standalone);
    root.dataset.pwaPlatform = detectPwaPlatform();
    syncScreenAnchor();

    if (!standalone) {
      clearKeyboardState();
      return;
    }

    if (stableLayoutHeight <= 0) {
      setStableLayoutHeight({ force: true });
    }
  };

  const keepFocusedElementVisible = () => {
    const activeElement = document.activeElement;
    if (!keyboardOpen || !visualViewport || !isEditableElement(activeElement)) return;

    const scrollContainer = activeElement.closest(INTERNAL_SCROLL_SELECTOR);
    if (!scrollContainer) return;

    const rect = activeElement.getBoundingClientRect();
    const visibleTop = Number(visualViewport.offsetTop || 0) + 16;
    const visibleBottom =
      Number(visualViewport.offsetTop || 0)
      + Number(visualViewport.height || 0)
      - 16;
    let delta = 0;

    if (rect.bottom > visibleBottom) delta = rect.bottom - visibleBottom;
    if (rect.top < visibleTop) delta = rect.top - visibleTop;
    if (Math.abs(delta) < 1) return;

    // Immediate corrections cannot overlap the native keyboard scroll animation.
    scrollContainer.scrollBy({
      top: delta,
      left: 0,
      behavior: "auto",
    });
  };

  const syncKeyboardState = () => {
    if (!isStandalonePwa() || !visualViewport || stableLayoutHeight <= 0) {
      clearKeyboardState();
      return;
    }

    const activeElement = document.activeElement;
    const keyboardHeight = Math.max(
      0,
      Math.round(
        stableLayoutHeight
          - Number(visualViewport.height || 0)
          - Number(visualViewport.offsetTop || 0),
      ),
    );

    keyboardOpen = isEditableElement(activeElement)
      && keyboardHeight >= KEYBOARD_THRESHOLD_PX;

    root.dataset.keyboardOpen = String(keyboardOpen);
    root.style.setProperty(
      "--virtual-keyboard-height",
      keyboardOpen ? `${keyboardHeight}px` : "0px",
    );

    if (!keyboardOpen) return;

    // iOS WebKit already scrolls focused auth inputs into view. Re-scrolling
    // the auth container on every visualViewport scroll/resize creates a
    // feedback loop: the manual scroll emits another viewport event, causing
    // the login form to jump or flicker while the keyboard is displayed.
    if (
      root.dataset.pwaPlatform === "ios" &&
      isEditableElement(activeElement) &&
      activeElement.closest(".auth-surface")
    ) {
      window.cancelAnimationFrame(frameId);
      return;
    }

    window.cancelAnimationFrame(frameId);
    frameId = window.requestAnimationFrame(keepFocusedElementVisible);
  };

  const handleViewportResize = () => {
    const widthChanged = Number(window.innerWidth || 0) !== stableViewportWidth;
    syncKeyboardState();
    if (!keyboardOpen && widthChanged) {
      setStableLayoutHeight({ force: true });
    }
  };

  const handleOrientationChange = () => {
    window.clearTimeout(orientationTimer);
    orientationTimer = window.setTimeout(() => {
      clearKeyboardState();
      setStableLayoutHeight({ force: true });
      syncScreenAnchor();
      syncKeyboardState();
      resetHorizontalDocumentState();
    }, 250);
  };

  const handleVisibilityChange = () => {
    if (document.hidden) return;
    syncEnvironmentMarkers();
    clearKeyboardState();
    setStableLayoutHeight({ force: true });
    syncKeyboardState();
    resetHorizontalDocumentState();
  };

  const handleFocusChange = () => {
    window.cancelAnimationFrame(frameId);
    frameId = window.requestAnimationFrame(syncKeyboardState);
  };

  syncEnvironmentMarkers();
  setStableLayoutHeight({ force: true });
  syncKeyboardState();

  standaloneQuery?.addEventListener?.("change", syncEnvironmentMarkers);
  visualViewport?.addEventListener("resize", syncKeyboardState);
  visualViewport?.addEventListener("scroll", syncKeyboardState);
  window.addEventListener("resize", handleViewportResize);
  window.addEventListener("orientationchange", handleOrientationChange);
  window.addEventListener("pageshow", handleVisibilityChange);
  document.addEventListener("visibilitychange", handleVisibilityChange);
  document.addEventListener("focusin", handleFocusChange);
  document.addEventListener("focusout", handleFocusChange);

  const cleanup = () => {
    standaloneQuery?.removeEventListener?.("change", syncEnvironmentMarkers);
    visualViewport?.removeEventListener("resize", syncKeyboardState);
    visualViewport?.removeEventListener("scroll", syncKeyboardState);
    window.removeEventListener("resize", handleViewportResize);
    window.removeEventListener("orientationchange", handleOrientationChange);
    window.removeEventListener("pageshow", handleVisibilityChange);
    document.removeEventListener("visibilitychange", handleVisibilityChange);
    document.removeEventListener("focusin", handleFocusChange);
    document.removeEventListener("focusout", handleFocusChange);
    window.clearTimeout(orientationTimer);
    window.cancelAnimationFrame(frameId);
    clearKeyboardState();
    root.style.removeProperty("--pwa-device-screen-height");
    delete window[INSTALLATION_KEY];
  };

  window[INSTALLATION_KEY] = cleanup;
  return cleanup;
};
