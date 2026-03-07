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
_LEGACY_REVOKED_TOKEN_MAX_ENTRIES = 4096
_legacy_revoked_tokens: dict[str, datetime] = {}
_TOKEN_REVOCATION_CACHE_TTL_SECONDS_ENV = "TOKEN_REVOCATION_CACHE_TTL_SECONDS"
_TOKEN_REVOCATION_CACHE_MAX_ENTRIES = 4096
_TOKEN_IDENTITY_CACHE_MAX_ENTRIES = 2048
_token_revocation_cache: dict[str, tuple[bool, datetime]] = {}
_token_identity_cache: dict[str, tuple[str, datetime]] = {}

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


def _get_token_revocation_cache_ttl_seconds() -> float:
    raw_value = os.getenv(_TOKEN_REVOCATION_CACHE_TTL_SECONDS_ENV, "").strip()
    if not raw_value:
        return 1.0
    try:
        ttl_value = float(raw_value)
    except ValueError:
        return 1.0
    return max(0.0, min(ttl_value, 60.0))


def _cache_revocation_status(*, jti: str, revoked: bool, now: datetime, expires_at: datetime) -> None:
    cache_until = expires_at if revoked else min(
        expires_at,
        now + timedelta(seconds=_get_token_revocation_cache_ttl_seconds()),
    )
    _token_revocation_cache[jti] = (revoked, cache_until)
    if len(_token_revocation_cache) > _TOKEN_REVOCATION_CACHE_MAX_ENTRIES:
        for key, (_, valid_until) in list(_token_revocation_cache.items()):
            if valid_until <= now:
                _token_revocation_cache.pop(key, None)
        while len(_token_revocation_cache) > _TOKEN_REVOCATION_CACHE_MAX_ENTRIES:
            _token_revocation_cache.pop(next(iter(_token_revocation_cache)))


def _cache_legacy_revoked_token(*, token: str, now: datetime) -> None:
    expires_at = now + FALLBACK_RAW_TOKEN_TTL
    _legacy_revoked_tokens[token] = expires_at
    for key, valid_until in list(_legacy_revoked_tokens.items()):
        if valid_until <= now:
            _legacy_revoked_tokens.pop(key, None)
    while len(_legacy_revoked_tokens) > _LEGACY_REVOKED_TOKEN_MAX_ENTRIES:
        _legacy_revoked_tokens.pop(next(iter(_legacy_revoked_tokens)))


def _is_legacy_revoked_token_active(*, token: str, now: datetime) -> bool:
    expires_at = _legacy_revoked_tokens.get(token)
    if expires_at is None:
        return False
    if expires_at <= now:
        _legacy_revoked_tokens.pop(token, None)
        return False
    return True


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
    now = _utc_now()
    cached_identity = _token_identity_cache.get(token)
    if cached_identity is not None:
        token_jti, token_exp = cached_identity
        if token_exp > now:
            return token_jti, token_exp
        _token_identity_cache.pop(token, None)

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
        normalized_exp = _normalize_expiry(token_exp)
        token_jti_str = str(token_jti)
        _token_identity_cache[token] = (token_jti_str, normalized_exp)
        if len(_token_identity_cache) > _TOKEN_IDENTITY_CACHE_MAX_ENTRIES:
            _token_identity_cache.pop(next(iter(_token_identity_cache)))
        return token_jti_str, normalized_exp
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
        token_jti, token_exp = _extract_jti_and_exp(token, security=security)
    except ValueError:
        # Backward-compatible path for tests/legacy raw token strings.
        return _is_legacy_revoked_token_active(token=token, now=_utc_now())

    now = _utc_now()
    cached = _token_revocation_cache.get(token_jti)
    if cached is not None:
        cached_revoked, cached_until = cached
        if cached_until > now:
            return cached_revoked
        _token_revocation_cache.pop(token_jti, None)

    async with engine.begin() as conn:
        row = (
            await conn.execute(
                select(_revoked_token_jtis.c.expires_at).where(
                    _revoked_token_jtis.c.jti == token_jti
                )
            )
        ).first()
        if row is None:
            _cache_revocation_status(
                jti=token_jti,
                revoked=False,
                now=now,
                expires_at=token_exp,
            )
            return False
        expires_at = _normalize_expiry(row[0])
        if expires_at <= now:
            await conn.execute(
                delete(_revoked_token_jtis).where(_revoked_token_jtis.c.jti == token_jti)
            )
            _cache_revocation_status(
                jti=token_jti,
                revoked=False,
                now=now,
                expires_at=token_exp,
            )
            return False
        _cache_revocation_status(
            jti=token_jti,
            revoked=True,
            now=now,
            expires_at=expires_at,
        )
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
        _cache_legacy_revoked_token(token=token, now=_utc_now())
        return

    await _store_revoked_jti(engine, token_jti, expires_at)
    _cache_revocation_status(
        jti=token_jti,
        revoked=True,
        now=_utc_now(),
        expires_at=expires_at,
    )


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
