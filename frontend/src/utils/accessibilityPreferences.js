import { scheduleThemeChromeSync } from "./themeChromeSync";

export const ACCESSIBILITY_STORAGE_KEYS = {
  theme: "theme",
  fontScale: "accessibilityFontScale",
  reducedMotion: "accessibilityReducedMotion",
  highContrast: "accessibilityHighContrast",
  language: "accessibilityLanguage",
};

export const getSystemTheme = () => {
  if (typeof window === "undefined") return "light";
  return window.matchMedia?.("(prefers-color-scheme: dark)")?.matches ? "dark" : "light";
};

export const getSavedAccessibilityPreferences = () => {
  if (typeof window === "undefined") {
    return {
      theme: "system",
      fontScale: 100,
      reducedMotion: false,
      highContrast: false,
      language: "en-US",
    };
  }

  return {
    theme: window.localStorage.getItem(ACCESSIBILITY_STORAGE_KEYS.theme) || "system",
    fontScale: Number(window.localStorage.getItem(ACCESSIBILITY_STORAGE_KEYS.fontScale) || 100),
    reducedMotion: window.localStorage.getItem(ACCESSIBILITY_STORAGE_KEYS.reducedMotion) === "true",
    highContrast: window.localStorage.getItem(ACCESSIBILITY_STORAGE_KEYS.highContrast) === "true",
    language: window.localStorage.getItem(ACCESSIBILITY_STORAGE_KEYS.language) || "en-US",
  };
};

export const applyAccessibilityPreferences = (preferences = {}) => {
  if (typeof document === "undefined") return;

  const themeChoice = preferences.theme || "system";
  const resolvedTheme = themeChoice === "system" ? getSystemTheme() : themeChoice;
  const fontScale = Number(preferences.fontScale || 100);
  const boundedFontScale = Math.min(115, Math.max(90, fontScale));

  document.documentElement.dataset.theme = resolvedTheme;
  document.documentElement.dataset.themePreference = themeChoice;
  document.documentElement.dataset.reducedMotion = String(Boolean(preferences.reducedMotion));
  document.documentElement.dataset.contrast = preferences.highContrast ? "high" : "normal";
  document.documentElement.dataset.language = preferences.language || "en-US";
  document.documentElement.style.fontSize = `${boundedFontScale}%`;
  document.documentElement.style.colorScheme = resolvedTheme;

  const appleStatusBarMeta = document.querySelector('meta[name="apple-mobile-web-app-status-bar-style"]');
  if (appleStatusBarMeta) {
    appleStatusBarMeta.setAttribute("content", resolvedTheme === "dark" ? "black" : "default");
  }

  scheduleThemeChromeSync();
};

export const saveAccessibilityPreferences = (preferences) => {
  if (typeof window === "undefined") return;

  if (preferences.theme === "system") {
    window.localStorage.removeItem(ACCESSIBILITY_STORAGE_KEYS.theme);
  } else {
    window.localStorage.setItem(ACCESSIBILITY_STORAGE_KEYS.theme, preferences.theme || "light");
  }
  window.localStorage.setItem(ACCESSIBILITY_STORAGE_KEYS.fontScale, String(preferences.fontScale || 100));
  window.localStorage.setItem(ACCESSIBILITY_STORAGE_KEYS.reducedMotion, String(Boolean(preferences.reducedMotion)));
  window.localStorage.setItem(ACCESSIBILITY_STORAGE_KEYS.highContrast, String(Boolean(preferences.highContrast)));
  window.localStorage.setItem(ACCESSIBILITY_STORAGE_KEYS.language, preferences.language || "en-US");
  window.dispatchEvent(new CustomEvent("weave:accessibility-preferences-changed", { detail: preferences }));
};

export const syncSystemThemePreference = () => {
  if (typeof window === "undefined") return undefined;

  const mediaQuery = window.matchMedia?.("(prefers-color-scheme: dark)");
  if (!mediaQuery) return undefined;

  const handleSystemThemeChange = () => {
    const preferences = getSavedAccessibilityPreferences();
    if (preferences.theme !== "system") return;

    applyAccessibilityPreferences(preferences);
    window.dispatchEvent(
      new CustomEvent("weave:accessibility-preferences-changed", {
        detail: preferences,
      }),
    );
  };

  mediaQuery.addEventListener?.("change", handleSystemThemeChange);
  mediaQuery.addListener?.(handleSystemThemeChange);

  return () => {
    mediaQuery.removeEventListener?.("change", handleSystemThemeChange);
    mediaQuery.removeListener?.(handleSystemThemeChange);
  };
};
