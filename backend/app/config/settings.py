# ====================================== #
#             settings.py                #
# ====================================== #

"""Load and validate application settings from environment variables."""

import os
from datetime import timedelta
from enum import Enum
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from dotenv import dotenv_values
from pydantic import Field, field_validator, model_validator, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent
BASE_ENV_VALUES = dotenv_values(BASE_DIR / ".env")
ACTIVE_ENV = (
    os.getenv("ENV") or os.getenv("APP_ENV") or BASE_ENV_VALUES.get("ENV") or "dev"
).lower()

ENV_FILE_BY_NAME = {
    "dev": ".env.development",
    "development": ".env.development",
    "prod": ".env.production",
    "production": ".env.production",
    "stg": ".env.staging",
    "staging": ".env.staging",
}
ACTIVE_ENV_FILE = ENV_FILE_BY_NAME.get(ACTIVE_ENV, f".env.{ACTIVE_ENV}")


class EnvironmentType(str, Enum):
    DEVELOPMENT = "dev"
    PRODUCTION = "prod"
    STAGING = "stg"


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=(BASE_DIR / ".env", BASE_DIR / ACTIVE_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    ENV: EnvironmentType = EnvironmentType.DEVELOPMENT
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR"] | None = None
    APP_NAME: str = "School Management System"
    API_V1_PREFIX: str = "/api/v1"

    # ==========================================================
    # SENTRY OBSERVABILITY
    #
    # Sentry is optional in development and staging. Production
    # requires a DSN and treats initialization failure as fatal.
    # ==========================================================

    SENTRY_DSN: SecretStr | None = None
    SENTRY_RELEASE: str | None = None
    SENTRY_ERROR_SAMPLE_RATE: float = Field(default=1.0, ge=0.0, le=1.0)
    SENTRY_TRACES_SAMPLE_RATE: float = Field(default=0.0, ge=0.0, le=1.0)
    SENTRY_SHUTDOWN_TIMEOUT_SECONDS: float = Field(default=2.0, ge=0.1, le=10.0)
    SENTRY_DEBUG: bool = False

    SECRET_KEY: str = Field(..., min_length=32)
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 5
    DEFAULT_SESSION_DAYS: int = Field(default=7, gt=0)
    REMEMBER_ME_SESSION_DAYS: int = Field(default=30, gt=0)

    # DNS-01 is disabled until a rotated key and the Bunny zone ID are configured.
    BUNNY_DNS_API_KEY: SecretStr | None = None
    BUNNY_DNS_ZONE_ID: int | None = Field(default=None, gt=0)

    DATABASE_URL: str | None = None
    DB_POOL_SIZE: int = Field(default=5, ge=1, le=50)
    DB_MAX_OVERFLOW: int = Field(default=5, ge=0, le=100)
    DB_POOL_TIMEOUT_SECONDS: int = Field(default=10, ge=1, le=120)
    DB_POOL_RECYCLE_SECONDS: int = Field(default=1800, ge=60)

    OPENAI_API_KEY: str | None = None
    OPENAI_MODEL: str = "gpt-4o-mini"
    ANTHROPIC_API_KEY: str | None = None
    ANTHROPIC_MODEL: str = "claude-sonnet-4-5"
    LLM_MAX_TOKENS: int = 1024

    ALLOWED_ORIGINS: list[str] = Field(default_factory=list)
    TRUST_PROXY_HEADERS: bool = False
    TRUSTED_PROXY_HOPS: int = Field(default=1, ge=1, le=5)

    TWILIO_ACCOUNT_SID: str | None = None
    TWILIO_AUTH_TOKEN: str | None = None
    TWILIO_WHATSAPP_FROM: str | None = None

    # ==========================================================
    # EMAIL DELIVERY
    # ==========================================================

    EMAIL_PROVIDER: Literal["legacy", "ses", "resend"] = "legacy"

    EMAIL_SENDER_NAME: str = "WEAVE"
    EMAIL_REPLY_TO: str | None = None

    # ==========================================================
    # LEGACY EMAIL DELIVERY
    #
    # Intended for development and staging. Production must use
    # a supported external provider (SES or Resend).
    # ==========================================================

    APP_SCRIPT_URL: str | None = None

    SMTP_HOST: str | None = None
    SMTP_PORT: int = Field(default=587, ge=1, le=65535)
    SMTP_FROM_EMAIL: str | None = None
    SMTP_PASSWORD: SecretStr | None = None

    # ==========================================================
    # AMAZON SES
    #
    # Required only when EMAIL_PROVIDER=ses.
    # ==========================================================

    AWS_REGION: str = "eu-west-1"

    AWS_ACCESS_KEY_ID: str | None = None
    AWS_SECRET_ACCESS_KEY: SecretStr | None = None
    AWS_SESSION_TOKEN: SecretStr | None = None

    # Primarily useful for local mocks such as LocalStack.
    AWS_SES_ENDPOINT_URL: str | None = None

    SES_TRANSACTIONAL_FROM_EMAIL: str = "no-reply@notifications.weavecloudspace.com"
    SES_SECURITY_FROM_EMAIL: str = "security@notifications.weavecloudspace.com"
    SES_BULK_FROM_EMAIL: str = "updates@updates.weavecloudspace.com"

    SES_TRANSACTIONAL_CONFIGURATION_SET: str = "weave-transactional"
    SES_SECURITY_CONFIGURATION_SET: str = "weave-security"

    SES_BULK_CONFIGURATION_SET: str = "weave-bulk"

    SES_CONNECT_TIMEOUT_SECONDS: int = Field(
        default=5,
        ge=1,
        le=30,
    )
    SES_READ_TIMEOUT_SECONDS: int = Field(
        default=10,
        ge=1,
        le=60,
    )
    SES_MAX_ATTEMPTS: int = Field(
        default=3,
        ge=1,
        le=10,
    )

    # ==========================================================
    # RESEND
    #
    # Required only when EMAIL_PROVIDER=resend.
    # ==========================================================

    RESEND_API_KEY: SecretStr | None = None
    RESEND_BASE_URL: str = "https://api.resend.com"
    RESEND_TRANSACTIONAL_FROM_EMAIL: str = "no-reply@weavecloudspace.com"
    RESEND_SECURITY_FROM_EMAIL: str = "security@weavecloudspace.com"
    RESEND_BULK_FROM_EMAIL: str = "updates@weavecloudspace.com"
    RESEND_TIMEOUT_SECONDS: float = Field(default=10.0, ge=1.0, le=60.0)

    @model_validator(mode="after")
    def validate_email_provider_settings(self) -> "Settings":
        """Validate email configuration according to the active environment."""

        def has_value(value: object) -> bool:
            """Return whether a normal or secret setting is non-empty."""

            if value is None:
                return False

            if isinstance(value, SecretStr):
                value = value.get_secret_value()

            return bool(str(value).strip())

        # ======================================================
        # SMTP VALIDATION
        # ======================================================

        smtp_values = {
            "SMTP_HOST": self.SMTP_HOST,
            "SMTP_FROM_EMAIL": self.SMTP_FROM_EMAIL,
            "SMTP_PASSWORD": self.SMTP_PASSWORD,
        }

        configured_smtp_values = {name: has_value(value) for name, value in smtp_values.items()}

        smtp_any_configured = any(configured_smtp_values.values())
        smtp_fully_configured = all(configured_smtp_values.values())

        # SMTP is optional, but partially configuring it is invalid.
        if smtp_any_configured and not smtp_fully_configured:
            missing_smtp_values = [
                name for name, configured in configured_smtp_values.items() if not configured
            ]

            raise ValueError(
                "SMTP configuration is incomplete. Missing: " + ", ".join(missing_smtp_values)
            )

        # ======================================================
        # APPS SCRIPT VALIDATION
        # ======================================================

        app_script_configured = has_value(self.APP_SCRIPT_URL)

        if app_script_configured:
            app_script_url = urlparse(self.APP_SCRIPT_URL.strip())

            if app_script_url.scheme not in {"http", "https"} or not app_script_url.netloc:
                raise ValueError("APP_SCRIPT_URL must be a valid absolute HTTP or HTTPS URL.")

        # ======================================================
        # PROVIDER ENDPOINT VALIDATION
        # ======================================================

        if has_value(self.AWS_SES_ENDPOINT_URL):
            ses_endpoint_url = urlparse(self.AWS_SES_ENDPOINT_URL.strip())

            if ses_endpoint_url.scheme not in {"http", "https"} or not ses_endpoint_url.netloc:
                raise ValueError("AWS_SES_ENDPOINT_URL must be a valid absolute HTTP or HTTPS URL.")

        resend_base_url = urlparse(self.RESEND_BASE_URL.strip())
        if resend_base_url.scheme != "https" or not resend_base_url.netloc:
            raise ValueError("RESEND_BASE_URL must be a valid absolute HTTPS URL.")

        # ======================================================
        # PRODUCTION POLICY
        # ======================================================

        if self.ENV == EnvironmentType.PRODUCTION and self.EMAIL_PROVIDER not in {
            "ses",
            "resend",
        }:
            raise ValueError(
                "Production email provider must be 'ses' or 'resend'. "
                "The legacy provider is not allowed."
            )

        # ======================================================
        # LEGACY PROVIDER
        #
        # Allowed only in development and staging.
        # At least one legacy transport must be available.
        # ======================================================

        if self.EMAIL_PROVIDER == "legacy":
            if self.ENV == EnvironmentType.PRODUCTION:
                raise ValueError("The legacy email provider cannot be used in production.")

            if not app_script_configured and not smtp_fully_configured:
                raise ValueError(
                    "EMAIL_PROVIDER is set to 'legacy', but neither "
                    "APP_SCRIPT_URL nor complete SMTP settings "
                    "are configured."
                )

        # ======================================================
        # AMAZON SES PROVIDER
        #
        # AWS credentials and SES routing are required only when
        # SES is the selected provider.
        # ======================================================

        elif self.EMAIL_PROVIDER == "ses":
            required_ses_values = {
                "AWS_REGION": self.AWS_REGION,
                "AWS_ACCESS_KEY_ID": self.AWS_ACCESS_KEY_ID,
                "AWS_SECRET_ACCESS_KEY": (self.AWS_SECRET_ACCESS_KEY),
                "SES_TRANSACTIONAL_FROM_EMAIL": (self.SES_TRANSACTIONAL_FROM_EMAIL),
                "SES_SECURITY_FROM_EMAIL": (self.SES_SECURITY_FROM_EMAIL),
                "SES_BULK_FROM_EMAIL": (self.SES_BULK_FROM_EMAIL),
                "SES_TRANSACTIONAL_CONFIGURATION_SET": (self.SES_TRANSACTIONAL_CONFIGURATION_SET),
                "SES_SECURITY_CONFIGURATION_SET": (self.SES_SECURITY_CONFIGURATION_SET),
                "SES_BULK_CONFIGURATION_SET": (self.SES_BULK_CONFIGURATION_SET),
            }

            missing_ses_values = [
                name for name, value in required_ses_values.items() if not has_value(value)
            ]

            if missing_ses_values:
                raise ValueError(
                    "Amazon SES configuration is incomplete. Missing: "
                    + ", ".join(missing_ses_values)
                )

        # ======================================================
        # RESEND PROVIDER
        # ======================================================

        elif self.EMAIL_PROVIDER == "resend":
            required_resend_values = {
                "RESEND_API_KEY": self.RESEND_API_KEY,
                "RESEND_TRANSACTIONAL_FROM_EMAIL": self.RESEND_TRANSACTIONAL_FROM_EMAIL,
                "RESEND_SECURITY_FROM_EMAIL": self.RESEND_SECURITY_FROM_EMAIL,
                "RESEND_BULK_FROM_EMAIL": self.RESEND_BULK_FROM_EMAIL,
            }
            missing_resend_values = [
                name for name, value in required_resend_values.items() if not has_value(value)
            ]

            if missing_resend_values:
                raise ValueError(
                    "Resend configuration is incomplete. Missing: "
                    + ", ".join(missing_resend_values)
                )

        return self

    SECURITY_ALERTS_ENABLED: bool = True
    SECURITY_ALERT_EMAIL: str | None = None
    BOOTSTRAP_SUPERADMIN_ID: str = "550e8400-e29b-41d4-a716-446655440000"
    BOOTSTRAP_SUPERADMIN_EMAIL: str | None = None
    BOOTSTRAP_SUPERADMIN_PASSWORD: str | None = None

    OTP_EXPIRATION_MINUTES: int = 10
    TENANT_ACTIVATION_EXPIRATION_HOURS: int = 48

    FRONTEND_APP_URL: str = Field(...)
    EMAIL_BRAND_LOGO_URL: str | None = None
    STUDENT_ACCESS_CODE_EXPIRY_HOURS: int = 48
    STUDENT_ACCESS_CODE_LENGTH: int = 8

    BULK_IMPORT_RESULT_ENCRYPTION_KEY: str | None = None
    BULK_IMPORT_SETUP_CODE_RETENTION_HOURS: int = Field(default=24, ge=1, le=168)
    BULK_IMPORT_STALE_AFTER_MINUTES: int = Field(default=20, ge=5, le=180)

    PAYSTACK_SECRET_KEY: str | None = None
    PAYSTACK_BASE_URL: str = "https://api.paystack.co"
    PAYSTACK_CALLBACK_URL: str | None = None
    PAYSTACK_AI_CREDIT_CALLBACK_URL: str | None = None
    PAYSTACK_PLUS_TERM_AMOUNT_KOBO: int = Field(default=1500000, ge=0)
    PAYSTACK_PROFESSIONAL_TERM_AMOUNT_KOBO: int = Field(default=3500000, ge=0)
    PAYSTACK_ENTERPRISE_TERM_AMOUNT_KOBO: int = Field(default=8000000, ge=0)

    REDIS_URL: str | None = None
    REALTIME_REDIS_URL: str | None = None
    CACHE_ENABLED: bool = False
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_REDIS_URL: str | None = None

    LOGIN_IP_LIMIT_5M: int = Field(default=20, gt=0)
    LOGIN_IP_LIMIT_1H: int = Field(default=100, gt=0)
    LOGIN_IDENTIFIER_FAIL_LIMIT_10M: int = Field(default=5, gt=0)
    LOGIN_IDENTIFIER_FAIL_LIMIT_1H: int = Field(default=15, gt=0)
    LOGIN_IDENTIFIER_IP_FAIL_LIMIT_10M: int = Field(default=5, gt=0)
    OTP_EMAIL_COOLDOWN_SECONDS: int = Field(default=60, gt=0)
    OTP_EMAIL_LIMIT_10M: int = Field(default=5, gt=0)
    OTP_EMAIL_LIMIT_24H: int = Field(default=12, gt=0)
    OTP_IP_LIMIT_1H: int = Field(default=20, gt=0)
    OTP_VERIFY_EMAIL_FAIL_LIMIT_10M: int = Field(default=5, gt=0)
    OTP_VERIFY_IP_FAIL_LIMIT_1H: int = Field(default=30, gt=0)

    CACHE_DEFAULT_TTL_SECONDS: int = Field(default=300, gt=0)
    CACHE_SHORT_TTL_SECONDS: int = Field(default=60, gt=0)
    CACHE_LONG_TTL_SECONDS: int = Field(default=1800, gt=0)

    MEDIA_STORAGE_PROVIDER: Literal["local", "r2"] = "local"
    R2_ACCOUNT_ID: str | None = None
    R2_ACCESS_KEY_ID: str | None = None
    R2_SECRET_ACCESS_KEY: str | None = None
    R2_ENDPOINT_URL: str | None = None
    R2_BUCKET_NAME: str = "weave-public-media"
    R2_PUBLIC_URL: str | None = None
    MEDIA_PUBLIC_BASE_URL: str | None = None
    MEDIA_MAX_LOGO_SIZE_BYTES: int = 1 * 1024 * 1024
    MEDIA_MAX_PASSPORT_SIZE_BYTES: int = 2 * 1024 * 1024
    MEDIA_ALLOWED_IMAGE_TYPES: list[str] = ["image/jpeg", "image/png", "image/webp"]

    # ==========================================================
    # CBT AI QUESTION GENERATOR CONFIG
    # Credits, feature flags, tenant balances, and generation limits
    # belong to the CBT AI domain/configuration layer.
    # ==========================================================
    CBT_AI_QUESTION_PROVIDER: Literal["gemini", "minimax"] = "gemini"
    CBT_AI_IMAGE_PROVIDER: Literal["gemini", "minimax"] = "gemini"
    CBT_AI_IMAGE_SEARCH_PROVIDER: Literal["openverse"] = "openverse"
    CBT_AI_CREDIT_UNIT_PRICE_KOBO: int = Field(default=2000, ge=0)
    CBT_AI_MINIMUM_PURCHASE_CREDITS: int = Field(default=1, gt=0)

    MINIMAX_API_KEY: SecretStr | None = None
    MINIMAX_BASE_URL: str = "https://api.minimax.io"
    MINIMAX_TEXT_MODEL: str = "MiniMax-M3"
    MINIMAX_IMAGE_MODEL: str = "image-01"
    MINIMAX_MAX_OUTPUT_TOKENS: int = Field(default=16384, ge=256, le=131072)
    MINIMAX_IMAGE_TIMEOUT_SECONDS: float = Field(default=120.0, ge=1.0, le=300.0)
    MINIMAX_REQUEST_TIMEOUT_SECONDS: float = Field(default=60.0, ge=1.0, le=300.0)

    GEMINI_API_KEY: SecretStr | None = None
    GEMINI_BASE_URL: str = "https://generativelanguage.googleapis.com/v1beta"
    GEMINI_TEXT_MODEL: str = "gemini-flash-lite-latest"
    GEMINI_IMAGE_MODEL: str = "gemini-2.5-flash-image"
    GEMINI_MAX_OUTPUT_TOKENS: int = Field(default=16384, ge=256, le=131072)
    GEMINI_IMAGE_TIMEOUT_SECONDS: float = Field(default=120.0, ge=1.0, le=300.0)
    GEMINI_REQUEST_TIMEOUT_SECONDS: float = Field(default=60.0, ge=1.0, le=300.0)

    OPENVERSE_BASE_URL: str = "https://api.openverse.org/v1"
    OPENVERSE_CLIENT_ID: str | None = None
    OPENVERSE_CLIENT_SECRET: SecretStr | None = None
    OPENVERSE_REQUEST_TIMEOUT_SECONDS: float = Field(default=15.0, ge=1.0, le=60.0)

    @field_validator(
        "CACHE_DEFAULT_TTL_SECONDS",
        "CACHE_SHORT_TTL_SECONDS",
        "CACHE_LONG_TTL_SECONDS",
        mode="before",
    )
    @classmethod
    def parse_cache_ttl(cls, value: object) -> int:
        if value is None or value == "":
            raise ValueError("Cache TTL values cannot be empty.")
        if isinstance(value, timedelta):
            return int(value.total_seconds())
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str):
            raw_value = value.strip()
            if not raw_value:
                raise ValueError("Cache TTL values cannot be blank.")
            return int(float(raw_value))
        raise ValueError("Cache TTL values must be seconds.")

    @field_validator("MINIMAX_BASE_URL", "GEMINI_BASE_URL", "OPENVERSE_BASE_URL")
    @classmethod
    def validate_cbt_api_service_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        try:
            parsed = urlparse(normalized)
            port = parsed.port
            valid = (
                parsed.scheme == "https"
                and bool(parsed.hostname)
                and parsed.username is None
                and parsed.password is None
                and not parsed.query
                and not parsed.fragment
                and not any(char.isspace() for char in normalized)
                and "\\" not in normalized
                and (port is None or port > 0)
            )
        except ValueError:
            valid = False
        if not valid:
            raise ValueError(
                "CBT AI service URLs must be absolute HTTPS URLs without "
                "credentials, query strings, or fragments."
            )
        return normalized

    @field_validator(
        "MINIMAX_TEXT_MODEL", "MINIMAX_IMAGE_MODEL", "GEMINI_TEXT_MODEL", "GEMINI_IMAGE_MODEL"
    )
    @classmethod
    def validate_cbt_ai_model_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("CBT AI model names cannot be blank.")
        return normalized

    @field_validator("MINIMAX_API_KEY", "GEMINI_API_KEY", "OPENVERSE_CLIENT_SECRET")
    @classmethod
    def normalize_optional_cbt_ai_secret(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        normalized = value.get_secret_value().strip()
        if not normalized:
            return None
        return SecretStr(normalized)

    @field_validator("OPENVERSE_CLIENT_ID")
    @classmethod
    def normalize_optional_openverse_client_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_settings(self) -> "Settings":
        if not self.DATABASE_URL:
            raise ValueError("DATABASE_URL must be set for the active environment.")
        if self.CACHE_ENABLED and not self.REDIS_URL:
            raise ValueError("REDIS_URL must be set when CACHE_ENABLED is true.")
        if not (
            self.CACHE_SHORT_TTL_SECONDS
            <= self.CACHE_DEFAULT_TTL_SECONDS
            <= self.CACHE_LONG_TTL_SECONDS
        ):
            raise ValueError(
                "CACHE_TTL values must satisfy CACHE_SHORT_TTL_SECONDS <= "
                "CACHE_DEFAULT_TTL_SECONDS <= CACHE_LONG_TTL_SECONDS."
            )
        if not self.is_production_like:
            return self

        if len(self.SECRET_KEY.strip()) < 48:
            raise ValueError(
                "SECRET_KEY must contain at least 48 characters in staging/production."
            )
        if not self.REDIS_URL:
            raise ValueError(
                "REDIS_URL is required in staging/production for queues and rate limiting."
            )
        if self.RATE_LIMIT_ENABLED and not (self.RATE_LIMIT_REDIS_URL or self.REDIS_URL):
            raise ValueError("Redis must be configured when production rate limiting is enabled.")
        if (
            not self.BULK_IMPORT_RESULT_ENCRYPTION_KEY
            or len(self.BULK_IMPORT_RESULT_ENCRYPTION_KEY.strip()) < 32
        ):
            raise ValueError(
                "BULK_IMPORT_RESULT_ENCRYPTION_KEY must contain at least 32 characters in staging/production."
            )
        if not self.TRUST_PROXY_HEADERS:
            raise ValueError(
                "TRUST_PROXY_HEADERS must be enabled behind the staging/production reverse proxy."
            )
        if not self.ALLOWED_ORIGINS:
            raise ValueError(
                "ALLOWED_ORIGINS must contain explicit HTTPS origins in staging/production."
            )
        if "*" in self.ALLOWED_ORIGINS:
            raise ValueError("Wildcard CORS origins are forbidden in staging/production.")
        for origin in self.ALLOWED_ORIGINS:
            parsed = urlparse(origin)
            if parsed.scheme != "https" or not parsed.netloc:
                raise ValueError(f"Production CORS origin must be an absolute HTTPS URL: {origin}")

        frontend_url = urlparse(self.FRONTEND_APP_URL)
        if frontend_url.scheme != "https" or not frontend_url.netloc:
            raise ValueError(
                "FRONTEND_APP_URL must be an absolute HTTPS URL in staging/production."
            )

        if self.ENV == EnvironmentType.PRODUCTION:
            sentry_dsn = self.SENTRY_DSN
            if isinstance(sentry_dsn, SecretStr):
                sentry_dsn = sentry_dsn.get_secret_value()
            if not sentry_dsn or not str(sentry_dsn).strip():
                raise ValueError("SENTRY_DSN is required in production.")

            if self.MEDIA_STORAGE_PROVIDER != "r2":
                raise ValueError(
                    "Production media storage must use R2; local Railway storage is ephemeral."
                )
            required_r2_values = {
                "R2_ACCOUNT_ID": self.R2_ACCOUNT_ID,
                "R2_ACCESS_KEY_ID": self.R2_ACCESS_KEY_ID,
                "R2_SECRET_ACCESS_KEY": self.R2_SECRET_ACCESS_KEY,
                "R2_ENDPOINT_URL": self.R2_ENDPOINT_URL,
                "R2_PUBLIC_URL": self.R2_PUBLIC_URL,
            }
            missing = [name for name, value in required_r2_values.items() if not value]
            if missing:
                raise ValueError(f"Missing production R2 settings: {', '.join(missing)}")

        return self

    @property
    def is_development(self) -> bool:
        return self.ENV == EnvironmentType.DEVELOPMENT

    @property
    def is_production_like(self) -> bool:
        return self.ENV in {EnvironmentType.STAGING, EnvironmentType.PRODUCTION}


settings = Settings()  # pyright: ignore[reportCallIssue]
