from pathlib import Path
import os
import tempfile

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import create_async_engine
from unittest.mock import patch

from src.auth import passwords
from src.auth import service


@pytest.fixture(autouse=True)
def _reset_auth_service_caches():
    service._token_revocation_cache.clear()
    service._token_identity_cache.clear()
    service._revocation_cleanup_due_at.clear()
    yield
    service._token_revocation_cache.clear()
    service._token_identity_cache.clear()
    service._revocation_cleanup_due_at.clear()


@pytest.fixture(scope="module", autouse=True)
def _cheap_auth_service_hash_profile():
    from src.auth import passwords as password_module

    original_values = {
        "ARGON2_TIME_COST": os.environ.get("ARGON2_TIME_COST"),
        "ARGON2_MEMORY_COST": os.environ.get("ARGON2_MEMORY_COST"),
        "ARGON2_PARALLELISM": os.environ.get("ARGON2_PARALLELISM"),
    }
    os.environ["ARGON2_TIME_COST"] = "1"
    os.environ["ARGON2_MEMORY_COST"] = "1024"
    os.environ["ARGON2_PARALLELISM"] = "1"
    password_module._get_password_hasher.cache_clear()
    service._get_password_hasher.cache_clear()
    try:
        yield
    finally:
        for env_name, value in original_values.items():
            if value is None:
                os.environ.pop(env_name, None)
            else:
                os.environ[env_name] = value
        password_module._get_password_hasher.cache_clear()
        service._get_password_hasher.cache_clear()


class _InvalidSecurity:
    def verify_token(self, token, **kwargs):
        del token, kwargs
        raise ValueError("invalid token")


class _Payload:
    def __init__(self, *, jti: str, exp):
        self.jti = jti
        self.exp = exp

    def model_dump(self):
        return {"jti": self.jti, "exp": self.exp}


class _FixedSecurity:
    def __init__(self, *, jti: str, exp):
        self._payload = _Payload(jti=jti, exp=exp)

    def verify_token(self, token, **kwargs):
        assert token.type == "access"
        assert token.location == "headers"
        assert kwargs["verify_type"] is True
        assert kwargs["verify_fresh"] is False
        assert kwargs["verify_csrf"] is False
        return self._payload


class _FakeCacheService:
    def __init__(self):
        self.values: dict[str, dict] = {}

    async def get_json(self, key: str):
        return self.values.get(key)

    async def set_json(self, key: str, payload: dict, ttl_seconds: int | None = None):
        self.values[key] = dict(payload)

    async def delete(self, key: str):
        self.values.pop(key, None)


async def _create_revocation_engine(database_path: Path | None = None):
    if database_path is None:
        database_path = Path(tempfile.mkstemp(prefix="auth-service-", suffix=".sqlite3")[1])
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    async with engine.begin() as conn:
        await conn.run_sync(service._revocation_metadata.create_all)
    return engine


@pytest_asyncio.fixture(scope="module")
async def revocation_engine(tmp_path_factory: pytest.TempPathFactory):
    database_path = tmp_path_factory.mktemp("auth-service") / "revocation.sqlite3"
    engine = await _create_revocation_engine(database_path)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def clean_revocation_engine(revocation_engine):
    async with revocation_engine.begin() as conn:
        await conn.execute(service._revoked_token_jtis.delete())
    yield revocation_engine
    async with revocation_engine.begin() as conn:
        await conn.execute(service._revoked_token_jtis.delete())


def test_hash_and_verify_password_roundtrip():
    hashed = service.hash_password("StrongPass123")
    assert hashed.startswith("$argon2")
    assert service.verify_password("StrongPass123", hashed) is True
    assert service.verify_password("WrongPass123", hashed) is False


def test_verify_password_handles_malformed_hash():
    assert service.verify_password("secret", "broken") is False


def test_verify_password_accepts_legacy_pbkdf2_hash():
    iterations = service._get_pbkdf2_iterations()
    salt = "testsalt"
    digest = service._pbkdf2_hex_digest("legacy-secret", salt, iterations)
    legacy_hash = f"{service.PBKDF2_SCHEME_NAME}${iterations}${salt}${digest}"

    assert service.verify_password("legacy-secret", legacy_hash) is True
    assert service.verify_password("wrong-secret", legacy_hash) is False


def test_verify_password_rejects_legacy_pbkdf2_hash_with_non_positive_iterations():
    legacy_hash = f"{service.PBKDF2_SCHEME_NAME}$0$testsalt$deadbeef"

    assert service.verify_password("legacy-secret", legacy_hash) is False


@pytest.mark.asyncio
async def test_revoke_token_marks_token_as_revoked(clean_revocation_engine):
    token = "token-abc"
    security = _InvalidSecurity()
    cache_service = _FakeCacheService()
    engine = clean_revocation_engine
    assert await service.is_token_revoked(
        token,
        security=security,
        engine=engine,
        cache_service=cache_service,  # type: ignore[arg-type]
    ) is False
    await service.revoke_token(
        token,
        security=security,
        engine=engine,
        cache_service=cache_service,  # type: ignore[arg-type]
    )
    assert await service.is_token_revoked(
        token,
        security=security,
        engine=engine,
        cache_service=cache_service,  # type: ignore[arg-type]
    ) is True


@pytest.mark.asyncio
async def test_is_token_revoked_scopes_local_cache_to_engine(clean_revocation_engine):
    token = "shared-token"
    expires_at = service._utc_now() + service.timedelta(minutes=5)
    security = _FixedSecurity(jti="shared-jti", exp=expires_at)
    revoked_engine = clean_revocation_engine
    clean_engine = await _create_revocation_engine()
    try:
        await service.revoke_token(token, security=security, engine=revoked_engine)

        assert await service.is_token_revoked(token, security=security, engine=revoked_engine) is True
        assert await service.is_token_revoked(token, security=security, engine=clean_engine) is False
    finally:
        await revoked_engine.dispose()
        await clean_engine.dispose()


@pytest.mark.asyncio
async def test_is_token_revoked_scopes_identity_cache_to_security(clean_revocation_engine):
    token = "shared-token"
    expires_at = service._utc_now() + service.timedelta(minutes=5)
    first_security = _FixedSecurity(jti="first-jti", exp=expires_at)
    second_security = _FixedSecurity(jti="second-jti", exp=expires_at)
    first_engine = clean_revocation_engine
    second_engine = await _create_revocation_engine()
    try:
        assert await service.is_token_revoked(token, security=first_security, engine=first_engine) is False
        await service._store_revoked_jti(second_engine, "second-jti", expires_at)

        assert await service.is_token_revoked(token, security=second_security, engine=second_engine) is True
    finally:
        await first_engine.dispose()
        await second_engine.dispose()


@pytest.mark.asyncio
async def test_legacy_revoked_token_expires(
    monkeypatch: pytest.MonkeyPatch,
    clean_revocation_engine,
):
    issued_at = service.datetime(2026, 1, 1, tzinfo=service.timezone.utc)
    expiry_check_at = issued_at + service.FALLBACK_RAW_TOKEN_TTL + service.timedelta(seconds=1)
    current_now = {"value": issued_at}
    monkeypatch.setattr(service, "_utc_now", lambda: current_now["value"])
    security = _InvalidSecurity()
    cache_service = _FakeCacheService()
    engine = clean_revocation_engine
    await service.revoke_token(
        "legacy-token",
        security=security,
        engine=engine,
        cache_service=cache_service,  # type: ignore[arg-type]
    )
    assert await service.is_token_revoked(
        "legacy-token",
        security=security,
        engine=engine,
        cache_service=cache_service,  # type: ignore[arg-type]
    ) is True
    current_now["value"] = expiry_check_at
    assert await service.is_token_revoked(
        "legacy-token",
        security=security,
        engine=engine,
        cache_service=cache_service,  # type: ignore[arg-type]
    ) is False


def test_extract_jti_and_exp_accepts_numeric_exp_timestamp():
    class _Payload:
        jti = "test-jti"
        exp = 1772098145.865263

        def model_dump(self):
            return {"jti": self.jti, "exp": self.exp}

    class _Security:
        def verify_token(self, token, **kwargs):
            assert token.token == "jwt-token"
            assert token.type == "access"
            assert token.location == "headers"
            assert kwargs["verify_type"] is True
            assert kwargs["verify_fresh"] is False
            assert kwargs["verify_csrf"] is False
            return _Payload()

    token_jti, expires_at = service._extract_jti_and_exp("jwt-token", security=_Security())
    assert token_jti == "test-jti"
    assert expires_at.tzinfo is not None
    assert expires_at.year >= 2026


def test_pbkdf2_hex_digest_is_deterministic_for_same_inputs():
    digest_a = service._pbkdf2_hex_digest("secret", "salt", 100)
    digest_b = service._pbkdf2_hex_digest("secret", "salt", 100)
    digest_c = service._pbkdf2_hex_digest("secret", "salt2", 100)

    assert digest_a == digest_b
    assert digest_a != digest_c


def test_get_pbkdf2_iterations_clamps_low_values_outside_pytest(monkeypatch: pytest.MonkeyPatch):
    service._get_pbkdf2_iterations.cache_clear()
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv(service.PBKDF2_ITERATIONS_ENV, "1")

    assert service._get_pbkdf2_iterations() == service.PBKDF2_ITERATIONS


def test_get_pbkdf2_iterations_allows_low_values_during_pytest(monkeypatch: pytest.MonkeyPatch):
    service._get_pbkdf2_iterations.cache_clear()
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests/auth/test_auth_service.py::test")
    monkeypatch.setenv(service.PBKDF2_ITERATIONS_ENV, "1")

    assert service._get_pbkdf2_iterations() == 1


def test_password_hasher_clamps_weak_argon2_env_values_outside_pytest(monkeypatch: pytest.MonkeyPatch):
    service._get_password_hasher.cache_clear()
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("ARGON2_TIME_COST", "1")
    monkeypatch.setenv("ARGON2_MEMORY_COST", "1024")
    monkeypatch.setenv("ARGON2_PARALLELISM", "0")

    hasher = service._get_password_hasher().current_hasher._hasher

    assert hasher.time_cost == passwords._ARGON2_MIN_TIME_COST
    assert hasher.memory_cost == passwords._ARGON2_MIN_MEMORY_COST
    assert hasher.parallelism == passwords._ARGON2_MIN_PARALLELISM


def test_revocation_cache_remains_bounded_for_non_expired_entries(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(service, "_TOKEN_REVOCATION_CACHE_MAX_ENTRIES", 4)
    now = service._utc_now()
    expires_at = now + service.timedelta(seconds=30)

    for idx in range(8):
        service._cache_revocation_status(
            jti=f"jti-{idx}",
            revoked=bool(idx % 2),
            now=now,
            expires_at=expires_at,
        )

    assert len(service._token_revocation_cache) == 4
    assert set(service._token_revocation_cache) == {"jti-4", "jti-5", "jti-6", "jti-7"}


@pytest.mark.asyncio
async def test_shared_revocation_cache_helpers_roundtrip():
    cache_service = _FakeCacheService()
    jti = service._build_raw_token_revocation_key("token-redis")
    now = service._utc_now()
    expires_at = now + service.FALLBACK_RAW_TOKEN_TTL

    assert await service._get_cached_revocation_status(
        cache_service=cache_service,  # type: ignore[arg-type]
        jti=jti,
        now=now,
    ) is None

    await service._set_cached_revocation_status(
        cache_service=cache_service,  # type: ignore[arg-type]
        jti=jti,
        revoked=True,
        now=now,
        expires_at=expires_at,
    )

    assert await service._get_cached_revocation_status(
        cache_service=cache_service,  # type: ignore[arg-type]
        jti=jti,
        now=now,
    ) is True
    assert service._build_revocation_cache_key(jti) in cache_service.values


@pytest.mark.asyncio
async def test_store_revoked_jti_upserts_and_cleans_expired_rows(
    monkeypatch: pytest.MonkeyPatch,
    clean_revocation_engine,
):
    engine = clean_revocation_engine
    now = service.datetime(2026, 1, 1, tzinfo=service.timezone.utc)
    current_now = {"value": now}
    monkeypatch.setattr(service, "_utc_now", lambda: current_now["value"])
    monkeypatch.setattr(service, "_REVOCATION_EXPIRY_CLEANUP_INTERVAL", service.timedelta(seconds=30))

    expired_at = now - service.timedelta(seconds=5)
    fresh_expiry = now + service.timedelta(minutes=5)
    updated_expiry = fresh_expiry + service.timedelta(minutes=5)
    await service._store_revoked_jti(engine, "expired-jti", expired_at)
    current_now["value"] = now + service.timedelta(seconds=31)
    await service._store_revoked_jti(engine, "live-jti", fresh_expiry)
    await service._store_revoked_jti(engine, "live-jti", updated_expiry)

    async with engine.connect() as conn:
        count = await conn.scalar(select(func.count()).select_from(service._revoked_token_jtis))
        expiry = await conn.scalar(
            select(service._revoked_token_jtis.c.expires_at).where(
                service._revoked_token_jtis.c.jti == "live-jti"
            )
        )

    assert count == 1
    assert expiry is not None
    assert service._normalize_expiry(expiry) == service._normalize_expiry(updated_expiry)


@pytest.mark.asyncio
async def test_store_revoked_jti_uses_portable_delete_then_insert(
    monkeypatch: pytest.MonkeyPatch,
    clean_revocation_engine,
):
    engine = clean_revocation_engine
    deleted_jtis: list[str] = []
    original_delete = service.delete

    def _tracking_delete(table):
        statement = original_delete(table)

        class _DeleteProxy:
            def where(self, clause):
                left = getattr(clause, "left", None)
                right = getattr(clause, "right", None)
                if getattr(left, "name", None) == "jti" and hasattr(right, "value"):
                    deleted_jtis.append(right.value)
                return statement.where(clause)

        return _DeleteProxy()

    monkeypatch.setattr(service, "delete", _tracking_delete)
    await service._store_revoked_jti(
        engine,
        "portable-jti",
        service._utc_now() + service.timedelta(minutes=1),
    )

    assert "portable-jti" in deleted_jtis


@pytest.mark.asyncio
async def test_store_revoked_jti_throttles_expired_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    clean_revocation_engine,
):
    engine = clean_revocation_engine
    now = service.datetime(2026, 1, 1, tzinfo=service.timezone.utc)
    current_now = {"value": now}
    expired_cleanup_calls = 0
    original_delete = service.delete

    def _tracking_delete(table):
        statement = original_delete(table)

        class _DeleteProxy:
            def where(self, clause):
                nonlocal expired_cleanup_calls
                left = getattr(clause, "left", None)
                if getattr(left, "name", None) == "expires_at":
                    expired_cleanup_calls += 1
                return statement.where(clause)

        return _DeleteProxy()

    monkeypatch.setattr(service, "_utc_now", lambda: current_now["value"])
    monkeypatch.setattr(service, "_REVOCATION_EXPIRY_CLEANUP_INTERVAL", service.timedelta(seconds=30))
    monkeypatch.setattr(service, "delete", _tracking_delete)

    await service._store_revoked_jti(engine, "first-jti", now + service.timedelta(minutes=5))
    await service._store_revoked_jti(engine, "second-jti", now + service.timedelta(minutes=5))
    current_now["value"] = now + service.timedelta(seconds=31)
    await service._store_revoked_jti(engine, "third-jti", now + service.timedelta(minutes=5))

    assert expired_cleanup_calls == 2


def test_explicit_security_and_engine_do_not_require_default_runtime():
    security = object()
    engine = object()

    with patch("src.auth.service.get_default_runtime") as get_default_runtime_mock:
        resolved_security, resolved_engine, resolved_cache_service = service._resolve_security_and_engine(
            security=security,  # type: ignore[arg-type]
            engine=engine,  # type: ignore[arg-type]
        )

    assert resolved_security is security
    assert resolved_engine is engine
    assert resolved_cache_service is None
    get_default_runtime_mock.assert_not_called()
