from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from authx import AuthX
from sqlalchemy import Column, DateTime, MetaData, String, Table, delete, select
from sqlalchemy.ext.asyncio import AsyncEngine

from src.runtime import get_default_runtime

PBKDF2_ALGORITHM = "sha256"
PBKDF2_SCHEME_NAME = "pbkdf2_sha256"
PBKDF2_ITERATIONS = 100_000
PBKDF2_ITERATIONS_ENV = "PBKDF2_ITERATIONS"
FALLBACK_RAW_TOKEN_TTL = timedelta(days=30)
_legacy_revoked_tokens: set[str] = set()

_revocation_metadata = MetaData()
_revoked_token_jtis = Table(
    "auth_revoked_token_jtis",
    _revocation_metadata,
    Column("jti", String(255), primary_key=True),
    Column("expires_at", DateTime(timezone=True), nullable=False, index=True),
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _get_pbkdf2_iterations() -> int:
    raw_value = os.getenv(PBKDF2_ITERATIONS_ENV, "").strip()
    if not raw_value:
        return PBKDF2_ITERATIONS
    try:
        value = int(raw_value)
    except ValueError:
        return PBKDF2_ITERATIONS
    # Allow aggressive tuning in test/dev environments.
    return max(1, value)


def _normalize_expiry(expires_at: datetime) -> datetime:
    if expires_at.tzinfo is None:
        return expires_at.replace(tzinfo=timezone.utc)
    return expires_at.astimezone(timezone.utc)


def _resolve_security_and_engine(
    *,
    security: AuthX | None = None,
    engine: AsyncEngine | None = None,
) -> tuple[AuthX, AsyncEngine]:
    if security is not None and engine is not None:
        return security, engine

    runtime = get_default_runtime()
    return security or runtime.security, engine or runtime.engine


async def _store_revoked_jti(engine: AsyncEngine, jti: str, expires_at: datetime) -> None:
    expires_at = _normalize_expiry(expires_at)
    async with engine.begin() as conn:
        await conn.execute(
            delete(_revoked_token_jtis).where(_revoked_token_jtis.c.expires_at <= _utc_now())
        )
        await conn.execute(delete(_revoked_token_jtis).where(_revoked_token_jtis.c.jti == jti))
        await conn.execute(
            _revoked_token_jtis.insert(),
            [{"jti": jti, "expires_at": expires_at}],
        )


def _extract_jti_and_exp(token: str, *, security: AuthX) -> tuple[str, datetime]:
    try:
        payload = security._decode_token(token)
        payload_dict = payload.model_dump() if hasattr(payload, "model_dump") else {}
        token_jti = getattr(payload, "jti", None) or payload_dict.get("jti")
        token_exp = getattr(payload, "exp", None) or payload_dict.get("exp")
        if not token_jti:
            raise ValueError("Token jti is missing.")
        if token_exp is None:
            raise ValueError("Token expiry is missing.")
        if isinstance(token_exp, str):
            token_exp = datetime.fromisoformat(token_exp)
        elif isinstance(token_exp, (int, float)):
            token_exp = datetime.fromtimestamp(token_exp, tz=timezone.utc)
        if not isinstance(token_exp, datetime):
            raise ValueError("Invalid token expiry type.")
        return str(token_jti), _normalize_expiry(token_exp)
    except Exception:
        raise ValueError("Token is not a decodable JWT for jti-based revocation.") from None


async def is_token_revoked(
    token: str,
    *,
    security: AuthX | None = None,
    engine: AsyncEngine | None = None,
) -> bool:
    security, engine = _resolve_security_and_engine(security=security, engine=engine)
    try:
        token_jti, _ = _extract_jti_and_exp(token, security=security)
    except ValueError:
        # Backward-compatible path for tests/legacy raw token strings.
        return token in _legacy_revoked_tokens

    now = _utc_now()
    async with engine.begin() as conn:
        row = (
            await conn.execute(
                select(_revoked_token_jtis.c.expires_at).where(
                    _revoked_token_jtis.c.jti == token_jti
                )
            )
        ).first()
        if row is None:
            return False
        expires_at = _normalize_expiry(row[0])
        if expires_at <= now:
            await conn.execute(
                delete(_revoked_token_jtis).where(_revoked_token_jtis.c.jti == token_jti)
            )
            return False
        return True


async def revoke_token(
    token: str,
    *,
    security: AuthX | None = None,
    engine: AsyncEngine | None = None,
) -> None:
    security, engine = _resolve_security_and_engine(security=security, engine=engine)
    try:
        token_jti, expires_at = _extract_jti_and_exp(token, security=security)
    except ValueError:
        _legacy_revoked_tokens.add(token)
        return

    await _store_revoked_jti(engine, token_jti, expires_at)


def configure_token_blocklist(
    *,
    security: AuthX | None = None,
    engine: AsyncEngine | None = None,
) -> None:
    security, engine = _resolve_security_and_engine(security=security, engine=engine)

    async def _bound_blocklist(token: str) -> bool:
        return await is_token_revoked(token, security=security, engine=engine)

    security.set_token_blocklist(_bound_blocklist)


def _pbkdf2_hex_digest(password: str, salt: str, iterations: int) -> str:
    return hashlib.pbkdf2_hmac(
        PBKDF2_ALGORITHM,
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    ).hex()


def hash_password(password: str) -> str:
    iterations = _get_pbkdf2_iterations()
    salt = secrets.token_hex(16)
    digest = _pbkdf2_hex_digest(password, salt, iterations)
    return f"{PBKDF2_SCHEME_NAME}${iterations}${salt}${digest}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        scheme_name, iteration_count_raw, salt, expected_digest = stored_hash.split("$", 3)
        if scheme_name != PBKDF2_SCHEME_NAME:
            return False
        iteration_count = int(iteration_count_raw)
    except (ValueError, TypeError):
        return False

    candidate_digest = _pbkdf2_hex_digest(password, salt, iteration_count)
    return hmac.compare_digest(candidate_digest, expected_digest)


def issue_access_token(username: str, *, security: AuthX | None = None) -> str:
    security = security or get_default_runtime().security
    return security.create_access_token(uid=username, data={"jti": str(uuid4())})
