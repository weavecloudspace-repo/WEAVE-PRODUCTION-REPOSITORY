import { useCallback, useEffect, useMemo, useState } from "react";
import {
  BriefcaseBusiness,
  BookOpenCheck,
  Check,
  ChevronLeft,
  ChevronRight,
  MailPlus,
  MoreHorizontal,
  Pencil,
  Search,
  ShieldCheck,
  UserRound,
  Users,
  X,
} from "lucide-react";
import { Link } from "react-router-dom";

import DashboardLayout from "../../components/layout/DashboardLayout";
import {
  DirectorySummary,
  DirectoryTable,
  MobileDirectoryList,
  MobilePersonCard,
  PersonIdentity,
} from "../../components/people/PeopleDirectory";
import EmptyState from "../../components/shared/EmptyState";
import LoadingState from "../../components/shared/LoadingState";
import Badge from "../../components/ui/Badge";
import Button from "../../components/ui/Button";
import Card from "../../components/ui/Card";
import Dropdown from "../../components/ui/Dropdown";
import Input from "../../components/ui/Input";
import Modal from "../../components/ui/Modal";
import { useToast } from "../../hooks/useToast";
import { api, getErrorMessage, parseApiError } from "../../services/api";
import { parentService } from "../../services/parentService";
import { teacherService } from "../../services/teacherService";
import { getAvatarSrcFromRecord } from "../../utils/user";

const PAGE_SIZE = 24;
const INVITATION_STATUSES = ["pending", "accepted", "revoked", "expired"];

const ROLE_CONFIG = {
  teacher: {
    title: "Teacher Directory",
    description:
      "Manage teacher employment, approved subjects, invitations, and tenant-specific access.",
    membershipLabel: "Teacher memberships",
    inviteLabel: "Invite teacher",
    service: teacherService,
    accountKey: "teacher_account",
    membershipStatuses: ["active", "suspended", "inactive"],
  },
  parent: {
    title: "Parent Directory",
    description:
      "Manage parent memberships, invitation requests, and access without deleting global accounts.",
    membershipLabel: "Parent memberships",
    inviteLabel: "Invite parent",
    service: parentService,
    accountKey: "parent_account",
    membershipStatuses: ["active", "read_only", "inactive"],
  },
};

const asItems = (response) =>
  Array.isArray(response)
    ? response
    : Array.isArray(response?.items)
      ? response.items
      : [];

const defaultStatusForTab = (tabId) => {
  if (tabId === "memberships") return "active";
  if (tabId === "invitations") return "pending";
  return "";
};

const displayName = (account) => {
  const name = [account?.first_name, account?.last_name]
    .filter(Boolean)
    .join(" ")
    .trim();
  return name || account?.email || "Account";
};

const titleCase = (value) =>
  String(value || "")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());

const badgeVariant = (status) => {
  const value = String(status || "").toLowerCase();
  if (["active", "accepted", "approved"].includes(value)) return "success";
  if (["pending", "read_only"].includes(value)) return "warning";
  if (
    ["inactive", "suspended", "revoked", "expired", "rejected"].includes(value)
  )
    return "error";
  return "default";
};

function TeacherMembershipActions({
  membership,
  status,
  busy,
  onEdit,
  onCapabilities,
  onLifecycle,
}) {
  const [menuOpen, setMenuOpen] = useState(false);

  const runAction = (action) => {
    setMenuOpen(false);
    onLifecycle(membership, action);
  };

  return (
    <div className="flex items-center justify-end gap-2">
      <Button
        type="button"
        size="small"
        variant="outline"
        disabled={busy}
        onClick={() => onEdit(membership)}
      >
        <Pencil className="h-3.5 w-3.5" />
        Edit
      </Button>
      <Dropdown
        open={menuOpen}
        onOpenChange={setMenuOpen}
        align="right"
        strategy="fixed"
        className="w-56"
        trigger={
          <Button
            type="button"
            size="icon"
            variant="outline"
            disabled={busy}
            className="h-9 w-9 min-h-9 rounded-lg"
            aria-label="More teacher actions"
          >
            <MoreHorizontal className="h-4 w-4" />
          </Button>
        }
      >
        <div className="grid gap-1">
          <button
            type="button"
            className="flex min-h-10 items-center gap-2 rounded-xl px-3 py-2 text-left text-sm font-semibold text-text-soft transition hover:bg-surface-muted"
            onClick={() => {
              setMenuOpen(false);
              onCapabilities(membership);
            }}
          >
            <BookOpenCheck className="h-4 w-4" />
            Approved subjects
          </button>
          {status === "active" ? (
            <button
              type="button"
              className="min-h-10 rounded-xl px-3 py-2 text-left text-sm font-semibold text-text-soft transition hover:bg-surface-muted"
              onClick={() => runAction("suspend")}
            >
              Suspend membership
            </button>
          ) : null}
          {["inactive", "suspended"].includes(status) ? (
            <button
              type="button"
              className="min-h-10 rounded-xl px-3 py-2 text-left text-sm font-semibold text-success transition hover:bg-success-soft"
              onClick={() => runAction("reactivate")}
            >
              Reactivate membership
            </button>
          ) : null}
          {["active", "suspended"].includes(status) ? (
            <button
              type="button"
              className="min-h-10 rounded-xl px-3 py-2 text-left text-sm font-semibold text-error transition hover:bg-error-soft"
              onClick={() => runAction("end")}
            >
              End membership
            </button>
          ) : null}
        </div>
      </Dropdown>
    </div>
  );
}

function TeacherMembershipList({
  items,
  actionId,
  onEdit,
  onCapabilities,
  onLifecycle,
}) {
  return (
    <>
      <DirectoryTable
        label="Teacher directory"
        columns={[
          { key: "teacher", label: "Teacher" },
          { key: "staff", label: "Employment" },
          { key: "department", label: "Department" },
          { key: "status", label: "Status" },
          { key: "actions", label: "Actions", className: "text-right" },
        ]}
      >
        {items.map((membership) => {
          const account = membership.teacher_account || {};
          const status = String(membership.status || "unknown").toLowerCase();
          const busy = actionId === membership.id;
          return (
            <tr key={membership.id} className="transition hover:bg-surface-muted/25">
              <td className="px-4 py-3.5 align-middle">
                <PersonIdentity
                  name={displayName(account)}
                  meta={account.email || "No email"}
                  avatarSrc={getAvatarSrcFromRecord(account)}
                />
              </td>
              <td className="px-4 py-3.5 align-middle">
                <p className="text-sm font-medium text-text-soft">
                  {membership.job_title || "Role not provided"}
                </p>
                <p className="mt-0.5 text-xs text-text-muted">
                  {membership.staff_id || "No staff ID"}
                </p>
              </td>
              <td className="px-4 py-3.5 align-middle text-sm text-text-soft">
                {membership.department || "Not provided"}
              </td>
              <td className="px-4 py-3.5 align-middle">
                <Badge variant={badgeVariant(status)}>{titleCase(status)}</Badge>
              </td>
              <td className="px-4 py-3.5 align-middle">
                <TeacherMembershipActions
                  membership={membership}
                  status={status}
                  busy={busy}
                  onEdit={onEdit}
                  onCapabilities={onCapabilities}
                  onLifecycle={onLifecycle}
                />
              </td>
            </tr>
          );
        })}
      </DirectoryTable>

      <MobileDirectoryList label="Teacher directory">
        {items.map((membership) => {
          const account = membership.teacher_account || {};
          const status = String(membership.status || "unknown").toLowerCase();
          return (
            <MobilePersonCard
              key={membership.id}
              tone={
                status === "active"
                  ? "success"
                  : status === "suspended"
                    ? "warning"
                    : "error"
              }
            >
              <div className="flex items-start justify-between gap-3">
                <PersonIdentity
                  name={displayName(account)}
                  meta={account.email || "No email"}
                  avatarSrc={getAvatarSrcFromRecord(account)}
                />
                <Badge variant={badgeVariant(status)}>{titleCase(status)}</Badge>
              </div>
              <dl className="mt-4 grid grid-cols-2 gap-3 rounded-xl bg-surface-muted/35 px-3 py-3 text-sm">
                <div>
                  <dt className="text-xs font-semibold uppercase text-text-muted">Role</dt>
                  <dd className="mt-1 text-text-soft">
                    {membership.job_title || "Not provided"}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs font-semibold uppercase text-text-muted">Staff ID</dt>
                  <dd className="mt-1 text-text-soft">
                    {membership.staff_id || "Not assigned"}
                  </dd>
                </div>
                <div className="col-span-2">
                  <dt className="text-xs font-semibold uppercase text-text-muted">Department</dt>
                  <dd className="mt-1 text-text-soft">
                    {membership.department || "Not provided"}
                  </dd>
                </div>
              </dl>
              <div className="mt-4 border-t border-border/70 pt-3">
                <TeacherMembershipActions
                  membership={membership}
                  status={status}
                  busy={actionId === membership.id}
                  onEdit={onEdit}
                  onCapabilities={onCapabilities}
                  onLifecycle={onLifecycle}
                />
              </div>
            </MobilePersonCard>
          );
        })}
      </MobileDirectoryList>
    </>
  );
}

const parentAccessLabel = (status) => {
  if (status === "active") return "Active child links";
  if (status === "read_only") return "Historical records only";
  return "No active access";
};

function ParentMembershipActions({ membership, status, busy, onLifecycle }) {
  if (status === "inactive") {
    return (
      <Button
        type="button"
        size="small"
        variant="success"
        disabled={busy}
        onClick={() => onLifecycle(membership, "reactivate")}
      >
        Reactivate
      </Button>
    );
  }

  if (["active", "read_only"].includes(status)) {
    return (
      <Button
        type="button"
        size="small"
        variant="outline"
        disabled={busy}
        onClick={() => onLifecycle(membership, "end")}
        className="text-error hover:bg-error-soft hover:text-error"
      >
        End access
      </Button>
    );
  }

  return null;
}

function ParentMembershipList({ items, actionId, onLifecycle }) {
  return (
    <>
      <DirectoryTable
        label="Parent directory"
        columns={[
          { key: "parent", label: "Parent" },
          { key: "access", label: "School access" },
          { key: "joined", label: "Joined" },
          { key: "status", label: "Status" },
          { key: "actions", label: "Actions", className: "text-right" },
        ]}
      >
        {items.map((membership) => {
          const account = membership.parent_account || {};
          const status = String(membership.status || "unknown").toLowerCase();
          return (
            <tr key={membership.id} className="transition hover:bg-surface-muted/25">
              <td className="px-4 py-3.5 align-middle">
                <PersonIdentity
                  name={displayName(account)}
                  meta={account.email || "No email"}
                  avatarSrc={getAvatarSrcFromRecord(account)}
                />
              </td>
              <td className="px-4 py-3.5 align-middle">
                <p className="text-sm font-medium text-text-soft">
                  {parentAccessLabel(status)}
                </p>
                <p className="mt-0.5 text-xs text-text-muted">
                  Membership is scoped to this school
                </p>
              </td>
              <td className="px-4 py-3.5 text-sm text-text-soft">
                {membership.joined_at
                  ? new Date(membership.joined_at).toLocaleDateString()
                  : "Unknown"}
              </td>
              <td className="px-4 py-3.5">
                <Badge variant={badgeVariant(status)}>{titleCase(status)}</Badge>
              </td>
              <td className="px-4 py-3.5 text-right">
                <ParentMembershipActions
                  membership={membership}
                  status={status}
                  busy={actionId === membership.id}
                  onLifecycle={onLifecycle}
                />
              </td>
            </tr>
          );
        })}
      </DirectoryTable>

      <MobileDirectoryList label="Parent directory">
        {items.map((membership) => {
          const account = membership.parent_account || {};
          const status = String(membership.status || "unknown").toLowerCase();
          return (
            <MobilePersonCard
              key={membership.id}
              tone={
                status === "active"
                  ? "success"
                  : status === "read_only"
                    ? "warning"
                    : "error"
              }
            >
              <div className="flex items-start justify-between gap-3">
                <PersonIdentity
                  name={displayName(account)}
                  meta={account.email || "No email"}
                  avatarSrc={getAvatarSrcFromRecord(account)}
                />
                <Badge variant={badgeVariant(status)}>{titleCase(status)}</Badge>
              </div>
              <dl className="mt-4 grid grid-cols-2 gap-3 rounded-xl bg-surface-muted/35 px-3 py-3 text-sm">
                <div>
                  <dt className="text-xs font-semibold uppercase text-text-muted">
                    Access
                  </dt>
                  <dd className="mt-1 text-text-soft">
                    {parentAccessLabel(status)}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs font-semibold uppercase text-text-muted">
                    Joined
                  </dt>
                  <dd className="mt-1 text-text-soft">
                    {membership.joined_at
                      ? new Date(membership.joined_at).toLocaleDateString()
                      : "Unknown"}
                  </dd>
                </div>
              </dl>
              <div className="mt-4 flex justify-end border-t border-border/70 pt-3">
                <ParentMembershipActions
                  membership={membership}
                  status={status}
                  busy={actionId === membership.id}
                  onLifecycle={onLifecycle}
                />
              </div>
            </MobilePersonCard>
          );
        })}
      </MobileDirectoryList>
    </>
  );
}

function InvitationList({ items, actionId, onRevoke, role }) {
  return (
    <>
      <DirectoryTable
        label={`${titleCase(role)} invitations`}
        columns={[
          { key: "recipient", label: "Recipient" },
          { key: "details", label: "Invitation details" },
          { key: "expires", label: "Expires" },
          { key: "status", label: "Status" },
          { key: "actions", label: "Actions", className: "text-right" },
        ]}
      >
        {items.map((item) => {
          const status = String(item.status || "unknown").toLowerCase();
          return (
            <tr key={item.id} className="transition hover:bg-surface-muted/25">
              <td className="px-4 py-3.5 align-middle">
                <PersonIdentity
                  name={item.invited_email || "Parent invitation"}
                  meta={`Invited ${role} account`}
                />
              </td>
              <td className="px-4 py-3.5 text-sm text-text-soft">
                {role === "teacher"
                  ? item.job_title || item.department || "Teacher invitation"
                  : titleCase(item.relationship_type || "guardian")}
              </td>
              <td className="px-4 py-3.5 text-sm text-text-soft">
                {item.expires_at
                  ? new Date(item.expires_at).toLocaleDateString()
                  : "Not provided"}
              </td>
              <td className="px-4 py-3.5">
                <Badge variant={badgeVariant(status)}>{titleCase(status)}</Badge>
              </td>
              <td className="px-4 py-3.5 text-right">
                {status === "pending" ? (
                  <Button
                    type="button"
                    size="small"
                    variant="outline"
                    className="text-error hover:bg-error-soft hover:text-error"
                    disabled={actionId === item.id}
                    onClick={() => onRevoke(item)}
                  >
                    {actionId === item.id ? "Revoking..." : "Revoke"}
                  </Button>
                ) : (
                  <span className="text-xs text-text-muted">No actions</span>
                )}
              </td>
            </tr>
          );
        })}
      </DirectoryTable>

      <MobileDirectoryList label={`${titleCase(role)} invitations`}>
        {items.map((item) => {
          const status = String(item.status || "unknown").toLowerCase();
          return (
            <MobilePersonCard
              key={item.id}
              tone={
                status === "accepted"
                  ? "success"
                  : status === "pending"
                    ? "warning"
                    : "error"
              }
            >
              <div className="flex items-start justify-between gap-3">
                <PersonIdentity
                  name={item.invited_email || "Parent invitation"}
                  meta={
                    role === "teacher"
                      ? item.job_title || item.department || "Teacher invitation"
                      : titleCase(item.relationship_type || "guardian")
                  }
                />
                <Badge variant={badgeVariant(status)}>{titleCase(status)}</Badge>
              </div>
              <dl className="mt-4 rounded-xl bg-surface-muted/35 px-3 py-3 text-sm">
                <dt className="text-xs font-semibold uppercase text-text-muted">
                  Expires
                </dt>
                <dd className="mt-1 text-text-soft">
                  {item.expires_at
                    ? new Date(item.expires_at).toLocaleDateString()
                    : "Not provided"}
                </dd>
              </dl>
              {status === "pending" ? (
                <div className="mt-4 flex justify-end border-t border-border/70 pt-3">
                  <Button
                    type="button"
                    size="small"
                    variant="outline"
                    className="text-error hover:bg-error-soft hover:text-error"
                    disabled={actionId === item.id}
                    onClick={() => onRevoke(item)}
                  >
                    {actionId === item.id ? "Revoking..." : "Revoke"}
                  </Button>
                </div>
              ) : null}
            </MobilePersonCard>
          );
        })}
      </MobileDirectoryList>
    </>
  );
}

function ParentLinkRequestList({ items, actionId, onApprove, onReject }) {
  return (
    <>
      <DirectoryTable
        label="Pending parent link requests"
        columns={[
          { key: "student", label: "Student" },
          { key: "parent", label: "Parent" },
          { key: "relationship", label: "Relationship" },
          { key: "status", label: "Status" },
          { key: "actions", label: "Actions", className: "text-right" },
        ]}
      >
        {items.map((request) => (
          <tr key={request.id} className="transition hover:bg-surface-muted/25">
            <td className="px-4 py-3.5 align-middle">
              <PersonIdentity
                name={request.student_name || "Student"}
                meta={request.admission_number_snapshot || "No admission number"}
              />
            </td>
            <td className="px-4 py-3.5 text-sm text-text-soft">
              {request.parent_email || "Parent account"}
            </td>
            <td className="px-4 py-3.5 text-sm text-text-soft">
              {titleCase(request.relationship_type || "guardian")}
            </td>
            <td className="px-4 py-3.5">
              <Badge variant="warning">Pending</Badge>
            </td>
            <td className="px-4 py-3.5">
              <div className="flex items-center justify-end gap-2">
                <Button
                  type="button"
                  size="small"
                  disabled={actionId === request.id}
                  onClick={() => onApprove(request)}
                >
                  <Check className="h-4 w-4" />
                  Approve
                </Button>
                <Button
                  type="button"
                  size="small"
                  variant="outline"
                  disabled={actionId === request.id}
                  onClick={() => onReject(request)}
                >
                  <X className="h-4 w-4" />
                  Reject
                </Button>
              </div>
            </td>
          </tr>
        ))}
      </DirectoryTable>

      <MobileDirectoryList label="Pending parent link requests">
        {items.map((request) => (
          <MobilePersonCard
            key={request.id}
            tone="warning"
          >
            <div className="flex items-start justify-between gap-3">
              <PersonIdentity
                name={request.student_name || "Student"}
                meta={request.admission_number_snapshot || "No admission number"}
              />
              <Badge variant="warning">Pending</Badge>
            </div>
            <dl className="mt-4 grid gap-3 rounded-xl bg-surface-muted/35 px-3 py-3 text-sm sm:grid-cols-2">
              <div>
                <dt className="text-xs font-semibold uppercase text-text-muted">
                  Parent
                </dt>
                <dd className="mt-1 break-words text-text-soft">
                  {request.parent_email || "Parent account"}
                </dd>
              </div>
              <div>
                <dt className="text-xs font-semibold uppercase text-text-muted">
                  Relationship
                </dt>
                <dd className="mt-1 text-text-soft">
                  {titleCase(request.relationship_type || "guardian")}
                </dd>
              </div>
            </dl>
            <div className="mt-4 grid grid-cols-2 gap-2 border-t border-border/70 pt-3">
              <Button
                type="button"
                size="small"
                disabled={actionId === request.id}
                onClick={() => onApprove(request)}
              >
                <Check className="h-4 w-4" />
                Approve
              </Button>
              <Button
                type="button"
                size="small"
                variant="outline"
                disabled={actionId === request.id}
                onClick={() => onReject(request)}
              >
                <X className="h-4 w-4" />
                Reject
              </Button>
            </div>
          </MobilePersonCard>
        ))}
      </MobileDirectoryList>
    </>
  );
}

function MembershipDirectoryPage({ role }) {
  const config = ROLE_CONFIG[role] || ROLE_CONFIG.teacher;
  const availableTabs = useMemo(
    () => [
      { id: "memberships", label: config.membershipLabel },
      { id: "invitations", label: "Invitations" },
      ...(role === "parent"
        ? [{ id: "requests", label: "Pending link requests" }]
        : []),
    ],
    [config.membershipLabel, role],
  );
  const [activeTab, setActiveTab] = useState("memberships");
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [draftSearch, setDraftSearch] = useState("");
  const [appliedSearch, setAppliedSearch] = useState("");
  const [draftStatus, setDraftStatus] = useState(() =>
    defaultStatusForTab("memberships"),
  );
  const [appliedStatus, setAppliedStatus] = useState(() =>
    defaultStatusForTab("memberships"),
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [actionId, setActionId] = useState("");
  const [lifecycleState, setLifecycleState] = useState(null);
  const [editState, setEditState] = useState(null);
  const [capabilityState, setCapabilityState] = useState(null);
  const [requestDecision, setRequestDecision] = useState(null);
  const { showSuccess, showError, showWarning } = useToast();

  const statusOptions =
    activeTab === "memberships"
      ? config.membershipStatuses
      : activeTab === "invitations"
        ? INVITATION_STATUSES
        : [];
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const loadPage = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      let response;
      const skip = (page - 1) * PAGE_SIZE;
      if (activeTab === "memberships") {
        response = await config.service.listMemberships({
          skip,
          limit: PAGE_SIZE,
          search: appliedSearch.trim() || undefined,
          status: appliedStatus || undefined,
        });
      } else if (activeTab === "invitations") {
        response = await config.service.listInvitations({
          skip,
          // Teacher invitation API returns an array instead of a total.
          // Fetch one extra row to determine whether a next page exists.
          limit: role === "teacher" ? PAGE_SIZE + 1 : PAGE_SIZE,
          search: appliedSearch.trim() || undefined,
          status: appliedStatus || undefined,
        });
      } else {
        response = await parentService.listPendingLinkRequests({
          skip,
          limit: PAGE_SIZE,
        });
      }
      const pageRows = asItems(response);
      let nextItems = pageRows.slice(0, PAGE_SIZE);
      setItems(nextItems);
      setTotal(
        Number.isFinite(response?.total)
          ? response.total
          : skip + nextItems.length + (pageRows.length > PAGE_SIZE ? 1 : 0),
      );
    } catch (requestError) {
      const message = getErrorMessage(
        requestError,
        `Could not load ${role} directory.`,
      );
      setError(message);
      showError(message);
    } finally {
      setLoading(false);
    }
  }, [
    activeTab,
    appliedSearch,
    appliedStatus,
    config.service,
    page,
    role,
    showError,
  ]);

  useEffect(() => {
    loadPage();
  }, [loadPage]);

  useEffect(() => {
    if (activeTab === "requests") return undefined;

    const timeoutId = window.setTimeout(
      () => {
        setPage(1);
        setAppliedSearch(draftSearch);
        setAppliedStatus(draftStatus);
      },
      draftSearch.trim() ? 250 : 0,
    );

    return () => window.clearTimeout(timeoutId);
  }, [activeTab, draftSearch, draftStatus]);

  const selectTab = (tabId) => {
    const nextStatus = defaultStatusForTab(tabId);
    setActiveTab(tabId);
    setPage(1);
    setDraftSearch("");
    setAppliedSearch("");
    setDraftStatus(nextStatus);
    setAppliedStatus(nextStatus);
  };

  const clearFilters = () => {
    const nextStatus = defaultStatusForTab(activeTab);
    setPage(1);
    setDraftSearch("");
    setAppliedSearch("");
    setDraftStatus(nextStatus);
    setAppliedStatus(nextStatus);
  };

  const revokeInvitation = async (item) => {
    setActionId(item.id);
    try {
      await config.service.revokeInvitation(item.id);
      showSuccess("Invitation revoked.");
      await loadPage();
    } catch (requestError) {
      showError(getErrorMessage(requestError, "Could not revoke invitation."));
    } finally {
      setActionId("");
    }
  };

  const openLifecycle = async (membership, action) => {
    const state = {
      membership,
      action,
      reason: "",
      impact: null,
      replacementId: "",
      replacements: [],
      loadingImpact: role === "teacher" && action === "end",
    };
    setLifecycleState(state);
    if (role !== "teacher" || action !== "end") return;
    try {
      const [impact, replacementResponse] = await Promise.all([
        teacherService.getOffboardingImpact(membership.id),
        teacherService.listMemberships({ limit: 100, status: "active" }),
      ]);
      setLifecycleState((current) =>
        current
          ? {
              ...current,
              impact,
              replacements: asItems(replacementResponse).filter(
                (item) => item.id !== membership.id,
              ),
              loadingImpact: false,
            }
          : current,
      );
    } catch (requestError) {
      showError(
        getErrorMessage(
          requestError,
          "Could not inspect teacher responsibilities.",
        ),
      );
      setLifecycleState(null);
    }
  };

  const submitLifecycle = async (event) => {
    event.preventDefault();
    if (!lifecycleState) return;
    const reason = lifecycleState.reason.trim();
    if (reason.length < 3) {
      showWarning("Enter a reason with at least three characters.");
      return;
    }
    const { membership, action } = lifecycleState;
    setActionId(membership.id);
    try {
      if (action === "suspend") {
        await config.service.suspendMembership(membership.id, reason);
      } else if (action === "reactivate") {
        await config.service.reactivateMembership(membership.id, reason);
      } else if (role === "teacher") {
        await teacherService.endMembership(
          membership.id,
          reason,
          lifecycleState.replacementId || null,
        );
      } else {
        await parentService.endMembership(membership.id, reason);
      }
      showSuccess(
        action === "reactivate"
          ? "Membership reactivated."
          : action === "suspend"
            ? "Membership suspended."
            : "Membership ended.",
      );
      setLifecycleState(null);
      await loadPage();
    } catch (requestError) {
      showError(getErrorMessage(requestError, "Could not update membership."));
    } finally {
      setActionId("");
    }
  };

  const openTeacherEdit = (membership) => {
    setEditState({
      membership,
      form: {
        job_title: membership.job_title || "",
        department: membership.department || "",
        employment_type: membership.employment_type || "",
        receive_email_notifications:
          membership.receive_email_notifications !== false,
        receive_push_notifications:
          membership.receive_push_notifications !== false,
      },
      fieldErrors: {},
    });
  };

  const submitTeacherEdit = async (event) => {
    event.preventDefault();
    if (!editState) return;
    setActionId(editState.membership.id);
    try {
      await teacherService.updateMembership(editState.membership.id, {
        job_title: editState.form.job_title.trim() || null,
        department: editState.form.department.trim() || null,
        employment_type: editState.form.employment_type.trim() || null,
        receive_email_notifications: editState.form.receive_email_notifications,
        receive_push_notifications: editState.form.receive_push_notifications,
      });
      showSuccess("Teacher membership details updated.");
      setEditState(null);
      await loadPage();
    } catch (requestError) {
      const parsed = parseApiError(
        requestError,
        "Could not update teacher membership.",
      );
      setEditState((current) =>
        current
          ? { ...current, fieldErrors: parsed.fieldErrors || {} }
          : current,
      );
      showError(parsed.message);
    } finally {
      setActionId("");
    }
  };

  const openCapabilities = async (membership) => {
    setCapabilityState({
      membership,
      loading: true,
      subjects: [],
      selected: new Set(),
    });
    try {
      const [subjectResponse, capabilityResponse] = await Promise.all([
        api.get("/subjects?is_active=true&limit=100"),
        teacherService.listSubjectCapabilities(membership.id),
      ]);
      const selected = new Set(
        asItems(capabilityResponse)
          .filter((item) => item.is_active)
          .map((item) => item.subject_id),
      );
      setCapabilityState({
        membership,
        loading: false,
        subjects: asItems(subjectResponse),
        selected,
      });
    } catch (requestError) {
      showError(
        getErrorMessage(requestError, "Could not load subject capabilities."),
      );
      setCapabilityState(null);
    }
  };

  const toggleCapability = (subjectId) => {
    setCapabilityState((current) => {
      if (!current) return current;
      const selected = new Set(current.selected);
      if (selected.has(subjectId)) selected.delete(subjectId);
      else selected.add(subjectId);
      return { ...current, selected };
    });
  };

  const saveCapabilities = async () => {
    if (!capabilityState) return;
    setActionId(capabilityState.membership.id);
    try {
      await teacherService.replaceSubjectCapabilities(
        capabilityState.membership.id,
        [...capabilityState.selected],
      );
      showSuccess("Teacher subject capabilities updated.");
      setCapabilityState(null);
    } catch (requestError) {
      showError(
        getErrorMessage(requestError, "Could not update subject capabilities."),
      );
    } finally {
      setActionId("");
    }
  };

  const decideRequest = async (request, action, reason = null) => {
    setActionId(request.id);
    try {
      await parentService.decideLinkRequest(request.id, {
        action,
        ...(reason ? { reason } : {}),
      });
      showSuccess(
        action === "approve"
          ? "Parent link approved."
          : "Parent link rejected.",
      );
      setRequestDecision(null);
      await loadPage();
    } catch (requestError) {
      showError(
        getErrorMessage(requestError, "Could not update parent-link request."),
      );
    } finally {
      setActionId("");
    }
  };

  return (
    <DashboardLayout
      role="admin"
      title={config.title}
      description={config.description}
      actions={
        <Link to={`/admin/invitations/${role}`}>
          <Button type="button">
            <MailPlus className="h-4 w-4" />
            {config.inviteLabel}
          </Button>
        </Link>
      }
    >
      {error ? (
        <div className="rounded-2xl border border-error/30 bg-error-soft px-4 py-3 text-sm text-error">
          {error}
        </div>
      ) : null}

      <Card className="people-directory-toolbar rounded-xl p-2.5 sm:p-3">
        <div className="flex flex-col gap-2 lg:flex-row lg:items-center">
          <div
            role="tablist"
            aria-label={`${titleCase(role)} directory views`}
            className="people-directory-tabs flex shrink-0 gap-1 overflow-x-auto rounded-lg bg-surface-muted/55 p-1"
            style={{
              gridTemplateColumns: `repeat(${availableTabs.length}, minmax(0, 1fr))`,
            }}
          >
            {availableTabs.map((tab) => (
              <button
                key={tab.id}
                type="button"
                role="tab"
                aria-selected={activeTab === tab.id}
                onClick={() => selectTab(tab.id)}
                className={`min-h-9 shrink-0 whitespace-nowrap rounded-lg px-3 py-1.5 text-xs font-semibold transition sm:text-sm ${activeTab === tab.id ? "bg-primary text-primary-foreground shadow-sm" : "text-text-muted hover:bg-surface/70 hover:text-text"}`}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {activeTab !== "requests" ? (
            <form
              onSubmit={(event) => event.preventDefault()}
              className="grid min-w-0 flex-1 grid-cols-[minmax(0,1fr)_auto] gap-2 sm:grid-cols-[minmax(0,1fr)_10rem_auto]"
            >
              <div className="relative col-span-2 sm:col-span-1">
                <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted" />
                <Input
                  value={draftSearch}
                  onChange={(event) => setDraftSearch(event.target.value)}
                  placeholder={
                    activeTab === "memberships"
                      ? `Search ${role} email or name`
                      : "Search invited email"
                  }
                  className="!min-h-9 !rounded-lg !py-1.5 pl-9"
                />
              </div>
              <select
                aria-label="Filter by status"
                className="input-base !min-h-9 !rounded-lg !py-1.5"
                value={draftStatus}
                onChange={(event) => setDraftStatus(event.target.value)}
              >
                <option value="">All statuses</option>
                {statusOptions.map((status) => (
                  <option key={status} value={status}>
                    {titleCase(status)}
                  </option>
                ))}
              </select>
              <Button
                type="button"
                variant="outline"
                size="small"
                onClick={clearFilters}
              >
                Clear
              </Button>
            </form>
          ) : null}
        </div>
      </Card>

      {role === "teacher" && activeTab === "memberships" ? (
        <DirectorySummary
          items={[
            {
              label: "Matching teachers",
              value: total,
              detail: "all pages",
              icon: Users,
              tone: "primary",
            },
            {
              label: "Active",
              value: items.filter((item) => item.status === "active").length,
              detail: "this page",
              icon: ShieldCheck,
              tone: "success",
            },
            {
              label: "With staff ID",
              value: items.filter((item) => item.staff_id).length,
              detail: "this page",
              icon: BriefcaseBusiness,
            },
            {
              label: "Profile ready",
              value: items.filter((item) => item.job_title && item.department)
                .length,
              detail: "role and department",
              icon: UserRound,
              tone: "warning",
            },
          ]}
        />
      ) : null}

      {role === "parent" && activeTab === "memberships" ? (
        <DirectorySummary
          items={[
            {
              label: "Matching parents",
              value: total,
              detail: "all pages",
              icon: Users,
              tone: "primary",
            },
            {
              label: "Active",
              value: items.filter((item) => item.status === "active").length,
              detail: "this page",
              icon: ShieldCheck,
              tone: "success",
            },
            {
              label: "Read only",
              value: items.filter((item) => item.status === "read_only").length,
              detail: "historical access",
              icon: BookOpenCheck,
              tone: "warning",
            },
            {
              label: "Profile ready",
              value: items.filter((item) => {
                const account = item.parent_account || {};
                return account.first_name && account.last_name && account.email;
              }).length,
              detail: "name and email",
              icon: UserRound,
            },
          ]}
        />
      ) : null}

      <div className="flex items-center justify-between gap-3 rounded-xl border border-border/70 bg-surface/60 px-4 py-2.5 text-sm text-text-muted">
        <span>
          {total} record{total === 1 ? "" : "s"}
        </span>
        <span>
          Page {page} of {pageCount}
        </span>
      </div>

      {loading ? (
        <LoadingState label={`Loading ${role} directory...`} />
      ) : items.length === 0 ? (
        <Card className="p-6">
          <EmptyState
            icon={Users}
            title="No records found"
            description="Adjust the filters or create an invitation."
          />
        </Card>
      ) : activeTab === "memberships" && role === "teacher" ? (
        <TeacherMembershipList
          items={items}
          actionId={actionId}
          onEdit={openTeacherEdit}
          onCapabilities={openCapabilities}
          onLifecycle={openLifecycle}
        />
      ) : activeTab === "memberships" && role === "parent" ? (
        <ParentMembershipList
          items={items}
          actionId={actionId}
          onLifecycle={openLifecycle}
        />
      ) : activeTab === "memberships" ? (
        <section className="directory-card-grid mobile-scroll-list grid gap-4 sm:grid-cols-2 2xl:grid-cols-3">
          {items.map((membership) => {
            const account = membership[config.accountKey] || {};
            const status = String(membership.status || "unknown").toLowerCase();
            const busy = actionId === membership.id;
            return (
              <Card
                key={membership.id}
                className="flex min-h-[16rem] flex-col p-5"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex min-w-0 gap-3">
                    <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-primary-soft text-primary">
                      <UserRound className="h-5 w-5" />
                    </span>
                    <div className="min-w-0">
                      <p className="break-words font-semibold text-text">
                        {displayName(account)}
                      </p>
                      <p className="mt-1 break-words text-xs text-text-muted">
                        {account.email || "No email"}
                      </p>
                    </div>
                  </div>
                  <Badge variant={badgeVariant(status)}>
                    {titleCase(status)}
                  </Badge>
                </div>
                <div className="mt-4 space-y-2 rounded-2xl bg-surface-muted/30 px-4 py-3 text-sm text-text-muted">
                  {role === "teacher" ? (
                    <>
                      <p>Staff ID: {membership.staff_id || "Not assigned"}</p>
                      <p>Job title: {membership.job_title || "Not provided"}</p>
                      <p>
                        Department: {membership.department || "Not provided"}
                      </p>
                    </>
                  ) : (
                    <>
                      <p>
                        Joined:{" "}
                        {membership.joined_at
                          ? new Date(membership.joined_at).toLocaleDateString()
                          : "Unknown"}
                      </p>
                      <p>
                        Access:{" "}
                        {status === "read_only"
                          ? "Historical records only"
                          : status === "active"
                            ? "Active child links"
                            : "Inactive"}
                      </p>
                    </>
                  )}
                </div>
                <div className="mt-auto flex flex-wrap gap-2 pt-4">
                  {role === "teacher" ? (
                    <>
                      <Button
                        type="button"
                        size="small"
                        variant="outline"
                        disabled={busy}
                        onClick={() => openTeacherEdit(membership)}
                      >
                        <Pencil className="h-4 w-4" />
                        Edit
                      </Button>
                      <Button
                        type="button"
                        size="small"
                        variant="outline"
                        disabled={busy}
                        onClick={() => openCapabilities(membership)}
                      >
                        <BookOpenCheck className="h-4 w-4" />
                        Subjects
                      </Button>
                    </>
                  ) : null}
                  {role === "teacher" && status === "active" ? (
                    <Button
                      type="button"
                      size="small"
                      variant="outline"
                      disabled={busy}
                      onClick={() => openLifecycle(membership, "suspend")}
                    >
                      Suspend
                    </Button>
                  ) : null}
                  {["active", "read_only", "suspended"].includes(status) ? (
                    <Button
                      type="button"
                      size="small"
                      variant="danger"
                      disabled={busy}
                      onClick={() => openLifecycle(membership, "end")}
                    >
                      End
                    </Button>
                  ) : null}
                  {["inactive", "suspended"].includes(status) ? (
                    <Button
                      type="button"
                      size="small"
                      variant="success"
                      disabled={busy}
                      onClick={() => openLifecycle(membership, "reactivate")}
                    >
                      Reactivate
                    </Button>
                  ) : null}
                </div>
              </Card>
            );
          })}
        </section>
      ) : activeTab === "invitations" ? (
        <InvitationList
          items={items}
          actionId={actionId}
          onRevoke={revokeInvitation}
          role={role}
        />
      ) : (
        <ParentLinkRequestList
          items={items}
          actionId={actionId}
          onApprove={(request) => decideRequest(request, "approve")}
          onReject={(request) => setRequestDecision({ request, reason: "" })}
        />
      )}

      <div className="mobile-list-pagination flex items-center justify-between gap-2">
        <span className="text-xs font-semibold text-text-muted sm:hidden">
          Page {page}/{pageCount}
        </span>
        <div className="ml-auto grid grid-cols-2 gap-2 sm:flex">
          <Button
            type="button"
            size="small"
            variant="outline"
            disabled={page <= 1 || loading}
            onClick={() => setPage((current) => Math.max(1, current - 1))}
          >
            <ChevronLeft className="h-4 w-4" />
            Previous
          </Button>
          <Button
            type="button"
            size="small"
            variant="outline"
            disabled={page >= pageCount || loading}
            onClick={() =>
              setPage((current) => Math.min(pageCount, current + 1))
            }
          >
            Next
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>
      </div>

      <Modal
        open={Boolean(lifecycleState)}
        title={
          lifecycleState
            ? `${titleCase(lifecycleState.action)} membership`
            : "Membership lifecycle"
        }
        description="This changes access to this school only; the global account remains intact."
        onClose={() => !actionId && setLifecycleState(null)}
        closeOnOverlay={!actionId}
      >
        {lifecycleState ? (
          <form onSubmit={submitLifecycle} className="space-y-4">
            {lifecycleState.loadingImpact ? (
              <LoadingState label="Inspecting active responsibilities..." />
            ) : null}
            {role === "teacher" &&
            lifecycleState.action === "end" &&
            lifecycleState.impact ? (
              <div className="rounded-2xl border border-warning/30 bg-warning-soft px-4 py-3 text-sm text-amber-800">
                <p className="font-semibold">Current responsibilities</p>
                <p className="mt-1">
                  Class head: {lifecycleState.impact.class_teacher_assignments}
                </p>
                <p>
                  Teacher assignments:{" "}
                  {lifecycleState.impact.teacher_assignments}
                </p>
              </div>
            ) : null}
            {role === "teacher" && lifecycleState.action === "end" ? (
              <label className="block">
                <span className="mb-1.5 block text-sm font-semibold text-text-soft">
                  Replacement teacher (optional)
                </span>
                <select
                  className="input-base"
                  value={lifecycleState.replacementId}
                  onChange={(event) =>
                    setLifecycleState((current) => ({
                      ...current,
                      replacementId: event.target.value,
                    }))
                  }
                >
                  <option value="">Release current responsibilities</option>
                  {lifecycleState.replacements.map((item) => (
                    <option key={item.id} value={item.id}>
                      {displayName(item.teacher_account)} ·{" "}
                      {item.job_title || "Teacher"}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
            <label className="block">
              <span className="mb-1.5 block text-sm font-semibold text-text-soft">
                Reason
              </span>
              <textarea
                className="input-base min-h-28"
                maxLength={500}
                value={lifecycleState.reason}
                onChange={(event) =>
                  setLifecycleState((current) => ({
                    ...current,
                    reason: event.target.value,
                  }))
                }
              />
            </label>
            <div className="flex justify-end gap-2">
              <Button
                type="button"
                variant="outline"
                disabled={Boolean(actionId)}
                onClick={() => setLifecycleState(null)}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                variant={
                  lifecycleState.action === "reactivate" ? "success" : "danger"
                }
                disabled={Boolean(actionId) || lifecycleState.loadingImpact}
              >
                {actionId ? "Saving..." : "Confirm"}
              </Button>
            </div>
          </form>
        ) : null}
      </Modal>

      <Modal
        open={Boolean(editState)}
        title="Edit teacher membership"
        description="Employment details belong to this school membership only."
        onClose={() => !actionId && setEditState(null)}
        closeOnOverlay={!actionId}
      >
        {editState ? (
          <form onSubmit={submitTeacherEdit} className="space-y-4">
            <Input
              label="Job title"
              value={editState.form.job_title}
              error={editState.fieldErrors.job_title}
              onChange={(event) =>
                setEditState((current) => ({
                  ...current,
                  form: { ...current.form, job_title: event.target.value },
                }))
              }
            />
            <Input
              label="Department"
              value={editState.form.department}
              error={editState.fieldErrors.department}
              onChange={(event) =>
                setEditState((current) => ({
                  ...current,
                  form: { ...current.form, department: event.target.value },
                }))
              }
            />
            <Input
              label="Employment type"
              value={editState.form.employment_type}
              error={editState.fieldErrors.employment_type}
              onChange={(event) =>
                setEditState((current) => ({
                  ...current,
                  form: {
                    ...current.form,
                    employment_type: event.target.value,
                  },
                }))
              }
            />
            <label className="flex items-center gap-2 text-sm text-text-soft">
              <input
                type="checkbox"
                checked={editState.form.receive_email_notifications}
                onChange={(event) =>
                  setEditState((current) => ({
                    ...current,
                    form: {
                      ...current.form,
                      receive_email_notifications: event.target.checked,
                    },
                  }))
                }
              />
              Email notifications
            </label>
            <label className="flex items-center gap-2 text-sm text-text-soft">
              <input
                type="checkbox"
                checked={editState.form.receive_push_notifications}
                onChange={(event) =>
                  setEditState((current) => ({
                    ...current,
                    form: {
                      ...current.form,
                      receive_push_notifications: event.target.checked,
                    },
                  }))
                }
              />
              Push notifications
            </label>
            <div className="flex justify-end gap-2">
              <Button
                type="button"
                variant="outline"
                onClick={() => setEditState(null)}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={Boolean(actionId)}>
                {actionId ? "Saving..." : "Save"}
              </Button>
            </div>
          </form>
        ) : null}
      </Modal>

      <Modal
        open={Boolean(capabilityState)}
        title="Approved teaching subjects"
        description="Active assignments must be ended or reassigned before their subject approval can be removed."
        onClose={() => !actionId && setCapabilityState(null)}
        closeOnOverlay={!actionId}
      >
        {capabilityState?.loading ? (
          <LoadingState label="Loading subjects..." />
        ) : capabilityState ? (
          <div className="space-y-4">
            <div className="max-h-80 space-y-2 overflow-y-auto">
              {capabilityState.subjects.map((subject) => (
                <label
                  key={subject.id}
                  className="flex items-center gap-3 rounded-xl border border-border px-3 py-3 text-sm text-text-soft"
                >
                  <input
                    type="checkbox"
                    checked={capabilityState.selected.has(subject.id)}
                    onChange={() => toggleCapability(subject.id)}
                  />
                  <span>
                    <span className="font-semibold text-text">
                      {subject.name}
                    </span>
                    {subject.code ? (
                      <span className="ml-2 text-xs text-text-muted">
                        {subject.code}
                      </span>
                    ) : null}
                  </span>
                </label>
              ))}
            </div>
            <div className="flex justify-end gap-2">
              <Button
                type="button"
                variant="outline"
                onClick={() => setCapabilityState(null)}
              >
                Cancel
              </Button>
              <Button
                type="button"
                disabled={Boolean(actionId)}
                onClick={saveCapabilities}
              >
                {actionId ? "Saving..." : "Save subjects"}
              </Button>
            </div>
          </div>
        ) : null}
      </Modal>

      <Modal
        open={Boolean(requestDecision)}
        title="Reject parent-link request"
        description="A rejection reason is required for the audit trail."
        onClose={() => !actionId && setRequestDecision(null)}
        closeOnOverlay={!actionId}
      >
        {requestDecision ? (
          <div className="space-y-4">
            <label className="block">
              <span className="mb-1.5 block text-sm font-semibold text-text-soft">
                Reason
              </span>
              <textarea
                className="input-base min-h-28"
                value={requestDecision.reason}
                maxLength={500}
                onChange={(event) =>
                  setRequestDecision((current) => ({
                    ...current,
                    reason: event.target.value,
                  }))
                }
              />
            </label>
            <div className="flex justify-end gap-2">
              <Button
                type="button"
                variant="outline"
                onClick={() => setRequestDecision(null)}
              >
                Cancel
              </Button>
              <Button
                type="button"
                variant="danger"
                disabled={
                  Boolean(actionId) || requestDecision.reason.trim().length < 3
                }
                onClick={() =>
                  decideRequest(
                    requestDecision.request,
                    "reject",
                    requestDecision.reason.trim(),
                  )
                }
              >
                {actionId ? "Rejecting..." : "Reject request"}
              </Button>
            </div>
          </div>
        ) : null}
      </Modal>
    </DashboardLayout>
  );
}

export default MembershipDirectoryPage;
