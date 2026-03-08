from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from authx import AuthXConfig
from pydantic import ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.i18n.settings import REQUIRED_LANGUAGES
from src.user_role.defaults import (
    DEFAULT_ROLES,
    DEFAULT_SIGNUP_ROLE_ID,
    DEFAULT_SIGNUP_ROLE_NAME,
    DEFAULT_SIGNUP_ROLE_TITLE_KEY,
)

if TYPE_CHECKING:
    from authx import AuthX

APP: AppConfig
SECURITY: AuthX

__all__ = [
    "AppConfig",
    "CorsConfig",
    "build_app_config",
    "APP",
    "SECURITY",
    "get_app_config",
    "get_security",
]


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _normalize_environment(value: str | None) -> str:
    normalized = (value or "development").strip().lower()
    return normalized or "development"


def _default_log_level(environment: str) -> str:
    return "WARNING" if environment == "production" else "INFO"


def _validate_cors(cors: "CorsConfig") -> None:
    if not cors.ALLOW_ORIGINS:
        raise RuntimeError("CORS_ALLOW_ORIGINS must contain at least one explicit origin.")
    if "*" in cors.ALLOW_ORIGINS:
        raise RuntimeError("CORS_ALLOW_ORIGINS cannot contain '*'. Use explicit trusted origins.")
    for origin in cors.ALLOW_ORIGINS:
        parsed = urlparse(origin)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise RuntimeError(f"CORS_ALLOW_ORIGINS contains an invalid origin: {origin}")
        if parsed.params or parsed.query or parsed.fragment:
            raise RuntimeError(f"CORS_ALLOW_ORIGINS must not include query strings or fragments: {origin}")
        normalized_path = parsed.path.rstrip("/")
        if normalized_path:
            raise RuntimeError(f"CORS_ALLOW_ORIGINS must not include a path: {origin}")


@dataclass(slots=True)
class CorsConfig:
    ALLOW_ORIGINS: list[str] = field(default_factory=list)
    ALLOW_CREDENTIALS: bool = False
    ALLOW_METHODS: list[str] = field(default_factory=lambda: ["*"])
    ALLOW_HEADERS: list[str] = field(default_factory=lambda: ["*"])

    def as_dict(self) -> dict[str, Any]:
        return {
            "ALLOW_ORIGINS": self.ALLOW_ORIGINS,
            "ALLOW_CREDENTIALS": self.ALLOW_CREDENTIALS,
            "ALLOW_METHODS": self.ALLOW_METHODS,
            "ALLOW_HEADERS": self.ALLOW_HEADERS,
        }


@dataclass(slots=True)
class AppConfig:
    BASE_DIR: Path
    DATA_DIR: Path
    ENVIRONMENT: str
    HOST: str
    PORT: int
    DATABASE_URL: str
    CORS: dict[str, Any]
    REQUIRED_LANGUAGES: tuple[str, ...]
    DEFAULT_ROLES: tuple[tuple[int, str, str], ...]
    DEFAULT_SIGNUP_ROLE_ID: int
    DEFAULT_SIGNUP_ROLE_NAME: str
    DEFAULT_SIGNUP_ROLE_TITLE_KEY: str
    JWT_SECRET_KEY: str
    LOG_LEVEL: str
    REQUEST_LOG_ENABLED: bool
    AUDIT_LOG_ENABLED: bool
    RATE_LIMIT_ENABLED: bool
    RATE_LIMIT_WINDOW_SECONDS: int
    RATE_LIMIT_MAX_REQUESTS: int
    REDIS_ENABLED: bool
    REDIS_URL: str
    REDIS_DEFAULT_TTL_SECONDS: int
    REDIS_HEARTBEAT_ENABLED: bool
    REDIS_HEARTBEAT_SCHEDULE_SECONDS: tuple[int, ...]
    AUTH_CONFIG: AuthXConfig


def _require_int_range(
    name: str,
    value: int,
    *,
    minimum: int,
    maximum: int | None = None,
) -> int:
    if value < minimum:
        raise RuntimeError(f"{name} must be >= {minimum}.")
    if maximum is not None and value > maximum:
        raise RuntimeError(f"{name} must be <= {maximum}.")
    return value


def _require_int_tuple_range(
    name: str,
    values: tuple[int, ...],
    *,
    minimum: int,
    maximum: int | None = None,
) -> tuple[int, ...]:
    if not values:
        raise RuntimeError(f"{name} must contain at least one integer value.")
    for value in values:
        _require_int_range(name, value, minimum=minimum, maximum=maximum)
    return values


class _AppSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", case_sensitive=True)

    JWT_SECRET_KEY: str
    ENVIRONMENT: str = "development"
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DATABASE_URL: str | None = None

    CORS_ALLOW_ORIGINS: str = "http://localhost:3000"
    CORS_ALLOW_CREDENTIALS: bool = False
    CORS_ALLOW_METHODS: str = "*"
    CORS_ALLOW_HEADERS: str = "*"

    LOG_LEVEL: str | None = None
    REQUEST_LOG_ENABLED: bool | None = None
    AUDIT_LOG_ENABLED: bool | None = None
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_WINDOW_SECONDS: int = 60
    RATE_LIMIT_MAX_REQUESTS: int = 20

    REDIS_ENABLED: bool = False
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_DEFAULT_TTL_SECONDS: int = 3600
    REDIS_HEARTBEAT_ENABLED: bool = True
    REDIS_HEARTBEAT_SCHEDULE_SECONDS: str = "60,600,1200,3600,14400,28800,43200"

    @field_validator(
        "JWT_SECRET_KEY",
        "ENVIRONMENT",
        "LOG_LEVEL",
        "HOST",
        "DATABASE_URL",
        "REDIS_URL",
        "CORS_ALLOW_ORIGINS",
        "CORS_ALLOW_METHODS",
        "CORS_ALLOW_HEADERS",
        "REDIS_HEARTBEAT_SCHEDULE_SECONDS",
        mode="before",
    )
    @classmethod
    def _strip_string_values(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @model_validator(mode="after")
    def _validate_values(self) -> "_AppSettings":
        if not self.JWT_SECRET_KEY:
            raise RuntimeError("Missing required environment variable: JWT_SECRET_KEY")
        return self


def build_app_config() -> AppConfig:
    base_dir = Path(__file__).resolve().parent.parent
    data_dir = base_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    try:
        settings = _AppSettings(_env_file=base_dir / ".env")
    except ValidationError as exc:
        missing_jwt = any(
            error.get("loc") == ("JWT_SECRET_KEY",) and error.get("type") == "missing"
            for error in exc.errors()
        )
        if missing_jwt:
            raise RuntimeError("Missing required environment variable: JWT_SECRET_KEY") from exc
        raise RuntimeError(str(exc)) from exc
    cors = CorsConfig(
        ALLOW_ORIGINS=_split_csv(settings.CORS_ALLOW_ORIGINS),
        ALLOW_CREDENTIALS=settings.CORS_ALLOW_CREDENTIALS,
        ALLOW_METHODS=_split_csv(settings.CORS_ALLOW_METHODS),
        ALLOW_HEADERS=_split_csv(settings.CORS_ALLOW_HEADERS),
    )
    _validate_cors(cors)
    environment = _normalize_environment(settings.ENVIRONMENT)
    log_level = (settings.LOG_LEVEL or _default_log_level(environment)).upper()
    request_log_enabled = (
        settings.REQUEST_LOG_ENABLED
        if settings.REQUEST_LOG_ENABLED is not None
        else environment != "production"
    )
    audit_log_enabled = (
        settings.AUDIT_LOG_ENABLED
        if settings.AUDIT_LOG_ENABLED is not None
        else True
    )
    database_url = settings.DATABASE_URL or f"sqlite+aiosqlite:///{data_dir}/db.sqlite3"
    port = _require_int_range("PORT", settings.PORT, minimum=1, maximum=65535)
    rate_limit_window_seconds = _require_int_range(
        "RATE_LIMIT_WINDOW_SECONDS",
        settings.RATE_LIMIT_WINDOW_SECONDS,
        minimum=1,
        maximum=86400,
    )
    rate_limit_max_requests = _require_int_range(
        "RATE_LIMIT_MAX_REQUESTS",
        settings.RATE_LIMIT_MAX_REQUESTS,
        minimum=1,
        maximum=10000,
    )
    redis_default_ttl_seconds = _require_int_range(
        "REDIS_DEFAULT_TTL_SECONDS",
        settings.REDIS_DEFAULT_TTL_SECONDS,
        minimum=1,
        maximum=604800,
    )
    redis_heartbeat_schedule_seconds = _require_int_tuple_range(
        "REDIS_HEARTBEAT_SCHEDULE_SECONDS",
        tuple(int(item) for item in _split_csv(settings.REDIS_HEARTBEAT_SCHEDULE_SECONDS)),
        minimum=1,
        maximum=86400,
    )
    auth_config = AuthXConfig(
        JWT_SECRET_KEY=settings.JWT_SECRET_KEY,
        JWT_TOKEN_LOCATION=["headers"],
    )

    return AppConfig(
        BASE_DIR=base_dir,
        DATA_DIR=data_dir,
        ENVIRONMENT=environment,
        HOST=settings.HOST,
        PORT=port,
        DATABASE_URL=database_url,
        CORS=cors.as_dict(),
        REQUIRED_LANGUAGES=REQUIRED_LANGUAGES,
        DEFAULT_ROLES=DEFAULT_ROLES,
        DEFAULT_SIGNUP_ROLE_ID=DEFAULT_SIGNUP_ROLE_ID,
        DEFAULT_SIGNUP_ROLE_NAME=DEFAULT_SIGNUP_ROLE_NAME,
        DEFAULT_SIGNUP_ROLE_TITLE_KEY=DEFAULT_SIGNUP_ROLE_TITLE_KEY,
        JWT_SECRET_KEY=settings.JWT_SECRET_KEY,
        LOG_LEVEL=log_level,
        REQUEST_LOG_ENABLED=request_log_enabled,
        AUDIT_LOG_ENABLED=audit_log_enabled,
        RATE_LIMIT_ENABLED=settings.RATE_LIMIT_ENABLED,
        RATE_LIMIT_WINDOW_SECONDS=rate_limit_window_seconds,
        RATE_LIMIT_MAX_REQUESTS=rate_limit_max_requests,
        REDIS_ENABLED=settings.REDIS_ENABLED,
        REDIS_URL=settings.REDIS_URL,
        REDIS_DEFAULT_TTL_SECONDS=redis_default_ttl_seconds,
        REDIS_HEARTBEAT_ENABLED=settings.REDIS_HEARTBEAT_ENABLED,
        REDIS_HEARTBEAT_SCHEDULE_SECONDS=redis_heartbeat_schedule_seconds,
        AUTH_CONFIG=auth_config,
    )


def get_app_config() -> AppConfig:
    from src.runtime import get_default_runtime

    return get_default_runtime().config


def get_security() -> AuthX:
    from src.runtime import get_default_runtime

    return get_default_runtime().security


def __getattr__(name: str):
    if name == "APP":
        return get_app_config()
    if name == "SECURITY":
        return get_security()
    raise AttributeError(name)
