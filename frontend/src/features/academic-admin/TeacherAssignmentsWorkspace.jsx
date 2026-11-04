import {
  beginAcademicSubmission,
  endAcademicSubmission,
  finishAcademicCreation,
} from "./academicSubmission";
import { ArrowLeft, UserPlus, Users } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";

import Badge from "../../components/ui/Badge";
import Button from "../../components/ui/Button";
import Modal from "../../components/ui/Modal";
import { useToast } from "../../hooks/useToast";
import { academicService } from "../../services/academicService";
import { classService } from "../../services/academicsService";
import { getErrorMessage, parseApiError } from "../../services/api";
import { curriculumService } from "../../services/curriculumService";
import { teacherService } from "../../services/teacherService";
import {
  FormActions,
  Input,
  RecordList,
  SelectControl,
  WorkspacePanel,
} from "./AcademicWorkspacePrimitives";

const PAGE_SIZE = 25;
const today = () => new Date().toISOString().slice(0, 10);
const nextDate = (value) => {
  const parsed = new Date(`${value}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return today();
  parsed.setUTCDate(parsed.getUTCDate() + 1);
  return parsed.toISOString().slice(0, 10);
};

const asItems = (response) =>
  Array.isArray(response)
    ? response
    : Array.isArray(response?.items)
      ? response.items
      : [];

const classLabel = (item) =>
  item?.display_name ||
  [item?.academic_level_name, item?.arm_label || item?.class_arm]
    .filter(Boolean)
    .join(" ") ||
  item?.class_name ||
  "Unnamed class";

const teacherLabel = (item) => {
  const account = item?.teacher_account || item?.account || {};
  return (
    [account.first_name, account.last_name].filter(Boolean).join(" ") ||
    item?.teacher_name ||
    account.email ||
    item?.staff_id ||
    item?.teacher_staff_id ||
    "Teacher"
  );
};

const assignmentClassLabel = (item) =>
  [item?.class_name, item?.class_arm].filter(Boolean).join(" ") || "Class";

const isMarkedToEnd = (item) =>
  String(item?.status || "").toLowerCase() === "current" &&
  Boolean(item?.effective_to) &&
  !item?.has_scheduled_takeover;

const formatPeriod = (item) => {
  const period = `${item?.effective_from || "Unknown start"} – ${item?.effective_to || "Present"}`;
  if (item?.has_scheduled_takeover) {
    return `${period} · HANDOVER SCHEDULED to ${item.scheduled_takeover_teacher_name || "incoming teacher"} on ${item.scheduled_takeover_effective_from}`;
  }
  if (isMarkedToEnd(item)) return `${period} · MARKED TO END`;
  return period;
};

const formatDependencyMessage = (preview) => {
  const counts = preview?.dependency_counts || {};
  const details = Object.entries(counts)
    .filter(([, value]) => Number(value || 0) > 0)
    .map(([key, value]) => `${key.replaceAll("_", " ")}: ${value}`)
    .join("; ");
  return [(preview?.blocker_messages || []).join(" "), details]
    .filter(Boolean)
    .join(" ");
};

const assignmentErrorMessage = (error) => {
  const parsed = parseApiError(
    error,
    "Weave could not update this teacher assignment. Review the teacher, takeover date and any existing scheduled handover, then try again.",
  );
  const messages = {
    ASSIGNMENT_CORRECTION_BLOCKED:
      "This assignment already has academic records attached to it, so its history cannot be rewritten. Choose a later date for the new teacher to take over.",
    TAKEOVER_ALREADY_SCHEDULED:
      "A teacher takeover is already scheduled for this class and subject. Open the existing handover to change or cancel it first.",
    SAME_TEACHER:
      "Choose a different teacher. This teacher is already assigned to this class and subject.",
    SCHEDULED_ASSIGNMENT_CANNOT_END:
      "This assignment has not started yet. Edit or cancel the schedule instead.",
    ASSIGNMENT_OVERLAP:
      "The selected date overlaps an existing teacher assignment for this class and subject. Choose another date.",
    TAKEOVER_OUTSIDE_TERM:
      "The selected takeover date must fall within the current academic term.",
    SCHEDULE_DATE_IN_PAST:
      "Choose today or a future date for this assignment schedule.",
    DATE_BEFORE_ASSIGNMENT_START:
      "The last teaching date cannot be before this assignment started.",
    ASSIGNMENT_NOT_SCHEDULED:
      "This assignment has already started and can no longer be managed as a schedule.",
  };
  return messages[parsed?.data?.code] || parsed.message;
};

function TeacherAssignmentsWorkspace({ activeTab }) {
  const { showSuccess, showError, showWarning } = useToast();
  const [searchParams, setSearchParams] = useSearchParams();
  const [classes, setClasses] = useState([]);
  const [teachers, setTeachers] = useState([]);
  const [currentTerm, setCurrentTerm] = useState(null);
  const [assignments, setAssignments] = useState([]);
  const [assignmentTotal, setAssignmentTotal] = useState(0);
  const [assignmentPage, setAssignmentPage] = useState(0);
  const [assignmentSearch, setAssignmentSearch] = useState("");
  const [appliedAssignmentSearch, setAppliedAssignmentSearch] = useState("");
  useEffect(() => {
    const timer = window.setTimeout(() => setAppliedAssignmentSearch(assignmentSearch.trim()), 250);
    return () => window.clearTimeout(timer);
  }, [assignmentSearch]);
  const [assignmentLoading, setAssignmentLoading] = useState(true);
  const assignmentRequestGeneration = useRef(0);
  const [filters, setFilters] = useState({
    class_id: "",
    teacher_membership_id: "",
    status: "",
  });
  const [assignmentLevelId, setAssignmentLevelId] = useState("");
  const [curriculumSubjects, setCurriculumSubjects] = useState([]);
  const [subjectAvailabilityLoading, setSubjectAvailabilityLoading] = useState(false);
  const [subjectAvailabilityError, setSubjectAvailabilityError] = useState("");
  const [coverageRefreshKey, setCoverageRefreshKey] = useState(0);
  const [eligibleClasses, setEligibleClasses] = useState([]);
  const [selectedClassIds, setSelectedClassIds] = useState([]);
  const [form, setForm] = useState({
    curriculum_subject_id: "",
    teacher_membership_id: "",
    effective_from: today(),
  });
  const [reassigning, setReassigning] = useState(null);
  const [scheduleEditing, setScheduleEditing] = useState(null);
  const [scheduleForm, setScheduleForm] = useState({
    teacher_membership_id: "",
    effective_from: today(),
  });
  const [ending, setEnding] = useState(null);
  const [pendingCancel, setPendingCancel] = useState(null);
  const [reason, setReason] = useState("");
  const [effectiveTo, setEffectiveTo] = useState(today());
  const [saving, setSaving] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const currentTermId = currentTerm?.id || "";

  const selectView = useCallback(
    (view) => {
      const next = new URLSearchParams(searchParams);
      next.set("view", view);
      next.delete("tab");
      setSearchParams(next, { replace: true });
    },
    [searchParams, setSearchParams],
  );

  const resetCreateForm = () => {
    setForm({
      curriculum_subject_id: "",
      teacher_membership_id: "",
      effective_from: today(),
    });
    setSelectedClassIds([]);
  };

  const loadBase = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [classResponse, teacherResponse, termResponse] = await Promise.all([
        classService.getClasses({ limit: 500, activeOnly: true }),
        teacherService.listMemberships({ limit: 100 }),
        academicService.listTerms({ limit: 100 }),
      ]);
      const nextClasses = asItems(classResponse);
      const nextTerms = asItems(termResponse);
      setClasses(nextClasses);
      setTeachers(
        asItems(teacherResponse).filter(
          (item) => String(item.status || "active").toLowerCase() === "active",
        ),
      );
      setCurrentTerm(
        nextTerms.find(
          (item) => item.is_current && String(item.status || "").toLowerCase() === "open",
        ) || null,
      );
      setAssignmentLevelId((current) =>
        current || nextClasses.find((item) => item.academic_level_id)?.academic_level_id || "",
      );
    } catch (requestError) {
      const message = getErrorMessage(requestError, "Could not load teacher assignments.");
      setError(message);
      showError(message);
    } finally {
      setLoading(false);
    }
  }, [showError]);

  const loadAssignments = useCallback(async ({ signal } = {}) => {
    const requestGeneration = ++assignmentRequestGeneration.current;
    setAssignmentLoading(true);
    try {
      const response = await academicService.listTeacherAssignments(
        {
          class_id: filters.class_id || undefined,
          teacher_membership_id: filters.teacher_membership_id || undefined,
          status: filters.status || undefined,
          search: appliedAssignmentSearch || undefined,
          skip: assignmentPage * PAGE_SIZE,
          limit: PAGE_SIZE,
        },
        { signal },
      );
      if (signal?.aborted || requestGeneration !== assignmentRequestGeneration.current) return;
      setAssignments(asItems(response));
      setAssignmentTotal(Number(response?.total || 0));
    } catch (requestError) {
      if (signal?.aborted || requestGeneration !== assignmentRequestGeneration.current) return;
      showError(getErrorMessage(requestError, "Could not load teacher assignments."));
    } finally {
      if (requestGeneration === assignmentRequestGeneration.current) {
        setAssignmentLoading(false);
      }
    }
  }, [assignmentPage, filters, appliedAssignmentSearch, showError]);

  useEffect(() => {
    loadBase();
  }, [loadBase]);

  useEffect(() => {
    const controller = new AbortController();
    loadAssignments({ signal: controller.signal });
    return () => controller.abort();
  }, [loadAssignments]);

  useEffect(() => {
    let cancelled = false;
    if (!assignmentLevelId || !currentTermId || activeTab !== "assign") {
      setCurriculumSubjects([]);
      setSubjectAvailabilityLoading(false);
      setSubjectAvailabilityError("");
      return undefined;
    }
    setCurriculumSubjects([]);
    setSubjectAvailabilityLoading(true);
    setSubjectAvailabilityError("");
    Promise.all([
      curriculumService.getCurriculum(assignmentLevelId),
      curriculumService.getTeacherAssignmentAvailability(assignmentLevelId, currentTermId),
    ])
      .then(([curriculumResponse, availabilityResponse]) => {
        if (cancelled) return;
        const availableSubjectIds = new Set(
          asItems(availabilityResponse)
            .filter((item) => Number(item.unassigned_class_count || 0) > 0)
            .map((item) => item.curriculum_subject_id),
        );
        setCurriculumSubjects(
          (curriculumResponse?.subjects || [])
            .filter((item) => item.is_active !== false && !item.archived_at)
            .map((item) => ({ ...item, id: item.id || item.curriculum_subject_id }))
            .filter((item) => availableSubjectIds.has(item.id)),
        );
      })
      .catch((requestError) => {
        if (cancelled) return;
        setCurriculumSubjects([]);
        const message = getErrorMessage(
          requestError,
          "Could not check which subjects still need teacher coverage.",
        );
        setSubjectAvailabilityError(message);
        showError(message);
      })
      .finally(() => {
        if (!cancelled) setSubjectAvailabilityLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [activeTab, assignmentLevelId, coverageRefreshKey, currentTermId, showError]);

  useEffect(() => {
    let cancelled = false;
    if (!form.curriculum_subject_id || !currentTermId || activeTab !== "assign") {
      setEligibleClasses([]);
      setSelectedClassIds([]);
      return undefined;
    }
    curriculumService
      .getEligibleClasses(form.curriculum_subject_id, currentTermId)
      .then((response) => {
        if (cancelled) return;
        const rows = asItems(response).filter(
          (item) => item.academic_level_id === assignmentLevelId,
        );
        setEligibleClasses(rows);
        setSelectedClassIds((current) => {
          const allowed = new Set(
            rows.filter((item) => !item.already_assigned).map((item) => item.class_id),
          );
          return current.filter((id) => allowed.has(id));
        });
      })
      .catch((requestError) => {
        if (cancelled) return;
        setEligibleClasses([]);
        setSelectedClassIds([]);
        showError(getErrorMessage(requestError, "Could not load eligible classes."));
      });
    return () => {
      cancelled = true;
    };
  }, [activeTab, assignmentLevelId, currentTermId, form.curriculum_subject_id, showError]);

  const levelOptions = useMemo(() => {
    const rows = new Map();
    classes.forEach((item) => {
      if (item.academic_level_id && !rows.has(item.academic_level_id)) {
        rows.set(item.academic_level_id, {
          value: item.academic_level_id,
          label: item.academic_level_name || "Academic level",
        });
      }
    });
    return [...rows.values()];
  }, [classes]);

  const classOptions = useMemo(
    () => classes.map((item) => ({ value: item.id, label: classLabel(item) })),
    [classes],
  );
  const teacherOptions = useMemo(
    () => teachers.map((item) => ({ value: item.id, label: teacherLabel(item) })),
    [teachers],
  );
  const replacementTeacherOptions = useMemo(
    () =>
      teacherOptions.filter(
        (option) => option.value !== reassigning?.teacher_membership_id,
      ),
    [reassigning?.teacher_membership_id, teacherOptions],
  );
  const visibleAssignments = useMemo(() => {
    if (filters.status) return assignments;
    const actualById = new Map(assignments.map((item) => [item.id, item]));
    const renderedIds = new Set();
    const rows = [];
    assignments.forEach((item) => {
      if (renderedIds.has(item.id)) return;
      rows.push(item);
      renderedIds.add(item.id);
      if (!item.has_scheduled_takeover || !item.scheduled_takeover_id) return;
      const linked = actualById.get(item.scheduled_takeover_id) || {
        id: item.scheduled_takeover_id,
        tenant_id: item.tenant_id,
        curriculum_subject_id: item.curriculum_subject_id,
        teacher_membership_id: item.scheduled_takeover_teacher_membership_id,
        class_id: item.class_id,
        class_name: item.class_name,
        class_arm: item.class_arm,
        subject_id: item.subject_id,
        subject_name: item.subject_name,
        subject_code: item.subject_code,
        teacher_name: item.scheduled_takeover_teacher_name,
        status: "scheduled",
        effective_from: item.scheduled_takeover_effective_from,
        effective_to: null,
      };
      if (!renderedIds.has(linked.id)) {
        rows.push({ ...linked, linked_takeover: true });
        renderedIds.add(linked.id);
      }
    });
    return rows;
  }, [assignments, filters.status]);
  const subjectOptions = useMemo(
    () =>
      curriculumSubjects.map((item) => ({
        value: item.id,
        label: [item.subject_name, item.subject_code, item.is_elective ? "Elective" : null]
          .filter(Boolean)
          .join(" · "),
      })),
    [curriculumSubjects],
  );

  const updateFilters = (patch) => {
    setAssignmentPage(0);
    setFilters((current) => ({ ...current, ...patch }));
  };

  const saveAssignment = async (event) => {
    event.preventDefault();
    if (!currentTermId || !assignmentLevelId || !form.curriculum_subject_id) {
      showWarning("Choose an academic level and subject in the current open term.");
      return;
    }
    if (!form.teacher_membership_id || selectedClassIds.length === 0) {
      showWarning("Choose a teacher and at least one eligible class.");
      return;
    }
    const submission = beginAcademicSubmission(event, Boolean(saving));
    if (!submission) return;
    setSaving("create");
    try {
      await curriculumService.createTeacherAssignmentsBulk({
        class_ids: selectedClassIds,
        curriculum_subject_id: form.curriculum_subject_id,
        academic_term_id: currentTermId,
        teacher_membership_id: form.teacher_membership_id,
        effective_from: form.effective_from,
      });
      showSuccess(
        `Teacher assigned to ${selectedClassIds.length} class${selectedClassIds.length === 1 ? "" : "es"}.`,
      );
      finishAcademicCreation(
        submission,
        resetCreateForm,
        () => selectView("overview"),
      );
      setCoverageRefreshKey((current) => current + 1);
      await loadAssignments();
    } catch (requestError) {
      showError(getErrorMessage(requestError, "Could not create teacher assignments."));
    } finally {
      endAcademicSubmission(submission);
      setSaving("");
    }
  };

  const submitReassign = async (event) => {
    event.preventDefault();
    if (!reassigning || !currentTermId || reason.trim().length < 3) {
      showWarning("Choose a replacement teacher and enter an audit reason.");
      return;
    }
    if (form.teacher_membership_id === reassigning.teacher_membership_id) {
      showWarning(
        "Choose a different teacher. This teacher is already assigned to this class and subject.",
      );
      return;
    }
    setSaving(reassigning.id);
    try {
      await academicService.reassignTeacherAssignment(reassigning.id, {
        academic_term_id: currentTermId,
        teacher_membership_id: form.teacher_membership_id,
        effective_from: form.effective_from,
        reason: reason.trim(),
      });
      showSuccess("Teacher assignment reassigned and history preserved.");
      setReassigning(null);
      setReason("");
      await loadAssignments();
    } catch (requestError) {
      showError(assignmentErrorMessage(requestError));
    } finally {
      setSaving("");
    }
  };

  const submitEnd = async (event) => {
    event.preventDefault();
    if (!ending || !currentTermId || reason.trim().length < 3) return;
    setSaving(ending.id);
    try {
      const preview = await academicService.getTeacherAssignmentDependencies(ending.id);
      if (!preview?.can_end) {
        showError(formatDependencyMessage(preview) || "This assignment cannot be ended.");
        return;
      }
      await academicService.endTeacherAssignment(ending.id, {
        academic_term_id: currentTermId,
        reason: reason.trim(),
        effective_to: effectiveTo || null,
      });
      showSuccess("Assignment ended and retained in history.");
      setEnding(null);
      setReason("");
      await loadAssignments();
    } catch (requestError) {
      showError(assignmentErrorMessage(requestError));
    } finally {
      setSaving("");
    }
  };

  const openScheduleEditor = (item) => {
    setReason("");
    setScheduleForm({
      teacher_membership_id: item.teacher_membership_id || "",
      effective_from: item.effective_from || today(),
    });
    setScheduleEditing(item);
  };

  const submitScheduleEdit = async (event) => {
    event.preventDefault();
    if (!scheduleEditing || !currentTermId || reason.trim().length < 3) return;
    setSaving(scheduleEditing.id);
    try {
      await academicService.updateScheduledTeacherAssignment(scheduleEditing.id, {
        academic_term_id: currentTermId,
        teacher_membership_id: scheduleForm.teacher_membership_id,
        effective_from: scheduleForm.effective_from,
        reason: reason.trim(),
      });
      showSuccess("Scheduled teacher assignment updated.");
      setScheduleEditing(null);
      setReason("");
      await loadAssignments();
    } catch (requestError) {
      showError(assignmentErrorMessage(requestError));
    } finally {
      setSaving("");
    }
  };

  const cancelSchedule = async () => {
    if (!pendingCancel || reason.trim().length < 3) return;
    setSaving(pendingCancel.id);
    try {
      await academicService.cancelScheduledTeacherAssignment(pendingCancel.id, {
        reason: reason.trim(),
      });
      showSuccess("Scheduled teacher assignment cancelled.");
      setPendingCancel(null);
      setReason("");
      await loadAssignments();
    } catch (requestError) {
      showError(assignmentErrorMessage(requestError));
    } finally {
      setSaving("");
    }
  };

  const openReassign = (item) => {
    setReason("");
    setForm((current) => ({
      ...current,
      teacher_membership_id: "",
      effective_from: isMarkedToEnd(item) ? nextDate(item.effective_to) : today(),
    }));
    setReassigning(item);
  };

  const rowActions = (item) => {
    const status = String(item.status || "").toLowerCase();
    if (status === "current") {
      return (
        <>
          {item.has_scheduled_takeover ? (
            <Button
              type="button"
              size="small"
              variant="outline"
              disabled={saving === item.id}
              onClick={() =>
                openScheduleEditor({
                  id: item.scheduled_takeover_id,
                  teacher_membership_id:
                    item.scheduled_takeover_teacher_membership_id,
                  teacher_name: item.scheduled_takeover_teacher_name,
                  effective_from: item.scheduled_takeover_effective_from,
                  is_takeover: true,
                })
              }
            >
              Manage handover
            </Button>
          ) : (
            <Button type="button" size="small" variant="outline" disabled={saving === item.id} onClick={() => openReassign(item)}>
              Reassign
            </Button>
          )}
          <Button
            type="button"
            size="small"
            variant="danger"
            disabled={saving === item.id}
            onClick={() => {
              setReason("");
              setEffectiveTo(item.effective_to || today());
              setEnding(item);
            }}
          >
            End
          </Button>
        </>
      );
    }
    if (status === "scheduled") {
      return (
        <>
          <Button type="button" size="small" variant="outline" disabled={saving === item.id} onClick={() => openScheduleEditor(item)}>
            Edit schedule
          </Button>
          <Button
            type="button"
            size="small"
            variant="danger"
            disabled={saving === item.id}
            onClick={() => {
              setReason("");
              setPendingCancel(item);
            }}
          >
            Cancel schedule
          </Button>
        </>
      );
    }
    return null;
  };

  const editor = (
    <WorkspacePanel
      title="Assign subject teacher"
      description={
        currentTerm
          ? "Choose a level and subject, then select every eligible class that should receive this teacher assignment."
          : "Open an academic term before creating teacher assignments."
      }
      actions={
        <Button type="button" variant="outline" onClick={() => selectView("overview")}>
          <ArrowLeft className="h-4 w-4" /> Back to assignments
        </Button>
      }
    >
      <form className="space-y-4" onSubmit={saveAssignment}>
        <fieldset disabled={Boolean(saving)} className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <SelectControl
              label="Academic level"
              value={assignmentLevelId}
              onChange={(value) => {
                setAssignmentLevelId(value);
                setForm((current) => ({ ...current, curriculum_subject_id: "" }));
                setSelectedClassIds([]);
              }}
              options={levelOptions}
              placeholder="Select academic level"
              disabled={!currentTerm}
              required
            />
            <SelectControl
              label="Subject"
              value={form.curriculum_subject_id}
              onChange={(value) => {
                setForm((current) => ({ ...current, curriculum_subject_id: value }));
                setSelectedClassIds([]);
              }}
              options={subjectOptions}
              placeholder={
                !assignmentLevelId
                  ? "Select level first"
                  : subjectAvailabilityLoading
                    ? "Checking subject coverage..."
                    : curriculumSubjects.length === 0 && !subjectAvailabilityError
                      ? "All eligible subjects assigned"
                      : "Select subject"
              }
              disabled={
                !currentTerm ||
                !assignmentLevelId ||
                subjectAvailabilityLoading ||
                Boolean(subjectAvailabilityError) ||
                curriculumSubjects.length === 0
              }
              required
            />
            <SelectControl
              label="Teacher"
              value={form.teacher_membership_id}
              onChange={(value) => setForm((current) => ({ ...current, teacher_membership_id: value }))}
              options={teacherOptions}
              placeholder="Select teacher"
              required
            />
            <Input
              label="Effective from"
              type="date"
              value={form.effective_from}
              onChange={(event) => setForm((current) => ({ ...current, effective_from: event.target.value }))}
              required
            />
          </div>

          {subjectAvailabilityError ? (
            <p role="alert" className="text-sm text-error">
              {subjectAvailabilityError}
            </p>
          ) : assignmentLevelId &&
            currentTerm &&
            !subjectAvailabilityLoading &&
            curriculumSubjects.length === 0 ? (
            <p className="text-sm text-text-muted">
              Every eligible subject in this level already has teacher coverage.
            </p>
          ) : null}

          <div className="rounded-xl border border-border/70 bg-surface-muted/20 p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <p className="text-sm font-semibold text-text">Eligible classes</p>
                <p className="text-xs text-text-muted">Already-covered classes remain unavailable.</p>
              </div>
              <Button
                type="button"
                size="small"
                variant="outline"
                disabled={!eligibleClasses.some((item) => !item.already_assigned)}
                onClick={() =>
                  setSelectedClassIds(
                    eligibleClasses.filter((item) => !item.already_assigned).map((item) => item.class_id),
                  )
                }
              >
                Select all eligible
              </Button>
            </div>
            <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {eligibleClasses.map((item) => (
                <label key={item.class_id} className="flex items-center gap-2 rounded-lg border border-border/70 bg-surface px-3 py-2 text-sm text-text-soft">
                  <input
                    type="checkbox"
                    checked={selectedClassIds.includes(item.class_id)}
                    disabled={item.already_assigned}
                    onChange={(event) =>
                      setSelectedClassIds((current) =>
                        event.target.checked
                          ? [...current, item.class_id]
                          : current.filter((id) => id !== item.class_id),
                      )
                    }
                  />
                  <span>
                    {item.display_name || item.class_name || "Class"}
                    {item.department_name ? ` · ${item.department_name}` : ""}
                    {item.already_assigned ? " · already assigned" : ""}
                  </span>
                </label>
              ))}
              {form.curriculum_subject_id && eligibleClasses.length === 0 ? (
                <p className="text-sm text-text-muted">No eligible classes for this subject and level.</p>
              ) : null}
            </div>
          </div>

          <FormActions
            submitting={saving === "create"}
            submitLabel="Assign teacher"
            repeatLabel={`Assign teacher (${selectedClassIds.length})`}
            closeLabel="Assign & close"
            repeatable
            disabled={!currentTerm || !selectedClassIds.length}
          />
        </fieldset>
      </form>
    </WorkspacePanel>
  );

  if (error && !loading) {
    return (
      <WorkspacePanel title="Teacher assignments unavailable">
        <p className="text-sm text-error">{error}</p>
        <Button type="button" className="mt-4" onClick={loadBase}>Retry</Button>
      </WorkspacePanel>
    );
  }

  if (activeTab === "assign") return editor;

  return (
    <>
      <div className="mb-4 grid gap-3 rounded-xl border border-border/70 bg-surface px-4 py-4 sm:grid-cols-3">
        <SelectControl
          label="Class"
          value={filters.class_id}
          onChange={(value) => updateFilters({ class_id: value })}
          options={classOptions}
          placeholder="All classes"
          clearable
        />
        <SelectControl
          label="Teacher"
          value={filters.teacher_membership_id}
          onChange={(value) => updateFilters({ teacher_membership_id: value })}
          options={teacherOptions}
          placeholder="All teachers"
          clearable
        />
        <SelectControl
          label="Lifecycle"
          value={filters.status}
          onChange={(value) => updateFilters({ status: value })}
          options={[
            { value: "scheduled", label: "Scheduled" },
            { value: "current", label: "Current" },
            { value: "ended", label: "Ended" },
          ]}
          placeholder="All lifecycle states"
          clearable
        />
      </div>

      <RecordList
        title={`Teacher assignments${loading || assignmentLoading ? "" : ` (${assignmentTotal})`}`}
        description="One list for current, scheduled and historical teaching coverage. Reassign and end actions preserve assignment history."
        actions={
          <Button type="button" onClick={() => selectView("assign")}>
            <UserPlus className="h-4 w-4" /> Assign teacher
          </Button>
        }
        items={visibleAssignments}
        searchValue={assignmentSearch}
        onSearchChange={(value) => { setAssignmentPage(0); setAssignmentSearch(value); }}
        loading={loading || assignmentLoading}
        emptyIcon={Users}
        emptyTitle="No teacher assignments"
        emptyDescription="Create an assignment or adjust the class, teacher or lifecycle filters."
        recordLabel="Subject assignment"
        detailsLabel="Coverage"
        renderTitle={(item) => item.subject_name || item.subject_code || "Subject"}
        renderMeta={(item) => item.subject_code || assignmentClassLabel(item)}
        renderDescription={(item) =>
          `${assignmentClassLabel(item)} · ${item.teacher_name || item.teacher_staff_id || "Teacher"} · ${formatPeriod(item)}`
        }
        renderStatus={(item) => String(item.status || "ended").toLowerCase()}
        renderActions={rowActions}
        renderInspector={(item) => (
          <AssignmentInspector item={item} actions={rowActions(item)} />
        )}
      />

      <div className="mt-4 flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-text-muted">
          Showing {assignments.length} of {assignmentTotal} assignments
        </p>
        <div className="flex gap-2">
          <Button type="button" size="small" variant="outline" disabled={assignmentPage === 0 || loading || assignmentLoading} onClick={() => setAssignmentPage((value) => Math.max(0, value - 1))}>
            Previous
          </Button>
          <Button type="button" size="small" variant="outline" disabled={(assignmentPage + 1) * PAGE_SIZE >= assignmentTotal || loading || assignmentLoading} onClick={() => setAssignmentPage((value) => value + 1)}>
            Next
          </Button>
        </div>
      </div>

      <Modal
        open={Boolean(reassigning)}
        title="Reassign teacher"
        description="Replace the current teacher from an effective date while retaining the existing assignment as history."
        onClose={saving ? undefined : () => setReassigning(null)}
        footer={
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" disabled={Boolean(saving)} onClick={() => setReassigning(null)}>Cancel</Button>
            <Button type="submit" form="teacher-reassign-form" disabled={Boolean(saving) || !form.teacher_membership_id || reason.trim().length < 3}>
              {saving ? "Saving..." : "Confirm reassign"}
            </Button>
          </div>
        }
      >
        <form id="teacher-reassign-form" className="space-y-3" onSubmit={submitReassign}>
          <SelectControl label="Replacement teacher" value={form.teacher_membership_id} onChange={(value) => setForm((current) => ({ ...current, teacher_membership_id: value }))} options={replacementTeacherOptions} required />
          <Input label="Effective from" type="date" value={form.effective_from} onChange={(event) => setForm((current) => ({ ...current, effective_from: event.target.value }))} required />
          {isMarkedToEnd(reassigning) ? (
            <p className="text-sm text-text-muted">
              This assignment is marked to end on {reassigning.effective_to}. The takeover defaults to the next day; choosing an earlier date will shorten the current teacher's assignment.
            </p>
          ) : null}
          {form.effective_from === reassigning?.effective_from ? (
            <p className="text-sm text-text-muted">
              This date is the same as when the current teacher started. Weave will treat this as a correction if no academic records already depend on the assignment.
            </p>
          ) : null}
          <Input label="Audit reason" value={reason} onChange={(event) => setReason(event.target.value)} minLength={3} maxLength={500} required />
        </form>
      </Modal>

      <Modal
        open={Boolean(ending)}
        title="End assignment"
        description="Close this teaching assignment at an explicit date. Historical evidence remains available."
        onClose={saving ? undefined : () => setEnding(null)}
        footer={
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" disabled={Boolean(saving)} onClick={() => setEnding(null)}>Cancel</Button>
            <Button type="submit" form="teacher-end-form" variant="danger" disabled={Boolean(saving) || reason.trim().length < 3}>
              {saving ? "Ending..." : "Confirm end"}
            </Button>
          </div>
        }
      >
        <form id="teacher-end-form" className="space-y-3" onSubmit={submitEnd}>
          {ending?.has_scheduled_takeover &&
          effectiveTo &&
          ending.effective_to &&
          effectiveTo < ending.effective_to ? (
            <p role="alert" className="rounded-lg border border-warning/40 bg-warning/10 p-3 text-sm text-text">
              Ending this assignment early will also cancel the planned takeover by {ending.scheduled_takeover_teacher_name || "the incoming teacher"}. This subject/class will have no assigned teacher until you create a new assignment.
            </p>
          ) : null}
          <Input label="Last teaching date" type="date" value={effectiveTo} onChange={(event) => setEffectiveTo(event.target.value)} required />
          <p className="text-sm text-text-muted">
            The teacher remains assigned through this date.
            {effectiveTo === today()
              ? " Ends today. This assignment remains current through today and will appear under Ended from tomorrow."
              : ""}
          </p>
          <Input label="Audit reason" value={reason} onChange={(event) => setReason(event.target.value)} minLength={3} maxLength={500} required />
        </form>
      </Modal>

      <Modal
        open={Boolean(scheduleEditing)}
        title={scheduleEditing?.is_takeover ? "Manage handover" : "Edit schedule"}
        description="Change the planned teacher or start date. Moving a handover also updates the current teacher's planned end date."
        onClose={saving ? undefined : () => setScheduleEditing(null)}
        footer={
          <div className="flex flex-wrap justify-end gap-2">
            {scheduleEditing?.is_takeover ? (
              <Button
                type="button"
                variant="danger"
                disabled={Boolean(saving)}
                onClick={() => {
                  setPendingCancel(scheduleEditing);
                  setScheduleEditing(null);
                }}
              >
                Cancel handover
              </Button>
            ) : null}
            <Button type="button" variant="outline" disabled={Boolean(saving)} onClick={() => setScheduleEditing(null)}>Cancel</Button>
            <Button type="submit" form="teacher-schedule-form" disabled={Boolean(saving) || !scheduleForm.teacher_membership_id || reason.trim().length < 3}>
              {saving ? "Saving..." : "Save schedule"}
            </Button>
          </div>
        }
      >
        <form id="teacher-schedule-form" className="space-y-3" onSubmit={submitScheduleEdit}>
          <SelectControl label="Planned teacher" value={scheduleForm.teacher_membership_id} onChange={(value) => setScheduleForm((current) => ({ ...current, teacher_membership_id: value }))} options={teacherOptions} required />
          <Input label="Effective from" type="date" value={scheduleForm.effective_from} onChange={(event) => setScheduleForm((current) => ({ ...current, effective_from: event.target.value }))} required />
          <Input label="Audit reason" value={reason} onChange={(event) => setReason(event.target.value)} minLength={3} maxLength={500} required />
        </form>
      </Modal>

      <Modal
        open={Boolean(pendingCancel)}
        title="Cancel scheduled assignment"
        description="Cancel this never-effective plan. If it is a handover, the current teacher will be restored to an open-ended assignment."
        onClose={saving ? undefined : () => setPendingCancel(null)}
        footer={
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" disabled={Boolean(saving)} onClick={() => setPendingCancel(null)}>Keep schedule</Button>
            <Button type="button" variant="danger" disabled={Boolean(saving) || reason.trim().length < 3} onClick={cancelSchedule}>
              {saving ? "Cancelling..." : "Cancel schedule"}
            </Button>
          </div>
        }
      >
        <Input label="Audit reason" value={reason} onChange={(event) => setReason(event.target.value)} minLength={3} maxLength={500} required />
      </Modal>
    </>
  );
}

function AssignmentInspector({ item, actions }) {
  return (
    <div className="overflow-hidden rounded-xl border border-border/70 bg-surface">
      <div className="border-b border-border/70 p-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="font-semibold text-text">{item.subject_name || "Subject"}</p>
            <p className="mt-1 text-xs text-text-muted">{assignmentClassLabel(item)}</p>
          </div>
          <div className="flex flex-wrap justify-end gap-2">
            <Badge variant={String(item.status).toLowerCase() === "current" ? "success" : String(item.status).toLowerCase() === "scheduled" ? "warning" : "default"}>
              {String(item.status || "ended").toLowerCase()}
            </Badge>
            {item.has_scheduled_takeover ? (
              <Badge variant="warning">handover scheduled</Badge>
            ) : null}
            {isMarkedToEnd(item) ? <Badge variant="warning">marked to end</Badge> : null}
          </div>
        </div>
      </div>
      <div className="space-y-3 p-4 text-sm">
        <div><p className="text-xs font-semibold uppercase text-text-faint">Teacher</p><p className="mt-1 text-text">{item.teacher_name || item.teacher_staff_id || "Teacher"}</p></div>
        <div><p className="text-xs font-semibold uppercase text-text-faint">Effective period</p><p className="mt-1 text-text">{formatPeriod(item)}</p></div>
        {item.has_scheduled_takeover ? (
          <div><p className="text-xs font-semibold uppercase text-text-faint">Handover scheduled</p><p className="mt-1 text-text">{item.scheduled_takeover_teacher_name || "Incoming teacher"} · {item.scheduled_takeover_effective_from}</p></div>
        ) : null}
        <div><p className="text-xs font-semibold uppercase text-text-faint">Lifecycle actions</p><div className="mt-2 flex flex-wrap gap-2">{actions || <span className="text-text-muted">No action available</span>}</div></div>
      </div>
    </div>
  );
}

export default TeacherAssignmentsWorkspace;
