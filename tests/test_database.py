from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy.exc import IntegrityError

from src import database


class _FakeSession:
    def __init__(self) -> None:
        self.rollback_calls = 0
        self.close_calls = 0

    async def rollback(self) -> None:
        self.rollback_calls += 1

    async def close(self) -> None:
        self.close_calls += 1


class _SessionFactory:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    def __call__(self):
        return self._session


def test_resolve_session_factory_prefers_explicit_session_factory():
    explicit_factory = object()
    runtime_factory = object()
    request_factory = object()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=SimpleNamespace(session_factory=request_factory))))
    runtime = SimpleNamespace(session_factory=runtime_factory)

    resolved = database._resolve_session_factory(
        request=request,  # type: ignore[arg-type]
        runtime=runtime,  # type: ignore[arg-type]
        session_factory=explicit_factory,  # type: ignore[arg-type]
    )

    assert resolved is explicit_factory


def test_resolve_session_factory_prefers_runtime_over_request_runtime():
    runtime_factory = object()
    request_factory = object()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=SimpleNamespace(session_factory=request_factory))))
    runtime = SimpleNamespace(session_factory=runtime_factory)

    resolved = database._resolve_session_factory(
        request=request,  # type: ignore[arg-type]
        runtime=runtime,  # type: ignore[arg-type]
    )

    assert resolved is runtime_factory


def test_resolve_session_factory_uses_request_runtime_before_default_runtime():
    request_factory = object()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=SimpleNamespace(session_factory=request_factory))))

    with patch("src.database.get_default_runtime") as get_default_runtime_mock:
        resolved = database._resolve_session_factory(request=request)  # type: ignore[arg-type]

    assert resolved is request_factory
    get_default_runtime_mock.assert_not_called()


def test_resolve_session_factory_skips_partial_explicit_runtime_and_uses_request_runtime():
    request_factory = object()
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(runtime=SimpleNamespace(session_factory=request_factory)))
    )
    runtime = SimpleNamespace(security=object())

    with patch("src.database.get_default_runtime") as get_default_runtime_mock:
        resolved = database._resolve_session_factory(
            request=request,  # type: ignore[arg-type]
            runtime=runtime,  # type: ignore[arg-type]
        )

    assert resolved is request_factory
    get_default_runtime_mock.assert_not_called()


def test_resolve_session_factory_falls_back_to_default_runtime_when_request_runtime_is_partial():
    default_factory = object()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=SimpleNamespace(security=object()))))

    with patch(
        "src.database.get_default_runtime",
        return_value=SimpleNamespace(session_factory=default_factory),
    ) as get_default_runtime_mock:
        resolved = database._resolve_session_factory(request=request)  # type: ignore[arg-type]

    assert resolved is default_factory
    get_default_runtime_mock.assert_called_once_with()


@pytest.mark.asyncio
async def test_get_db_session_closes_session_on_success():
    session = _FakeSession()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=SimpleNamespace(session_factory=_SessionFactory(session)))))

    generator = database.get_db_session(request)  # type: ignore[arg-type]
    yielded = await anext(generator)
    assert yielded is session

    await generator.aclose()

    assert session.rollback_calls == 0
    assert session.close_calls == 1


@pytest.mark.asyncio
async def test_get_db_session_rolls_back_and_closes_on_error():
    session = _FakeSession()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=SimpleNamespace(session_factory=_SessionFactory(session)))))

    generator = database.get_db_session(request)  # type: ignore[arg-type]
    yielded = await anext(generator)
    assert yielded is session

    with pytest.raises(RuntimeError, match="boom"):
        await generator.athrow(RuntimeError("boom"))

    assert session.rollback_calls == 1
    assert session.close_calls == 1


@pytest.mark.asyncio
async def test_session_scope_rolls_back_and_closes_on_error():
    session = _FakeSession()
    runtime = SimpleNamespace(session_factory=_SessionFactory(session))

    with pytest.raises(RuntimeError, match="boom"):
        async with database.session_scope(runtime=runtime):  # type: ignore[arg-type]
            raise RuntimeError("boom")

    assert session.rollback_calls == 1
    assert session.close_calls == 1


def test_database_async_engine_attribute_uses_default_runtime_engine():
    engine = object()

    with patch("src.database.get_default_runtime", return_value=SimpleNamespace(engine=engine)):
        resolved = database.async_engine

    assert resolved is engine


def test_build_default_async_database_url_creates_data_dir(tmp_path: Path):
    url = database.build_default_async_database_url(base_dir=tmp_path)

    assert url == f"sqlite+aiosqlite:///{tmp_path / 'data' / 'db.sqlite3'}"
    assert (tmp_path / "data").is_dir()


def test_resolve_runtime_database_url_prefers_trimmed_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    monkeypatch.setenv("DATABASE_URL", "  postgresql+asyncpg://user:pass@db/app  ")

    assert database.resolve_runtime_database_url(base_dir=tmp_path) == "postgresql+asyncpg://user:pass@db/app"


@pytest.mark.parametrize(
    ("database_url", "expected"),
    [
        ("sqlite+aiosqlite:///./data/test.sqlite3", "sqlite:///./data/test.sqlite3"),
        ("postgresql+asyncpg://user:pass@db/app", "postgresql://user:pass@db/app"),
        ("postgresql+psycopg_async://user:pass@db/app", "postgresql+psycopg://user:pass@db/app"),
        ("mysql+aiomysql://user:pass@db/app", "mysql://user:pass@db/app"),
        ("mysql+asyncmy://user:pass@db/app", "mysql://user:pass@db/app"),
    ],
)
def test_to_sync_database_url_rewrites_known_async_drivers(database_url: str, expected: str):
    assert database.to_sync_database_url(database_url) == expected


def test_to_sync_database_url_leaves_sync_urls_unchanged():
    database_url = "postgresql+psycopg://user:pass@db/app"

    assert database.to_sync_database_url(database_url) == database_url


def test_escape_alembic_ini_value_doubles_percent_signs():
    database_url = "postgresql://user:pa%25ss@db/app"

    assert database.escape_alembic_ini_value(database_url) == "postgresql://user:pa%%25ss@db/app"


@pytest.mark.parametrize(
    ("database_url", "expected"),
    [
        ("sqlite+aiosqlite:///:memory:", True),
        ("sqlite:///:memory:", True),
        ("sqlite+aiosqlite:///./data/test.sqlite3", False),
        ("postgresql+asyncpg://user:pass@db/app", False),
    ],
)
def test_is_in_memory_sqlite_url_detects_only_sqlite_memory_urls(database_url: str, expected: bool):
    assert database.is_in_memory_sqlite_url(database_url) is expected


def test_is_unique_violation_matches_postgres_and_sqlite_messages():
    sqlite_exc = IntegrityError(
        statement="INSERT INTO users ...",
        params={},
        orig=Exception("UNIQUE constraint failed: users.username"),
    )
    postgres_exc = IntegrityError(
        statement="INSERT INTO users ...",
        params={},
        orig=Exception('duplicate key value violates unique constraint "users_username_key"'),
    )

    assert database.is_unique_violation(sqlite_exc, identifiers=("users.username",))
    assert database.is_unique_violation(postgres_exc, identifiers=("users_username_key",))


def test_is_unique_violation_rejects_unrelated_integrity_errors():
    exc = IntegrityError(
        statement="INSERT INTO users ...",
        params={},
        orig=Exception("foreign key constraint failed"),
    )

    assert database.is_unique_violation(exc, identifiers=("users.username",)) is False
