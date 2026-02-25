from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import TypeVar

from src.user_role.models import Role, User

RBACModel = TypeVar("RBACModel", Role, User)

RBAC_CAN_MANAGE_PERMISSIONS = "rbac_can_manage_permissions"

RBAC_ROLE_PERMISSION_DEFAULTS: dict[str, dict[str, bool]] = {
    "SuperAdmin": {
        RBAC_CAN_MANAGE_PERMISSIONS: True,
    },
    "Admin": {
        RBAC_CAN_MANAGE_PERMISSIONS: False,
    },
    "Teacher": {
        RBAC_CAN_MANAGE_PERMISSIONS: False,
    },
    "Student": {
        RBAC_CAN_MANAGE_PERMISSIONS: False,
    },
    "User": {
        RBAC_CAN_MANAGE_PERMISSIONS: False,
    },
    "Guest": {
        RBAC_CAN_MANAGE_PERMISSIONS: False,
    },
}


def get_rbac_role_permission_defaults(role_name: str) -> dict[str, bool]:
    return dict(RBAC_ROLE_PERMISSION_DEFAULTS.get(role_name, {}))


class RBACService:
    def __init__(self, role_permission_defaults: dict[str, dict[str, bool]] | None = None):
        self._role_permission_defaults: dict[str, dict[str, bool]] = {}
        if role_permission_defaults:
            self.register_role_permission_defaults(role_permission_defaults)

    def register_role_permission_defaults(self, mapping: dict[str, dict[str, bool]]) -> None:
        for role_name, permissions in mapping.items():
            current = self._role_permission_defaults.setdefault(role_name, {})
            current.update(dict(permissions))

    def get_default_role_permissions(self, role_name: str) -> dict[str, bool]:
        return dict(self._role_permission_defaults.get(role_name, {}))

    async def init_role_permissions_if_missing(self, session: AsyncSession) -> int:
        result = await session.execute(select(Role))
        roles = list(result.scalars().all())

        updated = 0
        for role in roles:
            defaults = self.get_default_role_permissions(role.name)
            if not defaults:
                continue

            permissions = role.permissions or {}
            changed = False
            for key, value in defaults.items():
                if key not in permissions:
                    permissions[key] = value
                    changed = True

            if changed:
                role.permissions = permissions
                session.add(role)
                updated += 1

        if updated:
            await session.commit()

        return updated


class PermissionService:
    async def update(
        self,
        session: AsyncSession,
        obj: RBACModel,
        permissions: dict[str, bool],
    ) -> RBACModel:
        obj.permissions = obj.permissions or {}
        obj.permissions.update(permissions)

        # если НЕ используешь MutableDict, делай так:
        # obj.permissions = dict(obj.permissions)

        session.add(obj)
        await session.commit()
        await session.refresh(obj)
        return obj

    async def get_all(self, session: AsyncSession, model_cls: type[RBACModel]) -> list[RBACModel]:
        result = await session.execute(select(model_cls))
        return list(result.scalars().all())

    async def reset_all(self, session: AsyncSession, model_cls: type[RBACModel]) -> int:
        result = await session.execute(select(model_cls))
        items = list(result.scalars().all())

        for obj in items:
            obj.permissions = {}
            session.add(obj)

        await session.commit()
        return len(items)
