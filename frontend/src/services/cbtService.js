import { api } from "./api";

const PENDING_PAIRING_KEY = "weave_cbt_pending_pairing";
const PAIRING_PAGE_PATH = "/admin/cbt/pairing-code";

const storePendingPairing = (value) => {
  if (typeof window === "undefined") return;
  if (!value?.pairing_code) {
    window.sessionStorage.removeItem(PENDING_PAIRING_KEY);
    return;
  }
  window.sessionStorage.setItem(PENDING_PAIRING_KEY, JSON.stringify(value));
};

const readPendingPairing = () => {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(PENDING_PAIRING_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    window.sessionStorage.removeItem(PENDING_PAIRING_KEY);
    return null;
  }
};

const leaveExpiredPairingPage = () => {
  if (typeof window === "undefined") return;
  window.sessionStorage.removeItem(PENDING_PAIRING_KEY);
  window.setTimeout(() => {
    if (window.location.pathname === PAIRING_PAGE_PATH) {
      window.location.assign("/admin/cbt");
    }
  }, 0);
};

const createPairingCode = async () => {
  const response = await api.post("/cbt/pairing/codes");
  storePendingPairing(response);
  return response;
};

const getPairingStatus = (pairingCode) =>
  api.post("/cbt/pairing/status", { pairing_code: pairingCode });

const listServers = async () => {
  const response = await api.get("/cbt/servers");
  if (
    typeof window === "undefined" ||
    window.location.pathname !== PAIRING_PAGE_PATH
  ) {
    return response;
  }

  const pending = readPendingPairing();
  if (!pending?.pairing_code) {
    return { ...response, items: [] };
  }

  try {
    const status = await getPairingStatus(pending.pairing_code);
    if (status?.status === "paired") {
      window.sessionStorage.removeItem(PENDING_PAIRING_KEY);
      return {
        ...response,
        items: Array.isArray(response?.items)
          ? response.items.filter(
              (server) => String(server.id) === String(status.server_id),
            )
          : [],
      };
    }

    if (status?.status === "expired" || status?.status === "invalidated") {
      leaveExpiredPairingPage();
    }

    return { ...response, items: [] };
  } catch {
    return { ...response, items: [] };
  }
};

export const cbtService = {
  createPairingCode,
  getPairingStatus,
  getLatestRelease: () =>
    api.get("/cbt/releases/latest", {
      auth: false,
      clearAuthOnUnauthorized: false,
    }),
  verifyPairingCode: (payload) =>
    api.post("/cbt/pairing/verify", payload, { auth: false }),
  listServers,
  getServer: (serverId) =>
    api.get(`/cbt/servers/${encodeURIComponent(serverId)}`),
  suspendServer: (serverId) =>
    api.post(`/cbt/servers/${encodeURIComponent(serverId)}/suspend`),
  reactivateServer: (serverId) =>
    api.post(`/cbt/servers/${encodeURIComponent(serverId)}/reactivate`),
  unrevokeServer: (serverId) =>
    api.post(`/cbt/servers/${encodeURIComponent(serverId)}/unrevoke`),
  revokeServer: (serverId, payload = {}) =>
    api.post(`/cbt/servers/${encodeURIComponent(serverId)}/revoke`, payload),
  rotateCredential: (serverId) =>
    api.post(`/cbt/servers/${encodeURIComponent(serverId)}/rotate-credential`),
};

export default cbtService;
