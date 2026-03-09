from __future__ import annotations

from uuid import uuid4

from authx import AuthX

from src.runtime import get_default_runtime


def _normalize_token_subject(username: str) -> str:
    normalized = username.strip()
    if not normalized:
        raise ValueError("username must be a non-empty string")
    return normalized


def _normalize_token_user_id(user_id: int) -> int:
    if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
        raise ValueError("user_id must be a positive integer")
    return user_id


def issue_access_token(
    username: str,
    *,
    user_id: int | None = None,
    security: AuthX | None = None,
) -> str:
    security = security or get_default_runtime().security
    token_subject = _normalize_token_subject(username)
    token_data: dict[str, object] = {"jti": str(uuid4())}
    if user_id is not None:
        token_data["uid"] = _normalize_token_user_id(user_id)
    return security.create_access_token(uid=token_subject, data=token_data)
