import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from unittest.mock import patch

from src.auth import service


@pytest.fixture(autouse=True)
def _reset_auth_service_caches():
    service._token_revocation_cache.clear()
    service._token_identity_cache.clear()
    yield
    service._token_revocation_cache.clear()
    service._token_identity_cache.clear()


class _InvalidSecurity:
    def _decode_token(self, token: str):
        raise ValueError("invalid token")


class _FakeCacheService:
    def __init__(self):
        self.values: dict[str, dict] = {}

    async def get_json(self, key: str):
        return self.values.get(key)

    async def set_json(self, key: str, payload: dict, ttl_seconds: int | None = None):
        self.values[key] = dict(payload)

    async def delete(self, key: str):
        self.values.pop(key, None)


async def _create_revocation_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(service._revocation_metadata.create_all)
    return engine


def test_hash_and_verify_password_roundtrip():
    hashed = service.hash_password("StrongPass123")
    assert hashed.startswith("pbkdf2_sha256$")
    assert service.verify_password("StrongPass123", hashed) is True
    assert service.verify_password("WrongPass123", hashed) is False


def test_verify_password_handles_malformed_hash():
    assert service.verify_password("secret", "broken") is False


@pytest.mark.asyncio
async def test_revoke_token_marks_token_as_revoked():
    token = "token-abc"
    security = _InvalidSecurity()
    cache_service = _FakeCacheService()
    engine = await _create_revocation_engine()
    try:
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
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_legacy_revoked_token_expires(
    monkeypatch: pytest.MonkeyPatch,
):
    issued_at = service.datetime(2026, 1, 1, tzinfo=service.timezone.utc)
    expiry_check_at = issued_at + service.FALLBACK_RAW_TOKEN_TTL + service.timedelta(seconds=1)
    current_now = {"value": issued_at}
    monkeypatch.setattr(service, "_utc_now", lambda: current_now["value"])
    security = _InvalidSecurity()
    cache_service = _FakeCacheService()
    engine = await _create_revocation_engine()
    try:
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
    finally:
        await engine.dispose()


def test_extract_jti_and_exp_accepts_numeric_exp_timestamp():
    class _Payload:
        jti = "test-jti"
        exp = 1772098145.865263

        def model_dump(self):
            return {"jti": self.jti, "exp": self.exp}

    class _Security:
        def _decode_token(self, token: str):
            assert token == "jwt-token"
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
