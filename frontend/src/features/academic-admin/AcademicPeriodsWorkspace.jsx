import { beginAcademicSubmission, endAcademicSubmission, finishAcademicCreation } from "./academicSubmission";
import { CalendarDays } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import Button from "../../components/ui/Button";
import Modal from "../../components/ui/Modal";
import { useToast } from "../../hooks/useToast";
import { academicService } from "../../services/academicService";
import { getErrorMessage, parseApiError } from "../../services/api";
import { subscriptionService } from "../../services/subscriptionService";
import {
  FormActions,
  Input,
  RecordList,
  SelectControl,
  WorkspaceGrid,
  WorkspacePanel,
} from "./AcademicWorkspacePrimitives";
import TypedConfirmationDialog from "./TypedConfirmationDialog";

const BLANK_SESSION = {
  name: "",
  start_date: "",
  end_date: "",
  next_academic_session_id: "",
};
const BLANK_TERM = {
  academic_session_id: "",
  name: "first_term",
  start_date: "",
  end_date: "",
};

const CONFIRM_OPEN_SESSION = "OPEN_ACADEMIC_SESSION";
const CONFIRM_DELETE_SESSION = "DELETE_ACADEMIC_SESSION";
const CONFIRM_OPEN_TERM = "OPEN_ACADEMIC_TERM";
const CONFIRM_START_TERM_CLOSING = "START_TERM_CLOSING";
const CONFIRM_FINALIZE_TERM_CLOSE = "FINALIZE_TERM_CLOSE";
const CONFIRM_CANCEL_TERM_CLOSURE = "CANCEL_TERM_CLOSURE";
const CONFIRM_DELETE_TERM = "DELETE_ACADEMIC_TERM";

const asItems = (response) =>
  Array.isArray(response)
    ? response
    : Array.isArray(response?.items)
      ? response.items
      : [];

const termLabel = (value) =>
  String(value || "")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());

const dateLabel = (value) =>
  value ? new Date(value).toLocaleDateString() : "Date not set";

const dependencyLabels = {
  open_terms: "Open terms",
  draft_results: "Draft results",
  submitted_results: "Submitted results",
  approved_but_unlocked_results: "Approved results awaiting lock",
  unpublished_report_cards: "Unpublished report cards",
  active_or_pending_progression_runs: "Active progression runs",
  terms: "Academic terms",
  enrollments: "Student enrollments",
  report_cards: "Report cards",
  progression_runs: "Progression runs",
  inbound_next_sessions: "Inbound progression links",
};

const formatDependencyMessage = (preview) => {
  const messages = preview?.blocker_messages || [];
  if (messages.length) return messages.join(" ");
  return Object.entries(preview?.dependency_counts || {})
    .filter(([, count]) => Number(count) > 0)
    .map(
      ([key, count]) =>
        `${dependencyLabels[key] || key.replaceAll("_", " ")}: ${count}`,
    )
    .join("; ");
};

function AcademicPeriodsWorkspace({
  domain,
  activeTab = "overview",
  onContextChange,
  guided = false,
  onSaved,
  setupSessionName,
  setupRecordId,
}) {
  const isSessions = domain === "sessions";
  const { showError, showSuccess } = useToast();
  const [searchParams, setSearchParams] = useSearchParams();
  const [sessions, setSessions] = useState([]);
  const [terms, setTerms] = useState([]);
  const [sessionForm, setSessionForm] = useState(BLANK_SESSION);
  const [termForm, setTermForm] = useState(BLANK_TERM);
  const [editing, setEditing] = useState(null);
  const [saving, setSaving] = useState("");
  const [pendingConfirmation, setPendingConfirmation] = useState(null);
  const [cancelClosureReason, setCancelClosureReason] = useState("");
  const [termPlanPrompt, setTermPlanPrompt] = useState(null);

  const load = useCallback(async () => {
    try {
      const [sessionResponse, termResponse] = await Promise.all([
        academicService.listSessions({ limit: 100 }),
        academicService.listTerms({ limit: 100 }),
      ]);
      const sessionRows = guided && setupSessionName
        ? asItems(sessionResponse).filter((item) => item.name === setupSessionName)
        : asItems(sessionResponse);
      const termRows = asItems(termResponse);
      setSessions(sessionRows);
      setTerms(termRows);
      if (guided && setupRecordId) {
        const record = (isSessions ? sessionRows : termRows).find((item) => item.id === setupRecordId);
        if (record) {
          setEditing({ type: isSessions ? "session" : "term", id: record.id });
          if (isSessions) setSessionForm({ ...BLANK_SESSION, ...record });
          else setTermForm({ ...BLANK_TERM, ...record });
        }
      }

      const currentSession = sessionRows.find((item) => item.is_current) || null;
      const currentTerm = termRows.find((item) => item.is_current) || null;
      onContextChange?.({ currentSession, currentTerm });
      setTermForm((current) => ({
        ...current,
        academic_session_id:
          current.academic_session_id ||
          currentSession?.id ||
          sessionRows[0]?.id ||
          "",
      }));
    } catch (error) {
      showError(
        getErrorMessage(
          error,
          isSessions
            ? "Could not load academic sessions."
            : "Could not load academic terms.",
        ),
      );
    }
  }, [isSessions, onContextChange, showError, guided, setupSessionName, setupRecordId]);

  useEffect(() => {
    load();
  }, [load]);

  const sessionById = useMemo(
    () => new Map(sessions.map((item) => [item.id, item])),
    [sessions],
  );

  const rows = useMemo(() => {
    const source = isSessions ? sessions : terms;
    if (["draft", "open", "closing", "closed"].includes(activeTab)) {
      return source.filter((item) => item.status === activeTab);
    }
    return source;
  }, [activeTab, isSessions, sessions, terms]);

  const selectView = (view) => {
    const next = new URLSearchParams(searchParams);
    if (view === "create") next.set("returnView", activeTab === "create" ? "overview" : activeTab);
    else next.delete("returnView");
    next.set("view", view);
    next.delete("tab");
    setSearchParams(next, { replace: true });
  };

  const closeEditor = () => {
    setEditing(null);
    setSessionForm(BLANK_SESSION);
    setTermForm((current) => ({
      ...BLANK_TERM,
      academic_session_id:
        sessions.find((item) => item.is_current)?.id ||
        current.academic_session_id ||
        sessions[0]?.id ||
        "",
    }));
    selectView(searchParams.get("returnView") || (activeTab === "create" ? "overview" : activeTab));
  };

  const saveSession = async (event) => {
    const submission = beginAcademicSubmission(event, Boolean(saving));
    if (!submission) return;
    setSaving("session");
    try {
      const row = editing?.type === "session" ? sessionById.get(editing.id) : null;
      const payload =
        row?.status === "open"
          ? {
              next_academic_session_id:
                sessionForm.next_academic_session_id || null,
            }
          : {
              name: sessionForm.name,
              start_date: sessionForm.start_date || null,
              end_date: sessionForm.end_date || null,
              next_academic_session_id:
                sessionForm.next_academic_session_id || null,
            };
      if (row) await academicService.updateSession(row.id, payload);
      else await academicService.createSession(payload);
      showSuccess(row ? "Academic session updated." : "Academic session created.");
      if (!guided) finishAcademicCreation(submission, () => setSessionForm(BLANK_SESSION), closeEditor, Boolean(editing));
      await load();
      if (guided) await onSaved?.();
    } catch (error) {
      showError(getErrorMessage(error, "Could not save academic session."));
    } finally {
      endAcademicSubmission(submission);
      setSaving("");
    }
  };

  const saveTerm = async (event) => {
    const submission = beginAcademicSubmission(event, Boolean(saving));
    if (!submission) return;
    setSaving("term");
    try {
      const payload = {
        academic_session_id: termForm.academic_session_id,
        name: termForm.name,
        start_date: termForm.start_date || null,
        end_date: termForm.end_date || null,
      };
      if (editing?.type === "term") {
        await academicService.updateTerm(editing.id, payload);
      } else {
        await academicService.createTerm(payload);
      }
      showSuccess(
        editing?.type === "term" ? "Academic term updated." : "Academic term created.",
      );
      if (!guided) finishAcademicCreation(submission, () => setTermForm((current) => ({ ...BLANK_TERM, academic_session_id: current.academic_session_id })), closeEditor, Boolean(editing));
      await load();
      if (guided) await onSaved?.();
    } catch (error) {
      showError(getErrorMessage(error, "Could not save academic term."));
    } finally {
      endAcademicSubmission(submission);
      setSaving("");
    }
  };

  const openSession = async (item) => {
    setSaving(item.id);
    try {
      await academicService.openSession(item.id);
      showSuccess("Academic session opened.");
      await load();
    } catch (error) {
      showError(getErrorMessage(error, "Could not open academic session."));
    } finally {
      setSaving("");
      setPendingConfirmation(null);
    }
  };

  const deleteSession = async (item) => {
    setSaving(item.id);
    try {
      const preview = await academicService.getSessionDependencies(item.id);
      if (!preview?.can_delete) {
        showError(
          formatDependencyMessage(preview) || "This session cannot be deleted.",
        );
        return;
      }
      await academicService.deleteSession(item.id);
      showSuccess("Academic session deleted.");
      await load();
    } catch (error) {
      showError(getErrorMessage(error, "Could not delete academic session."));
    } finally {
      setSaving("");
      setPendingConfirmation(null);
    }
  };

  const transitionTerm = async (item, transition) => {
    setSaving(item.id);
    try {
      if (transition === "open") {
        await academicService.openTerm(item.id);
        showSuccess("Academic term opened.");
      } else if (transition === "start-closing") {
        const preview = await academicService.getTermDependencies(item.id);
        if (!preview?.can_start_closing) {
          showError(
            formatDependencyMessage(preview) ||
              "This term cannot start closing yet.",
          );
          return;
        }
        await academicService.startTermClosing(item.id);
        showSuccess("Academic term is now closing.");
      } else if (transition === "finalize-close") {
        const preview = await academicService.getTermDependencies(item.id);
        if (!preview?.can_finalize_close) {
          showError(
            formatDependencyMessage(preview) ||
              "This term cannot be finalized yet.",
          );
          return;
        }
        await academicService.finalizeTermClose(item.id);
        showSuccess("Academic term closed.");
      } else if (transition === "cancel-closure") {
        const reason = cancelClosureReason.trim();
        if (reason.length < 3) {
          showError("A reason is required to cancel term closure.");
          return;
        }
        await academicService.cancelTermClosure(item.id, reason);
        showSuccess("Academic term closure cancelled.");
      }
      await load();
    } catch (error) {
      const parsed = parseApiError(
        error,
        "Could not update academic term lifecycle.",
      );
      const directCode = parsed.data?.code;
      const nestedCode = parsed.data?.detail?.code;
      const selectionRequired = new Set([
        "TERM_PLAN_SELECTION_REQUIRED",
        "TERM_PLAN_ACTIVATION_REQUIRED",
      ]);
      const activation = selectionRequired.has(directCode)
        ? parsed.data
        : selectionRequired.has(nestedCode)
          ? parsed.data.detail
          : null;
      if (transition === "open" && activation) {
        setTermPlanPrompt({ ...activation, term: item });
      } else {
        showError(parsed.message);
      }
    } finally {
      setSaving("");
      setPendingConfirmation(null);
      setCancelClosureReason("");
    }
  };

  const deleteTerm = async (item) => {
    setSaving(item.id);
    try {
      const preview = await academicService.getTermDependencies(item.id);
      if (!preview?.can_delete) {
        showError(formatDependencyMessage(preview) || "This term cannot be deleted.");
        return;
      }
      await academicService.deleteTerm(item.id);
      showSuccess("Academic term deleted.");
      await load();
    } catch (error) {
      showError(getErrorMessage(error, "Could not delete academic term."));
    } finally {
      setSaving("");
      setPendingConfirmation(null);
    }
  };

  const activateFreeAndOpen = async () => {
    const term = termPlanPrompt?.term;
    if (!term?.id) return;
    setSaving(term.id);
    try {
      await subscriptionService.activateFreeTerm(term.id);
      await academicService.openTerm(term.id);
      showSuccess("Free selected and academic term opened.");
      setTermPlanPrompt(null);
      await load();
    } catch (error) {
      showError(getErrorMessage(error, "Could not continue with Free."));
    } finally {
      setSaving("");
    }
  };

  const openPaidPlans = () => {
    const term = termPlanPrompt?.term;
    if (!term?.id) return;
    window.location.assign(
      `/admin/billing/plans?term=${encodeURIComponent(
        term.id,
      )}&intent=open-term&origin=academic-terms&return=${encodeURIComponent(
        "/admin/academic/terms",
      )}`,
    );
  };

  const runConfirmedAction = () => {
    if (!pendingConfirmation) return;
    const { type, item, transition } = pendingConfirmation;
    if (type === "open-session") openSession(item);
    if (type === "delete-session") deleteSession(item);
    if (type === "term-transition") transitionTerm(item, transition);
    if (type === "delete-term") deleteTerm(item);
  };

  const editSession = (item) => {
    setEditing({ type: "session", id: item.id });
    setSessionForm({
      name: item.name || "",
      start_date: item.start_date || "",
      end_date: item.end_date || "",
      next_academic_session_id: item.next_academic_session_id || "",
    });
  };

  const editTerm = (item) => {
    setEditing({ type: "term", id: item.id });
    setTermForm({
      academic_session_id: item.academic_session_id || "",
      name: item.name || "first_term",
      start_date: item.start_date || "",
      end_date: item.end_date || "",
    });
  };

  const showEditor = activeTab === "create" || Boolean(editing);

  const editor = isSessions ? (
    <WorkspacePanel
      onBack={guided ? undefined : closeEditor}
      backDisabled={Boolean(saving)}
      title={
        editing?.type === "session"
          ? sessionById.get(editing.id)?.status === "open"
            ? "Configure session"
            : "Edit session"
          : "Create session"
      }
      description={guided ? "Name the school year and choose its dates." : "Session dates become immutable after opening. An open session may only change its next-session progression target."}
    >
      <form className="space-y-3" onSubmit={saveSession}>
        <fieldset disabled={Boolean(saving)} className="space-y-3">
          <Input
            label="Session name"
            value={sessionForm.name}
            onChange={(event) =>
              setSessionForm((current) => ({ ...current, name: event.target.value }))
            }
            placeholder="2026/2027"
            minLength={9}
            maxLength={9}
            required
            disabled={sessionById.get(editing?.id)?.status === "open"}
          />
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-1">
            <Input
              label="Start date"
              type="date"
              required={guided}
              value={sessionForm.start_date}
              onChange={(event) =>
                setSessionForm((current) => ({
                  ...current,
                  start_date: event.target.value,
                }))
              }
              disabled={sessionById.get(editing?.id)?.status === "open"}
            />
            <Input
              label="End date"
              type="date"
              required={guided}
              value={sessionForm.end_date}
              onChange={(event) =>
                setSessionForm((current) => ({
                  ...current,
                  end_date: event.target.value,
                }))
              }
              disabled={sessionById.get(editing?.id)?.status === "open"}
            />
          </div>
          {!guided ? <SelectControl
            label="Next session"
            value={sessionForm.next_academic_session_id}
            onChange={(value) =>
              setSessionForm((current) => ({
                ...current,
                next_academic_session_id: value,
              }))
            }
            options={sessions
              .filter((item) => item.id !== editing?.id && item.status === "draft")
              .map((item) => ({ value: item.id, label: item.name }))}
            clearable
            placeholder="Optional progression target"
          /> : null}
          <FormActions
            submitting={saving === "session"}
            submitLabel={guided ? "Save and continue" : editing ? "Save session" : "Create session"}
            repeatable={!guided}
            editing={Boolean(editing)}
            onCancel={guided ? undefined : closeEditor}
          />
        </fieldset>
      </form>
    </WorkspacePanel>
  ) : (
    <WorkspacePanel
      title={editing?.type === "term" ? "Edit term" : "Create term"}
      onBack={guided ? undefined : closeEditor}
      backDisabled={Boolean(saving)}
      description={guided ? "Choose a term and its dates within the school year." : "Terms belong to one academic session. A plan is deliberately selected only when the term is opened."}
    >
      <form className="space-y-3" onSubmit={saveTerm}>
        <fieldset disabled={Boolean(saving)} className="space-y-3">
          <SelectControl
            label="Academic session"
            value={termForm.academic_session_id}
            onChange={(value) =>
              setTermForm((current) => ({
                ...current,
                academic_session_id: value,
              }))
            }
            options={sessions.map((item) => ({ value: item.id, label: item.name }))}
            required
            disabled={editing?.type === "term"}
          />
          <SelectControl
            label="Term"
            value={termForm.name}
            onChange={(value) =>
              setTermForm((current) => ({ ...current, name: value }))
            }
            options={[
              { value: "first_term", label: "First Term" },
              { value: "second_term", label: "Second Term" },
              { value: "third_term", label: "Third Term" },
            ]}
            required
          />
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-1">
            <Input
              label="Start date"
              type="date"
              required={guided}
              value={termForm.start_date}
              onChange={(event) =>
                setTermForm((current) => ({
                  ...current,
                  start_date: event.target.value,
                }))
              }
            />
            <Input
              label="End date"
              type="date"
              required={guided}
              value={termForm.end_date}
              onChange={(event) =>
                setTermForm((current) => ({
                  ...current,
                  end_date: event.target.value,
                }))
              }
            />
          </div>
          <FormActions
            submitting={saving === "term"}
            submitLabel={guided ? "Save and continue" : editing ? "Save term" : "Create term"}
            repeatable={!guided}
            editing={Boolean(editing)}
            onCancel={guided ? undefined : closeEditor}
          />
        </fieldset>
      </form>
    </WorkspacePanel>
  );

  if (guided) return <div className="school-year-form">{editor}</div>;

  return (
    <>
      <WorkspaceGrid
        content={
          <RecordList
            title={isSessions ? "Academic sessions" : "Academic terms"}
            description={
              isSessions
                ? "School years with explicit draft, open, closing, and closed lifecycle states."
                : "Academic terms within a session. Free or paid plan selection happens only when a draft term is opened."
            }
            actions={
              !showEditor ? (
                <Button type="button" onClick={() => selectView("create")}>
                  {isSessions ? "Create session" : "Create term"}
                </Button>
              ) : null
            }
            items={rows}
            emptyIcon={CalendarDays}
            emptyTitle={isSessions ? "No academic sessions" : "No academic terms"}
            emptyDescription={
              isSessions
                ? "Create the first school year to begin the academic lifecycle."
                : "Create an academic term inside an existing session."
            }
            renderTitle={(item) => (isSessions ? item.name : termLabel(item.name))}
            renderMeta={(item) =>
              isSessions
                ? `${dateLabel(item.start_date)} – ${dateLabel(item.end_date)}`
                : sessionById.get(item.academic_session_id)?.name || "Academic session"
            }
            renderDescription={(item) => {
              if (!isSessions) {
                return `${dateLabel(item.start_date)} – ${dateLabel(item.end_date)}`;
              }
              const next = sessionById.get(item.next_academic_session_id);
              return next
                ? `Progression target: ${next.name}`
                : "No next-session progression target configured.";
            }}
            renderStatus={(item) => (item.is_current ? "current" : item.status)}
            showInspector={!showEditor}
            canEdit={(item) =>
              isSessions
                ? ["draft", "open"].includes(item.status)
                : item.status === "draft"
            }
            showDefaultEditAction={!isSessions}
            onEdit={isSessions ? editSession : editTerm}
            renderActions={(item) =>
              isSessions ? (
                <SessionActions
                  item={item}
                  busy={saving === item.id}
                  onConfirm={setPendingConfirmation}
                  onEdit={editSession}
                />
              ) : (
                <TermActions
                  item={item}
                  busy={saving === item.id}
                  onConfirm={(payload) => {
                    if (payload.transition === "cancel-closure") {
                      setCancelClosureReason("");
                    }
                    setPendingConfirmation(payload);
                  }}
                />
              )
            }
          />
        }
        editor={showEditor ? editor : null}
      />

      <TypedConfirmationDialog
        open={Boolean(pendingConfirmation)}
        title={pendingConfirmation?.title}
        description={pendingConfirmation?.description}
        confirmationText={pendingConfirmation?.confirmationText || ""}
        confirmLabel={pendingConfirmation?.confirmLabel}
        variant={pendingConfirmation?.variant}
        confirmDisabled={
          pendingConfirmation?.transition === "cancel-closure" &&
          cancelClosureReason.trim().length < 3
        }
        isLoading={saving === pendingConfirmation?.item?.id}
        onConfirm={runConfirmedAction}
        onCancel={() => {
          setPendingConfirmation(null);
          setCancelClosureReason("");
        }}
      >
        {pendingConfirmation?.transition === "cancel-closure" ? (
          <Input
            label="Reason"
            value={cancelClosureReason}
            onChange={(event) => setCancelClosureReason(event.target.value)}
            placeholder="Explain why this term should remain open"
          />
        ) : null}
      </TypedConfirmationDialog>

      <Modal
        open={Boolean(termPlanPrompt)}
        onClose={() => setTermPlanPrompt(null)}
        title={`Choose a plan for ${termLabel(termPlanPrompt?.term?.name || "this term")}`}
        description="Every term makes a deliberate operating-plan choice when it opens. Free requires no payment; paid plans continue through Billing and Paystack."
      >
        <div className="space-y-4">
          <div className="rounded-xl border border-border bg-surface-muted/30 p-4">
            <p className="text-sm font-semibold text-text">Free is available as the baseline option.</p>
            <p className="mt-1 text-sm leading-6 text-text-muted">
              Weave will validate the school&apos;s active operational resources before opening this term on Free. Paid plans provide higher limits and additional features.
            </p>
          </div>
          <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
            <Button
              onClick={activateFreeAndOpen}
              disabled={saving === termPlanPrompt?.term?.id}
            >
              Continue with Free
            </Button>
            <Button
              variant="outline"
              onClick={openPaidPlans}
              disabled={saving === termPlanPrompt?.term?.id}
            >
              View paid plans
            </Button>
          </div>
        </div>
      </Modal>
    </>
  );
}

function SessionActions({ item, busy, onConfirm, onEdit }) {
  if (item.status === "draft") {
    return (
      <>
        <Button
          type="button"
          size="small"
          disabled={busy}
          onClick={() =>
            onConfirm({
              type: "open-session",
              item,
              title: "Open academic session",
              description: `${item.name} will become the current operational school year.`,
              confirmationText: CONFIRM_OPEN_SESSION,
              confirmLabel: "Open session",
              variant: "primary",
            })
          }
        >
          Open
        </Button>
        <Button type="button" size="small" variant="outline" onClick={() => onEdit(item)}>
          Edit
        </Button>
        <Button
          type="button"
          size="small"
          variant="danger"
          disabled={busy}
          onClick={() =>
            onConfirm({
              type: "delete-session",
              item,
              title: "Delete academic session",
              description: `${item.name} can only be deleted when the backend dependency check confirms it is unused.`,
              confirmationText: CONFIRM_DELETE_SESSION,
              confirmLabel: "Delete session",
              variant: "danger",
            })
          }
        >
          Delete
        </Button>
      </>
    );
  }
  if (item.status === "open") {
    return (
      <Button type="button" size="small" variant="outline" onClick={() => onEdit(item)}>
        Configure
      </Button>
    );
  }
  return null;
}

function TermActions({ item, busy, onConfirm }) {
  if (item.status === "draft") {
    return (
      <>
        <Button
          type="button"
          size="small"
          disabled={busy}
          onClick={() =>
            onConfirm({
              type: "term-transition",
              item,
              transition: "open",
              title: "Open academic term",
              description: `${termLabel(item.name)} will first validate its selected Free or paid term plan.`,
              confirmationText: CONFIRM_OPEN_TERM,
              confirmLabel: "Open term",
              variant: "primary",
            })
          }
        >
          Open
        </Button>
        <Button
          type="button"
          size="small"
          variant="danger"
          disabled={busy}
          onClick={() =>
            onConfirm({
              type: "delete-term",
              item,
              title: "Delete academic term",
              description: `${termLabel(item.name)} can only be deleted when it has no protected dependencies.`,
              confirmationText: CONFIRM_DELETE_TERM,
              confirmLabel: "Delete term",
              variant: "danger",
            })
          }
        >
          Delete
        </Button>
      </>
    );
  }
  if (item.status === "open") {
    return (
      <Button
        type="button"
        size="small"
        variant="outline"
        disabled={busy}
        onClick={() =>
          onConfirm({
            type: "term-transition",
            item,
            transition: "start-closing",
            title: "Start closing academic term",
            description: `${termLabel(item.name)} will enter closing after backend readiness checks pass.`,
            confirmationText: CONFIRM_START_TERM_CLOSING,
            confirmLabel: "Start closing",
            variant: "danger",
          })
        }
      >
        Start closing
      </Button>
    );
  }
  if (item.status === "closing") {
    return (
      <>
        <Button
          type="button"
          size="small"
          variant="success"
          disabled={busy}
          onClick={() =>
            onConfirm({
              type: "term-transition",
              item,
              transition: "finalize-close",
              title: "Finalize academic term",
              description: `${termLabel(item.name)} becomes closed and read-only after final readiness checks.`,
              confirmationText: CONFIRM_FINALIZE_TERM_CLOSE,
              confirmLabel: "Finalize close",
              variant: "danger",
            })
          }
        >
          Finalize
        </Button>
        <Button
          type="button"
          size="small"
          variant="outline"
          disabled={busy}
          onClick={() =>
            onConfirm({
              type: "term-transition",
              item,
              transition: "cancel-closure",
              title: "Cancel term closure",
              description: `${termLabel(item.name)} will return to Open so academic work can continue.`,
              confirmationText: CONFIRM_CANCEL_TERM_CLOSURE,
              confirmLabel: "Cancel closure",
              variant: "outline",
            })
          }
        >
          Cancel closure
        </Button>
      </>
    );
  }
  return null;
}

export default AcademicPeriodsWorkspace;
