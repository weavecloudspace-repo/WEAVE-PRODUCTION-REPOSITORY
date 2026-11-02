import { Link, useLocation, useParams } from "react-router-dom";
import {
  ArrowLeft,
  ExternalLink,
  FileSearch,
  GraduationCap,
  Mail,
  Tag,
  UserRound,
} from "lucide-react";

import DashboardLayout from "../../components/layout/DashboardLayout";
import { PersonIdentity } from "../../components/people/PeopleDirectory";
import Button from "../../components/ui/Button";
import Card from "../../components/ui/Card";
import { getAvatarSrcFromRecord } from "../../utils/user";

const SEARCH_STORAGE_PREFIX = "weave:admin-search:";

const getStoredSearchResult = (resultKey) => {
  if (typeof window === "undefined" || !resultKey) return null;

  try {
    const raw = window.sessionStorage.getItem(`${SEARCH_STORAGE_PREFIX}${resultKey}`);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
};

const visibleDetailEntries = (item) =>
  Object.entries(item || {})
    .filter(([, value]) => value !== undefined && value !== null && value !== "")
    .filter(([key]) => !["href", "passport_photo_url"].includes(key))
    .map(([key, value]) => ({
      key,
      label: key.replace(/_/g, " "),
      value: typeof value === "object" ? JSON.stringify(value, null, 2) : String(value),
    }));

function DetailTile({ icon: Icon, label, value }) {
  if (!value) return null;

  return (
    <div className="rounded-2xl border border-border bg-surface-muted/25 px-4 py-3">
      <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-wide text-text-muted">
        <Icon className="h-4 w-4" />
        {label}
      </div>
      <p className="mt-2 break-words text-sm font-semibold text-text">{value}</p>
    </div>
  );
}

function AdminSearchDetailPage() {
  const { resultKey } = useParams();
  const location = useLocation();
  const storedPayload = getStoredSearchResult(resultKey);
  const payload = location.state || storedPayload || {};
  const item = payload.item || null;
  const query = payload.query || "";
  const details = visibleDetailEntries(item);

  return (
    <DashboardLayout
      role="admin"
      title="Search result"
      description={query ? `Full detail preview for "${query}".` : "Full detail preview for the selected search result."}
      actions={
        <Link to="/admin/dashboard">
          <Button variant="outline">
            <ArrowLeft className="h-4 w-4" />
            Back to dashboard
          </Button>
        </Link>
      }
    >
      {!item ? (
        <Card className="p-6 text-center">
          <FileSearch className="mx-auto h-10 w-10 text-text-faint" />
          <h2 className="mt-4 text-lg font-semibold text-text">Search result not available</h2>
          <p className="mx-auto mt-2 max-w-xl text-sm leading-6 text-text-muted">
            This detail page is powered by the selected search result payload. Search again from the admin dashboard to open a fresh detail view.
          </p>
        </Card>
      ) : (
        <div className="mx-auto w-full max-w-5xl space-y-5">
          <Card className="overflow-hidden">
            <div className="border-b border-border bg-surface-muted/35 p-5 sm:p-6">
              <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0">
                  <p className="text-xs font-bold uppercase tracking-[0.14em] text-primary">
                    {item.role || item.type || item.category || "Search result"}
                  </p>
                  <div className="mt-3">
                    <PersonIdentity
                      name={item.label || item.title || item.name || "Untitled record"}
                      meta={item.admission_number || item.staff_id || item.email || item.metadata}
                      avatarSrc={getAvatarSrcFromRecord(item)}
                      size="large"
                    />
                  </div>
                  <p className="mt-3 max-w-2xl text-sm leading-6 text-text-muted sm:pl-20">
                    This page keeps search context in one place before you open the record's owning workspace.
                  </p>
                </div>
                {item.href ? (
                  <Link to={item.href} className="shrink-0">
                    <Button variant="outline">
                      Open in workspace
                      <ExternalLink className="h-4 w-4" />
                    </Button>
                  </Link>
                ) : null}
              </div>
            </div>

            <div className="grid gap-3 p-4 sm:grid-cols-2 sm:p-6 lg:grid-cols-4">
              <DetailTile icon={UserRound} label="Role" value={item.role || item.type || item.category} />
              <DetailTile icon={Mail} label="Email" value={item.email} />
              <DetailTile icon={GraduationCap} label="Admission" value={item.admission_number || item.staff_id} />
              <DetailTile icon={Tag} label="Metadata" value={item.metadata || item.class_name || item.subject_name} />
            </div>
          </Card>

          <Card className="p-4 sm:p-6">
            <div className="flex items-center gap-3">
              <span className="flex h-10 w-10 items-center justify-center rounded-2xl bg-primary-soft text-primary">
                <FileSearch className="h-5 w-5" />
              </span>
              <div>
                <h3 className="text-base font-semibold text-text">All available details</h3>
                <p className="text-sm text-text-muted">These are the fields returned by the current search endpoint.</p>
              </div>
            </div>

            <dl className="mt-5 grid gap-3 sm:grid-cols-2">
              {details.map((detail) => (
                <div key={detail.key} className="rounded-2xl border border-border/70 bg-surface-muted/20 px-4 py-3">
                  <dt className="text-xs font-bold uppercase tracking-wide text-text-muted">{detail.label}</dt>
                  <dd className="mt-1 whitespace-pre-wrap break-words text-sm font-medium text-text">{detail.value}</dd>
                </div>
              ))}
            </dl>
          </Card>
        </div>
      )}
    </DashboardLayout>
  );
}

export { SEARCH_STORAGE_PREFIX };
export default AdminSearchDetailPage;
