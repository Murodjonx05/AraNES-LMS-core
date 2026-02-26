from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from authx import AuthXConfig
from dotenv import load_dotenv

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


def _get_bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _get_required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _get_csv_env(name: str, default: str) -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


def _validate_cors(cors: "CorsConfig") -> None:
    if not cors.ALLOW_ORIGINS:
        raise RuntimeError("CORS_ALLOW_ORIGINS must contain at least one explicit origin.")
    if "*" in cors.ALLOW_ORIGINS:
        raise RuntimeError("CORS_ALLOW_ORIGINS cannot contain '*'. Use explicit trusted origins.")


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
    BOOTSTRAP_SUPERUSER_PROMPT: bool
    AUTH_CONFIG: AuthXConfig


def build_app_config() -> AppConfig:
    base_dir = Path(__file__).resolve().parent.parent
    load_dotenv(base_dir / ".env")

    data_dir = base_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    jwt_secret_key = _get_required_env("JWT_SECRET_KEY")
    cors = CorsConfig(
        ALLOW_ORIGINS=_get_csv_env("CORS_ALLOW_ORIGINS", "http://localhost:3000"),
        ALLOW_CREDENTIALS=_get_bool_env("CORS_ALLOW_CREDENTIALS", False),
        ALLOW_METHODS=_get_csv_env("CORS_ALLOW_METHODS", "*"),
        ALLOW_HEADERS=_get_csv_env("CORS_ALLOW_HEADERS", "*"),
    )
    _validate_cors(cors)

    auth_config = AuthXConfig(
        JWT_SECRET_KEY=jwt_secret_key,
        JWT_TOKEN_LOCATION=["headers"],
    )

    return AppConfig(
        BASE_DIR=base_dir,
        DATA_DIR=data_dir,
        HOST=os.getenv("HOST", "0.0.0.0"),
        PORT=int(os.getenv("PORT", "8000")),
        DATABASE_URL=os.getenv("DATABASE_URL", f"sqlite+aiosqlite:///{data_dir}/db.sqlite3"),
        CORS=cors.as_dict(),
        REQUIRED_LANGUAGES=REQUIRED_LANGUAGES,
        DEFAULT_ROLES=DEFAULT_ROLES,
        DEFAULT_SIGNUP_ROLE_ID=DEFAULT_SIGNUP_ROLE_ID,
        DEFAULT_SIGNUP_ROLE_NAME=DEFAULT_SIGNUP_ROLE_NAME,
        DEFAULT_SIGNUP_ROLE_TITLE_KEY=DEFAULT_SIGNUP_ROLE_TITLE_KEY,
        JWT_SECRET_KEY=jwt_secret_key,
        BOOTSTRAP_SUPERUSER_PROMPT=_get_bool_env("BOOTSTRAP_SUPERUSER_PROMPT", True),
        AUTH_CONFIG=auth_config,
    )


def get_app_config():
    from src.runtime import get_default_runtime

    return get_default_runtime().config


def get_security():
    from src.runtime import get_default_runtime

    return get_default_runtime().security


def __getattr__(name: str):
    if name == "APP":
        return get_app_config()
    if name == "SECURITY":
        return get_security()
    raise AttributeError(name)