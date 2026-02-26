import pytest

from src.auth import service


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
