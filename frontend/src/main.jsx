import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import AppErrorBoundary from "./components/errors/AppErrorBoundary.jsx";
import { captureFrontendException, initializeSentry } from "./config/sentry";
import {
  applyPublicPricingCatalogue,
  hydrateCachedPublicPricingCatalogue,
  resetPublicPricingPlans,
  settlePublicPricingCatalogue,
} from "./features/subscriptions/pricingCatalogueRuntime";
import "./index.css";
import { installCookieCsrfFetchGuard } from "./services/installCookieCsrfFetchGuard";
import { realtimeClient } from "./services/realtimeClient";
import { subscriptionService } from "./services/subscriptionService";
import "./styles/brandAssets.css";
import "./styles/iosSafariBrowserTheme.css";
import "./styles/messaging.css";
import "./styles/mobileDashboard.css";
import "./styles/mobileDirectoryCards.css";
import "./styles/mobileOverrides.css";
import "./styles/mobilePlatformFixes.css";
import "./styles/pwaInteractions.css";
import "./styles/mobilePwaStability.css";
import "./styles/notificationDropdown.css";
import "./styles/studentDashboardCleanup.css";
import "./styles/largeScreens.css";
import {
  applyAccessibilityPreferences,
  getSavedAccessibilityPreferences,
  syncSystemThemePreference,
} from "./utils/accessibilityPreferences";
import { installMobilePwaStability } from "./utils/mobilePwaStability";
import { installThemeChromeSync } from "./utils/themeChromeSync";

void initializeSentry();
installCookieCsrfFetchGuard();
realtimeClient.start();
applyAccessibilityPreferences(getSavedAccessibilityPreferences());
syncSystemThemePreference();
installMobilePwaStability();
installThemeChromeSync();
resetPublicPricingPlans();
hydrateCachedPublicPricingCatalogue();

const standaloneQuery = window.matchMedia?.("(display-mode: standalone)");
const isStandalonePwa = () =>
  Boolean(standaloneQuery?.matches || window.navigator?.standalone === true);
const syncStandaloneDisplayMode = () => {
  document.documentElement.dataset.standalonePwa = String(isStandalonePwa());
};

const registerPwaServiceWorker = () => {
  if (
    !import.meta.env.PROD ||
    !window.isSecureContext ||
    !("serviceWorker" in window.navigator)
  )
    return;

  window.addEventListener(
    "load",
    () => {
      window.navigator.serviceWorker
        .register("/sw.js", { scope: "/", updateViaCache: "none" })
        .catch((error) => {
          console.warn("PWA service worker registration failed", error);
        });
    },
    { once: true },
  );
};

syncStandaloneDisplayMode();
registerPwaServiceWorker();
standaloneQuery?.addEventListener?.("change", syncStandaloneDisplayMode);
window.addEventListener("pageshow", syncStandaloneDisplayMode);
document.addEventListener("visibilitychange", syncStandaloneDisplayMode);

const reportReactError = (kind) => (error, errorInfo) => {
  captureFrontendException(error, {
    kind,
    componentStack: errorInfo?.componentStack,
  });
};

const root = createRoot(document.getElementById("root"), {
  onUncaughtError: reportReactError("react_uncaught"),
  onCaughtError: reportReactError("react_caught"),
  onRecoverableError: reportReactError("react_recoverable"),
});

const renderApp = () => {
  root.render(
    <AppErrorBoundary>
      <App />
    </AppErrorBoundary>,
  );
};

renderApp();

let lastCatalogueFetchAt = 0;
const refreshPublicCatalogue = ({ force = false } = {}) => {
  lastCatalogueFetchAt = Date.now();
  return subscriptionService
    .getPublicPlans({ force })
    .then((catalogue) => {
      const applied = applyPublicPricingCatalogue(catalogue);
      if (applied) renderApp();
      return applied;
    })
    .catch((error) => {
      settlePublicPricingCatalogue();
      console.warn("Subscription pricing catalogue could not be loaded", {
        message: error?.message || "unknown error",
      });
    });
};

const scheduleCatalogueRefresh = () => {
  const callback = () => refreshPublicCatalogue();
  if (typeof window.requestIdleCallback === "function") {
    window.requestIdleCallback(callback, { timeout: 2000 });
  } else {
    window.setTimeout(callback, 700);
  }
};

scheduleCatalogueRefresh();
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && Date.now() - lastCatalogueFetchAt > 5 * 60 * 1000) {
    refreshPublicCatalogue();
  }
});
