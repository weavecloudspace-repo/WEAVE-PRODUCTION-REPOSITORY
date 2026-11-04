export const BULK_IMPORT_HISTORY_PAGE_SIZE = 20;
export const HISTORY_NEXT_LABEL = "Next";

export const getResultRows = (job) => (Array.isArray(job?.metadata_json?.result_rows) ? job.metadata_json.result_rows : []);

export const getExpectedParentInvitationCount = (job) => Number(
  job?.metadata_json?.new_parent_invitations_expected ?? 0,
);

export const getActualParentInvitationsQueued = (job) => getResultRows(job).reduce(
  (total, row) => total + Number(row.parent_invitations_queued || 0),
  0,
);

export const createHistoryQuery = ({ skip, status, search }) => ({
  skip,
  limit: BULK_IMPORT_HISTORY_PAGE_SIZE,
  status: status || undefined,
  ...(search?.trim() ? { search: search.trim() } : {}),
});

export async function loadImportHistoryPage({
  listJobs,
  skip,
  status,
  search,
  isCurrent = () => true,
  setJobs,
  setJobsTotal,
  setHistorySkip,
  setHistoryLoading,
}) {
  setHistoryLoading(true);
  try {
    const response = await listJobs(createHistoryQuery({ skip, status, search }));
    const items = Array.isArray(response?.items) ? response.items : [];
    if (isCurrent()) {
      setJobs(items);
      setJobsTotal(Number(response?.total ?? items.length));
      setHistorySkip(skip);
    }
    return items;
  } finally {
    if (isCurrent()) setHistoryLoading(false);
  }
}

export const getStatusChangeHistoryRequest = (status) => ({
  skip: 0,
  status,
});

export const getPreviousHistoryRequest = (skip, status) => ({
  skip: Math.max(0, Number(skip || 0) - BULK_IMPORT_HISTORY_PAGE_SIZE),
  status,
});

export const getNextHistoryRequest = (skip, status) => ({
  skip: Number(skip || 0) + BULK_IMPORT_HISTORY_PAGE_SIZE,
  status,
});
