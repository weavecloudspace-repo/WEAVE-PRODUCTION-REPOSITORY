const DEFAULT_API_URL =
  import.meta.env.MODE === "development"
    ? "http://localhost:8080/api/v1"
    : "/api/v1";

const API_URL =
  (import.meta.env.MODE === "development"
    ? import.meta.env.VITE_API_URL_DEV || import.meta.env.VITE_API_URL
    : import.meta.env.VITE_API_URL) || DEFAULT_API_URL;

export const API_BASE_URL = API_URL.replace(/\/$/, "");

const ACCESS_TOKEN_KEY = "access_token";
const LEGACY_TOKEN_KEY = "token";
const USER_KEY = "auth_user";
const ROLE_KEY = "auth_role";
const REMEMBER_KEY = "auth_remember";
const AUTH_REFRESH_ENDPOINT = "/auth/refresh";
const AUTH_LOGOUT_ENDPOINT = "/auth/logout";
const AUTH_LOGIN_ENDPOINT = "/auth/login";
const CSRF_HEADER_NAME = "x-weave-csrf";
const CSRF_HEADER_VALUE = "1";
const MAINTENANCE_STORAGE_KEY = "weave_platform_maintenance";
const SECURITY_BLOCK_STORAGE_KEY = "weave_security_block";
export const NAVIGATION_ABORT_EVENT = "weave:navigation-start";
export const APP_NAVIGATE_EVENT = "weave:navigate";
export const PLATFORM_MAINTENANCE_EVENT = "weave:platform-maintenance";
export const SECURITY_BLOCK_EVENT = "weave:security-block";
const DEFAULT_USER_SAFE_ERROR =
  "Something went wrong while processing your request. Please try again.";
const NETWORK_ERROR_MESSAGE =
  "We could not reach the server. Check your connection and try again.";
const TECHNICAL_ERROR_PATTERN =
  /traceback|sql|sqlalchemy|asyncpg|psycopg|uuid|pydantic|stack trace|internal server error|syntax error/i;
const REFRESH_BEFORE_EXPIRY_MS = 75 * 1000;

let refreshPromise = null;
let refreshTimerId = null;
const authTokenListeners = new Set();

const notifyAuthTokenListeners = (token) => {
  for (const listener of [...authTokenListeners]) {
    try {
      listener(token);
    } catch (error) {
      console.error("Auth token listener failed", error);
    }
  }
};

export const isAbortError = (error) =>
  !error?.response && (
    error?.name === "AbortError" ||
    error?.code === 20 ||
    error?.isAbortError === true ||
    (typeof error?.message === "string" &&
      /^(?:the operation was aborted|this operation was aborted|request (?:was )?aborted)\.?$/i.test(error.message.trim()))
  );

const normalizeDetail = (detail) => {
  if (!detail) return null;

  if (typeof detail === "string") return detail;

  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (typeof item === "string") return item;
        if (item?.msg) return item.msg;
        if (item?.message) return item.message;
        return null;
      })
      .filter(Boolean)
      .join(", ");
  }

  if (typeof detail === "object") {
    return detail.detail || detail.message || detail.msg || null;
  }

  return String(detail);
};

const getStoredValue = (key) =>
  localStorage.getItem(key) || sessionStorage.getItem(key);

const setStoredValue = (key, value, { remember = true } = {}) => {
  const primaryStorage = remember ? localStorage : sessionStorage;
  const secondaryStorage = remember ? sessionStorage : localStorage;

  secondaryStorage.removeItem(key);
  primaryStorage.setItem(key, value);
};

const removeStoredValue = (key) => {
  localStorage.removeItem(key);
  sessionStorage.removeItem(key);
};

// Remove old persisted access tokens from previous builds.
// The refresh-token cookie is now the durable session source.
removeStoredValue(LEGACY_TOKEN_KEY);

const decodeTokenPayload = (token) => {
  try {
    const payload = token.split(".")[1];
    const normalizedPayload = payload.replace(/-/g, "+").replace(/_/g, "/");
    const padding = "=".repeat((4 - (normalizedPayload.length % 4)) % 4);
    return JSON.parse(atob(`${normalizedPayload}${padding}`));
  } catch {
    return null;
  }
};

const getStoredRememberPreference = () =>
  localStorage.getItem(REMEMBER_KEY) === "true";

const setStoredRememberPreference = (remember) => {
  if (remember) {
    localStorage.setItem(REMEMBER_KEY, "true");
  } else {
    localStorage.removeItem(REMEMBER_KEY);
  }
};

const isRefreshManagedEndpoint = (endpoint) =>
  endpoint === AUTH_REFRESH_ENDPOINT ||
  endpoint === AUTH_LOGOUT_ENDPOINT ||
  endpoint === AUTH_LOGIN_ENDPOINT;

const isCookieProtectedEndpoint = (endpoint) =>
  endpoint === AUTH_REFRESH_ENDPOINT || endpoint === AUTH_LOGOUT_ENDPOINT;

const buildEndpointWithParams = (endpoint, params) => {
  if (!params || typeof params !== "object") return endpoint;

  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") return;
    if (Array.isArray(value)) {
      value.forEach((item) => query.append(key, String(item)));
      return;
    }
    query.set(key, String(value));
  });

  const queryString = query.toString();
  if (!queryString) return endpoint;
  return `${endpoint}${endpoint.includes("?") ? "&" : "?"}${queryString}`;
};

const clearRefreshTimer = () => {
  if (refreshTimerId !== null) {
    window.clearTimeout(refreshTimerId);
    refreshTimerId = null;
  }
};

const redirectToLogin = () => {
  if (window.location.pathname === "/login") return;

  window.dispatchEvent(
    new CustomEvent(APP_NAVIGATE_EVENT, { detail: { path: "/login" } }),
  );
};

const handleRefreshFailure = () => {
  authSession.clear();
  redirectToLogin();
};

const scheduleAccessTokenRefresh = (token) => {
  clearRefreshTimer();

  const payload = decodeTokenPayload(token);
  const expiresAt = payload?.exp ? payload.exp * 1000 : null;

  if (!expiresAt) return;

  const refreshInMs = Math.max(
    expiresAt - Date.now() - REFRESH_BEFORE_EXPIRY_MS,
    0,
  );

  refreshTimerId = window.setTimeout(() => {
    refreshAccessToken().catch(handleRefreshFailure);
  }, refreshInMs);
};

const buildFieldErrors = (detail) => {
  if (!Array.isArray(detail)) return {};

  return detail.reduce((errors, item) => {
    if (!item || typeof item !== "object") return errors;

    const loc = Array.isArray(item.loc)
      ? item.loc.filter((segment) => segment !== "body")
      : [];

    const fieldName = loc.map(String).join(".");
    const message = normalizeDetail(item.msg) || "Invalid value";

    if (!fieldName) return errors;

    errors[fieldName] = errors[fieldName]
      ? `${errors[fieldName]}, ${message}`
      : message;

    return errors;
  }, {});
};

const getStatusFallbackMessage = (status, fallback) => {
  if (fallback) return fallback;

  switch (status) {
    case 400:
      return DEFAULT_USER_SAFE_ERROR;
    case 401:
      return "Your session has expired. Please log in again.";
    case 403:
      return "You do not have permission to perform this action.";
    case 409:
      return "This request conflicts with existing data.";
    case 429:
      return "Too many requests. Please wait before trying again.";
    case 503:
      return "Weave is temporarily in maintenance mode. Please try again later.";
    default:
      return DEFAULT_USER_SAFE_ERROR;
  }
};

const isTechnicalMessage = (message) =>
  typeof message === "string" && TECHNICAL_ERROR_PATTERN.test(message);

const normalizeBoolean = (value) => value === true || value === "true";

const normalizeSessionUser = (user) => {
  if (!user || typeof user !== "object") return user;

  const normalizedUser = { ...user };

  if (normalizedUser.first_name && !normalizedUser.firstname) {
    normalizedUser.firstname = normalizedUser.first_name;
  }
  if (normalizedUser.last_name && !normalizedUser.lastname) {
    normalizedUser.lastname = normalizedUser.last_name;
  }
  if (normalizedUser.actor_type === "tenant_admin" && !normalizedUser.role) {
    normalizedUser.role = "admin";
  }

  return normalizedUser;
};

const getVerificationMetadata = (data = {}, headers = {}) => ({
  verificationRequired: normalizeBoolean(
    data?.verification_required ??
      headers["x-verification-required"] ??
      headers["X-Verification-Required"],
  ),
  email: data?.email || headers["x-email"] || headers["X-Email"] || null,
  purpose:
    data?.purpose ||
    headers["x-otp-purpose"] ||
    headers["X-OTP-Purpose"] ||
    null,
  redirectTo:
    data?.redirect_to ||
    headers["x-redirect-to"] ||
    headers["X-Redirect-To"] ||
    null,
  resendOtpAvailable: normalizeBoolean(
    data?.resend_otp_available ??
      headers["x-resend-otp-available"] ??
      headers["X-Resend-Otp-Available"],
  ),
});

const getUserSafeMessage = (status, data, fallback, fieldErrors) => {
  const backendMessage =
    normalizeDetail(data?.message) || normalizeDetail(data?.detail);

  if (Object.keys(fieldErrors || {}).length > 0) {
    return backendMessage && !isTechnicalMessage(backendMessage)
      ? backendMessage
      : "Please correct the highlighted fields and try again.";
  }

  if (data?.security_block === true) {
    return (
      backendMessage ||
      "Access from this network has been temporarily blocked for security reasons."
    );
  }

  if (data?.maintenance_mode === true) {
    return (
      backendMessage ||
      "Weave is temporarily in maintenance mode. Please try again later."
    );
  }

  if (status >= 500) {
    return DEFAULT_USER_SAFE_ERROR;
  }

  if (backendMessage && !isTechnicalMessage(backendMessage)) {
    return backendMessage;
  }

  return getStatusFallbackMessage(status, fallback);
};

const persistMaintenanceState = (data = {}) => {
  if (data?.maintenance_mode !== true) return;
  const currentUser = authSession.getUser?.() || {};
  const currentRole = String(
    currentUser.role || currentUser.actor_type || authSession.getRole?.() || "",
  ).toLowerCase();
  if (currentRole === "superadmin") return;

  const payload = {
    message:
      normalizeDetail(data?.detail) ||
      normalizeDetail(data?.message) ||
      "Weave is temporarily in maintenance mode. Please try again later.",
    reason: data?.maintenance_reason || null,
    detectedAt: new Date().toISOString(),
  };

  sessionStorage.setItem(MAINTENANCE_STORAGE_KEY, JSON.stringify(payload));
  window.dispatchEvent(
    new CustomEvent(PLATFORM_MAINTENANCE_EVENT, { detail: payload }),
  );

  if (window.location.pathname !== "/maintenance") {
    window.dispatchEvent(
      new CustomEvent(APP_NAVIGATE_EVENT, { detail: { path: "/maintenance" } }),
    );
  }
};

const persistSecurityBlockState = (data = {}) => {
  if (data?.security_block !== true) return;

  const payload = {
    message:
      normalizeDetail(data?.detail) ||
      normalizeDetail(data?.message) ||
      "Access from this network has been temporarily blocked for security reasons.",
    reason: data?.reason || null,
    ipLabel: data?.ip_label || null,
    expiresAt: data?.expires_at || null,
    detectedAt: new Date().toISOString(),
  };

  sessionStorage.setItem(SECURITY_BLOCK_STORAGE_KEY, JSON.stringify(payload));
  window.dispatchEvent(
    new CustomEvent(SECURITY_BLOCK_EVENT, { detail: payload }),
  );

  if (window.location.pathname !== "/network-blocked") {
    window.dispatchEvent(
      new CustomEvent(APP_NAVIGATE_EVENT, {
        detail: { path: "/network-blocked" },
      }),
    );
  }
};

export const getStoredMaintenanceState = () => {
  const rawValue = sessionStorage.getItem(MAINTENANCE_STORAGE_KEY);
  if (!rawValue) return null;

  try {
    return JSON.parse(rawValue);
  } catch {
    sessionStorage.removeItem(MAINTENANCE_STORAGE_KEY);
    return null;
  }
};

export const clearStoredMaintenanceState = () => {
  sessionStorage.removeItem(MAINTENANCE_STORAGE_KEY);
};

export const getStoredSecurityBlockState = () => {
  const rawValue = sessionStorage.getItem(SECURITY_BLOCK_STORAGE_KEY);
  if (!rawValue) return null;

  try {
    return JSON.parse(rawValue);
  } catch {
    sessionStorage.removeItem(SECURITY_BLOCK_STORAGE_KEY);
    return null;
  }
};

export const clearStoredSecurityBlockState = () => {
  sessionStorage.removeItem(SECURITY_BLOCK_STORAGE_KEY);
};

export const authSession = {
  getToken: () => sessionStorage.getItem(ACCESS_TOKEN_KEY),

  setToken: (token, { remember = true } = {}) => {
    removeStoredValue(LEGACY_TOKEN_KEY);
    setStoredRememberPreference(remember);
    clearRefreshTimer();

    if (!token) {
      sessionStorage.removeItem(ACCESS_TOKEN_KEY);
      notifyAuthTokenListeners(null);
      return;
    }

    sessionStorage.setItem(ACCESS_TOKEN_KEY, token);
    scheduleAccessTokenRefresh(token);
    notifyAuthTokenListeners(token);
  },

  clearToken: () => {
    clearRefreshTimer();
    sessionStorage.removeItem(ACCESS_TOKEN_KEY);
    removeStoredValue(LEGACY_TOKEN_KEY);
    notifyAuthTokenListeners(null);
  },

  subscribeToken: (listener) => {
    if (typeof listener !== "function") {
      throw new TypeError("Auth token listener must be a function.");
    }
    authTokenListeners.add(listener);
    return () => authTokenListeners.delete(listener);
  },

  getRememberPreference: getStoredRememberPreference,

  getUser: () => {
    const rawValue = getStoredValue(USER_KEY);

    if (!rawValue) return null;

    try {
      return JSON.parse(rawValue);
    } catch {
      removeStoredValue(USER_KEY);
      return null;
    }
  },

  setUser: (user, { remember = true } = {}) => {
    if (!user) {
      authSession.clearUser();
      return;
    }

    const normalizedUser = normalizeSessionUser(user);

    setStoredValue(USER_KEY, JSON.stringify(normalizedUser), { remember });

    if (normalizedUser.role) {
      authSession.setRole(normalizedUser.role, { remember });
    }
  },

  clearUser: () => {
    removeStoredValue(USER_KEY);
    removeStoredValue(ROLE_KEY);
  },

  getRole: () => getStoredValue(ROLE_KEY),

  setRole: (role, { remember = true } = {}) => {
    if (!role) {
      removeStoredValue(ROLE_KEY);
      return;
    }

    setStoredValue(ROLE_KEY, role, { remember });
  },

  clear: () => {
    authSession.clearToken();
    authSession.clearUser();
  },
};

export const parseApiError = (error, fallback) => {
  if (isAbortError(error)) {
    return {
      status: null,
      message: "",
      fieldErrors: {},
      headers: {},
      retryAfter: null,
      isNetworkError: false,
      isAbortError: true,
      isMaintenanceMode: false,
      isSecurityBlock: false,
      technicalMessage: error?.message || null,
    };
  }

  if (!error?.response && error?.name !== "TypeError" && error?.message) {
    return {
      status: null,
      message: error.message,
      fieldErrors: {},
      headers: {},
      retryAfter: null,
      isNetworkError: false,
      isAbortError: false,
      isMaintenanceMode: false,
      isSecurityBlock: false,
      technicalMessage: error.message,
    };
  }

  if (!error?.response) {
    return {
      status: null,
      message: NETWORK_ERROR_MESSAGE,
      fieldErrors: {},
      headers: {},
      retryAfter: null,
      isNetworkError: true,
      isAbortError: false,
      isMaintenanceMode: false,
      isSecurityBlock: false,
      technicalMessage: error?.message || null,
    };
  }

  const { data = {}, headers = {}, status } = error.response;
  const safeHeaders = headers || {};
  const fieldErrors = buildFieldErrors(data?.detail);
  const verificationMetadata = getVerificationMetadata(data, safeHeaders);
  const message = getUserSafeMessage(status, data, fallback, fieldErrors);

  return {
    status,
    message,
    fieldErrors,
    headers: safeHeaders,
    retryAfter:
      safeHeaders["retry-after"] || safeHeaders["Retry-After"] || null,
    isNetworkError: false,
    isAbortError: false,
    isMaintenanceMode: data?.maintenance_mode === true,
    isSecurityBlock: data?.security_block === true,
    maintenanceReason: data?.maintenance_reason || null,
    securityBlockReason: data?.reason || null,
    technicalMessage: error?.message || null,
    data,
    ...verificationMetadata,
  };
};

export const remapFieldErrors = (fieldErrors = {}, fieldMap = {}) =>
  Object.entries(fieldErrors || {}).reduce((mappedErrors, [field, message]) => {
    const mappedField = fieldMap[field] || field;
    mappedErrors[mappedField] = message;
    return mappedErrors;
  }, {});

export const getErrorMessage = (error, fallback = "An error occurred") => {
  if (!error || isAbortError(error)) return "";
  return parseApiError(error, fallback).message;
};

const logUnexpectedApiError = (endpoint, error) => {
  if (isAbortError(error)) return;

  const status = error?.response?.status;
  if (status && (status < 500 || status === 503)) {
    return;
  }

  console.error(`API request failed: ${endpoint}`, {
    status: status || "network",
    message: status ? getErrorMessage(error) : NETWORK_ERROR_MESSAGE,
  });
};

const createApiError = (response, data, headers) => {
  const errorPayload = {
    response: {
      status: response.status,
      data,
      headers,
    },
  };

  const error = new Error(getErrorMessage(errorPayload, "An error occurred"));
  error.response = errorPayload.response;
  return error;
};

const handleControlResponse = (response, data) => {
  if (response.status === 403 && data?.security_block === true) {
    persistSecurityBlockState(data);
    return;
  }

  if (response.status === 503 && data?.maintenance_mode === true) {
    persistMaintenanceState(data);
  }
};

const refreshAccessToken = async () => {
  if (!refreshPromise) {
    refreshPromise = fetch(`${API_BASE_URL}${AUTH_REFRESH_ENDPOINT}`, {
      method: "POST",
      headers: {
        [CSRF_HEADER_NAME]: CSRF_HEADER_VALUE,
      },
      credentials: "include",
    })
      .then(async (response) => {
        const data = await response.json().catch(() => ({}));
        const responseHeaders = Object.fromEntries(response.headers.entries());

        if (!response.ok) {
          handleControlResponse(response, data);
          throw createApiError(response, data, responseHeaders);
        }

        if (!data?.access_token) {
          throw new Error("Refresh response did not include an access token.");
        }

        authSession.setToken(data.access_token, {
          remember: getStoredRememberPreference(),
        });

        return data.access_token;
      })
      .finally(() => {
        refreshPromise = null;
      });
  }

  return refreshPromise;
};

async function request(endpoint, options = {}, hasRetried = false) {
  const {
    auth = true,
    clearAuthOnUnauthorized = true,
    skipAuthRefresh = false,
    headers: optionHeaders = {},
    signal: providedSignal,
    params,
    responseType = "json",
    ...restOptions
  } = options;
  const token = auth ? authSession.getToken() : null;
  const hasBody = restOptions.body !== undefined && restOptions.body !== null;
  const isFormData =
    typeof FormData !== "undefined" && restOptions.body instanceof FormData;
  const method = restOptions.method || "GET";
  const autoAbortController =
    !providedSignal && method === "GET" ? new AbortController() : null;
  const requestSignal = providedSignal || autoAbortController?.signal;
  const requestEndpoint = buildEndpointWithParams(endpoint, params);

  const headers = {
    ...(hasBody && !isFormData ? { "Content-Type": "application/json" } : {}),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...optionHeaders,
    ...(isCookieProtectedEndpoint(endpoint)
      ? { [CSRF_HEADER_NAME]: CSRF_HEADER_VALUE }
      : {}),
  };

  const config = {
    ...restOptions,
    headers,
    credentials: "include",
    ...(requestSignal ? { signal: requestSignal } : {}),
  };

  // The route effect can notify after the destination page has started reading.
  const requestLocation = window.location.href;
  const abortOnNavigation = () => {
    if (window.location.href !== requestLocation) autoAbortController?.abort();
  };

  if (autoAbortController) {
    window.addEventListener(NAVIGATION_ABORT_EVENT, abortOnNavigation);
  }

  try {
    const response = await fetch(`${API_BASE_URL}${requestEndpoint}`, config);
    const responseHeaders = Object.fromEntries(response.headers.entries());
    const data =
      response.ok && responseType === "blob"
        ? await response.blob()
        : response.ok && responseType === "text"
          ? await response.text()
          : await response.json().catch(() => ({}));

    if (!response.ok) {
      handleControlResponse(response, data);

      const canAttemptRefresh =
        response.status === 401 &&
        auth &&
        clearAuthOnUnauthorized &&
        !skipAuthRefresh &&
        !hasRetried &&
        !isRefreshManagedEndpoint(endpoint);

      if (canAttemptRefresh) {
        try {
          await refreshAccessToken();
          return request(endpoint, options, true);
        } catch (refreshError) {
          handleRefreshFailure();
          throw refreshError;
        }
      }

      if (response.status === 401 && clearAuthOnUnauthorized) {
        authSession.clear();
      }

      throw createApiError(response, data, responseHeaders);
    }

    // Invalidate after the server confirms a write, including lifecycle actions.
    if (
      ["POST", "PATCH", "PUT", "DELETE"].includes(method) &&
      /^\/(academic-levels|classes|subjects|tenant-admin\/(academics|setup-assistant))(\/|\?|$)/.test(endpoint)
    ) {
      window.dispatchEvent(new Event("weave:dashboard-cache-clear"));
    }
    return data;
  } catch (error) {
    if (isAbortError(error)) {
      error.isAbortError = true;
      throw error;
    }

    logUnexpectedApiError(endpoint, error);
    throw error;
  } finally {
    if (autoAbortController) {
      window.removeEventListener(NAVIGATION_ABORT_EVENT, abortOnNavigation);
    }
  }
}

export const api = {
  get: (endpoint, options) => request(endpoint, { method: "GET", ...options }),

  getBlob: (endpoint, options) =>
    request(endpoint, { method: "GET", responseType: "blob", ...options }),

  post: (endpoint, body, options) =>
    request(endpoint, {
      method: "POST",
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
      ...options,
    }),

  postForm: (endpoint, formData, options) =>
    request(endpoint, {
      method: "POST",
      body: formData,
      ...options,
    }),

  patch: (endpoint, body, options) =>
    request(endpoint, {
      method: "PATCH",
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
      ...options,
    }),

  put: (endpoint, body, options) =>
    request(endpoint, {
      method: "PUT",
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
      ...options,
    }),

  delete: (endpoint, options) =>
    request(endpoint, { method: "DELETE", ...options }),
};

const initialToken = authSession.getToken();
if (initialToken) {
  scheduleAccessTokenRefresh(initialToken);
}
