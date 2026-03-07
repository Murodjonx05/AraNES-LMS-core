from fastapi import APIRouter

from src.auth.endpoints.auth import auth_closed_router, auth_opened_router


def _build_auth_route(router: APIRouter) -> APIRouter:
    auth_route = APIRouter(
        prefix="/v1/auth",
        tags=["auth"],
    )
    auth_route.include_router(router)
    return auth_route


auth_opened_route = _build_auth_route(auth_opened_router)
auth_closed_route = _build_auth_route(auth_closed_router)
