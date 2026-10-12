import {
  AlertCircle,
  ArrowLeft,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ClipboardCheck,
  Clock3,
  Copy,
  FileSearch,
  RefreshCw,
  Search,
  ShieldAlert,
  SlidersHorizontal,
  Users,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import DashboardLayout from "../../components/layout/DashboardLayout";
import LoadingState from "../../components/shared/LoadingState";
import Badge from "../../components/ui/Badge";
import Button from "../../components/ui/Button";
import Card from "../../components/ui/Card";
import Modal from "../../components/ui/Modal";
import { useToast } from "../../hooks/useToast";
import { getErrorMessage } from "../../services/api";
import { cbtResultLedgerService } from "../../services/cbtResultLedgerService";
import { superadminService } from "../../services/superadmin.service";
import {
  buildResultLedgerQuery,
  RESULT_ITEM_OUTCOMES,
  ResultLedgerFilterError,
  summarizeResultBatches,
} from "./resultLedger";

const PAGE_SIZE = 25;
const ITEM_PAGE_SIZE = 50;

const EMPTY_FILTERS = {
  status: "",
  sourceExamId: "",
  ingestionReference: "",
  academicSessionId: "",
  academicTermId: "",
  academicLevelId: "",
  curriculumSubjectId: "",
  assessmentComponentId: "",
  serverId: "",
  tenantId: "",
  createdFrom: "",
  createdTo: "",
};

const EMPTY_FILTER_OPTIONS = {
  exams: [],
  sessions: [],
  terms: [],
  academicLevels: [],
  subjects: [],
  assessmentComponents: [],
  servers: [],
  statuses: [],
};

const BATCH_STATUS_META = {
  processing: { label: "Processing", variant: "info", icon: Clock3 },
  completed: { label: "Completed", variant: "success", icon: CheckCircle2 },
  completed_with_rejections: {
    label: "Completed with rejections",
    variant: "warning",
    icon: ShieldAlert,
  },
  rejected: { label: "Rejected", variant: "error", icon: AlertCircle },
  failed: { label: "Failed", variant: "error", icon: AlertCircle },
};

const ITEM_OUTCOME_META = {
  applied: { label: "Applied", variant: "success" },
  unchanged: { label: "Unchanged", variant: "default" },
  rejected: { label: "Rejected", variant: "error" },
};

const humanize = (value) =>
  String(value || "")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());

const formatDateTime = (value) => {
  if (!value) return "--";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "--" : date.toLocaleString();
};

const formatDate = (value) => {
  if (!value) return "--";
  const date = new Date(`${value}T00:00:00`);
  return Number.isNaN(date.getTime())
    ? "--"
    : date.toLocaleDateString(undefined, {
        day: "numeric",
        month: "short",
        year: "numeric",
      });
};

const formatScore = (value) => {
  if (value === null || value === undefined || value === "") return "--";
  const score = Number(value);
  return Number.isFinite(score) ? score.toLocaleString(undefined, { maximumFractionDigits: 2 }) : String(value);
};

const outcomeExplanation = (outcome) => {
  if (outcome === "applied") {
    return "The incoming CBT score was written into the canonical Weave result.";
  }
  if (outcome === "unchanged") {
    return "The same score already existed, so no mutation was necessary.";
  }
  return "The CBT score was not applied.";
};

const firstText = (record, keys, fallback = "") => {
  for (const key of keys) {
    const value = String(record?.[key] || "").trim();
    if (value) return value;
  }
  return fallback;
};

const firstId = (record, keys) => {
  for (const key of keys) {
    const value = String(record?.[key] || "").trim();
    if (value) return value;
  }
  return "";
};

const normalizeOptions = (sources, idKeys, labelKeys) =>
  (Array.isArray(sources) ? sources : [])
    .map((source) => {
      const id = firstId(source, idKeys);
      const label = firstText(source, labelKeys);
      return id && label ? { id, label } : null;
    })
    .filter(Boolean);

const normalizeFilterOptions = (response) => {
  const provided = response || {};
  return {
    exams: normalizeOptions(
      provided.exams,
      ["id", "source_exam_id"],
      ["title", "source_exam_title", "label"],
    ),
    sessions: normalizeOptions(
      provided.sessions,
      ["id", "academic_session_id"],
      ["name", "academic_session_name", "label"],
    ),
    terms: normalizeOptions(
      provided.terms,
      ["id", "academic_term_id"],
      ["name", "academic_term_name", "label"],
    ),
    academicLevels: normalizeOptions(
      provided.levels,
      ["id", "academic_level_id"],
      ["name", "academic_level_name", "label"],
    ),
    subjects: normalizeOptions(
      provided.subjects,
      ["id", "curriculum_subject_id"],
      ["name", "subject_name", "label"],
    ),
    assessmentComponents: normalizeOptions(
      provided.assessment_components,
      ["id", "assessment_component_id"],
      ["name", "assessment_component_name", "label"],
    ),
    servers: normalizeOptions(
      provided.servers,
      ["id", "cbt_server_id"],
      ["name", "server_name", "label"],
    ),
    statuses: Array.isArray(provided.statuses)
      ? provided.statuses.filter(Boolean).map(String)
      : [],
  };
};

const batchPresentation = (batch, scopeName = "") => {
  const level = firstText(batch, ["academic_level_name"], "Academic level");
  const subject = firstText(
    batch,
    ["subject_name", "curriculum_subject_name"],
    "Subject",
  );
  const component = firstText(
    batch,
    ["assessment_component_name", "component_name"],
    "Assessment component",
  );
  const term = firstText(batch, ["academic_term_name"], "Academic term");
  return {
    title: firstText(batch, ["source_exam_title"], "Exam title unavailable"),
    reference: firstText(
      batch,
      ["ingestion_reference"],
      "Reference unavailable",
    ),
    session: firstText(batch, ["academic_session_name"], "Academic session"),
    term,
    level,
    subject,
    component,
    server: firstText(batch, ["server_name", "cbt_server_name"], scopeName || "CBT server"),
    tenant: firstText(batch, ["tenant_name", "school_name"], scopeName || "School"),
  };
};

function StatusBadge({ status }) {
  const meta = BATCH_STATUS_META[status] || {
    label: humanize(status || "unknown"),
    variant: "default",
    icon: AlertCircle,
  };
  const Icon = meta.icon;
  return (
    <Badge variant={meta.variant} title={meta.label}>
      <Icon className="h-3.5 w-3.5" />
      {meta.label}
    </Badge>
  );
}

function OutcomeBadge({ outcome }) {
  const meta = ITEM_OUTCOME_META[outcome] || {
    label: humanize(outcome || "unknown"),
    variant: "default",
  };
  return <Badge variant={meta.variant}>{meta.label}</Badge>;
}

function MetricCard({ icon: Icon, label, value, hint, tone = "primary" }) {
  const tones = {
    primary: "bg-primary-soft text-primary",
    success: "bg-success-soft text-success",
    warning: "bg-warning-soft text-warning",
    neutral: "bg-surface-muted text-text-muted",
  };
  return (
    <Card className="min-w-0 p-4 shadow-sm sm:p-5">
      <div className={`grid h-10 w-10 place-items-center rounded-xl ${tones[tone]}`}>
        <Icon className="h-5 w-5" />
      </div>
      <p className="mt-4 text-xs font-semibold uppercase tracking-wide text-text-muted">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-text">{Number(value || 0).toLocaleString()}</p>
      <p className="mt-1 text-xs text-text-faint">{hint}</p>
    </Card>
  );
}

function TechnicalIdentifier({ label, value, onCopy }) {
  if (!value) return null;
  return (
    <div className="flex min-w-0 items-center justify-between gap-3 rounded-lg bg-surface-muted/60 px-3 py-2">
      <div className="min-w-0">
        <p className="text-[10px] font-bold uppercase tracking-wider text-text-faint">{label}</p>
        <code className="mt-1 block truncate text-xs text-text" title={String(value)}>{value}</code>
      </div>
      <Button type="button" size="icon" variant="ghost" className="h-8 w-8 shrink-0" onClick={() => onCopy(value, label)} aria-label={`Copy ${label}`}>
        <Copy className="h-3.5 w-3.5" />
      </Button>
    </div>
  );
}

function DetailField({ label, value }) {
  return (
    <div className="flex min-w-0 items-start gap-3 border-b border-border/60 py-2.5">
      <dt className="w-28 shrink-0 text-xs font-medium text-text-muted sm:w-32">{label}</dt>
      <dd className="min-w-0 flex-1 break-words text-sm font-medium text-text">
        {value || "--"}
      </dd>
    </div>
  );
}

function ErrorNotice({ children }) {
  return (
    <div className="flex items-start gap-3 rounded-xl border border-error/30 bg-error-soft px-4 py-3 text-sm text-error">
      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
      <span>{children}</span>
    </div>
  );
}

export default function CBTResultLedgerPage({ role = "admin" }) {
  const navigate = useNavigate();
  const { showError, showSuccess } = useToast();
  const isSuperadmin = role === "superadmin";
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [appliedFilters, setAppliedFilters] = useState(EMPTY_FILTERS);
  const [batches, setBatches] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [lookups, setLookups] = useState([]);
  const [lookupError, setLookupError] = useState("");
  const [filterOptions, setFilterOptions] = useState(EMPTY_FILTER_OPTIONS);
  const [filterOptionsLoading, setFilterOptionsLoading] = useState(false);
  const [filterOptionsError, setFilterOptionsError] = useState("");
  const [selectedBatchId, setSelectedBatchId] = useState("");
  const [batchDetail, setBatchDetail] = useState(null);
  const [detailItems, setDetailItems] = useState([]);
  const [detailTotal, setDetailTotal] = useState(0);
  const [detailPage, setDetailPage] = useState(1);
  const [itemOutcome, setItemOutcome] = useState("");
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const listRequestRef = useRef(0);
  const detailRequestRef = useRef(0);

  const roleApi = useMemo(
    () =>
      isSuperadmin
        ? {
            list: cbtResultLedgerService.listSuperadminBatches,
            get: cbtResultLedgerService.getSuperadminBatch,
            listItems: cbtResultLedgerService.listSuperadminBatchItems,
            filterOptions: cbtResultLedgerService.getFilterOptions,
          }
        : {
            list: cbtResultLedgerService.listTenantBatches,
            get: cbtResultLedgerService.getTenantBatch,
            listItems: cbtResultLedgerService.listTenantBatchItems,
            filterOptions: cbtResultLedgerService.getFilterOptions,
          },
    [isSuperadmin],
  );

  const lookupNames = useMemo(
    () =>
      new Map(
        lookups.map((item) => [
          String(item.id),
          isSuperadmin
            ? item.school_name || item.email || "School"
            : item.name || "CBT server",
        ]),
      ),
    [isSuperadmin, lookups],
  );

  const loadBatches = useCallback(async () => {
    const requestId = listRequestRef.current + 1;
    listRequestRef.current = requestId;
    setLoading(true);
    setError("");

    try {
      const query = buildResultLedgerQuery({
        filters: appliedFilters,
        page,
        pageSize: PAGE_SIZE,
        role,
      });
      const response = await roleApi.list(query);
      if (requestId !== listRequestRef.current) return;
      setBatches(Array.isArray(response?.items) ? response.items : []);
      setTotal(Number(response?.total || 0));
    } catch (requestError) {
      if (requestId !== listRequestRef.current) return;
      setBatches([]);
      setTotal(0);
      setError(
        requestError instanceof ResultLedgerFilterError
          ? requestError.message
          : getErrorMessage(requestError, "Could not load the CBT result ledger."),
      );
    } finally {
      if (requestId === listRequestRef.current) setLoading(false);
    }
  }, [appliedFilters, page, role, roleApi]);

  useEffect(() => {
    const timeoutId = window.setTimeout(loadBatches, 0);
    return () => window.clearTimeout(timeoutId);
  }, [loadBatches]);

  useEffect(() => {
    let active = true;
    const loadLookups = async () => {
      if (!isSuperadmin) return;
      try {
        const response = await superadminService.getTenants(0, 100);
        if (!active) return;
        setLookups(Array.isArray(response) ? response : []);
      } catch (requestError) {
        if (!active) return;
        setLookupError(
          getErrorMessage(
            requestError,
            "Tenant names could not be loaded. The platform ledger is still available.",
          ),
        );
      }
    };
    const timeoutId = window.setTimeout(loadLookups, 0);
    return () => {
      active = false;
      window.clearTimeout(timeoutId);
    };
  }, [isSuperadmin]);

  useEffect(() => {
    if (isSuperadmin && !filters.tenantId) return undefined;
    let active = true;
    const loadFilterOptions = async () => {
      setFilterOptionsLoading(true);
      setFilterOptionsError("");
      try {
        const response = await roleApi.filterOptions(
          isSuperadmin ? { tenant_id: filters.tenantId } : {},
        );
        if (active) setFilterOptions(normalizeFilterOptions(response));
      } catch (requestError) {
        if (!active) return;
        setFilterOptions(EMPTY_FILTER_OPTIONS);
        setFilterOptionsError(
          getErrorMessage(
            requestError,
            "Audit filter choices are temporarily unavailable. Status and date filters remain available.",
          ),
        );
      } finally {
        if (active) setFilterOptionsLoading(false);
      }
    };
    const timeoutId = window.setTimeout(loadFilterOptions, 0);
    return () => {
      active = false;
      window.clearTimeout(timeoutId);
    };
  }, [filters.tenantId, isSuperadmin, roleApi]);

  const loadDetail = useCallback(
    async (batchRecordId, nextPage = 1, nextOutcome = "") => {
      if (!batchRecordId) return;
      const requestId = detailRequestRef.current + 1;
      detailRequestRef.current = requestId;
      setDetailLoading(true);
      setDetailError("");
      try {
        const [detailResponse, itemsResponse] = await Promise.all([
          roleApi.get(batchRecordId),
          roleApi.listItems(batchRecordId, {
            skip: (nextPage - 1) * ITEM_PAGE_SIZE,
            limit: ITEM_PAGE_SIZE,
            ...(nextOutcome ? { outcome: nextOutcome } : {}),
          }),
        ]);
        if (requestId !== detailRequestRef.current) return;
        setBatchDetail(detailResponse);
        setDetailItems(Array.isArray(itemsResponse?.items) ? itemsResponse.items : []);
        setDetailTotal(Number(itemsResponse?.total || 0));
        setDetailPage(nextPage);
      } catch (requestError) {
        if (requestId !== detailRequestRef.current) return;
        setDetailError(getErrorMessage(requestError, "Could not load ingestion details."));
      } finally {
        if (requestId === detailRequestRef.current) setDetailLoading(false);
      }
    },
    [roleApi],
  );

  const openBatch = (batchRecordId) => {
    setSelectedBatchId(batchRecordId);
    setBatchDetail(null);
    setDetailItems([]);
    setDetailTotal(0);
    setDetailPage(1);
    setItemOutcome("");
    loadDetail(batchRecordId, 1, "");
  };

  const closeBatch = () => {
    detailRequestRef.current += 1;
    setSelectedBatchId("");
    setBatchDetail(null);
    setDetailItems([]);
    setDetailError("");
  };

  const applyFilters = (event) => {
    event.preventDefault();
    try {
      buildResultLedgerQuery({ filters, page: 1, pageSize: PAGE_SIZE, role });
      setError("");
      setPage(1);
      setAppliedFilters({ ...filters });
      setFiltersOpen(false);
    } catch (filterError) {
      setError(filterError.message);
    }
  };

  const clearFilters = () => {
    setFilters(EMPTY_FILTERS);
    setAppliedFilters(EMPTY_FILTERS);
    setPage(1);
    setError("");
  };

  const updateFilter = (key) => (event) =>
    setFilters((current) => ({ ...current, [key]: event.target.value }));

  const updateTenant = (event) => {
    const tenantId = event.target.value;
    setFilterOptions(EMPTY_FILTER_OPTIONS);
    setFilters((current) => ({
      ...EMPTY_FILTERS,
      tenantId,
      status: current.status,
      createdFrom: current.createdFrom,
      createdTo: current.createdTo,
    }));
  };

  const copyTechnicalValue = async (value, label) => {
    try {
      await navigator.clipboard.writeText(String(value));
      showSuccess(`${label} copied.`);
    } catch {
      showError(`Could not copy ${label.toLowerCase()}.`);
    }
  };

  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const detailPageCount = Math.max(1, Math.ceil(detailTotal / ITEM_PAGE_SIZE));
  const summary = summarizeResultBatches(batches, total);
  const activeFilterCount = Object.values(appliedFilters).filter(Boolean).length;
  const selectedScopeName = batchDetail
    ? lookupNames.get(
        String(isSuperadmin ? batchDetail.tenant_id : batchDetail.cbt_server_id),
      )
    : "";
  const detailPresentation = batchDetail
    ? batchPresentation(batchDetail, selectedScopeName)
    : null;

  return (
    <DashboardLayout
      role={role}
      title={isSuperadmin ? "CBT Result Operations" : "CBT Result Ledger"}
    >
      <div className="space-y-5">
        <div className="space-y-3">
          <div className={`flex min-h-9 items-center gap-3 ${isSuperadmin ? "justify-end" : "justify-between"}`}>
            {!isSuperadmin ? (
              <button
                type="button"
                onClick={() => navigate("/admin/cbt")}
                className="inline-flex items-center gap-2 text-sm font-semibold text-text-muted transition hover:text-primary"
              >
                <ArrowLeft className="h-4 w-4" />
                CBT Servers
              </button>
            ) : null}
            <Button
              size="sm"
              variant="outline"
              onClick={loadBatches}
              disabled={loading}
              aria-label="Refresh CBT result imports"
              className="shrink-0"
            >
              <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
              <span className="hidden sm:inline">Refresh</span>
            </Button>
          </div>
          <div>
            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-text-faint">
              <ClipboardCheck className="h-4 w-4" />
              {isSuperadmin ? "Platform operations" : "CBT operations"}
            </div>
            <h1 className="mt-2 text-[1.65rem] font-semibold tracking-tight text-text">
              {isSuperadmin ? "CBT Result Operations" : "CBT Result Ledger"}
            </h1>
            <p className="mt-1 max-w-3xl text-sm leading-6 text-text-muted">
              {isSuperadmin
                ? "Investigate result ingestion across tenants, isolate failed batches, and inspect immutable student-level decisions."
                : "Track every result batch received from your paired servers and inspect exactly which scores were applied, unchanged, or rejected."}
            </p>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <MetricCard icon={ClipboardCheck} label="Matching batches" value={summary.total} hint="Across all matching pages" />
          <MetricCard icon={Users} label="Scores received" value={summary.received} hint="Visible page" tone="neutral" />
          <MetricCard icon={CheckCircle2} label="Scores applied" value={summary.applied} hint="Visible page" tone="success" />
          <MetricCard icon={ShieldAlert} label="Scores rejected" value={summary.rejected} hint="Visible page" tone="warning" />
        </div>

        <Card className="overflow-hidden p-0 shadow-sm">
          <form onSubmit={applyFilters}>
            <button
              type="button"
              className="flex w-full items-center justify-between gap-4 px-4 py-3.5 text-left transition hover:bg-surface-muted/35 sm:px-5"
              aria-expanded={filtersOpen}
              aria-controls="cbt-ledger-filters"
              onClick={() => setFiltersOpen((open) => !open)}
            >
              <span className="flex min-w-0 items-center gap-3">
                <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-surface-muted text-text-muted">
                  <SlidersHorizontal className="h-4 w-4" />
                </span>
                <span className="min-w-0">
                  <span className="block text-sm font-semibold text-text">Filters</span>
                  <span className="block truncate text-xs font-normal text-text-muted">
                    {activeFilterCount
                      ? `${activeFilterCount} ${activeFilterCount === 1 ? "filter" : "filters"} active`
                      : "Refine the ingestion batches shown below"}
                  </span>
                </span>
              </span>
              <ChevronDown
                className={`h-4 w-4 shrink-0 text-text-muted transition-transform ${filtersOpen ? "rotate-180" : ""}`}
              />
            </button>

            {filtersOpen ? (
              <div id="cbt-ledger-filters" className="space-y-4 border-t border-border/70 px-4 py-4 sm:px-5">
                <div className="grid gap-x-4 gap-y-3 sm:grid-cols-2 xl:grid-cols-3">
              {isSuperadmin ? (
                <label className="text-xs font-semibold text-text-muted">
                  School
                  <select
                    className="input-base mt-1.5 w-full text-sm"
                    value={filters.tenantId}
                    onChange={updateTenant}
                  >
                    <option value="">All schools</option>
                    {lookups.map((item) => (
                      <option key={item.id} value={item.id}>{item.school_name || item.email || "School"}</option>
                    ))}
                  </select>
                </label>
              ) : null}
              <label className="text-xs font-semibold text-text-muted">
                Exam
                <select
                  className="input-base mt-1.5 w-full text-sm"
                  value={filters.sourceExamId}
                  onChange={updateFilter("sourceExamId")}
                  disabled={filterOptionsLoading}
                >
                  <option value="">All exams</option>
                  {filterOptions.exams.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}
                </select>
              </label>
              <label className="text-xs font-semibold text-text-muted">
                Academic session
                <select className="input-base mt-1.5 w-full text-sm" value={filters.academicSessionId} onChange={updateFilter("academicSessionId")} disabled={filterOptionsLoading}>
                  <option value="">All sessions</option>
                  {filterOptions.sessions.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}
                </select>
              </label>
              <label className="text-xs font-semibold text-text-muted">
                Academic term
                <select className="input-base mt-1.5 w-full text-sm" value={filters.academicTermId} onChange={updateFilter("academicTermId")} disabled={filterOptionsLoading}>
                  <option value="">All terms</option>
                  {filterOptions.terms.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}
                </select>
              </label>
              <label className="text-xs font-semibold text-text-muted">
                Academic level
                <select className="input-base mt-1.5 w-full text-sm" value={filters.academicLevelId} onChange={updateFilter("academicLevelId")} disabled={filterOptionsLoading}>
                  <option value="">All levels</option>
                  {filterOptions.academicLevels.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}
                </select>
              </label>
              <label className="text-xs font-semibold text-text-muted">
                Subject
                <select className="input-base mt-1.5 w-full text-sm" value={filters.curriculumSubjectId} onChange={updateFilter("curriculumSubjectId")} disabled={filterOptionsLoading}>
                  <option value="">All subjects</option>
                  {filterOptions.subjects.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}
                </select>
              </label>
              <label className="text-xs font-semibold text-text-muted">
                Assessment component
                <select className="input-base mt-1.5 w-full text-sm" value={filters.assessmentComponentId} onChange={updateFilter("assessmentComponentId")} disabled={filterOptionsLoading}>
                  <option value="">All components</option>
                  {filterOptions.assessmentComponents.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}
                </select>
              </label>
              <label className="text-xs font-semibold text-text-muted">
                CBT server
                <select className="input-base mt-1.5 w-full text-sm" value={filters.serverId} onChange={updateFilter("serverId")} disabled={filterOptionsLoading}>
                  <option value="">All servers</option>
                  {filterOptions.servers.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}
                </select>
              </label>
              <label className="text-xs font-semibold text-text-muted">
                Status
                <select className="input-base mt-1.5 w-full text-sm" value={filters.status} onChange={updateFilter("status")} disabled={filterOptionsLoading}>
                  <option value="">All statuses</option>
                  {filterOptions.statuses.map((status) => <option key={status} value={status}>{humanize(status)}</option>)}
                </select>
              </label>
              <label className="text-xs font-semibold text-text-muted">
                Batch reference
                <input type="search" className="input-base mt-1.5 w-full text-sm" value={filters.ingestionReference} onChange={updateFilter("ingestionReference")} placeholder="e.g. CBT-2026-000184" />
              </label>
              <label className="text-xs font-semibold text-text-muted">
                Imported from
                <input type="date" className="input-base mt-1.5 w-full text-sm" value={filters.createdFrom} onChange={updateFilter("createdFrom")} />
              </label>
              <label className="text-xs font-semibold text-text-muted">
                Imported to
                <input type="date" className="input-base mt-1.5 w-full text-sm" value={filters.createdTo} onChange={updateFilter("createdTo")} />
              </label>
                </div>
                {filterOptionsError ? <p className="text-xs text-warning">{filterOptionsError}</p> : null}
                {isSuperadmin && !filters.tenantId ? (
                  <p className="text-xs text-text-muted">Choose a school to load its tenant-scoped exam and academic filter choices.</p>
                ) : null}
                <div className="flex flex-wrap justify-end gap-2 border-t border-border/70 pt-4">
                  <Button type="button" variant="ghost" onClick={clearFilters} disabled={loading}>Clear</Button>
                  <Button type="submit" disabled={loading}>
                    <Search className="h-4 w-4" />
                    Apply filters
                  </Button>
                </div>
              </div>
            ) : null}
          </form>
        </Card>

        {lookupError ? (
          <div className="rounded-xl border border-warning/30 bg-warning-soft px-4 py-3 text-sm text-warning">{lookupError}</div>
        ) : null}
        {error ? <ErrorNotice>{error}</ErrorNotice> : null}

        <Card className="overflow-hidden p-0 shadow-sm">
          <div className="flex flex-col gap-1 border-b border-border px-4 py-4 sm:px-5">
            <h2 className="text-base font-semibold text-text">Ingestion batches</h2>
            <p className="text-xs text-text-muted">Newest evidence appears first. Select a batch to inspect its student score decisions.</p>
          </div>
          {loading ? (
            <LoadingState label="Loading CBT result ledger..." />
          ) : batches.length === 0 ? (
            <div className="flex min-h-56 flex-col items-center justify-center px-6 py-10 text-center">
              <span className="grid h-12 w-12 place-items-center rounded-2xl bg-primary-soft text-primary"><FileSearch className="h-5 w-5" /></span>
              <h3 className="mt-4 text-base font-semibold text-text">No ingestion batches found</h3>
              <p className="mt-1 max-w-lg text-sm text-text-muted">No CBT result evidence matches these filters. Clear the filters or wait for a paired server to submit results.</p>
            </div>
          ) : (
            <>
              <div className="hidden overflow-x-auto md:block">
                <table className="w-full min-w-[1080px] text-left text-sm">
                  <thead className="bg-surface-muted/55 text-[11px] uppercase tracking-wider text-text-faint">
                    <tr>
                      <th className="px-5 py-3 font-bold">Exam import</th>
                      <th className="px-4 py-3 font-bold">Academic context</th>
                      <th className="px-4 py-3 font-bold">Source</th>
                      <th className="px-4 py-3 font-bold">Processing counts</th>
                      <th className="px-4 py-3 font-bold">Status</th>
                      <th className="px-5 py-3 text-right font-bold">Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border/70">
                    {batches.map((batch) => {
                      const scopeId = isSuperadmin ? batch.tenant_id : batch.cbt_server_id;
                      const display = batchPresentation(
                        batch,
                        lookupNames.get(String(scopeId)),
                      );
                      return (
                        <tr key={batch.id} className="hover:bg-surface-muted/25">
                          <td className="max-w-[280px] px-5 py-4">
                            <p className="font-semibold text-text">{display.title}</p>
                            <p className="mt-1 text-xs font-medium text-primary">{display.reference}</p>
                          </td>
                          <td className="max-w-[260px] px-4 py-4">
                            <p className="font-medium text-text">{display.level} · {display.subject} · {display.component}</p>
                            <p className="mt-1 text-xs text-text-muted">{display.term} · {display.session}</p>
                          </td>
                          <td className="max-w-[210px] px-4 py-4">
                            {isSuperadmin ? <p className="font-medium text-text">{display.tenant}</p> : null}
                            <p className={isSuperadmin ? "mt-1 text-xs text-text-muted" : "font-medium text-text"}>{display.server}</p>
                            <p className="mt-1 text-xs text-text-faint">Exam date: {formatDate(batch.exam_date)}</p>
                          </td>
                          <td className="px-4 py-4 text-xs">
                            <p><span className="font-semibold text-text">{batch.received_count}</span> received</p>
                            <p className="mt-1 text-success"><span className="font-semibold">{batch.applied_count}</span> applied · <span className="font-semibold">{batch.unchanged_count}</span> unchanged</p>
                            <p className="mt-1 text-error"><span className="font-semibold">{batch.rejected_count}</span> rejected</p>
                          </td>
                          <td className="px-4 py-4"><StatusBadge status={batch.status} /><p className="mt-2 text-xs text-text-muted">{formatDateTime(batch.processed_at || batch.created_at)}</p></td>
                          <td className="px-5 py-4 text-right"><Button size="sm" variant="outline" onClick={() => openBatch(batch.id)}>Review</Button></td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <div className="divide-y divide-border md:hidden">
                {batches.map((batch) => {
                  const scopeId = isSuperadmin ? batch.tenant_id : batch.cbt_server_id;
                  const display = batchPresentation(
                    batch,
                    lookupNames.get(String(scopeId)),
                  );
                  return (
                    <button key={batch.id} type="button" onClick={() => openBatch(batch.id)} className="w-full px-4 py-4 text-left transition hover:bg-surface-muted/30">
                      <div className="flex items-start justify-between gap-3"><div className="min-w-0"><p className="font-semibold text-text">{display.title}</p><p className="mt-1 text-xs font-medium text-primary">{display.reference}</p></div><StatusBadge status={batch.status} /></div>
                      <p className="mt-3 text-xs text-text-muted">{display.level} · {display.subject} · {display.component}</p>
                      <p className="mt-1 text-xs text-text-muted">{display.term} · {display.session}</p>
                      <p className="mt-2 text-xs text-text-faint">{isSuperadmin ? `${display.tenant} · ` : ""}{display.server} · {formatDate(batch.exam_date)}</p>
                      <div className="mt-4 grid grid-cols-4 gap-2 text-center"><div className="rounded-lg bg-surface-muted/60 px-1 py-2"><p className="text-[9px] uppercase text-text-faint">Received</p><p className="font-semibold text-text">{batch.received_count}</p></div><div className="rounded-lg bg-success-soft px-1 py-2"><p className="text-[9px] uppercase text-success">Applied</p><p className="font-semibold text-success">{batch.applied_count}</p></div><div className="rounded-lg bg-surface-muted/60 px-1 py-2"><p className="text-[9px] uppercase text-text-faint">Unchanged</p><p className="font-semibold text-text">{batch.unchanged_count}</p></div><div className="rounded-lg bg-error-soft px-1 py-2"><p className="text-[9px] uppercase text-error">Rejected</p><p className="font-semibold text-error">{batch.rejected_count}</p></div></div>
                      <p className="mt-3 text-xs text-text-faint">Processed {formatDateTime(batch.processed_at || batch.created_at)}</p>
                    </button>
                  );
                })}
              </div>
            </>
          )}
          <div className="flex flex-col gap-3 border-t border-border px-4 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-5">
            <p className="text-xs text-text-muted">Page {page} of {pageCount} · {total.toLocaleString()} matching batches</p>
            <div className="flex gap-2">
              <Button size="sm" variant="outline" disabled={page <= 1 || loading} onClick={() => setPage((current) => Math.max(1, current - 1))}><ChevronLeft className="h-4 w-4" />Previous</Button>
              <Button size="sm" variant="outline" disabled={page >= pageCount || loading} onClick={() => setPage((current) => Math.min(pageCount, current + 1))}>Next<ChevronRight className="h-4 w-4" /></Button>
            </div>
          </div>
        </Card>
      </div>

      <Modal
        open={Boolean(selectedBatchId)}
        onClose={closeBatch}
        title="Ingestion batch evidence"
        description="Canonical batch metadata and immutable student-level processing decisions."
        className="max-w-6xl"
        footer={<div className="flex justify-end"><Button variant="outline" onClick={closeBatch}>Close</Button></div>}
      >
        {detailLoading && !batchDetail ? (
          <LoadingState label="Loading ingestion evidence..." />
        ) : detailError && !batchDetail ? (
          <ErrorNotice>{detailError}</ErrorNotice>
        ) : batchDetail ? (
          <div className="space-y-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <StatusBadge status={batchDetail.status} />
              <p className="text-xs text-text-muted">Processed {formatDateTime(batchDetail.processed_at)}</p>
            </div>
            {batchDetail.batch_error_detail ? (
              <ErrorNotice><span className="font-semibold">{batchDetail.batch_error_code || "Batch error"}:</span> {batchDetail.batch_error_detail}</ErrorNotice>
            ) : null}
            <dl className="grid gap-x-6 md:grid-cols-2">
              <DetailField label="Batch reference" value={detailPresentation.reference} />
              <DetailField label="Exam" value={detailPresentation.title} />
              {isSuperadmin ? <DetailField label="School" value={detailPresentation.tenant} /> : null}
              <DetailField label="CBT server" value={detailPresentation.server} />
              <DetailField label="Academic session" value={detailPresentation.session} />
              <DetailField label="Academic term" value={detailPresentation.term} />
              <DetailField label="Academic level" value={detailPresentation.level} />
              <DetailField label="Subject" value={detailPresentation.subject} />
              <DetailField label="Assessment component" value={detailPresentation.component} />
              <DetailField label="Exam date" value={formatDate(batchDetail.exam_date)} />
              <DetailField label="Imported" value={formatDateTime(batchDetail.created_at)} />
              <DetailField label="Processed" value={formatDateTime(batchDetail.processed_at)} />
            </dl>
            <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-border bg-border sm:grid-cols-4">
              {[
                ["Received", batchDetail.received_count],
                ["Applied", batchDetail.applied_count],
                ["Unchanged", batchDetail.unchanged_count],
                ["Rejected", batchDetail.rejected_count],
              ].map(([label, count]) => (
                <div key={label} className="min-w-0 bg-surface px-4 py-3">
                  <dt className="text-xs font-medium text-text-muted">{label}</dt>
                  <dd className="mt-1 text-xl font-semibold tabular-nums text-text">{Number(count || 0).toLocaleString()}</dd>
                </div>
              ))}
            </dl>
            <details className="rounded-xl border border-border bg-surface-muted/20">
              <summary className="cursor-pointer px-4 py-3 text-sm font-semibold text-text">
                Technical details
              </summary>
              <div className="grid gap-2 border-t border-border px-4 py-4 sm:grid-cols-2 lg:grid-cols-3">
                <TechnicalIdentifier label="Ledger record ID" value={batchDetail.id} onCopy={copyTechnicalValue} />
                <TechnicalIdentifier label="Batch ID" value={batchDetail.batch_id} onCopy={copyTechnicalValue} />
                <TechnicalIdentifier label="Source exam ID" value={batchDetail.source_exam_id} onCopy={copyTechnicalValue} />
                <TechnicalIdentifier label="Academic session ID" value={batchDetail.academic_session_id} onCopy={copyTechnicalValue} />
                <TechnicalIdentifier label="Academic term ID" value={batchDetail.academic_term_id} onCopy={copyTechnicalValue} />
                <TechnicalIdentifier label="Academic level ID" value={batchDetail.academic_level_id} onCopy={copyTechnicalValue} />
                <TechnicalIdentifier label="Curriculum subject ID" value={batchDetail.curriculum_subject_id} onCopy={copyTechnicalValue} />
                <TechnicalIdentifier label="Assessment component ID" value={batchDetail.assessment_component_id} onCopy={copyTechnicalValue} />
                <TechnicalIdentifier label="CBT server ID" value={batchDetail.cbt_server_id} onCopy={copyTechnicalValue} />
                {isSuperadmin ? <TechnicalIdentifier label="Tenant ID" value={batchDetail.tenant_id} onCopy={copyTechnicalValue} /> : null}
                <TechnicalIdentifier label="Credential ID" value={batchDetail.credential_id} onCopy={copyTechnicalValue} />
                <TechnicalIdentifier label="Request fingerprint" value={batchDetail.request_hash} onCopy={copyTechnicalValue} />
              </div>
            </details>
            <section className="overflow-hidden rounded-xl border border-border">
              <div className="flex flex-col gap-3 border-b border-border bg-surface-muted/25 px-4 py-4 sm:flex-row sm:items-center sm:justify-between">
                <div><h3 className="text-sm font-semibold text-text">Student score decisions</h3><p className="mt-0.5 text-xs text-text-muted">{detailTotal.toLocaleString()} matching items</p></div>
                <select
                  className="input-base min-w-[170px] text-sm"
                  aria-label="Filter student score decisions by outcome"
                  value={itemOutcome}
                  onChange={(event) => {
                    const nextOutcome = event.target.value;
                    setItemOutcome(nextOutcome);
                    loadDetail(selectedBatchId, 1, nextOutcome);
                  }}
                >
                  <option value="">All outcomes</option>
                  {RESULT_ITEM_OUTCOMES.map((outcome) => <option key={outcome} value={outcome}>{humanize(outcome)}</option>)}
                </select>
              </div>
              {detailLoading ? (
                <LoadingState label="Loading score decisions..." />
              ) : detailError ? (
                <div className="p-4"><ErrorNotice>{detailError}</ErrorNotice></div>
              ) : detailItems.length === 0 ? (
                <p className="px-4 py-10 text-center text-sm text-text-muted">No student decisions match this outcome.</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[880px] text-left text-sm">
                    <thead className="bg-surface-muted/55 text-[10px] uppercase tracking-wider text-text-faint"><tr><th className="px-4 py-3">Student</th><th className="px-4 py-3">Outcome</th><th className="px-4 py-3 text-right">Incoming</th><th className="px-4 py-3 text-right">Previous</th><th className="px-4 py-3 text-right">Resulting</th><th className="px-4 py-3">Decision detail</th></tr></thead>
                    <tbody className="divide-y divide-border/70">
                      {detailItems.map((item) => {
                        const studentLabel = firstText(
                          item,
                          ["student_name", "student_display_name", "student_admission_number"],
                          "Student score",
                        );
                        const isScoreConflict = String(item.error_code || "").toUpperCase() === "SCORE_CONFLICT";
                        return (
                          <tr key={item.id} className="align-top">
                            <td className="px-4 py-3">
                              <p className="font-semibold text-text">{studentLabel}</p>
                              {item.student_name && item.student_admission_number ? (
                                <p className="mt-0.5 text-xs text-text-muted">{item.student_admission_number}</p>
                              ) : null}
                            </td>
                            <td className="px-4 py-3"><OutcomeBadge outcome={item.outcome} /></td>
                            <td className="px-4 py-3 text-right font-semibold text-text">{formatScore(item.incoming_score)}</td>
                            <td className="px-4 py-3 text-right text-text-muted">{formatScore(item.previous_score)}</td>
                            <td className="px-4 py-3 text-right font-semibold text-text">{formatScore(item.resulting_score)}</td>
                            <td className="max-w-sm px-4 py-3 text-xs">
                              <p className="text-text-muted">{outcomeExplanation(item.outcome)}</p>
                              {isScoreConflict ? (
                                <div className="mt-2 rounded-lg border border-warning/30 bg-warning-soft px-3 py-2 text-text">
                                  <p className="font-semibold text-warning">Score conflict evidence</p>
                                  <p className="mt-1">CBT submitted: {formatScore(item.incoming_score)}</p>
                                  <p>Existing Weave score: {formatScore(item.previous_score)}</p>
                                  <p>Weave retained: {formatScore(item.resulting_score)}</p>
                                </div>
                              ) : null}
                              {item.error_code ? <p className="mt-2 font-semibold text-error">{humanize(item.error_code)}</p> : null}
                              {item.error_detail ? <p className="mt-1 whitespace-normal text-text-muted">{item.error_detail}</p> : null}
                              <details className="mt-2">
                                <summary className="cursor-pointer font-semibold text-text-muted">Technical details</summary>
                                <div className="mt-2 grid gap-2">
                                  <TechnicalIdentifier label="Submitted student ID" value={item.submitted_student_id} onCopy={copyTechnicalValue} />
                                  <TechnicalIdentifier label="Item ID" value={item.id} onCopy={copyTechnicalValue} />
                                  <TechnicalIdentifier label="Result ID" value={item.student_subject_result_id} onCopy={copyTechnicalValue} />
                                  <TechnicalIdentifier label="Assignment ID" value={item.resolved_teacher_assignment_id} onCopy={copyTechnicalValue} />
                                </div>
                              </details>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
              <div className="flex items-center justify-between gap-3 border-t border-border px-4 py-3"><p className="text-xs text-text-muted">Item page {detailPage} of {detailPageCount}</p><div className="flex gap-2"><Button size="sm" variant="outline" disabled={detailPage <= 1 || detailLoading} onClick={() => loadDetail(selectedBatchId, detailPage - 1, itemOutcome)}><ChevronLeft className="h-4 w-4" />Previous</Button><Button size="sm" variant="outline" disabled={detailPage >= detailPageCount || detailLoading} onClick={() => loadDetail(selectedBatchId, detailPage + 1, itemOutcome)}>Next<ChevronRight className="h-4 w-4" /></Button></div></div>
            </section>
          </div>
        ) : null}
      </Modal>
    </DashboardLayout>
  );
}
