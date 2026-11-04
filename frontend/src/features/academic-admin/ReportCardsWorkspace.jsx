import {
  ArrowLeft,
  CheckCircle2,
  Eye,
  FilePlus2,
  FileText,
  MessageSquareWarning,
  RefreshCw,
  TriangleAlert,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";

import Badge from "../../components/ui/Badge";
import Button from "../../components/ui/Button";
import Modal from "../../components/ui/Modal";
import { useToast } from "../../hooks/useToast";
import { academicService } from "../../services/academicService";
import { classService } from "../../services/academicsService";
import { getErrorMessage } from "../../services/api";
import { reportCardService } from "../../services/reportCardService";
import { reportCommentService } from "../../services/reportCommentService";
import {
  Input,
  RecordList,
  SelectControl,
  WorkspacePanel,
} from "./AcademicWorkspacePrimitives";

const CARD_PAGE_SIZE = 100;
const READINESS_PAGE_SIZE = 50;

const asItems = (response) =>
  Array.isArray(response)
    ? response
    : Array.isArray(response?.items)
      ? response.items
      : [];

const classLabel = (item) =>
  item?.display_name ||
  [item?.academic_level_name, item?.arm_label || item?.arm]
    .filter(Boolean)
    .join(" ") ||
  "Unnamed class";

const studentLabel = (item) =>
  `${item?.student_name || item?.admission_number || "Student"}${
    item?.admission_number ? ` · ${item.admission_number}` : ""
  }`;

const termLabel = (item) =>
  String(item?.display_name || item?.name || "No term").replaceAll("_", " ");

const humanize = (value, fallback = "Not set") =>
  String(value || fallback)
    .replaceAll("_", " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());

const asNumber = (value) => {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};

const formatPercent = (value) => {
  const parsed = asNumber(value);
  return parsed === null ? "–" : `${parsed.toFixed(2)}%`;
};

const commentOptionLabel = (template) => {
  const text = String(template?.text || "").trim();
  if (!text) return "Saved comment";
  return text.length > 90 ? `${text.slice(0, 87)}...` : text;
};

const templatesForPerformance = (templates, performance) => {
  const score = asNumber(performance);
  if (score === null) return [];
  return templates
    .filter((item) => {
      const minimum = asNumber(item.minimum_score);
      const maximum = asNumber(item.maximum_score);
      return minimum !== null && maximum !== null && score >= minimum && score <= maximum;
    })
    .sort((left, right) => Number(Boolean(right.is_default)) - Number(Boolean(left.is_default)));
};

const templateOptionsForPerformance = (templates, performance) =>
  templatesForPerformance(templates, performance).map((item) => ({
    value: item.id,
    label: commentOptionLabel(item),
    description: `${item.minimum_score}–${item.maximum_score}%${
      item.is_default ? " · Default" : ""
    }`,
  }));

const statusVariant = (value) => {
  const status = String(value || "").toLowerCase();
  if (
    [
      "complete",
      "ready",
      "published",
      "submitted",
      "submitted_or_overridden",
      "available",
    ].includes(status)
  ) {
    return "success";
  }
  if (
    [
      "missing",
      "needs_review",
      "override_required",
      "outdated",
      "incomplete",
    ].includes(status)
  ) {
    return "error";
  }
  if (["draft", "manual", "waiting_for_results"].includes(status)) {
    return "warning";
  }
  return "default";
};

function StatusBadge({ value }) {
  return <Badge variant={statusVariant(value)}>{humanize(value)}</Badge>;
}

function ReportCardsWorkspace({ activeTab, onContextChange }) {
  const { showSuccess, showError, showWarning } = useToast();
  const [searchParams, setSearchParams] = useSearchParams();
  const [sessions, setSessions] = useState([]);
  const [terms, setTerms] = useState([]);
  const [classes, setClasses] = useState([]);
  const [templates, setTemplates] = useState([]);
  const [overview, setOverview] = useState(null);
  const [cards, setCards] = useState([]);
  const [cardTotal, setCardTotal] = useState(0);
  const [cardPage, setCardPage] = useState(0);
  const [cardSearch, setCardSearch] = useState("");
  const [appliedCardSearch, setAppliedCardSearch] = useState("");
  const cardRequestVersion = useRef(0);

  useEffect(() => {
    const timer = window.setTimeout(() => setAppliedCardSearch(cardSearch.trim()), 250);
    return () => window.clearTimeout(timer);
  }, [cardSearch]);
  const [readinessPage, setReadinessPage] = useState(0);
  const [readinessQuery, setReadinessQuery] = useState("");
  const [debouncedReadinessQuery, setDebouncedReadinessQuery] = useState("");
  const [filters, setFilters] = useState({
    class_id: "",
    academic_session_id: "",
    academic_term_id: "",
    status: "",
    record_state: "",
  });
  const [generationTarget, setGenerationTarget] = useState("class");
  const [selectedStudentId, setSelectedStudentId] = useState("");
  const [principalMode, setPrincipalMode] = useState("default");
  const [principalTemplateId, setPrincipalTemplateId] = useState("");
  const [principalComment, setPrincipalComment] = useState("");
  const [generationSummary, setGenerationSummary] = useState(null);
  const [previewCard, setPreviewCard] = useState(null);
  const [overrideState, setOverrideState] = useState(null);
  const [principalEditor, setPrincipalEditor] = useState(null);
  const [revisionTarget, setRevisionTarget] = useState(null);
  const [saving, setSaving] = useState("");
  const [loading, setLoading] = useState(true);
  const [overviewLoading, setOverviewLoading] = useState(false);
  const [error, setError] = useState("");

  const selectView = useCallback(
    (view) => {
      const next = new URLSearchParams(searchParams);
      next.set("view", view);
      next.delete("tab");
      setSearchParams(next, { replace: true });
    },
    [searchParams, setSearchParams],
  );

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedReadinessQuery(readinessQuery.trim());
      setReadinessPage(0);
    }, 250);
    return () => window.clearTimeout(timer);
  }, [readinessQuery]);

  const loadBase = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [sessionResponse, termResponse, classResponse, templateResponse] =
        await Promise.all([
          academicService.listSessions({ limit: 100 }),
          academicService.listTerms({ limit: 100 }),
          classService.getClasses({ limit: 100, activeOnly: false }),
          reportCommentService.listAdminTemplates({ include_archived: false }),
        ]);
      const nextSessions = asItems(sessionResponse);
      const nextTerms = asItems(termResponse);
      const nextClasses = asItems(classResponse);
      const currentSession =
        nextSessions.find((item) => item.is_current) || nextSessions[0] || null;
      const currentTerm =
        nextTerms.find(
          (item) =>
            item.is_current &&
            (!currentSession || item.academic_session_id === currentSession.id),
        ) ||
        nextTerms.find(
          (item) => !currentSession || item.academic_session_id === currentSession.id,
        ) ||
        null;

      setSessions(nextSessions);
      setTerms(nextTerms);
      setClasses(nextClasses);
      setTemplates(asItems(templateResponse).filter((item) => item.status === "active"));
      setFilters((current) => ({
        ...current,
        class_id: current.class_id || nextClasses[0]?.id || "",
        academic_session_id:
          current.academic_session_id || currentSession?.id || nextSessions[0]?.id || "",
        academic_term_id:
          current.academic_term_id || currentTerm?.id || nextTerms[0]?.id || "",
      }));
      onContextChange?.({ currentSession, currentTerm });
    } catch (requestError) {
      const message = getErrorMessage(requestError, "Could not load report-card setup.");
      setError(message);
      showError(message);
    } finally {
      setLoading(false);
    }
  }, [onContextChange, showError]);

  const loadOverview = useCallback(async () => {
    if (!filters.class_id || !filters.academic_session_id || !filters.academic_term_id) {
      setOverview(null);
      return;
    }
    setOverviewLoading(true);
    try {
      const response = await reportCardService.getClassOverview({
        class_id: filters.class_id,
        academic_session_id: filters.academic_session_id,
        academic_term_id: filters.academic_term_id,
        search: debouncedReadinessQuery || undefined,
        offset: readinessPage * READINESS_PAGE_SIZE,
        limit: READINESS_PAGE_SIZE,
      });
      setOverview(response);
      setSelectedStudentId((current) =>
        current && asItems(response).some((item) => item.student_id === current) ? current : "",
      );
    } catch (requestError) {
      setOverview(null);
      showError(getErrorMessage(requestError, "Could not load report readiness."));
    } finally {
      setOverviewLoading(false);
    }
  }, [
    debouncedReadinessQuery,
    filters.academic_session_id,
    filters.academic_term_id,
    filters.class_id,
    readinessPage,
    showError,
  ]);

  const loadCards = useCallback(async () => {
    const requestVersion = ++cardRequestVersion.current;
    if (!filters.class_id || !filters.academic_session_id || !filters.academic_term_id) {
      setCards([]);
      setCardTotal(0);
      return;
    }
    try {
      const response = await reportCardService.listAdminReportCards({
        class_id: filters.class_id,
        academic_session_id: filters.academic_session_id,
        academic_term_id: filters.academic_term_id,
        status: filters.status || undefined,
        is_outdated:
          filters.record_state === "outdated"
            ? true
            : filters.record_state === "current"
              ? false
              : undefined,
        search: appliedCardSearch || undefined,
        skip: cardPage * CARD_PAGE_SIZE,
        limit: CARD_PAGE_SIZE,
      });
      if (requestVersion !== cardRequestVersion.current) return;
      setCards(asItems(response));
      setCardTotal(Number(response?.total || 0));
    } catch (requestError) {
      if (requestVersion !== cardRequestVersion.current) return;
      setCards([]);
      setCardTotal(0);
      showError(getErrorMessage(requestError, "Could not load report cards."));
    }
  }, [cardPage, filters, appliedCardSearch, showError]);

  useEffect(() => {
    loadBase();
  }, [loadBase]);

  useEffect(() => {
    loadCards();
  }, [loadCards]);

  useEffect(() => {
    if (["overview", "ready", "generate"].includes(activeTab)) loadOverview();
  }, [activeTab, loadOverview]);

  useEffect(() => {
    setGenerationSummary(null);
    if (activeTab !== "generate") setSelectedStudentId("");
  }, [activeTab]);

  const sessionOptions = useMemo(
    () => sessions.map((item) => ({ value: item.id, label: item.name })),
    [sessions],
  );
  const termOptions = useMemo(
    () =>
      terms
        .filter(
          (item) =>
            !filters.academic_session_id ||
            item.academic_session_id === filters.academic_session_id,
        )
        .map((item) => ({ value: item.id, label: termLabel(item) })),
    [filters.academic_session_id, terms],
  );
  const classOptions = useMemo(
    () => classes.map((item) => ({ value: item.id, label: classLabel(item) })),
    [classes],
  );

  const rows = overview?.items || [];
  const readinessTotal = Number(overview?.total || 0);
  const selectedStudent = rows.find((item) => item.student_id === selectedStudentId);
  const selectedClass = classes.find((item) => item.id === filters.class_id);
  const selectedSession = sessions.find((item) => item.id === filters.academic_session_id);
  const selectedTerm = terms.find((item) => item.id === filters.academic_term_id);
  const generationTemplateOptions = useMemo(
    () => templateOptionsForPerformance(templates, selectedStudent?.performance_percentage),
    [selectedStudent?.performance_percentage, templates],
  );
  const principalEditorTemplateOptions = useMemo(
    () => templateOptionsForPerformance(templates, principalEditor?.card?.average_score),
    [principalEditor?.card?.average_score, templates],
  );

  const updateFilters = (patch) => {
    setCardPage(0);
    setReadinessPage(0);
    setSelectedStudentId("");
    setFilters((current) => ({ ...current, ...patch }));
  };

  const buildGenerationPayload = () => {
    const payload = {
      academic_session_id: filters.academic_session_id,
      academic_term_id: filters.academic_term_id,
      ...(generationTarget === "class"
        ? { class_id: filters.class_id }
        : { student_id: selectedStudentId }),
    };
    if (generationTarget === "class" || principalMode === "default") {
      payload.apply_default_principal_template = true;
    } else if (principalMode === "template" && principalTemplateId) {
      payload.principal_template_id = principalTemplateId;
    } else if (principalMode === "manual" && principalComment.trim()) {
      payload.principal_comment = principalComment.trim();
    }
    return payload;
  };

  const resetSingleCreate = () => {
    setSelectedStudentId("");
    setPrincipalTemplateId("");
    setPrincipalComment("");
    setPrincipalMode("default");
    setGenerationSummary(null);
  };

  const generate = async ({ addMore = false } = {}) => {
    if (generationTarget === "student" && !selectedStudentId) {
      showWarning("Select a student first.");
      return;
    }
    if (generationTarget === "student" && selectedStudent?.report_readiness !== "ready") {
      showWarning("Resolve result or teacher-comment blockers before generating this report.");
      return;
    }
    if (generationTarget === "student" && principalMode === "template" && !principalTemplateId) {
      showWarning("Choose a principal comment for this performance range.");
      return;
    }
    if (generationTarget === "student" && principalMode === "manual" && !principalComment.trim()) {
      showWarning("Enter the principal comment to use.");
      return;
    }

    setSaving("generate");
    setGenerationSummary(null);
    try {
      const response = await reportCardService.generateReportCard(buildGenerationPayload());
      const generated = Array.isArray(response?.generated) ? response.generated : [response];
      const skipped = Array.isArray(response?.skipped) ? response.skipped : [];
      setGenerationSummary({ generated, skipped });
      showSuccess(
        generationTarget === "class"
          ? `${generated.length} report card${generated.length === 1 ? "" : "s"} generated.`
          : "Report card generated as a draft.",
      );
      await Promise.all([loadCards(), loadOverview()]);
      if (generationTarget === "student") {
        if (addMore) resetSingleCreate();
        else selectView("overview");
      }
    } catch (requestError) {
      showError(getErrorMessage(requestError, "Could not generate report card."));
    } finally {
      setSaving("");
    }
  };

  const submitOverride = async (event) => {
    event.preventDefault();
    if (!overrideState?.comment_text?.trim() || !overrideState?.reason?.trim()) return;
    setSaving("override");
    try {
      await reportCommentService.overrideTeacherComment({
        student_id: overrideState.student.student_id,
        academic_session_id: filters.academic_session_id,
        academic_term_id: filters.academic_term_id,
        comment_text: overrideState.comment_text.trim(),
        reason: overrideState.reason.trim(),
      });
      showSuccess("Teacher comment override recorded with its audit reason.");
      setOverrideState(null);
      await loadOverview();
    } catch (requestError) {
      showError(getErrorMessage(requestError, "Could not record the teacher comment override."));
    } finally {
      setSaving("");
    }
  };

  const openPreview = async (card) => {
    setSaving(`preview:${card.id}`);
    try {
      setPreviewCard(await reportCardService.getAdminReportCard(card.id));
    } catch (requestError) {
      showError(getErrorMessage(requestError, "Could not load report-card preview."));
    } finally {
      setSaving("");
    }
  };

  const publish = async (card) => {
    setSaving(card.id);
    try {
      await reportCardService.publishReportCard(card.id);
      showSuccess("Report card published as the current official version.");
      setPreviewCard(null);
      await Promise.all([loadCards(), loadOverview()]);
    } catch (requestError) {
      showError(getErrorMessage(requestError, "Could not publish report card."));
    } finally {
      setSaving("");
    }
  };

  const regenerate = async (card) => {
    setSaving(card.id);
    try {
      const replacement = await reportCardService.regenerateReportCard(card.id);
      showSuccess(
        card.status === "published"
          ? `Editable revision v${replacement?.version || Number(card.version || 1) + 1} created. The published version remains available until this draft is published.`
          : `Replacement report draft v${replacement?.version || Number(card.version || 1) + 1} created.`,
      );
      setRevisionTarget(null);
      setPreviewCard(null);
      await Promise.all([loadCards(), loadOverview()]);
    } catch (requestError) {
      showError(getErrorMessage(requestError, "Could not create the replacement report draft."));
    } finally {
      setSaving("");
    }
  };

  const cardPeriodKey = (card) =>
    [card.student_id, card.academic_session_id, card.academic_term_id].join(":");
  const periodsWithDraft = new Set(
    cards
      .filter(
        (card) =>
          card.status === "draft" && !card.superseded_at,
      )
      .map(cardPeriodKey),
  );

  const openPrincipalEditor = (card) => {
    setPrincipalEditor({
      card,
      template_id: card.principal_comment_source_template_id || "",
      comment: card.principal_comment || "",
    });
  };

  const savePrincipalComment = async (event) => {
    event.preventDefault();
    if (!principalEditor) return;
    const allowedTemplateIds = new Set(principalEditorTemplateOptions.map((item) => item.value));
    const selectedTemplate = templates.find(
      (item) => item.id === principalEditor.template_id && allowedTemplateIds.has(item.id),
    );
    if (principalEditor.template_id && !selectedTemplate) {
      showWarning("Choose a principal comment covering this report's performance percentage.");
      return;
    }
    const text = selectedTemplate?.text || principalEditor.comment.trim();
    if (!text) {
      showWarning("Choose a matching saved comment or enter a principal comment.");
      return;
    }
    setSaving("principal");
    try {
      const updated = await reportCardService.updatePrincipalComment(principalEditor.card.id, {
        principal_comment: text,
        principal_template_id: selectedTemplate?.id || null,
      });
      showSuccess("Principal comment updated on this draft.");
      setPrincipalEditor(null);
      if (previewCard?.id === updated?.id) setPreviewCard(updated);
      await loadCards();
    } catch (requestError) {
      showError(getErrorMessage(requestError, "Could not update the principal comment."));
    } finally {
      setSaving("");
    }
  };

  const rowActions = (card) => (
    <>
      <Button
        type="button"
        size="small"
        variant="outline"
        disabled={saving === `preview:${card.id}`}
        onClick={() => openPreview(card)}
      >
        <Eye className="h-4 w-4" /> Preview
      </Button>
      {card.status === "draft" ? (
        <Button type="button" size="small" variant="outline" onClick={() => openPrincipalEditor(card)}>
          Edit comment
        </Button>
      ) : null}
      {card.status === "draft" && !card.is_outdated ? (
        <Button
          type="button"
          size="small"
          variant="success"
          disabled={saving === card.id}
          onClick={() => publish(card)}
        >
          Publish
        </Button>
      ) : null}
      {card.status === "draft" ? (
        <Button
          type="button"
          size="small"
          variant="outline"
          disabled={saving === card.id}
          onClick={() => setRevisionTarget(card)}
        >
          Regenerate draft
        </Button>
      ) : null}
      {card.status === "published" && !periodsWithDraft.has(cardPeriodKey(card)) ? (
        <Button
          type="button"
          size="small"
          variant="outline"
          disabled={saving === card.id}
          onClick={() => setRevisionTarget(card)}
        >
          Create editable revision
        </Button>
      ) : null}
      {card.status === "published" && periodsWithDraft.has(cardPeriodKey(card)) ? (
        <span className="self-center text-xs font-semibold text-text-muted">
          Revision draft exists
        </span>
      ) : null}
    </>
  );

  const contextSelectors = (
    <div className="grid gap-3 rounded-xl border border-border/70 bg-surface px-4 py-4 sm:grid-cols-3">
      <SelectControl
        label="Class"
        value={filters.class_id}
        onChange={(value) => updateFilters({ class_id: value })}
        options={classOptions}
        required
      />
      <SelectControl
        label="Academic session"
        value={filters.academic_session_id}
        onChange={(value) => {
          const nextTerm =
            terms.find((item) => item.academic_session_id === value && item.is_current) ||
            terms.find((item) => item.academic_session_id === value);
          updateFilters({ academic_session_id: value, academic_term_id: nextTerm?.id || "" });
        }}
        options={sessionOptions}
        required
      />
      <SelectControl
        label="Academic term"
        value={filters.academic_term_id}
        onChange={(value) => updateFilters({ academic_term_id: value })}
        options={termOptions}
        required
      />
    </div>
  );

  const contextSummary = (
    <div className="flex flex-col gap-2 rounded-xl border border-border/70 bg-surface px-4 py-3 text-sm text-text-muted sm:flex-row sm:items-center sm:justify-between">
      <span>
        <span className="font-semibold text-text">Selected report context:</span>{" "}
        {classLabel(selectedClass)} · {selectedSession?.name || "No session"} · {termLabel(selectedTerm)}
      </span>
      <Button type="button" size="small" variant="outline" onClick={() => Promise.all([loadOverview(), loadCards()])}>
        <RefreshCw className="h-4 w-4" /> Refresh
      </Button>
    </div>
  );

  if (error && !loading) {
    return (
      <WorkspacePanel title="Report cards unavailable">
        <p className="text-sm text-error">{error}</p>
        <Button type="button" className="mt-4" onClick={loadBase}>Retry</Button>
      </WorkspacePanel>
    );
  }

  if (activeTab === "generate") {
    return (
      <div className="space-y-4">
        {contextSelectors}
        <WorkspacePanel
          title="Create report card"
          description="Choose the report context here. Creation does not depend on the Academic Hub overview page state."
          actions={
            <Button type="button" variant="outline" onClick={() => selectView("overview")}>
              <ArrowLeft className="h-4 w-4" /> Back to reports
            </Button>
          }
        >
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(300px,0.85fr)]">
            <div className="space-y-4">
              <SelectControl
                label="Generation target"
                value={generationTarget}
                onChange={(value) => {
                  setGenerationTarget(value);
                  resetSingleCreate();
                  if (value === "class") setPrincipalMode("default");
                }}
                options={[
                  { value: "student", label: "One student" },
                  { value: "class", label: "Entire class" },
                ]}
              />

              {generationTarget === "student" ? (
                <>
                  <Input
                    label="Find student"
                    value={readinessQuery}
                    placeholder="Name or admission number"
                    onChange={(event) => setReadinessQuery(event.target.value)}
                  />
                  <SelectControl
                    label="Student"
                    value={selectedStudentId}
                    onChange={(value) => {
                      setSelectedStudentId(value);
                      setPrincipalTemplateId("");
                      setPrincipalComment("");
                    }}
                    options={rows.map((item) => ({
                      value: item.student_id,
                      label: studentLabel(item),
                      description: `${humanize(item.report_readiness)} · ${formatPercent(
                        item.performance_percentage,
                      )}`,
                    }))}
                    disabled={overviewLoading}
                    required
                  />
                  <Pager
                    page={readinessPage}
                    total={readinessTotal}
                    pageSize={READINESS_PAGE_SIZE}
                    onPage={setReadinessPage}
                  />
                </>
              ) : (
                <div className="rounded-xl border border-border/70 bg-surface-muted/30 px-4 py-3 text-sm leading-6 text-text-muted">
                  The backend freezes the class population at the start of generation and processes it in bounded batches. Students with blockers are skipped and returned in the generation summary.
                </div>
              )}

              {generationTarget === "student" ? (
                <div className="flex flex-wrap gap-2">
                  <Button type="button" onClick={() => generate({ addMore: false })} disabled={saving === "generate"}>
                    <FilePlus2 className="h-4 w-4" />
                    {saving === "generate" ? "Creating..." : "Create & Exit"}
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => generate({ addMore: true })}
                    disabled={saving === "generate"}
                  >
                    Create & Add More
                  </Button>
                </div>
              ) : (
                <Button type="button" onClick={() => generate()} disabled={saving === "generate"}>
                  <FilePlus2 className="h-4 w-4" />
                  {saving === "generate" ? "Generating..." : "Generate class reports"}
                </Button>
              )}

              {generationSummary ? (
                <div className="rounded-xl border border-border/70 px-4 py-3 text-sm text-text-muted">
                  Generated <span className="font-semibold text-text">{generationSummary.generated.length}</span>{" "}
                  · Skipped <span className="font-semibold text-text">{generationSummary.skipped.length}</span>
                  {generationSummary.skipped.slice(0, 8).map((item) => (
                    <p className="mt-1" key={`${item.student_id}-${item.reason}`}>{item.reason}</p>
                  ))}
                </div>
              ) : null}
            </div>

            <div className="space-y-3 rounded-xl border border-border/70 bg-surface p-4">
              <p className="font-semibold text-text">Principal comment policy</p>
              {generationTarget === "class" ? (
                <p className="text-sm leading-6 text-text-muted">
                  Each student receives your default active principal comment for the inclusive performance range containing their calculated overall percentage. If no default exists, the report is still generated with manual principal-comment status.
                </p>
              ) : (
                <>
                  {selectedStudent ? (
                    <div className="rounded-lg bg-surface-muted/40 px-3 py-2 text-sm text-text-muted">
                      Performance: <span className="font-semibold text-text">{formatPercent(selectedStudent.performance_percentage)}</span>{" "}
                      · Grade: <span className="font-semibold text-text">{selectedStudent.overall_grade || "–"}</span>
                    </div>
                  ) : null}
                  <SelectControl
                    label="Comment source"
                    value={principalMode}
                    onChange={(value) => {
                      setPrincipalMode(value);
                      setPrincipalTemplateId("");
                      setPrincipalComment("");
                    }}
                    options={[
                      { value: "default", label: "Use my performance-range default" },
                      { value: "template", label: "Choose another comment in this range" },
                      { value: "manual", label: "Write a manual comment" },
                    ]}
                  />
                  {principalMode === "template" ? (
                    <SelectControl
                      label="Matching saved principal comment"
                      value={principalTemplateId}
                      onChange={setPrincipalTemplateId}
                      options={generationTemplateOptions}
                      disabled={asNumber(selectedStudent?.performance_percentage) === null}
                      required
                    />
                  ) : null}
                  {principalMode === "manual" ? (
                    <label className="grid gap-1.5 text-sm font-medium text-text-soft">
                      Principal comment
                      <textarea
                        className="w-full rounded-xl border border-border bg-surface px-3 py-2 text-sm text-text outline-none focus:border-primary"
                        rows={5}
                        maxLength={2000}
                        value={principalComment}
                        onChange={(event) => setPrincipalComment(event.target.value)}
                      />
                    </label>
                  ) : null}
                </>
              )}
            </div>
          </div>
        </WorkspacePanel>
      </div>
    );
  }

  if (activeTab === "ready") {
    return (
      <div className="space-y-4">
        {contextSelectors}
        {contextSummary}
        <ReadinessTable
          rows={rows}
          total={readinessTotal}
          loading={overviewLoading}
          query={readinessQuery}
          onQuery={setReadinessQuery}
          page={readinessPage}
          onPage={setReadinessPage}
          onOverride={(student) => setOverrideState({ student, comment_text: "", reason: "" })}
        />
        <OverrideModal
          state={overrideState}
          saving={saving === "override"}
          onChange={setOverrideState}
          onClose={() => setOverrideState(null)}
          onSubmit={submitOverride}
        />
      </div>
    );
  }

  return (
    <>
      <div className="mb-4 grid gap-3 rounded-xl border border-border/70 bg-surface px-4 py-4 sm:grid-cols-2 xl:grid-cols-5">
        <SelectControl label="Class" value={filters.class_id} onChange={(value) => updateFilters({ class_id: value })} options={classOptions} required />
        <SelectControl
          label="Academic session"
          value={filters.academic_session_id}
          onChange={(value) => {
            const nextTerm =
              terms.find((item) => item.academic_session_id === value && item.is_current) ||
              terms.find((item) => item.academic_session_id === value);
            updateFilters({ academic_session_id: value, academic_term_id: nextTerm?.id || "" });
          }}
          options={sessionOptions}
          required
        />
        <SelectControl label="Academic term" value={filters.academic_term_id} onChange={(value) => updateFilters({ academic_term_id: value })} options={termOptions} required />
        <SelectControl
          label="Lifecycle"
          value={filters.status}
          onChange={(value) => updateFilters({ status: value })}
          options={[
            { value: "draft", label: "Draft" },
            { value: "published", label: "Published" },
            { value: "archived", label: "Archived" },
          ]}
          placeholder="All lifecycle states"
          clearable
        />
        <SelectControl
          label="Record state"
          value={filters.record_state}
          onChange={(value) => updateFilters({ record_state: value })}
          options={[
            { value: "current", label: "Current" },
            { value: "outdated", label: "Outdated" },
          ]}
          placeholder="Current + outdated"
          clearable
        />
      </div>

      <RecordList
        title={`Report cards${loading ? "" : ` (${cardTotal})`}`}
        description="Drafts can be edited, regenerated and published. Published reports stay immutable; create an editable revision when corrections are required."
        actions={
          <Button type="button" onClick={() => selectView("generate")}>
            <FilePlus2 className="h-4 w-4" /> Create report
          </Button>
        }
        items={cards}
        searchValue={cardSearch}
        onSearchChange={(value) => { setCardPage(0); setCardSearch(value); }}
        loading={loading}
        emptyIcon={FileText}
        emptyTitle="No report cards found"
        emptyDescription="No generated report cards match the selected class, period and lifecycle filters."
        recordLabel="Student report"
        detailsLabel="Outcome"
        renderTitle={(card) => card.student_name || card.admission_number || "Student"}
        renderMeta={(card) => `${card.admission_number || "No admission number"} · Version ${card.version || 1}`}
        renderDescription={(card) =>
          `Performance ${formatPercent(card.average_score)} · Position ${
            card.position ? `${card.position}/${card.position_out_of || "–"}` : "–"
          }${card.department_name ? ` · ${card.department_name}` : ""}`
        }
        renderStatus={(card) => (card.is_outdated ? "outdated" : card.status)}
        renderActions={rowActions}
        renderInspector={(card) => <ReportInspector card={card} actions={rowActions(card)} />}
      />

      <div className="mt-4">
        <Pager page={cardPage} total={cardTotal} pageSize={CARD_PAGE_SIZE} onPage={setCardPage} />
      </div>

      <OverrideModal
        state={overrideState}
        saving={saving === "override"}
        onChange={setOverrideState}
        onClose={() => setOverrideState(null)}
        onSubmit={submitOverride}
      />

      <Modal
        open={Boolean(principalEditor)}
        title="Edit principal comment"
        description="Draft principal comments may use only saved wording covering this report's weighted performance percentage."
        onClose={() => setPrincipalEditor(null)}
      >
        {principalEditor ? (
          <form className="space-y-4" onSubmit={savePrincipalComment}>
            <div className="rounded-lg bg-surface-muted/40 px-3 py-2 text-sm text-text-muted">
              Report performance: <span className="font-semibold text-text">{formatPercent(principalEditor.card.average_score)}</span>
            </div>
            <SelectControl
              label="Matching saved comment"
              value={principalEditor.template_id}
              onChange={(value) => setPrincipalEditor((current) => ({ ...current, template_id: value, comment: "" }))}
              options={principalEditorTemplateOptions}
              clearable
            />
            <label className="grid gap-1.5 text-sm font-medium text-text-soft">
              Or write a manual principal comment
              <textarea
                value={principalEditor.comment}
                onChange={(event) => setPrincipalEditor((current) => ({ ...current, template_id: "", comment: event.target.value }))}
                rows={5}
                maxLength={2000}
                className="w-full rounded-xl border border-border bg-surface px-3 py-2 text-sm text-text outline-none focus:border-primary"
              />
            </label>
            <div className="flex justify-end gap-2">
              <Button type="button" variant="outline" onClick={() => setPrincipalEditor(null)}>Cancel</Button>
              <Button type="submit" disabled={saving === "principal"}>{saving === "principal" ? "Saving..." : "Save principal comment"}</Button>
            </div>
          </form>
        ) : null}
      </Modal>

      <Modal
        open={Boolean(previewCard)}
        title="Report card preview"
        description="The preview is rendered from the report snapshot. Passport photographs and signature blocks are intentionally excluded."
        onClose={() => setPreviewCard(null)}
        footer={
          previewCard ? (
            <div className="flex flex-wrap justify-end gap-2">
              {previewCard.status === "draft" ? (
                <Button type="button" variant="outline" onClick={() => openPrincipalEditor(previewCard)}>Edit principal comment</Button>
              ) : null}
              {previewCard.status === "draft" ? (
                <Button type="button" variant="outline" disabled={saving === previewCard.id} onClick={() => setRevisionTarget(previewCard)}>
                  Regenerate draft
                </Button>
              ) : null}
              {previewCard.status === "published" && !periodsWithDraft.has(cardPeriodKey(previewCard)) ? (
                <Button type="button" variant="outline" disabled={saving === previewCard.id} onClick={() => setRevisionTarget(previewCard)}>
                  Create editable revision
                </Button>
              ) : null}
              {previewCard.status === "draft" && !previewCard.is_outdated ? (
                <Button type="button" variant="success" disabled={saving === previewCard.id} onClick={() => publish(previewCard)}>
                  <CheckCircle2 className="h-4 w-4" /> {saving === previewCard.id ? "Publishing..." : "Publish official version"}
                </Button>
              ) : null}
            </div>
          ) : null
        }
      >
        {previewCard ? <ReportSheet card={previewCard} /> : null}
      </Modal>

      <Modal
        open={Boolean(revisionTarget)}
        title={
          revisionTarget?.status === "published"
            ? "Create an editable report revision?"
            : "Regenerate this report draft?"
        }
        description={
          revisionTarget?.status === "published"
            ? "Weave will preserve the published report as the official version and create a new draft from the latest locked results and comments. Families will not see the revision until you publish it."
            : "Weave will archive this draft and create a replacement from the latest locked results and comments."
        }
        onClose={() => (saving ? undefined : setRevisionTarget(null))}
        footer={
          revisionTarget ? (
            <div className="flex justify-end gap-2">
              <Button type="button" variant="outline" disabled={saving === revisionTarget.id} onClick={() => setRevisionTarget(null)}>
                Cancel
              </Button>
              <Button type="button" disabled={saving === revisionTarget.id} onClick={() => regenerate(revisionTarget)}>
                {saving === revisionTarget.id
                  ? "Creating..."
                  : revisionTarget.status === "published"
                    ? "Create revision draft"
                    : "Regenerate draft"}
              </Button>
            </div>
          ) : null
        }
      >
        {revisionTarget ? (
          <div className="rounded-xl border border-border/70 bg-surface-muted/30 px-4 py-3 text-sm text-text-muted">
            <span className="font-semibold text-text">
              {revisionTarget.student_name || revisionTarget.admission_number || "Student"}
            </span>{" "}
            · Version {revisionTarget.version || 1} · {humanize(revisionTarget.status)}
          </div>
        ) : null}
      </Modal>
    </>
  );
}

function Pager({ page, total, pageSize, onPage }) {
  const first = total === 0 ? 0 : page * pageSize + 1;
  const last = Math.min(total, (page + 1) * pageSize);
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 text-sm text-text-muted">
      <span>Showing {first}–{last} of {total}</span>
      <div className="flex gap-2">
        <Button type="button" size="small" variant="outline" disabled={page <= 0} onClick={() => onPage(Math.max(0, page - 1))}>Previous</Button>
        <Button type="button" size="small" variant="outline" disabled={(page + 1) * pageSize >= total} onClick={() => onPage(page + 1)}>Next</Button>
      </div>
    </div>
  );
}

function ReportInspector({ card, actions }) {
  return (
    <div className="overflow-hidden rounded-xl border border-border/70 bg-surface">
      <div className="border-b border-border/70 p-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="font-semibold text-text">{card.student_name || card.admission_number || "Student"}</p>
            <p className="mt-1 text-xs text-text-muted">Version {card.version || 1}</p>
          </div>
          <StatusBadge value={card.is_outdated ? "outdated" : card.status} />
        </div>
      </div>
      <div className="divide-y divide-border/70">
        <section className="p-4">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-text-faint">Outcome</p>
          <dl className="mt-3 space-y-2 text-sm">
            <div className="flex justify-between gap-4"><dt className="text-text-muted">Performance</dt><dd className="font-semibold text-text">{formatPercent(card.average_score)}</dd></div>
            <div className="flex justify-between gap-4"><dt className="text-text-muted">Position</dt><dd className="font-semibold text-text">{card.position ? `${card.position}/${card.position_out_of || "–"}` : "–"}</dd></div>
            <div className="flex justify-between gap-4"><dt className="text-text-muted">Department</dt><dd className="text-right font-semibold text-text">{card.department_name || "No specialization"}</dd></div>
          </dl>
        </section>
        <section className="p-4">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-text-faint">Report actions</p>
          <div className="mt-3 flex flex-wrap gap-2">{actions}</div>
        </section>
      </div>
    </div>
  );
}

function ReadinessTable({ rows, total, loading, query, onQuery, page, onPage, onOverride }) {
  return (
    <WorkspacePanel
      title="Student readiness"
      description="This table is server-paginated. Search and page changes resolve only the requested student slice."
      actions={
        <Input label="Search" value={query} placeholder="Student or admission number" onChange={(event) => onQuery(event.target.value)} />
      }
    >
      {loading ? (
        <p className="py-8 text-center text-sm text-text-muted">Resolving readiness...</p>
      ) : rows.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border px-4 py-8 text-center text-sm text-text-muted">No students match this report context.</div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-border/70">
          <table className="w-full min-w-[1060px] text-left text-sm">
            <thead className="bg-surface-muted/60 text-xs uppercase tracking-wide text-text-muted">
              <tr>
                <th className="px-4 py-3">Student</th>
                <th className="px-4 py-3">Results</th>
                <th className="px-4 py-3">Teacher comment</th>
                <th className="px-4 py-3">Performance</th>
                <th className="px-4 py-3">Grade</th>
                <th className="px-4 py-3">Principal comment</th>
                <th className="px-4 py-3">Readiness</th>
                <th className="px-4 py-3">Report</th>
                <th className="px-4 py-3 text-right">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/70">
              {rows.map((item) => {
                const canOverride = ["missing", "needs_review"].includes(item.teacher_comment_status);
                return (
                  <tr key={item.student_id}>
                    <td className="px-4 py-3"><p className="font-semibold text-text">{item.student_name || "Student"}</p><p className="text-xs text-text-muted">{item.admission_number}</p></td>
                    <td className="px-4 py-3"><StatusBadge value={item.results_readiness} /><p className="mt-1 text-xs text-text-muted">{item.submitted_count}/{item.expected_count} locked</p>{item.missing_subject_names?.length ? <p className="mt-1 max-w-52 text-xs text-error">Missing: {item.missing_subject_names.join(", ")}</p> : null}</td>
                    <td className="px-4 py-3"><StatusBadge value={item.teacher_comment_status} /></td>
                    <td className="px-4 py-3 font-semibold text-text">{formatPercent(item.performance_percentage)}</td>
                    <td className="px-4 py-3 font-semibold text-text">{item.overall_grade || "–"}</td>
                    <td className="px-4 py-3"><StatusBadge value={item.principal_comment_status} /></td>
                    <td className="px-4 py-3"><StatusBadge value={item.report_readiness} /></td>
                    <td className="px-4 py-3">{item.report_card_id ? <div className="flex flex-wrap gap-1.5"><StatusBadge value={item.is_outdated ? "outdated" : item.report_card_status} /><Badge variant="default">v{item.report_card_version || 1}</Badge></div> : <span className="text-text-muted">Not generated</span>}</td>
                    <td className="px-4 py-3 text-right">
                      {canOverride ? (
                        <Button type="button" size="small" variant="outline" onClick={() => onOverride(item)}><MessageSquareWarning className="h-4 w-4" /> Override</Button>
                      ) : item.report_readiness === "waiting_for_results" ? (
                        <span className="inline-flex items-center gap-1 text-xs font-semibold text-warning"><TriangleAlert className="h-4 w-4" /> Resolve results</span>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-xs font-semibold text-success"><CheckCircle2 className="h-4 w-4" /> Ready</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <div className="mt-4"><Pager page={page} total={total} pageSize={READINESS_PAGE_SIZE} onPage={onPage} /></div>
    </WorkspacePanel>
  );
}

function OverrideModal({ state, saving, onChange, onClose, onSubmit }) {
  return (
    <Modal
      open={Boolean(state)}
      title="Override class-teacher comment"
      description="Use this only when the effective class-teacher comment is missing or needs review. The reason is stored as audit evidence."
      onClose={saving ? undefined : onClose}
    >
      {state ? (
        <form className="space-y-4" onSubmit={onSubmit}>
          <div className="rounded-xl border border-warning/30 bg-warning-soft/40 px-4 py-3 text-sm text-text-soft">
            <p className="font-semibold text-text">{studentLabel(state.student)}</p>
            <p className="mt-1">Current teacher-comment state: {humanize(state.student.teacher_comment_status)}</p>
          </div>
          <label className="grid gap-1.5 text-sm font-medium text-text-soft">Override comment<textarea value={state.comment_text} onChange={(event) => onChange((current) => ({ ...current, comment_text: event.target.value }))} rows={5} maxLength={2000} className="w-full rounded-xl border border-border bg-surface px-3 py-2 text-sm text-text outline-none focus:border-primary" required /></label>
          <label className="grid gap-1.5 text-sm font-medium text-text-soft">Audit reason<textarea value={state.reason} onChange={(event) => onChange((current) => ({ ...current, reason: event.target.value }))} rows={3} maxLength={1000} className="w-full rounded-xl border border-border bg-surface px-3 py-2 text-sm text-text outline-none focus:border-primary" required /></label>
          <div className="flex justify-end gap-2"><Button type="button" variant="outline" disabled={saving} onClick={onClose}>Cancel</Button><Button type="submit" disabled={saving}>{saving ? "Saving..." : "Record override"}</Button></div>
        </form>
      ) : null}
    </Modal>
  );
}

function ReportSheet({ card }) {
  const className = [card.class_name, card.class_arm].filter(Boolean).join(" ") || "–";
  return (
    <article className="mx-auto max-w-5xl overflow-hidden rounded-2xl border border-border bg-white text-slate-900 shadow-sm">
      <header className="border-b border-slate-200 px-6 py-6 text-center sm:px-8">
        <p className="text-xs font-semibold uppercase tracking-[0.25em] text-slate-500">Academic performance report</p>
        <h2 className="mt-2 text-2xl font-bold">{card.school_name || "School Report Card"}</h2>
        {card.school_address ? <p className="mt-1 text-sm text-slate-500">{card.school_address}</p> : null}
        <div className="mt-3 flex flex-wrap justify-center gap-x-4 gap-y-1 text-sm text-slate-600">
          <span>{card.academic_session_name || "Academic session"}</span>
          <span>•</span>
          <span>{humanize(card.academic_term_name, "Academic term")}</span>
          <span>•</span>
          <span>Version {card.version || 1}</span>
        </div>
      </header>

      <section className="grid gap-x-6 gap-y-3 border-b border-slate-200 bg-slate-50 px-6 py-5 text-sm sm:grid-cols-2 lg:grid-cols-4 sm:px-8">
        <ReportDatum label="Student" value={card.student_name || "–"} />
        <ReportDatum label="Admission number" value={card.admission_number || "–"} />
        <ReportDatum label="Class" value={className} />
        <ReportDatum label="Department" value={card.department_name || "General"} />
      </section>

      <section className="overflow-x-auto px-6 py-6 sm:px-8">
        <table className="w-full min-w-[760px] border-collapse text-sm">
          <thead>
            <tr className="border-y border-slate-300 bg-slate-100 text-left text-xs uppercase tracking-wide text-slate-600">
              <th className="px-3 py-3">Subject</th>
              <th className="px-3 py-3">Assessment</th>
              <th className="px-3 py-3 text-right">Total</th>
              <th className="px-3 py-3">Grade</th>
              <th className="px-3 py-3">Remark</th>
              <th className="px-3 py-3">Teacher</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200">
            {(card.lines || []).map((line) => (
              <tr key={line.id || line.subject_id}>
                <td className="px-3 py-3 font-semibold">{line.subject_name}</td>
                <td className="px-3 py-3 text-slate-600">
                  {(line.components || []).length
                    ? (line.components || [])
                        .map((component) => `${component.name}: ${component.score}/${component.maximum_score}`)
                        .join(" · ")
                    : "–"}
                </td>
                <td className="px-3 py-3 text-right font-semibold">{line.total_score}</td>
                <td className="px-3 py-3 font-semibold">{line.grade || "–"}</td>
                <td className="px-3 py-3 text-slate-600">{line.remark || "–"}</td>
                <td className="px-3 py-3 text-slate-600">{line.teacher_name || "–"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="grid gap-3 border-y border-slate-200 bg-slate-50 px-6 py-5 sm:grid-cols-3 sm:px-8">
        <ReportMetric label="Overall performance" value={formatPercent(card.average_score)} />
        <ReportMetric label="Class position" value={card.position ? `${card.position}/${card.position_out_of || "–"}` : "–"} />
        <ReportMetric label="Class teacher" value={card.class_teacher_name || "Not assigned"} />
      </section>

      <section className="grid gap-5 px-6 py-6 sm:grid-cols-2 sm:px-8">
        <ReportComment label="Class teacher comment" value={card.class_teacher_comment || "No comment recorded."} />
        <ReportComment label="Principal comment" value={card.principal_comment || "No comment recorded."} />
      </section>
    </article>
  );
}

function ReportDatum({ label, value }) {
  return <div><p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</p><p className="mt-1 font-semibold text-slate-900">{value}</p></div>;
}

function ReportMetric({ label, value }) {
  return <div className="rounded-xl border border-slate-200 bg-white px-4 py-3 text-center"><p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</p><p className="mt-1 text-lg font-bold text-slate-900">{value}</p></div>;
}

function ReportComment({ label, value }) {
  return <div><p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</p><p className="mt-2 whitespace-pre-wrap rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm leading-6 text-slate-700">{value}</p></div>;
}

export default ReportCardsWorkspace;
