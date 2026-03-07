from __future__ import annotations

from dataclasses import dataclass
from threading import Lock

from authx import AuthX
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from src.config import AppConfig, build_app_config
from src.utils.cache import RedisCacheService


@dataclass(slots=True)
class RuntimeContext:
    config: AppConfig
    security: AuthX
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    cache_service: RedisCacheService


def _build_engine_kwargs(database_url: str, *, in_memory: bool) -> dict:
    engine_kwargs = {"echo": False}
    if database_url.startswith("sqlite") and in_memory:
        engine_kwargs["poolclass"] = StaticPool
        engine_kwargs["connect_args"] = {"check_same_thread": False}
    return engine_kwargs


def build_runtime(config: AppConfig, in_memory: bool = False) -> RuntimeContext:
    security = AuthX(config=config.AUTH_CONFIG)
    engine_kwargs = _build_engine_kwargs(config.DATABASE_URL, in_memory=in_memory)
    engine = create_async_engine(config.DATABASE_URL, **engine_kwargs)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    cache_service = RedisCacheService(
        enabled=bool(getattr(config, "REDIS_ENABLED", False)),
        redis_url=str(getattr(config, "REDIS_URL", "redis://localhost:6379/0")),
        default_ttl_seconds=int(getattr(config, "REDIS_DEFAULT_TTL_SECONDS", 3600)),
        heartbeat_enabled=bool(getattr(config, "REDIS_HEARTBEAT_ENABLED", True)),
        heartbeat_schedule_seconds=tuple(
            getattr(
                config,
                "REDIS_HEARTBEAT_SCHEDULE_SECONDS",
                (60, 600, 1200, 3600, 14400, 28800, 43200),
            )
        ),
    )
    runtime = RuntimeContext(
        config=config,
        security=security,
        engine=engine,
        session_factory=session_factory,
        cache_service=cache_service,
    )

    from src.auth.service import configure_token_blocklist

    configure_token_blocklist(security=security, engine=engine, cache_service=cache_service)
    return runtime


def create_runtime_from_env() -> RuntimeContext:
    return build_runtime(build_app_config())


_default_runtime: RuntimeContext | None = None
_default_runtime_lock = Lock()


def get_default_runtime() -> RuntimeContext:
    global _default_runtime
    if _default_runtime is not None:
        return _default_runtime

    with _default_runtime_lock:
        if _default_runtime is None:
            _default_runtime = create_runtime_from_env()
        return _default_runtime


def reset_default_runtime() -> None:
    global _default_runtime
    with _default_runtime_lock:
        _default_runtime = None


__all__ = [
    "RuntimeContext",
    "build_runtime",
    "create_runtime_from_env",
    "get_default_runtime",
    "reset_default_runtime",
]