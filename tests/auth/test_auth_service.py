from src.auth import service


def test_hash_and_verify_password_roundtrip():
    hashed = service.hash_password("StrongPass123")
    assert hashed.startswith("pbkdf2_sha256$")
    assert service.verify_password("StrongPass123", hashed) is True
    assert service.verify_password("WrongPass123", hashed) is False


def test_verify_password_handles_malformed_hash():
    assert service.verify_password("secret", "broken") is False


def test_revoke_token_marks_token_as_revoked():
    token = "token-abc"
    assert service.is_token_revoked(token) is False
    service.revoke_token(token)
    assert service.is_token_revoked(token) is True
