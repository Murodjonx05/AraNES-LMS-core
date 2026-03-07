import pytest

from src.auth import service


@pytest.fixture(autouse=True)
def _reset_auth_service_caches():
    service._token_revocation_cache.clear()
    service._token_identity_cache.clear()
    service._legacy_revoked_tokens.clear()
    yield
    service._token_revocation_cache.clear()
    service._token_identity_cache.clear()
    service._legacy_revoked_tokens.clear()


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
    assert await service.is_token_revoked(token) is False
    await service.revoke_token(token)
    assert await service.is_token_revoked(token) is True


@pytest.mark.asyncio
async def test_legacy_revoked_token_expires(monkeypatch: pytest.MonkeyPatch):
    issued_at = service.datetime(2026, 1, 1, tzinfo=service.timezone.utc)
    expiry_check_at = issued_at + service.FALLBACK_RAW_TOKEN_TTL + service.timedelta(seconds=1)
    current_now = {"value": issued_at}
    monkeypatch.setattr(service, "_utc_now", lambda: current_now["value"])

    await service.revoke_token("legacy-token")
    assert await service.is_token_revoked("legacy-token") is True
    current_now["value"] = expiry_check_at
    assert await service.is_token_revoked("legacy-token") is False


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


def test_legacy_revoked_token_cache_remains_bounded(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(service, "_LEGACY_REVOKED_TOKEN_MAX_ENTRIES", 4)
    now = service._utc_now()

    for idx in range(8):
        service._cache_legacy_revoked_token(token=f"legacy-{idx}", now=now)

    assert len(service._legacy_revoked_tokens) == 4
    assert set(service._legacy_revoked_tokens) == {
        "legacy-4",
        "legacy-5",
        "legacy-6",
        "legacy-7",
    }
