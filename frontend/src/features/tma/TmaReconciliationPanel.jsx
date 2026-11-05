import { AlertTriangle, ArrowUpRight, ClipboardCheck, RefreshCw } from "lucide-react";
import { Link } from "react-router-dom";
import Button from "../../components/ui/Button";

const issueLabel = (issue) =>
  issue.student_name?.trim() || issue.admission_number || "Student record";

function resultReviewPath(issue, assignment) {
  const query = new URLSearchParams({
    view: "overview",
    academic_session_id: assignment.academic_session_id,
    academic_term_id: assignment.academic_term_id,
  });
  if (issue.class_id) query.set("class_id", issue.class_id);
  if (issue.admission_number) query.set("search", issue.admission_number);
  return `/admin/academic/results?${query}`;
}

export default function TmaReconciliationPanel({
  kind, issues, assignment, role, busy, onExempt, onRefresh,
}) {
  if (!issues.length) return null;
  const isZero = kind === "zero";
  const title = isZero ? "Missed-TMA grading needs review" : "Cancellation needs review";
  return (
    <section
      aria-label={title}
      className="w-full min-w-0 overflow-hidden rounded-2xl border border-warning/30 bg-surface shadow-sm"
    >
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-warning/20 bg-surface-muted px-4 py-4 sm:px-5">
        <div className="flex min-w-0 items-start gap-3">
          <div className="rounded-xl bg-warning/10 p-2 text-warning">
            <AlertTriangle className="h-5 w-5" aria-hidden="true" />
          </div>
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-text">{title}</h3>
            <p className="mt-1 max-w-2xl text-xs leading-relaxed text-text-muted">
              {isZero
                ? "Review each affected student. Correct the academic result or, if justified, retain the existing mark with an audited exemption."
                : "Review the affected academic results before retrying cancellation. No scores have been silently overwritten."}
            </p>
            <span className="mt-2 inline-flex rounded-full bg-warning/10 px-2.5 py-1 text-xs font-semibold text-warning">
              {issues.length} {issues.length === 1 ? "student" : "students"} to review
            </span>
          </div>
        </div>
        <Button type="button" variant="outline" size="sm" disabled={busy} onClick={onRefresh}>
          <RefreshCw className="h-4 w-4" aria-hidden="true" /> Refresh
        </Button>
      </div>
      <div className="divide-y divide-border/70">
        {issues.map((issue) => (
          <article
            key={issue.attempt_id || issue.student_id}
            className="grid min-w-0 gap-3 px-4 py-4 sm:px-5 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center"
          >
            <div className="min-w-0">
              <h4 className="truncate text-sm font-semibold text-text">{issueLabel(issue)}</h4>
              {issue.admission_number && (
                <p className="mt-0.5 text-xs text-text-muted">
                  Admission no. {issue.admission_number}
                </p>
              )}
              <p className="mt-2 rounded-lg bg-surface-muted px-3 py-2 text-xs leading-relaxed text-text-soft">
                <span className="font-semibold">Why this needs attention: </span>
                {issue.reason}
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2 lg:justify-end">
              {role === "admin" ? (
                <>
                  <Link
                    to={resultReviewPath(issue, assignment)}
                    className="inline-flex min-h-10 items-center justify-center gap-1.5 rounded-xl border border-border bg-surface px-3 py-2 text-xs font-semibold text-text transition hover:bg-surface-muted"
                  >
                    <ArrowUpRight className="h-4 w-4" aria-hidden="true" />
                    Open results
                  </Link>
                  {isZero && (
                    <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => onExempt(issue)}>
                      <ClipboardCheck className="h-4 w-4" aria-hidden="true" />
                      Exempt with reason
                    </Button>
                  )}
                </>
              ) : (
                <span className="text-xs text-text-muted">
                  Ask an administrator to review the academic result.
                </span>
              )}
            </div>
          </article>
        ))}
      </div>
      <p className="border-t border-border/70 px-4 py-3 text-xs leading-relaxed text-text-muted sm:px-5">
        {isZero
          ? "Exemptions require a reason, are audited, and do not modify marks. Repairs follow normal academic permissions."
          : "Resolve the affected results using the normal academic approval/reopen workflow, then choose Retry cancellation."}
      </p>
    </section>
  );
}
