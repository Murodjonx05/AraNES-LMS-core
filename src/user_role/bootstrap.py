from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.i18n.permission import get_i18n_role_permission_defaults
from src.user_role.defaults import DEFAULT_ROLES
from src.user_role.permission import RBACService, get_rbac_role_permission_defaults


def get_default_role_permissions(role_name: str) -> dict[str, bool]:
    permissions: dict[str, bool] = {}
    permissions.update(get_i18n_role_permission_defaults(role_name))
    permissions.update(get_rbac_role_permission_defaults(role_name))
    return permissions


RBAC_SERVICE = RBACService(
    {
        role_name: get_default_role_permissions(role_name)
        for _, role_name, _ in DEFAULT_ROLES
    }
)
_DEFAULT_ROLE_IDS = tuple(role_id for role_id, _, _ in DEFAULT_ROLES)
_DEFAULT_ROLE_NAMES = tuple(role_name for _, role_name, _ in DEFAULT_ROLES)


def _resolve_default_role_match(
    *,
    role_id: int,
    role_name: str,
    by_id: dict[int, object],
    by_name: dict[str, object],
):
    existing_by_id = by_id.get(role_id)
    existing_by_name = by_name.get(role_name)

    if existing_by_id is None and existing_by_name is None:
        return None

    if (
        existing_by_id is not None
        and existing_by_name is not None
        and existing_by_id is not existing_by_name
    ):
        raise RuntimeError(
            "Default role mapping drift detected. "
            f"Role id {role_id} maps to '{getattr(existing_by_id, 'name', None)}' "
            f"while role name '{role_name}' maps to id {getattr(existing_by_name, 'id', None)}'."
        )

    existing = existing_by_id or existing_by_name
    if existing is None:
        return None

    if getattr(existing, "id", None) != role_id or getattr(existing, "name", None) != role_name:
        raise RuntimeError(
            "Default role drift detected. "
            f"Expected role ({role_id}, '{role_name}') but found "
            f"({getattr(existing, 'id', None)}, '{getattr(existing, 'name', None)}')."
        )

    return existing


async def seed_roles_if_missing(session: AsyncSession, *, commit: bool = True) -> int:
    """
    Seed default roles if they do not already exist.
    Returns the number of roles created.
    """
    from src.user_role.models import Role

    # Only default-role candidates matter for seeding/drift checks.
    result = await session.execute(
        select(Role).where(
            (Role.id.in_(_DEFAULT_ROLE_IDS)) | (Role.name.in_(_DEFAULT_ROLE_NAMES))
        )
    )
    existing_roles = list(result.scalars().all())

    # Use both ID and name as lookup keys for existence
    by_id = {role.id: role for role in existing_roles}
    by_name = {role.name: role for role in existing_roles}

    created = 0
    roles_to_update = []
    roles_to_add = []

    for role_id, role_name, role_title_key in DEFAULT_ROLES:
        existing = _resolve_default_role_match(
            role_id=role_id,
            role_name=role_name,
            by_id=by_id,
            by_name=by_name,
        )
        if existing:
            # Only update title_key if it's missing or falsy
            if not getattr(existing, "title_key", None):
                existing.title_key = role_title_key
                roles_to_update.append(existing)
            continue

        roles_to_add.append(
            Role(
                id=role_id,
                name=role_name,
                title_key=role_title_key,
                permissions=RBAC_SERVICE.get_default_role_permissions(role_name),
            )
        )
        created += 1

    # Bulk add and update outside of loop for efficiency
    if roles_to_add:
        session.add_all(roles_to_add)
    if roles_to_update:
        session.add_all(roles_to_update)

    if commit and (roles_to_add or roles_to_update or session.dirty):
        await session.commit()

    await RBAC_SERVICE.init_role_permissions_if_missing(
        session,
        commit=commit,
        roles=[*existing_roles, *roles_to_add],
    )

    return created
