/* eslint-disable react-refresh/only-export-components */
import { lazy } from "react";
import { Route } from "react-router-dom";

import { DashboardShell } from "../components/layout/DashboardLayout";
import PullRefreshBoundary from "../components/layout/PullRefreshBoundary";
const AcademicHubOverviewPage = lazy(
  () => import("../pages/admin/AcademicHubOverviewPage"),
);
const AcademicWorkflowPage = lazy(
  () => import("../pages/admin/AcademicWorkflowPage"),
);
const AdminDashboardPage = lazy(
  () => import("../pages/admin/AdminDashboardPage"),
);
const AdminInvitationPage = lazy(
  () => import("../pages/admin/AdminInvitationPage"),
);
const AdminSearchDetailPage = lazy(
  () => import("../pages/admin/AdminSearchDetailPage"),
);
const AttendancePage = lazy(() => import("../pages/admin/AttendancePage"));
const BillingPage = lazy(() => import("../pages/admin/BillingPage"));
const CBTPairingCodePage = lazy(
  () => import("../pages/admin/CBTPairingCodePage"),
);
const CBTServerSetupPage = lazy(
  () => import("../pages/admin/CBTServerSetupPage"),
);
const CBTServerDocumentationPage = lazy(
  () => import("../pages/admin/CBTServerDocumentationPage"),
);
const CBTServersPage = lazy(() => import("../pages/admin/CBTServersPage"));
const CBTResultLedgerPage = lazy(
  () => import("../pages/admin/CBTResultLedgerPage"),
);
const InstitutionTypeSettingsPage = lazy(
  () => import("../pages/admin/InstitutionTypeSettingsPage"),
);
const ParentLinkManagementPage = lazy(
  () => import("../pages/admin/ParentLinkManagementPage"),
);
const ParentsPage = lazy(() => import("../pages/admin/ParentsPage"));
const ResponsiveSubscriptionOptionsPage = lazy(
  () => import("../pages/admin/ResponsiveSubscriptionOptionsPage"),
);
const StudentClassPlacementPage = lazy(
  () => import("../pages/admin/StudentClassPlacementPage"),
);
const StudentCreatePage = lazy(
  () => import("../pages/admin/StudentCreatePage"),
);
const StudentSlipsPage = lazy(() => import("../pages/admin/StudentSlipsPage"));
const StudentsPage = lazy(() => import("../pages/admin/StudentsPage"));
const SubscriptionVerifyPage = lazy(
  () => import("../pages/admin/SubscriptionVerifyPage"),
);
const TeachersPage = lazy(() => import("../pages/admin/TeachersPage"));
const TenantBrandingPage = lazy(
  () => import("../pages/admin/TenantBrandingPage"),
);
const UsagePage = lazy(() => import("../pages/admin/UsagePage"));
const NoticeManagementPage = lazy(
  () => import("../pages/shared/NoticeManagementPage"),
);
const NoticesPage = lazy(() => import("../pages/shared/NoticesPage"));
const CommunicationInboxPage = lazy(
  () => import("../pages/shared/CommunicationInboxPage"),
);
const MessagesPage = lazy(() => import("../pages/shared/MessagesPage"));
const RoleAnalyticsPage = lazy(
  () => import("../pages/shared/RoleAnalyticsPage"),
);
const RoleSettingsPage = lazy(() => import("../pages/shared/RoleSettingsPage"));
const SchoolCalendarPage = lazy(
  () => import("../pages/shared/SchoolCalendarPage"),
);
import AdminGettingStartedRoute from "./AdminGettingStartedRoute";
import BulkImportRouteGuard from "./BulkImportRouteGuard";
import CBTHistoricalAccessRouteGuard from "./CBTHistoricalAccessRouteGuard";
import RoleGuard from "./RoleGuard";
import RuntimeFeatureRoute from "./RuntimeFeatureRoute";
import SubscriptionFeatureRouteGuard from "./SubscriptionFeatureRouteGuard";
import { FEATURE_CODES } from "../features/subscriptions/subscriptionConfig";

const protectedWorkflow = (element) => (
  <PullRefreshBoundary>{element}</PullRefreshBoundary>
);

export const adminRoutes = (
  <Route element={<RoleGuard allowedRoles={["ADMIN"]} />}>
    <Route
      path="/billing/subscription/verify"
      element={<SubscriptionVerifyPage />}
    />
    <Route element={<DashboardShell role="admin" />}>
      <Route path="/admin/dashboard" element={<AdminDashboardPage />} />
      <Route path="/admin/getting-started" element={<AdminGettingStartedRoute />} />
      <Route path="/admin/getting-started/:step" element={<AdminGettingStartedRoute />} />
      <Route path="/admin/search/:resultKey" element={<AdminSearchDetailPage />} />
      <Route path="/admin/analytics" element={<RoleAnalyticsPage role="admin" />} />
      <Route path="/admin/calendar" element={<SchoolCalendarPage role="admin" />} />
      <Route path="/admin/invitations/:role" element={protectedWorkflow(<AdminInvitationPage />)} />
      <Route path="/admin/teachers" element={protectedWorkflow(<TeachersPage />)} />
      <Route path="/admin/students" element={protectedWorkflow(<StudentsPage />)} />
      <Route path="/admin/students/create" element={protectedWorkflow(<StudentCreatePage />)} />
      <Route path="/admin/students/class-placement" element={protectedWorkflow(<StudentClassPlacementPage />)} />
      <Route path="/admin/parents" element={protectedWorkflow(<ParentsPage />)} />
      <Route path="/admin/parents/links" element={protectedWorkflow(<ParentLinkManagementPage />)} />
      <Route path="/admin/imports" element={protectedWorkflow(<BulkImportRouteGuard />)} />
      <Route
        path="/admin/imports/:jobId/student-slips"
        element={protectedWorkflow(
          <BulkImportRouteGuard>
            <StudentSlipsPage />
          </BulkImportRouteGuard>,
        )}
      />
      <Route path="/admin/imports/:step" element={protectedWorkflow(<BulkImportRouteGuard />)} />
      <Route path="/admin/imports/:step/:jobId" element={protectedWorkflow(<BulkImportRouteGuard />)} />
      <Route
        path="/admin/attendance"
        element={
          <RuntimeFeatureRoute feature="attendance" role="admin">
            {protectedWorkflow(<AttendancePage />)}
          </RuntimeFeatureRoute>
        }
      />
      <Route path="/admin/academic" element={<AcademicHubOverviewPage />} />
      <Route path="/admin/academic/:workflow" element={protectedWorkflow(<AcademicWorkflowPage />)} />
      <Route path="/admin/billing" element={<BillingPage />} />
      <Route path="/admin/billing/plans" element={<ResponsiveSubscriptionOptionsPage />} />
      <Route
        path="/admin/cbt"
        element={protectedWorkflow(
          <CBTHistoricalAccessRouteGuard>
            <CBTServersPage />
          </CBTHistoricalAccessRouteGuard>,
        )}
      />
      <Route
        path="/admin/cbt/setup-server"
        element={protectedWorkflow(
          <SubscriptionFeatureRouteGuard featureCode={FEATURE_CODES.CBT_PAIRING}>
            <CBTServerSetupPage />
          </SubscriptionFeatureRouteGuard>,
        )}
      />
      <Route
        path="/admin/cbt/documentation"
        element={protectedWorkflow(
          <SubscriptionFeatureRouteGuard featureCode={FEATURE_CODES.CBT_PAIRING}>
            <CBTServerDocumentationPage />
          </SubscriptionFeatureRouteGuard>,
        )}
      />
      <Route
        path="/admin/cbt/results"
        element={protectedWorkflow(
          <CBTHistoricalAccessRouteGuard>
            <CBTResultLedgerPage />
          </CBTHistoricalAccessRouteGuard>,
        )}
      />
      <Route
        path="/admin/cbt/pairing-code"
        element={protectedWorkflow(
          <SubscriptionFeatureRouteGuard featureCode={FEATURE_CODES.CBT_PAIRING}>
            <CBTPairingCodePage />
          </SubscriptionFeatureRouteGuard>,
        )}
      />
      <Route path="/admin/usage" element={<UsagePage />} />
      <Route path="/admin/inbox" element={<CommunicationInboxPage />} />
      <Route
        path="/admin/messages"
        element={
          <RuntimeFeatureRoute feature="messaging" role="admin">
            <MessagesPage />
          </RuntimeFeatureRoute>
        }
      />
      <Route path="/admin/notices" element={<NoticeManagementPage mode="tenant-admin" />} />
      <Route path="/admin/notices/received" element={<NoticesPage />} />
      <Route path="/admin/settings" element={<RoleSettingsPage role="admin" />} />
      <Route
        path="/admin/settings/institution-type"
        element={<InstitutionTypeSettingsPage />}
      />
      <Route
        path="/admin/settings/branding"
        element={
          <SubscriptionFeatureRouteGuard featureCode={FEATURE_CODES.TENANT_BRANDING}>
            <TenantBrandingPage />
          </SubscriptionFeatureRouteGuard>
        }
      />
    </Route>
  </Route>
);
