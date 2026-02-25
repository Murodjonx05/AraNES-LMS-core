from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from src.settings import APP

class Model(DeclarativeBase):
    pass

async_engine = create_async_engine(APP.DATABASE_URL, echo=False)


async def get_db_session() -> AsyncSession:
    async with AsyncSession(
        bind=async_engine,
        expire_on_commit=False
    ) as session:
        yield session


DbSession = Annotated[AsyncSession, Depends(get_db_session)]


@asynccontextmanager
async def session_scope() -> AsyncSession:
    async with AsyncSession(
        bind=async_engine,
        expire_on_commit=False
    ) as session:
        yield session
