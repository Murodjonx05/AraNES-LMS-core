from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.i18n import crud
from src.i18n import translates
from src.i18n.exceptions import I18nLargeNotFoundError, I18nSmallNotFoundError


@pytest.fixture(autouse=True)
def _reset_translate_registries():
    small_snapshot = dict(translates.SMALL_TRANSLATES_REGISTRY)
    large_snapshot = dict(translates.LARGE_TRANSLATES_REGISTRY)
    translates.SMALL_TRANSLATES_REGISTRY.clear()
    translates.LARGE_TRANSLATES_REGISTRY.clear()
    yield
    translates.SMALL_TRANSLATES_REGISTRY.clear()
    translates.SMALL_TRANSLATES_REGISTRY.update(small_snapshot)
    translates.LARGE_TRANSLATES_REGISTRY.clear()
    translates.LARGE_TRANSLATES_REGISTRY.update(large_snapshot)


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
async def test_upsert_small_skips_lookup_when_existing_item_is_preloaded(monkeypatch):
    existing_item = SimpleNamespace(key="k", title={"en": "Old"})
    get_small_optional = AsyncMock(side_effect=AssertionError("lookup should be skipped"))
    monkeypatch.setattr(crud, "get_small_optional", get_small_optional)
    session = SimpleNamespace(add=Mock(), commit=AsyncMock())

    result = await crud.upsert_small(
        session,
        key="k",
        translation_patch={"ru": "Новый"},
        existing_item=existing_item,
        existing_item_loaded=True,
    )

    assert result is existing_item
    assert result.title == {"en": "Old", "ru": "Новый"}
    get_small_optional.assert_not_awaited()
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


@pytest.mark.asyncio
async def test_upsert_large_skips_lookup_when_existing_item_is_preloaded(monkeypatch):
    existing_item = SimpleNamespace(key1="course", key2="description", description={"en": "Old"})
    get_large_optional = AsyncMock(side_effect=AssertionError("lookup should be skipped"))
    monkeypatch.setattr(crud, "get_large_optional", get_large_optional)
    session = SimpleNamespace(add=Mock(), commit=AsyncMock())

    result = await crud.upsert_large(
        session,
        key1="course",
        key2="description",
        translation_patch={"ru": "Описание"},
        existing_item=existing_item,
        existing_item_loaded=True,
    )

    assert result is existing_item
    assert result.description == {"en": "Old", "ru": "Описание"}
    get_large_optional.assert_not_awaited()
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_register_and_upsert_small_registers_merged_translation_state(monkeypatch):
    item = SimpleNamespace(
        key="role.student.title",
        title={"en": "Student", "ru": "Студент", "uz": "Talaba"},
    )
    monkeypatch.setattr(crud, "upsert_small", AsyncMock(return_value=item))

    result = await crud.register_and_upsert_small(
        SimpleNamespace(),
        key="role.student.title",
        translation_patch={"uz": "Talaba"},
    )

    assert result is item
    assert translates.get_registered_small_translates() == {
        "role.student.title": {"en": "Student", "ru": "Студент", "uz": "Talaba"}
    }


@pytest.mark.asyncio
async def test_register_and_upsert_small_does_not_mutate_registry_on_failed_upsert(monkeypatch):
    translates.register_small_translate("role.student.title", {"en": "Student", "ru": "Студент"})
    monkeypatch.setattr(crud, "upsert_small", AsyncMock(side_effect=RuntimeError("db failed")))

    with pytest.raises(RuntimeError, match="db failed"):
        await crud.register_and_upsert_small(
            SimpleNamespace(),
            key="role.student.title",
            translation_patch={"uz": "Talaba"},
        )

    assert translates.get_registered_small_translates() == {
        "role.student.title": {"en": "Student", "ru": "Студент"}
    }


@pytest.mark.asyncio
async def test_register_and_upsert_large_registers_merged_translation_state(monkeypatch):
    item = SimpleNamespace(
        key1="course",
        key2="description",
        description={"en": "Course", "ru": "Курс", "uz": "Kurs"},
    )
    monkeypatch.setattr(crud, "upsert_large", AsyncMock(return_value=item))

    result = await crud.register_and_upsert_large(
        SimpleNamespace(),
        key1="course",
        key2="description",
        translation_patch={"uz": "Kurs"},
    )

    assert result is item
    assert translates.get_registered_large_translates() == {
        ("course", "description"): {"en": "Course", "ru": "Курс", "uz": "Kurs"}
    }


@pytest.mark.asyncio
async def test_register_and_upsert_large_does_not_mutate_registry_on_failed_upsert(monkeypatch):
    translates.register_large_translate("course", "description", {"en": "Course", "ru": "Курс"})
    monkeypatch.setattr(crud, "upsert_large", AsyncMock(side_effect=RuntimeError("db failed")))

    with pytest.raises(RuntimeError, match="db failed"):
        await crud.register_and_upsert_large(
            SimpleNamespace(),
            key1="course",
            key2="description",
            translation_patch={"uz": "Kurs"},
        )

    assert translates.get_registered_large_translates() == {
        ("course", "description"): {"en": "Course", "ru": "Курс"}
    }
