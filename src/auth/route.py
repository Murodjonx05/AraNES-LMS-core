from fastapi import APIRouter

from src.auth.endpoints.auth import auth_router

auth_main_route = APIRouter(
    prefix="/v1/auth",
    tags=["auth"],
)
auth_main_route.include_router(auth_router)
