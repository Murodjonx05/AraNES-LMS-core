import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from authx import AuthXConfig

from src.user_role.defaults import (
    DEFAULT_ROLES,
    DEFAULT_SIGNUP_ROLE_ID,
    DEFAULT_SIGNUP_ROLE_NAME,
    DEFAULT_SIGNUP_ROLE_TITLE_KEY,
)


def _get_bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class CorsConfig:
    ALLOW_ORIGINS: list[str] = field(default_factory=lambda: ["*"])
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
    base_dir = Path(__file__).resolve().parent.parent.parent
    data_dir = base_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    jwt_secret_key = os.getenv("JWT_SECRET_KEY") or secrets.token_urlsafe(32)
    cors = CorsConfig(
        ALLOW_ORIGINS=[item for item in os.getenv("CORS_ALLOW_ORIGINS", "*").split(",") if item],
        ALLOW_CREDENTIALS=_get_bool_env("CORS_ALLOW_CREDENTIALS", False),
        ALLOW_METHODS=[item for item in os.getenv("CORS_ALLOW_METHODS", "*").split(",") if item],
        ALLOW_HEADERS=[item for item in os.getenv("CORS_ALLOW_HEADERS", "*").split(",") if item],
    )

    auth_config = AuthXConfig(
        JWT_SECRET_KEY=jwt_secret_key,
        JWT_ACCESS_COOKIE_NAME=os.getenv("JWT_ACCESS_COOKIE_NAME", "cookie_access_token"),
        JWT_TOKEN_LOCATION=["cookies"],
        JWT_COOKIE_SECURE=_get_bool_env("JWT_COOKIE_SECURE", False),
        JWT_COOKIE_CSRF_PROTECT=_get_bool_env("JWT_COOKIE_CSRF_PROTECT", False),
    )

    return AppConfig(
        BASE_DIR=base_dir,
        DATA_DIR=data_dir,
        HOST=os.getenv("HOST", "0.0.0.0"),
        PORT=int(os.getenv("PORT", "8000")),
        DATABASE_URL=os.getenv("DATABASE_URL", f"sqlite+aiosqlite:///{data_dir}/db.sqlite3"),
        CORS=cors.as_dict(),
        REQUIRED_LANGUAGES=("en", "ru", "uz"),
        DEFAULT_ROLES=DEFAULT_ROLES,
        DEFAULT_SIGNUP_ROLE_ID=DEFAULT_SIGNUP_ROLE_ID,
        DEFAULT_SIGNUP_ROLE_NAME=DEFAULT_SIGNUP_ROLE_NAME,
        DEFAULT_SIGNUP_ROLE_TITLE_KEY=DEFAULT_SIGNUP_ROLE_TITLE_KEY,
        JWT_SECRET_KEY=jwt_secret_key,
        BOOTSTRAP_SUPERUSER_PROMPT=_get_bool_env("BOOTSTRAP_SUPERUSER_PROMPT", True),
        AUTH_CONFIG=auth_config,
    )
