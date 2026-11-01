import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  Plus,
  Settings,
  ArrowLeft,
  Sparkles,
  ImagePlus,
  Trash2,
} from "lucide-react";
import Button from "../../components/ui/Button";
import Card from "../../components/ui/Card";
import Modal from "../../components/ui/Modal";
import Badge from "../../components/ui/Badge";
import { authSession } from "../../services/api";
import { tmaService as service } from "../../services/tmaService";
import MathText from "./MathText.jsx";
import { useToast } from "../../hooks/useToast";

const field =
  "min-h-11 w-full rounded-xl border border-border bg-surface px-3 py-2 text-sm text-text";
const rows = (value) => value?.items || value || [];

function PreviewImage({ image }) {
  if (
    !image?.data_base64 ||
    !["image/png", "image/jpeg", "image/webp"].includes(image.content_type)
  )
    return null;
  return (
    <img
      className="max-h-64 max-w-full rounded-lg object-contain"
      src={`data:${image.content_type};base64,${image.data_base64}`}
      alt={image.alt_text || "AI question illustration"}
    />
  );
}
const blank = () => ({
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

function Select({ label, value, onChange, children, disabled = false }) {
  return (
    <label className="grid min-w-0 gap-1.5 text-sm font-medium">
      {label}
      <select
        className={field}
        value={value || ""}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="">Select {label.toLowerCase()}</option>
        {children}
      </select>
    </label>
  );
}

function Configuration({
  config,
  assignment,
  onSave,
  busy,
  scopeEditable = false,
}) {
  const [scope, setScope] = useState(
    assignment
      ? `${assignment.academic_level_id}:${assignment.curriculum_subject_id}`
      : "",
  );
  const [component, setComponent] = useState(
    assignment?.assessment_component_id || "",
  );
  const [closing, setClosing] = useState(dateInput(assignment?.closes_at));
  const locked = Boolean(assignment) && !scopeEditable;
  return (
    <form
      className="space-y-5"
      onSubmit={(e) => {
        e.preventDefault();
        const [level, subject] = scope.split(":");
        const closingPayload = {
          closes_at: closing ? new Date(closing).toISOString() : null,
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
      <Select
        label="Level and subject"
        value={scope}
        onChange={setScope}
        disabled={locked}
      >
        {config.scopes.map((s) => (
          <option
            key={s.curriculum_subject_id}
            value={`${s.academic_level_id}:${s.curriculum_subject_id}`}
          >
            {s.level_name} · {s.subject_name}
          </option>
        ))}
      </Select>
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
      {locked && (
        <p className="text-xs text-text-muted">
          Only the lead teacher or admin may change academic scope, before any
          questions exist. Collaborators can adjust the closing estimate while
          draft or active.
        </p>
      )}
      <label className="grid gap-1.5 text-sm font-medium">
        Expected closing (optional)
        <input
          type="datetime-local"
          className={field}
          value={closing}
          onChange={(e) => setClosing(e.target.value)}
        />
      </label>
      <p className="text-xs text-text-muted">
        This is an estimate. Only manually closing the assignment stops student
        access.
      </p>
      <Button
        type="submit"
        disabled={
          busy || (!assignment && (!scope || !component || !config.term_open))
        }
      >
        Save assignment
      </Button>
    </form>
  );
}

function TextEditor({ label, value, onChange }) {
  const ref = useRef(null);
  const insert = (text) => {
    const el = ref.current;
    const start = el.selectionStart;
    const end = el.selectionEnd;
    onChange(value.slice(0, start) + text + value.slice(end));
    requestAnimationFrame(() => {
      el.focus();
      el.setSelectionRange(start + text.length, start + text.length);
    });
  };
  return (
    <div className="space-y-2">
      <label className="grid gap-1.5 text-sm font-medium">
        {label}
        <textarea
          ref={ref}
          className={`${field} min-h-28 resize-y`}
          value={value || ""}
          onChange={(e) => onChange(e.target.value)}
        />
      </label>
      <div className="flex flex-wrap gap-1" aria-label={`${label} formatting`}>
        {[
          "²",
          "³",
          "√",
          "π",
          "θ",
          "±",
          "×",
          "÷",
          "≤",
          "≥",
          "≠",
          "∞",
          "\\(\\frac{a}{b}\\)",
          "\\(x^{2}\\)",
        ].map((s) => (
          <button
            key={s}
            type="button"
            className="min-h-11 min-w-11 rounded-lg border border-border px-2 text-sm hover:bg-primary-soft"
            onClick={() => insert(s)}
          >
            {s.length > 3 ? (s.includes("frac") ? "Fraction" : "Power") : s}
          </button>
        ))}
      </div>
      <div className="rounded-xl bg-surface-muted/40 p-3 text-sm">
        <MathText>{value}</MathText>
      </div>
    </div>
  );
}

export default function TmaPage({ role }) {
  const { showError } = useToast();
  const { assignmentId } = useParams();
  const navigate = useNavigate();
  const base = `/${role}/tma`;
  const [config, setConfig] = useState(null);
  const [list, setList] = useState([]);
  const [offset, setOffset] = useState(0);
  const [assignment, setAssignment] = useState(null);
  const [questions, setQuestions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [dialog, setDialog] = useState(null);
  const [draft, setDraft] = useState(null);
  const [tab, setTab] = useState("questions");
  const [readiness, setReadiness] = useState(null);
  const [assets, setAssets] = useState([]);
  const [urls, setUrls] = useState({});
  const [prompt, setPrompt] = useState("");
  const [count, setCount] = useState(5);
  const [difficulty, setDifficulty] = useState("medium");
  const [visual, setVisual] = useState("auto");
  const [previews, setPreviews] = useState([]);
  const [instruction, setInstruction] = useState("");
  const aiKey = useRef(null);
  const [report, setReport] = useState(null);
  const [search, setSearch] = useState("");
  const [participation, setParticipation] = useState("");
  const [classFilter, setClassFilter] = useState("");
  const [reportOffset, setReportOffset] = useState(0);
  const [history, setHistory] = useState([]);
  const [cancellation, setCancellation] = useState(null);
  const [reason, setReason] = useState("");
  const loadVersion = useRef(0);
  const load = useCallback(async () => {
    const version = ++loadVersion.current;
    setLoading(true);
    setError("");
    try {
      const c = await service.configuration();
      if (version !== loadVersion.current) return;
      setConfig(c);
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
        const page = await service.list(offset);
        if (version === loadVersion.current) setList(rows(page));
      }
    } catch (e) {
      if (version === loadVersion.current) setError(e.message);
    } finally {
      if (version === loadVersion.current) setLoading(false);
    }
  }, [assignmentId, offset]);
  useEffect(() => {
    load();
    return () => {
      loadVersion.current += 1;
    };
  }, [load]);
  useEffect(() => {
    setDraft(null);
    setDialog(null);
    setReadiness(null);
    setCancellation(null);
    setTab("questions");
    setPreviews([]);
    setUrls({});
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
    const timer = window.setInterval(() => {
      service
        .cancellation(assignmentId)
        .then((result) => {
          if (!active) return;
          setCancellation(result);
          if (result.status === "completed") load();
        })
        .catch((e) => {
          if (active) setError(e.message);
        });
    }, 5000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [assignmentId, assignment?.status, cancellation?.status, load]);
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
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [assignmentId, tab, search, participation, classFilter, reportOffset]);
  const run = async (fn, message = "Saved.") => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await fn();
      setNotice(message);
    } catch (e) {
      setError(e.message);
      showError(e.message);
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
  const canManage =
    role === "admin" ||
    (assignment?.created_by_actor_type === "teacher" &&
      assignment.created_by_actor_id === (actor?.membership_id || actor?.id));
  const editable = assignment?.status === "draft";
  const canEditQuestion = (q) =>
    canManage ||
    (q.author_actor_type === "teacher" &&
      q.author_actor_id === (actor?.membership_id || actor?.id));
  const previewImage = (id) =>
    run(async () => {
      const r = await service.imageUrl(assignmentId, id);
      setUrls((old) => ({ ...old, [id]: r.signed_url }));
    }, "Image loaded.");
  const saveQuestion = () =>
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
      setDraft(null);
      await load();
    });
  const imageSelect = (value, change) => (
    <Select label="Image" value={value} onChange={(v) => change(v || null)}>
      {assets.map((a, i) => (
        <option key={a.id} value={a.id}>
          Image {i + 1} · {Math.round(a.size_bytes / 1024)} KB
        </option>
      ))}
    </Select>
  );
  return (
    <div className="mx-auto w-full max-w-6xl space-y-5 px-1 pb-6 text-text">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          {assignmentId && (
            <Link
              className="mb-3 inline-flex min-h-11 items-center gap-2 text-sm text-primary"
              to={base}
            >
              <ArrowLeft className="h-4 w-4" />
              All assignments
            </Link>
          )}
          <h1 className="text-2xl font-semibold">
            {assignment ? scopeLabel(assignment) : "Tutor Marked Assignments"}
          </h1>
          <p className="mt-1 text-sm text-text-muted">
            Create, review and publish assignments for your students.
          </p>
        </div>
        {!assignmentId ? (
          <Button
            onClick={() => setDialog("create")}
            disabled={!config?.term_open}
          >
            <Plus className="h-4 w-4" />
            Create assignment
          </Button>
        ) : (
          <Button
            variant="outline"
            disabled={!["draft", "active"].includes(assignment?.status)}
            onClick={() => setDialog("settings")}
          >
            <Settings className="h-4 w-4" />
            Settings
          </Button>
        )}
      </header>
      {error && (
        <p
          role="alert"
          className="rounded-xl border border-error/30 bg-error-soft p-4 text-sm text-error"
        >
          {error}
          <button className="ml-3 underline" onClick={load}>
            Reload
          </button>
        </p>
      )}
      {notice && (
        <p role="status" className="rounded-xl bg-primary-soft p-3 text-sm">
          {notice}
        </p>
      )}
      {loading ? (
        <p role="status">Loading assignments…</p>
      ) : !assignmentId ? (
        <>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {list.map((a) => (
              <Link
                key={a.id}
                to={`${base}/${a.id}`}
                className="block rounded-2xl border border-border bg-surface p-5 transition hover:border-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary"
              >
                <Badge>{a.status}</Badge>
                <h2 className="mt-3 font-semibold">{scopeLabel(a)}</h2>
                <p className="mt-2 text-sm text-text-muted">
                  Revision {a.current_revision_number} ·{" "}
                  {config.components.find(
                    (c) => c.id === a.assessment_component_id,
                  )?.name || "Assessment"}
                </p>
                <p className="mt-2 text-xs text-text-muted">
                  {a.closes_at
                    ? `Expected closing: ${new Date(a.closes_at).toLocaleString()}`
                    : "No closing estimate"}
                </p>
                <span className="mt-4 block text-sm font-medium text-primary">
                  Open assignment →
                </span>
              </Link>
            ))}
          </div>
          {!list.length && (
            <Card className="p-8 text-center">
              No assignments on this page. Create your first assignment or check
              another page.
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
              disabled={list.length === 0}
              onClick={() => setOffset(offset + 24)}
            >
              Next page
            </Button>
          </div>
        </>
      ) : (
        assignment && (
          <>
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
            {tab === "questions" && (
              <>
                <div className="flex flex-wrap gap-2">
                  {editable && (
                    <>
                      <Button onClick={() => setDraft(blank())}>
                        <Plus className="h-4 w-4" />
                        Add question
                      </Button>
                      <Button variant="outline" onClick={() => setDialog("ai")}>
                        <Sparkles className="h-4 w-4" />
                        Use AI
                      </Button>
                      <Button
                        variant="outline"
                        onClick={() => setDialog("media")}
                      >
                        <ImagePlus className="h-4 w-4" />
                        Images
                      </Button>
                    </>
                  )}
                  <Button
                    variant="outline"
                    disabled={busy}
                    onClick={() =>
                      run(
                        async () =>
                          setReadiness(await service.readiness(assignmentId)),
                        "Readiness checked.",
                      )
                    }
                  >
                    Check readiness
                  </Button>
                  {editable && canManage && (
                    <Button
                      disabled={busy}
                      onClick={() => setDialog("activate")}
                    >
                      Publish assignment
                    </Button>
                  )}
                </div>
                {readiness && (
                  <Card className="p-4">
                    <h2 className="font-semibold">Publication readiness</h2>
                    {readiness.length ? (
                      <ul className="mt-2 list-disc space-y-1 pl-5 text-sm">
                        {readiness.map((r) => (
                          <li key={r}>{r}</li>
                        ))}
                      </ul>
                    ) : (
                      <p className="mt-2 text-sm">Ready to publish.</p>
                    )}
                  </Card>
                )}
                {questions.map((q, i) => (
                  <Card key={q.id} className="space-y-4 p-4 sm:p-6">
                    <div className="flex items-center justify-between gap-2">
                      <h2 className="text-sm font-semibold text-text-muted">
                        Question {i + 1}
                      </h2>
                      {editable && canEditQuestion(q) && (
                        <Button
                          variant="outline"
                          onClick={() =>
                            setDraft({
                              ...q,
                              options: q.options.map((o) => ({ ...o })),
                            })
                          }
                        >
                          Edit
                        </Button>
                      )}
                    </div>
                    <MathText>{q.question_text}</MathText>
                    {q.image_asset_id && (
                      <Button
                        variant="outline"
                        onClick={() => previewImage(q.image_asset_id)}
                      >
                        View question image
                      </Button>
                    )}
                    {urls[q.image_asset_id] && (
                      <img
                        src={urls[q.image_asset_id]}
                        alt="Question illustration"
                        className="max-h-64 max-w-full object-contain"
                      />
                    )}
                    <div className="grid gap-2 sm:grid-cols-2">
                      {q.options.map((o, j) => (
                        <div
                          key={o.id}
                          className={`rounded-xl border p-3 ${o.is_correct ? "border-primary bg-primary-soft" : "border-border"}`}
                        >
                          <span className="text-xs font-bold">
                            {String.fromCharCode(65 + j)}
                            {o.is_correct ? " · Correct" : ""}
                          </span>
                          <MathText>{o.option_text}</MathText>
                          {o.image_asset_id && (
                            <Button
                              variant="outline"
                              onClick={() => previewImage(o.image_asset_id)}
                            >
                              View option image
                            </Button>
                          )}
                          {urls[o.image_asset_id] && (
                            <img
                              src={urls[o.image_asset_id]}
                              alt="Option illustration"
                              className="max-h-40 max-w-full object-contain"
                            />
                          )}
                        </div>
                      ))}
                    </div>
                  </Card>
                ))}
                {!questions.length && (
                  <Card className="p-8 text-center text-text-muted">
                    Add your first question manually or generate questions with
                    AI.
                  </Card>
                )}
              </>
            )}
            {tab === "submissions" && (
              <Card className="space-y-4 p-4">
                <div className="grid gap-3 sm:grid-cols-2">
                  <input
                    aria-label="Search submissions"
                    placeholder="Student name or admission number"
                    className={field}
                    value={search}
                    onChange={(e) => {
                      setSearch(e.target.value);
                      setReportOffset(0);
                    }}
                  />
                  <Select
                    label="Participation"
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
                    value={classFilter}
                    onChange={(v) => {
                      setClassFilter(v);
                      setReportOffset(0);
                    }}
                  >
                    {(config.classes || [])
                      .filter(
                        (c) =>
                          c.academic_level_id === assignment.academic_level_id,
                      )
                      .map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.name}
                        </option>
                      ))}
                  </Select>
                </div>
                {report?.items.map((s) => (
                  <div
                    key={s.student_id}
                    className="flex flex-wrap justify-between gap-2 border-b border-border py-3"
                  >
                    <div>
                      <p className="font-medium">{s.student_name}</p>
                      <p className="text-xs text-text-muted">
                        {s.admission_number} · {s.class_name}
                        {!s.is_currently_eligible &&
                          " · Historical participant"}
                      </p>
                    </div>
                    <div className="text-sm">
                      {s.participation_status.replaceAll("_", " ")} ·{" "}
                      {s.score ?? "—"}
                    </div>
                  </div>
                ))}
                <div className="flex justify-between">
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
              </Card>
            )}
            {tab === "history" && (
              <Card className="space-y-4 p-4">
                {history.map((r) => (
                  <div key={r.id} className="border-b border-border pb-3">
                    <h2 className="font-semibold">
                      Revision {r.revision_number}
                    </h2>
                    <p className="text-sm text-text-muted">
                      {r.invalidated_at
                        ? "Cancelled"
                        : r.published_at
                          ? "Published"
                          : "Draft"}
                    </p>
                    {r.invalidation_reason && (
                      <p className="mt-2 text-sm">{r.invalidation_reason}</p>
                    )}
                  </div>
                ))}
                {cancellation && (
                  <div role="status">
                    <p>
                      Cancellation: {cancellation.status} ·{" "}
                      {cancellation.reversed_scores} scores reversed
                    </p>
                    {cancellation.error_message && (
                      <p className="text-error">{cancellation.error_message}</p>
                    )}
                    <Button
                      variant="outline"
                      disabled={busy}
                      onClick={() => run(load, "Status refreshed.")}
                    >
                      Refresh status
                    </Button>
                    {canManage && cancellation.status === "failed" && (
                      <Button
                        disabled={busy}
                        onClick={() =>
                          run(async () => {
                            await service.retryCancellation(assignmentId);
                            await load();
                          })
                        }
                      >
                        Retry cancellation
                      </Button>
                    )}
                  </div>
                )}
                {canManage && assignment.status === "active" && (
                  <Button variant="outline" onClick={() => setDialog("close")}>
                    Close assignment
                  </Button>
                )}
                {canManage && assignment.status === "closed" && (
                  <Button variant="outline" onClick={() => setDialog("cancel")}>
                    Cancel and reverse scores
                  </Button>
                )}
                {canManage && assignment.status === "cancelled" && (
                  <Button
                    onClick={() =>
                      run(async () => {
                        await service.revise(assignmentId);
                        await load();
                      })
                    }
                    disabled={busy}
                  >
                    Create corrected revision
                  </Button>
                )}
              </Card>
            )}
          </>
        )
      )}
      <Modal
        open={dialog === "create" || dialog === "settings"}
        title={
          dialog === "create" ? "Create assignment" : "Assignment settings"
        }
        onClose={() => !busy && setDialog(null)}
      >
        {config && (
          <Configuration
            key={dialog}
            scopeEditable={
              !assignmentId || (canManage && editable && questions.length === 0)
            }
            config={config}
            assignment={dialog === "settings" ? assignment : null}
            busy={busy}
            onSave={(body) =>
              run(async () => {
                if (dialog === "settings") {
                  await service.update(assignmentId, body);
                  setDialog(null);
                  await load();
                } else {
                  const a = await service.create(body);
                  setDialog(null);
                  navigate(`${base}/${a.id}`);
                }
              })
            }
          />
        )}
      </Modal>
      <Modal
        open={Boolean(draft)}
        title={draft?.id ? "Edit question" : "New question"}
        className="max-w-3xl"
        onClose={() => !busy && setDraft(null)}
      >
        {draft && (
          <form
            className="space-y-5"
            onSubmit={(e) => {
              e.preventDefault();
              saveQuestion();
            }}
          >
            <TextEditor
              label="Question"
              value={draft.question_text || ""}
              onChange={(v) => setDraft({ ...draft, question_text: v })}
            />
            {imageSelect(draft.image_asset_id, (v) =>
              setDraft({ ...draft, image_asset_id: v }),
            )}
            <p className="text-xs text-text-muted">
              Use at least four options and select exactly one correct answer.
              Wrap equations in \\( … \\) or $$ … $$ for display.
            </p>
            {draft.options.map((o, i) => (
              <div
                key={i}
                className="space-y-3 rounded-xl border border-border p-3"
              >
                <label className="flex min-h-11 items-center gap-3 text-sm font-semibold">
                  <input
                    type="radio"
                    name="correct"
                    checked={o.is_correct}
                    onChange={() =>
                      setDraft({
                        ...draft,
                        options: draft.options.map((x, j) => ({
                          ...x,
                          is_correct: j === i,
                        })),
                      })
                    }
                  />
                  Option {String.fromCharCode(65 + i)} · Correct answer
                </label>
                <TextEditor
                  label={`Option ${String.fromCharCode(65 + i)}`}
                  value={o.option_text || ""}
                  onChange={(v) =>
                    setDraft({
                      ...draft,
                      options: draft.options.map((x, j) =>
                        j === i ? { ...x, option_text: v } : x,
                      ),
                    })
                  }
                />
                {imageSelect(o.image_asset_id, (v) =>
                  setDraft({
                    ...draft,
                    options: draft.options.map((x, j) =>
                      j === i ? { ...x, image_asset_id: v } : x,
                    ),
                  }),
                )}
              </div>
            ))}
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                variant="outline"
                onClick={() =>
                  setDraft({
                    ...draft,
                    options: [
                      ...draft.options,
                      {
                        position: draft.options.length + 1,
                        option_text: "",
                        is_correct: false,
                      },
                    ],
                  })
                }
              >
                Add option
              </Button>
              <Button
                type="submit"
                disabled={
                  busy ||
                  (!draft.question_text?.trim() && !draft.image_asset_id) ||
                  draft.options.some(
                    (o) => !o.option_text?.trim() && !o.image_asset_id,
                  )
                }
              >
                Save question
              </Button>
              {draft.id && (
                <Button
                  type="button"
                  variant="outline"
                  disabled={busy}
                  onClick={() => setDialog("delete")}
                >
                  <Trash2 className="h-4 w-4" />
                  Delete
                </Button>
              )}
            </div>
          </form>
        )}
      </Modal>
      <Modal
        open={dialog === "media"}
        title="Assignment images"
        onClose={() => !busy && setDialog(null)}
      >
        <div className="space-y-4">
          <label className="grid gap-2 text-sm">
            Upload JPEG, PNG or WebP (up to 5 MB)
            <input
              type="file"
              accept="image/jpeg,image/png,image/webp"
              disabled={busy}
              onChange={(e) => {
                const file = e.target.files[0];
                if (file)
                  run(async () => {
                    await service.uploadImage(assignmentId, file);
                    await load();
                  });
                e.target.value = "";
              }}
            />
          </label>
          {assets.map((a, i) => (
            <div
              key={a.id}
              className="flex flex-wrap items-center gap-2 rounded-xl border border-border p-3"
            >
              <span>Image {i + 1}</span>
              <Button variant="outline" onClick={() => previewImage(a.id)}>
                Preview
              </Button>
              <Button
                variant="outline"
                disabled={busy}
                onClick={() =>
                  run(async () => {
                    const r = await service.deleteImage(assignmentId, a.id);
                    await load();
                    if (!r.storage_cleaned)
                      setNotice("Image detached. Storage cleanup is pending.");
                  })
                }
              >
                Delete unused image
              </Button>
              {urls[a.id] && (
                <img
                  src={urls[a.id]}
                  alt={`Assignment image ${i + 1}`}
                  className="max-h-48 max-w-full object-contain"
                />
              )}
            </div>
          ))}
        </div>
      </Modal>
      <Modal
        open={dialog === "ai"}
        title="AI question studio"
        className="max-w-3xl"
        onClose={() => !busy && setDialog(null)}
      >
        <div className="space-y-4">
          <TextEditor
            label="What should students be assessed on?"
            value={prompt}
            onChange={(v) => {
              setPrompt(v);
              aiKey.current = null;
            }}
          />
          <div className="grid gap-3 sm:grid-cols-3">
            <label className="grid gap-2 text-sm">
              Questions
              <input
                className={field}
                type="number"
                min="1"
                max="50"
                value={count}
                onChange={(e) => {
                  setCount(Number(e.target.value));
                  aiKey.current = null;
                }}
              />
            </label>
            <Select
              label="Difficulty"
              value={difficulty}
              onChange={(v) => {
                setDifficulty(v);
                aiKey.current = null;
              }}
            >
              {["easy", "medium", "difficult"].map((v) => (
                <option key={v}>{v}</option>
              ))}
            </Select>
            <Select
              label="Visuals"
              value={visual}
              onChange={(v) => {
                setVisual(v);
                aiKey.current = null;
              }}
            >
              {["auto", "text_only"].map((v) => (
                <option key={v}>{v}</option>
              ))}
            </Select>
          </div>
          <p className="text-xs text-text-muted">
            Generation uses your existing AI credit allowance. Review each
            question before importing it. Import each preview once.
          </p>
          <Button
            disabled={busy || !prompt.trim() || count < 1 || count > 50}
            onClick={() =>
              run(async () => {
                aiKey.current ||= crypto.randomUUID();
                const r = await service.generate(
                  assignmentId,
                  {
                    generation_prompt: prompt,
                    question_count: count,
                    difficulty,
                    visual_mode: visual,
                  },
                  aiKey.current,
                );
                setPreviews(r.questions);
              }, "Generation complete. Review the previews before saving.")
            }
          >
            {busy ? "Working…" : "Generate preview"}
          </Button>
          <label className="grid gap-2 text-sm">
            Regeneration instruction
            <input
              className={field}
              value={instruction}
              onChange={(e) => setInstruction(e.target.value)}
              placeholder="For example: make this question simpler"
            />
          </label>
          {previews.map((q, i) => (
            <Card key={i} className="space-y-3 p-4">
              <MathText>{q.prompt}</MathText>
              <PreviewImage image={q.image} />
              {q.options.map((o, j) => (
                <div key={j} className="text-sm">
                  <span>{o.is_correct ? "✓ " : ""}</span>
                  <MathText>{o.text}</MathText>
                  <PreviewImage image={o.image} />
                </div>
              ))}
              <div className="flex flex-wrap gap-2">
                <Button
                  disabled={busy}
                  onClick={() =>
                    run(async () => {
                      await service.importQuestion(assignmentId, q);
                      setPreviews((p) => p.filter((_, j) => j !== i));
                      await load();
                    }, "Question imported.")
                  }
                >
                  Import question
                </Button>
                <Button
                  variant="outline"
                  disabled={busy || !instruction.trim()}
                  onClick={() =>
                    run(async () => {
                      const r = await service.regenerate(
                        assignmentId,
                        {
                          generation_prompt: prompt,
                          existing_question: q,
                          instruction,
                          difficulty,
                          visual_mode: visual,
                        },
                        crypto.randomUUID(),
                      );
                      setPreviews((p) =>
                        p.map((old, j) => (j === i ? r.question : old)),
                      );
                    }, "Preview regenerated.")
                  }
                >
                  Regenerate
                </Button>
              </div>
            </Card>
          ))}
        </div>
      </Modal>
      <Modal
        open={["activate", "close", "cancel", "delete"].includes(dialog)}
        title={
          {
            activate: "Publish assignment?",
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
                  "Publishing locks question editing and allows eligible students to start. Check readiness before continuing.",
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
            disabled={busy || (dialog === "cancel" && reason.trim().length < 5)}
            onClick={() =>
              run(async () => {
                if (dialog === "activate") await service.activate(assignmentId);
                if (dialog === "close") await service.close(assignmentId);
                if (dialog === "cancel")
                  await service.cancel(assignmentId, reason);
                if (dialog === "delete") {
                  await service.deleteQuestion(assignmentId, draft.id);
                  setDraft(null);
                }
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
  );
}
