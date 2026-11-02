import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Archive,
  Ban,
  BookOpen,
  ChevronLeft,
  ChevronRight,
  GraduationCap,
  KeyRound,
  MoreHorizontal,
  Plus,
  RotateCcw,
  School,
  ShieldOff,
  SlidersHorizontal,
  Trash2,
  Undo2,
  UserCheck,
  UserMinus,
  Users,
} from "lucide-react";

import EmptyState from "../../components/shared/EmptyState";
import LoadingState from "../../components/shared/LoadingState";
import {
  DirectorySummary,
  DirectoryTable,
  MobileDirectoryList,
  MobilePersonCard,
  PersonIdentity,
} from "../../components/people/PeopleDirectory";
import StudentAccessCodeSlipModal from "../../components/students/StudentAccessCodeSlipModal";
import Badge from "../../components/ui/Badge";
import Button from "../../components/ui/Button";
import Card from "../../components/ui/Card";
import Dropdown from "../../components/ui/Dropdown";
import Input from "../../components/ui/Input";
import Modal from "../../components/ui/Modal";
import SearchableSelect from "../../components/ui/SearchableSelect";
import { useToast } from "../../hooks/useToast";
import academicService from "../../services/academicService";
import {
  academicLevelService,
  classService,
} from "../../services/academicsService";
import { parseApiError } from "../../services/api";
import { studentService } from "../../services/studentService";
import { displayName, getAvatarSrcFromRecord } from "../../utils/user";

const PAGE_SIZE = 24;
const STUDENT_STATUSES = [
  "active",
  "suspended",
  "withdrawn",
  "graduated",
  "expelled",
];
const GENDER_OPTIONS = ["male", "female"];
const EMPTY_FILTERS = {
  search: "",
  classId: "",
  academicLevelId: "",
  unassignedClass: false,
  status: "active",
  includeArchived: false,
};

const localDateInputValue = (date = new Date()) => {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
};

const tomorrowDateInputValue = () => {
  const tomorrow = new Date();
  tomorrow.setDate(tomorrow.getDate() + 1);
  return localDateInputValue(tomorrow);
};

const titleCase = (value) =>
  String(value || "")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());

const formatDate = (value) => {
  if (!value) return "Not set";
  const date = new Date(`${String(value).slice(0, 10)}T12:00:00`);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleDateString();
};

const classLabel = (item) =>
  item?.display_name ||
  [item?.academic_level_name, item?.arm_label || item?.arm]
    .filter(Boolean)
    .join(" ") ||
  item?.id ||
  "Class";

const studentClassLabel = (student) =>
  [student?.class_name, student?.class_arm].filter(Boolean).join(" ") ||
  "Unassigned";

const upcomingPlacementLabel = (enrollment) =>
  [enrollment?.academic_level_name, enrollment?.class_arm]
    .filter(Boolean)
    .join(" ") ||
  enrollment?.class_name ||
  "Scheduled placement";

const asItems = (response) =>
  Array.isArray(response)
    ? response
    : Array.isArray(response?.items)
      ? response.items
      : [];

const lifecycleConfig = {
  suspend: {
    label: "Suspend",
    icon: Ban,
    method: "suspendStudent",
    usesPromotionHold: true,
  },
  reinstate: {
    label: "Reinstate",
    icon: UserCheck,
    method: "reinstateStudent",
  },
  reinstateExpelled: {
    label: "Reinstate expelled",
    icon: UserCheck,
    method: "reinstateExpelledStudent",
    usesPlacement: true,
    usesEffectiveDate: true,
    returnFlow: true,
  },
  readmit: {
    label: "Readmit student",
    icon: UserCheck,
    method: "readmitStudent",
    usesPlacement: true,
    usesEffectiveDate: true,
    returnFlow: true,
  },
  reenrolGraduate: {
    label: "Re-enrol former student",
    icon: UserCheck,
    method: "reenrolGraduatedStudent",
    usesPlacement: true,
    usesEffectiveDate: true,
    returnFlow: true,
  },
  undoWithdrawal: {
    label: "Undo withdrawal",
    icon: Undo2,
    method: "undoWithdrawal",
  },
  undoExpulsion: {
    label: "Undo expulsion",
    icon: Undo2,
    method: "undoExpulsion",
  },
  undoGraduation: {
    label: "Undo graduation",
    icon: Undo2,
    method: "undoGraduation",
  },
  withdraw: {
    label: "Withdraw",
    icon: UserMinus,
    method: "withdrawStudent",
    immediate: true,
  },
  expel: {
    label: "Expel",
    icon: ShieldOff,
    method: "expelStudent",
    immediate: true,
  },
  graduate: {
    label: "Graduate",
    icon: GraduationCap,
    method: "graduateStudent",
    immediate: true,
  },
  archive: {
    label: "Archive",
    icon: Archive,
    method: "archiveStudent",
  },
  restore: {
    label: "Restore",
    icon: Undo2,
    method: "restoreStudent",
  },
};

const actionsForStudent = (student) => {
  if (student.is_archived) return ["restore"];
  const status = String(student.status || "").toLowerCase();
  if (status === "active") {
    return ["suspend", "withdraw", "expel", "graduate"];
  }
  if (status === "suspended") {
    return ["reinstate", "withdraw", "expel"];
  }

  const capabilities = student.lifecycle_capabilities || {};
  const actions = [];
  if (status === "withdrawn") {
    if (capabilities.can_undo_withdrawal) actions.push("undoWithdrawal");
    else if (capabilities.can_readmit) actions.push("readmit");
  } else if (status === "expelled") {
    if (capabilities.can_undo_expulsion) actions.push("undoExpulsion");
    else if (capabilities.can_reinstate_expelled) actions.push("reinstateExpelled");
  } else if (status === "graduated") {
    if (capabilities.can_undo_graduation) actions.push("undoGraduation");
    else if (capabilities.can_reenrol_graduate) actions.push("reenrolGraduate");
  }

  if (!student.current_enrollment_id && !student.upcoming_enrollment) actions.push("archive");
  return actions;
};

function SelectField({
  label,
  value,
  onChange,
  options,
  placeholder,
  error,
  required,
  disabled,
}) {
  return (
    <SearchableSelect
      label={label}
      value={value || ""}
      options={options}
      placeholder={placeholder || "Select"}
      searchPlaceholder={`Search ${String(label || "options").toLowerCase()}`}
      clearable={!required}
      required={required}
      disabled={disabled}
      error={error}
      onChange={onChange}
    />
  );
}

function StudentFilterFields({ filters, setFilters, levelOptions, classOptions }) {
  return (
    <>
      <SelectField
        label="Academic level"
        value={filters.academicLevelId}
        onChange={(value) =>
          setFilters((current) => ({
            ...current,
            academicLevelId: value,
            classId: "",
          }))
        }
        options={levelOptions}
        placeholder="All levels"
      />
      <SelectField
        label="Class"
        value={filters.classId}
        onChange={(value) =>
          setFilters((current) => ({ ...current, classId: value }))
        }
        options={classOptions}
        placeholder="All classes"
      />
      <SelectField
        label="Status"
        value={filters.status}
        onChange={(value) =>
          setFilters((current) => ({ ...current, status: value }))
        }
        options={STUDENT_STATUSES.map((value) => ({
          value,
          label: titleCase(value),
        }))}
        placeholder="All statuses"
      />
      <label className="flex min-h-11 items-center gap-2 self-end rounded-xl border border-border px-3 text-xs font-semibold text-text-soft sm:text-sm">
        <input
          type="checkbox"
          checked={filters.includeArchived}
          onChange={(event) =>
            setFilters((current) => ({
              ...current,
              includeArchived: event.target.checked,
            }))
          }
        />
        Include archived
      </label>
      <label className="flex min-h-11 items-center gap-2 self-end rounded-xl border border-border px-3 text-xs font-semibold text-text-soft sm:text-sm">
        <input
          type="checkbox"
          checked={filters.unassignedClass}
          onChange={(event) =>
            setFilters((current) => ({
              ...current,
              unassignedClass: event.target.checked,
              classId: "",
            }))
          }
        />
        Unassigned only
      </label>
    </>
  );
}

function buildAccessNotice(result) {
  if (!result?.access_code) return null;
  return {
    title: "Student access code",
    description:
      "Give this one-time code to the student so they can set a new password.",
    fields: [
      { label: "Student", value: result.full_name || "Student" },
      { label: "Admission number", value: result.admission_number },
      { label: "Access code", value: result.access_code },
      { label: "Expires", value: formatDate(result.expires_at) },
    ],
  };
}

function StudentActions({
  student,
  busy,
  onEdit,
  onReset,
  onPlacementHistory,
  onReassignClass,
  onReassignLevel,
  onManageUpcoming,
  onLifecycle,
  onHardDelete,
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const actions = actionsForStudent(student);
  const placementDisabled =
    student.is_archived ||
    !["active", "suspended"].includes(String(student.status || "").toLowerCase());
  const hasManagedUpcomingPlacement = Boolean(student.upcoming_enrollment) && !placementDisabled;

  const choose = (handler) => {
    setMenuOpen(false);
    handler(student);
  };

  return (
    <div className="flex items-center justify-end gap-2">
      <Button
        type="button"
        size="small"
        variant="outline"
        onClick={() => onEdit(student)}
        disabled={busy}
      >
        Edit
      </Button>
      <Dropdown
        open={menuOpen}
        onOpenChange={setMenuOpen}
        align="right"
        strategy="fixed"
        className="w-64"
        trigger={
          <Button
            type="button"
            size="icon"
            variant="outline"
            disabled={busy}
            className="h-9 w-9 min-h-9 rounded-lg"
            aria-label={`More actions for ${displayName(student)}`}
          >
            <MoreHorizontal className="h-4 w-4" />
          </Button>
        }
      >
        <div className="grid gap-1">
          <button
            type="button"
            className="flex min-h-10 items-center gap-2 rounded-xl px-3 py-2 text-left text-sm font-semibold text-text-soft transition hover:bg-surface-muted"
            onClick={() => choose(onPlacementHistory)}
          >
            <BookOpen className="h-4 w-4" /> Placement History
          </button>
          {hasManagedUpcomingPlacement ? (
            <button
              type="button"
              className="flex min-h-10 items-center gap-2 rounded-xl px-3 py-2 text-left text-sm font-semibold text-text-soft transition hover:bg-surface-muted"
              onClick={() => choose(onManageUpcoming)}
            >
              <School className="h-4 w-4" /> Manage Scheduled Placement
            </button>
          ) : (
            <>
              <button
                type="button"
                disabled={placementDisabled || Boolean(student.upcoming_enrollment) || !student.class_id}
                className="flex min-h-10 items-center gap-2 rounded-xl px-3 py-2 text-left text-sm font-semibold text-text-soft transition hover:bg-surface-muted disabled:opacity-50"
                onClick={() => choose(onReassignClass)}
              >
                <School className="h-4 w-4" /> Reassign Class
              </button>
              <button
                type="button"
                disabled={placementDisabled || Boolean(student.upcoming_enrollment)}
                className="flex min-h-10 items-center gap-2 rounded-xl px-3 py-2 text-left text-sm font-semibold text-text-soft transition hover:bg-surface-muted disabled:opacity-50"
                onClick={() => choose(onReassignLevel)}
              >
                <GraduationCap className="h-4 w-4" /> Reassign Academic Level
              </button>
            </>
          )}
          <div className="my-1 border-t border-border/70" />
          <button
            type="button"
            disabled={student.is_archived}
            className="flex min-h-10 items-center gap-2 rounded-xl px-3 py-2 text-left text-sm font-semibold text-text-soft transition hover:bg-surface-muted disabled:opacity-50"
            onClick={() => choose(onReset)}
          >
            <RotateCcw className="h-4 w-4" /> Reset access code
          </button>
          <div className="my-1 border-t border-border/70" />
          {actions.map((key) => {
            const item = lifecycleConfig[key];
            const Icon = item.icon;
            return (
              <button
                key={key}
                type="button"
                className={`flex min-h-10 items-center gap-2 rounded-xl px-3 py-2 text-left text-sm font-semibold transition hover:bg-surface-muted ${["archive", "expel"].includes(key) ? "text-error" : "text-text-soft"}`}
                onClick={() => {
                  setMenuOpen(false);
                  onLifecycle(student, key);
                }}
              >
                <Icon className="h-4 w-4" /> {item.label}
              </button>
            );
          })}
          <button
            type="button"
            className="flex min-h-10 items-center gap-2 rounded-xl px-3 py-2 text-left text-sm font-semibold text-error transition hover:bg-error-soft"
            onClick={() => choose(onHardDelete)}
          >
            <Trash2 className="h-4 w-4" /> Hard-delete check
          </button>
        </div>
      </Dropdown>
    </div>
  );
}

function StudentCard({ student, expanded, onExpandedChange, ...actions }) {
  const tone = student.is_archived
    ? "error"
    : student.status === "active"
      ? "success"
      : "warning";
  return (
    <MobilePersonCard tone={tone} expanded={expanded} onExpandedChange={onExpandedChange}>
      <div
        role="button"
        tabIndex={0}
        aria-label={`${expanded ? "Hide" : "Show"} details for ${displayName(student)}`}
        aria-expanded={expanded}
        className="flex cursor-pointer items-start justify-between gap-3 rounded-lg focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary"
        onClick={() => onExpandedChange?.(!expanded)}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            onExpandedChange?.(!expanded);
          }
        }}
      >
        <PersonIdentity
          name={displayName(student)}
          meta={`${student.admission_number || "No admission number"} · ${studentClassLabel(student)}`}
          avatarSrc={getAvatarSrcFromRecord(student)}
        />
        <div className="flex flex-col items-end gap-2">
          <Badge variant={student.status === "active" ? "success" : "default"}>
            {titleCase(student.status)}
          </Badge>
          {student.is_archived ? <Badge variant="error">Archived</Badge> : null}
        </div>
      </div>
      <div className="mt-4 grid grid-cols-2 gap-3 rounded-xl bg-surface-muted/35 px-3 py-3 text-sm">
        <div>
          <p className="text-xs font-semibold uppercase text-text-muted">Class</p>
          <p className="mt-1 text-text-soft">{studentClassLabel(student)}</p>
        </div>
        <div>
          <p className="text-xs font-semibold uppercase text-text-muted">Admission</p>
          <p className="mt-1 text-text-soft">{formatDate(student.admission_date)}</p>
        </div>
        <div>
          <p className="text-xs font-semibold uppercase text-text-muted">Profile</p>
          <p className="mt-1 text-text-soft">{titleCase(student.profile_status)}</p>
        </div>
        <div>
          <p className="text-xs font-semibold uppercase text-text-muted">Credentials</p>
          <p className="mt-1 text-text-soft">
            {student.password_reset_required ? "Setup required" : "Configured"}
          </p>
        </div>
      </div>
      {student.upcoming_enrollment ? (
        <div className="mt-3 rounded-xl border border-warning/30 bg-warning-soft/35 px-3 py-3 text-sm">
          <p className="text-xs font-semibold uppercase text-warning">Upcoming enrollment</p>
          <p className="mt-1 font-medium text-text">
            {upcomingPlacementLabel(student.upcoming_enrollment)}
          </p>
          <p className="mt-1 text-xs text-text-muted">
            Starts {formatDate(student.upcoming_enrollment.started_on)}
          </p>
        </div>
      ) : null}
      <div className="mt-4 flex justify-end border-t border-border/70 pt-3">
        <StudentActions student={student} {...actions} />
      </div>
    </MobilePersonCard>
  );
}

function ImpactPreview({ preview }) {
  if (!preview) return null;
  const subjectNames = (items) =>
    items?.length ? items.map((item) => item.subject_name).join(", ") : "None";
  return (
    <div className="space-y-3 rounded-xl border border-warning/30 bg-warning-soft/40 p-4 text-sm">
      <p className="font-semibold text-text">Placement impact preview</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <p className="text-xs font-semibold uppercase text-text-muted">Department / specialization</p>
          <p className="mt-1 text-text-soft">
            {preview.current_department || "None"} → {preview.destination_department || "None"}
          </p>
        </div>
        <div>
          <p className="text-xs font-semibold uppercase text-text-muted">Ranking context</p>
          <p className="mt-1 text-text-soft">
            {preview.ranking_context_affected ? "Affected; replacement reporting may be required" : "Unchanged"}
          </p>
        </div>
      </div>
      <div>
        <p className="text-xs font-semibold uppercase text-text-muted">Remain applicable</p>
        <p className="mt-1 text-text-soft">{subjectNames(preview.subjects_remaining_applicable)}</p>
      </div>
      <div>
        <p className="text-xs font-semibold uppercase text-text-muted">Become historical-only in destination</p>
        <p className="mt-1 text-text-soft">{subjectNames(preview.subjects_becoming_historical_only)}</p>
      </div>
      <div>
        <p className="text-xs font-semibold uppercase text-text-muted">Destination subjects without scores</p>
        <p className="mt-1 text-text-soft">{subjectNames(preview.destination_subjects_without_scores)}</p>
      </div>
      <div className="flex flex-wrap gap-2">
        {preview.teacher_comment_requires_review ? <Badge variant="warning">Teacher comment needs review</Badge> : null}
        {preview.report_card_affected ? <Badge variant="warning">Report card affected</Badge> : null}
      </div>
      {preview.warnings?.length ? (
        <ul className="list-disc space-y-1 pl-5 text-text-soft">
          {preview.warnings.map((warning) => <li key={warning}>{warning}</li>)}
        </ul>
      ) : null}
      <p className="text-xs text-text-muted">
        These warnings are informational. Existing results, attendance, CBT attempts and published report evidence are preserved and do not block reassignment.
      </p>
    </div>
  );
}

function StudentDirectoryPage() {
  const navigate = useNavigate();
  const { showSuccess, showError, showWarning } = useToast();
  const [students, setStudents] = useState([]);
  const [classes, setClasses] = useState([]);
  const [levels, setLevels] = useState([]);
  const [sessions, setSessions] = useState([]);
  const [terms, setTerms] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [draftFilters, setDraftFilters] = useState(EMPTY_FILTERS);
  const [appliedFilters, setAppliedFilters] = useState(EMPTY_FILTERS);
  const [mobileFiltersOpen, setMobileFiltersOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState("");
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState({});
  const [accessNotice, setAccessNotice] = useState(null);
  const [editState, setEditState] = useState(null);
  const [lifecycleState, setLifecycleState] = useState(null);
  const [placementState, setPlacementState] = useState(null);
  const [hardDeleteState, setHardDeleteState] = useState(null);
  const [accessCodeConfirmation, setAccessCodeConfirmation] = useState(null);

  const levelOptions = useMemo(
    () => levels.map((item) => ({ value: item.id, label: item.name })),
    [levels],
  );
  const classOptions = useMemo(
    () => classes.map((item) => ({ value: item.id, label: classLabel(item) })),
    [classes],
  );
  const sessionOptions = useMemo(
    () => sessions.map((item) => ({ value: item.id, label: item.name || item.id })),
    [sessions],
  );
  const currentSession = sessions.find((item) => item.is_current) || sessions[0] || null;
  const currentTerm =
    terms.find(
      (item) =>
        item.is_current &&
        (!currentSession || item.academic_session_id === currentSession.id),
    ) || terms.find((item) => !currentSession || item.academic_session_id === currentSession.id) || null;
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const loadReferenceData = useCallback(async () => {
    const [levelResult, classResult, sessionResult, termResult] = await Promise.all([
      academicLevelService.getLevels({ activeOnly: true }),
      classService.getClasses({ limit: 100 }),
      academicService.listSessions({ limit: 100 }),
      academicService.listTerms({ limit: 100 }),
    ]);
    setLevels(asItems(levelResult));
    setClasses(asItems(classResult));
    setSessions(asItems(sessionResult));
    setTerms(asItems(termResult));
  }, []);

  const loadStudents = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const response = await studentService.getAdminStudents({
        skip: (page - 1) * PAGE_SIZE,
        limit: PAGE_SIZE,
        search: appliedFilters.search.trim() || undefined,
        classId: appliedFilters.classId || undefined,
        academicLevelId: appliedFilters.academicLevelId || undefined,
        unassignedClass: appliedFilters.unassignedClass,
        status: appliedFilters.status || undefined,
        includeArchived: appliedFilters.includeArchived,
      });
      setStudents(asItems(response));
      setTotal(Number(response?.total || 0));
    } catch (requestError) {
      setError(parseApiError(requestError, "Failed to load students.").message);
    } finally {
      setLoading(false);
    }
  }, [appliedFilters, page]);

  useEffect(() => {
    loadReferenceData().catch((requestError) => {
      setError(parseApiError(requestError, "Failed to load academic references.").message);
    });
  }, [loadReferenceData]);

  useEffect(() => {
    loadStudents();
  }, [loadStudents]);

  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      setPage(1);
      setAppliedFilters({ ...draftFilters });
    }, draftFilters.search.trim() ? 250 : 0);
    return () => window.clearTimeout(timeoutId);
  }, [draftFilters]);

  const refresh = () => loadStudents();

  const openEdit = (student) => {
    setFieldErrors({});
    setEditState({
      student,
      form: {
        first_name: student.first_name || "",
        last_name: student.last_name || "",
        gender: student.gender || "",
        date_of_birth: student.date_of_birth || "",
        state_of_origin: student.state_of_origin || "",
      },
    });
  };

  const submitEdit = async (event) => {
    event.preventDefault();
    if (!editState) return;
    setBusyId(editState.student.id);
    setFieldErrors({});
    const payload = Object.fromEntries(
      Object.entries(editState.form).map(([key, value]) => [key, value === "" ? null : value]),
    );
    try {
      await studentService.updateAdminStudent(editState.student.id, payload);
      showSuccess("Student profile updated.");
      setEditState(null);
      await refresh();
    } catch (requestError) {
      const parsed = parseApiError(requestError, "Failed to update student.");
      setFieldErrors(parsed.fieldErrors || {});
      showError(parsed.message);
    } finally {
      setBusyId("");
    }
  };

  const openLifecycle = (student, actionKey) => {
    const config = lifecycleConfig[actionKey];
    setFieldErrors({});
    setLifecycleState({
      student,
      actionKey,
      form: {
        reason: "",
        effective_date: config.returnFlow ? tomorrowDateInputValue() : localDateInputValue(),
        promotion_hold: true,
        target_class_id: student.class_id || classes[0]?.id || "",
        target_academic_level_id: student.academic_level_id || "",
        academic_session_id: currentSession?.id || "",
      },
    });
  };

  const submitLifecycle = async (event) => {
    event.preventDefault();
    if (!lifecycleState) return;
    const { student, actionKey, form } = lifecycleState;
    const config = lifecycleConfig[actionKey];
    const reason = form.reason.trim();
    if (reason.length < 3) {
      setFieldErrors({ reason: "Enter a reason with at least three characters." });
      return;
    }
    const payload = { reason };
    if (config.usesPromotionHold) payload.promotion_hold = form.promotion_hold;
    if (config.usesEffectiveDate) payload.effective_date = form.effective_date;
    if (config.usesPlacement) {
      payload.target_academic_level_id = form.target_academic_level_id;
      payload.target_class_id = form.target_class_id;
      payload.academic_session_id = form.academic_session_id;
      if (!payload.target_academic_level_id || !payload.target_class_id || !payload.academic_session_id) {
        setFieldErrors({
          target_academic_level_id: payload.target_academic_level_id ? undefined : "Choose a level.",
          target_class_id: payload.target_class_id ? undefined : "Choose a class.",
          academic_session_id: payload.academic_session_id ? undefined : "Choose a session.",
        });
        return;
      }
    }
    setBusyId(student.id);
    try {
      const response = await studentService[config.method](student.id, payload);
      const updatedStudent = response?.student || response;
      if (config.returnFlow && updatedStudent?.upcoming_enrollment) {
        showSuccess(
          `Return enrollment scheduled for ${formatDate(updatedStudent.upcoming_enrollment.started_on)}. Access remains unchanged until then.`,
        );
      } else {
        showSuccess(`${config.label} completed.`);
      }
      setLifecycleState(null);
      if (
        ["restore", "reinstate", "reinstateExpelled", "readmit", "reenrolGraduate"].includes(actionKey) &&
        !updatedStudent?.upcoming_enrollment &&
        updatedStudent?.password_reset_required
      ) {
        showWarning("Student access is restored, but a new access code is still required.");
      }
      await refresh();
    } catch (requestError) {
      const parsed = parseApiError(
        requestError,
        `Failed to ${config.label.toLowerCase()} student.`,
      );
      setFieldErrors(parsed.fieldErrors || {});
      showError(parsed.message);
    } finally {
      setBusyId("");
    }
  };

  const resetAccessCode = async (student) => {
    setBusyId(student.id);
    try {
      const result = await studentService.resetStudentAccessCode(student.id);
      setAccessNotice(buildAccessNotice(result));
      setAccessCodeConfirmation(null);
      showSuccess("New student access code generated.");
      await refresh();
    } catch (requestError) {
      showError(parseApiError(requestError, "Failed to generate access code.").message);
    } finally {
      setBusyId("");
    }
  };

  const openPlacementHistory = async (student) => {
    setPlacementState({ type: "history", student, loading: true, items: [] });
    try {
      const response = await studentService.getPlacementHistory(student.id);
      setPlacementState({
        type: "history",
        student,
        loading: false,
        items: asItems(response),
      });
    } catch (requestError) {
      showError(parseApiError(requestError, "Failed to load placement history.").message);
      setPlacementState(null);
    }
  };

  const openUpcomingManager = (student) => {
    if (!student.upcoming_enrollment) {
      showWarning("This student no longer has a scheduled placement to manage.");
      return;
    }
    setFieldErrors({});
    setPlacementState({
      type: "upcomingManage",
      student,
      enrollment: student.upcoming_enrollment,
    });
  };

  const openUpcomingEdit = (student, enrollment) => {
    setFieldErrors({});
    setPlacementState({
      type: "upcomingEdit",
      student,
      enrollment,
      form: {
        target_academic_level_id: enrollment.academic_level_id || "",
        target_class_id: enrollment.class_id || "",
        academic_session_id: enrollment.academic_session_id || currentSession?.id || "",
        effective_date: enrollment.started_on || tomorrowDateInputValue(),
        reason: "",
      },
    });
  };

  const submitUpcomingEdit = async (event) => {
    event.preventDefault();
    if (!placementState?.form || !placementState?.enrollment) return;
    const { student, enrollment, form } = placementState;
    if (form.reason.trim().length < 3) {
      setFieldErrors({ reason: "Enter a reason with at least three characters." });
      return;
    }
    setBusyId(student.id);
    try {
      await studentService.updateUpcomingEnrollment(student.id, enrollment.id, {
        target_academic_level_id: form.target_academic_level_id,
        target_class_id: form.target_class_id,
        academic_session_id: form.academic_session_id,
        effective_date: form.effective_date,
        reason: form.reason.trim(),
      });
      showSuccess("Scheduled placement updated.");
      setPlacementState(null);
      await refresh();
    } catch (requestError) {
      const parsed = parseApiError(requestError, "Failed to update scheduled placement.");
      setFieldErrors(parsed.fieldErrors || {});
      showError(parsed.message);
    } finally {
      setBusyId("");
    }
  };

  const submitUpcomingCancel = async (event) => {
    event.preventDefault();
    const reason = String(placementState?.reason || "").trim();
    if (!placementState?.enrollment || reason.length < 3) return;
    setBusyId(placementState.student.id);
    try {
      await studentService.cancelUpcomingEnrollment(
        placementState.student.id,
        placementState.enrollment.id,
        { reason },
      );
      showSuccess("Scheduled placement cancelled.");
      setPlacementState(null);
      await refresh();
    } catch (requestError) {
      showError(parseApiError(requestError, "Failed to cancel scheduled placement.").message);
    } finally {
      setBusyId("");
    }
  };

  const openReassign = (student, type) => {
    setFieldErrors({});
    setPlacementState({
      type,
      student,
      preview: null,
      previewLoading: false,
      form: {
        target_academic_level_id:
          type === "class" ? student.academic_level_id || "" : "",
        target_class_id: "",
        academic_session_id: currentSession?.id || student.academic_session_id || "",
        academic_term_id: currentTerm?.id || "",
        effective_date: localDateInputValue(),
        reason: "",
      },
    });
  };

  const placementClassOptions = useMemo(() => {
    if (!placementState?.form) return [];
    const targetLevelId = placementState.form.target_academic_level_id;
    return classes
      .filter(
        (item) =>
          (!targetLevelId || item.academic_level_id === targetLevelId) &&
          item.id !== placementState.student?.class_id &&
          item.is_active !== false,
      )
      .map((item) => ({ value: item.id, label: classLabel(item) }));
  }, [classes, placementState]);

  const updatePlacementForm = (field, value) => {
    setPlacementState((current) => ({
      ...current,
      preview: null,
      form: {
        ...current.form,
        [field]: value,
        ...(field === "target_academic_level_id" ? { target_class_id: "" } : {}),
      },
    }));
  };

  const previewPlacement = async () => {
    if (!placementState?.form) return;
    const { student, form } = placementState;
    if (
      !form.target_academic_level_id ||
      !form.target_class_id ||
      !form.academic_session_id ||
      !form.academic_term_id ||
      !form.effective_date
    ) {
      showWarning("Choose the destination, session, term and effective date before previewing impact.");
      return;
    }
    setPlacementState((current) => ({ ...current, previewLoading: true }));
    try {
      const preview = await studentService.previewPlacementImpact(student.id, {
        target_academic_level_id: form.target_academic_level_id,
        target_class_id: form.target_class_id,
        academic_session_id: form.academic_session_id,
        academic_term_id: form.academic_term_id,
        effective_date: form.effective_date,
      });
      setPlacementState((current) => ({ ...current, preview, previewLoading: false }));
    } catch (requestError) {
      showError(parseApiError(requestError, "Failed to preview placement impact.").message);
      setPlacementState((current) => ({ ...current, previewLoading: false }));
    }
  };

  const submitReassignment = async (event) => {
    event.preventDefault();
    if (!placementState?.form || !placementState.preview) {
      showWarning("Review the placement impact preview before confirming reassignment.");
      return;
    }
    const { type, student, form } = placementState;
    if (form.reason.trim().length < 3) {
      setFieldErrors({ reason: "Enter a reason with at least three characters." });
      return;
    }
    setBusyId(student.id);
    try {
      if (type === "class") {
        await studentService.reassignStudentClass(student.id, {
          target_class_id: form.target_class_id,
          academic_session_id: form.academic_session_id,
          effective_date: form.effective_date,
          reason: form.reason.trim(),
        });
        showSuccess("Class reassignment recorded as a new placement segment.");
      } else {
        await studentService.reassignStudentAcademicLevel(student.id, {
          target_academic_level_id: form.target_academic_level_id,
          target_class_id: form.target_class_id,
          academic_session_id: form.academic_session_id,
          effective_date: form.effective_date,
          reason: form.reason.trim(),
        });
        showSuccess("Academic-level reassignment recorded as a new placement segment.");
      }
      setPlacementState(null);
      await refresh();
    } catch (requestError) {
      const parsed = parseApiError(requestError, "Failed to reassign student placement.");
      setFieldErrors(parsed.fieldErrors || {});
      showError(parsed.message);
    } finally {
      setBusyId("");
    }
  };

  const inspectHardDelete = async (student) => {
    setHardDeleteState({ student, loading: true, eligibility: null, reason: "", confirmation: "" });
    try {
      const eligibility = await studentService.getHardDeleteEligibility(student.id);
      setHardDeleteState({ student, loading: false, eligibility, reason: "", confirmation: "" });
    } catch (requestError) {
      showError(parseApiError(requestError, "Failed to inspect delete eligibility.").message);
      setHardDeleteState(null);
    }
  };

  const submitHardDelete = async (event) => {
    event.preventDefault();
    if (!hardDeleteState?.eligibility?.eligible) return;
    if (
      hardDeleteState.confirmation !== "DELETE_UNUSED_STUDENT" ||
      hardDeleteState.reason.trim().length < 3
    ) {
      showWarning("Enter the exact confirmation text and a reason.");
      return;
    }
    setBusyId(hardDeleteState.student.id);
    try {
      await studentService.hardDeleteStudent(hardDeleteState.student.id, {
        confirmation: "DELETE_UNUSED_STUDENT",
        reason: hardDeleteState.reason.trim(),
      });
      showSuccess("Unused student record permanently deleted.");
      setHardDeleteState(null);
      await refresh();
    } catch (requestError) {
      showError(parseApiError(requestError, "Failed to hard-delete student.").message);
    } finally {
      setBusyId("");
    }
  };

  const clearFilters = () => {
    setDraftFilters(EMPTY_FILTERS);
    setAppliedFilters(EMPTY_FILTERS);
    setPage(1);
  };

  if (loading && students.length === 0 && !error) {
    return <LoadingState label="Loading students..." />;
  }

  const placedCount = students.filter((student) => student.class_id).length;
  const activeCount = students.filter(
    (student) => String(student.status).toLowerCase() === "active",
  ).length;
  const credentialsReadyCount = students.filter(
    (student) => !student.password_reset_required,
  ).length;
  const activeFilterCount = [
    draftFilters.academicLevelId,
    draftFilters.classId,
    draftFilters.status !== EMPTY_FILTERS.status,
    draftFilters.includeArchived,
    draftFilters.unassignedClass,
  ].filter(Boolean).length;

  return (
    <div className="space-y-5">
      <StudentAccessCodeSlipModal
        notice={accessNotice}
        onClose={() => setAccessNotice(null)}
        onCopied={() => showSuccess("Access code copied.")}
        onCopyFailed={() => showError("Could not copy access details.")}
        onPrintFailed={() => showError("Could not open the print window.")}
      />

      {error ? (
        <div className="rounded-2xl border border-error/30 bg-error-soft px-4 py-3 text-sm text-error">
          {error}
        </div>
      ) : null}

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-xl font-semibold tracking-tight text-text sm:text-[1.65rem]">
            Student Directory
          </h1>
          <p className="mt-1 line-clamp-2 text-xs leading-5 text-text-muted sm:text-sm">
            Search and maintain student profiles, placement history, lifecycle and access.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            size="small"
            variant="outline"
            className="min-h-10"
            onClick={() => navigate("/admin/students/class-placement")}
          >
            <School className="h-4 w-4" /> Class Placement
          </Button>
          <Button
            type="button"
            size="small"
            className="min-h-10"
            onClick={() => navigate("/admin/students/create")}
          >
            <Plus className="h-4 w-4" /> Add Student
          </Button>
        </div>
      </div>

      <DirectorySummary
        items={[
          { label: "Matching records", value: total, detail: "all pages", icon: Users, tone: "primary" },
          { label: "Active", value: activeCount, detail: "this page", icon: UserCheck, tone: "success" },
          { label: "Class placed", value: placedCount, detail: `${students.length - placedCount} unassigned`, icon: School },
          {
            label: "Access ready",
            value: credentialsReadyCount,
            detail: `${students.length - credentialsReadyCount} need setup`,
            icon: KeyRound,
            tone: credentialsReadyCount === students.length ? "success" : "warning",
          },
        ]}
      />

      <Card className="people-filter-panel p-3 sm:p-5">
        <form
          onSubmit={(event) => event.preventDefault()}
          className="grid grid-cols-[minmax(0,1fr)_auto] gap-2 md:grid-cols-4 md:gap-3 xl:grid-cols-7"
        >
          <div className="people-filter-search">
            <Input
              label="Search"
              value={draftFilters.search}
              placeholder="Name or admission number"
              onChange={(event) =>
                setDraftFilters((current) => ({ ...current, search: event.target.value }))
              }
            />
          </div>
          <Button
            type="button"
            size="small"
            variant="outline"
            className="min-h-11 self-end md:hidden"
            aria-expanded={mobileFiltersOpen}
            onClick={() => setMobileFiltersOpen(true)}
          >
            <SlidersHorizontal className="h-4 w-4" /> Filters
            {activeFilterCount ? (
              <span className="grid h-5 min-w-5 place-items-center rounded-full bg-primary px-1 text-[0.65rem] text-primary-foreground">
                {activeFilterCount}
              </span>
            ) : null}
          </Button>
          <div className="hidden md:contents">
            <StudentFilterFields
              filters={draftFilters}
              setFilters={setDraftFilters}
              levelOptions={levelOptions}
              classOptions={classOptions}
            />
            <div className="grid gap-2 self-end">
              <Button type="button" size="small" variant="outline" onClick={clearFilters}>
                Clear
              </Button>
            </div>
          </div>
        </form>
      </Card>

      <Modal
        open={mobileFiltersOpen}
        title="Filter students"
        description="Narrow the directory without losing your place in the list."
        placement="bottom"
        className="mobile-filter-sheet md:hidden"
        onClose={() => setMobileFiltersOpen(false)}
        footer={
          <div className="grid grid-cols-2 gap-2">
            <Button type="button" variant="outline" onClick={clearFilters}>Clear filters</Button>
            <Button type="button" onClick={() => setMobileFiltersOpen(false)}>View results</Button>
          </div>
        }
      >
        <div className="grid gap-4">
          <StudentFilterFields
            filters={draftFilters}
            setFilters={setDraftFilters}
            levelOptions={levelOptions}
            classOptions={classOptions}
          />
        </div>
      </Modal>

      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border/70 bg-surface/60 px-4 py-2.5">
        <p className="text-sm text-text-muted">
          Showing <span className="font-semibold text-text">{students.length}</span> of{" "}
          <span className="font-semibold text-text">{total}</span> students
        </p>
        <p className="text-sm text-text-muted">Page {page} of {pageCount}</p>
      </div>

      {students.length === 0 ? (
        <Card className="p-6">
          <EmptyState
            title="No students found"
            description="Adjust the filters or create a student."
            actionLabel="Create student"
            onAction={() => navigate("/admin/students/create")}
          />
        </Card>
      ) : (
        <>
          <DirectoryTable
            label="Student directory"
            columns={[
              { key: "student", label: "Student" },
              { key: "class", label: "Class placement" },
              { key: "status", label: "Status" },
              { key: "profile", label: "Profile & access" },
              { key: "actions", label: "Actions", className: "text-right" },
            ]}
          >
            {students.map((student) => (
              <tr key={student.id} className="transition hover:bg-surface-muted/25">
                <td className="px-4 py-3.5 align-middle">
                  <PersonIdentity
                    name={displayName(student)}
                    meta={student.admission_number || "No admission number"}
                    avatarSrc={getAvatarSrcFromRecord(student)}
                  />
                </td>
                <td className="px-4 py-3.5 align-middle">
                  <p className="text-sm font-medium text-text-soft">{studentClassLabel(student)}</p>
                  <p className="mt-0.5 text-xs text-text-muted">Admitted {formatDate(student.admission_date)}</p>
                  {student.upcoming_enrollment ? (
                    <p className="mt-1 text-xs font-medium text-warning">
                      Upcoming: {upcomingPlacementLabel(student.upcoming_enrollment)} from {formatDate(student.upcoming_enrollment.started_on)}
                    </p>
                  ) : null}
                </td>
                <td className="px-4 py-3.5 align-middle">
                  <div className="flex flex-wrap gap-1.5">
                    <Badge variant={student.status === "active" ? "success" : "default"}>
                      {titleCase(student.status)}
                    </Badge>
                    {student.is_archived ? <Badge variant="error">Archived</Badge> : null}
                  </div>
                </td>
                <td className="px-4 py-3.5 align-middle">
                  <p className="text-sm font-medium text-text-soft">
                    {titleCase(student.profile_status) || "Not set"}
                  </p>
                  <p className={`mt-0.5 text-xs ${student.password_reset_required ? "text-warning" : "text-success"}`}>
                    {student.password_reset_required ? "Access setup required" : "Access configured"}
                  </p>
                </td>
                <td className="px-4 py-3.5 align-middle">
                  <StudentActions
                    student={student}
                    busy={busyId === student.id}
                    onEdit={openEdit}
                    onReset={setAccessCodeConfirmation}
                    onPlacementHistory={openPlacementHistory}
                    onReassignClass={(item) => openReassign(item, "class")}
                    onReassignLevel={(item) => openReassign(item, "level")}
                    onManageUpcoming={openUpcomingManager}
                    onLifecycle={openLifecycle}
                    onHardDelete={inspectHardDelete}
                  />
                </td>
              </tr>
            ))}
          </DirectoryTable>

          <MobileDirectoryList label="Student directory">
            {students.map((student) => (
              <StudentCard
                key={student.id}
                student={student}
                busy={busyId === student.id}
                onEdit={openEdit}
                onReset={setAccessCodeConfirmation}
                onPlacementHistory={openPlacementHistory}
                onReassignClass={(item) => openReassign(item, "class")}
                onReassignLevel={(item) => openReassign(item, "level")}
                onManageUpcoming={openUpcomingManager}
                onLifecycle={openLifecycle}
                onHardDelete={inspectHardDelete}
              />
            ))}
          </MobileDirectoryList>
        </>
      )}

      <div className="mobile-list-pagination flex items-center justify-between gap-2">
        <span className="text-xs font-semibold text-text-muted sm:hidden">Page {page}/{pageCount}</span>
        <div className="ml-auto grid grid-cols-2 gap-2 sm:flex">
          <Button
            type="button"
            variant="outline"
            size="small"
            disabled={page <= 1 || loading}
            onClick={() => setPage((current) => Math.max(1, current - 1))}
          >
            <ChevronLeft className="h-4 w-4" /> Previous
          </Button>
          <Button
            type="button"
            variant="outline"
            size="small"
            disabled={page >= pageCount || loading}
            onClick={() => setPage((current) => Math.min(pageCount, current + 1))}
          >
            Next <ChevronRight className="h-4 w-4" />
          </Button>
        </div>
      </div>

      <Modal
        open={Boolean(editState)}
        title="Edit student profile"
        description="Update profile fields. Placement changes are managed separately so history remains immutable."
        onClose={() => !busyId && setEditState(null)}
        closeOnOverlay={!busyId}
      >
        {editState ? (
          <form onSubmit={submitEdit} className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <Input
                label="First name"
                value={editState.form.first_name}
                required
                error={fieldErrors.first_name}
                onChange={(event) =>
                  setEditState((current) => ({ ...current, form: { ...current.form, first_name: event.target.value } }))
                }
              />
              <Input
                label="Last name"
                value={editState.form.last_name}
                required
                error={fieldErrors.last_name}
                onChange={(event) =>
                  setEditState((current) => ({ ...current, form: { ...current.form, last_name: event.target.value } }))
                }
              />
              <SelectField
                label="Gender"
                value={editState.form.gender}
                options={GENDER_OPTIONS.map((value) => ({ value, label: titleCase(value) }))}
                error={fieldErrors.gender}
                onChange={(value) =>
                  setEditState((current) => ({ ...current, form: { ...current.form, gender: value } }))
                }
              />
              <Input
                label="Date of birth"
                type="date"
                value={editState.form.date_of_birth}
                required
                error={fieldErrors.date_of_birth}
                onChange={(event) =>
                  setEditState((current) => ({ ...current, form: { ...current.form, date_of_birth: event.target.value } }))
                }
              />
              <Input
                label="State of origin"
                value={editState.form.state_of_origin}
                error={fieldErrors.state_of_origin}
                onChange={(event) =>
                  setEditState((current) => ({ ...current, form: { ...current.form, state_of_origin: event.target.value } }))
                }
              />
            </div>
            <div className="flex justify-end gap-2">
              <Button type="button" variant="outline" disabled={Boolean(busyId)} onClick={() => setEditState(null)}>
                Cancel
              </Button>
              <Button type="submit" disabled={Boolean(busyId)}>{busyId ? "Saving..." : "Save changes"}</Button>
            </div>
          </form>
        ) : null}
      </Modal>

      <Modal
        open={Boolean(accessCodeConfirmation)}
        title="Generate new access code"
        description={accessCodeConfirmation ? `Generate a new one-time access code for ${displayName(accessCodeConfirmation)}.` : ""}
        onClose={() => !busyId && setAccessCodeConfirmation(null)}
        closeOnOverlay={!busyId}
        footer={
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button type="button" variant="outline" disabled={Boolean(busyId)} onClick={() => setAccessCodeConfirmation(null)}>Cancel</Button>
            <Button type="button" disabled={Boolean(busyId)} onClick={() => resetAccessCode(accessCodeConfirmation)}>
              {busyId ? "Generating..." : "Generate code"}
            </Button>
          </div>
        }
      >
        <p className="text-sm leading-6 text-text-muted">
          The student's academic history and placement records are not changed by credential reset.
        </p>
      </Modal>

      <Modal
        open={Boolean(lifecycleState)}
        title={lifecycleState ? lifecycleConfig[lifecycleState.actionKey].label : "Student lifecycle"}
        description="This action is recorded against the student lifecycle."
        onClose={() => !busyId && setLifecycleState(null)}
        closeOnOverlay={!busyId}
      >
        {lifecycleState ? (
          <form onSubmit={submitLifecycle} className="space-y-4">
            <div className="rounded-xl bg-surface-muted/40 px-4 py-3 text-sm">
              <p className="font-semibold text-text">{displayName(lifecycleState.student)}</p>
              <p className="mt-1 text-text-muted">{lifecycleState.student.admission_number}</p>
            </div>
            {lifecycleConfig[lifecycleState.actionKey].immediate ? (
              <p className="rounded-xl border border-border/70 bg-surface-muted/25 px-4 py-3 text-sm text-text-soft">
                Effective immediately - {formatDate(localDateInputValue())}
              </p>
            ) : null}
            {lifecycleConfig[lifecycleState.actionKey].usesEffectiveDate ? (
              <Input
                label="Effective date"
                type="date"
                min={localDateInputValue()}
                value={lifecycleState.form.effective_date}
                required
                error={fieldErrors.effective_date}
                onChange={(event) =>
                  setLifecycleState((current) => ({ ...current, form: { ...current.form, effective_date: event.target.value } }))
                }
              />
            ) : null}
            {lifecycleConfig[lifecycleState.actionKey].returnFlow ? (
              <p className="text-sm text-text-muted">
                A previous enrollment owns its final date. If the exit was a mistake, use Undo;
                otherwise choose the following day or later. Future return dates are allowed.
              </p>
            ) : null}
            {lifecycleConfig[lifecycleState.actionKey].usesPlacement ? (
              <div className="grid gap-4 sm:grid-cols-2">
                <SelectField
                  label="Academic level"
                  value={lifecycleState.form.target_academic_level_id}
                  options={levelOptions}
                  required
                  error={fieldErrors.target_academic_level_id}
                  onChange={(value) =>
                    setLifecycleState((current) => ({
                      ...current,
                      form: {
                        ...current.form,
                        target_academic_level_id: value,
                        target_class_id: "",
                      },
                    }))
                  }
                />
                <SelectField
                  label="Target class"
                  value={lifecycleState.form.target_class_id}
                  options={classOptions.filter((item) => {
                    const classroom = classes.find((row) => row.id === item.value);
                    return classroom?.academic_level_id === lifecycleState.form.target_academic_level_id;
                  })}
                  required
                  error={fieldErrors.target_class_id}
                  onChange={(value) =>
                    setLifecycleState((current) => ({ ...current, form: { ...current.form, target_class_id: value } }))
                  }
                />
                <SelectField
                  label="Academic session"
                  value={lifecycleState.form.academic_session_id}
                  options={sessionOptions}
                  required
                  error={fieldErrors.academic_session_id}
                  onChange={(value) =>
                    setLifecycleState((current) => ({ ...current, form: { ...current.form, academic_session_id: value } }))
                  }
                />
              </div>
            ) : null}
            {lifecycleConfig[lifecycleState.actionKey].usesPromotionHold ? (
              <label className="flex items-center gap-2 rounded-xl border border-border px-3 py-2 text-sm font-semibold text-text-soft">
                <input
                  type="checkbox"
                  checked={lifecycleState.form.promotion_hold}
                  onChange={(event) =>
                    setLifecycleState((current) => ({ ...current, form: { ...current.form, promotion_hold: event.target.checked } }))
                  }
                />
                Hold automatic progression while suspended
              </label>
            ) : null}
            <label className="block">
              <span className="mb-1.5 block text-sm font-semibold text-text-soft">Reason</span>
              <textarea
                className="input-base min-h-24"
                maxLength={500}
                required
                value={lifecycleState.form.reason}
                onChange={(event) =>
                  setLifecycleState((current) => ({ ...current, form: { ...current.form, reason: event.target.value } }))
                }
              />
              {fieldErrors.reason ? <p className="mt-1 text-xs text-error">{fieldErrors.reason}</p> : null}
            </label>
            <div className="flex justify-end gap-2">
              <Button type="button" variant="outline" disabled={Boolean(busyId)} onClick={() => setLifecycleState(null)}>Cancel</Button>
              <Button type="submit" disabled={Boolean(busyId)}>{busyId ? "Saving..." : "Confirm action"}</Button>
            </div>
          </form>
        ) : null}
      </Modal>

      <Modal
        open={placementState?.type === "history"}
        title="Placement History"
        description={placementState?.student ? `Immutable enrollment segments for ${displayName(placementState.student)}.` : ""}
        onClose={() => setPlacementState(null)}
      >
        {placementState?.loading ? (
          <LoadingState label="Loading placement history..." />
        ) : placementState?.items?.length ? (
          <div className="space-y-3">
            {placementState.items.map((item) => (
              <div key={item.id} className="rounded-xl border border-border/70 bg-surface-muted/25 px-4 py-3">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <p className="font-semibold text-text">
                      {[item.academic_level_name, item.class_arm].filter(Boolean).join(" ") || item.academic_level_name || "Unassigned"}
                    </p>
                    <p className="mt-1 text-sm text-text-muted">
                      {item.class_id ? item.class_name || "Class assigned" : "Class: Unassigned"}
                    </p>
                  </div>
                  <Badge variant={item.lifecycle_state === "current" ? "success" : item.lifecycle_state === "upcoming" ? "warning" : "default"}>
                    {item.lifecycle_state === "upcoming"
                      ? `Upcoming · starts ${formatDate(item.started_on)}`
                      : item.lifecycle_state === "current"
                        ? `${formatDate(item.started_on)} – Current`
                        : `${formatDate(item.started_on)} – ${formatDate(item.ended_on)}`}
                  </Badge>
                </div>
                <p className="mt-2 text-xs text-text-muted">
                  Entry: {titleCase(item.entry_outcome)}{item.entry_reason ? ` · ${item.entry_reason}` : ""}
                </p>
                {item.lifecycle_state === "upcoming" ? (
                  <div className="mt-3 flex flex-wrap gap-2">
                    <Button type="button" size="small" variant="outline" onClick={() => openUpcomingEdit(placementState.student, item)}>
                      Edit schedule
                    </Button>
                    <Button
                      type="button"
                      size="small"
                      variant="danger"
                      onClick={() => setPlacementState({ type: "upcomingCancel", student: placementState.student, enrollment: item, reason: "" })}
                    >
                      Cancel schedule
                    </Button>
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        ) : (
          <EmptyState title="No placement history" description="No enrollment segments are available for this student." />
        )}
      </Modal>

      <Modal
        open={placementState?.type === "class" || placementState?.type === "level"}
        title={placementState?.type === "class" ? "Reassign Class" : "Reassign Academic Level"}
        description="Reassignment remains allowed when academic evidence exists. Review the impact before confirming."
        onClose={() => !busyId && setPlacementState(null)}
        closeOnOverlay={!busyId}
      >
        {placementState?.form ? (
          <form onSubmit={submitReassignment} className="space-y-4">
            <div className="rounded-xl bg-surface-muted/35 px-4 py-3 text-sm">
              <p className="font-semibold text-text">{displayName(placementState.student)}</p>
              <p className="mt-1 text-text-muted">Current placement: {studentClassLabel(placementState.student)}</p>
            </div>
            {placementState.type === "level" ? (
              <SelectField
                label="Destination academic level"
                value={placementState.form.target_academic_level_id}
                options={levelOptions.filter((item) => item.value !== placementState.student.academic_level_id)}
                required
                onChange={(value) => updatePlacementForm("target_academic_level_id", value)}
              />
            ) : null}
            <SelectField
              label="Destination class"
              value={placementState.form.target_class_id}
              options={placementClassOptions}
              required
              disabled={!placementState.form.target_academic_level_id}
              onChange={(value) => updatePlacementForm("target_class_id", value)}
            />
            <div className="grid gap-4 sm:grid-cols-2">
              <SelectField
                label="Academic session"
                value={placementState.form.academic_session_id}
                options={sessionOptions}
                required
                onChange={(value) => updatePlacementForm("academic_session_id", value)}
              />
              <Input
                label="Effective date"
                type="date"
                value={placementState.form.effective_date}
                required
                onChange={(event) => updatePlacementForm("effective_date", event.target.value)}
              />
            </div>
            <Button
              type="button"
              variant="outline"
              disabled={placementState.previewLoading}
              onClick={previewPlacement}
            >
              {placementState.previewLoading ? "Previewing..." : "Preview placement impact"}
            </Button>
            <ImpactPreview preview={placementState.preview} />
            <label className="block">
              <span className="mb-1.5 block text-sm font-semibold text-text-soft">Mandatory reason</span>
              <textarea
                className="input-base min-h-24"
                maxLength={500}
                required
                value={placementState.form.reason}
                onChange={(event) => updatePlacementForm("reason", event.target.value)}
              />
              {fieldErrors.reason ? <p className="mt-1 text-xs text-error">{fieldErrors.reason}</p> : null}
            </label>
            <div className="flex justify-end gap-2">
              <Button type="button" variant="outline" disabled={Boolean(busyId)} onClick={() => setPlacementState(null)}>Cancel</Button>
              <Button type="submit" disabled={Boolean(busyId) || !placementState.preview}>
                {busyId ? "Reassigning..." : "Confirm reassignment"}
              </Button>
            </div>
          </form>
        ) : null}
      </Modal>

      <Modal
        open={placementState?.type === "upcomingManage"}
        title="Manage Scheduled Placement"
        description="Review the student's planned class or academic-level change before it becomes effective."
        onClose={() => !busyId && setPlacementState(null)}
        closeOnOverlay={!busyId}
      >
        {placementState?.enrollment ? (
          <div className="space-y-4">
            <div className="rounded-xl bg-surface-muted/35 px-4 py-3 text-sm">
              <p className="font-semibold text-text">{displayName(placementState.student)}</p>
              <p className="mt-1 text-text-muted">Current placement: {studentClassLabel(placementState.student)}</p>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="rounded-xl border border-border/70 px-4 py-3">
                <p className="text-xs font-semibold uppercase text-text-muted">Scheduled placement</p>
                <p className="mt-1 font-semibold text-text">
                  {upcomingPlacementLabel(placementState.enrollment)}
                </p>
                <p className="mt-1 text-sm text-text-muted">
                  {placementState.enrollment.class_name || "Class assigned"}
                </p>
              </div>
              <div className="rounded-xl border border-warning/30 bg-warning-soft/30 px-4 py-3">
                <p className="text-xs font-semibold uppercase text-warning">Takes effect</p>
                <p className="mt-1 font-semibold text-text">
                  {formatDate(placementState.enrollment.started_on)}
                </p>
                <p className="mt-1 text-sm text-text-muted">
                  {sessionOptions.find((option) => option.value === placementState.enrollment.academic_session_id)?.label || "Academic session"}
                </p>
              </div>
            </div>
            <p className="text-sm leading-6 text-text-muted">
              Editing this schedule can change the target academic level, target class or effective date. Historical placement remains unchanged until the schedule becomes effective.
            </p>
            <div className="flex flex-wrap justify-end gap-2">
              <Button type="button" variant="outline" disabled={Boolean(busyId)} onClick={() => setPlacementState(null)}>
                Close
              </Button>
              <Button
                type="button"
                variant="outline"
                disabled={Boolean(busyId)}
                onClick={() => openUpcomingEdit(placementState.student, placementState.enrollment)}
              >
                Edit schedule
              </Button>
              <Button
                type="button"
                variant="danger"
                disabled={Boolean(busyId)}
                onClick={() => setPlacementState({
                  type: "upcomingCancel",
                  student: placementState.student,
                  enrollment: placementState.enrollment,
                  reason: "",
                })}
              >
                Cancel schedule
              </Button>
            </div>
          </div>
        ) : null}
      </Modal>

      <Modal
        open={placementState?.type === "upcomingEdit"}
        title="Edit Scheduled Placement"
        description="Change a future class or academic-level placement before it becomes effective. Current and historical placement remain intact."
        onClose={() => !busyId && setPlacementState(null)}
        closeOnOverlay={!busyId}
      >
        {placementState?.form ? (
          <form onSubmit={submitUpcomingEdit} className="space-y-4">
            <SelectField
              label="Academic level"
              value={placementState.form.target_academic_level_id}
              options={levelOptions}
              required
              onChange={(value) => updatePlacementForm("target_academic_level_id", value)}
            />
            <SelectField
              label="Class"
              value={placementState.form.target_class_id}
              options={placementClassOptions}
              required
              onChange={(value) => updatePlacementForm("target_class_id", value)}
            />
            <SelectField
              label="Academic session"
              value={placementState.form.academic_session_id}
              options={sessionOptions}
              required
              onChange={(value) => updatePlacementForm("academic_session_id", value)}
            />
            <Input
              label="Starts on"
              type="date"
              min={tomorrowDateInputValue()}
              value={placementState.form.effective_date}
              required
              onChange={(event) => updatePlacementForm("effective_date", event.target.value)}
            />
            <Input
              label="Audit reason"
              value={placementState.form.reason}
              minLength={3}
              maxLength={500}
              required
              error={fieldErrors.reason}
              onChange={(event) => updatePlacementForm("reason", event.target.value)}
            />
            <div className="flex justify-end gap-2">
              <Button type="button" variant="outline" disabled={Boolean(busyId)} onClick={() => setPlacementState(null)}>Cancel</Button>
              <Button type="submit" disabled={Boolean(busyId)}>{busyId ? "Saving..." : "Save scheduled placement"}</Button>
            </div>
          </form>
        ) : null}
      </Modal>

      <Modal
        open={placementState?.type === "upcomingCancel"}
        title="Cancel Scheduled Placement"
        description="Only the never-effective future enrollment will be removed. A current predecessor is reopened when this was a scheduled placement change."
        onClose={() => !busyId && setPlacementState(null)}
        closeOnOverlay={!busyId}
      >
        <form onSubmit={submitUpcomingCancel} className="space-y-4">
          <Input
            label="Audit reason"
            value={placementState?.reason || ""}
            minLength={3}
            maxLength={500}
            required
            onChange={(event) => setPlacementState((current) => ({ ...current, reason: event.target.value }))}
          />
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" disabled={Boolean(busyId)} onClick={() => setPlacementState(null)}>Keep schedule</Button>
            <Button type="submit" variant="danger" disabled={Boolean(busyId) || (placementState?.reason || "").trim().length < 3}>
              {busyId ? "Cancelling..." : "Cancel scheduled placement"}
            </Button>
          </div>
        </form>
      </Modal>

      <Modal
        open={Boolean(hardDeleteState)}
        title="Hard-delete eligibility"
        description="Permanent deletion is allowed only for an unused accidental record. Historical academic evidence prevents deletion."
        onClose={() => !busyId && setHardDeleteState(null)}
        closeOnOverlay={!busyId}
      >
        {hardDeleteState?.loading ? (
          <LoadingState label="Checking historical dependencies..." />
        ) : hardDeleteState ? (
          <form onSubmit={submitHardDelete} className="space-y-4">
            <div className={`rounded-xl border px-4 py-3 text-sm ${hardDeleteState.eligibility?.eligible ? "border-success/30 bg-success-soft text-success" : "border-error/30 bg-error-soft text-error"}`}>
              {hardDeleteState.eligibility?.eligible
                ? "This unused record is eligible for permanent deletion."
                : hardDeleteState.eligibility?.reason || "This record has dependencies and cannot be hard-deleted."}
            </div>
            {hardDeleteState.eligibility?.eligible ? (
              <>
                <Input
                  label="Confirmation"
                  value={hardDeleteState.confirmation}
                  placeholder="DELETE_UNUSED_STUDENT"
                  onChange={(event) => setHardDeleteState((current) => ({ ...current, confirmation: event.target.value }))}
                />
                <label className="block">
                  <span className="mb-1.5 block text-sm font-semibold text-text-soft">Reason</span>
                  <textarea
                    className="input-base min-h-24"
                    maxLength={500}
                    value={hardDeleteState.reason}
                    onChange={(event) => setHardDeleteState((current) => ({ ...current, reason: event.target.value }))}
                  />
                </label>
                <div className="flex justify-end gap-2">
                  <Button type="button" variant="outline" onClick={() => setHardDeleteState(null)} disabled={Boolean(busyId)}>Cancel</Button>
                  <Button type="submit" variant="danger" disabled={Boolean(busyId)}>
                    {busyId ? "Deleting..." : "Permanently delete"}
                  </Button>
                </div>
              </>
            ) : null}
          </form>
        ) : null}
      </Modal>
    </div>
  );
}

export default StudentDirectoryPage;
