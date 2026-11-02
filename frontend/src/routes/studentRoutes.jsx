/* eslint-disable react-refresh/only-export-components */

import { lazy } from "react";
import { Route } from "react-router-dom";

import { DashboardShell } from "../components/layout/DashboardLayout";
import RoleGuard from "./RoleGuard";
import RuntimeFeatureRoute from "./RuntimeFeatureRoute";

const CommunicationInboxPage = lazy(() => import("../pages/shared/CommunicationInboxPage"));
const MessagesPage = lazy(() => import("../pages/shared/MessagesPage"));
const NoticesPage = lazy(() => import("../pages/shared/NoticesPage"));
const RoleAnalyticsPage = lazy(() => import("../pages/shared/RoleAnalyticsPage"));
const RoleGettingStartedPage = lazy(() => import("../pages/shared/RoleGettingStartedPage"));
const RoleSettingsPage = lazy(() => import("../pages/shared/RoleSettingsPage"));
const SchoolCalendarPage = lazy(() => import("../pages/shared/SchoolCalendarPage"));
const StudentAttendancePage = lazy(() => import("../pages/student/StudentAttendancePage"));
const StudentChangePasswordPage = lazy(() => import("../pages/student/StudentChangePasswordPage"));
const StudentDashboardPage = lazy(() => import("../pages/student/StudentDashboardPage"));
const StudentParentLinkingPage = lazy(() => import("../pages/student/StudentParentLinkingPage"));
const StudentReportCardsPage = lazy(() => import("../pages/student/StudentReportCardsPage"));
const StudentSubjectDetailsPage = lazy(() => import("../pages/student/StudentSubjectDetailsPage"));
const StudentSubjectsPage = lazy(() => import("../pages/student/StudentSubjectsPage"));
const StudentTmaPage = lazy(() => import("../features/tma/student/StudentTmaPage"));

export const studentRoutes = (
  <Route element={<RoleGuard allowedRoles={["STUDENT"]} />}>
    <Route element={<DashboardShell role="student" onboardingModalEnabled={false} />}>
      <Route path="/student/change-password" element={<StudentChangePasswordPage />} />
    </Route>
    <Route element={<DashboardShell role="student" />}>
      <Route path="/student/dashboard" element={<StudentDashboardPage />} />
      <Route path="/student/getting-started" element={<RoleGettingStartedPage role="student" />} />
      <Route path="/student/analytics" element={<RoleAnalyticsPage role="student" />} />
      <Route path="/student/subjects" element={<StudentSubjectsPage />} />
      <Route path="/student/subjects/:subjectResultId" element={<StudentSubjectDetailsPage />} />
      <Route path="/student/subjects/:subjectResultId/tma/:assignmentId" element={<StudentTmaPage />} />
      <Route path="/student/parent-linking" element={<StudentParentLinkingPage />} />
      <Route path="/student/report-cards" element={<StudentReportCardsPage />} />
      <Route path="/student/attendance" element={<RuntimeFeatureRoute feature="attendance" role="student"><StudentAttendancePage /></RuntimeFeatureRoute>} />
      <Route path="/student/calendar" element={<SchoolCalendarPage role="student" />} />
      <Route path="/student/inbox" element={<CommunicationInboxPage />} />
      <Route path="/student/messages" element={<RuntimeFeatureRoute feature="messaging" role="student"><MessagesPage /></RuntimeFeatureRoute>} />
      <Route path="/student/notices" element={<NoticesPage />} />
      <Route path="/student/settings" element={<RoleSettingsPage role="student" />} />
    </Route>
  </Route>
);
