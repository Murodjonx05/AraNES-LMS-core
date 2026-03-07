from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from uuid import uuid4

from authx import AuthX
from sqlalchemy import Column, DateTime, MetaData, String, Table, delete, select
from sqlalchemy.ext.asyncio import AsyncEngine

from src.runtime import get_default_runtime
from src.utils.cache import RedisCacheService

PBKDF2_ALGORITHM = "sha256"
PBKDF2_SCHEME_NAME = "pbkdf2_sha256"
PBKDF2_ITERATIONS = 100_000
PBKDF2_ITERATIONS_ENV = "PBKDF2_ITERATIONS"
FALLBACK_RAW_TOKEN_TTL = timedelta(days=30)
_TOKEN_REVOCATION_CACHE_TTL_SECONDS_ENV = "TOKEN_REVOCATION_CACHE_TTL_SECONDS"
_TOKEN_REVOCATION_CACHE_MAX_ENTRIES = 4096
_TOKEN_IDENTITY_CACHE_MAX_ENTRIES = 2048
_token_revocation_cache: dict[str, tuple[bool, datetime]] = {}
_token_identity_cache: dict[str, tuple[str, datetime]] = {}
_REVOCATION_CACHE_KEY_PREFIX = "auth:revoked"

_revocation_metadata = MetaData()
_revoked_token_jtis = Table(
    "auth_revoked_token_jtis",
    _revocation_metadata,
    Column("jti", String(255), primary_key=True),
    Column("expires_at", DateTime(timezone=True), nullable=False, index=True),
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@lru_cache(maxsize=1)
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


@lru_cache(maxsize=1)
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


def _build_raw_token_revocation_key(token: str) -> str:
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return f"raw:{digest}"


def _build_revocation_cache_key(jti: str) -> str:
    return f"{_REVOCATION_CACHE_KEY_PREFIX}:{jti}"


def _token_cache_key(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _resolve_security_and_engine(
    *,
    security: AuthX | None = None,
    engine: AsyncEngine | None = None,
    cache_service: RedisCacheService | None = None,
) -> tuple[AuthX, AsyncEngine, RedisCacheService | None]:
    if security is not None and engine is not None:
        return security, engine, cache_service

    runtime = get_default_runtime()
    return (
        security or runtime.security,
        engine or runtime.engine,
        cache_service or runtime.cache_service,
    )


async def _get_cached_revocation_status(
    *,
    cache_service: RedisCacheService | None,
    jti: str,
    now: datetime,
) -> bool | None:
    if cache_service is None:
        return None
    payload = await cache_service.get_json(_build_revocation_cache_key(jti))
    if not isinstance(payload, dict):
        return None
    revoked = payload.get("revoked")
    expires_at_raw = payload.get("expires_at")
    if not isinstance(revoked, bool) or not isinstance(expires_at_raw, str):
        return None
    try:
        expires_at = _normalize_expiry(datetime.fromisoformat(expires_at_raw))
    except ValueError:
        await cache_service.delete(_build_revocation_cache_key(jti))
        return None
    if expires_at <= now:
        await cache_service.delete(_build_revocation_cache_key(jti))
        return None
    return revoked


async def _set_cached_revocation_status(
    *,
    cache_service: RedisCacheService | None,
    jti: str,
    revoked: bool,
    now: datetime,
    expires_at: datetime,
) -> None:
    if cache_service is None:
        return
    normalized_expiry = _normalize_expiry(expires_at)
    if revoked:
        cache_until = normalized_expiry
    else:
        short_ttl = timedelta(seconds=_get_token_revocation_cache_ttl_seconds())
        cache_until = min(normalized_expiry, now + short_ttl)

    ttl_seconds = max(int((cache_until - now).total_seconds()), 1)
    await cache_service.set_json(
        _build_revocation_cache_key(jti),
        {
            "revoked": revoked,
            "expires_at": normalized_expiry.isoformat(),
        },
        ttl_seconds=ttl_seconds,
    )


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
    cache_key = _token_cache_key(token)
    cached_identity = _token_identity_cache.get(cache_key)
    if cached_identity is not None:
        token_jti, token_exp = cached_identity
        if token_exp > now:
            return token_jti, token_exp
        _token_identity_cache.pop(cache_key, None)

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
        _token_identity_cache[cache_key] = (token_jti_str, normalized_exp)
        if len(_token_identity_cache) > _TOKEN_IDENTITY_CACHE_MAX_ENTRIES:
            _token_identity_cache.pop(next(iter(_token_identity_cache)))
        return token_jti_str, normalized_exp
    except Exception as exc:
        raise ValueError("Token is not a decodable JWT for jti-based revocation.") from exc


def _resolve_revocation_identity(token: str, *, security: AuthX) -> tuple[str, datetime]:
    try:
        return _extract_jti_and_exp(token, security=security)
    except ValueError:
        return _build_raw_token_revocation_key(token), _utc_now() + FALLBACK_RAW_TOKEN_TTL


async def is_token_revoked(
    token: str,
    *,
    security: AuthX | None = None,
    engine: AsyncEngine | None = None,
    cache_service: RedisCacheService | None = None,
) -> bool:
    security, engine, cache_service = _resolve_security_and_engine(
        security=security,
        engine=engine,
        cache_service=cache_service,
    )
    token_jti, token_exp = _resolve_revocation_identity(token, security=security)

    now = _utc_now()
    cached = _token_revocation_cache.get(token_jti)
    if cached is not None:
        cached_revoked, cached_until = cached
        if cached_until > now:
            return cached_revoked
        _token_revocation_cache.pop(token_jti, None)

    redis_cached = await _get_cached_revocation_status(
        cache_service=cache_service,
        jti=token_jti,
        now=now,
    )
    if redis_cached is not None:
        _cache_revocation_status(
            jti=token_jti,
            revoked=redis_cached,
            now=now,
            expires_at=token_exp,
        )
        return redis_cached

    async with engine.connect() as conn:
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
        await _set_cached_revocation_status(
            cache_service=cache_service,
            jti=token_jti,
            revoked=False,
            now=now,
            expires_at=token_exp,
        )
        return False

    expires_at = _normalize_expiry(row[0])
    if expires_at <= now:
        async with engine.begin() as conn:
            await conn.execute(
                delete(_revoked_token_jtis).where(_revoked_token_jtis.c.jti == token_jti)
            )
        _cache_revocation_status(
            jti=token_jti,
            revoked=False,
            now=now,
            expires_at=token_exp,
        )
        await _set_cached_revocation_status(
            cache_service=cache_service,
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
    await _set_cached_revocation_status(
        cache_service=cache_service,
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
    cache_service: RedisCacheService | None = None,
) -> None:
    security, engine, cache_service = _resolve_security_and_engine(
        security=security,
        engine=engine,
        cache_service=cache_service,
    )
    token_jti, expires_at = _resolve_revocation_identity(token, security=security)

    await _store_revoked_jti(engine, token_jti, expires_at)
    now = _utc_now()
    _cache_revocation_status(
        jti=token_jti,
        revoked=True,
        now=now,
        expires_at=expires_at,
    )
    await _set_cached_revocation_status(
        cache_service=cache_service,
        jti=token_jti,
        revoked=True,
        now=now,
        expires_at=expires_at,
    )


def configure_token_blocklist(
    *,
    security: AuthX | None = None,
    engine: AsyncEngine | None = None,
    cache_service: RedisCacheService | None = None,
) -> None:
    security, engine, cache_service = _resolve_security_and_engine(
        security=security,
        engine=engine,
        cache_service=cache_service,
    )

    async def _bound_blocklist(token: str) -> bool:
        return await is_token_revoked(
            token,
            security=security,
            engine=engine,
            cache_service=cache_service,
        )

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
