from fastapi import APIRouter
from src.user_role.endpoints.roles import roles_router
from src.user_role.endpoints.users import users_router
from src.user_role.endpoints.role_registry import role_registry_router

user_role_route = APIRouter(
    prefix="/v1/rbac",
)
user_role_route.include_router(roles_router)
user_role_route.include_router(users_router)
user_role_route.include_router(role_registry_router)
