from __future__ import annotations

import logging
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


def _normalize_log_level(value: str | None) -> str | None:
    normalized = (value or "").strip().upper()
    if not normalized:
        return None
    level_names = logging.getLevelNamesMapping()
    level = level_names.get(normalized)
    if level is None:
        valid_values = ", ".join(sorted(level_names))
        raise ValueError(f"LOG_LEVEL must be one of: {valid_values}.")
    return str(logging.getLevelName(level))


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


@dataclass(frozen=True, slots=True)
class AppConfig:
    BASE_DIR: Path
    DATA_DIR: Path
    ENVIRONMENT: str
    HOST: str
    PORT: int
    DATABASE_URL: str
    CORS: dict[str, Any]
    REQUIRED_LANGUAGES: tuple[str, ...]
    DEFAULT_ROLES: tuple[tuple[int | None, str, str], ...]
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
    STARTUP_DB_BOOTSTRAP_ENABLED: bool
    PLUGIN_MANAGER_ENABLED: bool
    PLUGIN_GATEWAY_URL: str | None
    PLUGIN_GATEWAY_CACHE_TTL_SECONDS: float
    PLUGIN_START_PORT: int
    PLUGIN_READINESS_TIMEOUT: float
    PLUGIN_SERVICES_DIR: Path
    REDIS_ENABLED: bool
    REDIS_URL: str
    REDIS_DEFAULT_TTL_SECONDS: int
    REDIS_HEARTBEAT_ENABLED: bool
    REDIS_HEARTBEAT_SCHEDULE_SECONDS: tuple[int, ...]
    REDIS_COMMAND_TIMEOUT_SECONDS: float
    REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS: float
    REDIS_SOCKET_TIMEOUT_SECONDS: float
    OPERABILITY_DB_CHECK_TIMEOUT_SECONDS: float
    INPROCESS_HTTP_ROUTE_CACHE_MAX_ENTRIES: int
    INPROCESS_HTTP_EXTERNAL_TIMEOUT_SECONDS: float
    INPROCESS_HTTP_EXTERNAL_CONNECT_TIMEOUT_SECONDS: float
    INPROCESS_HTTP_LOCAL_READ_TIMEOUT_SECONDS: float
    PLUGIN_GATEWAY_HTTP_TIMEOUT_SECONDS: float
    PLUGIN_GATEWAY_OPENAPI_FETCH_TIMEOUT_SECONDS: float
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
    STARTUP_DB_BOOTSTRAP_ENABLED: bool = True
    PLUGIN_MANAGER_ENABLED: bool = True
    PLUGIN_GATEWAY_URL: str | None = None
    PLUGIN_GATEWAY_CACHE_TTL_SECONDS: float = 2.0
    PLUGIN_START_PORT: int = 10000
    PLUGIN_READINESS_TIMEOUT: float = 20.0

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
    REDIS_COMMAND_TIMEOUT_SECONDS: float = 3.0
    REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS: float = 3.0
    REDIS_SOCKET_TIMEOUT_SECONDS: float = 5.0
    OPERABILITY_DB_CHECK_TIMEOUT_SECONDS: float = 2.0
    INPROCESS_HTTP_ROUTE_CACHE_MAX_ENTRIES: int = 4096
    INPROCESS_HTTP_EXTERNAL_TIMEOUT_SECONDS: float = 5.0
    INPROCESS_HTTP_EXTERNAL_CONNECT_TIMEOUT_SECONDS: float = 2.0
    INPROCESS_HTTP_LOCAL_READ_TIMEOUT_SECONDS: float = 120.0
    PLUGIN_GATEWAY_HTTP_TIMEOUT_SECONDS: float = 30.0
    PLUGIN_GATEWAY_OPENAPI_FETCH_TIMEOUT_SECONDS: float = 10.0

    @field_validator(
        "JWT_SECRET_KEY",
        "ENVIRONMENT",
        "LOG_LEVEL",
        "HOST",
        "DATABASE_URL",
        "REDIS_URL",
        "PLUGIN_GATEWAY_URL",
        mode="before",
    )
    @classmethod
    def _strip_string_values(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("PLUGIN_GATEWAY_URL", mode="after")
    @classmethod
    def _normalize_plugin_gateway_url(cls, value: str | None) -> str | None:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        return value.strip() if isinstance(value, str) else value

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

    @field_validator("PLUGIN_START_PORT", mode="after")
    @classmethod
    def _validate_plugin_start_port(cls, value: int) -> int:
        return _validate_int_range("PLUGIN_START_PORT", value, minimum=1, maximum=65535)

    @field_validator("PLUGIN_READINESS_TIMEOUT", mode="after")
    @classmethod
    def _validate_plugin_readiness_timeout(cls, value: float) -> float:
        if value < 1.0 or value > 120.0:
            raise ValueError("PLUGIN_READINESS_TIMEOUT must be between 1.0 and 120.0 seconds.")
        return value

    @field_validator("PLUGIN_GATEWAY_CACHE_TTL_SECONDS", mode="after")
    @classmethod
    def _validate_plugin_gateway_cache_ttl_seconds(cls, value: float) -> float:
        if value < 0.0 or value > 300.0:
            raise ValueError("PLUGIN_GATEWAY_CACHE_TTL_SECONDS must be between 0.0 and 300.0 seconds.")
        return value

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

    @field_validator("REDIS_COMMAND_TIMEOUT_SECONDS", mode="after")
    @classmethod
    def _validate_redis_command_timeout(cls, value: float) -> float:
        if value < 0.5 or value > 60.0:
            raise ValueError("REDIS_COMMAND_TIMEOUT_SECONDS must be between 0.5 and 60.0 seconds.")
        return value

    @field_validator("REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS", mode="after")
    @classmethod
    def _validate_redis_socket_connect_timeout(cls, value: float) -> float:
        if value < 0.5 or value > 120.0:
            raise ValueError("REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS must be between 0.5 and 120.0 seconds.")
        return value

    @field_validator("REDIS_SOCKET_TIMEOUT_SECONDS", mode="after")
    @classmethod
    def _validate_redis_socket_timeout(cls, value: float) -> float:
        if value < 0.5 or value > 120.0:
            raise ValueError("REDIS_SOCKET_TIMEOUT_SECONDS must be between 0.5 and 120.0 seconds.")
        return value

    @field_validator("OPERABILITY_DB_CHECK_TIMEOUT_SECONDS", mode="after")
    @classmethod
    def _validate_operability_db_check_timeout(cls, value: float) -> float:
        if value < 0.25 or value > 60.0:
            raise ValueError("OPERABILITY_DB_CHECK_TIMEOUT_SECONDS must be between 0.25 and 60.0 seconds.")
        return value

    @field_validator("INPROCESS_HTTP_ROUTE_CACHE_MAX_ENTRIES", mode="after")
    @classmethod
    def _validate_inprocess_route_cache(cls, value: int) -> int:
        return _validate_int_range(
            "INPROCESS_HTTP_ROUTE_CACHE_MAX_ENTRIES",
            value,
            minimum=256,
            maximum=131072,
        )

    @field_validator("INPROCESS_HTTP_EXTERNAL_TIMEOUT_SECONDS", mode="after")
    @classmethod
    def _validate_inprocess_external_timeout(cls, value: float) -> float:
        if value < 1.0 or value > 300.0:
            raise ValueError("INPROCESS_HTTP_EXTERNAL_TIMEOUT_SECONDS must be between 1.0 and 300.0 seconds.")
        return value

    @field_validator("INPROCESS_HTTP_EXTERNAL_CONNECT_TIMEOUT_SECONDS", mode="after")
    @classmethod
    def _validate_inprocess_external_connect_timeout(cls, value: float) -> float:
        if value < 0.5 or value > 60.0:
            raise ValueError(
                "INPROCESS_HTTP_EXTERNAL_CONNECT_TIMEOUT_SECONDS must be between 0.5 and 60.0 seconds."
            )
        return value

    @field_validator("INPROCESS_HTTP_LOCAL_READ_TIMEOUT_SECONDS", mode="after")
    @classmethod
    def _validate_inprocess_local_read_timeout(cls, value: float) -> float:
        if value < 5.0 or value > 600.0:
            raise ValueError("INPROCESS_HTTP_LOCAL_READ_TIMEOUT_SECONDS must be between 5.0 and 600.0 seconds.")
        return value

    @field_validator("PLUGIN_GATEWAY_HTTP_TIMEOUT_SECONDS", mode="after")
    @classmethod
    def _validate_plugin_gateway_http_timeout(cls, value: float) -> float:
        if value < 5.0 or value > 600.0:
            raise ValueError("PLUGIN_GATEWAY_HTTP_TIMEOUT_SECONDS must be between 5.0 and 600.0 seconds.")
        return value

    @field_validator("PLUGIN_GATEWAY_OPENAPI_FETCH_TIMEOUT_SECONDS", mode="after")
    @classmethod
    def _validate_plugin_gateway_openapi_fetch_timeout(cls, value: float) -> float:
        if value < 2.0 or value > 120.0:
            raise ValueError(
                "PLUGIN_GATEWAY_OPENAPI_FETCH_TIMEOUT_SECONDS must be between 2.0 and 120.0 seconds."
            )
        return value

    @model_validator(mode="after")
    def _apply_runtime_defaults(self) -> "_AppSettings":
        if not self.JWT_SECRET_KEY:
            raise RuntimeError("Missing required environment variable: JWT_SECRET_KEY")
        self.LOG_LEVEL = _normalize_log_level(self.LOG_LEVEL) or _default_log_level(self.ENVIRONMENT)
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
            STARTUP_DB_BOOTSTRAP_ENABLED=self.STARTUP_DB_BOOTSTRAP_ENABLED,
            PLUGIN_MANAGER_ENABLED=self.PLUGIN_MANAGER_ENABLED,
            PLUGIN_GATEWAY_URL=self.PLUGIN_GATEWAY_URL,
            PLUGIN_GATEWAY_CACHE_TTL_SECONDS=self.PLUGIN_GATEWAY_CACHE_TTL_SECONDS,
            PLUGIN_START_PORT=self.PLUGIN_START_PORT,
            PLUGIN_READINESS_TIMEOUT=self.PLUGIN_READINESS_TIMEOUT,
            PLUGIN_SERVICES_DIR=base_dir / "services",
            REDIS_ENABLED=self.REDIS_ENABLED,
            REDIS_URL=self.REDIS_URL,
            REDIS_DEFAULT_TTL_SECONDS=self.REDIS_DEFAULT_TTL_SECONDS,
            REDIS_HEARTBEAT_ENABLED=self.REDIS_HEARTBEAT_ENABLED,
            REDIS_HEARTBEAT_SCHEDULE_SECONDS=self.REDIS_HEARTBEAT_SCHEDULE_SECONDS,
            REDIS_COMMAND_TIMEOUT_SECONDS=self.REDIS_COMMAND_TIMEOUT_SECONDS,
            REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS=self.REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS,
            REDIS_SOCKET_TIMEOUT_SECONDS=self.REDIS_SOCKET_TIMEOUT_SECONDS,
            OPERABILITY_DB_CHECK_TIMEOUT_SECONDS=self.OPERABILITY_DB_CHECK_TIMEOUT_SECONDS,
            INPROCESS_HTTP_ROUTE_CACHE_MAX_ENTRIES=self.INPROCESS_HTTP_ROUTE_CACHE_MAX_ENTRIES,
            INPROCESS_HTTP_EXTERNAL_TIMEOUT_SECONDS=self.INPROCESS_HTTP_EXTERNAL_TIMEOUT_SECONDS,
            INPROCESS_HTTP_EXTERNAL_CONNECT_TIMEOUT_SECONDS=self.INPROCESS_HTTP_EXTERNAL_CONNECT_TIMEOUT_SECONDS,
            INPROCESS_HTTP_LOCAL_READ_TIMEOUT_SECONDS=self.INPROCESS_HTTP_LOCAL_READ_TIMEOUT_SECONDS,
            PLUGIN_GATEWAY_HTTP_TIMEOUT_SECONDS=self.PLUGIN_GATEWAY_HTTP_TIMEOUT_SECONDS,
            PLUGIN_GATEWAY_OPENAPI_FETCH_TIMEOUT_SECONDS=self.PLUGIN_GATEWAY_OPENAPI_FETCH_TIMEOUT_SECONDS,
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
