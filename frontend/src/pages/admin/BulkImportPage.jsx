import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  CheckCircle2,
  AlertCircle,
  Download,
  FileSpreadsheet,
  History,
  Loader2,
  Printer,
  RefreshCw,
  Search,
  Trash2,
  UploadCloud,
  X,
} from "lucide-react";

import DashboardLayout from "../../components/layout/DashboardLayout";
import Badge from "../../components/ui/Badge";
import Button from "../../components/ui/Button";
import Card from "../../components/ui/Card";
import Modal from "../../components/ui/Modal";
import EmptyState from "../../components/shared/EmptyState";
import LoadingState from "../../components/shared/LoadingState";
import { useToast } from "../../hooks/useToast";
import { getErrorMessage } from "../../services/api";
import { bulkImportService } from "../../services/bulkImport.service";
import { realtimeClient } from "../../services/realtimeClient";
import {
  BULK_IMPORT_REALTIME_EVENTS,
  matchesBulkImportEvent,
} from "../../services/realtimeEventMatchers";
import {
  HISTORY_NEXT_LABEL,
  getActualParentInvitationsQueued,
  getExpectedParentInvitationCount,
  getNextHistoryRequest,
  getPreviousHistoryRequest,
  getResultRows,
  getStatusChangeHistoryRequest,
  loadImportHistoryPage,
} from "./bulkImportPageLogic";

const ACTIVE_IMPORT_JOB_STORAGE_KEY = "weave:active-import-job";
const VALID_STEPS = new Set([
  "upload",
  "validate",
  "review",
  "process",
  "history",
]);
const ACTIVE_JOB_STATUSES = new Set(["pending", "processing"]);
const TERMINAL_JOB_STATUSES = new Set([
  "completed",
  "partially_completed",
  "failed",
  "cancelled",
]);

const stepOrder = ["upload", "validate", "review", "process"];
const stepLabels = {
  upload: "Download and upload",
  validate: "Validation result",
  review: "Review dry run",
  process: "Process and results",
};

const statusLabels = {
  pending: "Queued",
  processing: "Processing",
  completed: "Completed",
  partially_completed: "Completed with errors",
  failed: "Failed",
  cancelled: "Cancelled",
};

const statusVariants = {
  pending: "info",
  processing: "warning",
  completed: "success",
  partially_completed: "warning",
  failed: "error",
  cancelled: "default",
};
const historyStatusOptions = [
  { value: "", label: "All statuses" },
  { value: "pending", label: "Queued" },
  { value: "processing", label: "Processing" },
  { value: "completed", label: "Completed" },
  { value: "partially_completed", label: "Completed with errors" },
  { value: "failed", label: "Failed" },
  { value: "cancelled", label: "Cancelled" },
];
const errorSuggestions = {
  required: "Enter a value in this column.",
  invalid_date: "Use a supported date format such as YYYY-MM-DD.",
  date_not_before_today: "Enter a date earlier than today.",
  invalid_email: "Enter a valid email address.",
  class_not_found: "Use the name and optional arm of an existing class.",
  class_inactive: "Choose an active, non-archived class.",
  invalid_parent_relationship:
    "Use father, mother, guardian, sponsor, or other.",
  duplicate_parent_email: "Use two different parent email addresses.",
  parent_email_role_conflict:
    "Use an email that is not already registered under another role.",
};

const formatDate = (value) => {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "--";
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
};

const formatBytes = (value) => {
  const bytes = Number(value || 0);
  if (!bytes) return "--";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
};

const percent = (value, total) => {
  const safeTotal = Number(total || 0);
  if (!safeTotal) return 0;
  return Math.min(100, Math.round((Number(value || 0) / safeTotal) * 100));
};

const getFailedResultRows = (job) =>
  getResultRows(job).filter(
    (row) =>
      String(row?.status || "").toLowerCase() === "failed" ||
      row?.error_message,
  );
const inferErrorFieldName = (item) => {
  if (item?.field_name) return item.field_name;
  const prefix = String(item?.error_message || "")
    .split(":")[0]
    ?.trim();
  return /^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$/i.test(prefix) ? prefix : null;
};
const isStudentJob = (job) => String(job?.resource_type || "") === "students";
const isActiveJob = (job) =>
  job?.id && ACTIVE_JOB_STATUSES.has(String(job.status || "").toLowerCase());
const isTerminalJob = (job) =>
  job?.id && TERMINAL_JOB_STATUSES.has(String(job.status || "").toLowerCase());
const canConfirmJob = (job) =>
  isStudentJob(job) &&
  job?.metadata_json?.dry_run &&
  job?.metadata_json?.confirmation_required &&
  Number(job?.failed_rows || 0) === 0 &&
  Number(job?.successful_rows || 0) > 0 &&
  !job?.metadata_json?.confirmed_at;
const canDeleteJob = (job) => job?.id && !isActiveJob(job);

const routeForStep = (nextStep, jobId) => {
  if (nextStep === "upload") return "/admin/imports/upload";
  if (nextStep === "history") return "/admin/imports/history";
  return jobId ? `/admin/imports/${nextStep}/${jobId}` : null;
};

function StepHeader({ step, currentJob, onNavigate }) {
  const activeIndex = Math.max(0, stepOrder.indexOf(step));
  return (
    <Card className="p-3 sm:p-4">
      <div className="grid grid-cols-2 gap-2 sm:gap-4 md:grid-cols-4">
        {stepOrder.map((key, index) => {
          const complete = index < activeIndex;
          const active = index === activeIndex;
          const canNavigate =
            key === "upload" || Boolean(routeForStep(key, currentJob?.id));
          return (
            <button
              key={key}
              type="button"
              disabled={!canNavigate}
              onClick={() => onNavigate(key)}
              className="flex min-h-12 min-w-0 items-center gap-2 rounded-xl p-2 text-left transition hover:bg-surface-muted/40 sm:gap-3"
            >
              <span
                className={[
                  "flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-sm font-bold ring-1 ring-inset",
                  complete
                    ? "bg-success text-text-inverse ring-success"
                    : active
                      ? "bg-primary text-text-inverse ring-primary"
                      : "bg-surface-muted text-text-muted ring-border",
                ].join(" ")}
              >
                {complete ? <CheckCircle2 className="h-4 w-4" /> : index + 1}
              </span>
              <span
                className={[
                  "line-clamp-2 text-xs font-semibold leading-tight sm:text-sm",
                  canNavigate ? "text-text" : "text-text-muted",
                ].join(" ")}
              >
                {stepLabels[key]}
              </span>
            </button>
          );
        })}
      </div>
    </Card>
  );
}

function MetricCard({ label, value, variant = "default" }) {
  return (
    <Card className="min-h-[5.75rem] p-3 sm:min-h-[7rem] sm:p-4">
      <p className="text-xs font-semibold uppercase text-text-muted">{label}</p>
      <p
        className={[
          "mt-1 text-xl font-bold sm:mt-2 sm:text-2xl",
          variant === "success"
            ? "text-success"
            : variant === "error"
              ? "text-error"
              : "text-text",
        ].join(" ")}
      >
        {value ?? 0}
      </p>
    </Card>
  );
}

function JobStatusBadge({ job }) {
  const status = String(job?.status || "pending").toLowerCase();
  return (
    <Badge variant={statusVariants[status] || "default"}>
      {statusLabels[status] || status}
    </Badge>
  );
}

function BulkImportPage() {
  const { step: routeStep, jobId } = useParams();
  const navigate = useNavigate();
  const { showSuccess, showError } = useToast();
  const fileInputRef = useRef(null);
  const workspaceRef = useRef(null);
  const step = VALID_STEPS.has(routeStep) ? routeStep : "upload";

  const [file, setFile] = useState(null);
  const [currentJob, setCurrentJob] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [jobsTotal, setJobsTotal] = useState(0);
  const [historySearch, setHistorySearch] = useState("");
  const [appliedHistorySearch, setAppliedHistorySearch] = useState("");
  const historyRequestVersion = useRef(0);
  useEffect(() => {
    const timer = window.setTimeout(() => setAppliedHistorySearch(historySearch.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [historySearch]);
  const [historyStatus, setHistoryStatus] = useState("");
  const [historySkip, setHistorySkip] = useState(0);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [errors, setErrors] = useState([]);
  const [errorSearch, setErrorSearch] = useState("");
  const [busy, setBusy] = useState("");
  const [validationProgress, setValidationProgress] = useState(0);
  const [pageLoading, setPageLoading] = useState(true);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [deleteJob, setDeleteJob] = useState(null);
  const [criticalImportError, setCriticalImportError] = useState(null);
  const [displayStep, setDisplayStep] = useState(step);
  const [transitionState, setTransitionState] = useState("entered");

  const navigateSmooth = useCallback(
    (to, options) => {
      const doNavigate = () => navigate(to, options);
      if (document.startViewTransition) {
        document.startViewTransition(doNavigate);
      } else {
        doNavigate();
      }
      window.setTimeout(() => {
        workspaceRef.current?.scrollIntoView({
          behavior: "smooth",
          block: "start",
        });
      }, 80);
    },
    [navigate],
  );

  const go = useCallback(
    (nextStep, nextJobId = currentJob?.id) => {
      const nextRoute = routeForStep(nextStep, nextJobId);
      if (nextRoute) navigateSmooth(nextRoute);
    },
    [currentJob?.id, navigateSmooth],
  );

  const loadJob = useCallback(async (id, { force = false } = {}) => {
    const job = await bulkImportService.getJob(id, { force });
    setCurrentJob(job);
    if (job?.id) {
      window.sessionStorage.setItem(ACTIVE_IMPORT_JOB_STORAGE_KEY, job.id);
      const errorResponse = await bulkImportService
        .getErrors(job.id, force ? { force: true } : {})
        .catch(() => ({ items: [] }));
      setErrors(Array.isArray(errorResponse?.items) ? errorResponse.items : []);
    }
    return job;
  }, []);

  const loadJobs = useCallback(
    ({ skip, status }) => {
      const requestVersion = ++historyRequestVersion.current;
      return loadImportHistoryPage({
        listJobs: bulkImportService.listJobs,
        skip,
        status,
        search: appliedHistorySearch,
        isCurrent: () => requestVersion === historyRequestVersion.current,
        setJobs,
        setJobsTotal,
        setHistorySkip,
        setHistoryLoading,
      });
    },
    [appliedHistorySearch],
  );

  const refresh = useCallback(async () => {
    try {
      if (step === "history") return;
      const targetJobId =
        jobId || window.sessionStorage.getItem(ACTIVE_IMPORT_JOB_STORAGE_KEY);
      if (targetJobId) {
        await loadJob(targetJobId);
      }
    } catch (error) {
      showError(getErrorMessage(error, "Could not load import jobs."));
    } finally {
      setPageLoading(false);
    }
  }, [jobId, loadJob, showError, step]);

  useEffect(() => {
    if (!VALID_STEPS.has(routeStep || "upload")) {
      navigateSmooth("/admin/imports/upload", { replace: true });
      return;
    }
    refresh();
  }, [navigateSmooth, refresh, routeStep]);

  useEffect(() => {
    if (step !== "history") return undefined;

    let mounted = true;
    loadJobs({ skip: historySkip, status: historyStatus }).catch((error) => {
      if (mounted)
        showError(getErrorMessage(error, "Could not load import history."));
    });

    return () => {
      mounted = false;
      historyRequestVersion.current += 1;
    };
  }, [historySkip, historyStatus, loadJobs, showError, step]);

  const handleRefresh = useCallback(() => {
    if (step === "history") {
      loadJobs({ skip: historySkip, status: historyStatus }).catch((error) => {
        showError(getErrorMessage(error, "Could not load import history."));
      });
      return;
    }
    refresh();
  }, [historySkip, historyStatus, loadJobs, refresh, showError, step]);

  useEffect(() => {
    if (step === displayStep) return undefined;
    setTransitionState("leaving");
    const swapTimer = window.setTimeout(() => {
      setDisplayStep(step);
      setTransitionState("entering");
      window.requestAnimationFrame(() => setTransitionState("entered"));
    }, 110);
    return () => window.clearTimeout(swapTimer);
  }, [displayStep, step]);

  useEffect(() => {
    const activeJobId = currentJob?.id;
    if (!activeJobId) return undefined;

    const reconcile = () => {
      loadJob(activeJobId, { force: true }).catch((error) => {
        showError(getErrorMessage(error, "Could not refresh import progress."));
      });
    };
    const unsubscribers = BULK_IMPORT_REALTIME_EVENTS.map((eventType) =>
      realtimeClient.subscribe(eventType, (message) => {
        if (matchesBulkImportEvent(activeJobId, message)) reconcile();
      }),
    );
    unsubscribers.push(
      realtimeClient.subscribeConnection((state) => {
        if (state.status === "reconnected" && isActiveJob(currentJob))
          reconcile();
      }),
    );

    return () => unsubscribers.forEach((unsubscribe) => unsubscribe());
  }, [currentJob, loadJob, showError]);

  useEffect(() => {
    if (busy !== "validate") return undefined;

    setValidationProgress(12);
    const timer = window.setInterval(() => {
      setValidationProgress((current) => {
        if (current < 45) return current + 8;
        if (current < 75) return current + 5;
        return Math.min(current + 2, 92);
      });
    }, 450);

    return () => window.clearInterval(timer);
  }, [busy]);

  const filteredErrors = useMemo(() => {
    const query = errorSearch.trim().toLowerCase();
    const displayErrors = errors.length
      ? errors.map((item) => ({
          ...item,
          field_name: inferErrorFieldName(item),
        }))
      : getFailedResultRows(currentJob).map((row) => ({
          id: `result-row-${row.row_number}`,
          row_number: row.row_number,
          field_name: inferErrorFieldName(row),
          error_code: row.error_code || "row_failed",
          error_message:
            row.error_message ||
            currentJob?.error_message ||
            "This row failed during import.",
          normalized_row: row,
        }));

    if (!query) return displayErrors;
    return displayErrors.filter((item) =>
      [
        item.row_number,
        item.field_name,
        item.error_code,
        item.error_message,
        item.normalized_row?.first_name,
        item.normalized_row?.last_name,
      ].some((value) =>
        String(value || "")
          .toLowerCase()
          .includes(query),
      ),
    );
  }, [currentJob, errorSearch, errors]);

  const expectedParentInvitationCount = useMemo(
    () => getExpectedParentInvitationCount(currentJob),
    [currentJob],
  );
  const actualParentInvitationsQueued = useMemo(
    () => getActualParentInvitationsQueued(currentJob),
    [currentJob],
  );
  // Search is applied across the tenant in PostgreSQL before pagination.
  const filteredJobs = jobs;

  const handleDownloadTemplate = async () => {
    setBusy("template");
    try {
      await bulkImportService.downloadTemplate();
      showSuccess("Student template downloaded.");
    } catch (error) {
      showError(getErrorMessage(error, "Could not download the template."));
    } finally {
      setBusy("");
    }
  };

  const handleValidate = async () => {
    if (!file) return;
    setBusy("validate");
    try {
      const job = await bulkImportService.dryRun(file);
      setCurrentJob(job);
      window.sessionStorage.setItem(ACTIVE_IMPORT_JOB_STORAGE_KEY, job.id);
      const errorResponse = await bulkImportService
        .getErrors(job.id)
        .catch(() => ({ items: [] }));
      setErrors(Array.isArray(errorResponse?.items) ? errorResponse.items : []);
      await loadJobs({ skip: historySkip, status: historyStatus });
      setValidationProgress(100);
      showSuccess(
        Number(job.failed_rows || 0)
          ? "Validation finished with errors."
          : "Validation passed.",
      );
      navigateSmooth(`/admin/imports/validate/${job.id}`);
    } catch (error) {
      setCriticalImportError({
        title: "Validation blocked",
        message: getErrorMessage(error, "Could not validate the file."),
      });
    } finally {
      setBusy("");
      window.setTimeout(() => setValidationProgress(0), 600);
    }
  };

  const handleConfirm = async () => {
    if (!currentJob?.id) return;
    setBusy("confirm");
    try {
      const job = await bulkImportService.confirm(currentJob.id);
      setCurrentJob(job);
      setConfirmOpen(false);
      await loadJobs({ skip: historySkip, status: historyStatus });
      showSuccess("Student import queued for background processing.");
      navigateSmooth(`/admin/imports/process/${job.id}`);
    } catch (error) {
      showError(getErrorMessage(error, "Could not queue the import."));
    } finally {
      setBusy("");
    }
  };

  const handleDownloadResult = async (format) => {
    if (!currentJob?.id) return;
    setBusy(format);
    try {
      await bulkImportService.downloadResult(currentJob.id, { format });
      showSuccess(
        format === "slip"
          ? "Student access slips downloaded."
          : "Result spreadsheet downloaded.",
      );
    } catch (error) {
      showError(getErrorMessage(error, "Could not download the result."));
    } finally {
      setBusy("");
    }
  };

  const handleDownloadErrors = async () => {
    if (!currentJob?.id) return;
    setBusy("errors");
    try {
      await bulkImportService.downloadErrors(currentJob.id);
      showSuccess("Validation error report downloaded.");
    } catch (error) {
      showError(getErrorMessage(error, "Could not download the error report."));
    } finally {
      setBusy("");
    }
  };

  const handleDeleteJob = async () => {
    if (!deleteJob?.id) return;
    setBusy("delete");
    try {
      await bulkImportService.deleteJob(deleteJob.id);
      showSuccess("Import history entry deleted.");
      setDeleteJob(null);
      if (currentJob?.id === deleteJob.id) {
        setCurrentJob(null);
        navigateSmooth("/admin/imports/history");
      }
      await loadJobs({ skip: historySkip, status: historyStatus });
    } catch (error) {
      showError(getErrorMessage(error, "Could not delete this import job."));
    } finally {
      setBusy("");
    }
  };

  const openHistoryJob = async (id) => {
    await loadJob(id);
    navigateSmooth(`/admin/imports/process/${id}`);
  };

  const onDrop = (event) => {
    event.preventDefault();
    const selected = event.dataTransfer.files?.[0];
    if (selected) setFile(selected);
  };

  if (pageLoading) {
    return (
      <DashboardLayout
        role="admin"
        title="Import Students"
        description="Download the official template, upload it for validation, then continue step by step."
      >
        <LoadingState label="Loading import workspace..." />
      </DashboardLayout>
    );
  }

  const renderUpload = () => (
    <Card className="p-3 sm:p-5">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="text-lg font-semibold text-text">
            Start With The Official Template
          </h2>
          <p className="mt-1 max-w-2xl text-sm text-text-muted">
            Download the backend-generated XLSX file, keep the headers
            unchanged, then upload the completed student sheet.
          </p>
        </div>
        <Button
          className="w-full sm:w-auto"
          onClick={handleDownloadTemplate}
          disabled={Boolean(busy)}
        >
          {busy === "template" ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Download className="h-4 w-4" />
          )}
          Download student template
        </Button>
      </div>
      <div className="mt-4 grid grid-cols-1 gap-2 sm:gap-3 md:grid-cols-3">
        <div className="rounded-lg border border-border bg-surface-muted/40 p-3 text-sm text-text-muted">
          Required: first name, last name, date of birth, and class name. Class
          arm is optional for classes without an arm.
        </div>
        <div className="rounded-lg border border-border bg-surface-muted/40 p-3 text-sm text-text-muted">
          One or two parent or guardian emails can be supplied with matching
          relationship fields.
        </div>
        <div className="rounded-lg border border-border bg-surface-muted/40 p-3 text-sm text-text-muted">
          Validation checks the template signature, version, headers, classes,
          dates, emails, and duplicates.
        </div>
      </div>
      <div
        className="mt-4 flex min-h-36 cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed border-border bg-surface-muted/30 p-4 text-center focus-within:ring-2 focus-within:ring-primary sm:mt-5 sm:min-h-48 sm:p-6"
        onDragOver={(event) => event.preventDefault()}
        onDrop={onDrop}
        onClick={() => fileInputRef.current?.click()}
        role="button"
        tabIndex={0}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ")
            fileInputRef.current?.click();
        }}
      >
        <UploadCloud className="h-9 w-9 text-primary" />
        <p className="mt-3 text-sm font-semibold text-text">
          {file ? file.name : "Drop the completed XLSX file here"}
        </p>
        <p className="mt-1 text-xs text-text-muted">
          {file ? formatBytes(file.size) : "or choose a file from your device"}
        </p>
        <input
          ref={fileInputRef}
          type="file"
          accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
          className="sr-only"
          onChange={(event) => setFile(event.target.files?.[0] || null)}
          aria-label="Choose student import file"
        />
      </div>
      {busy === "validate" ? (
        <div
          className="mt-4 rounded-2xl border border-primary/20 bg-primary-soft/35 px-4 py-4"
          role="status"
          aria-live="polite"
        >
          <div className="flex items-center justify-between gap-3 text-sm">
            <span className="font-semibold text-text">Validating file</span>
            <span className="font-bold text-primary">
              {validationProgress}%
            </span>
          </div>
          <div className="mt-3 h-2 overflow-hidden rounded-full bg-surface">
            <div
              className="h-full rounded-full bg-primary transition-[width] duration-500 ease-out"
              style={{ width: `${validationProgress}%` }}
            />
          </div>
          <p className="mt-2 text-xs leading-5 text-text-muted">
            Checking the template, rows, classes, dates, parent emails, and
            duplicate records.
          </p>
        </div>
      ) : null}
      <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:justify-between">
        <Button variant="outline" onClick={() => go("history")}>
          <History className="h-4 w-4" /> View history
        </Button>
        <div className="flex flex-col gap-2 sm:flex-row">
          {file && (
            <Button
              variant="ghost"
              onClick={() => setFile(null)}
              disabled={Boolean(busy)}
            >
              <X className="h-4 w-4" /> Remove file
            </Button>
          )}
          <Button onClick={handleValidate} disabled={!file || Boolean(busy)}>
            {busy === "validate" ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <FileSpreadsheet className="h-4 w-4" />
            )}
            {busy === "validate" ? "Validating..." : "Validate file"}
          </Button>
        </div>
      </div>
    </Card>
  );

  const renderValidation = () => {
    if (!currentJob)
      return (
        <EmptyState
          title="No validation job selected"
          description="Upload a file first, or choose a job from history."
        />
      );
    const hasErrors = Number(currentJob.failed_rows || 0) > 0;
    return (
      <div className="space-y-5">
        <Card className="p-3 sm:p-5">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <h2 className="text-lg font-semibold text-text">
                Validation Result
              </h2>
              <p className="mt-1 text-sm text-text-muted">
                {currentJob.original_filename}
              </p>
            </div>
            <JobStatusBadge job={currentJob} />
          </div>
          <div className="mt-4 grid grid-cols-2 gap-2 sm:gap-3 lg:grid-cols-4">
            <MetricCard label="Total rows" value={currentJob.total_rows} />
            <MetricCard
              label="Valid rows"
              value={currentJob.successful_rows}
              variant="success"
            />
            <MetricCard
              label="Rows with errors"
              value={currentJob.failed_rows}
              variant="error"
            />
            <MetricCard
              label="Warnings"
              value={currentJob.metadata_json?.warning_count || 0}
            />
          </div>
          <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:justify-end">
            {hasErrors ? (
              <Button onClick={() => go("upload")}>
                <UploadCloud className="h-4 w-4" /> Upload corrected file
              </Button>
            ) : (
              <Button onClick={() => go("review", currentJob.id)}>
                Continue to dry-run review
              </Button>
            )}
          </div>
        </Card>
        {hasErrors && renderErrors()}
      </div>
    );
  };

  const renderErrors = ({
    title = "Validation Errors",
    description = "Correct these rows and upload the file again.",
  } = {}) => (
    <Card className="p-3 sm:p-5">
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <h2 className="text-lg font-semibold text-text">{title}</h2>
          <p className="mt-1 text-sm text-text-muted">{description}</p>
        </div>
        <label className="relative block md:w-72">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted" />
          <input
            value={errorSearch}
            onChange={(event) => setErrorSearch(event.target.value)}
            className="w-full rounded-lg border border-border bg-surface py-2 pl-9 pr-3 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
            placeholder="Search errors"
            aria-label="Search validation errors"
          />
        </label>
        {currentJob?.id && (
          <Button
            variant="outline"
            onClick={handleDownloadErrors}
            disabled={Boolean(busy)}
          >
            {busy === "errors" ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Download className="h-4 w-4" />
            )}
            Download error report
          </Button>
        )}
      </div>
      {filteredErrors.length === 0 && (
        <div className="mt-4 rounded-lg border border-warning/40 bg-warning/10 p-3 text-sm text-text">
          This job is marked as failed, but no row-level error details were
          returned. Refresh the page; if it stays this way, check the import job
          error message in the backend.
        </div>
      )}
      <div className="mt-4 max-h-[min(24rem,58dvh)] overflow-auto rounded-xl border border-border sm:max-h-[420px]">
        <table className="min-w-[980px] w-full text-left text-sm">
          <thead className="sticky top-0 border-b border-border bg-surface text-xs uppercase text-text-muted">
            <tr>
              <th className="py-2 pl-3 pr-4">Row</th>
              <th className="py-2 pr-4">Student</th>
              <th className="py-2 pr-4">Column</th>
              <th className="py-2 pr-4">Code</th>
              <th className="py-2 pr-4">Message</th>
              <th className="py-2 pr-4">Suggested correction</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {filteredErrors.map((item) => (
              <tr key={item.id || `${item.row_number}-${item.error_code}`}>
                <td className="py-3 pl-3 pr-4 font-semibold">
                  {item.row_number}
                </td>
                <td className="py-3 pr-4">
                  {[
                    item.normalized_row?.first_name,
                    item.normalized_row?.last_name,
                  ]
                    .filter(Boolean)
                    .join(" ") || "--"}
                </td>
                <td className="py-3 pr-4">{item.field_name || "--"}</td>
                <td className="py-3 pr-4 font-mono text-xs">
                  {item.error_code || "--"}
                </td>
                <td className="py-3 pr-4 text-error">{item.error_message}</td>
                <td className="py-3 pr-4 text-text-muted">
                  {errorSuggestions[item.error_code] ||
                    "Review this value and match the template instructions."}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );

  const renderReview = () => {
    if (!currentJob)
      return (
        <EmptyState
          title="No dry run selected"
          description="Validate a file before reviewing the import."
        />
      );
    return (
      <Card className="p-3 sm:p-5">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h2 className="text-lg font-semibold text-text">Review Dry Run</h2>
            <p className="mt-1 text-sm text-text-muted">
              No student records have been created yet. Confirm only if this
              summary is correct.
            </p>
          </div>
          <JobStatusBadge job={currentJob} />
        </div>
        <div className="mt-4 grid grid-cols-2 gap-2 sm:gap-3 lg:grid-cols-4">
          <MetricCard
            label="Students to create"
            value={currentJob.successful_rows}
            variant="success"
          />
          <MetricCard
            label="Rows blocked"
            value={currentJob.failed_rows}
            variant="error"
          />
          <MetricCard
            label="Parent invitations expected"
            value={expectedParentInvitationCount}
          />
          <MetricCard label="Total rows" value={currentJob.total_rows} />
        </div>
        <div className="mt-5 flex flex-col gap-2 sm:flex-row sm:justify-between">
          <Button
            variant="outline"
            onClick={() => go("validate", currentJob.id)}
          >
            Back to validation
          </Button>
          <Button
            onClick={() => setConfirmOpen(true)}
            disabled={!canConfirmJob(currentJob) || Boolean(busy)}
          >
            Confirm and process {currentJob.successful_rows || 0} students
          </Button>
        </div>
      </Card>
    );
  };

  const renderProcess = () => {
    if (!currentJob)
      return (
        <EmptyState
          title="No processing job selected"
          description="Confirm a validated job to see progress and downloads."
        />
      );
    const failedRows = Number(currentJob.failed_rows || 0);
    const hasFailures = failedRows > 0;
    const terminal = isTerminalJob(currentJob);
    return (
      <div className="space-y-5">
        <Card className="p-3 sm:p-5">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <h2 className="text-lg font-semibold text-text">
                Processing and Results
              </h2>
              <p className="mt-1 text-sm text-text-muted">
                {currentJob.original_filename}
              </p>
            </div>
            <JobStatusBadge job={currentJob} />
          </div>
          {terminal && hasFailures && (
            <div className="mt-4 flex gap-3 rounded-lg border border-error/40 bg-error/10 p-3 text-sm text-text">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-error" />
              <div>
                <p className="font-semibold text-error">
                  {failedRows === Number(currentJob.total_rows || 0)
                    ? "No rows were imported."
                    : `${failedRows} row${failedRows === 1 ? "" : "s"} failed during import.`}
                </p>
                <p className="mt-1 text-text-muted">
                  Review the row details below, fix the spreadsheet data, then
                  upload a corrected file.
                </p>
              </div>
            </div>
          )}
          <div className="mt-4 h-3 overflow-hidden rounded-full bg-surface-muted">
            <div
              className="h-full rounded-full bg-primary"
              style={{
                width: `${percent(currentJob.processed_rows, currentJob.total_rows)}%`,
              }}
            />
          </div>
          <div className="mt-4 grid grid-cols-2 gap-2 sm:gap-3 lg:grid-cols-4">
            <MetricCard label="Processed" value={currentJob.processed_rows} />
            <MetricCard
              label="Created"
              value={currentJob.successful_rows}
              variant="success"
            />
            <MetricCard
              label="Failed"
              value={currentJob.failed_rows}
              variant="error"
            />
            <MetricCard
              label="Parent emails queued"
              value={actualParentInvitationsQueued}
            />
          </div>
          <div className="mt-4 grid grid-cols-2 gap-2 text-xs text-text-muted sm:gap-3 sm:text-sm lg:grid-cols-4">
            <span>Created: {formatDate(currentJob.created_at)}</span>
            <span>
              Started:{" "}
              {formatDate(
                currentJob.started_at || currentJob.metadata_json?.queued_at,
              )}
            </span>
            <span>Completed: {formatDate(currentJob.completed_at)}</span>
            <span>Updated: {formatDate(currentJob.updated_at)}</span>
          </div>
          <div className="mt-5 flex flex-col gap-2 sm:flex-row sm:justify-end">
            <Button variant="outline" onClick={() => go("upload")}>
              <UploadCloud className="h-4 w-4" /> Start another import
            </Button>
            {terminal && (
              <>
                <Button
                  variant="outline"
                  onClick={() => handleDownloadResult("spreadsheet")}
                  disabled={Boolean(busy)}
                >
                  {busy === "spreadsheet" ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Download className="h-4 w-4" />
                  )}
                  Download result spreadsheet
                </Button>
                <Button
                  variant="outline"
                  onClick={() => handleDownloadResult("slip")}
                  disabled={
                    Boolean(busy) ||
                    Number(currentJob.successful_rows || 0) === 0
                  }
                >
                  {busy === "slip" ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Printer className="h-4 w-4" />
                  )}
                  Download student access slips
                </Button>
              </>
            )}
          </div>
        </Card>
        {terminal &&
          hasFailures &&
          renderErrors({
            title: "Import Failures",
            description:
              "These rows were not created. The messages below come from the backend import job result.",
          })}
      </div>
    );
  };

  const renderHistory = () => (
    <Card className="p-3 sm:p-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-lg font-semibold text-text">Job History</h2>
          <p className="mt-1 text-sm text-text-muted">
            {jobsTotal} import job{jobsTotal === 1 ? "" : "s"} match the
            selected filters.
          </p>
        </div>
        <Button className="w-full sm:w-auto" onClick={() => go("upload")}>
          <UploadCloud className="h-4 w-4" /> New student import
        </Button>
      </div>
      <div className="mt-4 grid gap-3 md:grid-cols-[1fr_220px]">
        <label className="relative block">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted" />
          <input
            value={historySearch}
            onChange={(event) => { setHistorySkip(0); setHistorySearch(event.target.value); }}
            className="w-full rounded-lg border border-border bg-surface py-2 pl-9 pr-3 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
            placeholder="Search all import filenames"
            aria-label="Search import filenames"
          />
        </label>
        <select
          value={historyStatus}
          onChange={(event) => {
            const request = getStatusChangeHistoryRequest(event.target.value);
            setHistoryStatus(request.status);
            setHistorySkip(request.skip);
          }}
          className="input-base"
          aria-label="Filter import status"
        >
          {historyStatusOptions.map((option) => (
            <option key={option.value || "all"} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </div>
      {historyLoading && (
        <div className="mt-4 flex items-center gap-2 rounded-lg border border-border bg-surface-muted/40 p-3 text-sm text-text-muted">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading import history...
        </div>
      )}
      <div className="mt-4 grid max-h-[min(28rem,58dvh)] grid-cols-1 gap-2 overflow-y-auto pr-1 sm:max-h-[560px] sm:gap-3 lg:grid-cols-2 xl:grid-cols-1">
        {jobs.length === 0 && !historyLoading && (
          <EmptyState
            title="No imports found"
            description={historySearch || historyStatus ? "No import jobs match these filters." : "Student import jobs will appear here after validation."}
          />
        )}

        {filteredJobs.map((job) => (
          <div
            key={job.id}
            className="rounded-xl border border-border bg-surface p-3"
          >
            <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
              <button
                type="button"
                onClick={() => openHistoryJob(job.id)}
                className="min-w-0 text-left"
              >
                <p className="truncate text-sm font-semibold text-text">
                  {job.original_filename}
                </p>
                <p className="mt-1 text-xs text-text-muted">
                  {formatDate(job.created_at)} · {job.total_rows || 0} rows ·{" "}
                  {job.successful_rows || 0} successful · {job.failed_rows || 0}{" "}
                  failed
                </p>
                {!isStudentJob(job) && (
                  <p className="mt-1 text-xs font-semibold text-warning">
                    Historical import type - new imports are no longer
                    supported.
                  </p>
                )}
              </button>
              <div className="flex shrink-0 flex-wrap items-center gap-2">
                <JobStatusBadge job={job} />
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => openHistoryJob(job.id)}
                >
                  View
                </Button>
                {canDeleteJob(job) && (
                  <Button
                    variant="danger"
                    size="sm"
                    onClick={() => setDeleteJob(job)}
                    aria-label={`Delete ${job.original_filename}`}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
      <div className="mt-4 flex flex-col gap-2 text-sm text-text-muted sm:flex-row sm:items-center sm:justify-between">
        <span>
          Showing {jobs.length ? historySkip + 1 : 0}-
          {historySkip + jobs.length} of {jobsTotal}
        </span>
        <div className="grid grid-cols-2 gap-2 sm:flex">
          <Button
            variant="outline"
            size="sm"
            disabled={historySkip === 0 || historyLoading}
            onClick={() =>
              setHistorySkip(
                getPreviousHistoryRequest(historySkip, historyStatus).skip,
              )
            }
          >
            Previous
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={historySkip + jobs.length >= jobsTotal || historyLoading}
            onClick={() =>
              setHistorySkip(
                getNextHistoryRequest(historySkip, historyStatus).skip,
              )
            }
          >
            {HISTORY_NEXT_LABEL}
          </Button>
        </div>
      </div>
    </Card>
  );

  const content = {
    upload: renderUpload,
    validate: renderValidation,
    review: renderReview,
    process: renderProcess,
    history: renderHistory,
  }[displayStep]();

  return (
    <DashboardLayout
      role="admin"
      title="Import Students"
      description="Download the official template, validate the upload, review the dry run, then process in the background."
      actions={
        <Button
          variant="outline"
          className="manual-refresh-action"
          onClick={handleRefresh}
          disabled={Boolean(busy)}
        >
          <RefreshCw className="h-4 w-4" /> Refresh
        </Button>
      }
    >
      <div ref={workspaceRef} className="space-y-4 scroll-mt-4 sm:space-y-5">
        {step !== "history" && (
          <StepHeader step={step} currentJob={currentJob} onNavigate={go} />
        )}
        <div
          key={displayStep}
          className={[
            "transform-gpu transition duration-200 ease-out",
            transitionState === "leaving"
              ? "translate-y-2 opacity-0"
              : "translate-y-0 opacity-100",
          ].join(" ")}
        >
          {content}
        </div>
      </div>

      <Modal
        open={confirmOpen}
        title={`Process ${currentJob?.successful_rows || 0} students`}
        description="This queues the import for background processing. The uploaded file cannot be changed after confirmation."
        onClose={() => setConfirmOpen(false)}
        footer={
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button
              variant="outline"
              onClick={() => setConfirmOpen(false)}
              disabled={Boolean(busy)}
            >
              Cancel
            </Button>
            <Button onClick={handleConfirm} disabled={Boolean(busy)}>
              {busy === "confirm" ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <CheckCircle2 className="h-4 w-4" />
              )}
              Confirm and process {currentJob?.successful_rows || 0} students
            </Button>
          </div>
        }
      >
        <div className="space-y-3 text-sm text-text-muted">
          <p>
            Students to create:{" "}
            <strong className="text-text">
              {currentJob?.successful_rows || 0}
            </strong>
          </p>
          <p>
            Parent invitation emails expected:{" "}
            <strong className="text-text">
              {expectedParentInvitationCount}
            </strong>
          </p>
          <p>
            Processing happens in the bulk-import worker. This page updates when
            persisted progress changes.
          </p>
        </div>
      </Modal>

      <Modal
        open={Boolean(deleteJob)}
        title="Delete import history?"
        description="This removes the selected non-active job and its row-level history from this tenant view."
        onClose={() => setDeleteJob(null)}
        footer={
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button
              variant="outline"
              onClick={() => setDeleteJob(null)}
              disabled={Boolean(busy)}
            >
              Cancel
            </Button>
            <Button
              variant="danger"
              onClick={handleDeleteJob}
              disabled={Boolean(busy)}
            >
              {busy === "delete" ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Trash2 className="h-4 w-4" />
              )}
              Delete history entry
            </Button>
          </div>
        }
      >
        <p className="text-sm text-text-muted">
          {deleteJob?.original_filename}
        </p>
      </Modal>

      <Modal
        open={Boolean(criticalImportError)}
        title={criticalImportError?.title || "Import blocked"}
        description={criticalImportError?.message || ""}
        onClose={() => setCriticalImportError(null)}
        placement="center"
        footer={
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button
              variant="outline"
              onClick={() => setCriticalImportError(null)}
            >
              Stay here
            </Button>
            <Button
              onClick={() => {
                setCriticalImportError(null);
                setFile(null);
                navigateSmooth("/admin/imports/upload");
              }}
            >
              <UploadCloud className="h-4 w-4" />
              Upload another file
            </Button>
          </div>
        }
      >
        <div className="flex gap-3 rounded-2xl border border-error/30 bg-error-soft px-4 py-4 text-sm leading-6 text-error">
          <AlertCircle className="mt-0.5 h-5 w-5 shrink-0" />
          <div>
            <p className="font-semibold">
              The file cannot continue in this import flow.
            </p>
            <p className="mt-1 text-error/85">
              Review the message above, then upload a workbook that has not
              already been imported.
            </p>
          </div>
        </div>
      </Modal>
    </DashboardLayout>
  );
}

export default BulkImportPage;
