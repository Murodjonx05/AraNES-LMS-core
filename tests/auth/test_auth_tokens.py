from __future__ import annotations

import pytest
from authx import AuthX, AuthXConfig
from authx.schema import RequestToken

from src.auth.tokens import issue_access_token


def _build_security() -> AuthX:
    return AuthX(
        config=AuthXConfig(
            JWT_SECRET_KEY="test-secret-key-with-32-byte-minimum!!",
            JWT_TOKEN_LOCATION=["headers"],
        )
    )


def _decode_access_token(security: AuthX, token: str):
    return security.verify_token(
        RequestToken(token=token, type="access", location="headers"),
        verify_type=True,
        verify_fresh=False,
        verify_csrf=False,
    )


def test_issue_access_token_sets_access_type_subject_and_jti():
    security = _build_security()

    token = issue_access_token("alice", security=security)
    payload = _decode_access_token(security, token)

    assert payload.type == "access"
    assert payload.sub == "alice"
    assert payload.jti
    assert payload.exp is not None


def test_issue_access_token_can_embed_stable_user_id_claim():
    security = _build_security()

    token = issue_access_token("alice", user_id=42, security=security)
    payload = _decode_access_token(security, token)

    assert payload.sub == "alice"
    assert payload.uid == 42


def test_issue_access_token_generates_unique_jti_per_token():
    security = _build_security()

    first = _decode_access_token(security, issue_access_token("alice", security=security))
    second = _decode_access_token(security, issue_access_token("alice", security=security))

    assert first.jti != second.jti


@pytest.mark.parametrize("username", ["", "   "])
def test_issue_access_token_rejects_blank_subject(username: str):
    security = _build_security()

    with pytest.raises(ValueError, match="username must be a non-empty string"):
        issue_access_token(username, security=security)


@pytest.mark.parametrize("user_id", [0, -1, True])
def test_issue_access_token_rejects_invalid_user_id_claim(user_id):
    security = _build_security()

    with pytest.raises(ValueError, match="user_id must be a positive integer"):
        issue_access_token("alice", user_id=user_id, security=security)
