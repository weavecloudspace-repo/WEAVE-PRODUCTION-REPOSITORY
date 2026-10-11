import {
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  Copy,
  Cpu,
  Eye,
  EyeOff,
  MoreVertical,
  PauseCircle,
  Plus,
  RefreshCw,
  RotateCcw,
  Search,
  Server,
  ShieldAlert,
  ShieldX,
  ClipboardCheck,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import DashboardLayout from "../../components/layout/DashboardLayout";
import ConfirmDialog from "../../components/shared/ConfirmDialog";
import EmptyState from "../../components/shared/EmptyState";
import LoadingState from "../../components/shared/LoadingState";
import TypedConfirmationDialog from "../../features/academic-admin/TypedConfirmationDialog";
import Button from "../../components/ui/Button";
import Card from "../../components/ui/Card";
import Dropdown from "../../components/ui/Dropdown";
import Input from "../../components/ui/Input";
import Modal from "../../components/ui/Modal";
import {
  FEATURE_CODES,
  RESOURCE_CODES,
  formatPlanName,
} from "../../features/subscriptions/subscriptionConfig";
import { useSubscription } from "../../features/subscriptions/useSubscription";
import { useToast } from "../../hooks/useToast";
import { getErrorMessage, parseApiError } from "../../services/api";
import { cbtService } from "../../services/cbtService";

// Keep rotation hidden until CBT can adopt a replacement server credential.
const CREDENTIAL_ROTATION_AVAILABLE = false;

const STATUS_META = {
  active: {
    label: "Active",
    badge: "success",
    icon: CheckCircle2,
    dotClassName: "bg-emerald-500",
    haloClassName: "ring-emerald-100",
    tintClassName: "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-100",
  },
  suspended: {
    label: "Suspended",
    badge: "warning",
    icon: PauseCircle,
    dotClassName: "bg-amber-500",
    haloClassName: "ring-amber-100",
    tintClassName: "bg-amber-50 text-amber-700 ring-1 ring-amber-100",
  },
  revoked: {
    label: "Revoked",
    badge: "error",
    icon: ShieldX,
    dotClassName: "bg-rose-500",
    haloClassName: "ring-rose-100",
    tintClassName: "bg-rose-50 text-rose-700 ring-1 ring-rose-200",
  },
};

const SORT_OPTIONS = {
  newest: "Newest",
  oldest: "Oldest",
  name: "Name",
  recent: "Last seen",
};
const REVOKE_CONFIRMATION_LITERAL = "REVOKE SERVER";

const formatDateTime = (value) => {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "--";
  return date.toLocaleString();
};

const formatDate = (value) => {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "--";
  return date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
};

const formatTime = (value) => {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "--";
  return date.toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
  });
};

const formatRelativeTime = (value) => {
  if (!value) return "Never";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "--";
  const diffMs = Date.now() - date.getTime();
  const diffMinutes = Math.round(diffMs / 60000);

  if (diffMinutes <= 1) return "Just now";
  if (diffMinutes < 60)
    return `${diffMinutes} minute${diffMinutes === 1 ? "" : "s"} ago`;

  const diffHours = Math.round(diffMinutes / 60);
  if (diffHours < 24)
    return `${diffHours} hour${diffHours === 1 ? "" : "s"} ago`;

  const diffDays = Math.round(diffHours / 24);
  if (diffDays < 30) return `${diffDays} day${diffDays === 1 ? "" : "s"} ago`;

  const diffMonths = Math.round(diffDays / 30);
  return `${diffMonths} month${diffMonths === 1 ? "" : "s"} ago`;
};

const statusMetaFor = (status) =>
  STATUS_META[String(status || "").toLowerCase()] || {
    label: "Unknown",
    badge: "default",
    icon: AlertCircle,
    dotClassName: "bg-slate-400",
    haloClassName: "ring-slate-200",
    tintClassName: "bg-slate-100 text-slate-700 ring-1 ring-slate-200",
  };

function StatCard({ icon: Icon, label, value, hint, iconClassName }) {
  return (
    <Card className="rounded-xl border-border/80 p-3 shadow-sm sm:p-4">
      <div className="flex flex-col items-start gap-2.5 sm:gap-3">
        <div
          className={`grid h-10 w-10 place-items-center rounded-full sm:h-12 sm:w-12 ${iconClassName}`}
        >
          <Icon className="h-5 w-5 sm:h-6 sm:w-6" />
        </div>
        <div>
          <p className="text-xs font-medium text-text-muted sm:text-sm">
            {label}
          </p>
          <p className="mt-1 text-2xl font-semibold leading-none text-text sm:text-3xl">
            {value}
          </p>
          <p className="mt-2 hidden text-xs text-text-muted sm:block">{hint}</p>
        </div>
      </div>
    </Card>
  );
}

function ToolbarDropdown({ value, onChange, options, className = "" }) {
  const selectedOption =
    options.find((option) => option.value === value) || options[0];

  return (
    <Dropdown
      className={`min-w-[11rem] ${className}`}
      trigger={
        <button
          type="button"
          className="flex h-11 w-full items-center justify-between gap-3 rounded-xl border border-border/80 bg-surface px-4 text-left text-sm font-medium text-text shadow-sm transition hover:border-primary/30 hover:bg-primary-subtle/30"
        >
          <span className="truncate">{selectedOption.label}</span>
          <ChevronDown className="h-4 w-4 shrink-0 text-text-faint" />
        </button>
      }
    >
      <div className="px-2 py-1">
        {options.map((option) => (
          <button
            key={option.value}
            type="button"
            onClick={() => onChange(option.value)}
            className={`flex w-full items-center justify-between rounded-xl px-3 py-2.5 text-left text-sm font-medium transition ${
              option.value === value
                ? "bg-primary-subtle text-primary"
                : "text-text hover:bg-surface-muted/70"
            }`}
          >
            {option.label}
            {option.value === value ? (
              <CheckCircle2 className="h-4 w-4" />
            ) : null}
          </button>
        ))}
      </div>
    </Dropdown>
  );
}

export default function CBTServersPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const { showError, showSuccess } = useToast();
  const {
    planCode,
    getFeatureGuard,
    getResourceGuard,
    refreshSubscriptionState,
  } = useSubscription();
  const featureGuard = getFeatureGuard(FEATURE_CODES.CBT_PAIRING);
  const resourceGuard = getResourceGuard(RESOURCE_CODES.CBT_SERVERS, {
    featureCode: FEATURE_CODES.CBT_PAIRING,
  });

  const [servers, setServers] = useState([]);
  const [selectedServerId, setSelectedServerId] = useState("");
  const [serverModalOpen, setServerModalOpen] = useState(false);
  const [hiddenServerDetails, setHiddenServerDetails] = useState({});
  const [actionMenuServerId, setActionMenuServerId] = useState("");
  const [rotatedCredential, setRotatedCredential] = useState(null);
  const [confirmState, setConfirmState] = useState(null);
  const [revocationReason, setRevocationReason] = useState("");
  const [busyAction, setBusyAction] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [searchTerm, setSearchTerm] = useState("");
  const [statusFilter, setStatusFilter] = useState("active");
  const [sortBy, setSortBy] = useState("newest");

  const loadServers = async ({ preserveSelected = true } = {}) => {
    try {
      setError("");
      const response = await cbtService.listServers();
      const items = Array.isArray(response?.items) ? response.items : [];
      setServers(items);
      setSelectedServerId((current) => {
        if (
          preserveSelected &&
          current &&
          items.some((item) => item.id === current)
        ) {
          return current;
        }
        return items[0]?.id || "";
      });
    } catch (requestError) {
      setError(getErrorMessage(requestError, "Could not load CBT servers."));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (featureGuard.pending) {
      setLoading(false);
      return;
    }
    loadServers();
  }, [featureGuard.allowed, featureGuard.pending]);

  useEffect(() => {
    const requestedServerId = location.state?.selectedServerId;
    if (!requestedServerId || servers.length === 0) return;

    const matchedServer = servers.find(
      (server) => String(server.id) === String(requestedServerId),
    );
    if (matchedServer) {
      setSelectedServerId(matchedServer.id);
      setServerModalOpen(true);
      navigate(location.pathname, { replace: true, state: null });
    }
  }, [location.pathname, location.state, navigate, servers]);

  const filteredServers = useMemo(() => {
    const normalizedSearch = searchTerm.trim().toLowerCase();
    let items = [...servers];

    if (normalizedSearch) {
      items = items.filter((server) => {
        const haystack = [
          server.name,
          server.id,
          server.client_version,
          server.last_ip_address,
        ]
          .filter(Boolean)
          .join(" ")
          .toLowerCase();
        return haystack.includes(normalizedSearch);
      });
    }

    if (statusFilter !== "all") {
      items = items.filter(
        (server) => String(server.status || "").toLowerCase() === statusFilter,
      );
    }

    items.sort((left, right) => {
      if (sortBy === "name") {
        return String(left.name || "").localeCompare(String(right.name || ""));
      }

      const leftPaired = new Date(left.paired_at || 0).getTime();
      const rightPaired = new Date(right.paired_at || 0).getTime();
      const leftSeen = new Date(left.last_seen_at || 0).getTime();
      const rightSeen = new Date(right.last_seen_at || 0).getTime();

      if (sortBy === "oldest") return leftPaired - rightPaired;
      if (sortBy === "recent") return rightSeen - leftSeen;
      return rightPaired - leftPaired;
    });

    return items;
  }, [searchTerm, servers, sortBy, statusFilter]);

  const selectedServer =
    filteredServers.find((server) => server.id === selectedServerId) ||
    servers.find((server) => server.id === selectedServerId) ||
    filteredServers[0] ||
    servers[0] ||
    null;

  const stats = useMemo(() => {
    const active = servers.filter(
      (server) => String(server.status || "").toLowerCase() === "active",
    ).length;
    const suspended = servers.filter(
      (server) => String(server.status || "").toLowerCase() === "suspended",
    ).length;
    const revoked = servers.filter(
      (server) => String(server.status || "").toLowerCase() === "revoked",
    ).length;

    return {
      total: servers.length,
      active,
      suspended,
      revoked,
    };
  }, [servers]);

  const copyText = async (value, label) => {
    if (!value) return;
    try {
      await navigator.clipboard.writeText(value);
      showSuccess(`${label} copied.`);
    } catch {
      showError(`Could not copy ${label.toLowerCase()}.`);
    }
  };

  const refreshAll = async () => {
    await Promise.all([
      loadServers(),
      refreshSubscriptionState({ silent: true }),
    ]);
  };

  const beginPairingSetup = () => {
    setRotatedCredential(null);
    navigate("/admin/cbt/setup-server");
  };

  const closeConfirmDialog = () => {
    setConfirmState(null);
    setRevocationReason("");
  };

  const runServerAction = async (action, confirmationLiteral) => {
    if (!confirmState?.serverId) return;
    setBusyAction(`${action}:${confirmState.serverId}`);
    try {
      if (action === "suspend")
        await cbtService.suspendServer(confirmState.serverId);
      if (action === "reactivate")
        await cbtService.reactivateServer(confirmState.serverId);
      if (action === "revoke") {
        await cbtService.revokeServer(confirmState.serverId, {
          reason: revocationReason.trim(),
          confirmation_literal: confirmationLiteral,
        });
      }
      closeConfirmDialog();
      setRotatedCredential(null);
      await refreshAll();
      showSuccess(
        `Server ${action === "reactivate" ? "reactivated" : action === "revoke" ? "revoked" : "suspended"} successfully.`,
      );
    } catch (requestError) {
      showError(
        parseApiError(requestError, `Could not ${action} server.`).message,
      );
    } finally {
      setBusyAction("");
    }
  };

  const rotateCredential = async (serverId) => {
    setBusyAction(`rotate:${serverId}`);
    try {
      const response = await cbtService.rotateCredential(serverId);
      setRotatedCredential(response);
      await loadServers();
      showSuccess("Server credential rotated.");
    } catch (requestError) {
      showError(
        parseApiError(requestError, "Could not rotate server credential.")
          .message,
      );
    } finally {
      setBusyAction("");
    }
  };

  if (loading) {
    return (
      <DashboardLayout role="admin" title="CBT Servers">
        <LoadingState label="Loading CBT servers..." />
      </DashboardLayout>
    );
  }

  if (featureGuard.pending) {
    return (
      <DashboardLayout role="admin" title="CBT Servers">
        <LoadingState label="Confirming CBT access..." />
      </DashboardLayout>
    );
  }

  const usage = resourceGuard.usage;
  const selectedStatusMeta = statusMetaFor(selectedServer?.status);

  return (
    <DashboardLayout role="admin">
      <div className="space-y-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <h1 className="text-[1.65rem] font-semibold tracking-tight text-text">
              CBT Servers
            </h1>
            <p className="mt-1 text-sm text-text-muted">
              Manage and monitor CBT examination servers
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              className="justify-center rounded-lg"
              onClick={() => navigate("/admin/cbt/results")}
            >
              <ClipboardCheck className="h-4 w-4" />
              Result Ledger
            </Button>
            <Button
              onClick={beginPairingSetup}
              disabled={
                Boolean(busyAction) ||
                !featureGuard.allowed ||
                resourceGuard.allowed === false
              }
              className="min-w-[180px] justify-center rounded-lg"
            >
              <Plus className="h-4 w-4" />
              Pair Server
            </Button>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
          <StatCard
            icon={Server}
            label="Total Servers"
            value={String(stats.total)}
            hint="All registered servers"
            iconClassName="bg-violet-50 text-violet-600"
          />
          <StatCard
            icon={CheckCircle2}
            label="Active"
            value={String(stats.active)}
            hint="Currently active"
            iconClassName="bg-emerald-50 text-emerald-600"
          />
          <StatCard
            icon={PauseCircle}
            label="Suspended"
            value={String(stats.suspended)}
            hint="Temporarily suspended"
            iconClassName="bg-amber-50 text-amber-600"
          />
          <StatCard
            icon={ShieldX}
            label="Revoked"
            value={String(stats.revoked)}
            hint="Permanently revoked"
            iconClassName="bg-rose-50 text-rose-600"
          />
        </div>

        {error ? (
          <div className="rounded-2xl border border-warning/30 bg-warning-soft px-4 py-3 text-sm font-medium text-amber-700">
            {error}
          </div>
        ) : null}

        {!featureGuard.allowed ? (
          <div className="flex flex-col gap-3 rounded-2xl border border-warning/30 bg-warning-soft px-4 py-4 text-sm text-amber-800 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="font-semibold">Historical CBT access is limited on this plan.</p>
              <p className="mt-1 text-xs leading-5">
                Existing servers and result evidence remain available. Upgrade to Professional or Enterprise to pair or reactivate servers.
              </p>
            </div>
            <Link to="/admin/billing/plans" className="shrink-0">
              <Button size="sm" variant="outline">View plans</Button>
            </Link>
          </div>
        ) : null}

        {featureGuard.allowed && resourceGuard.allowed === false ? (
          <div className="rounded-2xl border border-warning/30 bg-warning-soft px-4 py-3 text-sm text-amber-700">
            {resourceGuard.reason ||
              "This plan cannot pair another CBT server right now."}
          </div>
        ) : null}

        <section>
          <Card className="overflow-visible rounded-none border-0 bg-transparent p-0 shadow-none lg:overflow-hidden lg:rounded-xl lg:border lg:border-border/80 lg:bg-surface lg:shadow-sm">
            <div className="mb-3 rounded-xl border border-border/80 bg-surface px-4 py-5 shadow-sm lg:mb-0 lg:rounded-none lg:border-x-0 lg:border-t-0 lg:border-b lg:shadow-none sm:px-5">
              <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                <label className="flex h-11 w-full items-center gap-3 rounded-xl border border-border/80 bg-surface px-4 lg:max-w-[260px]">
                  <Search className="h-4 w-4 text-text-faint" />
                  <input
                    value={searchTerm}
                    onChange={(event) => setSearchTerm(event.target.value)}
                    placeholder="Search servers..."
                    className="w-full bg-transparent text-sm outline-none placeholder:text-text-faint"
                  />
                </label>
                <div className="grid grid-cols-2 gap-3 sm:flex">
                  <ToolbarDropdown
                    value={statusFilter}
                    onChange={setStatusFilter}
                    options={[
                      { value: "all", label: "All Statuses" },
                      { value: "active", label: "Active" },
                      { value: "suspended", label: "Suspended" },
                      { value: "revoked", label: "Revoked" },
                    ]}
                    className="sm:min-w-[190px]"
                  />
                  <ToolbarDropdown
                    value={sortBy}
                    onChange={setSortBy}
                    options={Object.entries(SORT_OPTIONS).map(
                      ([value, label]) => ({
                        value,
                        label: `Sort by: ${label}`,
                      }),
                    )}
                    className="sm:min-w-[190px]"
                  />
                  <Button
                    variant="outline"
                    size="icon"
                    onClick={refreshAll}
                    disabled={Boolean(busyAction)}
                    aria-label="Refresh servers"
                  >
                    <RefreshCw className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            </div>

            {filteredServers.length === 0 ? (
              <div className="p-6">
                <EmptyState
                  icon={Cpu}
                  title="No CBT servers found"
                  description={
                    servers.length === 0
                      ? "Use Pair Server to download and install WEAVE CBT, then generate a pairing code when the local Manager is ready."
                      : "Adjust the search or filters to see more paired servers."
                  }
                />
              </div>
            ) : (
              <>
                <div className="hidden border-b border-border/60 px-5 py-3 text-xs font-semibold text-text-muted lg:grid lg:grid-cols-[2.1fr_1.2fr_1.4fr_1.2fr_0.9fr_0.8fr] lg:gap-4">
                  <span>Server Name</span>
                  <span className="text-center">Status</span>
                  <span>Last Seen</span>
                  <span>Paired At</span>
                  <span>Version</span>
                  <span>Actions</span>
                </div>

                <div className="-mx-1 grid gap-3 lg:mx-0 lg:hidden">
                  {filteredServers.map((server) => {
                    const statusMeta = statusMetaFor(server.status);
                    return (
                      <button
                        key={server.id}
                        type="button"
                        onClick={() => {
                          setSelectedServerId(server.id);
                          setServerModalOpen(true);
                        }}
                        className="w-full rounded-xl border border-border/80 bg-surface px-4 py-3 text-left shadow-sm transition hover:border-primary/30 hover:bg-primary-subtle/35 focus:outline-none focus:ring-4 focus:ring-primary/10"
                      >
                        <div className="flex items-center justify-between gap-3">
                          <div className="flex min-w-0 items-center gap-3">
                            <div className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-primary-subtle text-primary">
                              <Server className="h-4 w-4" />
                            </div>
                            <div className="min-w-0">
                              <p className="truncate text-sm font-semibold text-text">
                                {server.name}
                              </p>
                              <p className="mt-0.5 text-xs text-text-muted">
                                {server.client_version || "LAB"}-
                                {String(server.id).slice(0, 4).toUpperCase()}
                              </p>
                            </div>
                          </div>
                          <span
                            className={`h-3.5 w-3.5 shrink-0 rounded-full ${statusMeta.dotClassName} ring-4 ${statusMeta.haloClassName}`}
                            aria-label={statusMeta.label}
                            title={statusMeta.label}
                          />
                        </div>
                        <div className="mt-2 flex items-center justify-between gap-3 pl-[3.25rem] text-xs text-text-muted">
                          <span className="truncate">
                            Last seen {formatRelativeTime(server.last_seen_at)}
                            {server.last_ip_address
                              ? ` - ${server.last_ip_address}`
                              : ""}
                          </span>
                          <span className="inline-flex shrink-0 items-center gap-1 font-semibold text-primary">
                            Details <Eye className="h-3.5 w-3.5" />
                          </span>
                        </div>
                      </button>
                    );
                  })}
                </div>

                <div className="hidden divide-y divide-border/50 lg:block">
                  {filteredServers.map((server) => {
                    const statusMeta = statusMetaFor(server.status);
                    const selected =
                      String(selectedServerId) === String(server.id);
                    const detailsHidden = Boolean(
                      hiddenServerDetails[server.id],
                    );
                    return (
                      <div
                        key={server.id}
                        onClick={(event) => {
                          if (event.target.closest("[data-server-actions]"))
                            return;
                          setSelectedServerId(server.id);
                          setServerModalOpen(true);
                        }}
                        className={`w-full cursor-pointer px-4 py-3 text-left transition hover:bg-primary-subtle/45 sm:px-5 ${
                          selected ? "bg-primary-subtle/70" : "bg-surface"
                        }`}
                      >
                        <div className="flex flex-col gap-4 lg:grid lg:grid-cols-[2.1fr_1.2fr_1.4fr_1.2fr_0.9fr_0.8fr] lg:items-center lg:gap-4">
                          <div className="flex min-w-0 items-center gap-3">
                            <div className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-primary-subtle text-primary">
                              <Server className="h-5 w-5" />
                            </div>
                            <div className="min-w-0">
                              <div className="truncate text-sm font-semibold text-text">
                                {server.name}
                              </div>
                              <div className="mt-0.5 text-xs text-text-muted">
                                {server.client_version || "LAB"}-
                                {String(server.id).slice(0, 4).toUpperCase()}
                              </div>
                            </div>
                          </div>

                          <div className="flex justify-center">
                            <span
                              className={`block h-3.5 w-3.5 rounded-full ${statusMeta.dotClassName} ring-4 ${statusMeta.haloClassName}`}
                              aria-label={statusMeta.label}
                              title={statusMeta.label}
                            />
                          </div>

                          <div
                            className={`text-sm text-text ${detailsHidden ? "invisible" : ""}`}
                          >
                            <div>{formatRelativeTime(server.last_seen_at)}</div>
                            <div className="mt-1 text-xs text-text-muted">
                              {server.last_ip_address || "--"}
                            </div>
                          </div>

                          <div
                            className={`text-sm text-text ${detailsHidden ? "invisible" : ""}`}
                          >
                            <div>{formatDate(server.paired_at)}</div>
                            <div className="mt-1 text-xs text-text-muted">
                              {formatTime(server.paired_at)}
                            </div>
                          </div>

                          <div
                            className={`text-sm font-medium text-text ${detailsHidden ? "invisible" : ""}`}
                          >
                            {server.client_version || "1.0.0"}
                          </div>

                          <div
                            data-server-actions
                            className="flex items-center gap-2"
                          >
                            <Button
                              variant="outline"
                              size="icon"
                              onClick={(event) => {
                                event.stopPropagation();
                                setHiddenServerDetails((current) => ({
                                  ...current,
                                  [server.id]: !current[server.id],
                                }));
                              }}
                              aria-label={`${detailsHidden ? "Show" : "Hide"} inline details for ${server.name}`}
                              aria-pressed={detailsHidden}
                            >
                              {detailsHidden ? (
                                <EyeOff className="h-4 w-4" />
                              ) : (
                                <Eye className="h-4 w-4" />
                              )}
                            </Button>
                            <Dropdown
                              open={actionMenuServerId === server.id}
                              onOpenChange={(open) =>
                                setActionMenuServerId(open ? server.id : "")
                              }
                              className="min-w-52"
                              trigger={
                                <Button
                                  variant="outline"
                                  size="icon"
                                  aria-label={`Manage ${server.name}`}
                                >
                                  <MoreVertical className="h-4 w-4" />
                                </Button>
                              }
                            >
                              <p className="px-3 py-2 text-xs font-semibold uppercase tracking-[0.1em] text-text-faint">
                                Lifecycle actions
                              </p>
                              {String(server.status).toLowerCase() ===
                              "active" ? (
                                <button
                                  type="button"
                                  className="flex w-full items-center gap-2 rounded-xl px-3 py-2.5 text-left text-sm font-semibold text-text transition hover:bg-warning-soft hover:text-amber-800"
                                  onClick={() => {
                                    setActionMenuServerId("");
                                    setConfirmState({
                                      action: "suspend",
                                      serverId: server.id,
                                      title: "Suspend this CBT server?",
                                      description:
                                        "The server will remain registered but should stop normal activity until reactivated.",
                                      confirmLabel: "Suspend server",
                                    });
                                  }}
                                >
                                  <PauseCircle className="h-4 w-4" />
                                  Suspend server
                                </button>
                              ) : null}
                              {featureGuard.allowed &&
                              String(server.status).toLowerCase() ===
                                "suspended" ? (
                                <button
                                  type="button"
                                  className="flex w-full items-center gap-2 rounded-xl px-3 py-2.5 text-left text-sm font-semibold text-text transition hover:bg-success-soft"
                                  onClick={() => {
                                    setActionMenuServerId("");
                                    setConfirmState({
                                      action: "reactivate",
                                      serverId: server.id,
                                      title: "Reactivate this CBT server?",
                                      description:
                                        "The server will be allowed to resume normal use immediately.",
                                      confirmLabel: "Reactivate server",
                                    });
                                  }}
                                >
                                  <CheckCircle2 className="h-4 w-4" />
                                  Reactivate server
                                </button>
                              ) : null}
                              {String(server.status).toLowerCase() !==
                              "revoked" ? (
                                <>
                                  {CREDENTIAL_ROTATION_AVAILABLE && featureGuard.allowed ? (
                                    <button
                                      type="button"
                                      className="flex w-full items-center gap-2 rounded-xl px-3 py-2.5 text-left text-sm font-semibold text-text transition hover:bg-primary-subtle"
                                      onClick={() => {
                                        setActionMenuServerId("");
                                        rotateCredential(server.id);
                                      }}
                                    >
                                      <RotateCcw className="h-4 w-4" />
                                      Rotate credential
                                    </button>
                                  ) : null}
                                  <button
                                    type="button"
                                    className="flex w-full items-center gap-2 rounded-xl px-3 py-2.5 text-left text-sm font-semibold text-error transition hover:bg-error-soft"
                                    onClick={() => {
                                      setActionMenuServerId("");
                                      setConfirmState({
                                        action: "revoke",
                                        serverId: server.id,
                                        title: "Revoke this CBT server?",
                                        description:
                                          "This revokes the server and invalidates its active credential. Pair it again if it needs to reconnect later.",
                                        confirmLabel: "Revoke server",
                                      });
                                    }}
                                  >
                                    <ShieldAlert className="h-4 w-4" />
                                    Revoke server
                                  </button>
                                </>
                              ) : (
                                <p className="px-3 py-2 text-sm text-text-muted">
                                  No actions available.
                                </p>
                              )}
                            </Dropdown>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>

                <div className="flex flex-col gap-3 border-t border-border/60 px-5 py-4 text-sm text-text-muted sm:flex-row sm:items-center sm:justify-between sm:px-6">
                  <p>
                    Showing 1 to {filteredServers.length} of {servers.length}{" "}
                    servers
                  </p>
                  <div
                    className="hidden shrink-0 items-center gap-2 sm:flex"
                    aria-label="Server pagination"
                  >
                    <button
                      type="button"
                      className="grid h-9 w-9 shrink-0 place-items-center rounded-xl border border-border/70 bg-surface-muted/40 text-text-faint"
                      aria-label="Previous page"
                      disabled
                    >
                      <ChevronDown className="h-4 w-4 rotate-90" />
                    </button>
                    <button
                      type="button"
                      className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-primary text-sm font-semibold text-primary-foreground"
                      aria-current="page"
                      disabled
                    >
                      1
                    </button>
                    <button
                      type="button"
                      className="grid h-9 w-9 shrink-0 place-items-center rounded-xl border border-border/70 bg-surface text-sm font-medium text-text"
                      disabled
                    >
                      2
                    </button>
                    <button
                      type="button"
                      className="grid h-9 w-9 shrink-0 place-items-center rounded-xl border border-border/70 bg-surface text-text"
                      aria-label="Next page"
                      disabled
                    >
                      <ChevronDown className="h-4 w-4 -rotate-90" />
                    </button>
                  </div>
                </div>
              </>
            )}
          </Card>

          <Modal
            open={serverModalOpen}
            title="Server Details"
            description="Review this CBT server and manage its access."
            onClose={() => {
              setServerModalOpen(false);
              setSelectedServerId("");
            }}
            className="max-w-xl"
          >
            {!selectedServer ? (
              <EmptyState
                title="No server selected"
                description="Select a server from the list to inspect its current details and actions."
              />
            ) : (
              <div className="space-y-5">
                <div>
                  <span
                    className={`inline-flex items-center gap-2 rounded-full px-3 py-1 text-sm font-medium ${selectedStatusMeta.tintClassName}`}
                  >
                    <span
                      className={`h-2.5 w-2.5 rounded-full ${selectedStatusMeta.dotClassName}`}
                    />
                    {selectedStatusMeta.label}
                  </span>
                </div>

                <div className="mx-auto grid h-20 w-20 place-items-center rounded-full bg-primary-subtle text-primary">
                  <Server className="h-10 w-10" />
                </div>

                <div className="text-center">
                  <h3 className="text-[1.9rem] font-semibold leading-tight text-text">
                    {selectedServer.name}
                  </h3>
                  <p className="mt-2 text-lg text-text-muted">
                    {selectedServer.client_version ||
                      `LAB-${String(selectedServer.id).slice(0, 4).toUpperCase()}`}
                  </p>
                </div>

                <div className="space-y-4 text-sm">
                  <div className="flex items-start gap-3">
                    <AlertCircle className="mt-0.5 h-4 w-4 text-text-faint" />
                    <div>
                      <p className="text-text-faint">Server ID</p>
                      <div className="mt-1 flex items-center gap-2 break-all font-medium text-text">
                        <span>{selectedServer.id}</span>
                        <button
                          type="button"
                          onClick={() =>
                            copyText(selectedServer.id, "Server ID")
                          }
                          className="text-text-faint transition hover:text-text"
                          aria-label="Copy server ID"
                        >
                          <Copy className="h-4 w-4" />
                        </button>
                      </div>
                    </div>
                  </div>

                  <div className="flex items-start gap-3">
                    <AlertCircle className="mt-0.5 h-4 w-4 text-text-faint" />
                    <div>
                      <p className="text-text-faint">Paired At</p>
                      <p className="mt-1 font-medium text-text">
                        {formatDateTime(selectedServer.paired_at)}
                      </p>
                    </div>
                  </div>

                  <div className="flex items-start gap-3">
                    <AlertCircle className="mt-0.5 h-4 w-4 text-text-faint" />
                    <div>
                      <p className="text-text-faint">Paired By</p>
                      <p className="mt-1 font-medium text-text">
                        {selectedServer.paired_by_admin_id
                          ? "Admin User"
                          : "--"}
                      </p>
                    </div>
                  </div>

                  <div className="flex items-start gap-3">
                    <AlertCircle className="mt-0.5 h-4 w-4 text-text-faint" />
                    <div>
                      <p className="text-text-faint">Last Seen</p>
                      <p className="mt-1 font-medium text-text">
                        {formatRelativeTime(selectedServer.last_seen_at)}
                      </p>
                      <p className="mt-1 text-text-muted">
                        {selectedServer.last_ip_address || "--"}
                      </p>
                    </div>
                  </div>

                  <div className="flex items-start gap-3">
                    <AlertCircle className="mt-0.5 h-4 w-4 text-text-faint" />
                    <div>
                      <p className="text-text-faint">Client Version</p>
                      <p className="mt-1 font-medium text-text">
                        {selectedServer.client_version || "1.0.0"}
                      </p>
                    </div>
                  </div>

                  <div className="flex items-start gap-3">
                    <AlertCircle className="mt-0.5 h-4 w-4 text-text-faint" />
                    <div>
                      <p className="text-text-faint">Status</p>
                      <p className="mt-1 font-medium text-text">
                        {selectedStatusMeta.label}
                      </p>
                    </div>
                  </div>
                </div>

                <div className="space-y-3 pt-2">
                  {String(selectedServer.status).toLowerCase() === "active" ? (
                    <Button
                      variant="outline"
                      className="w-full justify-center rounded-xl"
                      onClick={() =>
                        setConfirmState({
                          action: "suspend",
                          serverId: selectedServer.id,
                          title: "Suspend this CBT server?",
                          description:
                            "The server will remain registered but should stop normal activity until reactivated.",
                          confirmLabel: "Suspend server",
                        })
                      }
                    >
                      <PauseCircle className="h-4 w-4" />
                      Suspend Server
                    </Button>
                  ) : null}

                  {featureGuard.allowed &&
                  String(selectedServer.status).toLowerCase() ===
                    "suspended" ? (
                    <Button
                      variant="outline"
                      className="w-full justify-center rounded-xl"
                      onClick={() =>
                        setConfirmState({
                          action: "reactivate",
                          serverId: selectedServer.id,
                          title: "Reactivate this CBT server?",
                          description:
                            "The server will be allowed to resume normal use immediately.",
                          confirmLabel: "Reactivate server",
                        })
                      }
                    >
                      <CheckCircle2 className="h-4 w-4" />
                      Reactivate Server
                    </Button>
                  ) : null}

                  {String(selectedServer.status).toLowerCase() !== "revoked" ? (
                    <>
                      {CREDENTIAL_ROTATION_AVAILABLE && featureGuard.allowed ? (
                        <Button
                          variant="outline"
                          className="w-full justify-center rounded-xl"
                          onClick={() => rotateCredential(selectedServer.id)}
                          disabled={busyAction === `rotate:${selectedServer.id}`}
                        >
                          <RotateCcw className="h-4 w-4" />
                          Rotate Credential
                        </Button>
                      ) : null}

                      <Button
                        variant="danger"
                        className="w-full justify-center rounded-xl"
                        onClick={() =>
                          setConfirmState({
                            action: "revoke",
                            serverId: selectedServer.id,
                            title: "Revoke this CBT server?",
                            description:
                              "This revokes the server and invalidates its active credential. Pair it again if it needs to reconnect later.",
                            confirmLabel: "Revoke server",
                          })
                        }
                      >
                        <ShieldAlert className="h-4 w-4" />
                        Revoke Server
                      </Button>
                    </>
                  ) : null}
                </div>

                {rotatedCredential?.server_id === selectedServer.id ? (
                  <div className="rounded-2xl border border-success/25 bg-success/10 px-4 py-4">
                    <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-success">
                      New Credential
                    </p>
                    <div className="mt-2 flex items-center gap-2">
                      <code className="max-w-full overflow-x-auto rounded-xl bg-surface px-3 py-2 text-sm font-semibold text-text">
                        {rotatedCredential.server_credential}
                      </code>
                      <Button
                        variant="outline"
                        size="icon"
                        onClick={() =>
                          copyText(
                            rotatedCredential.server_credential,
                            "Server credential",
                          )
                        }
                      >
                        <Copy className="h-4 w-4" />
                      </Button>
                    </div>
                    <p className="mt-3 text-xs text-text-muted">
                      Rotated {formatDateTime(rotatedCredential.rotated_at)}.
                      Store this on the local server now because it will not be
                      shown again.
                    </p>
                  </div>
                ) : null}

                <div className="rounded-2xl border border-border/60 bg-surface-muted/25 px-4 py-3 text-xs text-text-muted">
                  Plan: {formatPlanName(planCode)}. Limit{" "}
                  {usage?.is_unlimited
                    ? "Unlimited"
                    : `${usage?.limit ?? 0} servers`}
                  .
                </div>
              </div>
            )}
          </Modal>
        </section>
      </div>

      <ConfirmDialog
        open={Boolean(confirmState) && confirmState?.action !== "revoke"}
        title={confirmState?.title}
        description={confirmState?.description}
        confirmLabel={confirmState?.confirmLabel}
        onCancel={closeConfirmDialog}
        onConfirm={() => runServerAction(confirmState?.action)}
        isLoading={Boolean(
          confirmState &&
          busyAction === `${confirmState.action}:${confirmState.serverId}`,
        )}
        variant={confirmState?.action === "revoke" ? "danger" : "primary"}
      />
      <TypedConfirmationDialog
        open={Boolean(confirmState) && confirmState?.action === "revoke"}
        title={confirmState?.title}
        description={confirmState?.description}
        confirmationText={REVOKE_CONFIRMATION_LITERAL}
        confirmLabel={confirmState?.confirmLabel}
        variant="danger"
        isLoading={Boolean(
          confirmState &&
          busyAction === `${confirmState.action}:${confirmState.serverId}`,
        )}
        confirmDisabled={revocationReason.trim().length < 3}
        onCancel={closeConfirmDialog}
        onConfirm={(confirmationLiteral) =>
          runServerAction("revoke", confirmationLiteral)
        }
      >
        <Input
          label="Reason for revocation"
          value={revocationReason}
          onChange={(event) => setRevocationReason(event.target.value)}
          placeholder="Explain why this server is being revoked"
          minLength={3}
          maxLength={1000}
          required
        />
      </TypedConfirmationDialog>
    </DashboardLayout>
  );
}
