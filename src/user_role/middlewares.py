from typing import Any

from fastapi import Depends, HTTPException
from sqlalchemy import select

from src.database import DbSession
from src.settings import SECURITY
from src.user_role.models import Role, User


async def get_current_user_with_role(
    session: DbSession,
    payload: Any = Depends(SECURITY.access_token_required),
) -> tuple[User, Role]:
    username = getattr(payload, "sub", None)
    if not username:
        raise HTTPException(status_code=401, detail="Invalid token subject")

    result = await session.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")

    role = await session.get(Role, user.role_id)
    if role is None:
        raise HTTPException(status_code=403, detail="Role not found")

    return user, role


def require_permission(permission_key: str):
    async def _require_permission(
        user_role_pair: tuple[User, Role] = Depends(get_current_user_with_role),
    ) -> tuple[User, Role]:
        user, role = user_role_pair

        effective_permissions: dict[str, bool] = {}
        effective_permissions.update(role.permissions or {})
        effective_permissions.update(user.permissions or {})

        if not effective_permissions.get(permission_key, False):
            raise HTTPException(status_code=403, detail=f"Missing permission: {permission_key}")

        return user, role

    return _require_permission


def has_permission(user: User, role: Role, permission_key: str) -> bool:
    effective_permissions: dict[str, bool] = {}
    effective_permissions.update(role.permissions or {})
    effective_permissions.update(user.permissions or {})
    return bool(effective_permissions.get(permission_key, False))


def ensure_permission(user: User, role: Role, permission_key: str) -> None:
    if not has_permission(user, role, permission_key):
        raise HTTPException(status_code=403, detail=f"Missing permission: {permission_key}")
