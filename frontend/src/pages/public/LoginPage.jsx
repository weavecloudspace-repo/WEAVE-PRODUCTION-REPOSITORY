import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import {
  ArrowRight,
  CheckCircle2,
  Clock3,
  LockKeyhole,
  TriangleAlert,
} from "lucide-react";
import AuthLayout from "../../components/layout/AuthLayout";
import SessionBootstrapScreen from "../../components/layout/SessionBootstrapScreen";
import Input from "../../components/ui/Input";
import Button from "../../components/ui/Button";
import { authService } from "../../services/auth.service";
import { authSession, parseApiError } from "../../services/api";

const ROLE_ROUTES = {
  SUPERADMIN: "/superadmin/dashboard",
  ADMIN: "/admin/dashboard",
  TEACHER: "/teacher/dashboard",
  STUDENT: "/student/dashboard",
  PARENT: "/parent/dashboard",
};

const ACCOUNT_SCHOOL_ROUTES = {
  TEACHER: "/teacher/schools",
  PARENT: "/parent/schools",
};

const safeInvitationReturnTo = (value) => {
  if (
    typeof value !== "string" ||
    !value.startsWith("/") ||
    value.startsWith("//")
  ) {
    return "";
  }
  if (
    value.startsWith("/parent-invitations/") ||
    value.startsWith("/teacher-invitations/")
  ) {
    return value;
  }
  return "";
};

const resolvePostLoginRoute = (data, role) => {
  const actorType = String(
    data?.actor_type || data?.user?.actor_type || ""
  ).toLowerCase();
  const tenantId = data?.tenant_id || data?.user?.tenant_id || null;
  const membershipSelectionRequired = Boolean(
    data?.membership_selection_required ||
      data?.user?.membership_selection_required ||
      data?.user?.meta?.membership_selection_required
  );
  const isGlobalAccount = ["parent_account", "teacher_account"].includes(
    actorType
  );

  if (
    ACCOUNT_SCHOOL_ROUTES[role] &&
    (isGlobalAccount || membershipSelectionRequired || !tenantId)
  ) {
    return ACCOUNT_SCHOOL_ROUTES[role];
  }

  return ROLE_ROUTES[role] || "/";
};

const formatCountdown = (totalSeconds) => {
  const safeSeconds = Math.max(Number(totalSeconds) || 0, 0);
  const minutes = Math.floor(safeSeconds / 60);
  const seconds = safeSeconds % 60;

  if (minutes <= 0) {
    return `${seconds}s`;
  }

  return `${minutes}m ${String(seconds).padStart(2, "0")}s`;
};

function Notice({ type = "success", children }) {
  const Icon = type === "error" ? TriangleAlert : CheckCircle2;
  const styles =
    type === "error"
      ? "border-error/20 bg-error-soft text-error"
      : "border-success/20 bg-success-soft text-emerald-700";

  return (
    <div
      className={`mb-4 flex gap-3 rounded-2xl border px-4 py-3 text-sm font-medium ${styles}`}
    >
      <Icon className="mt-0.5 h-4 w-4 shrink-0" />
      {children}
    </div>
  );
}

function LoginLockoutNotice({ seconds }) {
  const countdownLabel = formatCountdown(seconds);

  return (
    <div className="mb-4 rounded-2xl border border-error/25 bg-error-soft px-4 py-4 text-error">
      <div className="flex items-start gap-3">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-error/10">
          <LockKeyhole className="h-5 w-5" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="font-semibold">Login temporarily locked</p>
            <span className="inline-flex items-center gap-1 rounded-full bg-error/10 px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide">
              <Clock3 className="h-3 w-3" />
              {countdownLabel}
            </span>
          </div>
          <p className="mt-1 text-sm leading-6">
            Too many failed attempts were made for this login. For security,
            even the correct password will not work until the countdown ends.
          </p>
          <p className="mt-2 text-xs font-semibold uppercase tracking-wide">
            Next login attempt available in {countdownLabel}
          </p>
        </div>
      </div>
    </div>
  );
}

function LoginPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const justVerified = searchParams.get("verified") === "true";
  const passwordReset = searchParams.get("reset") === "true";
  const inviteCompleted = searchParams.get("invite") === "success";
  const returnTo = safeInvitationReturnTo(searchParams.get("returnTo"));
  const resumeRequested = searchParams.get("resume") === "1";
  const shouldRestoreSession = Boolean(
    !justVerified &&
      !passwordReset &&
      !inviteCompleted &&
      (resumeRequested || authSession.getUser())
  );

  const [formData, setFormData] = useState({
    identifier: "",
    password: "",
    remember: true,
  });
  const [isLoading, setIsLoading] = useState(false);
  const [isRestoringSession, setIsRestoringSession] = useState(
    shouldRestoreSession
  );
  const [error, setError] = useState(null);
  const [fieldErrors, setFieldErrors] = useState({});
  const [lockout, setLockout] = useState(() => {
    try {
      const saved = JSON.parse(localStorage.getItem("weave_login_lockout") || "null");
      return saved?.scope === "ip" && Number(saved.expiresAt) > Date.now()
        ? saved
        : null;
    } catch {
      return null;
    }
  });
  const [now, setNow] = useState(Date.now());
  const retryAfterSeconds = lockout
    ? Math.max(0, Math.ceil((lockout.expiresAt - now) / 1000))
    : 0;
  const [lockoutMessage, setLockoutMessage] = useState(null);

  useEffect(() => {
    if (!shouldRestoreSession) return undefined;

    let cancelled = false;

    const restoreSavedSession = async () => {
      try {
        const data = await authService.bootstrapSession();
        if (cancelled) return;

        if (!data) {
          setIsRestoringSession(false);
          return;
        }

        const role = String(data?.role || data?.user?.role || "").toUpperCase();
        const passwordResetRequired = Boolean(
          data?.user?.password_reset_required ?? data?.password_reset_required
        );

        if (role === "STUDENT" && passwordResetRequired) {
          navigate("/student/change-password", { replace: true });
          return;
        }

        navigate(returnTo || resolvePostLoginRoute(data, role), {
          replace: true,
        });
      } catch {
        if (!cancelled) {
          setIsRestoringSession(false);
        }
      }
    };

    restoreSavedSession();

    return () => {
      cancelled = true;
    };
  }, [navigate, returnTo, shouldRestoreSession]);

  useEffect(() => {
    const updateClock = () => setNow(Date.now());
    const intervalId = window.setInterval(updateClock, 1000);
    window.addEventListener("focus", updateClock);
    document.addEventListener("visibilitychange", updateClock);
    return () => {
      window.clearInterval(intervalId);
      window.removeEventListener("focus", updateClock);
      document.removeEventListener("visibilitychange", updateClock);
    };
  }, []);

  useEffect(() => {
    if (!lockout) return;
    if (lockout.expiresAt > now) return;
    setLockout(null);
    setLockoutMessage(null);
    localStorage.removeItem("weave_login_lockout");
  }, [lockout, now]);

  const lockoutCountdownLabel = useMemo(
    () => formatCountdown(retryAfterSeconds),
    [retryAfterSeconds]
  );

  const redirectToVerification = (
    identifier,
    notice,
    purpose = "verification",
    redirectTo = "/verify-otp"
  ) => {
    if (!identifier) return;
    authService.setPendingVerificationEmail(identifier);
    const query = new URLSearchParams({
      email: identifier,
      purpose,
    });
    if (returnTo) query.set("returnTo", returnTo);
    navigate(`${redirectTo}?${query.toString()}`, {
      replace: true,
      state: {
        notice,
        autoRequestOtp: true,
        source: "unverified-login",
      },
    });
  };

  const handleChange = (event) => {
    const { checked, name, type, value } = event.target;
    setFormData((prev) => ({
      ...prev,
      [name]: type === "checkbox" ? checked : value,
    }));
    setFieldErrors((prev) => ({
      ...prev,
      [name]: undefined,
      email: undefined,
    }));
    if (retryAfterSeconds <= 0) {
      setError(null);
      setLockoutMessage(null);
    }
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    if (lockout && lockout.expiresAt > Date.now()) return;

    setIsLoading(true);
    setError(null);
    setLockoutMessage(null);
    setFieldErrors({});

    try {
      const data = await authService.login(formData.identifier, formData.password, {
        remember: formData.remember,
      });

      localStorage.removeItem("weave_login_lockout");
      setLockout(null);
      authService.clearPendingVerificationEmail();
      const role = String(data?.role || data?.user?.role || "").toUpperCase();
      const passwordResetRequired = Boolean(
        data?.user?.password_reset_required ?? data?.password_reset_required
      );

      if (role === "STUDENT" && passwordResetRequired) {
        navigate("/student/change-password", { replace: true });
        return;
      }

      navigate(returnTo || resolvePostLoginRoute(data, role), { replace: true });
    } catch (err) {
      const apiError = parseApiError(
        err,
        "Invalid email/admission number or password."
      );
      if (Object.keys(apiError.fieldErrors || {}).length > 0) {
        setFieldErrors(apiError.fieldErrors);
      }
      if (apiError.verificationRequired) {
        redirectToVerification(
          apiError.email || formData.identifier,
          apiError.message,
          apiError.purpose || "verification",
          apiError.redirectTo || "/verify-otp"
        );
        return;
      }

      const retryAfter = Number(
        apiError.data?.next_allowed_in_seconds ||
          apiError.data?.retry_after_seconds ||
          apiError.retryAfter ||
          0
      );

      if (
        apiError.status === 429 &&
        Number.isFinite(retryAfter) &&
        retryAfter > 0
      ) {
        const roundedRetryAfter = Math.ceil(retryAfter);
        const scope = apiError.data?.rate_limit_scope === "ip" ? "ip" : "identifier";
        const nextLockout = {
          scope,
          expiresAt: Date.now() + roundedRetryAfter * 1000,
        };
        setNow(Date.now());
        setLockout(nextLockout);
        if (scope === "ip") {
          localStorage.setItem("weave_login_lockout", JSON.stringify(nextLockout));
        } else {
          localStorage.removeItem("weave_login_lockout");
        }
        setLockoutMessage(
          apiError.message ||
            "Login is temporarily locked after too many failed attempts. Correct passwords are also blocked until the countdown ends."
        );
        setError(null);
      } else {
        setError(apiError.message);
      }
    } finally {
      setIsLoading(false);
    }
  };

  const submitDisabled = isLoading || retryAfterSeconds > 0;

  if (isRestoringSession) {
    return <SessionBootstrapScreen />;
  }

  return (
    <AuthLayout
      title="Welcome back"
      description="Log in to continue into your school workspace."
      iconPosition="below"
      footer={
        <p className="mt-7 text-center text-sm text-text-soft">
          Need a workspace?{" "}
          <Link
            to="/register"
            className="font-semibold text-primary hover:text-primary-hover"
          >
            Start free
          </Link>
        </p>
      }
    >
      {justVerified && <Notice>Account verified. You can now log in.</Notice>}
      {passwordReset && (
        <Notice>Password reset successful. You can now log in.</Notice>
      )}
      {inviteCompleted && (
        <Notice>Account setup completed. You can now log in.</Notice>
      )}
      {retryAfterSeconds > 0 ? (
        <LoginLockoutNotice seconds={retryAfterSeconds} />
      ) : null}
      {lockoutMessage && retryAfterSeconds <= 0 ? (
        <Notice type="error">{lockoutMessage}</Notice>
      ) : null}
      {error && <Notice type="error">{error}</Notice>}

      <form onSubmit={handleSubmit} className="space-y-5">
        <Input
          label="Email or admission number"
          type="text"
          name="identifier"
          value={formData.identifier}
          onChange={handleChange}
          placeholder="name@school.edu or WVS-2026-12345"
          required
          error={fieldErrors.identifier || fieldErrors.email}
        />
        <Input
          label="Password"
          type="password"
          name="password"
          value={formData.password}
          onChange={handleChange}
          placeholder="Enter your password"
          required
          error={fieldErrors.password}
        />
        <div className="flex items-center justify-between gap-4 text-sm">
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              name="remember"
              checked={formData.remember}
              onChange={handleChange}
              className="h-4 w-4 rounded border-border accent-primary"
              disabled={retryAfterSeconds > 0}
            />
            <span className="text-text-soft">Remember me</span>
          </label>
          <Link
            to="/forgot-password"
            className="font-semibold text-primary hover:text-primary-hover"
          >
            Forgot password?
          </Link>
        </div>
        <Button type="submit" className="w-full" disabled={submitDisabled}>
          {isLoading
            ? "Logging in..."
            : retryAfterSeconds > 0
              ? `Login locked · ${lockoutCountdownLabel}`
              : "Log in to workspace"}
          <ArrowRight className="h-4 w-4" />
        </Button>
      </form>
    </AuthLayout>
  );
}

export default LoginPage;
