import {
  BookOpen,
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  GraduationCap,
  MoreHorizontal,
  Search,
  Trash2,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import Badge from "../../components/ui/Badge";
import Button from "../../components/ui/Button";
import Dropdown from "../../components/ui/Dropdown";
import Modal from "../../components/ui/Modal";
import { useToast } from "../../hooks/useToast";
import { getErrorMessage, parseApiError } from "../../services/api";
import { academicService } from "../../services/academicService";
import { subjectService } from "../../services/subject.service";
import { subscriptionService } from "../../services/subscriptionService";
import { termOpenPreflightBlocker } from "../../services/termOpenPreflight";
import TypedConfirmationDialog from "./TypedConfirmationDialog";
import {
  CheckboxControl,
  FormActions,
  Input,
  RecordList,
  SelectControl,
  WorkspaceGrid,
  WorkspacePanel,
} from "./AcademicWorkspacePrimitives";

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
const BLANK_SCALE = {
  grade: "",
  min_score: "",
  max_score: "",
  remark: "",
  is_active: true,
};
const BLANK_SUBJECT = { name: "", code: "", description: "" };
const CONFIRM_OPEN_SESSION = "OPEN_ACADEMIC_SESSION";
const CONFIRM_OPEN_TERM = "OPEN_ACADEMIC_TERM";
const CONFIRM_START_TERM_CLOSING = "START_TERM_CLOSING";
const CONFIRM_FINALIZE_TERM_CLOSE = "FINALIZE_TERM_CLOSE";
const CONFIRM_CANCEL_TERM_CLOSURE = "CANCEL_TERM_CLOSURE";
const CONFIRM_DELETE_SESSION = "DELETE_ACADEMIC_SESSION";
const CONFIRM_DELETE_TERM = "DELETE_ACADEMIC_TERM";
const SUBJECT_PAGE_SIZE = 24;
const ACADEMIC_PAGE_SIZE = 25;

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

const subjectStatus = (item) =>
  item.archived_at
    ? "archived"
    : item.is_active === false
      ? "inactive"
      : "active";

const dependencyLabels = {
  curriculum_subjects: "Curriculum subjects attached to academic levels",
  teacher_links: "Teacher capability links",
  teacher_assignments: "Teacher assignments",
  results: "Student result rows",
  report_card_lines: "Report-card subject lines",
  active_curriculum_subjects:
    "Active curriculum subjects attached to academic levels",
  active_teacher_links: "Active teacher capability links",
  active_teacher_assignments: "Active teacher assignments",
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

const dependencyCountItems = (counts = {}) =>
  Object.entries(counts)
    .filter(([, count]) => Number(count) > 0)
    .map(([key, count]) => ({
      key,
      label: dependencyLabels[key] || key.replaceAll("_", " "),
      count,
    }));

const formatDependencyMessage = (preview) => {
  const messages = preview?.blocker_messages || [];
  if (messages.length) return messages.join(" ");
  return dependencyCountItems(preview?.dependency_counts)
    .map((blocker) => `${blocker.label}: ${blocker.count}`)
    .join("; ");
};

function SubjectForm({ form, setForm, saving, editing, onSubmit, onCancel }) {
  return (
    <form className="space-y-3" onSubmit={onSubmit}>
      <Input
        label="Subject name"
        value={form.name}
        onChange={(event) =>
          setForm((current) => ({ ...current, name: event.target.value }))
        }
        required
      />
      <Input
        label="Subject code"
        value={form.code}
        onChange={(event) =>
          setForm((current) => ({ ...current, code: event.target.value }))
        }
        placeholder="MTH"
      />
      <Input
        label="Description"
        value={form.description}
        onChange={(event) =>
          setForm((current) => ({
            ...current,
            description: event.target.value,
          }))
        }
      />
      <FormActions
        submitting={saving === "subject"}
        submitLabel={editing ? "Update subject" : "Create subject"}
        editing={editing}
        onCancel={onCancel}
      />
    </form>
  );
}

function SubjectActionMenu({ item, busy, onAction }) {
  const [open, setOpen] = useState(false);
  const status = subjectStatus(item);
  const actions =
    status === "archived"
      ? [{ key: "restore", label: "Restore", tone: "default" }]
      : status === "inactive"
        ? [
            { key: "activate", label: "Restore to active", tone: "success" },
            { key: "archive", label: "Archive", tone: "danger" },
            ...(item.can_delete
              ? [
                  {
                    key: "delete",
                    label: "Delete",
                    tone: "danger",
                    icon: Trash2,
                  },
                ]
              : []),
          ]
        : [{ key: "deactivate", label: "Deactivate", tone: "default" }];

  return (
    <Dropdown
      open={open}
      onOpenChange={setOpen}
      align="right"
      strategy="fixed"
      className="w-64"
      trigger={
        <Button type="button" size="small" variant="outline" disabled={busy}>
          Actions
          <MoreHorizontal className="h-4 w-4" />
        </Button>
      }
    >
      <div className="grid gap-1">
        {actions.map((action) => {
          const Icon = action.icon;
          return (
            <button
              key={action.key}
              type="button"
              className={`flex min-h-10 items-center gap-2 rounded-xl px-3 py-2 text-left text-sm font-semibold transition hover:bg-surface-muted ${
                action.tone === "danger" ? "text-error" : "text-text-soft"
              }`}
              onClick={() => {
                setOpen(false);
                onAction(item, action.key);
              }}
            >
              {Icon ? <Icon className="h-4 w-4" /> : null}
              {action.label}
            </button>
          );
        })}
      </div>
    </Dropdown>
  );
}

function AcademicSetupWorkspace({
  activeTab,
  onContextChange,
  domain = "sessions",
}) {
  const [sessions, setSessions] = useState([]);
  const [terms, setTerms] = useState([]);
  const [sessionTotal, setSessionTotal] = useState(0);
  const [termTotal, setTermTotal] = useState(0);
  const [sessionPage, setSessionPage] = useState(1);
  const [termPage, setTermPage] = useState(1);
  const [termSearch, setTermSearch] = useState("");
  const [appliedTermSearch, setAppliedTermSearch] = useState("");
  useEffect(() => {
    const timer = window.setTimeout(() => setAppliedTermSearch(termSearch.trim()), 250);
    return () => window.clearTimeout(timer);
  }, [termSearch]);
  const [scales, setScales] = useState([]);
  const [subjects, setSubjects] = useState([]);
  const [subjectTotal, setSubjectTotal] = useState(0);
  const [subjectPage, setSubjectPage] = useState(1);
  const [subjectSearchDraft, setSubjectSearchDraft] = useState("");
  const [subjectSearch, setSubjectSearch] = useState("");
  const [sessionForm, setSessionForm] = useState(BLANK_SESSION);
  const [termForm, setTermForm] = useState(BLANK_TERM);
  const [scaleForm, setScaleForm] = useState(BLANK_SCALE);
  const [subjectForm, setSubjectForm] = useState(BLANK_SUBJECT);
  const [editing, setEditing] = useState({ type: "", id: "" });
  const [saving, setSaving] = useState("");
  const [openingSessionId, setOpeningSessionId] = useState("");
  const [pendingConfirmation, setPendingConfirmation] = useState(null);
  const [checkingTermId, setCheckingTermId] = useState("");
  const [cancelClosureReason, setCancelClosureReason] = useState("");
  const [termPlanPrompt, setTermPlanPrompt] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const { showSuccess, showError } = useToast();

  const subjectLifecycleStatus =
    domain === "subjects" &&
    ["active", "inactive", "archived"].includes(activeTab)
      ? activeTab
      : undefined;
  const academicStatusFilter = ["draft", "open", "closing", "closed"].includes(
    activeTab,
  )
    ? activeTab
    : undefined;
  const editingSession = sessions.find((item) => item.id === editing.id);
  const configuringOpenSession =
    editing.type === "session" && editingSession?.status === "open";

  const loadWorkspace = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [sessionResponse, termResponse, scaleResponse, subjectResponse] =
        await Promise.all([
          academicService.listSessions({
            skip:
              domain === "sessions"
                ? (sessionPage - 1) * ACADEMIC_PAGE_SIZE
                : 0,
            limit: domain === "sessions" ? ACADEMIC_PAGE_SIZE : 100,
            status: domain === "sessions" ? academicStatusFilter : undefined,
          }),
          academicService.listTerms({
            skip: domain === "terms" ? (termPage - 1) * ACADEMIC_PAGE_SIZE : 0,
            limit: domain === "terms" ? ACADEMIC_PAGE_SIZE : 100,
            status: domain === "terms" ? academicStatusFilter : undefined,
            search: domain === "terms" ? appliedTermSearch || undefined : undefined,
          }),
          academicService.listGradingScales({ limit: 100 }),
          subjectService.getSubjects({
            skip:
              domain === "subjects" ? (subjectPage - 1) * SUBJECT_PAGE_SIZE
                : 0,
            limit: domain === "subjects" ? SUBJECT_PAGE_SIZE : 100,
            includeArchived: domain === "subjects",
            search: domain === "subjects" ? subjectSearch : undefined,
            lifecycleStatus: subjectLifecycleStatus,
          }),
        ]);
      const nextSessions = asItems(sessionResponse);
      const nextTerms = asItems(termResponse);
      setSessions(nextSessions);
      setTerms(nextTerms);
      setSessionTotal(Number(sessionResponse?.total || nextSessions.length));
      setTermTotal(Number(termResponse?.total || nextTerms.length));
      setScales(asItems(scaleResponse));
      setSubjects(asItems(subjectResponse));
      setSubjectTotal(Number(subjectResponse?.total || 0));

      const currentSession =
        nextSessions.find((item) => item.is_current) || null;
      const currentTerm = nextTerms.find((item) => item.is_current) || null;
      onContextChange?.({ currentSession, currentTerm });
      setTermForm((current) => ({
        ...current,
        academic_session_id:
          current.academic_session_id ||
          currentSession?.id ||
          nextSessions[0]?.id ||
          "",
      }));
    } catch (err) {
      const message = getErrorMessage(err, "Could not load academic setup.");
      setError(message);
      showError(message);
    } finally {
      setLoading(false);
    }
  }, [
    academicStatusFilter,
    domain,
    onContextChange,
    sessionPage,
    showError,
    subjectLifecycleStatus,
    subjectPage,
    subjectSearch,
    termPage,
  ]);

  useEffect(() => {
    loadWorkspace();
  }, [loadWorkspace]);

  useEffect(() => {
    setSubjectPage(1);
    setSessionPage(1);
    setTermPage(1);
  }, [activeTab, domain, subjectSearch, appliedTermSearch]);

  const sessionOptions = useMemo(
    () => sessions.map((item) => ({ value: item.id, label: item.name })),
    [sessions],
  );
  const visibleSessions = useMemo(
    () =>
      activeTab === "draft"
        ? sessions.filter((item) => item.status === "draft")
        : activeTab === "open"
          ? sessions.filter((item) => item.status === "open")
          : activeTab === "closed"
            ? sessions.filter((item) => item.status === "closed")
            : sessions,
    [activeTab, sessions],
  );

  const resetSession = () => {
    setSessionForm(BLANK_SESSION);
    setEditing({ type: "", id: "" });
  };
  const resetTerm = () => {
    setTermForm((current) => ({
      ...BLANK_TERM,
      academic_session_id:
        sessions.find((item) => item.is_current)?.id ||
        current.academic_session_id ||
        sessions[0]?.id ||
        "",
    }));
    setEditing({ type: "", id: "" });
  };
  const resetScale = () => {
    setScaleForm(BLANK_SCALE);
    setEditing({ type: "", id: "" });
  };
  const resetSubject = () => {
    setSubjectForm(BLANK_SUBJECT);
    setEditing({ type: "", id: "" });
  };

  const saveSession = async (event) => {
    event.preventDefault();
    setSaving("session");
    try {
      const editingSession = sessions.find((item) => item.id === editing.id);
      const payload =
        editing.type === "session" && editingSession?.status === "open"
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
      if (editing.type === "session") {
        await academicService.updateSession(editing.id, payload);
      } else {
        await academicService.createSession(payload);
      }
      showSuccess(
        editing.type === "session"
          ? "Academic session updated."
          : "Academic session created.",
      );
      resetSession();
      await loadWorkspace();
    } catch (err) {
      showError(getErrorMessage(err, "Could not save academic session."));
    } finally {
      setSaving("");
    }
  };

  const openSession = async (item) => {
    setOpeningSessionId(item.id);
    try {
      await academicService.openSession(item.id);
      showSuccess("Academic session opened.");
      await loadWorkspace();
    } catch (err) {
      showError(getErrorMessage(err, "Could not open academic session."));
    } finally {
      setOpeningSessionId("");
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
      if (sessions.length === 1 && sessionPage > 1) {
        setSessionPage((current) => Math.max(1, current - 1));
      }
      await loadWorkspace();
    } catch (err) {
      showError(getErrorMessage(err, "Could not delete academic session."));
    } finally {
      setSaving("");
      setPendingConfirmation(null);
    }
  };

  const prepareTermTransition = async (item, transition) => {
    const isOpen = transition === "open";
    const isStart = transition === "start-closing";

    if (isOpen) {
      setCheckingTermId(item.id);
      try {
        const [dependencyPreview, currentTerms] = await Promise.all([
          academicService.getTermDependencies(item.id),
          academicService.listTerms({ is_current: true, limit: 100 }),
        ]);
        const blocker = termOpenPreflightBlocker({
          currentTerms,
          targetTermId: item.id,
          dependencyPreview,
        });
        if (blocker) {
          showError(blocker);
          return;
        }
      } catch (err) {
        showError(getErrorMessage(err, "Could not check whether this term is ready to open."));
        return;
      } finally {
        setCheckingTermId("");
      }
    }

    setPendingConfirmation({
      type: "term-transition",
      item,
      transition,
      title: `${isOpen ? "Open" : isStart ? "Start closing" : "Finalize"} academic term`,
      description: `${termLabel(item.name)} - ${
        sessions.find((session) => session.id === item.academic_session_id)?.name ||
        "Unknown session"
      }`,
      confirmationText: isOpen
        ? CONFIRM_OPEN_TERM
        : isStart
          ? CONFIRM_START_TERM_CLOSING
          : CONFIRM_FINALIZE_TERM_CLOSE,
      confirmLabel: isOpen
        ? "Open term"
        : isStart
          ? "Start closing"
          : "Finalize close",
      variant: isOpen ? "primary" : "danger",
    });
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
      await loadWorkspace();
    } catch (err) {
      const parsed = parseApiError(
        err,
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

  const activateFreeAndOpen = async () => {
    if (!termPlanPrompt?.term?.id) return;
    setSaving(termPlanPrompt.term.id);
    try {
      await subscriptionService.activateFreeTerm(termPlanPrompt.term.id);
      await academicService.openTerm(termPlanPrompt.term.id);
      showSuccess("Free plan selected and academic term opened.");
      setTermPlanPrompt(null);
      await loadWorkspace();
    } catch (error) {
      showError(getErrorMessage(error, "Could not select the Free plan."));
    } finally {
      setSaving("");
    }
  };

  const payForSelectedPlan = async () => {
    if (!termPlanPrompt?.term?.id) return;
    setSaving(termPlanPrompt.term.id);
    try {
      const checkout = await subscriptionService.initializeTermCheckout({
        academic_term_id: termPlanPrompt.term.id,
        plan_code: termPlanPrompt.suggested_plan,
      });
      subscriptionService.saveTermPaymentOpenIntent({
        academicTermId: termPlanPrompt.term.id,
        reference: checkout.reference,
      });
      window.location.assign(subscriptionService.checkoutRedirectUrl(checkout));
    } catch (error) {
      showError(getErrorMessage(error, "Could not start term payment."));
      setSaving("");
    }
  };

  const deleteTerm = async (item) => {
    setSaving(item.id);
    try {
      const preview = await academicService.getTermDependencies(item.id);
      if (!preview?.can_delete) {
        showError(
          formatDependencyMessage(preview) || "This term cannot be deleted.",
        );
        return;
      }
      await academicService.deleteTerm(item.id);
      showSuccess("Academic term deleted.");
      if (terms.length === 1 && termPage > 1) {
        setTermPage((current) => Math.max(1, current - 1));
      }
      await loadWorkspace();
    } catch (err) {
      showError(getErrorMessage(err, "Could not delete academic term."));
    } finally {
      setSaving("");
      setPendingConfirmation(null);
    }
  };

  const runConfirmedAction = () => {
    if (!pendingConfirmation) return;
    if (pendingConfirmation.type === "open-session") {
      openSession(pendingConfirmation.item);
      return;
    }
    if (pendingConfirmation.type === "delete-session") {
      deleteSession(pendingConfirmation.item);
      return;
    }
    if (pendingConfirmation.type === "term-transition") {
      transitionTerm(pendingConfirmation.item, pendingConfirmation.transition);
      return;
    }
    if (pendingConfirmation.type === "delete-term") {
      deleteTerm(pendingConfirmation.item);
      return;
    }
    if (pendingConfirmation.type === "subject-lifecycle") {
      updateSubjectLifecycle(
        pendingConfirmation.item,
        pendingConfirmation.action,
      );
    }
  };

  const saveTerm = async (event) => {
    event.preventDefault();
    setSaving("term");
    try {
      const payload = {
        academic_session_id: termForm.academic_session_id,
        name: termForm.name,
        start_date: termForm.start_date || null,
        end_date: termForm.end_date || null,
      };
      if (editing.type === "term") {
        await academicService.updateTerm(editing.id, payload);
      } else {
        await academicService.createTerm(payload);
      }
      showSuccess(
        editing.type === "term"
          ? "Academic term updated."
          : "Academic term created.",
      );
      resetTerm();
      await loadWorkspace();
    } catch (err) {
      showError(getErrorMessage(err, "Could not save academic term."));
    } finally {
      setSaving("");
    }
  };

  const updateSubjectLifecycle = async (item, action) => {
    setSaving(item.id);
    try {
      if (action === "activate") await subjectService.activateSubject(item.id);
      if (action === "deactivate")
        await subjectService.deactivateSubject(item.id);
      if (action === "archive") await subjectService.archiveSubject(item.id);
      if (action === "restore") await subjectService.restoreSubject(item.id);
      if (action === "delete") await subjectService.deleteSubject(item.id);
      showSuccess(`Subject ${action}d.`);
      if (action === "delete" && subjects.length === 1 && subjectPage > 1) {
        setSubjectPage((current) => Math.max(1, current - 1));
      }
      await loadWorkspace();
    } catch (err) {
      const parsed = parseApiError(err, `Could not ${action} subject.`);
      const blockers = dependencyCountItems(parsed.data?.dependency_counts);
      const blockerText = blockers.length
        ? ` ${blockers.map((blocker) => `${blocker.label}: ${blocker.count}`).join("; ")}`
        : "";
      showError(`${parsed.message}${blockerText}`);
    } finally {
      setSaving("");
      setPendingConfirmation(null);
    }
  };

  const confirmSubjectAction = (item, action) => {
    const config = {
      activate: {
        title: "Restore deactivated subject",
        confirmationText: "ACTIVATE_SUBJECT",
        confirmLabel: "Restore to active",
        variant: "success",
        description: `${item.name} will become active again and available for curriculum setup and teacher assignments.`,
      },
      deactivate: {
        title: "Deactivate subject",
        confirmationText: "DEACTIVATE_SUBJECT",
        confirmLabel: "Deactivate subject",
        variant: "danger",
        description: `${item.name} will stop being available for new academic workflows.`,
      },
      archive: {
        title: "Archive subject",
        confirmationText: "ARCHIVE_SUBJECT",
        confirmLabel: "Archive subject",
        variant: "danger",
        description: `${item.name} will be hidden from normal workflows. Historical records are preserved.`,
      },
      restore: {
        title: "Restore subject",
        confirmationText: "RESTORE_SUBJECT",
        confirmLabel: "Restore subject",
        variant: "primary",
        description: `${item.name} will be restored as inactive. Activate it separately when it is ready for use.`,
      },
      delete: {
        title: "Delete subject",
        confirmationText: "DELETE_SUBJECT",
        confirmLabel: "Delete subject",
        variant: "danger",
        description: `${item.name} will be permanently deleted. This is only available for unused inactive subjects.`,
      },
    }[action];
    setPendingConfirmation({
      type: "subject-lifecycle",
      item,
      action,
      ...config,
    });
  };

  const saveScale = async (event) => {
    event.preventDefault();
    setSaving("scale");
    try {
      const payload = {
        grade: scaleForm.grade,
        min_score: Number(scaleForm.min_score),
        max_score: Number(scaleForm.max_score),
        remark: scaleForm.remark || null,
        is_active: scaleForm.is_active,
      };
      if (editing.type === "scale") {
        await academicService.updateGradingScale(editing.id, payload);
      } else {
        await academicService.createGradingScale(payload);
      }
      showSuccess(
        editing.type === "scale"
          ? "Grading scale updated."
          : "Grading scale created.",
      );
      resetScale();
      await loadWorkspace();
    } catch (err) {
      showError(getErrorMessage(err, "Could not save grading scale."));
    } finally {
      setSaving("");
    }
  };

  const saveSubject = async (event) => {
    event.preventDefault();
    setSaving("subject");
    try {
      const payload = {
        name: subjectForm.name,
        code: subjectForm.code || null,
        description: subjectForm.description || null,
      };
      if (editing.type === "subject") {
        await subjectService.updateSubject(editing.id, payload);
      } else {
        await subjectService.createSubject(payload);
      }
      showSuccess(
        editing.type === "subject" ? "Subject updated." : "Subject created.",
      );
      resetSubject();
      await loadWorkspace();
    } catch (err) {
      showError(getErrorMessage(err, "Could not save subject."));
    } finally {
      setSaving("");
    }
  };

  const periodsView = (
    <div className="space-y-4">
      {domain === "sessions" ? (
        <WorkspaceGrid
          editor={
            activeTab === "create" || editing.type === "session" ? (
              <WorkspacePanel
                title={
                  configuringOpenSession
                    ? "Configure session"
                    : editing.type === "session"
                      ? "Edit session"
                      : "Create session"
                }
              >
                <form className="space-y-3" onSubmit={saveSession}>
                  <Input
                    label="Session name"
                    value={sessionForm.name}
                    onChange={(event) =>
                      setSessionForm((current) => ({
                        ...current,
                        name: event.target.value,
                      }))
                    }
                    placeholder="2026/2027"
                    minLength={9}
                    maxLength={9}
                    required
                    disabled={configuringOpenSession}
                  />
                  <div className="grid gap-3 sm:grid-cols-2">
                    <Input
                      label="Start date"
                      type="date"
                      value={sessionForm.start_date}
                      onChange={(event) =>
                        setSessionForm((current) => ({
                          ...current,
                          start_date: event.target.value,
                        }))
                      }
                      disabled={configuringOpenSession}
                    />
                    <Input
                      label="End date"
                      type="date"
                      value={sessionForm.end_date}
                      onChange={(event) =>
                        setSessionForm((current) => ({
                          ...current,
                          end_date: event.target.value,
                        }))
                      }
                      disabled={configuringOpenSession}
                    />
                  </div>
                  <SelectControl
                    label="Next session"
                    value={sessionForm.next_academic_session_id}
                    onChange={(value) =>
                      setSessionForm((current) => ({
                        ...current,
                        next_academic_session_id: value,
                      }))
                    }
                    options={sessionOptions.filter(
                      (item) => item.value !== editing.id,
                    )}
                    placeholder="Optional progression target"
                  />
                  <FormActions
                    submitting={saving === "session"}
                    submitLabel={
                      configuringOpenSession
                        ? "Save configuration"
                        : editing.type === "session"
                          ? "Update session"
                          : "Create session"
                    }
                    editing={editing.type === "session"}
                    onCancel={resetSession}
                  />
                </form>
              </WorkspacePanel>
            ) : null
          }
          content={
            activeTab === "create" ? null : (
              <WorkspacePanel
                title="Academic sessions"
                description="Create and configure sessions here. Use the Progression workspace for staged session closing, terminal graduation approval, and finalization."
              >
                <div className="max-h-[32rem] space-y-3 overflow-y-auto overscroll-contain pr-1">
                  {visibleSessions.length === 0 ? (
                    <p className="rounded-2xl border border-dashed border-border p-5 text-sm text-text-muted">
                      No academic sessions have been created.
                    </p>
                  ) : (
                    visibleSessions.map((item) => (
                      <div
                        key={item.id}
                        className="rounded-2xl border border-border/70 bg-surface px-4 py-4"
                      >
                        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                          <div>
                            <div className="flex flex-wrap items-center gap-2">
                              <p className="font-semibold text-text">
                                {item.name}
                              </p>
                              <Badge
                                variant={
                                  item.is_current ? "success" : "default"
                                }
                              >
                                {item.status ||
                                  (item.is_current ? "current" : "draft")}
                              </Badge>
                            </div>
                            <p className="mt-1 text-xs text-text-muted">
                              {dateLabel(item.start_date)} –{" "}
                              {dateLabel(item.end_date)}
                            </p>
                            {item.next_academic_session_id ? (
                              <p className="mt-1 text-xs text-text-muted">
                                Next:{" "}
                                {sessions.find(
                                  (session) =>
                                    session.id ===
                                    item.next_academic_session_id,
                                )?.name || "Configured session"}
                              </p>
                            ) : null}
                          </div>
                          <div className="flex flex-wrap gap-2">
                            {item.status === "draft" ? (
                              <Button
                                type="button"
                                size="small"
                                onClick={() =>
                                  setPendingConfirmation({
                                    type: "open-session",
                                    item,
                                    title: "Open academic session",
                                    description: item.name,
                                    confirmationText: CONFIRM_OPEN_SESSION,
                                    confirmLabel: "Open session",
                                    variant: "primary",
                                  })
                                }
                                disabled={Boolean(openingSessionId)}
                              >
                                {openingSessionId === item.id
                                  ? "Opening..."
                                  : "Open session"}
                              </Button>
                            ) : null}
                            {["draft", "open"].includes(item.status) ? (
                              <Button
                                type="button"
                                size="small"
                                variant="outline"
                                onClick={() => {
                                  setEditing({ type: "session", id: item.id });
                                  setSessionForm({
                                    name: item.name || "",
                                    start_date: item.start_date || "",
                                    end_date: item.end_date || "",
                                    next_academic_session_id:
                                      item.next_academic_session_id || "",
                                  });
                                }}
                              >
                                {item.status === "open" ? "Configure" : "Edit"}
                              </Button>
                            ) : null}
                            {item.status === "draft" ? (
                              <Button
                                type="button"
                                size="small"
                                variant="danger"
                                onClick={() =>
                                  setPendingConfirmation({
                                    type: "delete-session",
                                    item,
                                    title: "Delete academic session",
                                    description: item.name,
                                    confirmationText: CONFIRM_DELETE_SESSION,
                                    confirmLabel: "Delete session",
                                    variant: "danger",
                                  })
                                }
                                disabled={saving === item.id}
                              >
                                Delete
                              </Button>
                            ) : null}
                          </div>
                        </div>
                      </div>
                    ))
                  )}
                </div>
                {domain === "sessions" && sessionTotal > ACADEMIC_PAGE_SIZE ? (
                  <div className="mt-4 flex items-center justify-between gap-3 text-sm text-text-muted">
                    <span>
                      Page {sessionPage} of{" "}
                      {Math.max(
                        1,
                        Math.ceil(sessionTotal / ACADEMIC_PAGE_SIZE),
                      )}
                    </span>
                    <div className="flex gap-2">
                      <Button
                        type="button"
                        size="small"
                        variant="outline"
                        disabled={sessionPage === 1}
                        onClick={() =>
                          setSessionPage((current) => Math.max(1, current - 1))
                        }
                      >
                        <ChevronLeft className="h-4 w-4" />
                      </Button>
                      <Button
                        type="button"
                        size="small"
                        variant="outline"
                        disabled={
                          sessionPage >=
                          Math.ceil(sessionTotal / ACADEMIC_PAGE_SIZE)
                        }
                        onClick={() => setSessionPage((current) => current + 1)}
                      >
                        <ChevronRight className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>
                ) : null}
              </WorkspacePanel>
            )
          }
        />
      ) : null}

      {domain === "terms" ? (
        <WorkspaceGrid
          editor={
            activeTab === "create" || editing.type === "term" ? (
              <WorkspacePanel
                title={editing.type === "term" ? "Edit term" : "Create term"}
              >
                <form className="space-y-3" onSubmit={saveTerm}>
                  <SelectControl
                    label="Academic session"
                    value={termForm.academic_session_id}
                    onChange={(value) =>
                      setTermForm((current) => ({
                        ...current,
                        academic_session_id: value,
                      }))
                    }
                    options={sessionOptions}
                    required
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
                  <div className="grid gap-3 sm:grid-cols-2">
                    <Input
                      label="Start date"
                      type="date"
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
                    submitLabel={
                      editing.type === "term" ? "Update term" : "Create term"
                    }
                    editing={editing.type === "term"}
                    onCancel={resetTerm}
                  />
                </form>
              </WorkspacePanel>
            ) : null
          }
          content={
            activeTab === "create" ? null : (
              <RecordList
                title={`Academic terms (${termTotal})`}
                searchValue={termSearch}
                onSearchChange={(value) => { setTermPage(1); setTermSearch(value); }}
                listClassName="max-h-[32rem] overflow-y-auto overscroll-contain pr-1"
                actions={
                  termTotal > ACADEMIC_PAGE_SIZE ? (
                    <div className="flex items-center justify-end gap-2">
                      <Button
                        type="button"
                        size="small"
                        variant="outline"
                        disabled={termPage === 1}
                        onClick={() =>
                          setTermPage((current) => Math.max(1, current - 1))
                        }
                      >
                        <ChevronLeft className="h-4 w-4" />
                      </Button>
                      <Button
                        type="button"
                        size="small"
                        variant="outline"
                        disabled={
                          termPage >= Math.ceil(termTotal / ACADEMIC_PAGE_SIZE)
                        }
                        onClick={() => setTermPage((current) => current + 1)}
                      >
                        <ChevronRight className="h-4 w-4" />
                      </Button>
                    </div>
                  ) : null
                }
                items={
                  activeTab === "draft"
                    ? terms.filter((item) => item.status === "draft")
                    : activeTab === "open"
                      ? terms.filter((item) => item.status === "open")
                      : activeTab === "closing"
                        ? terms.filter((item) => item.status === "closing")
                        : activeTab === "closed"
                          ? terms.filter((item) => item.status === "closed")
                          : terms
                }
                emptyIcon={CalendarDays}
                emptyTitle="No academic terms"
                emptyDescription="Create a term after creating an academic session."
                renderTitle={(item) => termLabel(item.name)}
                renderMeta={(item) =>
                  sessions.find(
                    (session) => session.id === item.academic_session_id,
                  )?.name || "Unknown session"
                }
                renderDescription={(item) =>
                  `${dateLabel(item.start_date)} – ${dateLabel(item.end_date)}`
                }
                renderStatus={(item) =>
                  item.is_current ? "current" : item.status
                }
                canEdit={(item) => item.status === "draft"}
                onEdit={(item) => {
                  setEditing({ type: "term", id: item.id });
                  setTermForm({
                    academic_session_id: item.academic_session_id || "",
                    name: item.name || "first_term",
                    start_date: item.start_date || "",
                    end_date: item.end_date || "",
                  });
                }}
                renderActions={(item) => (
                  <>
                    {["draft", "open", "closing"].includes(item.status) ? (
                      <Button
                        type="button"
                        size="small"
                        variant="outline"
                        disabled={
                          saving === item.id || checkingTermId === item.id
                        }
                        onClick={() => {
                          const transition =
                            item.status === "draft"
                              ? "open"
                              : item.status === "open"
                                ? "start-closing"
                                : "finalize-close";
                          prepareTermTransition(item, transition);
                        }}
                      >
                        {item.status === "draft" && checkingTermId === item.id
                          ? "Checking..."
                          : item.status === "draft"
                            ? `Open ${termLabel(item.name)}`
                            : item.status === "open"
                              ? `Start Closing ${termLabel(item.name)}`
                              : `Finalize ${termLabel(item.name)}`}
                      </Button>
                    ) : null}
                    {item.status === "closing" ? (
                      <Button
                        type="button"
                        size="small"
                        variant="outline"
                        disabled={saving === item.id}
                        onClick={() => {
                          setCancelClosureReason("");
                          setPendingConfirmation({
                            type: "term-transition",
                            item,
                            transition: "cancel-closure",
                            title: "Cancel term closure",
                            description: `${termLabel(item.name)} will return to Open so academic work can continue. Existing results, calendars, and reports remain available.`,
                            confirmationText: CONFIRM_CANCEL_TERM_CLOSURE,
                            confirmLabel: "Cancel closure",
                            variant: "outline",
                          });
                        }}
                      >
                        Cancel Closure
                      </Button>
                    ) : null}
                    {item.status === "draft" ? (
                      <Button
                        type="button"
                        size="small"
                        variant="danger"
                        disabled={saving === item.id}
                        onClick={() =>
                          setPendingConfirmation({
                            type: "delete-term",
                            item,
                            title: "Delete academic term",
                            description: termLabel(item.name),
                            confirmationText: CONFIRM_DELETE_TERM,
                            confirmLabel: "Delete term",
                            variant: "danger",
                          })
                        }
                      >
                        Delete
                      </Button>
                    ) : null}
                  </>
                )}
              />
            )
          }
        />
      ) : null}

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
        isLoading={
          pendingConfirmation?.type === "open-session"
            ? openingSessionId === pendingConfirmation.item?.id
            : saving === pendingConfirmation?.item?.id
        }
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
            placeholder="Explain why this term should stay open"
          />
        ) : null}
      </TypedConfirmationDialog>
      <Modal
        open={Boolean(termPlanPrompt)}
        onClose={() => setTermPlanPrompt(null)}
        title={`Choose a plan for ${termLabel(termPlanPrompt?.term?.name || "this term")}`}
        description="This term passed the opening pre-check and now needs an operating plan. A payment made from this flow belongs only to this term, and Weave re-checks opening safety before activating it."
      >
        <div className="space-y-4">
          <div className="rounded-2xl border border-border bg-surface-muted/30 p-4">
            <p className="text-sm text-text-muted">Suggested plan</p>
            <p className="mt-1 text-lg font-semibold text-text">
              {termLabel(termPlanPrompt?.suggested_plan || "free")}
            </p>
            <p className="mt-1 text-sm text-text-muted">
              {termPlanPrompt?.payment_required
                ? `₦${(Number(termPlanPrompt?.amount_kobo || 0) / 100).toLocaleString()} for this academic term`
                : "₦0 for this academic term"}
            </p>
            <p className="mt-2 text-xs leading-5 text-text-muted">
              This is only a suggestion. You can use Free or compare every
              available plan before opening the term.
            </p>
          </div>
          <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
            {termPlanPrompt?.payment_required ? (
              <Button
                onClick={payForSelectedPlan}
                disabled={saving === termPlanPrompt?.term?.id}
              >
                Pay ₦
                {(Number(termPlanPrompt?.amount_kobo || 0) / 100).toLocaleString()} for{" "}
                {termLabel(termPlanPrompt?.suggested_plan)}
              </Button>
            ) : null}
            <Button
              variant={termPlanPrompt?.payment_required ? "outline" : "primary"}
              onClick={activateFreeAndOpen}
              disabled={saving === termPlanPrompt?.term?.id}
            >
              Use Free for this term
            </Button>
            <Button
              variant="ghost"
              onClick={() => {
                window.location.assign(
                  `/admin/billing/plans?term=${encodeURIComponent(termPlanPrompt?.term?.id || "")}&intent=open-term&origin=academic-terms`,
                );
              }}
            >
              Compare all plans
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );

  const gradingView = (
    <WorkspaceGrid
      editor={
        <WorkspacePanel
          title={
            editing.type === "scale"
              ? "Edit grading scale"
              : "Create grading scale"
          }
          description="Score ranges may not overlap and must remain between 0 and 100."
        >
          <form className="space-y-3" onSubmit={saveScale}>
            <Input
              label="Grade"
              value={scaleForm.grade}
              onChange={(event) =>
                setScaleForm((current) => ({
                  ...current,
                  grade: event.target.value,
                }))
              }
              placeholder="A"
              required
            />
            <div className="grid gap-3 sm:grid-cols-2">
              <Input
                label="Minimum score"
                type="number"
                min="0"
                max="100"
                value={scaleForm.min_score}
                onChange={(event) =>
                  setScaleForm((current) => ({
                    ...current,
                    min_score: event.target.value,
                  }))
                }
                required
              />
              <Input
                label="Maximum score"
                type="number"
                min="0"
                max="100"
                value={scaleForm.max_score}
                onChange={(event) =>
                  setScaleForm((current) => ({
                    ...current,
                    max_score: event.target.value,
                  }))
                }
                required
              />
            </div>
            <Input
              label="Remark"
              value={scaleForm.remark}
              onChange={(event) =>
                setScaleForm((current) => ({
                  ...current,
                  remark: event.target.value,
                }))
              }
              placeholder="Excellent"
            />
            <CheckboxControl
              label="Active scale"
              checked={scaleForm.is_active}
              onChange={(value) =>
                setScaleForm((current) => ({ ...current, is_active: value }))
              }
            />
            <FormActions
              submitting={saving === "scale"}
              submitLabel={
                editing.type === "scale" ? "Update scale" : "Create scale"
              }
              editing={editing.type === "scale"}
              onCancel={resetScale}
            />
          </form>
        </WorkspacePanel>
      }
      content={
        <RecordList
          title="Grading scales"
          description="The active grade boundaries used when computing results."
          items={
            activeTab === "active"
              ? scales.filter((item) => item.is_active)
              : activeTab === "inactive"
                ? scales.filter((item) => !item.is_active)
                : scales
          }
          emptyIcon={GraduationCap}
          emptyTitle="No grading scales"
          emptyDescription="Add grade boundaries before publishing results."
          renderTitle={(item) => item.grade}
          renderMeta={(item) => `${item.min_score} – ${item.max_score}`}
          renderDescription={(item) => item.remark || "No remark"}
          renderStatus={(item) => (item.is_active ? "active" : "inactive")}
          onEdit={(item) => {
            setEditing({ type: "scale", id: item.id });
            setScaleForm({
              grade: item.grade || "",
              min_score: item.min_score ?? "",
              max_score: item.max_score ?? "",
              remark: item.remark || "",
              is_active: item.is_active !== false,
            });
          }}
        />
      }
    />
  );

  const gradingListView = (
    <RecordList
      title="Grading scales"
      description="The grade boundaries used when computing results."
      items={
        activeTab === "active"
          ? scales.filter((item) => item.is_active)
          : activeTab === "inactive"
            ? scales.filter((item) => !item.is_active)
            : scales
      }
      emptyIcon={GraduationCap}
      emptyTitle="No grading scales"
      emptyDescription="Create grade boundaries before publishing results."
      renderTitle={(item) => item.grade}
      renderMeta={(item) => `${item.min_score} - ${item.max_score}`}
      renderDescription={(item) => item.remark || "No remark"}
      renderStatus={(item) => (item.is_active ? "active" : "inactive")}
      onEdit={(item) => {
        setEditing({ type: "scale", id: item.id });
        setScaleForm({
          grade: item.grade || "",
          min_score: item.min_score ?? "",
          max_score: item.max_score ?? "",
          remark: item.remark || "",
          is_active: item.is_active !== false,
        });
      }}
    />
  );

  const subjectPageCount = Math.max(
    1,
    Math.ceil(subjectTotal / SUBJECT_PAGE_SIZE),
  );
  const subjectListItems = subjects;
  const subjectEmptyTitle =
    subjectSearch || subjectLifecycleStatus
      ? "No matching subjects"
      : "No subjects";
  const subjectEmptyDescription =
    subjectSearch || subjectLifecycleStatus
      ? "Try another search or lifecycle filter."
      : "Create the first subject in this school workspace.";
  const subjectSearchControls = (
    <form
      className="flex flex-col gap-2 sm:flex-row"
      onSubmit={(event) => {
        event.preventDefault();
        setSubjectPage(1);
        setSubjectSearch(subjectSearchDraft.trim());
      }}
    >
      <Input
        label="Search"
        value={subjectSearchDraft}
        onChange={(event) => setSubjectSearchDraft(event.target.value)}
        placeholder="Name, code, or description"
      />
      <div className="flex gap-2 sm:items-end">
        <Button type="submit" variant="outline">
          <Search className="h-4 w-4" />
          Search
        </Button>
        {subjectSearch ? (
          <Button
            type="button"
            variant="ghost"
            onClick={() => {
              setSubjectSearchDraft("");
              setSubjectSearch("");
              setSubjectPage(1);
            }}
          >
            Clear
          </Button>
        ) : null}
      </div>
    </form>
  );
  const subjectPager = (
    <div className="mt-4 flex flex-col gap-2 text-sm text-text-muted sm:flex-row sm:items-center sm:justify-between">
      <span>
        {subjectTotal === 0
          ? "0 subjects"
          : `${(subjectPage - 1) * SUBJECT_PAGE_SIZE + 1}-${Math.min(
              subjectPage * SUBJECT_PAGE_SIZE,
              subjectTotal,
            )} of ${subjectTotal} subjects`}
      </span>
      <div className="flex gap-2">
        <Button
          type="button"
          size="small"
          variant="outline"
          disabled={subjectPage <= 1 || loading}
          onClick={() => setSubjectPage((current) => Math.max(1, current - 1))}
        >
          <ChevronLeft className="h-4 w-4" />
          Previous
        </Button>
        <Button
          type="button"
          size="small"
          variant="outline"
          disabled={subjectPage >= subjectPageCount || loading}
          onClick={() =>
            setSubjectPage((current) => Math.min(subjectPageCount, current + 1))
          }
        >
          Next
          <ChevronRight className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );

  const subjectEditor = (
    <WorkspacePanel
      title={editing.type === "subject" ? "Edit subject" : "Create subject"}
      description="Create each tenant-scoped subject once, then attach it to level curricula."
    >
      <SubjectForm
        form={subjectForm}
        setForm={setSubjectForm}
        saving={saving}
        editing={editing.type === "subject"}
        onSubmit={saveSubject}
        onCancel={resetSubject}
      />
    </WorkspacePanel>
  );

  const subjectsListView = (
    <div>
      <RecordList
        title="Subject catalog"
        hideSearch
        description="Subjects available for one or more level curricula."
        actions={subjectSearchControls}
        items={subjectListItems}
        emptyIcon={BookOpen}
        emptyTitle={subjectEmptyTitle}
        emptyDescription={subjectEmptyDescription}
        renderTitle={(item) => item.name}
        renderMeta={(item) => item.code || "No code"}
        renderDescription={(item) => item.description || "No description"}
        renderStatus={subjectStatus}
        renderActions={(item) => (
          <SubjectActionMenu
            item={item}
            busy={saving === item.id}
            onAction={confirmSubjectAction}
          />
        )}
        canEdit={(item) => !item.archived_at}
        onEdit={(item) => {
          setEditing({ type: "subject", id: item.id });
          setSubjectForm({
            name: item.name || "",
            code: item.code || "",
            description: item.description || "",
          });
        }}
      />
      {subjectPager}
    </div>
  );

  const subjectsView = (
    <WorkspaceGrid editor={subjectEditor} content={subjectsListView} />
  );
  const subjectConfirmationDialog = (
    <TypedConfirmationDialog
      open={pendingConfirmation?.type === "subject-lifecycle"}
      title={pendingConfirmation?.title}
      description={pendingConfirmation?.description}
      confirmationText={pendingConfirmation?.confirmationText || ""}
      confirmLabel={pendingConfirmation?.confirmLabel}
      variant={pendingConfirmation?.variant}
      isLoading={saving === pendingConfirmation?.item?.id}
      onConfirm={runConfirmedAction}
      onCancel={() => setPendingConfirmation(null)}
    />
  );

  if (error && !loading) {
    return (
      <WorkspacePanel title="Academic setup unavailable">
        <p className="text-sm text-error">{error}</p>
        <Button type="button" className="mt-4" onClick={loadWorkspace}>
          Retry
        </Button>
      </WorkspacePanel>
    );
  }

  if (domain === "subjects") {
    if (activeTab === "create") {
      return (
        <>
          {subjectEditor}
          {subjectConfirmationDialog}
        </>
      );
    }
    if (editing.type === "subject") {
      return (
        <>
          {subjectsView}
          {subjectConfirmationDialog}
        </>
      );
    }
    return (
      <>
        {subjectsListView}
        {subjectConfirmationDialog}
      </>
    );
  }
  if (domain === "grading") {
    return activeTab === "create" || editing.type === "scale"
      ? gradingView
      : gradingListView;
  }
  if (domain === "terms")
    return activeTab === "create" ? periodsView : periodsView;
  if (domain === "sessions") return periodsView;
  if (activeTab === "grading") return gradingView;
  if (activeTab === "subjects") return subjectsView;
  return periodsView;
}

export default AcademicSetupWorkspace;