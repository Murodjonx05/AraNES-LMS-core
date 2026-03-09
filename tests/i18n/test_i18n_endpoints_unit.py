from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.i18n.endpoints import large as large_endpoints
from src.i18n.endpoints import small as small_endpoints
from src.i18n.schemas import I18nLargeSchema, I18nSmallSchema
from src.i18n.permission import (
    I18N_CAN_CREATE_LARGE,
    I18N_CAN_CREATE_SMALL,
    I18N_CAN_PATCH_LARGE,
    I18N_CAN_PATCH_SMALL,
)


def _cache_service():
    return SimpleNamespace(
        invalidate_small=AsyncMock(),
        invalidate_small_list=AsyncMock(),
        invalidate_small_entry_and_list=AsyncMock(),
        invalidate_large=AsyncMock(),
        invalidate_large_list=AsyncMock(),
        invalidate_large_entry_and_list=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_small_upsert_endpoint_passes_preloaded_existing_item(monkeypatch):
    existing_item = SimpleNamespace(key="role.student.title", title={"en": "Student"})
    updated_item = SimpleNamespace(key="role.student.title", title={"en": "Student", "ru": "Студент"})
    crud_get_small_optional = AsyncMock(return_value=existing_item)
    crud_upsert_small = AsyncMock(return_value=updated_item)
    cache_service = _cache_service()
    session = SimpleNamespace()

    monkeypatch.setattr(small_endpoints, "crud_get_small_optional", crud_get_small_optional)
    monkeypatch.setattr(small_endpoints, "crud_upsert_small", crud_upsert_small)

    response = await small_endpoints.upsert_small(
        payload=I18nSmallSchema(key="role.student.title", data={"ru": "Студент"}),
        session=session,
        actor=SimpleNamespace(effective_permissions={I18N_CAN_PATCH_SMALL: True}),
        cache_service=cache_service,
    )

    assert response == {
        "key": "role.student.title",
        "data": {"en": "Student", "ru": "Студент"},
    }
    crud_upsert_small.assert_awaited_once_with(
        session,
        key="role.student.title",
        translation_patch={"ru": "Студент"},
        existing_item=existing_item,
        existing_item_loaded=True,
    )
    cache_service.invalidate_small_entry_and_list.assert_awaited_once_with("role.student.title")


@pytest.mark.asyncio
async def test_small_upsert_endpoint_passes_known_missing_item(monkeypatch):
    crud_get_small_optional = AsyncMock(return_value=None)
    created_item = SimpleNamespace(key="role.teacher.title", title={"en": "Teacher"})
    crud_upsert_small = AsyncMock(return_value=created_item)
    cache_service = _cache_service()
    session = SimpleNamespace()

    monkeypatch.setattr(small_endpoints, "crud_get_small_optional", crud_get_small_optional)
    monkeypatch.setattr(small_endpoints, "crud_upsert_small", crud_upsert_small)

    response = await small_endpoints.upsert_small(
        payload=I18nSmallSchema(key="role.teacher.title", data={"en": "Teacher"}),
        session=session,
        actor=SimpleNamespace(effective_permissions={I18N_CAN_CREATE_SMALL: True}),
        cache_service=cache_service,
    )

    assert response == {
        "key": "role.teacher.title",
        "data": {"en": "Teacher"},
    }
    crud_upsert_small.assert_awaited_once_with(
        session,
        key="role.teacher.title",
        translation_patch={"en": "Teacher"},
        existing_item=None,
        existing_item_loaded=True,
    )
    cache_service.invalidate_small_entry_and_list.assert_awaited_once_with("role.teacher.title")


@pytest.mark.asyncio
async def test_large_upsert_endpoint_passes_preloaded_existing_item(monkeypatch):
    existing_item = SimpleNamespace(key1="course", key2="description", description={"en": "Course"})
    updated_item = SimpleNamespace(
        key1="course",
        key2="description",
        description={"en": "Course", "ru": "Курс"},
    )
    crud_get_large_optional = AsyncMock(return_value=existing_item)
    crud_upsert_large = AsyncMock(return_value=updated_item)
    cache_service = _cache_service()
    session = SimpleNamespace()

    monkeypatch.setattr(large_endpoints, "crud_get_large_optional", crud_get_large_optional)
    monkeypatch.setattr(large_endpoints, "crud_upsert_large", crud_upsert_large)

    response = await large_endpoints.upsert_large(
        payload=I18nLargeSchema(key1="course", key2="description", data={"ru": "Курс"}),
        session=session,
        actor=SimpleNamespace(effective_permissions={I18N_CAN_PATCH_LARGE: True}),
        cache_service=cache_service,
    )

    assert response == {
        "key1": "course",
        "key2": "description",
        "data": {"en": "Course", "ru": "Курс"},
    }
    crud_upsert_large.assert_awaited_once_with(
        session,
        key1="course",
        key2="description",
        translation_patch={"ru": "Курс"},
        existing_item=existing_item,
        existing_item_loaded=True,
    )
    cache_service.invalidate_large_entry_and_list.assert_awaited_once_with("course", "description")


@pytest.mark.asyncio
async def test_large_upsert_endpoint_passes_known_missing_item(monkeypatch):
    crud_get_large_optional = AsyncMock(return_value=None)
    created_item = SimpleNamespace(key1="course", key2="summary", description={"en": "Summary"})
    crud_upsert_large = AsyncMock(return_value=created_item)
    cache_service = _cache_service()
    session = SimpleNamespace()

    monkeypatch.setattr(large_endpoints, "crud_get_large_optional", crud_get_large_optional)
    monkeypatch.setattr(large_endpoints, "crud_upsert_large", crud_upsert_large)

    response = await large_endpoints.upsert_large(
        payload=I18nLargeSchema(key1="course", key2="summary", data={"en": "Summary"}),
        session=session,
        actor=SimpleNamespace(effective_permissions={I18N_CAN_CREATE_LARGE: True}),
        cache_service=cache_service,
    )

    assert response == {
        "key1": "course",
        "key2": "summary",
        "data": {"en": "Summary"},
    }
    crud_upsert_large.assert_awaited_once_with(
        session,
        key1="course",
        key2="summary",
        translation_patch={"en": "Summary"},
        existing_item=None,
        existing_item_loaded=True,
    )
    cache_service.invalidate_large_entry_and_list.assert_awaited_once_with("course", "summary")
