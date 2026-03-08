from __future__ import annotations

from uuid import uuid4

from authx import AuthX

from src.runtime import get_default_runtime


def issue_access_token(username: str, *, security: AuthX | None = None) -> str:
    security = security or get_default_runtime().security
    return security.create_access_token(uid=username, data={"jti": str(uuid4())})
