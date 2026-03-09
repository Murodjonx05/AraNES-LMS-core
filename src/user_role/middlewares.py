from dataclasses import dataclass
from typing import Any

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select

from src.auth.dependencies import get_cached_access_token_payload
from src.database import DbSession
from src.user_role.models import Role, User
from src.utils.profiler import profile_function

_CURRENT_USER_ROLE_STATE_KEY = "_current_user_with_role"
_CURRENT_ACTOR_STATE_KEY = "_current_actor"


@dataclass(slots=True)
class CurrentActor:
    user_id: int
    role_id: int
    effective_permissions: dict[str, bool]


def _build_effective_permissions(
    *,
    user_permissions: dict[str, bool] | None,
    role_permissions: dict[str, bool] | None,
) -> dict[str, bool]:
    effective_permissions: dict[str, bool] = {}
    if role_permissions:
        effective_permissions.update(role_permissions)
    if user_permissions:
        effective_permissions.update(user_permissions)
    return effective_permissions


def _build_current_actor(
    *,
    user_id: int,
    role_id: int,
    user_permissions: dict[str, bool] | None,
    role_permissions: dict[str, bool] | None,
) -> CurrentActor:
    return CurrentActor(
        user_id=user_id,
        role_id=role_id,
        effective_permissions=_build_effective_permissions(
            user_permissions=user_permissions,
            role_permissions=role_permissions,
        ),
    )


def _get_cached_actor_from_user_role_pair(request: Request) -> CurrentActor | None:
    cached_pair = getattr(request.state, _CURRENT_USER_ROLE_STATE_KEY, None)
    if not (isinstance(cached_pair, tuple) and len(cached_pair) == 2):
        return None
    user, role = cached_pair
    user_id = getattr(user, "id", None)
    role_id = getattr(role, "id", None)
    if not isinstance(user_id, int) or user_id <= 0:
        return None
    if not isinstance(role_id, int) or role_id <= 0:
        return None
    actor = _build_current_actor(
        user_id=user_id,
        role_id=role_id,
        user_permissions=getattr(user, "permissions", None),
        role_permissions=getattr(role, "permissions", None),
    )
    setattr(request.state, _CURRENT_ACTOR_STATE_KEY, actor)
    return actor


def _payload_claim(payload: Any, key: str) -> Any:
    value = getattr(payload, key, None)
    if value is not None:
        return value
    if isinstance(payload, dict):
        return payload.get(key)
    if hasattr(payload, "model_dump"):
        return payload.model_dump().get(key)
    return None


def _resolve_token_user_id(payload: Any) -> int | None:
    raw_user_id = _payload_claim(payload, "uid")
    if raw_user_id is None:
        return None
    if isinstance(raw_user_id, int) and raw_user_id > 0:
        return raw_user_id
    if isinstance(raw_user_id, str) and raw_user_id.strip().isdigit():
        user_id = int(raw_user_id.strip())
        if user_id > 0:
            return user_id
    raise HTTPException(status_code=401, detail="Invalid token user id")


def _resolve_token_username(payload: Any) -> str:
    username = _payload_claim(payload, "sub")
    if isinstance(username, str) and username:
        return username
    raise HTTPException(status_code=401, detail="Invalid token subject")


@profile_function()
async def get_current_user_with_role(
    request: Request,
    session: DbSession,
    payload: Any = Depends(get_cached_access_token_payload),
) -> tuple[User, Role]:
    cached_pair = getattr(request.state, _CURRENT_USER_ROLE_STATE_KEY, None)
    if cached_pair is not None:
        return cached_pair

    user_id = _resolve_token_user_id(payload)

    query = select(User, Role).join(Role, Role.id == User.role_id).limit(1)
    if user_id is not None:
        query = query.where(User.id == user_id)
    else:
        query = query.where(User.username == _resolve_token_username(payload))

    result = await session.execute(query)
    row = result.first()
    if row is None:
        raise HTTPException(status_code=401, detail="User not found")
    user, role = row
    setattr(request.state, _CURRENT_USER_ROLE_STATE_KEY, (user, role))
    setattr(
        request.state,
        _CURRENT_ACTOR_STATE_KEY,
        _build_current_actor(
            user_id=user.id,
            role_id=role.id,
            user_permissions=user.permissions,
            role_permissions=role.permissions,
        ),
    )
    return user, role


@profile_function()
async def get_current_actor(
    request: Request,
    session: DbSession,
    payload: Any = Depends(get_cached_access_token_payload),
) -> CurrentActor:
    cached_actor = getattr(request.state, _CURRENT_ACTOR_STATE_KEY, None)
    if cached_actor is not None:
        return cached_actor
    cached_actor = _get_cached_actor_from_user_role_pair(request)
    if cached_actor is not None:
        return cached_actor

    user_id = _resolve_token_user_id(payload)

    query = (
        select(
            User.id,
            User.role_id,
            User.permissions,
            Role.permissions,
        )
        .join(Role, Role.id == User.role_id)
        .limit(1)
    )
    if user_id is not None:
        query = query.where(User.id == user_id)
    else:
        query = query.where(User.username == _resolve_token_username(payload))

    result = await session.execute(query)
    row = result.first()
    if row is None:
        raise HTTPException(status_code=401, detail="User not found")
    user_id, role_id, user_permissions, role_permissions = row
    actor = _build_current_actor(
        user_id=user_id,
        role_id=role_id,
        user_permissions=user_permissions,
        role_permissions=role_permissions,
    )
    setattr(request.state, _CURRENT_ACTOR_STATE_KEY, actor)
    return actor


def require_permission(permission_key: str):
    dependency_name = f"{__name__}.require_permission[{permission_key}]"

    @profile_function(name=dependency_name)
    async def _require_permission(
        actor: CurrentActor = Depends(get_current_actor),
    ) -> CurrentActor:
        if not actor.effective_permissions.get(permission_key, False):
            raise HTTPException(status_code=403, detail=f"Missing permission: {permission_key}")

        return actor

    return _require_permission


def has_permission(user: User, role: Role, permission_key: str) -> bool:
    effective_permissions = _build_effective_permissions(
        user_permissions=user.permissions,
        role_permissions=role.permissions,
    )
    return bool(effective_permissions.get(permission_key, False))


def ensure_permission(user: User, role: Role, permission_key: str) -> None:
    if not has_permission(user, role, permission_key):
        raise HTTPException(status_code=403, detail=f"Missing permission: {permission_key}")
