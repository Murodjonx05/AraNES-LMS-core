from sqlalchemy import select
from src.user_role.defaults import SUPERADMIN_ROLE_ID
from src.database import session_scope
import getpass


async def is_super_user_exist() -> bool:
    """
    Checks if a superuser role already exists in the database.
    """
    from src.user_role.models import User

    async with session_scope() as session:
        stmt = select(User).where(User.role_id == SUPERADMIN_ROLE_ID)
        result = await session.execute(stmt)
        superuser = result.scalar_one_or_none()
        return bool(superuser)


async def prompt_for_username() -> str:
    """
    Prompt the user for a unique username, ensuring it does not already exist.
    """
    from src.user_role.models import User

    while True:
        username = input("ENTER USERNAME: ").strip()
        if not username:
            print("Username cannot be empty. Please try again.")
            continue
        async with session_scope() as session:
            stmt = select(User).where(User.username == username)
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()
            if user is not None:
                print("User already exists. Please try again with a unique username.")
                continue
            return username


async def prompt_for_password() -> str:
    """
    Prompt the user for a password and confirmation, ensuring they match and aren't empty.
    """
    while True:
        password = getpass.getpass("ENTER PASSWORD: ")
        if not password:
            print("Password cannot be empty. Try again.")
            continue
        confirm_password = getpass.getpass("CONFIRM PASSWORD: ")
        if password != confirm_password:
            print("Passwords do not match, try again.")
            continue
        return password


async def create_super_user_prompt():
    """
    Prompt the user to create a superuser and handle the creation accordingly.
    """
    from src.user_role.models import User
    from src.auth.service import hash_password

    confirm = input(
        "Superuser is not found. Do you want to create it? y(yes)/ANY(no): "
    ).strip().lower()
    if confirm == "y":
        username = await prompt_for_username()
        password = await prompt_for_password()
        superuser = User(
            username=username,
            password=hash_password(password),
            role_id=SUPERADMIN_ROLE_ID,
        )
        async with session_scope() as session:
            session.add(superuser)
            await session.flush()
            await session.commit()
        masked_password = '*' * len(password)
        print(
            f"Superuser '{superuser.username}' created with password: '{masked_password}'"
        )
    else:
        print("Okay, bye! :)")


async def ensure_super_user_once():
    """
    Ensures a superuser exists in the system, otherwise offers to create one.
    """
    exists = await is_super_user_exist()
    if not exists:
        await create_super_user_prompt()
