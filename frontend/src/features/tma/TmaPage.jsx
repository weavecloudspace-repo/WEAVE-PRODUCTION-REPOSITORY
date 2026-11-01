import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  Plus,
  Settings,
  ArrowLeft,
  Trash2,
  Send,
  RefreshCw,
  XCircle,
  History,
} from "lucide-react";
import Button from "../../components/ui/Button";
import Card from "../../components/ui/Card";
import Modal from "../../components/ui/Modal";
import Badge from "../../components/ui/Badge";
import { authSession, getErrorMessage } from "../../services/api";
import { tmaService as service } from "../../services/tmaService";
import { useToast } from "../../hooks/useToast";
import TmaActions from "./TmaActions";
import Select from "./TmaSelect";
import TmaAssignmentCard from "./TmaAssignmentCard";
import TmaAuthoringWorkspace from "./TmaAuthoringWorkspace";
import TmaAIComposer from "./TmaAIComposer";
import TmaQuestionEditor from "./TmaQuestionEditor";
import TmaQuestionList from "./TmaQuestionList";

const field =
  "min-h-11 w-full rounded-xl border border-border bg-surface px-3 py-2 text-sm text-text";
const rows = (value) => value?.items || value || [];

const blank = () => ({
  clientKey: crypto.randomUUID(),
  question_text: "",
  image_asset_id: null,
  options: Array.from({ length: 4 }, (_, i) => ({
    position: i + 1,
    option_text: "",
    image_asset_id: null,
    is_correct: i === 0,
  })),
});
const dateInput = (value) =>
  value
    ? new Date(
        new Date(value).getTime() - new Date(value).getTimezoneOffset() * 60000,
      )
        .toISOString()
        .slice(0, 16)
    : "";

function Configuration({
  config,
  assignment,
  onSave,
  busy,
  scopeEditable = false,
  isAdmin = false,
}) {
  const [level, setLevel] = useState(assignment?.academic_level_id || "");
  const [subject, setSubject] = useState(
    assignment?.curriculum_subject_id || "",
  );
  const [component, setComponent] = useState(
    assignment?.assessment_component_id || "",
  );
  const [closing, setClosing] = useState(dateInput(assignment?.closes_at));
  const [lead, setLead] = useState(assignment?.lead_teacher_membership_id || "");
  const locked = Boolean(assignment) && !scopeEditable;
  const levels = [
    ...new Map(
      config.scopes.map((s) => [s.academic_level_id, s.level_name]),
    ).entries(),
  ];
  const subjects = config.scopes.filter((s) => s.academic_level_id === level);
  const eligibleLeads = (config.lead_teachers || []).filter(
    (item) => item.academic_level_id === level && item.curriculum_subject_id === subject,
  );
  const leadIsEligible = eligibleLeads.some((item) => item.teacher_membership_id === lead);
  const validScope = Boolean(
    level && subjects.some((s) => s.curriculum_subject_id === subject),
  );
  return (
    <form
      className="space-y-6 sm:space-y-7"
      onSubmit={(e) => {
        e.preventDefault();
        if (
          busy ||
          (!locked &&
            (!validScope || !component || (!assignment && !config.term_open)))
        )
          return;
        const closingPayload = {
          closes_at: closing ? new Date(closing).toISOString() : null,
          ...(isAdmin && assignment?.status !== "closed"
            ? { lead_teacher_membership_id: lead || null }
            : {}),
        };
        onSave(
          locked
            ? closingPayload
            : {
                academic_level_id: level,
                curriculum_subject_id: subject,
                academic_session_id: config.academic_session_id,
                academic_term_id: config.academic_term_id,
                assessment_component_id: component,
                ...closingPayload,
              },
        );
      }}
    >
      <p className="text-sm text-text-muted">
        Current term:{" "}
        {config.term_name?.replaceAll("_", " ") || "No current term"}. Each
        assignment covers all eligible classes at the selected level.
      </p>
      <div className="grid gap-5 sm:grid-cols-2">
        <Select
          label="Academic level"
          value={level}
          onChange={(value) => {
            setLevel(value);
            setSubject("");
            setLead("");
          }}
          disabled={locked}
        >
          {levels.map(([id, name]) => (
            <option key={id} value={id}>
              {name}
            </option>
          ))}
        </Select>
        <Select
          label="Subject"
          value={subject}
          onChange={(value) => {
            setSubject(value);
            setLead("");
          }}
          disabled={locked || !level}
        >
          {subjects.map((s) => (
            <option
              key={s.curriculum_subject_id}
              value={s.curriculum_subject_id}
            >
              {s.subject_name}
            </option>
          ))}
        </Select>
      </div>
      {!level && (
        <p className="text-xs text-text-muted">
          Choose an academic level to see its available subjects.
        </p>
      )}
      <Select
        label="Assessment component"
        value={component}
        onChange={setComponent}
        disabled={locked}
      >
        {config.components.map((c) => (
          <option key={c.id} value={c.id}>
            {c.name} · {c.maximum_score} marks
          </option>
        ))}
      </Select>
      <p className="text-xs leading-5 text-text-muted">
        Only non-examinable, non-hybrid assessment components are available.
      </p>
      {isAdmin && assignment?.status !== "closed" && (
        <div className="rounded-xl border border-border bg-surface-muted/40 p-4 space-y-2">
          <Select
            label="Lead teacher"
            value={lead}
            onChange={setLead}
            placeholder="Admin manages assignment"
            clearable
            disabled={!validScope}
          >
            {lead && !leadIsEligible && (
              <option value={lead}>Previously assigned teacher (no longer eligible)</option>
            )}
            {eligibleLeads.map((teacher) => (
              <option key={teacher.teacher_membership_id} value={teacher.teacher_membership_id}>
                {teacher.display_name}
              </option>
            ))}
          </Select>
          <p className="text-xs leading-5 text-text-muted">
            Choose a teacher assigned to this level and subject. The lead can publish,
            close, cancel and revise the TMA, while other eligible teachers can contribute
            questions. Administrators always retain full management control.
            {!eligibleLeads.length && " No eligible teachers are currently assigned."}
          </p>
        </div>
      )}
      {locked && (
        <p className="text-xs text-text-muted">
          Academic scope cannot be changed after questions have been added or published.
          Only the lead teacher or administrator can update these settings.
        </p>
      )}
      <label className="grid gap-1.5 text-sm font-medium">
        Submission deadline (optional)
        <input
          type="datetime-local"
          className={field}
          value={closing}
          onChange={(e) => setClosing(e.target.value)}
        />
      </label>
      <p className="text-xs text-text-muted">
        Students cannot start, save, or submit after this time. The assignment
        automatically changes to Closed. Manual closing remains available.
      </p>
      <Button
        type="submit"
        disabled={
          busy ||
          (!locked &&
            (!validScope || !component || (!assignment && !config.term_open)))
        }
      >
        Save assignment
      </Button>
    </form>
  );
}

export default function TmaPage({ role }) {
  const { showError, showSuccess } = useToast();
  const { assignmentId } = useParams();
  const navigate = useNavigate();
  const base = `/${role}/tma`;
  const [config, setConfig] = useState(null);
  const [list, setList] = useState([]);
  const [listTotal, setListTotal] = useState(0);
  const [terms, setTerms] = useState([]);
  const [termId, setTermId] = useState("");
  const [offset, setOffset] = useState(0);
  const [assignment, setAssignment] = useState(null);
  const [questions, setQuestions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [dialog, setDialog] = useState(null);
  const [draft, setDraft] = useState(null);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [leaveTarget, setLeaveTarget] = useState(null);
  const [tab, setTab] = useState("questions");
  const [aiOpen, setAiOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [levelFilter, setLevelFilter] = useState("");
  const [readiness, setReadiness] = useState(null);
  const [assets, setAssets] = useState([]);
  const [report, setReport] = useState(null);
  const [search, setSearch] = useState("");
  const [participation, setParticipation] = useState("");
  const [classFilter, setClassFilter] = useState("");
  const [reportOffset, setReportOffset] = useState(0);
  const [history, setHistory] = useState([]);
  const [cancellation, setCancellation] = useState(null);
  const [reason, setReason] = useState("");
  const loadVersion = useRef(0);
  const load = useCallback(
    async ({ background = false } = {}) => {
      const version = ++loadVersion.current;
      if (!background) setLoading(true);
      setLoadFailed(false);
      try {
        const [c, termOptions] = await Promise.all([
          service.configuration(),
          assignmentId ? Promise.resolve([]) : service.terms(),
        ]);
        if (version !== loadVersion.current) return;
        setConfig(c);
        if (!assignmentId) setTerms(termOptions);
        if (assignmentId) {
          const [a, q, images, revisions] = await Promise.all([
            service.get(assignmentId),
            service.questions(assignmentId),
            service.images(assignmentId),
            service.revisions(assignmentId),
          ]);
          if (version !== loadVersion.current) return;
          setAssignment(a);
          setQuestions(q);
          setAssets(images);
          setHistory(revisions.revisions);
          if (["cancelling", "cancelled"].includes(a.status)) {
            const status = await service.cancellation(assignmentId);
            if (version === loadVersion.current) setCancellation(status);
          }
        } else {
          const selected = termOptions.some((term) => term.id === termId)
            ? termId
            : (termOptions.find((term) => term.is_current)?.id || termOptions[0]?.id || "");
          if (selected !== termId) setTermId(selected);
          const response = selected
            ? await service.list(offset, selected)
            : { items: [], total: 0 };
          if (version === loadVersion.current) {
            setList(rows(response));
            setListTotal(response.total || 0);
          }
        }
      } catch (e) {
        if (version === loadVersion.current) {
          showError(getErrorMessage(e));
          setLoadFailed(true);
        }
      } finally {
        if (version === loadVersion.current) setLoading(false);
      }
    },
    [assignmentId, offset, showError, termId],
  );
  useEffect(() => {
    load();
    return () => {
      loadVersion.current += 1;
    };
  }, [load]);
  useEffect(() => {
    setDraft(null);
    setDeleteTarget(null);
    setLeaveTarget(null);
    setDialog(null);
    setReadiness(null);
    setCancellation(null);
    setTab("questions");
    setAiOpen(false);
    setAssignment(null);
    setSearch("");
    setParticipation("");
    setClassFilter("");
    setReportOffset(0);
  }, [assignmentId]);
  useEffect(() => {
    if (
      !assignmentId ||
      assignment?.status !== "cancelling" ||
      cancellation?.status === "failed"
    )
      return;
    let active = true;
    let lastError = "";
    const timer = window.setInterval(() => {
      service
        .cancellation(assignmentId)
        .then((result) => {
          if (!active) return;
          lastError = "";
          setCancellation(result);
          if (result.status === "completed") load();
        })
        .catch((e) => {
          const message = getErrorMessage(e);
          if (active && message && message !== lastError) showError(message);
          lastError = message;
        });
    }, 5000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [assignmentId, assignment?.status, cancellation?.status, load, showError]);
  useEffect(() => {
    if (!assignmentId || tab !== "submissions") return;
    let active = true;
    setReport(null);
    service
      .submissions(assignmentId, {
        search,
        ...(participation ? { status: participation } : {}),
        ...(classFilter ? { class_id: classFilter } : {}),
        offset: reportOffset,
        limit: 25,
      })
      .then((r) => {
        if (active) setReport(r);
      })
      .catch((e) => {
        if (active) showError(getErrorMessage(e));
      });
    return () => {
      active = false;
    };
  }, [assignmentId, tab, search, participation, classFilter, reportOffset, showError]);
  const run = async (fn, message = "") => {
    setBusy(true);
    try {
      await fn();
      if (message) showSuccess(message);
    } catch (e) {
      showError(getErrorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  const scopeLabel = (a) => {
    const s = config?.scopes.find(
      (s) => s.curriculum_subject_id === a.curriculum_subject_id,
    );
    return s ? `${s.subject_name} · ${s.level_name}` : "Assignment";
  };
  const actor = authSession.getUser();
  const actorId = actor?.membership_id || actor?.id;
  const canManage =
    role === "admin" ||
    (Boolean(assignment) && Boolean(actorId) && (
      assignment.lead_teacher_membership_id
        ? assignment.lead_teacher_membership_id === actorId
        : assignment.created_by_actor_type === "teacher" &&
          assignment.created_by_actor_id === actorId
    ));
  const editable = assignment?.status === "draft";
  const canEditQuestion = (q) =>
    canManage ||
    (q.author_actor_type === "teacher" &&
      q.author_actor_id === (actor?.membership_id || actor?.id));
  const saveQuestion = (createAnother = false) =>
    run(async () => {
      const payload = {
        question_text: draft.question_text || null,
        image_asset_id: draft.image_asset_id || null,
        options: draft.options.map((o, i) => ({
          position: i + 1,
          option_text: o.option_text || null,
          image_asset_id: o.image_asset_id || null,
          is_correct: o.is_correct,
        })),
      };
      if (draft.id)
        await service.updateQuestion(assignmentId, draft.id, {
          ...payload,
          version: draft.version,
        });
      else
        await service.addQuestion(assignmentId, {
          ...payload,
          position: questions.length + 1,
        });
      setDraft(createAnother ? blank() : null);
      setReadiness(null);
      await load({ background: true });
    }, "Question saved.");
  const visibleList = list.filter(
    (a) =>
      (!statusFilter || a.status === statusFilter) &&
      (!levelFilter || a.academic_level_id === levelFilter) &&
      scopeLabel(a).toLowerCase().includes(query.toLowerCase()),
  );
  return (
    <TmaAuthoringWorkspace
      open={aiOpen && Boolean(assignmentId)}
      panel={
        assignmentId ? (
          <TmaAIComposer
            key={assignmentId}
            open={aiOpen}
            assignmentId={assignmentId}
            label={assignment ? scopeLabel(assignment) : "Assignment"}
            onClose={() => setAiOpen(false)}
            role={role}
            revisionNumber={assignment?.current_revision_number}
            onReview={(draftId) => {
              const target = `${base}/${assignmentId}/ai-drafts/${draftId}`;
              const unsaved = draft && (draft.question_text?.trim() || draft.image_asset_id
                || draft.options.some((o) => o.option_text?.trim() || o.image_asset_id));
              if (unsaved) setLeaveTarget(target);
              else navigate(target);
            }}
          />
        ) : null
      }
    >
      <div className="mx-auto w-full max-w-6xl space-y-5 px-1 pb-6 text-text">
        {!draft && <header className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            {assignmentId && (
              <Link
                className="mb-3 inline-flex min-h-11 items-center gap-2 rounded-xl border border-border bg-surface px-4 py-2 text-sm font-medium text-primary shadow-sm hover:bg-surface-muted"
                to={base}
                onClick={(e) => {
                  if (draft) {
                    e.preventDefault();
                    setLeaveTarget("assignments");
                  }
                }}
              >
                <ArrowLeft className="h-4 w-4" />
                All assignments
              </Link>
            )}
            <h1 className="text-2xl font-semibold">
              {assignmentId && assignment
                ? scopeLabel(assignment)
                : "Tutor Marked Assignments"}
            </h1>
          </div>
          {!assignmentId ? (
            <Button
              onClick={() => setDialog("create")}
              disabled={!config?.term_open || termId !== config?.academic_term_id}
            >
              <Plus className="h-4 w-4" />
              Create assignment
            </Button>
          ) : (
            <TmaActions
              busy={busy || loading}
              items={[
                {
                  label: "Settings",
                  icon: Settings,
                  visible: canManage && ["draft", "active", "closed"].includes(assignment?.status),
                  onClick: () => setDialog("settings"),
                },
                {
                  label: "Publish assignment",
                  icon: Send,
                  visible: editable && canManage,
                  onClick: () =>
                    run(async () => {
                      if (draft) {
                        setTab("questions");
                        throw new Error(
                          "Save or leave the question editor before publishing.",
                        );
                      }
                      const issues = await service.readiness(assignmentId);
                      setReadiness(issues);
                      setTab("questions");
                      if (!issues.length) setDialog("activate");
                    }),
                },
                {
                  label: "Close assignment",
                  icon: XCircle,
                  visible: canManage && assignment?.status === "active",
                  onClick: () => setDialog("close"),
                },
                {
                  label: "Reopen assignment",
                  icon: RefreshCw,
                  visible: canManage && assignment?.status === "closed",
                  onClick: () => setDialog("reopen"),
                },
                {
                  label: "Cancel and reverse scores",
                  icon: Trash2,
                  danger: true,
                  visible: canManage && assignment?.status === "closed",
                  onClick: () => setDialog("cancel"),
                },
                {
                  label: "Create corrected revision",
                  icon: History,
                  visible: canManage && assignment?.status === "cancelled",
                  onClick: () =>
                    run(async () => {
                      await service.revise(assignmentId);
                      await load();
                      setTab("questions");
                    }),
                },
                {
                  label: "Retry cancellation",
                  icon: RefreshCw,
                  visible: canManage && cancellation?.status === "failed",
                  onClick: () =>
                    run(async () => {
                      await service.retryCancellation(assignmentId);
                      await load();
                    }),
                },
              ]}
            />
          )}
        </header>}
        {loadFailed && <Button variant="outline" onClick={load}>Retry loading assignments</Button>}
        {loading ? (
          <p role="status">Loading assignments…</p>
        ) : loadFailed ? null : !assignmentId ? (
          <>
            <div className="grid items-end gap-3 rounded-2xl border border-border bg-surface p-4 sm:grid-cols-2 lg:grid-cols-4">
              <div className="min-w-0 sm:col-span-2 lg:col-span-1">
                <Select
                  label="Academic term"
                  value={termId}
                  onChange={(value) => {
                    setOffset(0);
                    setTermId(value);
                    setStatusFilter("");
                    setLevelFilter("");
                  }}
                  disabled={!terms.length}
                >
                  {terms.map((term) => (
                    <option key={term.id} value={term.id}>
                      {term.session_name} · {term.name.replaceAll("_", " ")}
                      {term.is_current ? " (Current)" : ""}
                    </option>
                  ))}
                </Select>
              </div>
              <label className="grid min-w-0 gap-1.5 text-xs text-text-muted sm:col-span-2 lg:col-span-1">
                Find an assignment
                <input
                  className={field}
                  placeholder="Search this page by subject or level"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                />
              </label>
              <div className="min-w-0">
                <Select
                  label="Level"
                  value={levelFilter}
                  onChange={setLevelFilter}
                  placeholder="All levels"
                  clearable
                >
                  {[...new Map((config?.scopes || []).map((scope) => [
                    scope.academic_level_id, scope.level_name,
                  ])).entries()].map(([id, name]) => (
                    <option key={id} value={id}>{name}</option>
                  ))}
                </Select>
              </div>
              <div className="min-w-0">
                <Select
                  label="Status"
                  value={statusFilter}
                  onChange={setStatusFilter}
                  placeholder="All statuses"
                  clearable
                >
                  {["draft", "active", "closed", "cancelling", "cancelled"].map(
                    (v) => (
                      <option key={v} value={v}>
                        {v.charAt(0).toUpperCase() + v.slice(1)}
                      </option>
                    ),
                  )}
                </Select>
              </div>
            </div>
            <p className="text-xs text-text-muted">
              Showing {visibleList.length} of {listTotal} assignments for the selected term
            </p>
            <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
              {visibleList.map((a) => (
                <TmaAssignmentCard
                  key={a.id}
                  assignment={a}
                  scope={config?.scopes.find(
                    (s) => s.curriculum_subject_id === a.curriculum_subject_id,
                  )}
                  component={config?.components.find(
                    (c) => c.id === a.assessment_component_id,
                  )}
                  to={base + "/" + a.id}
                />
              ))}
            </div>
            {!visibleList.length && (
              <Card className="p-8 text-center text-sm text-text-muted">
                {list.length
                  ? "No matching assignments on this page."
                  : "No assignments yet on this page. Create an assignment to start building your questions."}
              </Card>
            )}
            <div className="flex justify-between gap-3">
              <Button
                variant="outline"
                disabled={!offset}
                onClick={() => setOffset(Math.max(0, offset - 24))}
              >
                Previous
              </Button>
              <Button
                variant="outline"
                disabled={offset + list.length >= listTotal}
                onClick={() => setOffset(offset + 24)}
              >
                Next page
              </Button>
            </div>
          </>
        ) : (
          assignment && (
            <>
              {!draft && <>
              <div className="flex flex-wrap items-center gap-3">
                <Badge>{assignment.status}</Badge>
                <span className="text-sm text-text-muted">
                  Revision {assignment.current_revision_number} ·{" "}
                  {questions.length} questions
                </span>
                <span className="text-xs text-text-muted">
                  {canManage ? "Assignment manager" : "Collaborating teacher"}
                </span>
              </div>
              <nav
                aria-label="Assignment sections"
                className="flex gap-2 overflow-x-auto pb-1"
              >
                {["questions", "submissions", "history"].map((t) => (
                  <Button
                    key={t}
                    variant={tab === t ? "primary" : "outline"}
                    onClick={() => setTab(t)}
                  >
                    {t[0].toUpperCase() + t.slice(1)}
                  </Button>
                ))}
              </nav>
              </>}
              {tab === "questions" && (
                <div className="space-y-5">
                  {!draft && editable && (
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div>
                        <h2 className="font-semibold">Questions</h2>
                        <p className="mt-1 text-xs text-text-muted">
                          Write questions manually, choose the correct answers,
                          then preview.
                        </p>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        <Button variant="outline" disabled={busy} onClick={() => setAiOpen(true)}>
                          Generate with AI
                        </Button>
                        <Button
                          disabled={busy}
                          onClick={() => {
                            setReadiness(null);
                            setDraft(blank());
                          }}
                        >
                          <Plus size={16} /> Add question
                        </Button>
                      </div>
                    </div>
                  )}
                  {readiness && (
                    <details
                      open
                      className="rounded-xl border border-border bg-surface px-5 py-4"
                    >
                      <summary className="cursor-pointer text-sm font-semibold">
                        Publication checklist ·{" "}
                        {readiness.length
                          ? readiness.length + " items to resolve"
                          : "Ready to publish"}
                      </summary>
                      {readiness.length > 0 && (
                        <ul className="mt-3 list-disc space-y-2 pl-5 text-xs leading-6 text-text-muted">
                          {readiness.map((item) => (
                            <li key={item}>{item}</li>
                          ))}
                        </ul>
                      )}
                    </details>
                  )}
                  {draft ? (
                    <TmaQuestionEditor
                      key={draft.id || draft.clientKey}
                      draft={draft}
                      setDraft={setDraft}
                      assets={assets}
                      assignmentId={assignmentId}
                      busy={busy}
                      onSave={saveQuestion}
                      onDelete={() => {
                        setDeleteTarget(draft);
                        setDialog("delete");
                      }}
                      onClose={() => setLeaveTarget("questions")}
                      onAI={() => setAiOpen(true)}
                      onUpload={async (file) => {
                        const asset = await service.uploadImage(
                          assignmentId,
                          file,
                        );
                        setAssets((current) => [...current, asset]);
                        return asset;
                      }}
                    />
                  ) : (
                    <TmaQuestionList
                      questions={questions}
                      assignmentPath={`${base}/${assignmentId}`}
                      busy={busy}
                      editable={editable}
                      canEdit={canEditQuestion}
                      onDelete={(q) => {
                        setDeleteTarget(q);
                        setDialog("delete");
                      }}
                      onEdit={(q) =>
                        setDraft({
                          ...q,
                          options: q.options.map((o) => ({ ...o })),
                        })
                      }
                    />
                  )}
                </div>
              )}
              {tab === "submissions" && (
                <Card className="tma-submissions">
                  <div className="tma-submissions-heading">
                    <div>
                      <h2 className="font-semibold">Student submissions</h2>
                      <p className="mt-1 text-sm text-text-muted">
                        Review participation and scores for this assignment.
                      </p>
                    </div>
                    {(search || participation || classFilter) && (
                      <Button
                        variant="outline"
                        onClick={() => {
                          setSearch("");
                          setParticipation("");
                          setClassFilter("");
                          setReportOffset(0);
                        }}
                      >
                        Clear filters
                      </Button>
                    )}
                  </div>
                  <div className="tma-submission-filters">
                    <label className="tma-submission-search">
                      <span className="mb-1.5 block text-sm font-semibold text-text-soft">
                        Search students
                      </span>
                      <input
                        aria-label="Search submissions"
                        placeholder="Name or admission number"
                        className={field}
                        value={search}
                        onChange={(e) => {
                          setSearch(e.target.value);
                          setReportOffset(0);
                        }}
                      />
                    </label>
                    <Select
                      label="Participation"
                      placeholder="All participation"
                      clearable
                      value={participation}
                      onChange={(v) => {
                        setParticipation(v);
                        setReportOffset(0);
                      }}
                    >
                      {["not_started", "in_progress", "submitted"].map((v) => (
                        <option key={v} value={v}>
                          {v.replaceAll("_", " ")}
                        </option>
                      ))}
                    </Select>
                    <Select
                      label="Class"
                      placeholder="All classes"
                      clearable
                      value={classFilter}
                      onChange={(v) => {
                        setClassFilter(v);
                        setReportOffset(0);
                      }}
                    >
                      {(config.classes || [])
                        .filter(
                          (c) =>
                            c.academic_level_id ===
                            assignment.academic_level_id,
                        )
                        .map((c) => (
                          <option key={c.id} value={c.id}>
                            {c.name}
                          </option>
                        ))}
                    </Select>
                  </div>
                  <div className="tma-submission-list">
                    <div className="tma-submission-columns" aria-hidden="true">
                      <span>Student</span>
                      <span>Participation</span>
                      <span>Score</span>
                    </div>
                    {report?.items.map((s) => (
                      <div key={s.student_id} className="tma-submission-row">
                        <div className="tma-submission-student">
                          <p className="font-medium break-words">
                            {s.student_name}
                          </p>
                          <p className="text-xs text-text-muted">
                            {s.admission_number} · {s.class_name}
                            {!s.is_currently_eligible &&
                              " · Historical participant"}
                          </p>
                        </div>
                        <div className="tma-submission-participation">
                          <span
                            className={`tma-participation tma-participation--${s.participation_status}`}
                          >
                            {s.participation_status.replaceAll("_", " ")}
                          </span>
                        </div>
                        <div className="tma-submission-score">
                          <span className="tma-submission-score-label">Score</span>
                          <span>{s.score ?? "—"}</span>
                        </div>
                      </div>
                    ))}
                    {report?.items.length === 0 && (
                      <p className="px-4 py-8 text-center text-sm text-text-muted">
                        No students match the current filters.
                      </p>
                    )}
                  </div>
                  <div className="tma-submission-pagination">
                    <p className="text-sm text-text-muted">
                      {report?.total
                        ? `${reportOffset + 1}–${Math.min(reportOffset + report.items.length, report.total)} of ${report.total} students`
                        : "0 students"}
                    </p>
                    <div className="flex gap-2">
                      <Button
                        variant="outline"
                        disabled={!reportOffset}
                        onClick={() => setReportOffset(reportOffset - 25)}
                      >
                        Previous
                      </Button>
                      <Button
                        variant="outline"
                        disabled={!report || reportOffset + 25 >= report.total}
                        onClick={() => setReportOffset(reportOffset + 25)}
                      >
                        Next
                      </Button>
                    </div>
                  </div>
                </Card>
              )}
              {tab === "history" && (
                <Card className="p-5 sm:p-6">
                  <h2 className="mb-5 text-base font-semibold">
                    Revision timeline
                  </h2>
                  <div className="space-y-5">
                    {history.map((r) => (
                      <div
                        key={r.id}
                        className="border-l-2 border-primary/20 pl-4"
                      >
                        <p className="text-sm font-semibold">
                          Revision {r.revision_number}
                        </p>
                        <p className="mt-1 text-xs text-text-muted">
                          {r.invalidated_at
                            ? "Cancelled"
                            : r.published_at
                              ? "Published"
                              : "Draft"}
                        </p>
                        {r.invalidation_reason && (
                          <p className="mt-3 text-sm leading-6">
                            {r.invalidation_reason}
                          </p>
                        )}
                      </div>
                    ))}
                  </div>
                  {cancellation && (
                    <div
                      className="mt-6 rounded-xl border border-border p-4 text-sm"
                      role="status"
                    >
                      <p>
                        Cancellation: {cancellation.status} ·{" "}
                        {cancellation.reversed_scores} scores reversed
                      </p>
                      {cancellation.error_message && (
                        <p className="mt-2 text-error">
                          {cancellation.error_message}
                        </p>
                      )}
                      <p className="mt-2 text-xs text-text-muted">
                        Use Actions to refresh, retry or create a corrected
                        revision when available.
                      </p>
                    </div>
                  )}
                </Card>
              )}
            </>
          )
        )}
        <Modal
          open={dialog === "create" || dialog === "settings"}
          className="max-w-2xl"
          title={
            dialog === "create" ? "Create assignment" : "Assignment settings"
          }
          onClose={() => !busy && setDialog(null)}
        >
          {config && (
            <Configuration
              key={dialog}
              scopeEditable={
                !assignmentId ||
                (canManage && editable && questions.length === 0)
              }
              isAdmin={role === "admin"}
              config={config}
              assignment={dialog === "settings" ? assignment : null}
              busy={busy}
              onSave={(body) =>
                run(async () => {
                  if (dialog === "settings") {
                    await service.update(assignmentId, body);
                    showSuccess("Assignment updated.");
                    setDialog(null);
                    await load();
                  } else {
                    const a = await service.create(body);
                    showSuccess("Assignment created.");
                    setDialog(null);
                    navigate(`${base}/${a.id}`);
                  }
                })
              }
            />
          )}
        </Modal>
        <Modal
          open={Boolean(leaveTarget)}
          title="Leave question editor?"
          description="Your unsaved changes will be lost. Save the question first if you want to keep them."
          onClose={() => setLeaveTarget(null)}
          footer={
            <div className="flex flex-wrap justify-end gap-2">
              <Button variant="outline" onClick={() => setLeaveTarget(null)}>Keep editing</Button>
              <Button variant="danger" onClick={() => {
                const target = leaveTarget;
                setLeaveTarget(null);
                setDraft(null);
                if (target === "assignments") navigate(base);
                else if (target?.startsWith("/")) navigate(target);
              }}>Leave without saving</Button>
            </div>
          }
        />
        <Modal
          open={["activate", "reopen", "close", "cancel", "delete"].includes(dialog)}
          title={
            {
              activate: "Publish assignment?",
              reopen: "Reopen assignment?",
              close: "Close assignment?",
              cancel: "Cancel assignment?",
              delete: "Delete question?",
            }[dialog] || "Confirm"
          }
          onClose={() => !busy && setDialog(null)}
        >
          <div className="space-y-4">
            <p className="text-sm text-text-muted">
              {
                {
                  activate:
                    "Publishing locks question editing and allows eligible students to start. The assignment has passed the publication checks.",
                  reopen:
                    "Reopening lets eligible students start or resume unfinished attempts. Existing submissions and scores are preserved, and questions remain locked.",
                  close:
                    "Closing immediately prevents students from starting, saving or submitting, including attempts already in progress.",
                  cancel:
                    "Cancellation reverses verified TMA-owned draft scores. Modified or submitted academic results require reconciliation. A worker completes this operation.",
                  delete: "This question will be removed from the draft.",
                }[dialog]
              }
            </p>
            {dialog === "cancel" && (
              <label className="grid gap-2 text-sm">
                Reason
                <textarea
                  className={field}
                  minLength={5}
                  maxLength={2000}
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                />
              </label>
            )}
            <Button
              disabled={
                busy || (dialog === "cancel" && reason.trim().length < 5)
              }
              onClick={() =>
                run(async () => {
                  if (dialog === "activate")
                    await service.activate(assignmentId);
                  if (dialog === "reopen") await service.reopen(assignmentId);
                  if (dialog === "close") await service.close(assignmentId);
                  if (dialog === "cancel")
                    await service.cancel(assignmentId, reason);
                  if (dialog === "delete") {
                    await service.deleteQuestion(assignmentId, deleteTarget.id);
                    if (draft?.id === deleteTarget.id) setDraft(null);
                    setDeleteTarget(null);
                  }
                  showSuccess({
                    activate: "Assignment published.", reopen: "Assignment reopened.",
                    close: "Assignment closed.", cancel: "Assignment cancellation started.",
                    delete: "Question deleted.",
                  }[dialog]);
                  setDialog(null);
                  await load();
                })
              }
            >
              Confirm
            </Button>
          </div>
        </Modal>
      </div>
    </TmaAuthoringWorkspace>
  );
}
