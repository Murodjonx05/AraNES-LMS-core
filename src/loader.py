from fastapi import APIRouter

from src.auth.route import auth_main_route
from src.i18n.route import i18n_route
from src.user_role.route import user_role_route

# This router contains all other routers.
all_routes = APIRouter(prefix="/api")


all_routes.include_router(auth_main_route)
all_routes.include_router(user_role_route)
all_routes.include_router(i18n_route)
