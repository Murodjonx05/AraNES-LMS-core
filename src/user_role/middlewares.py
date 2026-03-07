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


@profile_function()
async def get_current_user_with_role(
    request: Request,
    session: DbSession,
    payload: Any = Depends(get_cached_access_token_payload),
) -> tuple[User, Role]:
    cached_pair = getattr(request.state, _CURRENT_USER_ROLE_STATE_KEY, None)
    if cached_pair is not None:
        return cached_pair

    username = getattr(payload, "sub", None)
    if not username:
        raise HTTPException(status_code=401, detail="Invalid token subject")

    result = await session.execute(
        select(User, Role)
        .join(Role, Role.id == User.role_id)
        .where(User.username == username)
        .limit(1)
    )
    row = result.first()
    if row is None:
        raise HTTPException(status_code=401, detail="User not found")
    user, role = row
    setattr(request.state, _CURRENT_USER_ROLE_STATE_KEY, (user, role))
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

    username = getattr(payload, "sub", None)
    if not username:
        raise HTTPException(status_code=401, detail="Invalid token subject")

    result = await session.execute(
        select(
            User.id,
            User.role_id,
            User.permissions,
            Role.permissions,
        )
        .join(Role, Role.id == User.role_id)
        .where(User.username == username)
        .limit(1)
    )
    row = result.first()
    if row is None:
        raise HTTPException(status_code=401, detail="User not found")
    user_id, role_id, user_permissions, role_permissions = row
    effective_permissions: dict[str, bool] = {}
    effective_permissions.update(role_permissions or {})
    effective_permissions.update(user_permissions or {})
    actor = CurrentActor(
        user_id=user_id,
        role_id=role_id,
        effective_permissions=effective_permissions,
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
    effective_permissions: dict[str, bool] = {}
    effective_permissions.update(role.permissions or {})
    effective_permissions.update(user.permissions or {})
    return bool(effective_permissions.get(permission_key, False))


def ensure_permission(user: User, role: Role, permission_key: str) -> None:
    if not has_permission(user, role, permission_key):
        raise HTTPException(status_code=403, detail=f"Missing permission: {permission_key}")
