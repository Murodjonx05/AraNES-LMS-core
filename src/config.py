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


def _normalize_environment(value: str | None) -> str:
    normalized = (value or "development").strip().lower()
    return normalized or "development"


def _default_log_level(environment: str) -> str:
    return "WARNING" if environment == "production" else "INFO"


def _parse_csv(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(item.strip() for item in value.split(",") if item.strip())
    if isinstance(value, (list, tuple)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return (str(value).strip(),) if str(value).strip() else ()


def _validate_int_range(
    name: str,
    value: int,
    *,
    minimum: int,
    maximum: int | None = None,
) -> int:
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}.")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} must be <= {maximum}.")
    return value


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


class _AppSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", case_sensitive=True, enable_decoding=False)

    JWT_SECRET_KEY: str
    ENVIRONMENT: str = "development"
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DATABASE_URL: str | None = None

    CORS_ALLOW_ORIGINS: tuple[str, ...] = ("http://localhost:3000",)
    CORS_ALLOW_CREDENTIALS: bool = False
    CORS_ALLOW_METHODS: tuple[str, ...] = ("*",)
    CORS_ALLOW_HEADERS: tuple[str, ...] = ("*",)

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
    REDIS_HEARTBEAT_SCHEDULE_SECONDS: tuple[int, ...] = (
        60,
        600,
        1200,
        3600,
        14400,
        28800,
        43200,
    )

    @field_validator(
        "JWT_SECRET_KEY",
        "ENVIRONMENT",
        "LOG_LEVEL",
        "HOST",
        "DATABASE_URL",
        "REDIS_URL",
        mode="before",
    )
    @classmethod
    def _strip_string_values(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator(
        "CORS_ALLOW_ORIGINS",
        "CORS_ALLOW_METHODS",
        "CORS_ALLOW_HEADERS",
        mode="before",
    )
    @classmethod
    def _parse_csv_fields(cls, value: object) -> tuple[str, ...]:
        return _parse_csv(value)

    @field_validator("REDIS_HEARTBEAT_SCHEDULE_SECONDS", mode="before")
    @classmethod
    def _parse_heartbeat_schedule(cls, value: object) -> tuple[int, ...]:
        items = _parse_csv(value)
        if not items:
            raise ValueError("REDIS_HEARTBEAT_SCHEDULE_SECONDS must contain at least one integer value.")
        try:
            return tuple(int(item) for item in items)
        except ValueError as exc:
            raise ValueError("REDIS_HEARTBEAT_SCHEDULE_SECONDS must contain integers only.") from exc

    @field_validator("ENVIRONMENT", mode="after")
    @classmethod
    def _normalize_environment_field(cls, value: str) -> str:
        return _normalize_environment(value)

    @field_validator("PORT", mode="after")
    @classmethod
    def _validate_port(cls, value: int) -> int:
        return _validate_int_range("PORT", value, minimum=1, maximum=65535)

    @field_validator("RATE_LIMIT_WINDOW_SECONDS", mode="after")
    @classmethod
    def _validate_rate_limit_window(cls, value: int) -> int:
        return _validate_int_range("RATE_LIMIT_WINDOW_SECONDS", value, minimum=1, maximum=86400)

    @field_validator("RATE_LIMIT_MAX_REQUESTS", mode="after")
    @classmethod
    def _validate_rate_limit_max_requests(cls, value: int) -> int:
        return _validate_int_range("RATE_LIMIT_MAX_REQUESTS", value, minimum=1, maximum=10000)

    @field_validator("REDIS_DEFAULT_TTL_SECONDS", mode="after")
    @classmethod
    def _validate_redis_default_ttl(cls, value: int) -> int:
        return _validate_int_range("REDIS_DEFAULT_TTL_SECONDS", value, minimum=1, maximum=604800)

    @field_validator("REDIS_HEARTBEAT_SCHEDULE_SECONDS", mode="after")
    @classmethod
    def _validate_heartbeat_schedule_range(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        if not value:
            raise ValueError("REDIS_HEARTBEAT_SCHEDULE_SECONDS must contain at least one integer value.")
        return tuple(
            _validate_int_range(
                "REDIS_HEARTBEAT_SCHEDULE_SECONDS",
                item,
                minimum=1,
                maximum=86400,
            )
            for item in value
        )

    @model_validator(mode="after")
    def _apply_runtime_defaults(self) -> "_AppSettings":
        if not self.JWT_SECRET_KEY:
            raise RuntimeError("Missing required environment variable: JWT_SECRET_KEY")
        if self.LOG_LEVEL is None:
            self.LOG_LEVEL = _default_log_level(self.ENVIRONMENT)
        else:
            self.LOG_LEVEL = self.LOG_LEVEL.upper()
        if self.REQUEST_LOG_ENABLED is None:
            self.REQUEST_LOG_ENABLED = self.ENVIRONMENT != "production"
        if self.AUDIT_LOG_ENABLED is None:
            self.AUDIT_LOG_ENABLED = True
        return self

    def as_app_config(self, *, base_dir: Path, data_dir: Path) -> AppConfig:
        cors = CorsConfig(
            ALLOW_ORIGINS=list(self.CORS_ALLOW_ORIGINS),
            ALLOW_CREDENTIALS=self.CORS_ALLOW_CREDENTIALS,
            ALLOW_METHODS=list(self.CORS_ALLOW_METHODS),
            ALLOW_HEADERS=list(self.CORS_ALLOW_HEADERS),
        )
        _validate_cors(cors)
        auth_config = AuthXConfig(
            JWT_SECRET_KEY=self.JWT_SECRET_KEY,
            JWT_TOKEN_LOCATION=["headers"],
        )
        database_url = self.DATABASE_URL or f"sqlite+aiosqlite:///{data_dir}/db.sqlite3"
        return AppConfig(
            BASE_DIR=base_dir,
            DATA_DIR=data_dir,
            ENVIRONMENT=self.ENVIRONMENT,
            HOST=self.HOST,
            PORT=self.PORT,
            DATABASE_URL=database_url,
            CORS=cors.as_dict(),
            REQUIRED_LANGUAGES=REQUIRED_LANGUAGES,
            DEFAULT_ROLES=DEFAULT_ROLES,
            DEFAULT_SIGNUP_ROLE_ID=DEFAULT_SIGNUP_ROLE_ID,
            DEFAULT_SIGNUP_ROLE_NAME=DEFAULT_SIGNUP_ROLE_NAME,
            DEFAULT_SIGNUP_ROLE_TITLE_KEY=DEFAULT_SIGNUP_ROLE_TITLE_KEY,
            JWT_SECRET_KEY=self.JWT_SECRET_KEY,
            LOG_LEVEL=self.LOG_LEVEL or _default_log_level(self.ENVIRONMENT),
            REQUEST_LOG_ENABLED=bool(self.REQUEST_LOG_ENABLED),
            AUDIT_LOG_ENABLED=bool(self.AUDIT_LOG_ENABLED),
            RATE_LIMIT_ENABLED=self.RATE_LIMIT_ENABLED,
            RATE_LIMIT_WINDOW_SECONDS=self.RATE_LIMIT_WINDOW_SECONDS,
            RATE_LIMIT_MAX_REQUESTS=self.RATE_LIMIT_MAX_REQUESTS,
            REDIS_ENABLED=self.REDIS_ENABLED,
            REDIS_URL=self.REDIS_URL,
            REDIS_DEFAULT_TTL_SECONDS=self.REDIS_DEFAULT_TTL_SECONDS,
            REDIS_HEARTBEAT_ENABLED=self.REDIS_HEARTBEAT_ENABLED,
            REDIS_HEARTBEAT_SCHEDULE_SECONDS=self.REDIS_HEARTBEAT_SCHEDULE_SECONDS,
            AUTH_CONFIG=auth_config,
        )


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

    return settings.as_app_config(base_dir=base_dir, data_dir=data_dir)


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
