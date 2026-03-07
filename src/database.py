from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from src.runtime import RuntimeContext, get_default_runtime

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

    async_engine: AsyncEngine

__all__ = ["Model", "async_engine", "DbSession", "get_db_session", "session_scope"]


class Model(DeclarativeBase):
    pass


def _resolve_session_factory(
    *,
    request: Request | None = None,
    runtime: RuntimeContext | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> async_sessionmaker[AsyncSession]:
    if session_factory is not None:
        return session_factory
    if runtime is not None:
        return runtime.session_factory
    if request is not None and (app_runtime := getattr(request.app.state, "runtime", None)) is not None:
        return app_runtime.session_factory
    return get_default_runtime().session_factory


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    factory = _resolve_session_factory(request=request)
    async with factory() as session:
        yield session


DbSession = Annotated[AsyncSession, Depends(get_db_session)]


@asynccontextmanager
async def session_scope(
    *,
    runtime: RuntimeContext | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> AsyncIterator[AsyncSession]:
    factory = _resolve_session_factory(runtime=runtime, session_factory=session_factory)
    async with factory() as session:
        yield session


def __getattr__(name: str):
    if name == "async_engine":
        return get_default_runtime().engine
    raise AttributeError(name)
