import { api } from "./api";
import { clearDashboardMetricsCache } from "./dashboard.service";

const STUDENT_RESOURCE_TYPE = "students";
const JOB_RESPONSE_CACHE_MS = 1500;
const ERROR_RESPONSE_CACHE_MS = 15000;
const inFlightJobRequests = new Map();
const inFlightErrorRequests = new Map();
const jobResponseCache = new Map();
const errorResponseCache = new Map();

const withRequestDeduplication = ({ key, inFlight, cache, ttlMs, loader }) => {
  const now = Date.now();
  const cached = cache.get(key);
  if (cached && cached.expiresAt > now) return Promise.resolve(cached.value);
  if (inFlight.has(key)) return inFlight.get(key);

  const promise = Promise.resolve()
    .then(loader)
    .then((value) => {
      cache.set(key, { value, expiresAt: Date.now() + ttlMs });
      return value;
    })
    .finally(() => {
      if (inFlight.get(key) === promise) inFlight.delete(key);
    });

  inFlight.set(key, promise);
  return promise;
};

const clearImportRequestCaches = () => {
  jobResponseCache.clear();
  errorResponseCache.clear();
};

const downloadBlob = async (endpoint, filename, signal) => {
  const blob = await api.getBlob(endpoint, { signal });
  const url = window.URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.URL.revokeObjectURL(url);
};

const invalidateImportRelatedCaches = () => {
  clearImportRequestCaches();
  clearDashboardMetricsCache();
  window.dispatchEvent(new Event("weave:dashboard-cache-clear"));
};

export const bulkImportService = {
  listTemplates: (requestOptions) =>
    api.get("/tenant-admin/imports/templates", requestOptions),

  downloadTemplate: (requestOptions = {}) =>
    downloadBlob(
      `/tenant-admin/imports/templates/${STUDENT_RESOURCE_TYPE}/download`,
      "students_import_template.xlsx",
      requestOptions.signal,
    ),

  dryRun: (file, requestOptions = {}) => {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("notify_on_completion", "true");

    return api.postForm(
      `/tenant-admin/imports/${STUDENT_RESOURCE_TYPE}/dry-run`,
      formData,
      requestOptions,
    );
  },

  confirm: async (jobId, requestOptions = {}) => {
    const result = await api.post(
      `/tenant-admin/imports/${jobId}/confirm`,
      undefined,
      requestOptions,
    );
    invalidateImportRelatedCaches();
    return result;
  },

  retry: async (jobId, requestOptions = {}) => {
    const result = await api.post(
      `/tenant-admin/imports/${jobId}/retry`,
      undefined,
      requestOptions,
    );
    invalidateImportRelatedCaches();
    return result;
  },

  getJob: (jobId, requestOptions = {}) => {
    const { force = false, ...apiOptions } = requestOptions;
    if (force) {
      jobResponseCache.delete(jobId);
      errorResponseCache.delete(jobId);
      inFlightJobRequests.delete(jobId);
      inFlightErrorRequests.delete(jobId);
    }
    return withRequestDeduplication({
      key: jobId,
      inFlight: inFlightJobRequests,
      cache: jobResponseCache,
      ttlMs: JOB_RESPONSE_CACHE_MS,
      loader: () => api.get(`/tenant-admin/imports/${jobId}`, apiOptions),
    });
  },

  listJobs: ({ skip = 0, limit = 20, status, search, signal } = {}) => {
    const params = new URLSearchParams({
      skip: String(skip),
      limit: String(limit),
    });
    if (status) params.set("status", status);
    if (search?.trim()) params.set("search", search.trim());
    return api.get(`/tenant-admin/imports?${params.toString()}`, { signal });
  },

  deleteJob: async (jobId, requestOptions = {}) => {
    const result = await api.delete(
      `/tenant-admin/imports/${jobId}`,
      requestOptions,
    );
    invalidateImportRelatedCaches();
    return result;
  },

  getErrors: (jobId, requestOptions = {}) => {
    const { force = false, ...apiOptions } = requestOptions;
    if (force) {
      errorResponseCache.delete(jobId);
      inFlightErrorRequests.delete(jobId);
    }
    return withRequestDeduplication({
      key: jobId,
      inFlight: inFlightErrorRequests,
      cache: errorResponseCache,
      ttlMs: ERROR_RESPONSE_CACHE_MS,
      loader: () =>
        api.get(`/tenant-admin/imports/${jobId}/errors?limit=100`, apiOptions),
    });
  },

  getSlipSummary: (jobId, requestOptions) =>
    api.get(`/tenant-admin/imports/${jobId}/slips/summary`, requestOptions),

  listSlips: (
    jobId,
    { search = "", classKey = "", page = 1, pageSize = 50, signal } = {},
  ) => {
    const params = new URLSearchParams({
      page: String(page),
      page_size: String(pageSize),
    });
    if (search) params.set("search", search);
    if (classKey) params.set("class_key", classKey);
    return api.get(
      `/tenant-admin/imports/${jobId}/slips?${params.toString()}`,
      { signal },
    );
  },

  getSlip: (jobId, rowNumber, requestOptions) =>
    api.get(
      `/tenant-admin/imports/${jobId}/slips/${rowNumber}`,
      requestOptions,
    ),

  getSlipPrintData: (jobId, payload, requestOptions) =>
    api.post(
      `/tenant-admin/imports/${jobId}/slips/print`,
      payload,
      requestOptions,
    ),

  downloadResult: (jobId, { format = "spreadsheet", signal } = {}) => {
    if (format === "slip") {
      window.location.assign(`/admin/imports/${jobId}/student-slips`);
      return Promise.resolve();
    }

    return downloadBlob(
      `/tenant-admin/imports/${jobId}/result?format=spreadsheet`,
      `students_${jobId}_result.xlsx`,
      signal,
    );
  },

  downloadErrors: (jobId, { signal } = {}) =>
    downloadBlob(
      `/tenant-admin/imports/${jobId}/errors/download`,
      `students_${jobId}_errors.csv`,
      signal,
    ),
};
