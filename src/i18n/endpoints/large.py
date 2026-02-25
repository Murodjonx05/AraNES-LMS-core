from fastapi import APIRouter, Depends, HTTPException

from src.database import DbSession
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
from src.user_role.middlewares import ensure_permission, get_current_user_with_role
from src.user_role.models import Role, User

large_route = APIRouter(
    prefix="/large",
    tags=[f"i18n:large({LARGE_I18N_DATA_MAX_LENGTH})"],
)


@large_route.get("")
async def list_large(session: DbSession):
    items = await crud_list_large(session)
    return [serialize_large(item) for item in items]


@large_route.get("/{key1}/{key2}")
async def get_large(key1: str, key2: str, session: DbSession):
    try:
        item = await crud_get_large(session, key1=key1, key2=key2)
    except I18nLargeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return serialize_large(item)


@large_route.put("")
async def upsert_large(
    payload: I18nLargeSchema,
    session: DbSession,
    user_role_pair: tuple[User, Role] = Depends(get_current_user_with_role),
):
    user, role = user_role_pair
    existing_item = await crud_get_large_optional(
        session,
        key1=payload.key1,
        key2=payload.key2,
    )
    if existing_item is None:
        ensure_permission(user, role, I18N_CAN_CREATE_LARGE)
    else:
        ensure_permission(user, role, I18N_CAN_PATCH_LARGE)
    item = await crud_upsert_large(
        session,
        key1=payload.key1,
        key2=payload.key2,
        translation_patch=payload.data,
    )
    return serialize_large(item)
