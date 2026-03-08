import argparse
import getpass
import logging
import os
from typing import Optional

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.auth.schemas import UserAuthBody
from src.database import session_scope
from src.user_role.defaults import SUPERADMIN_ROLE_ID

ENV_BOOTSTRAP_ENABLE = "BOOTSTRAP_SUPERUSER_CREATE"
ENV_BOOTSTRAP_USERNAME = "BOOTSTRAP_SUPERUSER_USERNAME"
ENV_BOOTSTRAP_PASSWORD = "BOOTSTRAP_SUPERUSER_PASSWORD"
_LOGGER = logging.getLogger("aranes.super_user")


def _ensure_logger_configured() -> None:
    if logging.getLogger().handlers:
        return
    logging.basicConfig(level=logging.INFO, format="%(message)s")


def _session_scope_ctx(
    *,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
):
    if session_factory is None:
        return session_scope()
    return session_scope(session_factory=session_factory)


async def is_super_user_exist(
    *,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> bool:
    """
    Checks if a superuser role already exists in the database.
    """
    from src.user_role.models import User

    async with _session_scope_ctx(session_factory=session_factory) as session:
        stmt = select(User).where(User.role_id == SUPERADMIN_ROLE_ID)
        result = await session.execute(stmt)
        return result.scalar_one_or_none() is not None


async def is_username_taken(
    username: str,
    *,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> bool:
    from src.user_role.models import User

    async with _session_scope_ctx(session_factory=session_factory) as session:
        stmt = select(User).where(User.username == username)
        result = await session.execute(stmt)
        return result.scalar_one_or_none() is not None


async def _ensure_superadmin_role_exists(session: AsyncSession) -> None:
    from src.user_role.models import Role

    role_exists = await session.scalar(select(Role.id).where(Role.id == SUPERADMIN_ROLE_ID).limit(1))
    if role_exists is None:
        raise RuntimeError(
            "SuperAdmin role does not exist. Seed default roles before creating the superuser."
        )


def _get_bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _log_info(message: str) -> None:
    _ensure_logger_configured()
    _LOGGER.info(message)


def _log_warning(message: str) -> None:
    _ensure_logger_configured()
    _LOGGER.warning(message)


def _validate_superuser_credentials(*, username: str, password: str) -> tuple[str, str]:
    normalized_username = username.strip()
    try:
        payload = UserAuthBody.model_validate(
            {
                "username": normalized_username,
                "password": password,
            }
        )
    except ValidationError as exc:
        messages: list[str] = []
        for error in exc.errors():
            location = ".".join(str(item) for item in error.get("loc", ())) or "credentials"
            message = error.get("msg", "Invalid value")
            messages.append(f"{location}: {message}")
        raise ValueError("; ".join(messages)) from exc
    return payload.username, payload.password


async def prompt_for_username(
    *,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> str:
    """
    Prompt the user for a unique username, ensuring it does not already exist.
    """
    while True:
        username = input("ENTER USERNAME: ").strip()
        if not username:
            _log_warning("Username cannot be empty. Please try again.")
            continue
        if await is_username_taken(username, session_factory=session_factory):
            _log_warning("User already exists. Please try again with a unique username.")
            continue
        return username


async def prompt_for_password() -> str:
    """
    Prompt the user for a password and confirmation, ensuring they match and aren't empty.
    """
    while True:
        password = getpass.getpass("ENTER PASSWORD: ")
        if not password:
            _log_warning("Password cannot be empty. Try again.")
            continue
        confirm_password = getpass.getpass("CONFIRM PASSWORD: ")
        if password != confirm_password:
            _log_warning("Passwords do not match, try again.")
            continue
        return password


async def create_super_user_prompt(
    *,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
):
    """
    Prompt the user to create a superuser and handle the creation accordingly.
    """
    confirm = input(
        "Superuser is not found. Do you want to create it? y(yes)/ANY(no): "
    ).strip().lower()
    if confirm == "y":
        username = await prompt_for_username(session_factory=session_factory)
        password = await prompt_for_password()
        superuser = await create_super_user(
            username=username,
            password=password,
            session_factory=session_factory,
        )
        _log_info(f"Superuser '{superuser.username}' created.")
    else:
        _log_info("Okay, bye! :)")


async def ensure_super_user_once(
    *,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
):
    """
    Ensures a superuser exists in the system, otherwise offers to create one.
    """
    exists = await is_super_user_exist(session_factory=session_factory)
    if not exists:
        await create_super_user_prompt(session_factory=session_factory)


async def create_super_user(
    username: str,
    password: str,
    *,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
):
    """
    Creates a superuser with explicit credentials.
    Raises ValueError on invalid input or username conflicts.
    """
    from src.auth.service import hash_password
    from src.user_role.models import User

    username, password = _validate_superuser_credentials(username=username, password=password)
    async with _session_scope_ctx(session_factory=session_factory) as session:
        await _ensure_superadmin_role_exists(session)
        existing_user_id = await session.scalar(select(User.id).where(User.username == username).limit(1))
        if existing_user_id is not None:
            raise ValueError("Username already exists.")

        superuser = User(
            username=username,
            password=hash_password(password),
            role_id=SUPERADMIN_ROLE_ID,
        )
        session.add(superuser)
        await session.flush()
        await session.commit()
    return superuser


async def ensure_super_user_with_credentials(
    username: str,
    password: str,
    *,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> bool:
    """
    Ensures a superuser exists using provided credentials (non-interactive).
    Returns True when a superuser was created, False when one already exists.
    """
    from src.auth.service import hash_password
    from src.user_role.models import User

    username, password = _validate_superuser_credentials(username=username, password=password)

    async with _session_scope_ctx(session_factory=session_factory) as session:
        await _ensure_superadmin_role_exists(session)
        superuser_exists = await session.scalar(
            select(User.id).where(User.role_id == SUPERADMIN_ROLE_ID).limit(1)
        )
        if superuser_exists is not None:
            _log_info("Superuser bootstrap skipped because a superuser already exists.")
            return False

        existing_username = await session.scalar(select(User.id).where(User.username == username).limit(1))
        if existing_username is not None:
            raise ValueError("Username already exists.")

        session.add(
            User(
                username=username,
                password=hash_password(password),
                role_id=SUPERADMIN_ROLE_ID,
            )
        )
        await session.commit()
        return True


async def ensure_super_user_from_env_if_enabled(
    *,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> bool:
    """
    Non-interactive startup bootstrap guarded by an explicit env flag.
    Returns True if a superuser was created.
    """
    if not _get_bool_env(ENV_BOOTSTRAP_ENABLE, False):
        return False

    username = os.getenv(ENV_BOOTSTRAP_USERNAME, "").strip()
    bootstrap_password = os.getenv(ENV_BOOTSTRAP_PASSWORD)
    if not username or not bootstrap_password:
        missing = []
        if not username:
            missing.append(ENV_BOOTSTRAP_USERNAME)
        if not bootstrap_password:
            missing.append(ENV_BOOTSTRAP_PASSWORD)
        _log_warning(
            "Superuser bootstrap requested but required credentials are missing. "
            f"Missing: {', '.join(missing)}."
        )
        return False

    password = bootstrap_password
    try:
        created = await ensure_super_user_with_credentials(
            username=username,
            password=password,
            session_factory=session_factory,
        )
    except ValueError as exc:
        _log_warning(f"Superuser bootstrap failed validation: {exc}")
        return False

    if not created:
        _log_info("Superuser was not created because one already exists.")
    return created


async def cli_create_super_user(
    *,
    username: Optional[str] = None,
    password: Optional[str] = None,
    interactive: bool = False,
    use_env: bool = False,
) -> int:
    """
    Admin CLI entrypoint for superuser creation outside the app lifespan.
    """
    if interactive:
        await ensure_super_user_once()
        return 0

    if use_env:
        created = await ensure_super_user_from_env_if_enabled()
        return 0 if created or await is_super_user_exist() else 1

    if not username:
        raise ValueError("CLI mode requires --username (or use --interactive / --from-env).")
    if password is None:
        password = getpass.getpass("ENTER PASSWORD: ")
        confirm_password = getpass.getpass("CONFIRM PASSWORD: ")
        if password != confirm_password:
            raise ValueError("Passwords do not match.")

    created = await ensure_super_user_with_credentials(username=username, password=password)
    if created:
        _log_info(f"Superuser '{username}' created.")
    else:
        _log_info("Superuser already exists. No changes made.")
    return 0


def build_super_user_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create or bootstrap a superuser.")
    parser.add_argument("--username", help="Superuser username (non-interactive mode).")
    parser.add_argument(
        "--password",
        help="Superuser password (non-interactive mode). If omitted, prompt securely.",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Run the old interactive prompt flow (outside app startup only).",
    )
    parser.add_argument(
        "--from-env",
        action="store_true",
        help=(
            f"Use {ENV_BOOTSTRAP_ENABLE}=true plus {ENV_BOOTSTRAP_USERNAME}/"
            f"{ENV_BOOTSTRAP_PASSWORD}."
        ),
    )
    return parser


def main() -> int:
    import asyncio

    parser = build_super_user_cli_parser()
    args = parser.parse_args()
    try:
        return asyncio.run(
            cli_create_super_user(
                username=args.username,
                password=args.password,
                interactive=args.interactive,
                use_env=args.from_env,
            )
        )
    except ValueError as exc:
        parser.error(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
