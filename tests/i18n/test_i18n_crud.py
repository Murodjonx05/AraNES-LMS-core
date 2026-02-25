from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.i18n import crud
from src.i18n.exceptions import I18nLargeNotFoundError, I18nSmallNotFoundError


@pytest.mark.asyncio
async def test_get_small_by_key_raises_not_found(monkeypatch):
    monkeypatch.setattr(crud, "get_small_optional", AsyncMock(return_value=None))
    with pytest.raises(I18nSmallNotFoundError):
        await crud.get_small_by_key(SimpleNamespace(), "missing")


@pytest.mark.asyncio
async def test_get_large_raises_not_found(monkeypatch):
    monkeypatch.setattr(crud, "get_large_optional", AsyncMock(return_value=None))
    with pytest.raises(I18nLargeNotFoundError):
        await crud.get_large(SimpleNamespace(), key1="a", key2="b")


@pytest.mark.asyncio
async def test_upsert_small_merges_existing_data(monkeypatch):
    item = SimpleNamespace(key="k", title={"en": "Old", "ru": "Старый"})
    monkeypatch.setattr(crud, "get_small_optional", AsyncMock(return_value=item))
    session = SimpleNamespace(add=Mock(), commit=AsyncMock(), refresh=AsyncMock())

    result = await crud.upsert_small(
        session,
        key="k",
        translation_patch={"en": "New", "uz": "Yangi"},
    )

    assert result.title == {"en": "New", "ru": "Старый", "uz": "Yangi"}
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_upsert_large_merges_existing_data(monkeypatch):
    item = SimpleNamespace(key1="course", key2="description", description={"en": "Old"})
    monkeypatch.setattr(crud, "get_large_optional", AsyncMock(return_value=item))
    session = SimpleNamespace(add=Mock(), commit=AsyncMock(), refresh=AsyncMock())

    result = await crud.upsert_large(
        session,
        key1="course",
        key2="description",
        translation_patch={"ru": "Описание"},
    )

    assert result.description == {"en": "Old", "ru": "Описание"}
    session.commit.assert_awaited_once()
