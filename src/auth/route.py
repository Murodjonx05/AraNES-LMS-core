from fastapi import APIRouter

from src.auth.endpoints.auth import auth_closed_router, auth_opened_router

auth_opened_route = APIRouter(
    prefix="/v1/auth",
    tags=["auth"],
)
auth_opened_route.include_router(auth_opened_router)

auth_closed_route = APIRouter(
    prefix="/v1/auth",
    tags=["auth"],
)
auth_closed_route.include_router(auth_closed_router)
