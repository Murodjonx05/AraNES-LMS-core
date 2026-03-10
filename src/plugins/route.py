from fastapi import APIRouter

from src.plugins.endpoints import plugins_router


plugins_route = APIRouter(prefix="/v1")
plugins_route.include_router(plugins_router)
