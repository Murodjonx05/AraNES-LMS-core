from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.exceptions import UsernameAlreadyExistsError
from src.settings import APP
from src.user_role.bootstrap import RBAC_SERVICE
from src.user_role.models import Role, User

PermissionMap = dict[str, bool]


async def get_user_by_username(session: AsyncSession, username: str) -> User | None:
    query_result = await session.execute(select(User).where(User.username == username))
    return query_result.scalar_one_or_none()


async def create_user(
    session: AsyncSession,
    *,
    username: str,
    password_hash: str,
    role_id: int,
    permissions: PermissionMap | None = None,
) -> User:
    existing_user = await get_user_by_username(session, username)
    if existing_user is not None:
        raise UsernameAlreadyExistsError("Username already exists")

    db_user = User(
        username=username,
        password=password_hash,
        role_id=role_id,
        permissions=dict(permissions or {}),
    )
    session.add(db_user)
    await session.commit()
    return db_user


async def get_or_create_default_signup_role(session: AsyncSession) -> Role:
    query_result = await session.execute(
        select(Role).where(Role.name == APP.DEFAULT_SIGNUP_ROLE_NAME)
    )
    db_role = query_result.scalar_one_or_none()
    if db_role is not None:
        return db_role

    db_role = Role(
        id=APP.DEFAULT_SIGNUP_ROLE_ID,
        name=APP.DEFAULT_SIGNUP_ROLE_NAME,
        title_key=APP.DEFAULT_SIGNUP_ROLE_TITLE_KEY,
        permissions=RBAC_SERVICE.get_default_role_permissions(APP.DEFAULT_SIGNUP_ROLE_NAME),
    )
    session.add(db_role)
    await session.flush()
    return db_role
