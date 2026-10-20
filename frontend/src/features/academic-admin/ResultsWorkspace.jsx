import { ArrowLeft, ClipboardList, Plus } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import Badge from "../../components/ui/Badge";
import Button from "../../components/ui/Button";
import Modal from "../../components/ui/Modal";
import { useToast } from "../../hooks/useToast";
import { academicService } from "../../services/academicService";
import { classService } from "../../services/academicsService";
import { getErrorMessage } from "../../services/api";
import { studentService } from "../../services/studentService";
import {
  Input,
  RecordList,
  SelectControl,
  WorkspacePanel,
} from "./AcademicWorkspacePrimitives";
import {
  assignmentsAvailableForEntry,
  componentScoresForAssignment,
} from "./resultEntryAvailability";

const PAGE_SIZE = 100;
const BLANK_FORM = {
  result_id: "",
  student_id: "",
  teacher_assignment_id: "",
  component_scores: {},
  hybrid_parts: {},
  cbt_changes: {},
  correction_reasons: {},
};

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
  `${[item?.first_name, item?.last_name].filter(Boolean).join(" ") || "Student"} · ${
    item?.admission_number || "No admission number"
  }`;

const assignmentLabel = (item) =>
  `${item?.subject_name || "Subject"} · ${
    item?.teacher_name || item?.teacher_staff_id || "Teacher"
  }`;

const readableTerm = (item) =>
  String(item?.display_name || item?.name || "No term").replaceAll("_", " ");

const scoreValue = (value) =>
  value === "" || value === null || value === undefined ? null : Number(value);

const statusTitle = (status) =>
  ({ submitted: "Submit result", approved: "Approve result", locked: "Lock result" })[
    status
  ] || "Confirm result action";

const statusDescription = (status, item) =>
  ({
    submitted: `Submit ${item.student_name || "this student's"} ${
      item.subject_name || "result"
    } for review?`,
    approved: `Approve ${item.student_name || "this student's"} ${
      item.subject_name || "result"
    }?`,
    locked: `Lock ${item.student_name || "this student's"} ${
      item.subject_name || "result"
    }? Locked results become final for reporting until explicitly reopened.`,
  })[status] || "Confirm this result lifecycle action.";

const badgeVariant = (status) => {
  if (status === "draft") return "warning";
  if (status === "locked") return "default";
  return "success";
};

function ResultsWorkspace({ activeTab, onContextChange }) {
  const { showSuccess, showError, showWarning } = useToast();
  const [searchParams, setSearchParams] = useSearchParams();
  const [sessions, setSessions] = useState([]);
  const [terms, setTerms] = useState([]);
  const [classes, setClasses] = useState([]);
  const [assignments, setAssignments] = useState([]);
  const [students, setStudents] = useState([]);
  const [results, setResults] = useState([]);
  const [resultTotal, setResultTotal] = useState(0);
  const [resultPage, setResultPage] = useState(0);
  const [assessmentConfig, setAssessmentConfig] = useState(null);
  const [entryResults, setEntryResults] = useState([]);
  const [entryResultsLoading, setEntryResultsLoading] = useState(false);
  const [entryResultsError, setEntryResultsError] = useState("");
  const [filters, setFilters] = useState({
    class_id: "",
    academic_session_id: "",
    academic_term_id: "",
    status: "",
    subject_id: "",
  });
  const [form, setForm] = useState(BLANK_FORM);
  const [pendingAction, setPendingAction] = useState(null);
  const [reopenTarget, setReopenTarget] = useState(null);
  const [reopenReason, setReopenReason] = useState("");
  const [saving, setSaving] = useState("");
  const [loading, setLoading] = useState(true);
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

  const resetForm = () => setForm(BLANK_FORM);

  const loadBase = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [sessionResponse, termResponse, classResponse, assignmentResponse, configResponse] =
        await Promise.all([
          academicService.listSessions({ limit: 100 }),
          academicService.listTerms({ limit: 100 }),
          classService.getClasses({ limit: 100, activeOnly: true }),
          academicService.listTeacherAssignments({ status: "current", limit: 100 }),
          academicService.getActiveAssessmentScheme().catch(() => null),
        ]);

      const nextSessions = asItems(sessionResponse);
      const nextTerms = asItems(termResponse);
      const nextClasses = asItems(classResponse);
      const currentSession = nextSessions.find((item) => item.is_current) || nextSessions[0] || null;
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
      setAssignments(asItems(assignmentResponse));
      setAssessmentConfig(configResponse || null);
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
      const message = getErrorMessage(requestError, "Could not load results workspace.");
      setError(message);
      showError(message);
    } finally {
      setLoading(false);
    }
  }, [onContextChange, showError]);

  const loadStudents = useCallback(async () => {
    if (!filters.class_id) {
      setStudents([]);
      return;
    }
    try {
      const response = await studentService.getAdminStudents({
        classId: filters.class_id,
        status: "active",
        limit: 100,
      });
      setStudents(asItems(response));
    } catch (requestError) {
      setStudents([]);
      showError(getErrorMessage(requestError, "Could not load students for this class."));
    }
  }, [filters.class_id, showError]);

  const loadResults = useCallback(async () => {
    if (!filters.class_id || !filters.academic_session_id || !filters.academic_term_id) {
      setResults([]);
      setResultTotal(0);
      return;
    }
    try {
      const response = await academicService.listAdminResults({
        class_id: filters.class_id,
        academic_session_id: filters.academic_session_id,
        academic_term_id: filters.academic_term_id,
        status: filters.status || undefined,
        subject_id: filters.subject_id || undefined,
        skip: resultPage * PAGE_SIZE,
        limit: PAGE_SIZE,
      });
      setResults(asItems(response));
      setResultTotal(Number(response?.total || 0));
    } catch (requestError) {
      setResults([]);
      setResultTotal(0);
      showError(getErrorMessage(requestError, "Could not load results."));
    }
  }, [filters, resultPage, showError]);

  useEffect(() => {
    loadBase();
  }, [loadBase]);

  useEffect(() => {
    loadStudents();
  }, [loadStudents]);

  useEffect(() => {
    loadResults();
  }, [loadResults]);

  useEffect(() => {
    setPendingAction(null);
    setReopenTarget(null);
    setReopenReason("");
    if (activeTab !== "entry") resetForm();
  }, [activeTab]);

  useEffect(() => {
    let cancelled = false;
    if (
      activeTab !== "entry" ||
      form.result_id ||
      !form.student_id ||
      !filters.class_id ||
      !filters.academic_session_id ||
      !filters.academic_term_id
    ) {
      setEntryResults([]);
      setEntryResultsError("");
      setEntryResultsLoading(false);
      return undefined;
    }

    const loadEntryResults = async () => {
      setEntryResults([]);
      setEntryResultsError("");
      setEntryResultsLoading(true);
      try {
        const params = {
          student_id: form.student_id,
          class_id: filters.class_id,
          academic_session_id: filters.academic_session_id,
          academic_term_id: filters.academic_term_id,
          limit: PAGE_SIZE,
        };
        const firstPage = await academicService.listAdminResults({ ...params, skip: 0 });
        const rows = asItems(firstPage);
        const total = Number(firstPage?.total || rows.length);
        for (let skip = PAGE_SIZE; skip < total; skip += PAGE_SIZE) {
          const page = await academicService.listAdminResults({ ...params, skip });
          rows.push(...asItems(page));
        }
        if (!cancelled) setEntryResults(rows);
      } catch (requestError) {
        if (!cancelled) {
          setEntryResults([]);
          setEntryResultsError(
            getErrorMessage(
              requestError,
              "Could not determine which subjects still need scores.",
            ),
          );
        }
      } finally {
        if (!cancelled) setEntryResultsLoading(false);
      }
    };

    loadEntryResults();
    return () => {
      cancelled = true;
    };
  }, [
    activeTab,
    filters.academic_session_id,
    filters.academic_term_id,
    filters.class_id,
    form.result_id,
    form.student_id,
  ]);

  const selectedSession = sessions.find((item) => item.id === filters.academic_session_id);
  const selectedTerm = terms.find((item) => item.id === filters.academic_term_id);
  const periodEditable = Boolean(
    selectedSession?.status === "open" &&
      selectedSession?.is_current &&
      selectedTerm?.status === "open" &&
      selectedTerm?.is_current &&
      selectedTerm?.academic_session_id === selectedSession?.id,
  );
  const limitsConfigured = Boolean(
    assessmentConfig?.is_configured && assessmentConfig?.components?.length,
  );

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
        .map((item) => ({ value: item.id, label: readableTerm(item) })),
    [filters.academic_session_id, terms],
  );
  const classOptions = useMemo(
    () => classes.map((item) => ({ value: item.id, label: classLabel(item) })),
    [classes],
  );
  const assignmentOptions = useMemo(
    () => {
      const availableAssignments = form.result_id
        ? assignments.filter((item) => item.class_id === filters.class_id)
        : form.student_id && !entryResultsLoading && !entryResultsError
          ? assignmentsAvailableForEntry(assignments, entryResults, filters.class_id)
          : [];
      return availableAssignments.map((item) => ({
        value: item.id,
        label: assignmentLabel(item),
      }));
    },
    [
      assignments,
      entryResults,
      entryResultsError,
      entryResultsLoading,
      filters.class_id,
      form.result_id,
      form.student_id,
    ],
  );
  const studentOptions = useMemo(
    () => students.map((item) => ({ value: item.id, label: studentLabel(item) })),
    [students],
  );
  const subjectOptions = useMemo(() => {
    const rows = new Map();
    assignments
      .filter((item) => !filters.class_id || item.class_id === filters.class_id)
      .forEach((item) => {
        if (!item.subject_id || rows.has(item.subject_id)) return;
        rows.set(item.subject_id, {
          value: item.subject_id,
          label:
            [item.subject_name, item.subject_code].filter(Boolean).join(" · ") || "Subject",
        });
      });
    return [...rows.values()];
  }, [assignments, filters.class_id]);

  const scoreTotal = (assessmentConfig?.components || []).reduce(
    (sum, component) => sum +
      (Number(form.component_scores?.[component.id]) || 0) +
      (component.is_hybrid ? (Number(form.cbt_changes?.[component.id] ?? form.hybrid_parts?.[component.id]?.cbt_score) || 0) : 0),
    0,
  );
  const totalMaximum = limitsConfigured ? Number(assessmentConfig.total_maximum_score) : null;

  const updateFilters = (patch) => {
    setResultPage(0);
    setFilters((current) => ({ ...current, ...patch }));
    resetForm();
  };

  const validateScores = () => {
    if (!limitsConfigured) {
      showWarning("Configure and activate an assessment scheme before entering scores.");
      return false;
    }
    for (const component of assessmentConfig.components) {
      const part = form.hybrid_parts?.[component.id];
      const maximum = component.is_hybrid && part ? Number(part.theory_maximum_score) : Number(component.maximum_score);
      const value = form.component_scores?.[component.id];
      if (value !== "" && value != null && (Number(value) < 0 || Number(value) > maximum)) {
        showWarning(`${component.name} must be between 0 and ${maximum}.`);
        return false;
      }
      if (component.is_hybrid && part?.cbt_score != null) {
        const corrected = form.cbt_changes?.[component.id];
        if (corrected !== undefined && (corrected === "" || Number(corrected) < 0 || Number(corrected) > Number(part.cbt_maximum_score))) {
          showWarning("Corrected CBT score exceeds its allocated maximum.");
          return false;
        }
        if (corrected !== undefined && Number(corrected) !== Number(part.cbt_score) &&
            !form.correction_reasons?.[component.id]?.trim()) {
          showWarning("Enter a reason for the CBT score correction.");
          return false;
        }
      }
    }
    return true;
  };

  const saveDraft = async ({ addMore = false } = {}) => {
    if (!periodEditable) {
      showWarning("Results can only be edited in the current open session and term.");
      return;
    }
    if (!form.student_id || !form.teacher_assignment_id || !validateScores()) {
      if (!form.student_id || !form.teacher_assignment_id) {
        showWarning("Select a student and subject assignment.");
      }
      return;
    }
    setSaving("result");
    try {
      const savedResult = await academicService.saveAdminResult({
        student_id: form.student_id,
        teacher_assignment_id: form.teacher_assignment_id,
        academic_session_id: filters.academic_session_id,
        academic_term_id: filters.academic_term_id,
        component_scores: assessmentConfig.components.map((component) => {
          if (!component.is_hybrid) return {
            assessment_component_id: component.id,
            score: scoreValue(form.component_scores?.[component.id]),
          };
          const part = form.hybrid_parts?.[component.id];
          if (part?.cbt_score == null) return null;
          const corrected = form.cbt_changes?.[component.id];
          return {
            assessment_component_id: component.id,
            theory_score: scoreValue(form.component_scores?.[component.id]),
            ...(corrected !== undefined && Number(corrected) !== Number(part.cbt_score)
              ? { cbt_score: Number(corrected), correction_reason: form.correction_reasons?.[component.id]?.trim() }
              : {}),
          };
        }).filter(Boolean),
        status: "draft",
      });
      showSuccess(form.result_id ? "Draft result updated." : "Draft result created.");
      await loadResults();
      if (addMore && !form.result_id) {
        setEntryResults((current) => [
          savedResult,
          ...current.filter((item) => item.id !== savedResult.id),
        ]);
        setForm({ ...BLANK_FORM, student_id: form.student_id });
      } else {
        resetForm();
        selectView("overview");
      }
    } catch (requestError) {
      showError(getErrorMessage(requestError, "Could not save result draft."));
    } finally {
      setSaving("");
    }
  };

  const editResult = (item) => {
    setForm({
      result_id: item.id,
      student_id: item.student_id || "",
      teacher_assignment_id: item.teacher_assignment_id || "",
      component_scores: Object.fromEntries(
        (item.components || []).map((component) => [
          component.assessment_component_id,
          component.is_hybrid ? (component.theory_score ?? "") : (component.score ?? ""),
        ]),
      ),
      hybrid_parts: Object.fromEntries(
        (item.components || []).filter((component) => component.is_hybrid && component.cbt_score != null)
          .map((component) => [component.assessment_component_id, component]),
      ),
      cbt_changes: {},
      correction_reasons: {},
    });
    selectView("entry");
  };

  const executeLifecycleAction = async () => {
    if (!pendingAction) return;
    const { item, status } = pendingAction;
    setSaving(item.id);
    try {
      await academicService.updateResultStatus(item.id, { status });
      showSuccess(`Result moved to ${status}.`);
      setPendingAction(null);
      await loadResults();
    } catch (requestError) {
      showError(getErrorMessage(requestError, "Could not update result status."));
    } finally {
      setSaving("");
    }
  };

  const reopenResult = async () => {
    if (!reopenTarget || reopenReason.trim().length < 3) return;
    setSaving(reopenTarget.id);
    try {
      await academicService.reopenResult(reopenTarget.id, { reason: reopenReason.trim() });
      showSuccess("Result reopened to draft for correction.");
      setReopenTarget(null);
      setReopenReason("");
      await loadResults();
    } catch (requestError) {
      showError(getErrorMessage(requestError, "Could not reopen result."));
    } finally {
      setSaving("");
    }
  };

  const rowActions = (item) => (
    <ResultActions
      item={item}
      periodEditable={periodEditable}
      busy={saving === item.id}
      onEdit={editResult}
      onTransition={(status) => setPendingAction({ item, status })}
      onReopen={() => {
        setReopenTarget(item);
        setReopenReason("");
      }}
    />
  );

  const contextSelectors = (
    <div className="grid gap-3 rounded-xl border border-border/70 bg-surface px-4 py-4 sm:grid-cols-3">
      <SelectControl
        label="Class"
        value={filters.class_id}
        onChange={(value) => updateFilters({ class_id: value, subject_id: "" })}
        options={classOptions}
        disabled={Boolean(form.result_id)}
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
        disabled={Boolean(form.result_id)}
        required
      />
      <SelectControl
        label="Academic term"
        value={filters.academic_term_id}
        onChange={(value) => updateFilters({ academic_term_id: value })}
        options={termOptions}
        disabled={Boolean(form.result_id)}
        required
      />
    </div>
  );

  if (error && !loading) {
    return (
      <WorkspacePanel title="Results unavailable">
        <p className="text-sm text-error">{error}</p>
        <Button type="button" className="mt-4" onClick={loadBase}>Retry</Button>
      </WorkspacePanel>
    );
  }

  if (activeTab === "entry") {
    return (
      <div className="space-y-4">
        {contextSelectors}
        <WorkspacePanel
          title={form.result_id ? "Edit draft result" : "Create result"}
          description="The class, session and term are selected inside this creation flow. It does not depend on the Academic Hub overview context."
          actions={
            <Button type="button" variant="outline" onClick={() => { resetForm(); selectView("overview"); }}>
              <ArrowLeft className="h-4 w-4" /> Back to results
            </Button>
          }
        >
          {!periodEditable ? (
            <p className="mb-3 rounded-xl border border-warning/30 bg-warning-soft px-4 py-3 text-sm text-warning">
              The selected period is read-only. Result entry requires the current open session and term.
            </p>
          ) : null}
          {!limitsConfigured ? (
            <p className="mb-3 rounded-xl border border-warning/30 bg-warning-soft px-4 py-3 text-sm text-warning">
              No assessment scheme is active. Configure Grading → Assessment Scheme before entering scores.
            </p>
          ) : null}
          <div className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-2">
              <SelectControl
                label="Student"
                value={form.student_id}
                onChange={(value) => {
                  setEntryResults([]);
                  setEntryResultsError("");
                  setEntryResultsLoading(Boolean(value));
                  setForm((current) => ({
                    ...current,
                    student_id: value,
                    teacher_assignment_id: "",
                    component_scores: {},
                    hybrid_parts: {},
                    cbt_changes: {},
                    correction_reasons: {},
                  }));
                }}
                options={studentOptions}
                disabled={!periodEditable || !limitsConfigured || Boolean(form.result_id)}
                required
              />
              <SelectControl
                label="Subject assignment"
                value={form.teacher_assignment_id}
                onChange={(value) => {
                  const assignment = assignments.find((item) => item.id === value);
                  const prior = entryResults.find((item) => item.curriculum_subject_id === assignment?.curriculum_subject_id);
                  setForm((current) => ({
                    ...current,
                    teacher_assignment_id: value,
                    component_scores: prior ? Object.fromEntries((prior.components || []).map((part) => [
                      part.assessment_component_id, part.is_hybrid ? (part.theory_score ?? "") : (part.score ?? ""),
                    ])) : componentScoresForAssignment(entryResults, assignment),
                    hybrid_parts: prior ? Object.fromEntries((prior.components || [])
                      .filter((part) => part.is_hybrid && part.cbt_score != null)
                      .map((part) => [part.assessment_component_id, part])) : {},
                    cbt_changes: {},
                    correction_reasons: {},
                  }));
                }}
                options={assignmentOptions}
                placeholder={
                  !form.student_id
                    ? "Select a student first"
                    : entryResultsLoading
                      ? "Checking unfinished subjects..."
                      : entryResultsError
                        ? "Subject availability unavailable"
                        : assignmentOptions.length
                          ? "Select unfinished subject"
                          : "All assigned subjects are complete"
                }
                disabled={
                  !periodEditable ||
                  !limitsConfigured ||
                  Boolean(form.result_id) ||
                  !form.student_id ||
                  entryResultsLoading ||
                  Boolean(entryResultsError)
                }
                required
              />
            </div>
            {entryResultsError ? (
              <p className="rounded-xl border border-error/30 bg-error-soft px-4 py-3 text-sm text-error">
                {entryResultsError} Refresh the page before entering another result.
              </p>
            ) : null}
            {!form.result_id && form.student_id && !entryResultsLoading && !entryResultsError ? (
              <p className="text-sm text-text-muted">
                Subjects with every assessment component filled are hidden here. Use Back to
                results to edit or reopen an existing result deliberately.
              </p>
            ) : null}
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {(assessmentConfig?.components || []).map((component) => {
                const part = form.hybrid_parts?.[component.id];
                if (component.is_hybrid) return (
                  <div key={component.id} className="space-y-2 rounded-lg border border-border p-3">
                    <p className="text-sm font-medium text-text">{component.name} · Hybrid / {component.maximum_score}</p>
                    {part?.cbt_score == null ? (
                      <p className="text-xs text-text-muted">Awaiting student's CBT score synchronization</p>
                    ) : (
                      <>
                        <Input label={`CBT (0–${part.cbt_maximum_score})`} type="number" min="0"
                          max={part.cbt_maximum_score} step="0.01"
                          value={form.cbt_changes?.[component.id] ?? part.cbt_score}
                          disabled={!periodEditable || !limitsConfigured}
                          onChange={(event) => setForm((current) => ({
                            ...current, cbt_changes: { ...current.cbt_changes, [component.id]: event.target.value },
                          }))} />
                        {form.cbt_changes?.[component.id] !== undefined &&
                          Number(form.cbt_changes[component.id]) !== Number(part.cbt_score) ? (
                          <Input label="Reason for CBT correction" value={form.correction_reasons?.[component.id] || ""}
                            disabled={!periodEditable || !limitsConfigured}
                            onChange={(event) => setForm((current) => ({
                              ...current, correction_reasons: { ...current.correction_reasons, [component.id]: event.target.value },
                            }))} />
                        ) : null}
                        {Number(part.theory_maximum_score) > 0 ? (
                          <Input label={`Theory (0–${part.theory_maximum_score})`} type="number"
                            min="0" max={part.theory_maximum_score} step="0.01"
                            value={form.component_scores?.[component.id] ?? ""}
                            disabled={!periodEditable || !limitsConfigured}
                            onChange={(event) => setForm((current) => ({
                              ...current, component_scores: { ...current.component_scores, [component.id]: event.target.value },
                            }))} />
                        ) : <p className="text-xs text-text-muted">Full CBT allocation; no theory entry.</p>}
                      </>
                    )}
                  </div>
                );
                return (
                  <Input key={component.id} label={`${component.name} (0–${component.maximum_score})`}
                    type="number" min="0" max={component.maximum_score}
                    value={form.component_scores?.[component.id] ?? ""}
                    disabled={!periodEditable || !limitsConfigured}
                    onChange={(event) => setForm((current) => ({
                      ...current, component_scores: { ...current.component_scores, [component.id]: event.target.value },
                    }))} />
                );
              })}
            </div>
            <div className="rounded-xl border border-border/70 bg-surface-muted/30 px-3 py-2 text-sm text-text-muted">
              Combined score: <span className="font-semibold text-text">{scoreTotal}</span>
              {totalMaximum != null ? ` / ${totalMaximum}` : ""}
            </div>
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                disabled={!periodEditable || !limitsConfigured || saving === "result"}
                onClick={() => saveDraft({ addMore: false })}
              >
                {saving === "result"
                  ? "Saving..."
                  : form.result_id
                    ? "Update & Exit"
                    : "Create & Exit"}
              </Button>
              {!form.result_id ? (
                <Button
                  type="button"
                  variant="outline"
                  disabled={!periodEditable || !limitsConfigured || saving === "result"}
                  onClick={() => saveDraft({ addMore: true })}
                >
                  Create & Add More
                </Button>
              ) : (
                <Button type="button" variant="outline" onClick={resetForm}>Cancel edit</Button>
              )}
            </div>
          </div>
        </WorkspacePanel>
      </div>
    );
  }

  return (
    <>
      <div className="mb-4 grid gap-3 rounded-xl border border-border/70 bg-surface px-4 py-4 sm:grid-cols-2 xl:grid-cols-5">
        <SelectControl label="Class" value={filters.class_id} onChange={(value) => updateFilters({ class_id: value, subject_id: "" })} options={classOptions} required />
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
        <SelectControl label="Subject" value={filters.subject_id} onChange={(value) => updateFilters({ subject_id: value })} options={subjectOptions} placeholder="All subjects" clearable />
        <SelectControl
          label="Lifecycle"
          value={filters.status}
          onChange={(value) => updateFilters({ status: value })}
          options={[
            { value: "draft", label: "Draft" },
            { value: "submitted", label: "Submitted" },
            { value: "approved", label: "Approved" },
            { value: "locked", label: "Locked" },
          ]}
          placeholder="All lifecycle states"
          clearable
        />
      </div>

      {!periodEditable ? (
        <div className="mb-4 rounded-xl border border-warning/30 bg-warning-soft px-4 py-3 text-sm text-warning">
          This academic period is read-only. Historical results remain visible, but lifecycle changes are disabled.
        </div>
      ) : null}

      <RecordList
        title={`Results${loading ? "" : ` (${resultTotal})`}`}
        description="Inspect score details and move each result through Draft → Submitted → Approved → Locked from its row."
        actions={
          <Button type="button" disabled={!limitsConfigured} onClick={() => { resetForm(); selectView("entry"); }}>
            <Plus className="h-4 w-4" /> Create result
          </Button>
        }
        items={results}
        loading={loading}
        emptyIcon={ClipboardList}
        emptyTitle="No results found"
        emptyDescription="No result records match the selected class, period, subject and lifecycle filters."
        recordLabel="Student result"
        detailsLabel="Score"
        renderTitle={(item) => item.student_name || item.admission_number || "Student"}
        renderMeta={(item) => item.subject_name || item.subject_code || "Subject"}
        renderDescription={(item) =>
          `Total ${item.total_score ?? "–"}${
            item.maximum_score != null ? `/${item.maximum_score}` : ""
          } · Grade ${item.grade || "Pending"}`
        }
        renderStatus={(item) => item.status}
        renderActions={rowActions}
        renderInspector={(item) => <ResultInspector item={item} actions={rowActions(item)} />}
      />

      <div className="mt-4 flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-text-muted">Showing {results.length} of {resultTotal} results</p>
        <div className="flex gap-2">
          <Button type="button" size="small" variant="outline" disabled={resultPage === 0 || loading} onClick={() => setResultPage((value) => Math.max(0, value - 1))}>Previous</Button>
          <Button type="button" size="small" variant="outline" disabled={(resultPage + 1) * PAGE_SIZE >= resultTotal || loading} onClick={() => setResultPage((value) => value + 1)}>Next</Button>
        </div>
      </div>

      <Modal
        open={Boolean(pendingAction)}
        title={pendingAction ? statusTitle(pendingAction.status) : "Confirm result action"}
        description={pendingAction ? statusDescription(pendingAction.status, pendingAction.item) : ""}
        onClose={saving ? undefined : () => setPendingAction(null)}
        footer={
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" disabled={Boolean(saving)} onClick={() => setPendingAction(null)}>Cancel</Button>
            <Button type="button" variant={pendingAction?.status === "locked" ? "danger" : "primary"} disabled={Boolean(saving)} onClick={executeLifecycleAction}>
              {saving ? "Saving..." : pendingAction ? statusTitle(pendingAction.status) : "Confirm"}
            </Button>
          </div>
        }
      />

      <Modal
        open={Boolean(reopenTarget)}
        title="Reopen locked result"
        description="Reopening returns the result to draft and marks affected generated reports outdated without altering published evidence."
        onClose={saving ? undefined : () => setReopenTarget(null)}
        footer={
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" disabled={Boolean(saving)} onClick={() => setReopenTarget(null)}>Cancel</Button>
            <Button type="button" variant="danger" disabled={Boolean(saving) || reopenReason.trim().length < 3} onClick={reopenResult}>
              {saving ? "Reopening..." : "Reopen result"}
            </Button>
          </div>
        }
      >
        <Input label="Audit reason" value={reopenReason} onChange={(event) => setReopenReason(event.target.value)} minLength={3} maxLength={500} required />
      </Modal>
    </>
  );
}

function ResultActions({ item, periodEditable, busy, onEdit, onTransition, onReopen }) {
  if (item.status === "draft") {
    return (
      <>
        <Button type="button" size="small" variant="outline" disabled={!periodEditable || busy} onClick={() => onEdit(item)}>Edit</Button>
        <Button type="button" size="small" variant="success" disabled={!periodEditable || busy} onClick={() => onTransition("submitted")}>Submit</Button>
      </>
    );
  }
  if (item.status === "submitted") {
    return <Button type="button" size="small" variant="success" disabled={!periodEditable || busy} onClick={() => onTransition("approved")}>Approve</Button>;
  }
  if (item.status === "approved") {
    return <Button type="button" size="small" variant="danger" disabled={!periodEditable || busy} onClick={() => onTransition("locked")}>Lock</Button>;
  }
  return <Button type="button" size="small" variant="outline" disabled={!periodEditable || busy} onClick={onReopen}>Reopen</Button>;
}

function ResultInspector({ item, actions }) {
  return (
    <div className="overflow-hidden rounded-xl border border-border/70 bg-surface">
      <div className="border-b border-border/70 p-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="font-semibold text-text">{item.student_name || item.admission_number || "Student"}</p>
            <p className="mt-1 text-xs text-text-muted">{item.subject_name || item.subject_code || "Subject"}</p>
          </div>
          <Badge variant={badgeVariant(item.status)}>{item.status}</Badge>
        </div>
      </div>
      <div className="divide-y divide-border/70">
        <section className="p-4">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-text-faint">Scores</p>
          <dl className="mt-3 space-y-2 text-sm">
            {(item.components || []).map((component) => (
              <div key={component.assessment_component_id || component.name} className="flex justify-between gap-4">
                <dt className="text-text-muted">{component.name}</dt>
                <dd className="font-semibold text-text">{component.score ?? "–"}{component.maximum_score != null ? `/${component.maximum_score}` : ""}{component.is_hybrid && component.cbt_score != null ? ` (CBT ${component.cbt_score}/${component.cbt_maximum_score}${component.theory_maximum_score > 0 ? ` · Theory ${component.theory_score ?? "–"}/${component.theory_maximum_score}` : ""})` : ""}</dd>
              </div>
            ))}
            <div className="flex justify-between gap-4 border-t border-border/70 pt-2">
              <dt className="font-semibold text-text">Total</dt>
              <dd className="font-semibold text-text">{item.total_score ?? "–"}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-text-muted">Grade</dt>
              <dd className="font-semibold text-text">{item.grade || "Pending"}</dd>
            </div>
          </dl>
        </section>
        <section className="p-4">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-text-faint">Actions</p>
          <div className="mt-3 flex flex-wrap gap-2">{actions}</div>
        </section>
      </div>
    </div>
  );
}

export default ResultsWorkspace;
