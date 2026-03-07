from dataclasses import dataclass
from enum import Enum

from fastapi import APIRouter, Depends

from src.auth.dependencies import require_access_token_payload
from src.auth.route import auth_closed_route, auth_opened_route
from src.i18n.route import i18n_route
from src.user_role.route import user_role_route


class RouteAccess(str, Enum):
    OPENED = "opened"
    CLOSED = "closed"


OPENED = RouteAccess.OPENED
CLOSED = RouteAccess.CLOSED


@dataclass(frozen=True, slots=True)
class RouteSpec:
    router: APIRouter
    access: RouteAccess = CLOSED


def _include_route(parent: APIRouter, spec: RouteSpec) -> None:
    include_kwargs = {}
    if spec.access is CLOSED:
        include_kwargs["dependencies"] = [Depends(require_access_token_payload)]
    parent.include_router(spec.router, **include_kwargs)


# This router contains all other routers.
all_routes = APIRouter(prefix="/api")

ROUTES: tuple[RouteSpec, ...] = (
    RouteSpec(router=auth_opened_route, access=OPENED),
    RouteSpec(router=auth_closed_route, access=CLOSED),
    RouteSpec(router=user_role_route),
    RouteSpec(router=i18n_route),
)

for route_spec in ROUTES:
    _include_route(all_routes, route_spec)


__all__ = ["RouteAccess", "OPENED", "CLOSED", "RouteSpec", "all_routes"]
