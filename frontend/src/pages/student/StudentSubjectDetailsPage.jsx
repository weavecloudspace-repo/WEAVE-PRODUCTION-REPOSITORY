import { ArrowLeft, BookOpen, ClipboardList, UserRound } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import DashboardLayout from "../../components/layout/DashboardLayout";
import EmptyState from "../../components/shared/EmptyState";
import LoadingState from "../../components/shared/LoadingState";
import Badge from "../../components/ui/Badge";
import Card from "../../components/ui/Card";
import { academicService } from "../../services/academicService";
import { getErrorMessage } from "../../services/api";
import { cleanText } from "../../utils/academicDashboard";
import { cn } from "../../utils/cn";
import {
  displayStatusLabel,
  hasValue,
  scoreDisplayValue,
  statusVariant,
} from "./studentPageUtils";

function StudentSubjectDetailsPage() {
  const { subjectResultId } = useParams();
  const [searchParams] = useSearchParams();
  const assessmentView = searchParams.get("tab") === "assessment";
  const [results, setResults] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);

  useEffect(() => {
    let mounted = true;
    async function loadResults() {
      try {
        const response = await academicService.listMySubjectCards();
        if (mounted) setResults(response?.items || []);
      } catch (error) {
        if (mounted)
          setLoadError(
            getErrorMessage(error, "Failed to load subject details."),
          );
      } finally {
        if (mounted) setIsLoading(false);
      }
    }
    loadResults();
    return () => {
      mounted = false;
    };
  }, []);

  const result = useMemo(
    () =>
      results.find(
        (item) =>
          String(item.id) === String(subjectResultId) ||
          String(item.result_id) === String(subjectResultId),
      ) || null,
    [results, subjectResultId],
  );
  const classLabel = result?.class_name
    ? [result.class_name, result.class_arm].filter(Boolean).join(" ")
    : "No class assigned";
  const components = result?.components || [];
  const scoredComponents = components.filter((component) =>
    hasValue(component.score),
  ).length;
  const subjectFacts = [
    { label: "Subject name", value: result?.subject_name },
    {
      label: "Subject code",
      value: cleanText(result?.subject_code, "Not provided"),
    },
    { label: "Class", value: classLabel },
    { label: "Academic session", value: result?.academic_session_name },
    { label: "Term", value: result?.academic_term_name },
    {
      label: "Assessment scheme",
      value: cleanText(result?.assessment_scheme_name, "Not configured"),
    },
  ];

  if (isLoading) {
    return (
      <DashboardLayout role="student" title="Subject details">
        <LoadingState label="Loading subject details..." />
      </DashboardLayout>
    );
  }

  return (
    <DashboardLayout
      role="student"
      title={cleanText(result?.subject_name, "Subject details")}
      description={`${cleanText(result?.academic_session_name, "No session")} / ${cleanText(result?.academic_term_name, "No term")} / ${classLabel}`}
      actions={
        <Link
          to="/student/subjects"
          className="inline-flex min-h-10 items-center gap-2 rounded-xl border border-border bg-surface px-3 py-2 text-sm font-semibold text-text transition hover:bg-surface-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
        >
          <ArrowLeft className="h-4 w-4" aria-hidden="true" /> All subjects
        </Link>
      }
    >
      {loadError && (
        <div
          role="alert"
          className="rounded-xl border border-error/30 bg-error-soft px-4 py-3 text-sm text-error"
        >
          {loadError}
        </div>
      )}
      {!loadError && result && (
        <section className="space-y-5">
          <Card className="overflow-hidden">
            <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-5 sm:px-6">
              <div className="flex items-center gap-3">
                <span className="rounded-xl bg-primary-soft/50 p-3 text-primary">
                  <BookOpen className="h-6 w-6" aria-hidden="true" />
                </span>
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-text-muted">
                    Subject
                  </p>
                  <p className="mt-1 text-base font-semibold text-text">
                    {cleanText(result.subject_code, "Current term")}
                  </p>
                </div>
              </div>
              <Badge variant={statusVariant(result.status)}>
                {hasValue(result.total_score)
                  ? displayStatusLabel(result.status)
                  : "Awaiting marks"}
              </Badge>
            </div>
            <nav
              aria-label="Subject sections"
              className="flex gap-6 border-t border-border/70 px-5 sm:px-6"
            >
              {[
                { label: "Overview", tab: "overview", active: !assessmentView },
                {
                  label: "Assessments",
                  tab: "assessment",
                  active: assessmentView,
                },
              ].map((item) => (
                <Link
                  key={item.tab}
                  to={`?tab=${item.tab}`}
                  aria-current={item.active ? "page" : undefined}
                  className={cn(
                    "border-b-2 py-4 text-sm font-semibold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary",
                    item.active
                      ? "border-primary text-primary"
                      : "border-transparent text-text-muted hover:text-text",
                  )}
                >
                  {item.label}
                </Link>
              ))}
            </nav>
          </Card>
          <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,1fr)_18rem]">
            <div className="min-w-0 space-y-5">
              {assessmentView ? (
                <Card className="overflow-hidden">
                  <div className="border-b border-border/70 px-5 py-5 sm:px-6">
                    <h2 className="text-lg font-semibold text-text">
                      Assessment breakdown
                    </h2>
                    <p className="mt-1 text-sm leading-6 text-text-muted">
                      Your recorded marks and the maximum score for each
                      assessment.
                    </p>
                  </div>
                  {components.length ? (
                    <>
                      <div
                        className="overflow-x-auto"
                        tabIndex={0}
                        role="region"
                        aria-label="Assessment scores"
                      >
                        <table className="w-full min-w-[28rem] text-left text-sm">
                          <caption className="sr-only">
                            Assessment scores for {result.subject_name}
                          </caption>
                          <thead className="bg-surface-muted/30 text-xs text-text-muted">
                            <tr>
                              <th scope="col" className="px-5 py-3 font-medium">
                                Assessment
                              </th>
                              <th
                                scope="col"
                                className="px-4 py-3 text-right font-medium"
                              >
                                Score
                              </th>
                              <th
                                scope="col"
                                className="px-4 py-3 text-right font-medium"
                              >
                                Maximum
                              </th>
                              <th
                                scope="col"
                                className="px-5 py-3 text-right font-medium"
                              >
                                Percentage
                              </th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-border/70">
                            {components.map((component) => {
                              const score = Number(component.score);
                              const maximum = Number(component.maximum_score);
                              const percentage =
                                hasValue(component.score) &&
                                hasValue(component.maximum_score) &&
                                Number.isFinite(score) &&
                                Number.isFinite(maximum) &&
                                maximum > 0
                                  ? `${((score / maximum) * 100).toFixed(1)}%`
                                  : "--";
                              return (
                                <tr key={component.assessment_component_id}>
                                  <th
                                    scope="row"
                                    className="px-5 py-4 font-medium text-text"
                                  >
                                    <span className="block">
                                      {component.name}
                                    </span>
                                    {!hasValue(component.score) && (
                                      <span className="mt-1 block text-xs font-normal text-text-muted">
                                        Awaiting marks
                                      </span>
                                    )}
                                  </th>
                                  <td className="px-4 py-4 text-right tabular-nums text-text">
                                    {scoreDisplayValue(component.score)}
                                  </td>
                                  <td className="px-4 py-4 text-right tabular-nums text-text-muted">
                                    {scoreDisplayValue(component.maximum_score)}
                                  </td>
                                  <td className="px-5 py-4 text-right tabular-nums text-text-muted">
                                    {percentage}
                                  </td>
                                </tr>
                              );
                            })}
                          </tbody>
                          <tfoot className="border-t border-border bg-surface-muted/30">
                            <tr>
                              <th
                                scope="row"
                                className="px-5 py-4 font-semibold text-text"
                              >
                                Total score
                              </th>
                              <td className="px-4 py-4 text-right font-semibold tabular-nums text-text">
                                {scoreDisplayValue(result.total_score)}
                              </td>
                              <td className="px-4 py-4 text-right tabular-nums text-text-muted">
                                {scoreDisplayValue(result.maximum_score)}
                              </td>
                              <td className="px-5 py-4 text-right text-text-muted">
                                --
                              </td>
                            </tr>
                          </tfoot>
                        </table>
                      </div>
                      <p className="border-t border-border/70 px-5 py-4 text-xs leading-5 text-text-muted">
                        {scoredComponents} of {components.length} assessments
                        have recorded marks. An unrecorded mark is shown as --.
                      </p>
                    </>
                  ) : (
                    <div className="p-6">
                      <EmptyState
                        icon={ClipboardList}
                        title="No assessments configured"
                        description="Your school has not set up an assessment scheme for this subject yet."
                      />
                    </div>
                  )}
                </Card>
              ) : (
                <>
                  <Card className="p-5 sm:p-6">
                    <h2 className="text-lg font-semibold text-text">
                      About this subject
                    </h2>
                    <dl className="mt-5 grid gap-5 sm:grid-cols-2">
                      {subjectFacts.map((item) => (
                        <div key={item.label}>
                          <dt className="text-xs font-medium text-text-muted">
                            {item.label}
                          </dt>
                          <dd className="mt-1.5 break-words text-sm font-semibold text-text">
                            {cleanText(item.value)}
                          </dd>
                        </div>
                      ))}
                    </dl>
                  </Card>
                  <Card className="p-5 sm:p-6">
                    <div className="flex items-start gap-3">
                      <UserRound
                        className="mt-1 h-5 w-5 shrink-0 text-primary"
                        aria-hidden="true"
                      />
                      <div>
                        <h2 className="text-sm font-medium text-text-muted">
                          Subject teacher
                        </h2>
                        <p className="mt-1 break-words text-base font-semibold text-text">
                          {cleanText(
                            result.teacher_name,
                            "Teacher not assigned",
                          )}
                        </p>
                      </div>
                    </div>
                  </Card>
                  <Card className="p-5 sm:p-6">
                    <div className="flex flex-wrap items-center justify-between gap-4">
                      <div>
                        <h2 className="text-base font-semibold text-text">
                          Assessments
                        </h2>
                        <p className="mt-1 text-sm text-text-muted">
                          {components.length
                            ? `${scoredComponents} of ${components.length} assessments have recorded marks.`
                            : "Your assessment breakdown will appear once configured."}
                        </p>
                      </div>
                      <Link
                        to="?tab=assessment"
                        className="text-sm font-semibold text-primary underline-offset-4 hover:underline"
                      >
                        View breakdown
                      </Link>
                    </div>
                  </Card>
                </>
              )}
            </div>
            <aside className="space-y-4">
              <Card className="p-5">
                <h2 className="text-sm font-semibold text-text">
                  Term performance
                </h2>
                <p className="mt-5 text-xs text-text-muted">Total score</p>
                <p className="mt-1 text-3xl font-semibold tabular-nums text-text">
                  {scoreDisplayValue(result.total_score)}
                  {Number(result.maximum_score) > 0 && (
                    <span className="ml-1 text-sm font-normal text-text-muted">
                      / {scoreDisplayValue(result.maximum_score)}
                    </span>
                  )}
                </p>
                <dl className="mt-5 space-y-3 border-t border-border/70 pt-4">
                  <div className="flex items-center justify-between gap-3">
                    <dt className="text-sm text-text-muted">Grade</dt>
                    <dd className="font-semibold text-text">
                      {cleanText(result.grade, "--")}
                    </dd>
                  </div>
                  <div className="flex items-center justify-between gap-3">
                    <dt className="text-sm text-text-muted">Status</dt>
                    <dd className="text-right text-sm font-medium text-text">
                      {displayStatusLabel(result.status)}
                    </dd>
                  </div>
                </dl>
              </Card>
              <Card className="p-5">
                <h2 className="text-sm font-semibold text-text">
                  Teacher's remark
                </h2>
                <p className="mt-2 break-words text-sm leading-6 text-text-muted">
                  {cleanText(result.remark, "No remark has been added yet.")}
                </p>
              </Card>
            </aside>
          </div>
        </section>
      )}
      {!loadError && !result && (
        <Card className="p-6">
          <EmptyState
            icon={BookOpen}
            title="Subject not found"
            description="This subject is not available in your current subject list. Return to Subjects to see the subjects assigned to you."
          />
        </Card>
      )}
    </DashboardLayout>
  );
}

export default StudentSubjectDetailsPage;
