from fastapi import APIRouter, Depends, HTTPException

from src.database import DbSession
from src.i18n.crud import (
    get_small_by_key as crud_get_small_by_key,
    get_small_optional as crud_get_small_optional,
    list_small as crud_list_small,
    upsert_small as crud_upsert_small,
)
from src.i18n.endpoints.serializers import serialize_small
from src.i18n.exceptions import I18nSmallNotFoundError
from src.i18n.permission import I18N_CAN_CREATE_SMALL, I18N_CAN_PATCH_SMALL
from src.i18n.schemas import I18nSmallSchema
from src.i18n.settings import SMALL_I18N_DATA_MAX_LENGTH
from src.user_role.middlewares import CurrentActor, get_current_actor

small_route = APIRouter(
    prefix="/small",
    tags=[f"i18n:small({SMALL_I18N_DATA_MAX_LENGTH})"],
)


@small_route.get("")
async def list_small(session: DbSession):
    items = await crud_list_small(session)
    return [serialize_small(item) for item in items]


@small_route.get("/{key}")
async def get_small(key: str, session: DbSession):
    try:
        item = await crud_get_small_by_key(session, key)
    except I18nSmallNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return serialize_small(item)


@small_route.put("")
async def upsert_small(
    payload: I18nSmallSchema,
    session: DbSession,
    actor: CurrentActor = Depends(get_current_actor),
):
    existing_item = await crud_get_small_optional(session, payload.key)
    if existing_item is None:
        permission_key = I18N_CAN_CREATE_SMALL
    else:
        permission_key = I18N_CAN_PATCH_SMALL
    if not actor.effective_permissions.get(permission_key, False):
        raise HTTPException(status_code=403, detail=f"Missing permission: {permission_key}")
    item = await crud_upsert_small(
        session,
        key=payload.key,
        translation_patch=payload.data,
    )
    return serialize_small(item)
