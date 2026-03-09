from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import os
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from src.runtime import RuntimeContext, get_default_runtime

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

    async_engine: AsyncEngine

_ASYNC_DRIVER_NAMES = {
    "aiomysql",
    "aiosqlite",
    "asyncmy",
    "asyncpg",
}
_UNIQUE_VIOLATION_MARKERS = (
    "unique constraint failed",
    "duplicate key value violates unique constraint",
    "duplicate entry",
)

__all__ = [
    "Model",
    "async_engine",
    "DbSession",
    "build_default_async_database_url",
    "escape_alembic_ini_value",
    "get_db_session",
    "is_in_memory_sqlite_url",
    "is_unique_violation",
    "resolve_runtime_database_url",
    "session_scope",
    "to_sync_database_url",
]


class Model(DeclarativeBase):
    pass


def build_default_async_database_url(*, base_dir: Path) -> str:
    data_dir = base_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return f"sqlite+aiosqlite:///{data_dir / 'db.sqlite3'}"


def resolve_runtime_database_url(*, base_dir: Path) -> str:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if database_url:
        return database_url
    return build_default_async_database_url(base_dir=base_dir)


def to_sync_database_url(database_url: str) -> str:
    normalized_url = database_url.strip()
    backend_and_driver, separator, remainder = normalized_url.partition("://")
    if not separator:
        return normalized_url

    backend, plus, driver_name = backend_and_driver.partition("+")
    if not plus:
        return normalized_url

    if driver_name == "psycopg_async":
        return f"{backend}+psycopg://{remainder}"
    if driver_name in _ASYNC_DRIVER_NAMES:
        return f"{backend}://{remainder}"
    return normalized_url


def escape_alembic_ini_value(value: str) -> str:
    # Alembic's config parser treats `%` as interpolation unless doubled first.
    return value.replace("%", "%%")


def is_in_memory_sqlite_url(database_url: str) -> bool:
    normalized_url = database_url.strip().lower()
    return normalized_url.startswith("sqlite") and ":memory:" in normalized_url


def is_unique_violation(exc: IntegrityError, *, identifiers: tuple[str, ...]) -> bool:
    message = str(getattr(exc, "orig", exc)).lower()
    if not any(marker in message for marker in _UNIQUE_VIOLATION_MARKERS):
        return False
    return any(identifier.lower() in message for identifier in identifiers)


def _runtime_session_factory(runtime: object | None) -> async_sessionmaker[AsyncSession] | None:
    if runtime is None:
        return None
    session_factory = getattr(runtime, "session_factory", None)
    if session_factory is None:
        return None
    return session_factory


def _request_runtime(request: Request | None) -> object | None:
    if request is None:
        return None
    app = getattr(request, "app", None)
    app_state = getattr(app, "state", None)
    return getattr(app_state, "runtime", None)


def _resolve_session_factory(
    *,
    request: Request | None = None,
    runtime: RuntimeContext | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> async_sessionmaker[AsyncSession]:
    if session_factory is not None:
        return session_factory
    runtime_session_factory = _runtime_session_factory(runtime)
    if runtime_session_factory is not None:
        return runtime_session_factory
    request_runtime_session_factory = _runtime_session_factory(_request_runtime(request))
    if request_runtime_session_factory is not None:
        return request_runtime_session_factory
    return get_default_runtime().session_factory


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    factory = _resolve_session_factory(request=request)
    session = factory()
    try:
        yield session
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


DbSession = Annotated[AsyncSession, Depends(get_db_session)]


@asynccontextmanager
async def session_scope(
    *,
    runtime: RuntimeContext | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> AsyncIterator[AsyncSession]:
    factory = _resolve_session_factory(runtime=runtime, session_factory=session_factory)
    session = factory()
    try:
        yield session
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


def __getattr__(name: str):
    if name == "async_engine":
        return get_default_runtime().engine
    raise AttributeError(name)
