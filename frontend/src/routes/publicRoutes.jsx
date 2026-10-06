/* eslint-disable react-refresh/only-export-components */

import { lazy } from "react";
import { Route } from "react-router-dom";

import PwaAwareLandingPage from "../pages/public/PwaAwareLandingPage";

const AICreditCompletePage = lazy(() => import("../pages/public/AICreditCompletePage"));
const AccountRegisterPage = lazy(() => import("../pages/public/AccountRegisterPage"));
const ForgotPasswordPage = lazy(() => import("../pages/public/ForgotPasswordPage"));
const InvitationAcceptancePage = lazy(() => import("../pages/public/InvitationAcceptancePage"));
const JoinPage = lazy(() => import("../pages/public/JoinPage"));
const LoginPage = lazy(() => import("../pages/public/LoginPage"));
const MaintenanceModePage = lazy(() => import("../pages/public/MaintenanceModePage"));
const NetworkBlockedPage = lazy(() => import("../pages/public/NetworkBlockedPage"));
const OTPValidationPage = lazy(() => import("../pages/public/otp_validationPage"));
const PricingPage = lazy(() => import("../pages/public/PricingPage"));
const RegisterPage = lazy(() => import("../pages/public/RegisterPage"));

export const publicRoutes = (
  <>
    <Route path="/" element={<PwaAwareLandingPage />} />
    <Route path="/payments/ai-credits/complete" element={<AICreditCompletePage />} />
    <Route path="/pricing" element={<PricingPage />} />
    <Route path="/join" element={<JoinPage />} />
    <Route path="/login" element={<LoginPage />} />
    <Route path="/maintenance" element={<MaintenanceModePage />} />
    <Route path="/network-blocked" element={<NetworkBlockedPage />} />
    <Route path="/register" element={<RegisterPage />} />
    <Route path="/parent/register" element={<AccountRegisterPage role="parent" />} />
    <Route path="/teacher/register" element={<AccountRegisterPage role="teacher" />} />
    <Route path="/verify-otp" element={<OTPValidationPage />} />
    <Route path="/parent-invitations/:token" element={<InvitationAcceptancePage role="parent" />} />
    <Route path="/teacher-invitations/:token" element={<InvitationAcceptancePage role="teacher" />} />
    <Route path="/forgot-password" element={<ForgotPasswordPage />} />
  </>
);
