from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import load_only
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.exceptions import UsernameAlreadyExistsError
from src.config import AppConfig
from src.database import is_unique_violation
from src.runtime import get_default_runtime
from src.user_role.bootstrap import RBAC_SERVICE
from src.user_role.models import Role, User

PermissionMap = dict[str, bool]
_USERNAME_UNIQUE_IDENTIFIERS = (
    "users.username",
    "users_username_key",
    "key 'username'",
    "for key 'username'",
)


async def _get_exact_default_signup_role(
    session: AsyncSession,
    *,
    role_id: int,
    role_name: str,
) -> Role | None:
    result = await session.execute(
        select(Role).where(
            or_(
                Role.id == role_id,
                Role.name == role_name,
            )
        )
    )
    matches = list(result.scalars().all())
    if not matches:
        return None

    for role in matches:
        if role.id == role_id and role.name == role_name:
            return role

    if len(matches) == 1:
        role = matches[0]
        raise RuntimeError(
            "Default signup role drift detected. "
            f"Expected ({role_id}, '{role_name}') but found ({role.id}, '{role.name}')."
        )

    role_descriptions = ", ".join(f"({role.id}, '{role.name}')" for role in matches)
    raise RuntimeError(
        "Default signup role mapping drift detected. "
        f"Expected id {role_id} and name '{role_name}' to refer to one role, found: {role_descriptions}."
    )


async def get_user_for_login(session: AsyncSession, username: str) -> User | None:
    return await session.scalar(
        select(User)
        .options(load_only(User.id, User.username, User.password))
        .where(User.username == username)
        .limit(1)
    )


async def create_user(
    session: AsyncSession,
    *,
    username: str,
    password_hash: str,
    role_id: int,
    permissions: PermissionMap | None = None,
) -> User:
    db_user = User(
        username=username,
        password=password_hash,
        role_id=role_id,
        permissions=dict(permissions or {}),
    )
    session.add(db_user)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        if is_unique_violation(exc, identifiers=_USERNAME_UNIQUE_IDENTIFIERS):
            raise UsernameAlreadyExistsError("Username already exists") from exc
        raise
    return db_user


async def get_or_create_default_signup_role(session: AsyncSession) -> Role:
    return await get_or_create_default_signup_role_with_config(session)


async def get_or_create_default_signup_role_with_config(
    session: AsyncSession,
    *,
    config: AppConfig | None = None,
) -> Role:
    app_config = config or get_default_runtime().config
    db_role = await _get_exact_default_signup_role(
        session,
        role_id=app_config.DEFAULT_SIGNUP_ROLE_ID,
        role_name=app_config.DEFAULT_SIGNUP_ROLE_NAME,
    )
    if db_role is not None:
        return db_role

    db_role = Role(
        id=app_config.DEFAULT_SIGNUP_ROLE_ID,
        name=app_config.DEFAULT_SIGNUP_ROLE_NAME,
        title_key=app_config.DEFAULT_SIGNUP_ROLE_TITLE_KEY,
        permissions=RBAC_SERVICE.get_default_role_permissions(app_config.DEFAULT_SIGNUP_ROLE_NAME),
    )
    session.add(db_role)
    await session.flush()
    return db_role
