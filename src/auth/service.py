from __future__ import annotations

from datetime import datetime, timedelta, timezone

from authx import AuthX
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine

from src.auth.passwords import (
    PBKDF2_ALGORITHM,
    PBKDF2_ITERATIONS,
    PBKDF2_ITERATIONS_ENV,
    PBKDF2_SCHEME_NAME,
    _get_int_env,
    _get_password_hasher,
    _get_pbkdf2_iterations,
    _pbkdf2_hex_digest,
    _verify_legacy_pbkdf2_password,
    hash_password,
    verify_password,
)
from src.auth.revocation import (
    FALLBACK_RAW_TOKEN_TTL,
    _TOKEN_REVOCATION_CACHE_MAX_ENTRIES as _REVOCATION_CACHE_LIMIT,
    _build_local_revocation_cache_key,
    _cache_revocation_status,
    _build_raw_token_revocation_key,
    _build_revocation_cache_key,
    _extract_jti_and_exp,
    _get_cached_revocation_status,
    _normalize_expiry,
    _revocation_metadata,
    _revoked_token_jtis,
    _set_cached_revocation_status,
    _token_identity_cache,
    _token_revocation_cache,
    _utc_now,
)
from src.auth.tokens import issue_access_token
from src.runtime import get_default_runtime
from src.utils.cache import RedisCacheService

_TOKEN_REVOCATION_CACHE_MAX_ENTRIES = _REVOCATION_CACHE_LIMIT
_REVOCATION_EXPIRY_CLEANUP_INTERVAL = timedelta(minutes=1)
_revocation_cleanup_due_at: dict[int, datetime] = {}


def _resolve_security_and_engine(
    *,
    security: AuthX | None = None,
    engine: AsyncEngine | None = None,
    cache_service: RedisCacheService | None = None,
) -> tuple[AuthX, AsyncEngine, RedisCacheService | None]:
    """Prefer explicit args. Fallback to global runtime for legacy/standalone callers (e.g. scripts)."""
    if security is not None and engine is not None:
        return security, engine, cache_service

    runtime = get_default_runtime()
    return (
        security or runtime.security,
        engine or runtime.engine,
        cache_service or runtime.cache_service,
    )


def _should_cleanup_expired_revocations(*, engine: AsyncEngine, now: datetime) -> bool:
    engine_key = id(engine)
    due_at = _revocation_cleanup_due_at.get(engine_key)
    if due_at is not None and due_at > now:
        return False
    _revocation_cleanup_due_at[engine_key] = now + _REVOCATION_EXPIRY_CLEANUP_INTERVAL
    return True


async def _store_revoked_jti(engine: AsyncEngine, jti: str, expires_at: datetime) -> None:
    now = _utc_now()
    expires_at = _normalize_expiry(expires_at)
    async with engine.begin() as conn:
        if _should_cleanup_expired_revocations(engine=engine, now=now):
            await conn.execute(
                delete(_revoked_token_jtis).where(_revoked_token_jtis.c.expires_at <= now)
            )
        await conn.execute(delete(_revoked_token_jtis).where(_revoked_token_jtis.c.jti == jti))
        await conn.execute(_revoked_token_jtis.insert().values(jti=jti, expires_at=expires_at))


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
    local_cache_key = _build_local_revocation_cache_key(token_jti, security=security, engine=engine)

    now = _utc_now()
    cached = _token_revocation_cache.get(local_cache_key)
    if cached is not None:
        cached_revoked, cached_until = cached
        if cached_until > now:
            _token_revocation_cache.move_to_end(local_cache_key)
            return cached_revoked
        _token_revocation_cache.pop(local_cache_key, None)

    redis_cached = await _get_cached_revocation_status(
        cache_service=cache_service,
        jti=token_jti,
        now=now,
    )
    if redis_cached is not None:
        _cache_revocation_status(
            jti=local_cache_key,
            revoked=redis_cached,
            now=now,
            expires_at=token_exp,
        )
        return redis_cached

    async with engine.connect() as conn:
        row = (
            await conn.execute(
                select(_revoked_token_jtis.c.expires_at).where(_revoked_token_jtis.c.jti == token_jti)
            )
        ).first()

    if row is None:
        _cache_revocation_status(jti=local_cache_key, revoked=False, now=now, expires_at=token_exp)
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
            await conn.execute(delete(_revoked_token_jtis).where(_revoked_token_jtis.c.jti == token_jti))
        _cache_revocation_status(jti=local_cache_key, revoked=False, now=now, expires_at=token_exp)
        await _set_cached_revocation_status(
            cache_service=cache_service,
            jti=token_jti,
            revoked=False,
            now=now,
            expires_at=token_exp,
        )
        return False

    _cache_revocation_status(jti=local_cache_key, revoked=True, now=now, expires_at=expires_at)
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
    local_cache_key = _build_local_revocation_cache_key(token_jti, security=security, engine=engine)

    await _store_revoked_jti(engine, token_jti, expires_at)
    now = _utc_now()
    _cache_revocation_status(jti=local_cache_key, revoked=True, now=now, expires_at=expires_at)
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


__all__ = [
    "FALLBACK_RAW_TOKEN_TTL",
    "PBKDF2_ALGORITHM",
    "PBKDF2_ITERATIONS",
    "PBKDF2_ITERATIONS_ENV",
    "PBKDF2_SCHEME_NAME",
    "_TOKEN_REVOCATION_CACHE_MAX_ENTRIES",
    "_REVOCATION_EXPIRY_CLEANUP_INTERVAL",
    "_build_local_revocation_cache_key",
    "_build_raw_token_revocation_key",
    "_build_revocation_cache_key",
    "_cache_revocation_status",
    "_extract_jti_and_exp",
    "_get_cached_revocation_status",
    "_get_int_env",
    "_get_password_hasher",
    "_get_pbkdf2_iterations",
    "_normalize_expiry",
    "_pbkdf2_hex_digest",
    "_resolve_revocation_identity",
    "_resolve_security_and_engine",
    "_revocation_cleanup_due_at",
    "_revocation_metadata",
    "_revoked_token_jtis",
    "_set_cached_revocation_status",
    "_should_cleanup_expired_revocations",
    "_store_revoked_jti",
    "_token_identity_cache",
    "_token_revocation_cache",
    "_utc_now",
    "_verify_legacy_pbkdf2_password",
    "AuthX",
    "RedisCacheService",
    "AsyncEngine",
    "configure_token_blocklist",
    "datetime",
    "delete",
    "get_default_runtime",
    "hash_password",
    "is_token_revoked",
    "issue_access_token",
    "revoke_token",
    "select",
    "timedelta",
    "timezone",
    "verify_password",
]
