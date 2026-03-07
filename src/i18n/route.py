from fastapi import APIRouter
from src.i18n.endpoints import large_route, small_route

i18n_route = APIRouter(
    prefix="/v1/i18n",
)
i18n_route.include_router(small_route)
i18n_route.include_router(large_route)
