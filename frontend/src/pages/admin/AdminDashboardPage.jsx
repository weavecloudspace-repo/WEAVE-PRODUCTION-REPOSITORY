import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  BarChart3,
  Bell,
  BookOpen,
  FileText,
  GraduationCap,
  PlusCircle,
  UploadCloud,
  Users,
} from "lucide-react";

import AnalyticsBarChart from "../../components/charts/AnalyticsBarChart";
import AIUsageDashboardCard from "../../features/ai/AIUsageDashboardCard";
import DashboardLayout from "../../components/layout/DashboardLayout";
import LoadingState from "../../components/shared/LoadingState";
import Button from "../../components/ui/Button";
import {
  DashboardFocusCard,
  DashboardListCard,
  DashboardMetricCard,
  DashboardQuickActions,
  DashboardWelcomePanel,
} from "../../components/dashboard/DashboardPrimitives";
import DashboardCalendarPanel from "../../features/schoolCalendar/components/DashboardCalendarPanel";
import { FEATURE_CODES } from "../../features/subscriptions/subscriptionConfig";
import { useSubscription } from "../../features/subscriptions/useSubscription";
import { authSession, getErrorMessage, isAbortError } from "../../services/api";
import { dashboardService } from "../../services/dashboard.service";
import { getCachedDashboardBundle, getDashboardSessionCacheKey } from "../../services/dashboardSessionCache";
import { cleanText } from "../../utils/academicDashboard";

const ADMIN_DASHBOARD_CACHE_KEY = getDashboardSessionCacheKey("admin:dashboard");

const metricNumber = (value, fallback = 0) => {
  const nextValue = Number(value);
  return Number.isFinite(nextValue) ? nextValue : fallback;
};

const chartData = (charts, key) => {
  const value = charts?.[key];
  return Array.isArray(value) ? value : [];
};

function AdminDashboardPage() {
  const [analytics, setAnalytics] = useState(null);
  const [error, setError] = useState(null);
  const { getFeatureGuard, planCode } = useSubscription();
  const user = authSession.getUser();
  const firstName = user?.first_name || user?.firstname || "Admin";
  const calendarScope = `${user?.tenant_id || "global"}:${user?.membership_id || ""}:${user?.id || user?.email || ""}`;
  const bulkImportGuard = getFeatureGuard(FEATURE_CODES.BULK_IMPORT);
  const canShowBulkImport = bulkImportGuard.allowed && String(planCode || "").toLowerCase() !== "free_trial";

  useEffect(() => {
    let mounted = true;
    const controller = new AbortController();
    let generation = 0;

    async function loadMetrics() {
      const request = ++generation;
      setError(null);
      try {
        const data = await getCachedDashboardBundle(ADMIN_DASHBOARD_CACHE_KEY, () =>
          dashboardService.getTenantAdminAnalytics({ signal: controller.signal }),
        );
        if (!mounted || controller.signal.aborted || request !== generation) return;
        setAnalytics(data);
      } catch (err) {
        if (!mounted || isAbortError(err) || request !== generation) return;
        setError(getErrorMessage(err, "Failed to load dashboard analytics."));
      }
    }

    loadMetrics();
    window.addEventListener("weave:dashboard-cache-invalidated", loadMetrics);

    return () => {
      window.removeEventListener("weave:dashboard-cache-invalidated", loadMetrics);
      mounted = false;
      controller.abort();
    };
  }, []);

  if (!analytics && !error) {
    return (
      <DashboardLayout role="admin" title="Dashboard">
        <LoadingState label="Loading dashboard..." />
      </DashboardLayout>
    );
  }

  const stats = analytics?.stats || {};
  const charts = analytics?.charts || {};
  const totalStudents = metricNumber(stats.total_students);
  const totalTeachers = metricNumber(stats.total_teachers);
  const totalParents = metricNumber(stats.total_parents);
  const totalClasses = metricNumber(stats.total_classes);
  const resultCompletion = metricNumber(stats.result_completion_percent);
  const submittedResults = metricNumber(stats.result_rows_submitted);
  const resultRowsTotal = metricNumber(stats.result_rows_total);
  const reportCardsPublished = metricNumber(stats.report_cards_published);
  const reportCardsGenerated = metricNumber(stats.report_cards_generated);
  const incompleteProfiles = metricNumber(stats.student_profiles_incomplete);
  const pendingTeachers = metricNumber(stats.pending_teacher_accounts);
  const pendingParents = metricNumber(stats.pending_parent_accounts);
  const schoolOverviewItems = [
    incompleteProfiles > 0
      ? {
          key: "profiles",
          title: "Incomplete student profiles",
          description: "Students with missing profile information.",
          icon: GraduationCap,
          tone: "warning",
          to: "/admin/students",
          value: incompleteProfiles,
        }
      : null,
    pendingTeachers > 0
      ? {
          key: "pending-teachers",
          title: "Pending teacher accounts",
          description: "Teacher accounts waiting for setup or verification.",
          icon: Users,
          tone: "warning",
          to: "/admin/teachers",
          value: pendingTeachers,
        }
      : null,
    pendingParents > 0
      ? {
          key: "pending-parents",
          title: "Pending parent accounts",
          description: "Parent accounts waiting for setup or verification.",
          icon: Users,
          tone: "warning",
          to: "/admin/parents",
          value: pendingParents,
        }
      : null,
    {
      key: "reports",
      title: "Report card publishing",
      description: `${reportCardsPublished} published from ${reportCardsGenerated} generated.`,
      icon: FileText,
      tone: reportCardsGenerated > reportCardsPublished ? "warning" : "success",
      to: "/admin/academic",
    },
  ].filter(Boolean);

  return (
    <DashboardLayout role="admin">
      <section className="admin-dashboard-header page-header">
        <div className="min-w-0">
          <h1 className="page-title">{firstName}'s Dashboard</h1>
        </div>
        <div className="page-header-actions">
          <Link to="/admin/students/create">
            <Button>
              <PlusCircle className="h-4 w-4" />
              Create student
            </Button>
          </Link>
        </div>
      </section>
      {error ? (
        <div className="rounded-2xl border border-error/30 bg-error-soft px-4 py-3 text-sm font-medium text-error">
          {error}
        </div>
      ) : null}

      {!error ? (
        <>
          <DashboardWelcomePanel
            variant="blue"
            eyebrow="Admin dashboard"
            title={`Welcome back, ${firstName}`}
            description="Key school signals and daily actions."
            profileCompletion={user?.onboarding_completed}
            chips={[
              { label: "Session", value: cleanText(stats.active_academic_session, "Not set"), tone: stats.active_academic_session ? "success" : "warning" },
              { label: "Term", value: cleanText(stats.active_academic_term, "Not set"), tone: stats.active_academic_term ? "primary" : "warning" },
            ]}
          />

          <section className="dashboard-kpi-grid dashboard-kpi-grid-four grid grid-cols-2 gap-3 sm:gap-4 xl:grid-cols-4">
            <DashboardMetricCard
              label="Students"
              value={totalStudents}
              description="Registered learners"
              icon={GraduationCap}
              tone="primary"
              to="/admin/students"
            />
            <DashboardMetricCard
              label="Teachers"
              value={totalTeachers}
              description="Teacher accounts"
              icon={Users}
              tone="success"
              to="/admin/teachers"
            />
            <DashboardMetricCard
              label="Classes"
              value={totalClasses}
              description="Academic groups"
              icon={BookOpen}
              tone="warning"
              to="/admin/academic/classes"
            />
            <DashboardMetricCard
              label="Parents"
              value={totalParents}
              description="Parent accounts"
              icon={Users}
              tone="accent"
              to="/admin/parents"
            />
          </section>

          <section className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(320px,0.8fr)]">
            <DashboardFocusCard
              title="School overview"
              description="Session, term, and report status at a glance."
              icon={BookOpen}
              tone="primary"
              primaryAction={{ to: "/admin/academic", label: "Open academic hub", icon: BookOpen }}
              secondaryAction={{ to: "/admin/analytics", label: "Advanced analytics", icon: BarChart3 }}
            >
              <div className="grid grid-cols-2 gap-3">
                <InfoTile label="Active session" value={cleanText(stats.active_academic_session, "Not set")} />
                <InfoTile label="Active term" value={cleanText(stats.active_academic_term, "Not set")} />
                <InfoTile label="Result completion" value={`${resultCompletion}%`} />
                <InfoTile label="Submitted results" value={`${submittedResults} / ${resultRowsTotal}`} />
                <InfoTile label="Generated reports" value={reportCardsGenerated} />
                <InfoTile label="Published reports" value={reportCardsPublished} />
              </div>
            </DashboardFocusCard>

            <DashboardListCard
              title="Needs attention"
              description="Items that may need admin follow-up."
              items={schoolOverviewItems}
              emptyTitle="School setup looks calm"
              emptyDescription="No pending account or publishing issue is showing on the dashboard."
            />
          </section>

          <AIUsageDashboardCard role="admin" />
          <section className="grid gap-5 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
            <DashboardCalendarPanel role="admin" admin actorId={user?.id || user?.email || ""} membershipId={user?.membership_id || ""} tenantId={user?.tenant_id || calendarScope} />
            <DashboardListCard
              title="Calendar quick actions"
              description="Use backend blockers and capability states before changing lifecycle."
              items={[
                {
                  key: "open-calendar",
                  title: "Open Calendar",
                  description: "Manage term calendar setup, days, and events.",
                  icon: BookOpen,
                  tone: "primary",
                  to: "/admin/academic/school-calendar",
                },
                {
                  key: "review-blockers",
                  title: "Review Blockers",
                  description: "Use term and session dependency previews before closure.",
                  icon: FileText,
                  tone: "warning",
                  to: "/admin/academic/terms",
                },
              ]}
            />
          </section>

          <section className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(320px,0.8fr)]">
            <AnalyticsBarChart
              title="Teacher submission progress"
              description="Submission progress by teacher."
              data={chartData(charts, "teacher_submission_progress")}
              emptyMessage="No teacher submission data available yet."
            />
            <DashboardQuickActions
              title="Quick actions"
              description="Common admin workflows."
              actions={[
                { label: "Create student", description: "Add a learner record", to: "/admin/students/create", icon: GraduationCap, tone: "primary" },
                canShowBulkImport
                  ? { label: "Bulk import", description: "Upload school records", to: "/admin/imports", icon: UploadCloud, tone: "success" }
                  : null,
                { label: "Academic hub", description: "Sessions, subjects, results", to: "/admin/academic", icon: BookOpen, tone: "warning" },
                { label: "Announcements", description: "Send school updates", to: "/admin/announcements", icon: Bell, tone: "accent" },
              ].filter(Boolean)}
            />
          </section>
        </>
      ) : null}
    </DashboardLayout>
  );
}

function InfoTile({ label, value }) {
  return (
    <div className="rounded-2xl border border-border/70 bg-surface-muted/20 px-3 py-3 sm:px-4">
      <p className="text-xs font-semibold leading-5 text-text-soft sm:text-[11px] sm:uppercase sm:tracking-wide sm:text-text-muted">{label}</p>
      <p className="mt-1 whitespace-normal break-words text-sm font-semibold leading-5 text-text sm:truncate">{value}</p>
    </div>
  );
}

export default AdminDashboardPage;
