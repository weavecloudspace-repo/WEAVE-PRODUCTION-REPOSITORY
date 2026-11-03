from __future__ import annotations

from dataclasses import dataclass

from app.config.logging import get_logger
from app.config.settings import settings
from app.core.exceptions import TooManyRequestsException
from app.core.rate_limits.keys import (
    build_rate_limit_key,
    digest_key_part,
    normalize_identifier,
)
from app.core.rate_limits.redis_limiter import RedisFixedWindowRateLimiter


logger = get_logger(__name__)


@dataclass(frozen=True)
class RateLimitRule:
    """One concrete rate-limit bucket policy."""

    key: str
    limit: int
    window_seconds: int


class AuthRateLimitService:
    """Auth-specific Redis rate-limit policy layer."""

    _limiter = RedisFixedWindowRateLimiter()

    @staticmethod
    def _enabled() -> bool:
        return bool(settings.RATE_LIMIT_ENABLED)

    @staticmethod
    def _value(value: object) -> str:
        return getattr(value, "value", str(value))

    @staticmethod
    def _safe_ip(ip_address: str | None) -> str:
        return ip_address or "unknown"

    @classmethod
    def _identifier_hash(cls, identifier: str) -> str:
        return digest_key_part(normalize_identifier(identifier))

    @classmethod
    def _email_hash(cls, email: str) -> str:
        return digest_key_part(email.strip().lower())

    @classmethod
    def _ip_hash(cls, ip_address: str | None) -> str:
        return digest_key_part(cls._safe_ip(ip_address))

    @staticmethod
    def _log_rejection(
        *,
        rules: list[RateLimitRule],
        states: list,
        reason: str,
        scope: str,
        phase: str,
    ) -> None:
        """Internal-only diagnostics. Never log raw identifiers, IPs or Redis keys."""
        for rule, state in zip(rules, states):
            if state.allowed:
                continue
            logger.warning(
                "auth_rate_limit.rejected",
                extra={
                    "rate_limit_reason": reason,
                    "rate_limit_scope": scope,
                    "rate_limit_phase": phase,
                    "rate_limit_bucket": (\n                        "identifier-ip" if ":identifier-ip:" in rule.key\n                        else "identifier" if ":identifier:" in rule.key\n                        else "ip" if ":ip:" in rule.key\n                        else "email" if ":email:" in rule.key\n                        else "other"\n                    ),\n                    "rate_limit_window_seconds": rule.window_seconds,
                    "rate_limit_backend_unavailable": state.backend_unavailable,
                    "rate_limit_limit": rule.limit,
                    "rate_limit_current": state.current,
                    "rate_limit_retry_after_seconds": state.retry_after,
                },
            )

    @classmethod
    async def _enforce_rules(
        cls,
        rules: list[RateLimitRule],
        *,
        detail: str,
        reason: str,
        scope: str,
    ) -> None:
        """Check all buckets first, then consume all when currently allowed."""

        if not cls._enabled():
            return

        states = [
            await cls._limiter.status(
                rule.key,
                limit=rule.limit,
                window_seconds=rule.window_seconds,
            )
            for rule in rules
        ]

        blocked = [state for state in states if not state.allowed]
        if blocked:
            cls._log_rejection(rules=rules, states=states, reason=reason, scope=scope, phase="status")
            retry_after = max(state.retry_after for state in blocked)
            raise TooManyRequestsException(
                detail=detail,
                retry_after=max(retry_after, 1),
                reason=reason,
                scope=scope,
            )

        for rule in rules:
            result = await cls._limiter.consume(
                rule.key,
                limit=rule.limit,
                window_seconds=rule.window_seconds,
            )
            if not result.allowed:
                cls._log_rejection(rules=[rule], states=[result], reason=reason, scope=scope, phase="consume")
                raise TooManyRequestsException(
                    detail=detail,
                    retry_after=max(result.retry_after, 1),
                    reason=reason,
                    scope=scope,
                )

    @classmethod
    async def _assert_not_blocked(
        cls,
        rules: list[RateLimitRule],
        *,
        detail: str,
        reason: str,
        scope: str,
    ) -> None:
        """Check current bucket state without consuming."""

        if not cls._enabled():
            return

        states = [
            await cls._limiter.status(
                rule.key,
                limit=rule.limit,
                window_seconds=rule.window_seconds,
            )
            for rule in rules
        ]

        blocked = [state for state in states if not state.allowed]
        if blocked:
            retry_after = max(state.retry_after for state in blocked)
            raise TooManyRequestsException(
                detail=detail,
                retry_after=max(retry_after, 1),
                reason=reason,
                scope=scope,
            )

    @classmethod
    def _login_ip_rules(cls, ip_address: str | None) -> list[RateLimitRule]:
        ip_hash = cls._ip_hash(ip_address)

        return [
            RateLimitRule(
                key=build_rate_limit_key("auth", "login", "ip", ip_hash, "5m"),
                limit=settings.LOGIN_IP_LIMIT_5M,
                window_seconds=300,
            ),
            RateLimitRule(
                key=build_rate_limit_key("auth", "login", "ip", ip_hash, "1h"),
                limit=settings.LOGIN_IP_LIMIT_1H,
                window_seconds=3600,
            ),
        ]

    @classmethod
    def _login_failure_rules(
        cls,
        *,
        identifier: str,
        ip_address: str | None,
    ) -> list[RateLimitRule]:
        identifier_hash = cls._identifier_hash(identifier)
        ip_hash = cls._ip_hash(ip_address)

        return [
            RateLimitRule(
                key=build_rate_limit_key(
                    "auth", "login", "fail", "identifier", identifier_hash, "10m"
                ),
                limit=settings.LOGIN_IDENTIFIER_FAIL_LIMIT_10M,
                window_seconds=600,
            ),
            RateLimitRule(
                key=build_rate_limit_key(
                    "auth", "login", "fail", "identifier", identifier_hash, "1h"
                ),
                limit=settings.LOGIN_IDENTIFIER_FAIL_LIMIT_1H,
                window_seconds=3600,
            ),
            RateLimitRule(
                key=build_rate_limit_key(
                    "auth",
                    "login",
                    "fail",
                    "identifier-ip",
                    identifier_hash,
                    ip_hash,
                    "10m",
                ),
                limit=settings.LOGIN_IDENTIFIER_IP_FAIL_LIMIT_10M,
                window_seconds=600,
            ),
        ]

    @classmethod
    async def check_login_allowed(
        cls,
        *,
        identifier: str,
        ip_address: str | None,
    ) -> None:
        """Apply login attempt and failed-login limits."""

        await cls._enforce_rules(
            cls._login_ip_rules(ip_address),
            detail=(
                "Login is temporarily locked from this device because there were too many "
                "recent attempts. Correct passwords are also blocked until the countdown ends."
            ),
            reason="login_attempt_rate_limit",
            scope="ip",
        )

        await cls._assert_not_blocked(
            cls._login_failure_rules(identifier=identifier, ip_address=ip_address),
            detail=(
                "Login is temporarily locked for this account because there were too many "
                "failed attempts. Correct passwords are also blocked until the countdown ends."
            ),
            reason="login_failed_credentials_rate_limit",
            scope="identifier",
        )

    @classmethod
    async def record_failed_login(
        cls,
        *,
        identifier: str,
        ip_address: str | None,
    ) -> None:
        """Record failed credential validation."""

        if not cls._enabled():
            return

        for rule in cls._login_failure_rules(identifier=identifier, ip_address=ip_address):
            await cls._limiter.consume(
                rule.key,
                limit=rule.limit,
                window_seconds=rule.window_seconds,
            )

    @classmethod
    async def clear_login_failures(
        cls,
        *,
        identifier: str,
        ip_address: str | None,
    ) -> None:
        """Clear failed-login counters after a successful login."""

        if not cls._enabled():
            return

        await cls._limiter.clear(
            rule.key
            for rule in cls._login_failure_rules(identifier=identifier, ip_address=ip_address)
        )

    @classmethod
    def _otp_request_ip_rules(
        cls,
        *,
        purpose: object,
        ip_address: str | None,
    ) -> list[RateLimitRule]:
        ip_hash = cls._ip_hash(ip_address)
        purpose_value = cls._value(purpose)

        return [
            RateLimitRule(
                key=build_rate_limit_key("auth", "otp-request", "ip", ip_hash, purpose_value, "1h"),
                limit=settings.OTP_IP_LIMIT_1H,
                window_seconds=3600,
            )
        ]

    @classmethod
    def _otp_verify_failure_rules(
        cls,
        *,
        email: str,
        purpose: object,
        ip_address: str | None,
    ) -> list[RateLimitRule]:
        email_hash = cls._email_hash(email)
        ip_hash = cls._ip_hash(ip_address)
        purpose_value = cls._value(purpose)

        return [
            RateLimitRule(
                key=build_rate_limit_key(
                    "auth",
                    "otp-verify",
                    "fail",
                    "email",
                    email_hash,
                    purpose_value,
                    "10m",
                ),
                limit=settings.OTP_VERIFY_EMAIL_FAIL_LIMIT_10M,
                window_seconds=600,
            ),
            RateLimitRule(
                key=build_rate_limit_key(
                    "auth", "otp-verify", "fail", "ip", ip_hash, purpose_value, "1h"
                ),
                limit=settings.OTP_VERIFY_IP_FAIL_LIMIT_1H,
                window_seconds=3600,
            ),
        ]

    @classmethod
    async def check_otp_request_ip_allowed(
        cls,
        *,
        purpose: object,
        ip_address: str | None,
    ) -> None:
        """Apply coarse IP limit before generating/sending OTP."""

        await cls._enforce_rules(
            cls._otp_request_ip_rules(purpose=purpose, ip_address=ip_address),
            detail="Too many OTP requests from this device. Please wait before requesting another code.",
            reason="otp_request_rate_limit",
            scope="ip",
        )

    @classmethod
    async def check_otp_verify_allowed(
        cls,
        *,
        email: str,
        purpose: object,
        ip_address: str | None,
    ) -> None:
        """Block OTP verification if there are too many recent failures."""

        await cls._assert_not_blocked(
            cls._otp_verify_failure_rules(
                email=email,
                purpose=purpose,
                ip_address=ip_address,
            ),
            detail="OTP verification is temporarily locked after too many invalid code attempts.",
            reason="otp_verify_failed_attempts_rate_limit",
            scope="email",
        )

    @classmethod
    async def record_failed_otp_verification(
        cls,
        *,
        email: str,
        purpose: object,
        ip_address: str | None,
    ) -> None:
        """Record a wrong OTP attempt."""

        if not cls._enabled():
            return

        for rule in cls._otp_verify_failure_rules(
            email=email,
            purpose=purpose,
            ip_address=ip_address,
        ):
            await cls._limiter.consume(
                rule.key,
                limit=rule.limit,
                window_seconds=rule.window_seconds,
            )

    @classmethod
    async def clear_otp_verification_failures(
        cls,
        *,
        email: str,
        purpose: object,
        ip_address: str | None,
    ) -> None:
        """Clear wrong OTP counters after successful verification."""

        if not cls._enabled():
            return

        await cls._limiter.clear(
            rule.key
            for rule in cls._otp_verify_failure_rules(
                email=email,
                purpose=purpose,
                ip_address=ip_address,
            )
        )
