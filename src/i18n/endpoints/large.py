from fastapi import APIRouter, Depends, HTTPException

from src.database import DbSession
from src.i18n.cache import I18nCacheService, get_request_i18n_cache_service
from src.i18n.crud import (
    get_large as crud_get_large,
    get_large_optional as crud_get_large_optional,
    list_large as crud_list_large,
    upsert_large as crud_upsert_large,
)
from src.i18n.endpoints.serializers import serialize_large
from src.i18n.exceptions import I18nLargeNotFoundError
from src.i18n.permission import I18N_CAN_CREATE_LARGE, I18N_CAN_PATCH_LARGE
from src.i18n.schemas import I18nLargeSchema
from src.i18n.settings import LARGE_I18N_DATA_MAX_LENGTH
from src.user_role.middlewares import CurrentActor, get_current_actor

large_route = APIRouter(
    prefix="/large",
    tags=[f"i18n:large({LARGE_I18N_DATA_MAX_LENGTH})"],
)


@large_route.get("")
async def list_large(session: DbSession):
    items = await crud_list_large(session)
    return [serialize_large(item) for item in items]


@large_route.get("/{key1}/{key2}")
async def get_large(
    key1: str,
    key2: str,
    session: DbSession,
    cache_service: I18nCacheService = Depends(get_request_i18n_cache_service),
):
    cached_item = await cache_service.get_large(key1, key2)
    if cached_item is not None:
        return cached_item
    try:
        item = await crud_get_large(session, key1=key1, key2=key2)
    except I18nLargeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    payload = serialize_large(item)
    await cache_service.set_large(key1, key2, payload)
    return payload


@large_route.put("")
async def upsert_large(
    payload: I18nLargeSchema,
    session: DbSession,
    actor: CurrentActor = Depends(get_current_actor),
    cache_service: I18nCacheService = Depends(get_request_i18n_cache_service),
):
    existing_item = await crud_get_large_optional(
        session,
        key1=payload.key1,
        key2=payload.key2,
    )
    if existing_item is None:
        permission_key = I18N_CAN_CREATE_LARGE
    else:
        permission_key = I18N_CAN_PATCH_LARGE
    if not actor.effective_permissions.get(permission_key, False):
        raise HTTPException(status_code=403, detail=f"Missing permission: {permission_key}")
    item = await crud_upsert_large(
        session,
        key1=payload.key1,
        key2=payload.key2,
        translation_patch=payload.data,
    )
    await cache_service.invalidate_large(payload.key1, payload.key2)
    return serialize_large(item)
