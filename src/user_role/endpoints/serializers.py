from src.user_role.models import Role, User


def serialize_role(role: Role) -> dict:
    return {
        "id": role.id,
        "name": role.name,
        "title_key": role.title_key,
        "permissions": role.permissions or {},
    }


def serialize_user(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "role_id": user.role_id,
        "permissions": user.permissions or {},
    }
