from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from authx import AuthX
from sqlalchemy import Column, DateTime, MetaData, String, Table, delete, select
from sqlalchemy.ext.asyncio import AsyncEngine

from src.utils.cache import RedisCacheService

FALLBACK_RAW_TOKEN_TTL = timedelta(days=30)
_TOKEN_REVOCATION_CACHE_TTL_SECONDS_ENV = "TOKEN_REVOCATION_CACHE_TTL_SECONDS"
_TOKEN_REVOCATION_CACHE_MAX_ENTRIES = 4096
_TOKEN_IDENTITY_CACHE_MAX_ENTRIES = 2048
_REVOCATION_CACHE_KEY_PREFIX = "auth:revoked"

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


def _normalize_expiry(expires_at: datetime) -> datetime:
    if expires_at.tzinfo is None:
        return expires_at.replace(tzinfo=timezone.utc)
    return expires_at.astimezone(timezone.utc)


@lru_cache(maxsize=1)
def _get_token_revocation_cache_ttl_seconds() -> float:
    import os

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
        {"revoked": revoked, "expires_at": normalized_expiry.isoformat()},
        ttl_seconds=ttl_seconds,
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
