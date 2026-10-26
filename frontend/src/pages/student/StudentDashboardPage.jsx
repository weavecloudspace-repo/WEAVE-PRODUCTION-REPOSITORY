import {
  BarChart3,
  BookOpen,
  ClipboardList,
  FileText,
  GraduationCap,
  Link2,
  Megaphone,
  UserRound,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import {
  DashboardFocusCard,
  DashboardListCard,
  DashboardMetricCard,
  DashboardQuickActions,
  DashboardSectionHeader,
  DashboardWelcomePanel,
} from "../../components/dashboard/DashboardPrimitives";
import DashboardLayout from "../../components/layout/DashboardLayout";
import EmptyState from "../../components/shared/EmptyState";
import LoadingState from "../../components/shared/LoadingState";
import Button from "../../components/ui/Button";
import Card from "../../components/ui/Card";
import DashboardCalendarPanel from "../../features/schoolCalendar/components/DashboardCalendarPanel";
import { academicService } from "../../services/academicService";
import { authSession, getErrorMessage, isAbortError } from "../../services/api";
import { dashboardService } from "../../services/dashboard.service";
import {
  getCachedDashboardBundle,
  getDashboardSessionCacheKey,
  invalidateDashboardSessionCache,
} from "../../services/dashboardSessionCache";
import { reportCardService } from "../../services/reportCardService";
import { realtimeClient } from "../../services/realtimeClient";
import { studentService } from "../../services/studentService";
import {
  averageByAcademicPeriod,
  averageScore,
  bestAndWeakestSubject,
  chartFromCounts,
  cleanText,
  formatChartLabel,
  subjectPerformanceChart,
} from "../../utils/academicDashboard";
import { displayName } from "../../utils/user";
import {
  displayStatusLabel,
  formatMetricNumber,
  getAcademicContext,
  hasValue,
  isPublishedResult,
  scoreDisplayValue,
} from "./studentPageUtils";

const PROGRESS_COLORS = ["#3452DB", "#16A34A", "#F59E0B", "#7C3AED", "#0EA5E9"];

const isCompleteStudentProfile = (student) =>
  String(student?.profile_status || "").toLowerCase() === "complete";

const emptyDashboardBundle = (studentProfile) => ({
  student: studentProfile,
  parentLinks: [],
  parentLinkRequests: [],
  metrics: null,
  academicResults: [],
  reportCards: [],
  subjectCards: [],
  subjectContext: null,
});

const studentClassLabel = (student, fallback = null) => {
  if (!student) return fallback;
  return cleanText(
    [student.class_name, student.class_arm || student.arm]
      .filter(Boolean)
      .join(" "),
    fallback ?? (student.class_id ? "Class assigned" : "No class assigned yet"),
  );
};

const formatAcademicTermLabel = (value) => {
  const normalized = String(value || "").trim();
  if (!normalized) return "No term";
  return normalized
    .replace(/_/g, " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
};

function StudentDashboardPage() {
  const [student, setStudent] = useState(null);
  const [parentLinks, setParentLinks] = useState([]);
  const [parentLinkRequests, setParentLinkRequests] = useState([]);
  const [metrics, setMetrics] = useState(null);
  const [academicResults, setAcademicResults] = useState([]);
  const [reportCards, setReportCards] = useState([]);
  const [subjectCards, setSubjectCards] = useState([]);
  const [subjectContext, setSubjectContext] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const user = authSession.getUser();
  const firstName = user?.first_name || user?.firstname || "Student";
  const calendarScope = `${user?.tenant_id || "global"}:${user?.membership_id || ""}:${user?.id || user?.email || ""}`;

  useEffect(() => {
    let mounted = true;
    let requestVersion = 0;
    const controller = new AbortController();

    async function loadDashboard(force = false) {
      const version = ++requestVersion;
      setIsLoading(true);
      setLoadError(null);

      try {
        const studentProfile = await studentService.getMyStudent({
          signal: controller.signal,
        });

        if (!mounted || controller.signal.aborted || version !== requestVersion) return;

        if (!isCompleteStudentProfile(studentProfile)) {
          const incompleteBundle = emptyDashboardBundle(studentProfile);
          setStudent(incompleteBundle.student);
          setParentLinks(incompleteBundle.parentLinks);
          setParentLinkRequests(incompleteBundle.parentLinkRequests);
          setMetrics(incompleteBundle.metrics);
          setAcademicResults(incompleteBundle.academicResults);
          setReportCards(incompleteBundle.reportCards);
          setSubjectCards(incompleteBundle.subjectCards);
          setSubjectContext(incompleteBundle.subjectContext);
          return;
        }

        const cacheKey = getDashboardSessionCacheKey("student:dashboard");
        const bundle = await getCachedDashboardBundle(cacheKey, async () => {
          const [
            linksResponse,
            requestsResponse,
            metricsResponse,
            resultResponse,
            reportCardResponse,
            subjectCardsResponse,
          ] = await Promise.all([
            studentService.getMyParentLinks({ signal: controller.signal }),
            studentService.getMyParentLinkRequests({
              signal: controller.signal,
            }),
            dashboardService.getStudentAnalytics({ signal: controller.signal }),
            academicService.listMyResults({ signal: controller.signal }),
            reportCardService.listMyReportCards({ signal: controller.signal }),
            academicService.listMySubjectCards({ signal: controller.signal }),
          ]);

          return {
            student: studentProfile,
            parentLinks: linksResponse?.items || [],
            parentLinkRequests: requestsResponse?.items || [],
            metrics: metricsResponse,
            academicResults: resultResponse?.items || [],
            reportCards: reportCardResponse?.items || [],
            subjectCards: subjectCardsResponse?.items || [],
            subjectContext: subjectCardsResponse?.context || null,
          };
        }, { force });

        if (!mounted || controller.signal.aborted || version !== requestVersion) return;
        setStudent(studentProfile);
        setParentLinks(bundle.parentLinks);
        setParentLinkRequests(bundle.parentLinkRequests);
        setMetrics(bundle.metrics);
        setAcademicResults(bundle.academicResults);
        setReportCards(bundle.reportCards);
        setSubjectCards(bundle.subjectCards);
        setSubjectContext(bundle.subjectContext);
      } catch (error) {
        if (mounted && version === requestVersion && !isAbortError(error)) {
          setLoadError(
            getErrorMessage(error, "Failed to load student dashboard."),
          );
        }
      } finally {
        if (mounted && !controller.signal.aborted && version === requestVersion) setIsLoading(false);
      }
    }

    loadDashboard();
    const refreshScores = () => {
      invalidateDashboardSessionCache();
      void loadDashboard(true);
    };
    const handleVisible = () => {
      if (document.visibilityState === "visible") refreshScores();
    };
    const unsubscribeScores = realtimeClient.subscribe(
      "academic.component_score.updated", refreshScores,
    );
    const handlePullRefresh = () => refreshScores();
    window.addEventListener("weave:pull-refresh", handlePullRefresh);
    document.addEventListener("visibilitychange", handleVisible);

    return () => {
      unsubscribeScores();
      document.removeEventListener("visibilitychange", handleVisible);
      window.removeEventListener("weave:pull-refresh", handlePullRefresh);
      mounted = false;
      controller.abort();
    };
  }, []);

  const dashboardData = useMemo(() => {
    const stats = metrics?.stats || {};
    const chartSource = metrics?.charts || {};
    const publishedResults = academicResults.filter(isPublishedResult);
    const pendingResults = academicResults.filter(
      (result) => !isPublishedResult(result),
    );
    const fallbackContext = getAcademicContext(academicResults, reportCards);
    const context = subjectContext
      ? {
          classLabel:
            studentClassLabel(student) ||
            (subjectContext.class_name || subjectContext.class_arm
              ? [subjectContext.class_name, subjectContext.class_arm]
                  .filter(Boolean)
                  .join(" ")
              : null),
          sessionLabel:
            student?.current_academic_session_name ||
            subjectContext.academic_session_name ||
            null,
          termLabel:
            student?.current_academic_term_name ||
            subjectContext.academic_term_name ||
            null,
        }
      : {
          ...fallbackContext,
          classLabel: studentClassLabel(student, fallbackContext.classLabel),
          sessionLabel:
            student?.current_academic_session_name ||
            fallbackContext.sessionLabel,
          termLabel:
            student?.current_academic_term_name || fallbackContext.termLabel,
        };
    const currentAverage = hasValue(stats.current_average)
      ? stats.current_average
      : publishedResults.length > 0
        ? averageScore(publishedResults)
        : null;
    const subjectHighlights = bestAndWeakestSubject(publishedResults);
    const subjectChart =
      chartSource.subject_performance ||
      chartSource.subject_comparison ||
      subjectPerformanceChart(publishedResults);
    const performanceTrend =
      chartSource.performance_trend ||
      averageByAcademicPeriod(
        reportCards.length > 0 ? reportCards : publishedResults,
        reportCards.length > 0 ? "average_score" : "total_score",
      );
    const gradeDistribution =
      chartSource.grade_distribution ||
      chartFromCounts(publishedResults, "grade", "ungraded");

    return {
      stats,
      currentAverage,
      publishedResults,
      pendingResults,
      subjectHighlights,
      subjectsCount: hasValue(stats.subjects_count)
        ? stats.subjects_count
        : subjectCards.length,
      context,
      latestReportCard: reportCards[0],
      pendingParentRequests: parentLinkRequests.filter(
        (request) => request.status === "pending",
      ),
      subjectCards,
      subjectChart,
      performanceTrend,
      gradeDistribution,
    };
  }, [
    academicResults,
    metrics,
    parentLinkRequests,
    reportCards,
    student,
    subjectCards,
    subjectContext,
  ]);

  if (isLoading) {
    return (
      <DashboardLayout role="student" title={`${firstName}'s Portal`}>
        <LoadingState label="Loading student dashboard..." />
      </DashboardLayout>
    );
  }

  const attentionItems = [
    dashboardData.pendingParentRequests.length > 0
      ? {
          key: "parent-approval",
          title: "Parent link request pending",
          description: `${dashboardData.pendingParentRequests.length} request${dashboardData.pendingParentRequests.length === 1 ? "" : "s"} waiting for approval.`,
          icon: Link2,
          tone: "warning",
          to: "/student/parent-linking",
        }
      : null,
    dashboardData.pendingResults.length > 0
      ? {
          key: "pending-results",
          title: "Some results are not published yet",
          description: `${dashboardData.pendingResults.length} result row${dashboardData.pendingResults.length === 1 ? "" : "s"} still pending.`,
          icon: ClipboardList,
          tone: "warning",
          to: "/student/report-cards",
        }
      : null,
    !dashboardData.latestReportCard
      ? {
          key: "no-report-card",
          title: "Report card awaiting release",
          description:
            "Your latest report card will appear when the school publishes it.",
          icon: FileText,
          tone: "neutral",
          to: "/student/report-cards",
        }
      : null,
    Number(dashboardData.stats.unread_count || 0) > 0
      ? {
          key: "unread-notices",
          title: "Unread notifications",
          description: `${dashboardData.stats.unread_count} notification${Number(dashboardData.stats.unread_count) === 1 ? "" : "s"} waiting for you.`,
          icon: Megaphone,
          tone: "primary",
          to: "/student/inbox",
        }
      : null,
  ].filter(Boolean);

  return (
    <DashboardLayout role="student" title={`${firstName}'s Portal`}>
      {loadError ? (
        <div className="rounded-2xl border border-error/30 bg-error-soft px-4 py-3 text-sm font-medium text-error">
          {loadError}
        </div>
      ) : null}

      {!loadError && !student ? (
        <EmptyState
          icon={UserRound}
          title="No student profile found"
          description="Your account exists, but the school has not created your student academic profile yet."
        />
      ) : null}

      {!loadError && student ? (
        <>
          <DashboardWelcomePanel
            variant="student"
            eyebrow="Student dashboard"
            title={`Welcome back, ${displayName(student) || firstName}`}
            description={cleanText(
              dashboardData.context.classLabel,
              student.class_id ? "Class assigned" : "No class assigned yet",
            )}
            profileCompletion={student.profile_status}
            chips={[
              {
                label: "Admission",
                value: cleanText(student.admission_number, "Not assigned"),
                tone: "primary",
              },
              {
                label: cleanText(
                  dashboardData.context.sessionLabel,
                  "No session",
                ),
                value: formatAcademicTermLabel(dashboardData.context.termLabel),
                tone: "primary",
              },
            ]}
          />

          <section className="dashboard-kpi-grid dashboard-kpi-grid-four grid grid-cols-2 gap-3 sm:gap-4 xl:grid-cols-4">
            <DashboardMetricCard
              label="Current average"
              value={
                hasValue(dashboardData.currentAverage)
                  ? formatMetricNumber(dashboardData.currentAverage)
                  : "-"
              }
              description="Published academic results"
              icon={BarChart3}
              tone={
                hasValue(dashboardData.currentAverage) ? "success" : "warning"
              }
              to="/student/analytics"
            />
            <DashboardMetricCard
              label="Subjects"
              value={dashboardData.subjectsCount}
              description="Class subjects available"
              icon={BookOpen}
              tone="primary"
              to="/student/subjects"
            />
            <DashboardMetricCard
              label="Published results"
              value={dashboardData.publishedResults.length}
              description={`${dashboardData.pendingResults.length} pending`}
              icon={ClipboardList}
              tone={
                dashboardData.pendingResults.length > 0 ? "warning" : "success"
              }
              to="/student/report-cards"
            />
            <DashboardMetricCard
              label="Parent links"
              value={parentLinks.length}
              description={`${dashboardData.pendingParentRequests.length} pending request${dashboardData.pendingParentRequests.length === 1 ? "" : "s"}`}
              icon={Link2}
              tone={parentLinks.length > 0 ? "success" : "warning"}
              to="/student/parent-linking"
            />
          </section>

          <section className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(320px,0.8fr)]">
            <DashboardFocusCard
              title="Focus for today"
              description="Your next useful academic step."
              icon={GraduationCap}
              tone="primary"
              primaryAction={{
                to: "/student/subjects",
                label: "Open subjects",
                icon: BookOpen,
              }}
              secondaryAction={{
                to: "/student/report-cards",
                label: "Report cards",
                icon: FileText,
              }}
            >
              <div className="grid grid-cols-2 gap-3">
                <InfoTile
                  label="Best subject"
                  value={
                    dashboardData.subjectHighlights.best?.label ||
                    "Awaiting results"
                  }
                />
                <InfoTile
                  label="Needs support"
                  value={
                    dashboardData.subjectHighlights.weakest?.label ||
                    "No weak spot yet"
                  }
                />
                <InfoTile
                  label="Latest report"
                  value={
                    dashboardData.latestReportCard
                      ? cleanText(
                          dashboardData.latestReportCard.academic_term_name,
                          "Published",
                        )
                      : "Awaiting release"
                  }
                />
                <InfoTile
                  label="Unread notifications"
                  value={dashboardData.stats.unread_count ?? 0}
                />
              </div>
            </DashboardFocusCard>

            <DashboardListCard
              title="Needs attention"
              description="Items that need a quick look."
              items={attentionItems}
              emptyTitle="You are all caught up"
              emptyDescription="No pending parent link, report, or school notification needs attention right now."
            />
          </section>

          <section className="grid gap-5 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
            <DashboardCalendarPanel
              role="student"
              actorId={user?.id || user?.email || ""}
              membershipId={user?.membership_id || ""}
              tenantId={user?.tenant_id || calendarScope}
            />
            <DashboardListCard
              title="Student calendar"
              description="Published student-visible dates and school status."
              items={[]}
              emptyTitle="No calendar action needed"
              emptyDescription="Exams, holidays, closures, and student events will appear in the calendar card."
            />
          </section>

          <section className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(320px,0.8fr)]">
            <SubjectProgressPreview data={dashboardData.subjectChart} />
            <DashboardQuickActions
              title="Quick actions"
              description="Common student workflows."
              actions={[
                {
                  label: "Subjects",
                  description: "View scores and components",
                  to: "/student/subjects",
                  icon: BookOpen,
                  tone: "primary",
                },
                {
                  label: "Performance",
                  description: "Open full analytics",
                  to: "/student/analytics",
                  icon: BarChart3,
                  tone: "success",
                },
                {
                  label: "Report cards",
                  description: "Published term reports",
                  to: "/student/report-cards",
                  icon: FileText,
                  tone: "warning",
                },
                {
                  label: "Inbox",
                  description: "Notifications and updates",
                  to: "/student/inbox",
                  icon: Megaphone,
                  tone: "accent",
                },
              ]}
            />
          </section>

          {dashboardData.subjectCards.length > 0 ? (
            <section className="space-y-4">
              <DashboardSectionHeader
                title="Subjects snapshot"
                description="A short preview of class subjects."
                action={
                  <Link to="/student/subjects">
                    <Button variant="outline" size="sm">
                      Open all subjects
                    </Button>
                  </Link>
                }
              />
              <div className="grid grid-cols-2 gap-3 md:grid-cols-2 xl:grid-cols-4">
                {dashboardData.subjectCards.slice(0, 4).map((card) => (
                  <Card
                    key={card.id}
                    as={Link}
                    to={`/student/subjects/${card.id}`}
                    className="p-3 transition hover:border-primary/30 hover:shadow-premium sm:p-4"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="truncate text-sm font-semibold text-text">
                          {cleanText(card.subject_name, "Subject")}
                        </p>
                        <p className="mt-1 truncate text-xs text-text-muted">
                          {cleanText(card.teacher_name, "Teacher not assigned")}
                        </p>
                        {card.components?.filter((item) => hasValue(item.score)).slice(0, 2).map((item) => (
                          <p key={item.assessment_component_id} className="mt-2 text-xs font-medium text-primary">
                            {item.name}: {scoreDisplayValue(item.score)} / {scoreDisplayValue(item.maximum_score)}
                          </p>
                        ))}
                      </div>
                      <span className="rounded-full bg-surface-muted px-2 py-1 text-[10px] font-semibold text-text-muted">
                        {displayStatusLabel(
                          card.status,
                          "Awaiting marks",
                        )}
                      </span>
                    </div>
                    <div className="mt-4 flex items-end justify-between gap-3 rounded-2xl border border-border/70 bg-surface-muted/20 px-3 py-3">
                      <div>
                        <p className="text-[10px] font-semibold uppercase tracking-wide text-text-muted">
                          Total
                        </p>
                        <p className="mt-1 text-lg font-semibold text-text">
                          {scoreDisplayValue(card.total_score)}
                        </p>
                      </div>
                      <div className="text-right">
                        <p className="text-[10px] font-semibold uppercase tracking-wide text-text-muted">
                          Grade
                        </p>
                        <p className="mt-1 text-lg font-semibold text-text">
                          {cleanText(card.grade, "--")}
                        </p>
                      </div>
                    </div>
                  </Card>
                ))}
              </div>
            </section>
          ) : null}
        </>
      ) : null}
    </DashboardLayout>
  );
}

function SubjectProgressPreview({ data = [] }) {
  const items = (Array.isArray(data) ? data : [])
    .map((item) => ({
      label: formatChartLabel(item?.label, "Subject"),
      value: Math.max(0, Math.min(100, Number(item?.value) || 0)),
    }))
    .filter((item) => item.label && Number.isFinite(item.value))
    .slice(0, 5);

  return (
    <Card className="p-4 sm:p-6">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="section-title">Subject progress</h3>
          <p className="mt-1 text-sm text-text-muted">
            Latest published scores.
          </p>
        </div>
        <Link
          to="/student/analytics"
          className="inline-flex min-h-11 shrink-0 items-center text-xs font-semibold text-primary hover:underline sm:min-h-0"
        >
          View all
        </Link>
      </div>
      {items.length === 0 ? (
        <p className="mt-4 rounded-2xl border border-dashed border-border bg-surface-muted/20 px-4 py-5 text-sm text-text-muted">
          No published subject scores yet.
        </p>
      ) : (
        <div className="mt-5 space-y-4">
          {items.map((item, index) => (
            <div key={`${item.label}-${index}`} className="space-y-2">
              <div className="flex items-center justify-between gap-3 text-xs sm:text-sm">
                <span className="min-w-0 whitespace-normal break-words font-semibold leading-5 text-text sm:truncate">
                  {item.label}
                </span>
                <span className="shrink-0 font-semibold text-text-muted">
                  {item.value}%
                </span>
              </div>
              <div className="h-2.5 rounded-full bg-surface-muted">
                <div
                  className="h-2.5 rounded-full"
                  style={{
                    width: `${item.value}%`,
                    backgroundColor:
                      PROGRESS_COLORS[index % PROGRESS_COLORS.length],
                  }}
                />
              </div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

function InfoTile({ label, value }) {
  return (
    <div className="rounded-2xl border border-border/70 bg-surface-muted/20 px-3 py-3 sm:px-4">
      <p className="text-xs font-semibold leading-5 text-text-soft sm:text-[11px] sm:uppercase sm:tracking-wide sm:text-text-muted">
        {label}
      </p>
      <p className="mt-1 whitespace-normal break-words text-sm font-semibold leading-5 text-text sm:truncate">{value}</p>
    </div>
  );
}

export default StudentDashboardPage;
