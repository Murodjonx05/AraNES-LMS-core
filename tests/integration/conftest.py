from __future__ import annotations

import os
import shutil
import asyncio
import hashlib
import sqlite3
import uuid
from pathlib import Path
from typing import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config

TEST_JWT_SECRET = "test-secret-key-with-32-byte-minimum!!"
TEST_CORS_ORIGIN = "http://testserver"
TEST_PBKDF2_ITERATIONS = "100"

# Cached config to avoid rebuilding for each test
_cached_app_config = None


def _integration_template_cache_key(repo_root: Path) -> str:
    hasher = hashlib.sha256()
    watched_paths = [
        repo_root / "alembic.ini",
        repo_root / "migrations" / "env.py",
        repo_root / "src" / "startup" / "bootstrap.py",
        repo_root / "src" / "user_role" / "bootstrap.py",
        repo_root / "src" / "i18n" / "bootstrap.py",
        repo_root / "src" / "i18n" / "translates.py",
        repo_root / "src" / "user_role" / "translates.py",
        repo_root / "src" / "user_role" / "defaults.py",
        Path(__file__).resolve(),
    ]
    watched_paths.extend(sorted((repo_root / "migrations" / "versions").glob("*.py")))
    for path in watched_paths:
        if not path.exists():
            continue
        hasher.update(str(path.relative_to(repo_root)).encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(path.read_bytes())
        hasher.update(b"\0")
    return hasher.hexdigest()[:16]


def _integration_template_cache_dir(repo_root: Path) -> Path:
    key = _integration_template_cache_key(repo_root)
    return repo_root / ".pytest_cache" / "integration_db_templates" / key


def _has_superuser_seed(db_path: Path) -> bool:
    if not db_path.exists():
        return False
    try:
        con = sqlite3.connect(db_path)
        cur = con.cursor()
        # Table is named `users` in current migrations.
        row = cur.execute(
            "SELECT 1 FROM users WHERE username = ? LIMIT 1",
            ("superuser",),
        ).fetchone()
        return row is not None
    except sqlite3.Error:
        return False
    finally:
        try:
            con.close()  # type: ignore[name-defined]
        except Exception:
            pass


@pytest.fixture(scope="session")
def migrated_db_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """
    Build a migrated SQLite DB once per test session, then copy it per test for isolation.
    This avoids running Alembic in every integration test fixture.
    """
    repo_root = Path(__file__).resolve().parents[2]
    cache_dir = _integration_template_cache_dir(repo_root)
    cache_dir.mkdir(parents=True, exist_ok=True)
    template_db_path = cache_dir / "template.sqlite3"
    tmp_template_db_path = cache_dir / f"template.{uuid.uuid4().hex}.tmp.sqlite3"

    if template_db_path.exists():
        return template_db_path

    os.environ["JWT_SECRET_KEY"] = TEST_JWT_SECRET
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{tmp_template_db_path}"
    os.environ["CORS_ALLOW_ORIGINS"] = TEST_CORS_ORIGIN
    os.environ["CORS_ALLOW_CREDENTIALS"] = "false"
    os.environ["PBKDF2_ITERATIONS"] = TEST_PBKDF2_ITERATIONS

    alembic_cfg = Config(str(repo_root / "alembic.ini"))
    try:
        command.upgrade(alembic_cfg, "head")
        tmp_template_db_path.replace(template_db_path)
    finally:
        if tmp_template_db_path.exists():
            tmp_template_db_path.unlink()
    return template_db_path


@pytest.fixture(scope="session")
def seeded_db_template(migrated_db_template: Path) -> Path:
    """
    Prepare a fully bootstrapped template DB once (migrations + app startup seeding/superuser).
    Per-test fixtures will copy this DB and can skip lifespan startup for speed.
    """
    seeded_db_path = migrated_db_template.with_name("template-seeded.sqlite3")
    if _has_superuser_seed(seeded_db_path):
        return seeded_db_path
    if seeded_db_path.exists():
        seeded_db_path.unlink()
    tmp_seeded_db_path = seeded_db_path.with_name(f"template-seeded.{uuid.uuid4().hex}.tmp.sqlite3")
    shutil.copy2(migrated_db_template, tmp_seeded_db_path)

    os.environ["JWT_SECRET_KEY"] = TEST_JWT_SECRET
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{tmp_seeded_db_path}"
    os.environ["CORS_ALLOW_ORIGINS"] = TEST_CORS_ORIGIN
    os.environ["CORS_ALLOW_CREDENTIALS"] = "false"
    os.environ["PBKDF2_ITERATIONS"] = TEST_PBKDF2_ITERATIONS
    os.environ["BOOTSTRAP_SUPERUSER_CREATE"] = "true"
    os.environ["BOOTSTRAP_SUPERUSER_USERNAME"] = "superuser"
    os.environ["BOOTSTRAP_SUPERUSER_PASSWORD"] = "superuser11"

    async def _seed_once() -> None:
        from src.runtime import build_runtime, reset_default_runtime
        from src.config import build_app_config
        from src.startup.bootstrap import ensure_initial_super_user, run_bootstrap_seeding

        reset_default_runtime()
        runtime = build_runtime(build_app_config())
        try:
            await ensure_initial_super_user(runtime=runtime)
            await run_bootstrap_seeding(runtime=runtime)
        finally:
            await runtime.engine.dispose()
            reset_default_runtime()

    try:
        asyncio.run(_seed_once())
        if not _has_superuser_seed(tmp_seeded_db_path):
            raise RuntimeError("Seeded integration DB template was created without superuser.")
        tmp_seeded_db_path.replace(seeded_db_path)
    finally:
        if tmp_seeded_db_path.exists():
            tmp_seeded_db_path.unlink()
    return seeded_db_path


@pytest_asyncio.fixture
async def client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    seeded_db_template: Path,
) -> AsyncIterator[httpx.AsyncClient]:
    import time
    t0 = time.perf_counter()
    
    db_path = tmp_path / "integration.sqlite3"
    shutil.copy2(seeded_db_template, db_path)
    t1 = time.perf_counter()

    monkeypatch.setenv("JWT_SECRET_KEY", TEST_JWT_SECRET)
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", TEST_CORS_ORIGIN)
    monkeypatch.setenv("CORS_ALLOW_CREDENTIALS", "false")
    monkeypatch.setenv("PBKDF2_ITERATIONS", TEST_PBKDF2_ITERATIONS)
    # DB template is already seeded and includes the superuser.
    monkeypatch.setenv("BOOTSTRAP_SUPERUSER_CREATE", "false")
    monkeypatch.setenv("BOOTSTRAP_SUPERUSER_USERNAME", "superuser")
    monkeypatch.setenv("BOOTSTRAP_SUPERUSER_PASSWORD", "superuser11")

    from src.runtime import build_runtime, reset_default_runtime
    from src.config import build_app_config
    from src.app import create_app
    from src.utils.inprocess_http import close_inprocess_http

    global _cached_app_config
    if _cached_app_config is None:
        _cached_app_config = build_app_config()
    
    # Update DATABASE_URL in cached config
    _cached_app_config.DATABASE_URL = f"sqlite+aiosqlite:///{db_path}"
    
    reset_default_runtime()
    runtime = build_runtime(_cached_app_config)
    t2 = time.perf_counter()
    
    app = create_app(runtime)
    t3 = time.perf_counter()

    try:
        # Skip lifespan startup for per-test clients: template DB is already fully bootstrapped.
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
            # Print timing info for first few tests
            if hasattr(client, '_timing_logged'):
                pass
            else:
                print(f"[TIMING] DB copy: {(t1-t0)*1000:.1f}ms, Runtime: {(t2-t1)*1000:.1f}ms, App: {(t3-t2)*1000:.1f}ms")
                client._timing_logged = True
            yield c
    finally:
        await close_inprocess_http(app)
        await runtime.engine.dispose()
        reset_default_runtime()


@pytest_asyncio.fixture(scope="session")
async def unauth_client(
    tmp_path_factory: pytest.TempPathFactory,
    seeded_db_template: Path,
) -> AsyncIterator[httpx.AsyncClient]:
    """
    Shared client for unauthenticated/401 integration checks.
    Uses a copied seeded DB once and skips lifespan; tests using this fixture must not mutate state.
    """
    db_dir = tmp_path_factory.mktemp("integration-unauth-client")
    db_path = db_dir / "integration.sqlite3"
    shutil.copy2(seeded_db_template, db_path)

    os.environ["JWT_SECRET_KEY"] = TEST_JWT_SECRET
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"
    os.environ["CORS_ALLOW_ORIGINS"] = TEST_CORS_ORIGIN
    os.environ["CORS_ALLOW_CREDENTIALS"] = "false"
    os.environ["PBKDF2_ITERATIONS"] = TEST_PBKDF2_ITERATIONS
    os.environ["BOOTSTRAP_SUPERUSER_CREATE"] = "false"
    os.environ["BOOTSTRAP_SUPERUSER_USERNAME"] = "superuser"
    os.environ["BOOTSTRAP_SUPERUSER_PASSWORD"] = "superuser11"

    from src.runtime import build_runtime, reset_default_runtime
    from src.config import build_app_config
    from src.app import create_app
    from src.utils.inprocess_http import close_inprocess_http

    global _cached_app_config
    if _cached_app_config is None:
        _cached_app_config = build_app_config()
    
    # Update DATABASE_URL in cached config
    _cached_app_config.DATABASE_URL = f"sqlite+aiosqlite:///{db_path}"
    
    reset_default_runtime()
    runtime = build_runtime(_cached_app_config)
    app = create_app(runtime)

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
            yield c
    finally:
        await close_inprocess_http(app)
        await runtime.engine.dispose()
        reset_default_runtime()


@pytest_asyncio.fixture
async def superuser_tokens(client: httpx.AsyncClient) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "superuser", "password": "superuser11"},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    return {"access": data["access_token"]}


@pytest_asyncio.fixture
async def regular_user_tokens(client: httpx.AsyncClient) -> dict[str, str]:
    username = f"student{uuid.uuid4().hex[:10]}"
    response = await client.post(
        "/api/v1/auth/signup",
        json={"username": username, "password": "StrongPass123"},
    )
    assert response.status_code == 201, response.text
    data = response.json()
    me_response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {data['access_token']}"},
    )
    assert me_response.status_code == 200, me_response.text
    me = me_response.json()
    return {
        "username": username,
        "access": data["access_token"],
        "user_id": me["id"],
    }


def bearer_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
